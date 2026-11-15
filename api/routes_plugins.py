"""Community plugins API: the plugins/ folder (api/plugins_index.py) as JSON for the dashboard
(community/) and the FaceTime agent (chert/plugins.py). Plugins are read from disk on every
request, so a `git pull` on the server shows up without a restart.

GET  /plugins                 {"plugins": [...], "skipped": {folder: reason}, "enabled": [ids]}
GET  /plugins/search?q=       {"plugins": [...], "engine": "typesense" | "substring"}
GET  /plugins/enabled         {"plugins": [...]} the enabled ones, with what the agent needs
GET  /plugins/{id}            one plugin plus its README; 404 unknown
POST /plugins/{id}/enable     {"enabled": [ids]}; 404 unknown
POST /plugins/{id}/disable    {"enabled": [ids]}; 404 unknown

The enabled set is one global set for the demo line (no Chert sign-in in the dashboard clone).
Enable/disable refuse browser requests from origins outside the CORS list (api/session.py; add the
dashboard's Vercel URL to CORS_EXTRA_ORIGINS). Unverified plugins never get the money tools:
`effective_tools` (plugins_index.to_public) is what the agent wires.
"""
from __future__ import annotations

import json
import logging
import threading
import time

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse

from api import plugins_index as pi
from api import session
from data import plugins_store, typesense_store

log = logging.getLogger("scansafe.plugins")
router = APIRouter()

COLLECTION = "plugins"
SCHEMA = {
    "name": COLLECTION,
    "fields": [
        {"name": "name", "type": "string"},
        {"name": "summary", "type": "string"},
        {"name": "author", "type": "string", "facet": True},
        {"name": "phrases", "type": "string[]", "optional": True},
        {"name": "verified", "type": "bool", "facet": True},
    ],
    "token_separators": ["-"],
}
QUERY_BY, QUERY_WEIGHTS = "name,phrases,summary,author", "4,3,2,1"
MAX_Q = 200
TYPESENSE_RETRY_S = 60        # after a Typesense error, use the substring search for this long

_ts_lock = threading.Lock()
_indexed: tuple | None = None   # fingerprint of the plugins last sent to Typesense
_ts_down_until = 0.0


def reset() -> None:
    """Forget the Typesense index state (tests)."""
    global _indexed, _ts_down_until
    with _ts_lock:
        _indexed, _ts_down_until = None, 0.0


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"ok": False, "error": code, "message": message})


def _unknown() -> JSONResponse:
    return _error(404, "unknown_plugin", "There's no plugin with that id.")


def _load() -> tuple[list[pi.Plugin], dict[str, str]]:
    return pi.load_plugins(pi.PLUGINS_DIR)   # module attribute read per call (tests patch it)


def _find(plugin_id: str, plugins: list[pi.Plugin] | None = None) -> pi.Plugin | None:
    if not pi.ID_RE.fullmatch(plugin_id or ""):
        return None
    return next((p for p in (_load()[0] if plugins is None else plugins) if p.id == plugin_id), None)


def _card(p: pi.Plugin, installs: dict[str, int], enabled: set[str]) -> dict:
    """to_public without the README (list/search stay small; GET /plugins/{id} has it)."""
    out = pi.to_public(p, installs.get(p.id, 0))
    out.pop("readme", None)
    out["enabled"] = p.id in enabled
    return out


@router.get("/plugins")
def list_plugins() -> dict:
    plugins, skipped = _load()
    enabled, installs = set(plugins_store.get_enabled()), plugins_store.install_counts()
    return {"plugins": [_card(p, installs, enabled) for p in plugins],
            "skipped": skipped,
            "enabled": [p.id for p in plugins if p.id in enabled]}


# --- search ------------------------------------------------------------------------------------

def _substring(plugins: list[pi.Plugin], q: str) -> list[pi.Plugin]:
    """Fallback search: whole query and each word, over id/name (3), phrases (2), summary (1)."""
    q = q.lower().strip()
    terms = [q] + [w for w in q.split() if len(w) > 1 and w != q]
    scored = []
    for p in plugins:
        fields = ((3, f"{p.id} {p.name}".lower()), (2, " | ".join(p.phrases).lower()), (1, p.summary.lower()))
        score = sum(w * (2 if t == q else 1) for t in terms for w, text in fields if t in text)
        if score:
            scored.append((-score, p.id, p))
    return [p for _, _, p in sorted(scored)]


def _ensure_index(plugins: list[pi.Plugin]) -> None:
    """Create the `plugins` collection and upsert every plugin, once per change of the folder."""
    global _indexed
    fingerprint = tuple((p.id, p.sha256, p.verified) for p in plugins)
    if _indexed == fingerprint:
        return
    with typesense_store._client() as c:
        r = c.get(f"/collections/{COLLECTION}")
        if r.status_code == 404:
            r = c.post("/collections", json=SCHEMA)
            if r.status_code != 409:   # 409: created by someone else in the meantime
                r.raise_for_status()
        else:
            r.raise_for_status()
        docs = [{"id": p.id, "name": p.name, "summary": p.summary, "author": p.author,
                 "phrases": p.phrases, "verified": p.verified} for p in plugins]
        if docs:
            r = c.post(f"/collections/{COLLECTION}/documents/import", params={"action": "upsert"},
                       content="\n".join(json.dumps(d) for d in docs),
                       headers={"Content-Type": "text/plain"})
            r.raise_for_status()
            bad = [ln for ln in r.text.splitlines() if ln.strip() and not json.loads(ln).get("success")]
            if bad:
                raise RuntimeError(f"{len(bad)} plugin documents failed to import")
    _indexed = fingerprint


