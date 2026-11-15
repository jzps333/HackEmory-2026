#!/usr/bin/env python3
"""Measure ScanSafe's scam verdicts on a labeled list of URLs.

Live run (sequential, one scan at a time; the sandbox is shared with the live demo):
    python scripts/eval_detection.py                       # every URL in eval/labeled_urls.csv
    python scripts/eval_detection.py --only scams --api https://api.scansafe.nyc
  -> per-URL verdicts, a confusion table, and raw results in eval/results-<timestamp>.json
     (screenshots stripped; gitignored).

Offline re-score (no scans): re-apply THIS checkout's verdict rule (api/scan.py judge() with
api/signals.py) to a saved live run. Jev's answers come from the saved run; domain age is looked
up again (RDAP); Gemini's second look runs only if GEMINI_API_KEY is set locally.
    python scripts/eval_detection.py --rescore eval/baseline.json
  Saved results don't carry the sandbox's raw form fields, page text or download list, so the
  re-score rebuilds what it can (see sandbox_from_result) and falls back to Jev's asks_* answers.

Labels: "scam" is correct when the verdict is malicious or suspicious; "safe" only when safe.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_API = "https://api.scansafe.nyc"
DEFAULT_CSV = ROOT / "eval" / "labeled_urls.csv"
SCAN_TIMEOUT_S = 120
FAILED_TEXT = "We couldn't finish checking"        # api.scan.failed_result's explanation
VERDICTS = ("malicious", "suspicious", "safe", "error")
KEEP = ("verdict", "jev_score", "scam_type", "domain", "final_url", "redirect_chain",
        "page_title", "checks", "explanation", "scan_ms")


def load_labels(path: Path) -> list[dict]:
    with open(path, newline="") as f:
        rows = [r for r in csv.DictReader(f) if (r.get("url") or "").strip()]
    for r in rows:
        r["url"], r["label"] = r["url"].strip(), r["label"].strip().lower()
        if r["label"] not in ("scam", "safe"):
            sys.exit(f"bad label {r['label']!r} for {r['url']}")
    return rows


def scan_one(client: httpx.Client, api: str, url: str) -> dict:
    """POST /scan for one URL -> a slim record (no screenshots)."""
    t0 = time.monotonic()
    rec: dict = {"error": None}
    try:
        r = client.post(f"{api.rstrip('/')}/scan", json={"url": url}, timeout=SCAN_TIMEOUT_S)
        rec["http_status"] = r.status_code
        r.raise_for_status()
        data = r.json()
        rec.update({k: data.get(k) for k in KEEP})
        if FAILED_TEXT in (data.get("explanation") or ""):
            rec["error"] = "sandbox_failed"     # verdict is the "suspicious" fallback
    except (httpx.HTTPError, ValueError) as e:
        rec.update(verdict="error", error=f"{type(e).__name__}: {str(e)[:150]}")
    rec["elapsed_s"] = round(time.monotonic() - t0, 1)
    return rec


def correct(label: str, verdict: str) -> bool:
    return verdict in ("malicious", "suspicious") if label == "scam" else verdict == "safe"


def confusion(rows: list[dict], key: str = "verdict") -> str:
    lines = [f"{'':14}" + "".join(f"{v:>12}" for v in VERDICTS)]
    for label in ("scam", "safe"):
        sub = [r for r in rows if r["label"] == label]
        counts = [sum(1 for r in sub if (r.get(key) or "error") == v) for v in VERDICTS]
        lines.append(f"{label + f' ({len(sub)})':14}" + "".join(f"{c:>12}" for c in counts))
    m = metrics(rows, key)
    lines.append(f"accuracy {m['correct']}/{m['n']} = {m['accuracy']:.1%}   "
                 f"false positives (safe flagged) {m['fp']}   "
                 f"false negatives (scam called safe) {m['fn']}   "
                 f"scams blocked as malicious {m['scam_malicious']}/{m['n_scam']}")
    return "\n".join(lines)


def metrics(rows: list[dict], key: str = "verdict") -> dict:
    n = len(rows)
    ok = sum(1 for r in rows if correct(r["label"], r.get(key) or "error"))
    return {
        "n": n, "correct": ok, "accuracy": ok / n if n else 0.0,
        "fp": sum(1 for r in rows if r["label"] == "safe" and r.get(key) != "safe"),
        "fn": sum(1 for r in rows if r["label"] == "scam" and r.get(key) == "safe"),
        "n_scam": sum(1 for r in rows if r["label"] == "scam"),
        "scam_malicious": sum(1 for r in rows if r["label"] == "scam" and r.get(key) == "malicious"),
    }


def short(url: str, n: int = 58) -> str:
    u = url.replace("https://scansafe-demo-sites.vercel.app", "demo:").replace("https://", "")
    return u if len(u) <= n else u[: n - 1] + "~"


def print_rows(rows: list[dict]) -> None:
    for r in rows:
        mark = "ok " if correct(r["label"], r.get("verdict") or "error") else "BAD"
        print(f"{mark} {r['label']:4} {(r.get('verdict') or 'error'):10} "
              f"{(r.get('jev_score') if r.get('jev_score') is not None else ''):>5} "
              f"{(r.get('scam_type') or ''):20} {short(r['url'])}"
              + (f"  [{r['error']}]" if r.get("error") else ""))


def run_live(args) -> None:
    labels = load_labels(Path(args.csv))
    if args.only:
        labels = [r for r in labels if args.only in r["url"]]
    started = datetime.now()
    out_path = ROOT / "eval" / f"results-{started:%Y%m%d-%H%M%S}.json"
    rows = []
    print(f"Scanning {len(labels)} URLs one at a time via {args.api} ...", flush=True)
    with httpx.Client(headers={"user-agent": "scansafe-eval/1"}) as client:
        for i, lab in enumerate(labels, 1):
            rec = {"url": lab["url"], "label": lab["label"], "note": lab.get("note", "")}
            rec.update(scan_one(client, args.api, lab["url"]))
            rows.append(rec)
            print(f"[{i}/{len(labels)}] {rec.get('verdict') or 'error':10} "
                  f"{rec.get('elapsed_s')}s {short(lab['url'])}", flush=True)
            out_path.write_text(json.dumps({"api": args.api, "started": started.isoformat(),
                                            "results": rows}, indent=1))
            if i < len(labels):
                time.sleep(args.delay)
    print()
    print_rows(rows)
    print()
    print(confusion(rows))
    print(f"\nraw results: {out_path.relative_to(ROOT)}")


# ---------- offline re-score with this checkout's rule ----------

FLOOR = 0.5   # config.SECOND_LOOK_SCORE on the live server


def sandbox_from_result(r: dict) -> tuple[dict, list[str]]:
    """Best-effort sandbox dict rebuilt from a saved ScanResult, plus what had to be assumed.
    Not in ScanResult, so inferred: downloads (scam_type malware_download, or the explanation
    mentions a download), the robot check (the explanation mentions one), and a blocked frame
    (the old rule's 0.5 floor on a page Jev called safe, with no robot check: the block reason
    isn't saved, so it is assumed routine, as seen locally on chase.com). form_fields and
    page_text are unknown (empty), so Jev's asks_* answers stand in for form fields."""
    expl = (r.get("explanation") or "").lower()
    checks = r.get("checks") or {}
    download = r.get("scam_type") == "malware_download" or "download" in expl
    bot = "robot check" in expl or "verify you are human" in expl
    assumed = []
    blocked = []
    if (r.get("verdict") == "suspicious" and r.get("jev_score") == FLOOR and not bot
            and not download and (checks.get("malicious_p") or 0) < FLOOR
            and (checks.get("prompt_injection_p") or 0) < 0.5):
        blocked = [{"type": "document", "reason": "(reason not saved in ScanResult)"}]
        assumed.append("old 0.5 floor came from a blocked frame with a routine reason")
    return {
        "url": r["url"], "final_url": r.get("final_url"), "domain": r.get("domain"),
        "redirect_chain": r.get("redirect_chain") or [], "page_title": r.get("page_title") or "",
        "page_text": "", "form_fields": [], "downloads": ["(inferred)"] if download else [],
        "bot_check": {"detected": bot, "kind": "text" if bot else None},
        "blocked_requests": blocked,
    }, assumed


def run_rescore(args) -> None:
    sys.path.insert(0, str(ROOT))
    from api import scan as api_scan
    from api import signals
    from api.schema import JevChecks

    data = json.loads(Path(args.rescore).read_text())
    rows = data["results"]
    if args.only:
        rows = [r for r in rows if args.only in r["url"]]
    after = []
    for r in rows:
        new = dict(r)
        if r.get("verdict") in (None, "error") or r.get("error") == "sandbox_failed":
            after.append(new)          # nothing was checked; the fallback stays as it was
            continue
        sandbox, assumed = sandbox_from_result(r)
        sandbox["redirect_chain"] = signals.clean_chain(sandbox["redirect_chain"])
        checks = JevChecks(**(r.get("checks") or {}))
        sig = signals.collect(sandbox, checks)
        verdict, score, scam_type, sig = api_scan.judge(sandbox, checks, sig)
        _, fired = signals.score_adjustment(sig)
        new.update(verdict=verdict, jev_score=score, scam_type=scam_type,
                   redirect_chain=sandbox["redirect_chain"], rules=fired, assumed=assumed,
                   reasons=[text for _, text in sig.facts()],
                   hop_fact=signals.hop_fact(sig, sandbox.get("domain")),
                   age_days=sig.age_days)
        after.append(new)

    print("BEFORE (live run):")
    print(confusion(rows))
    print("\nAFTER (this checkout's rule, re-scored offline):")
    print(confusion(after))
    print("\nPer-URL:")
    for b, a in zip(rows, after):
        changed = b.get("verdict") != a.get("verdict")
        mark = "ok " if correct(a["label"], a.get("verdict") or "error") else "BAD"
        print(f"{mark} {a['label']:4} {(b.get('verdict') or 'error'):10} {b.get('jev_score', ''):>5} -> "
              f"{(a.get('verdict') or 'error'):10} {a.get('jev_score', ''):>5} "
              f"{'*' if changed else ' '} {short(a['url'])}"
              + (f"  rules: {', '.join(a['rules'])}" if a.get("rules") else ""))
        if args.verbose:
            for why in (a.get("assumed") or []):
                print(f"        assumed: {why}")
            for why in (a.get("reasons") or []):
                print(f"        - {why}")
            if a.get("hop_fact"):
                print(f"        hops: {a['hop_fact']}")
    if args.save:
        Path(args.save).write_text(json.dumps({"rescored_from": args.rescore,
                                               "results": after}, indent=1))
        print(f"\nsaved: {args.save}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--api", default=DEFAULT_API, help="backend base URL (default: live)")
    ap.add_argument("--csv", default=str(DEFAULT_CSV), help="labeled URLs (url,label,note)")
    ap.add_argument("--only", help="only URLs containing this text")
    ap.add_argument("--delay", type=float, default=1.0, help="seconds between scans")
    ap.add_argument("--rescore", metavar="RESULTS_JSON",
                    help="re-score a saved run offline with this checkout's rule (no scans)")
    ap.add_argument("--save", help="with --rescore: write the re-scored results here")
    ap.add_argument("-v", "--verbose", action="store_true", help="with --rescore: show reasons")
    args = ap.parse_args()
    run_rescore(args) if args.rescore else run_live(args)


if __name__ == "__main__":
    main()
