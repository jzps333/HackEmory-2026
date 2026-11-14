"""Backfill the Typesense `scans` collection from Tiger Data: `python3 -m data.sync_scans [--prune]`.

Reads every row of the Tiger `scans` table and emplaces it into Typesense in batches. Idempotent:
doc ids are a hash of the row (data/scan_search.py), so a re-run updates the same documents and
keeps the url/explanation/location that live scans and reports added. `--prune` also deletes
documents whose row is gone from Tiger (e.g. after deleting test scans there).

Prints counts only, never keys or connection strings.
"""
from __future__ import annotations

import sys
from collections.abc import Iterator

from data import scan_search, tiger_store, typesense_store

BATCH = 500
SELECT_SQL = "SELECT time, domain, verdict, scam_type, jev_score, scan_ms FROM scans ORDER BY time"


def tiger_batches(batch: int = BATCH) -> Iterator[list[dict]]:
    with tiger_store._connect() as conn:
        cur = conn.execute(SELECT_SQL)
        while True:
            rows = cur.fetchmany(batch)
            if not rows:
                return
            yield rows


def sync(batch: int = BATCH, prune: bool = False) -> dict:
    created = scan_search.ensure_collection()
    rows, ok, errors, ids = 0, 0, [], set()
    for chunk in tiger_batches(batch):
        docs = [scan_search.row_document(r) for r in chunk]
        rows += len(chunk)
        ids.update(d["id"] for d in docs)
        good, bad = scan_search.import_documents(docs)
        ok += good
        errors.extend(bad)
    pruned = scan_search.delete_ids(scan_search.all_ids() - ids) if prune else 0
    return {"created_collection": created, "rows": rows, "docs": len(ids), "ok": ok,
            "failed": len(errors), "errors": errors[:3], "pruned": pruned,
            "num_documents": scan_search.count()}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not tiger_store.is_configured():
        print("SKIP Tiger Data: not configured (see data/README.md for env vars)")
        return 1
    if not typesense_store.is_configured():
        print("SKIP Typesense: not configured (see data/README.md for env vars)")
        return 1
    try:
        s = sync(prune="--prune" in argv)
    except Exception as e:  # error type only; messages can echo URLs with secrets
        status = getattr(getattr(e, "response", None), "status_code", None)
        print(f"FAIL sync_scans: {type(e).__name__}{f' (HTTP {status})' if status else ''}")
        return 1
    print(f"{'OK  ' if not s['failed'] else 'FAIL'} synced {s['rows']} Tiger rows -> {s['docs']} docs "
          f"({s['ok']} written, {s['failed']} failed, {s['pruned']} pruned); "
          f"Typesense `scans` now has {s['num_documents']} docs"
          f"{' (collection created)' if s['created_collection'] else ''}")
    for err in s["errors"]:
        print(f"     error: {err}")
    return 0 if not s["failed"] else 1


if __name__ == "__main__":
    sys.exit(main())
