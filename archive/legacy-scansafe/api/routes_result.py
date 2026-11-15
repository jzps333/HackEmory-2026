"""The result of one finished check.

GET /result/{scan_id}  JSON, for the app.
GET /r/{scan_id}       the page linked from the follow-up text (served here, so it works without the
                       web app having a /r route). Safe: a button to the real site. Suspicious or
                       scam: no link to the site, a button to report it instead.
"""
from __future__ import annotations

import html
import time
from typing import Optional
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from api import result_store
from api.schema import ScanResult

router = APIRouter()

REPORT_URL = "https://reportfraud.ftc.gov/"      # the FTC's official fraud report form
VERDICT_VIEW = {
    "safe": ("Looks safe", "#0ae448", "#04160a",
             "We opened this link in a locked-down browser and didn't find signs of a scam."),
    "suspicious": ("Be careful", "#f5a524", "#1a1203",
                   "Something about this link looked off. Don't pay or sign in unless you're sure."),
    "malicious": ("Likely a scam", "#e5484d", "#1a0506",
                  "Don't pay, sign in, or type anything on this page."),
}
ERROR_VIEW = ("Couldn't finish the check", "#8b8d98", "#111113",
              "We couldn't finish checking this link. Please don't pay or type anything on it for now.")
SCAM_TYPES = {
    "fake_bank": "Fake bank page",
    "fake_payment_app": "Fake payment app",
    "fake_parking_or_toll": "Fake parking or toll payment",
    "fake_delivery": "Fake delivery fee",
    "fake_government": "Fake government page",
    "tech_support": "Fake tech support",
    "fake_login_other": "Fake sign-in page",
    "malware_download": "Harmful download",
    "other": "Scam",
}
HEADERS = {
    # Only our own inline styles and the page picture; no scripts at all.
    "Content-Security-Policy": "default-src 'none'; img-src data: https:; style-src 'unsafe-inline'; "
                               "base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "private, max-age=60",
}


@router.get("/result/{scan_id}", response_model=ScanResult)
def get_result(scan_id: str) -> ScanResult:
    result = result_store.get(scan_id)
    if result is None:
        raise HTTPException(status_code=404, detail="We couldn't find this check. It may have expired.")
    return result


def _site_link(result: ScanResult) -> Optional[str]:
    """Where "Continue" goes: the page it ended up on, only for http(s)."""
    for u in (result.final_url, result.url):
        try:
            parts = urlsplit(u or "")
        except ValueError:
            continue
        if parts.scheme in ("http", "https") and parts.hostname:
            return u
    return None


def _picture(result: ScanResult) -> Optional[str]:
    for s in result.screenshots or []:
        if isinstance(s, str) and (s.startswith("https://") or s.startswith("data:image/jpeg;base64,")
                                   or s.startswith("data:image/png;base64,")):
            return s
    return None


def _page(title: str, body: str, accent: str, tint: str, status: int = 200) -> HTMLResponse:
    e = html.escape
    doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="robots" content="noindex">
<title>{e(title)} · ScanSafe</title>
<style>
:root {{ --accent: {accent}; --tint: {tint}; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: #000; color: #f4f4f5; font: 17px/1.5 -apple-system, BlinkMacSystemFont,
       "SF Pro Text", "Segoe UI", Roboto, sans-serif; -webkit-text-size-adjust: 100%; }}
