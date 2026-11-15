"""Research agent jobs (plugins/research; the engine is api/research.py).

Agent only (header X-Agent-Key = AGENT_INTERNAL_KEY), JSON:
  POST /research/start  {"phone": "+1...", "topic": "<=300 chars", "details": "<=1000 chars"}
                        -> {"job_id": "<12 hex>", "status": "queued"}
                        Only while the "research" plugin is verified and gets the research tool.
                        One running job per phone: 409 job_running with that job_id.
  POST /research/search {"phone": "+1...", "q": "<=200 chars, may be empty"}
                        -> {"reports": [{"job_id", "topic", "summary", "at", "page_url"}] (top 3,
                            this caller's own only; empty q: the latest), "engine"}
                        Same checks as start. Typesense `research_reports`, else a substring match
                        over the stored jobs.
  GET  /research/{job_id}
                        -> {"job_id", "status", "topic", "details", "started_at", "finished_at",
                            "progress": [{"at", "note"}], "report": null | {...}, "page_url",
                            "reason"}
Errors: {"ok": false, "error", "message"}.

Public (the token is the secret, linked from the "done" text):
  GET  /research/r/{token}   the results page (HTML, no scripts, strict CSP); unknown -> 404 page
"""
from __future__ import annotations

import asyncio
import html
import re
import time
from typing import Any, Optional
from urllib.parse import urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from api import config
from api import plugins_index as pi
from api import research
from api.dogwood import _agent_ok
from api.routes_call import PHONE_RE
from api.routes_memory import _e164
from api.routes_result import HEADERS as PAGE_HEADERS

router = APIRouter()
PLUGIN_ID = TOOL = "research"


def _error(status: int, code: str, message: str, **extra: Any) -> JSONResponse:
    return JSONResponse({"ok": False, "error": code, "message": message, **extra}, status_code=status,
                        headers={"Cache-Control": "no-store"})


def _research_allowed() -> Optional[JSONResponse]:
    plugins, _ = pi.load_plugins(pi.PLUGINS_DIR)
    p = next((p for p in plugins if p.id == PLUGIN_ID), None)
    if p is None:
        return _error(404, "unknown_plugin", "The research plugin isn't installed on this server.")
    if not p.verified or TOOL not in pi.effective_tools(p):
        return _error(403, "tool_not_allowed", "Only the verified research plugin can start research.")
    return None


def _text_field(body: dict, key: str, limit: int, required: bool) -> tuple[Optional[str], Optional[str]]:
    """(cleaned value, error message)."""
    v = body.get(key)
    if v is None and not required:
        return "", None
    if not isinstance(v, str):
        return None, f"{key} must be text"
    v = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", " ", v)
    v = re.sub(r"\s+", " ", v).strip()
    if required and not v:
        return None, f"{key} is required"
    if len(v) > limit:
        return None, f"{key} must be at most {limit} characters"
    return v, None


async def _agent_request(request: Request):
    """(phone, body) for an agent call from the verified research plugin, or a JSONResponse."""
    bad = _agent_ok(request)
    if bad is not None:
        return bad
    bad = await asyncio.to_thread(_research_allowed)
    if bad is not None:
        return bad
    try:
        body = await request.json()
    except ValueError:
        return _error(400, "bad_json", "Send a JSON body.")
    if not isinstance(body, dict):
        return _error(400, "bad_json", "Send a JSON object.")
    phone = _e164(body.get("phone"))
    if phone is None or not PHONE_RE.match(phone):
        return _error(400, "bad_phone", "The caller's phone number (E.164, like +14045550123) is required.")
    return phone, body


@router.post("/research/start")
async def research_start(request: Request):
    got = await _agent_request(request)
    if isinstance(got, JSONResponse):
        return got
    phone, body = got
    topic, err = _text_field(body, "topic", research.TOPIC_MAX, True)
    if err:
        return _error(400, "bad_topic", f"The topic {err.split(' ', 1)[1]}.")
    details, err = _text_field(body, "details", research.DETAILS_MAX, False)
    if err:
        return _error(400, "bad_details", f"The details {err.split(' ', 1)[1]}.")
    if not config.GEMINI_API_KEY:
        return _error(503, "research_not_configured", "Research isn't set up on the server (no Gemini key).")
    try:
        job = await asyncio.to_thread(research.start, phone, topic, details)
    except research.JobRunning as e:
        return _error(409, "job_running", "Research for this caller is already running.", job_id=e.job_id)
    except research.TooBusy:
        return _error(429, "busy", "Too many research jobs are running right now. Try again in a few minutes.")
    return JSONResponse({"job_id": job["job_id"], "status": job["status"]},
                        headers={"Cache-Control": "no-store"})


@router.post("/research/search")
async def research_search(request: Request):
    got = await _agent_request(request)
    if isinstance(got, JSONResponse):
        return got
    phone, body = got
    q, err = _text_field(body, "q", 200, False)
    if err:
        return _error(400, "bad_query", f"The search {err.split(' ', 1)[1]}.")
    reports, engine = await asyncio.to_thread(research.library, phone, q)
    return JSONResponse({"reports": reports, "engine": engine}, headers={"Cache-Control": "no-store"})