def _typesense(plugins: list[pi.Plugin], q: str) -> list[pi.Plugin] | None:
    """Plugins in Typesense's order, or None when it isn't configured or fails."""
    global _ts_down_until
    if not typesense_store.is_configured():
        return None
    with _ts_lock:
        if time.monotonic() < _ts_down_until:
            return None
        try:
            _ensure_index(plugins)
            with typesense_store._client() as c:
                r = c.get(f"/collections/{COLLECTION}/documents/search",
                          params={"q": q, "query_by": QUERY_BY, "query_by_weights": QUERY_WEIGHTS,
                                  "per_page": 50})
                r.raise_for_status()
                hits = r.json().get("hits", [])
        except Exception as e:  # noqa: BLE001 - search must still answer
            _ts_down_until = time.monotonic() + TYPESENSE_RETRY_S
            log.warning("plugin search: Typesense failed (%s), using substring search", type(e).__name__)
            return None
    by_id = {p.id: p for p in plugins}
    ids = [str((h.get("document") or {}).get("id", "")) for h in hits]
    return [by_id[i] for i in dict.fromkeys(ids) if i in by_id]   # drops ids no longer in the folder


@router.get("/plugins/search")
def search_plugins(q: str = "") -> dict:
    plugins, _ = _load()
    q = (q or "").strip()[:MAX_Q]
    enabled, installs = set(plugins_store.get_enabled()), plugins_store.install_counts()
    if not q:
        found, engine = plugins, "substring"
    else:
        found, engine = _typesense(plugins, q), "typesense"
        if not found:   # not configured, failed, or nothing matched: try the plain substring match
            found, engine = _substring(plugins, q), "substring"
    return {"plugins": [_card(p, installs, enabled) for p in found], "engine": engine}


# --- what the agent reads ----------------------------------------------------------------------

@router.get("/plugins/enabled")
def enabled_plugins() -> dict:
    """The enabled plugins with instructions, permissions, phrases, qr, verified and
    effective_tools. No install counts (no Tiger round-trip on the agent's call-start path).
    Only VERIFIED plugins: this set is shared by every caller of the demo line, so an unverified
    plugin's instructions must never reach the agent (defence in depth with _toggle)."""
    plugins, _ = _load()
    enabled = set(plugins_store.get_enabled())
    out = []
    for p in plugins:
        if p.id in enabled and p.verified:
            d = pi.to_public(p)
            d.pop("readme", None)
            d.pop("installs", None)
            out.append(d)
    return {"plugins": out, "baseline": plugins_store.get_baseline()}


# --- one plugin --------------------------------------------------------------------------------

@router.get("/plugins/baseline")
def get_baseline() -> dict:
    return {"baseline": plugins_store.get_baseline()}


@router.get("/plugins/{plugin_id}")
def get_plugin(plugin_id: str):
    p = _find(plugin_id)
    if p is None:
        return _unknown()
    out = pi.to_public(p, plugins_store.install_counts().get(p.id, 0))
    out["enabled"] = p.id in set(plugins_store.get_enabled())
    return out


def _toggle(plugin_id: str, on: bool, request: Request, background_tasks: BackgroundTasks):
    origin = (request.headers.get("origin") or "").rstrip("/")
    if origin and origin not in session.allowed_origins():
        return _error(403, "origin_not_allowed", "This site can't change the demo agent's plugins.")
    plugins, _ = _load()
    p = _find(plugin_id, plugins)
    if p is None:
        return _unknown()
    if on and not p.verified:
        # The demo agent is shared by every caller: anyone could otherwise switch on an unverified
        # plugin and put its instructions in front of everyone. Verify first (admins only).
        return _error(403, "needs_verification",
                      "Unverified plugins can't be turned on for the shared demo agent until an admin verifies them.")
    try:
        ids, newly_on = plugins_store.change_enabled(p.id, on)
    except OSError as e:
        log.warning("plugins: couldn't save the enabled set (%s)", type(e).__name__)
        return _error(503, "state_unavailable", "Couldn't save that change. Please try again.")
    if newly_on:
        background_tasks.add_task(plugins_store.record_install, p.id)   # Tiger off the request path
    valid = {q.id for q in plugins}
    return {"enabled": [i for i in ids if i in valid]}


@router.post("/plugins/baseline")
async def set_baseline(request: Request):
    """Demo switch: calls use plain Chert (no skills) while on. Same origin rule as the toggles."""
    origin = (request.headers.get("origin") or "").rstrip("/")
    if origin and origin not in session.allowed_origins():
        return _error(403, "origin_not_allowed", "This site can't change the demo agent.")
    try:
        body = await request.json()
    except ValueError:
        body = None
    if not isinstance(body, dict) or not isinstance(body.get("on"), bool):
        return _error(400, "bad_request", 'Send {"on": true} or {"on": false}.')
    try:
        return {"baseline": plugins_store.set_baseline(body["on"])}
    except OSError as e:
        log.warning("plugins: couldn't save baseline (%s)", type(e).__name__)
        return _error(503, "state_unavailable", "Couldn't save that change. Please try again.")


@router.post("/plugins/{plugin_id}/enable")
def enable_plugin(plugin_id: str, request: Request, background_tasks: BackgroundTasks):
    return _toggle(plugin_id, True, request, background_tasks)


@router.post("/plugins/{plugin_id}/disable")
def disable_plugin(plugin_id: str, request: Request, background_tasks: BackgroundTasks):
    return _toggle(plugin_id, False, request, background_tasks)