main {{ max-width: 520px; margin: 0 auto; padding: 20px 16px 40px; }}
.brand {{ font-weight: 800; letter-spacing: -0.02em; font-size: 20px; margin: 4px 0 22px; }}
.brand span {{ color: #0ae448; }}
.card {{ background: var(--tint); border: 2px solid var(--accent); border-radius: 22px; padding: 22px 20px; }}
.badge {{ display: inline-block; background: var(--accent); color: #000; font-weight: 800; font-size: 13px;
         letter-spacing: 0.06em; text-transform: uppercase; padding: 5px 10px; border-radius: 999px; }}
h1 {{ font-size: 34px; line-height: 1.1; letter-spacing: -0.03em; margin: 14px 0 8px; color: var(--accent); }}
.lede {{ margin: 0; color: #e4e4e7; }}
.meta {{ margin: 16px 0 0; padding: 0; list-style: none; color: #a1a1aa; font-size: 15px; }}
.meta li {{ padding: 6px 0; border-top: 1px solid #27272a; overflow-wrap: anywhere; }}
.meta b {{ color: #f4f4f5; font-weight: 600; }}
.why {{ margin: 18px 0 0; color: #d4d4d8; }}
.shot {{ display: block; width: 100%; margin-top: 18px; border-radius: 14px; border: 1px solid #27272a; }}
.btn {{ display: block; text-align: center; text-decoration: none; font-weight: 700; font-size: 18px;
       min-height: 52px; padding: 14px 18px; border-radius: 14px; margin-top: 14px; }}
.primary {{ background: var(--accent); color: #000; }}
.secondary {{ background: #18181b; color: #f4f4f5; border: 1px solid #3f3f46; }}
.note {{ color: #71717a; font-size: 14px; margin-top: 22px; }}
</style></head>
<body><main>
<div class="brand">Scan<span>Safe</span></div>
{body}
<p class="note">Checked in a locked-down browser on our side. Nothing ran on your phone.</p>
</main></body></html>"""
    return HTMLResponse(doc, status_code=status, headers=HEADERS)


@router.get("/r/{scan_id}", response_class=HTMLResponse)
def result_page(scan_id: str) -> HTMLResponse:
    e = html.escape
    result = result_store.get(scan_id)
    if result is None:
        title, accent, tint, lede = ERROR_VIEW
        body = (f'<section class="card"><span class="badge">Not found</span>'
                f"<h1>We couldn't find this check</h1><p class=\"lede\">It may have expired (we keep "
                f"checks for a week). Scan the code again in ScanSafe to check it now.</p></section>")
        return _page("Check not found", body, accent, tint, status=404)

    title, accent, tint, lede = VERDICT_VIEW.get(result.verdict, ERROR_VIEW)
    rows = []
    if result.domain:
        rows.append(f"<li>Website <b>{e(result.domain)}</b></li>")
    if result.scam_type and result.scam_type != "none" and result.verdict != "safe":
        rows.append(f"<li>Looks like <b>{e(SCAM_TYPES.get(result.scam_type, result.scam_type.replace('_', ' ')))}</b></li>")
    if result.flagged_before:
        rows.append(f"<li>Reported nearby <b>{int(result.flagged_before)} time(s)</b> before</li>")
    if result.scanned_at:
        when = time.strftime("%b %d, %Y %H:%M UTC", time.gmtime(int(result.scanned_at)))
        rows.append(f"<li>Checked <b>{e(when)}</b></li>")
    why = f'<p class="why">{e(result.explanation)}</p>' if result.explanation and result.verdict in VERDICT_VIEW else ""
    pic = _picture(result)
    shot = f'<img class="shot" src="{e(pic, quote=True)}" alt="What the page looked like">' if pic else ""

    actions = ""
    link = _site_link(result)
    if result.verdict == "safe" and link:
        actions = (f'<a class="btn primary" href="{e(link, quote=True)}" rel="noopener noreferrer">'
                   f"Continue to {e(result.domain or 'the site')}</a>")
    elif result.verdict in ("malicious", "suspicious"):
        actions = (f'<a class="btn primary" href="{REPORT_URL}" rel="noopener noreferrer">Report this scam</a>'
                   f'<a class="btn secondary" href="https://www.ic3.gov/" rel="noopener noreferrer">'
                   f"Report to the FBI (IC3)</a>")

    body = (f'<section class="card"><span class="badge">{e(title)}</span><h1>{e(title)}</h1>'
            f'<p class="lede">{e(lede)}</p><ul class="meta">{"".join(rows)}</ul>{why}{shot}</section>'
            f"{actions}")
    return _page(title, body, accent, tint)