@router.get("/research/r/{token}", response_class=HTMLResponse)
async def research_page(token: str) -> HTMLResponse:
    job = await asyncio.to_thread(research.get_by_token, token)
    if job is None or not isinstance(job.get("report"), dict):
        return _page("Report not found",
                     "<h1>We couldn't find this report</h1><p class=\"lede\">The link may be wrong "
                     "or the report may have been removed. Call the research agent to start a new one.</p>",
                     status=404)
    return _page(job["topic"], _report_html(job))


@router.get("/research/{job_id}")
async def research_status(job_id: str, request: Request):
    bad = _agent_ok(request)
    if bad is not None:
        return bad
    job = await asyncio.to_thread(research.get_job, job_id)
    if job is None:
        return _error(404, "unknown_job", "No research job with that id.")
    return JSONResponse(research.public(job), headers={"Cache-Control": "no-store"})


# --- the results page ------------------------------------------------------------------------------

def _link(url: Any) -> Optional[str]:
    """``url`` when it is a plain http(s) link with a host, else None (never linked)."""
    if not isinstance(url, str) or len(url) > 2000:
        return None
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    return url.strip() if parts.scheme in ("http", "https") and parts.hostname else None


def _paragraphs(text: Any) -> str:
    e = html.escape
    return "".join(f"<p>{e(p.strip())}</p>" for p in str(text or "").split("\n") if p.strip())


def _report_html(job: dict) -> str:
    e = html.escape
    rep = job["report"]
    when = ""
    if job.get("finished_at"):
        when = time.strftime("%b %d, %Y %H:%M UTC", time.gmtime(int(job["finished_at"])))
    out = [f'<h1>{e(job["topic"])}</h1>',
           f'<p class="when">Researched {e(when)}</p>' if when else "",
           f'<section class="card summary"><h2>Summary</h2>{_paragraphs(rep.get("summary"))}</section>']
    for s in rep.get("sections") or []:
        if isinstance(s, dict):
            out.append(f'<section class="card"><h2>{e(str(s.get("title") or ""))}</h2>'
                       f'{_paragraphs(s.get("body"))}</section>')
    steps = [x for x in rep.get("next_steps") or [] if isinstance(x, str) and x.strip()]
    if steps:
        out.append('<section class="card"><h2>Next steps</h2><ul>'
                   + "".join(f"<li>{e(x)}</li>" for x in steps) + "</ul></section>")
    items = []
    for src in rep.get("sources") or []:
        if not isinstance(src, dict):
            continue
        url = _link(src.get("url"))
        title = str(src.get("title") or "").strip()
        if url:
            label = title or (urlsplit(url).hostname or url)
            study = ""
            if src.get("kind") == "paper":
                meta = str(src.get("meta") or "").strip()
                study = ('<br><span class="study">Study</span> '
                         f'<span class="meta">{e(meta)}</span>' if meta else '<br><span class="study">Study</span>')
            items.append(f'<li><a href="{e(url, quote=True)}" rel="noopener noreferrer">{e(label)}</a>{study}</li>')
        elif title:
            items.append(f"<li>{e(title)}</li>")      # not a web link: shown, never linked
    if items:
        out.append('<section class="card"><h2>Sources</h2><ol class="sources">' + "".join(items)
                   + "</ol></section>")
    return "".join(out)


def _page(title: str, body: str, status: int = 200) -> HTMLResponse:
    e = html.escape
    doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="robots" content="noindex">
<title>{e(title)} · Toolstone research</title>
<style>
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: #000; color: #f4f4f5; font: 17px/1.55 -apple-system, BlinkMacSystemFont,
       "SF Pro Text", "Segoe UI", Roboto, sans-serif; -webkit-text-size-adjust: 100%; }}
main {{ max-width: 640px; margin: 0 auto; padding: 20px 16px 40px; }}
.brand {{ font-weight: 800; letter-spacing: -0.02em; font-size: 18px; margin: 4px 0 22px; color: #a1a1aa; }}
.brand span {{ color: #0ae448; }}
h1 {{ font-size: 30px; line-height: 1.15; letter-spacing: -0.03em; margin: 0 0 6px; overflow-wrap: anywhere; }}
.when {{ color: #a1a1aa; font-size: 15px; margin: 0 0 18px; }}
.lede {{ color: #d4d4d8; }}
.card {{ background: #111113; border: 1px solid #27272a; border-radius: 18px; padding: 18px; margin-top: 14px; }}
.summary {{ border-color: #0ae448; }}
h2 {{ font-size: 19px; margin: 0 0 8px; letter-spacing: -0.01em; }}
p {{ margin: 0 0 10px; color: #e4e4e7; overflow-wrap: anywhere; }}
ul, ol {{ margin: 0; padding-left: 22px; }}
li {{ margin: 6px 0; color: #e4e4e7; overflow-wrap: anywhere; }}
a {{ color: #7cc4ff; }}
.study {{ display: inline-block; font-size: 12px; font-weight: 700; color: #000; background: #0ae448; border-radius: 6px; padding: 1px 6px; margin-top: 4px; }}
.meta {{ color: #a1a1aa; font-size: 14px; }}
.note {{ color: #71717a; font-size: 14px; margin-top: 22px; }}
</style></head>
<body><main>
<div class="brand">Toolstone · <span>Research agent</span></div>
{body}
<p class="note">Researched by Gemini with published studies (OpenAlex) and Google Search. Check important facts before acting on them.</p>
</main></body></html>"""
    headers = {**PAGE_HEADERS, "Cache-Control": "private, no-store", "X-Robots-Tag": "noindex"}
    return HTMLResponse(doc, status_code=status, headers=headers)
