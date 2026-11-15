"""Memory and flashcards for community plugins ("apps": skills that remember).

Agent only (header X-Agent-Key = AGENT_INTERNAL_KEY). All POST so the phone never sits in a URL:
  POST /plugins/{id}/memory/put        {"phone", "key", "data"}       -> {"ok": true}
  POST /plugins/{id}/memory/list       {"phone", "prefix", "limit"}   -> {"records": [...]}
  POST /plugins/{id}/flashcards/add    {"phone", "front", "back"}     -> {"card", "due", "total"}
  POST /plugins/{id}/flashcards/next   {"phone"}                      -> {"card"|null, "due", "total"}
  POST /plugins/{id}/flashcards/grade  {"phone", "card_id", "correct"} -> {"card", "due", "total"}
The plugin must exist, be VERIFIED, and list the tool (memory / flashcards).

Signed-in person (phone sign-in token, Bearer or the ss_session cookie):
  GET /me/apps            -> {"apps": [{"plugin_id", "name", "summary", "records", "updated_at", "kind"}]}
  GET /me/apps/{id}       -> {"plugin", "records" (newest first, <=100), "flashcards": {...}|null}

Records are keyed by phone_hash(phone): the number itself is never stored or logged.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from api import plugins_index as pi
from api import session
from api.dogwood import _agent_ok
from data import plugin_memory as mem

router = APIRouter()


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"ok": False, "error": code, "message": message}, status_code=status)


def _e164(phone: Any) -> Optional[str]:
    if not isinstance(phone, str):
        return None
    digits = re.sub(r"[^\d+]", "", phone.strip())
    if re.fullmatch(r"\d{10}", digits):
        digits = "+1" + digits
    elif re.fullmatch(r"1\d{10}", digits):
        digits = "+" + digits
    return digits if re.fullmatch(r"\+\d{8,15}", digits) else None


def _owner(phone: str) -> str:
    from api.account_crypto import phone_hash
    return phone_hash(phone)


def _plugin(plugin_id: str) -> Optional[pi.Plugin]:
    if not isinstance(plugin_id, str) or not pi.ID_RE.fullmatch(plugin_id):
        return None
    plugins, _ = pi.load_plugins(pi.PLUGINS_DIR)
    return next((p for p in plugins if p.id == plugin_id), None)


async def _agent_call(request: Request, plugin_id: str, tool: str):
    """(plugin, owner, body) or a JSONResponse error."""
    bad = _agent_ok(request)
    if bad is not None:
        return bad
    p = _plugin(plugin_id)
    if p is None:
        return _error(404, "unknown_plugin", "No plugin with that id.")
    if not p.verified or tool not in pi.effective_tools(p):
        return _error(403, "tool_not_allowed", f"This plugin can't use {tool}.")
    try:
        body = await request.json()
    except ValueError:
        return _error(400, "bad_json", "Send a JSON body.")
    if not isinstance(body, dict):
        return _error(400, "bad_json", "Send a JSON object.")
    phone = _e164(body.get("phone"))
    if phone is None:
        return _error(400, "bad_phone", "A caller phone number is required.")
    return p, _owner(phone), body


def _deck_reply(p: pi.Plugin, owner: str, card: Optional[dict]) -> dict:
    d = mem.deck(p.id, owner)
    return {"card": card, "due": d["due"], "total": d["total"]}


@router.post("/plugins/{plugin_id}/memory/put")
async def memory_put(plugin_id: str, request: Request):
    got = await _agent_call(request, plugin_id, "memory")
    if isinstance(got, JSONResponse):
        return got
    p, owner, body = got
    try:
        mem.put(p.id, owner, body.get("key"), body.get("data"))
    except mem.MemoryError_ as e:
        return _error(400, "bad_record", str(e))
    return {"ok": True}


@router.post("/plugins/{plugin_id}/memory/list")
async def memory_list(plugin_id: str, request: Request):
    got = await _agent_call(request, plugin_id, "memory")
    if isinstance(got, JSONResponse):
        return got
    p, owner, body = got
    try:
        limit = int(body.get("limit") or 20)
    except (TypeError, ValueError):
        limit = 20
    return {"records": mem.list_records(p.id, owner, str(body.get("prefix") or ""), max(1, min(limit, 100)))}


@router.post("/plugins/{plugin_id}/flashcards/add")
async def flashcards_add(plugin_id: str, request: Request):
    got = await _agent_call(request, plugin_id, "flashcards")
    if isinstance(got, JSONResponse):
        return got
    p, owner, body = got
    try:
        card = mem.add_card(p.id, owner, str(body.get("front") or ""), str(body.get("back") or ""))
    except mem.MemoryError_ as e:
        return _error(400, "bad_card", str(e))
    return _deck_reply(p, owner, card)


@router.post("/plugins/{plugin_id}/flashcards/next")
async def flashcards_next(plugin_id: str, request: Request):
    got = await _agent_call(request, plugin_id, "flashcards")
    if isinstance(got, JSONResponse):
        return got
    p, owner, _ = got
    return _deck_reply(p, owner, mem.next_card(p.id, owner))


@router.post("/plugins/{plugin_id}/flashcards/grade")
async def flashcards_grade(plugin_id: str, request: Request):
    got = await _agent_call(request, plugin_id, "flashcards")
    if isinstance(got, JSONResponse):
        return got
    p, owner, body = got
    card = mem.grade_card(p.id, owner, body.get("card_id"), bool(body.get("correct") is True))
    if card is None:
        return _error(404, "unknown_card", "No card with that id.")
    return _deck_reply(p, owner, card)


# --- the signed-in person's own data ---------------------------------------------------------------

def _kind(p: Optional[pi.Plugin]) -> str:
    if p is None:
        return "notes"
    if "flashcards" in p.tools:
        return "flashcards"
    return "sessions" if "screen" in p.tools and "camera" in p.tools else "notes"


@router.get("/me/apps")
def my_apps(request: Request):
    phone = session.current_phone(request)
    if not phone:
        return _error(401, "signed_out", "Sign in with your phone number first.")
    owner = _owner(phone)
    plugins, _ = pi.load_plugins(pi.PLUGINS_DIR)
    by_id = {p.id: p for p in plugins}
    apps = []
    for a in mem.apps_for(owner):
        p = by_id.get(a["plugin_id"])
        apps.append({**a, "name": p.name if p else a["plugin_id"], "summary": p.summary if p else "",
                     "kind": _kind(p)})
    return JSONResponse({"apps": apps}, headers={"Cache-Control": "no-store"})


@router.get("/me/apps/{plugin_id}")
def my_app(plugin_id: str, request: Request):
    phone = session.current_phone(request)
    if not phone:
        return _error(401, "signed_out", "Sign in with your phone number first.")
    if not pi.ID_RE.fullmatch(plugin_id or ""):
        return _error(404, "unknown_plugin", "No plugin with that id.")
    owner = _owner(phone)
    p = _plugin(plugin_id)
    records = mem.list_records(plugin_id, owner, "", 100)
    flash = None
    if (p is not None and "flashcards" in p.tools) or any(r["key"].startswith("card:") for r in records):
        flash = mem.deck(plugin_id, owner)
        records = [r for r in records if not r["key"].startswith("card:")]
    plugin = {"id": plugin_id, "name": p.name if p else plugin_id, "summary": p.summary if p else ""}
    return JSONResponse({"plugin": plugin, "records": records, "flashcards": flash},
                        headers={"Cache-Control": "no-store"})
