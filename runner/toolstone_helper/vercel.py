"""Vercel connector (REST, httpx). The token comes from ~/.toolstone/.env and never appears in
results or error text."""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx

from .config import redact

API = "https://api.vercel.com"


class VercelError(Exception):
    """`code` is a short, token-free error string for the job result."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code[:200]


def _https(u: Optional[str]) -> Optional[str]:
    if not u:
        return None
    u = str(u)
    return u if u.startswith(("http://", "https://")) else f"https://{u}"


def _project_url(p: dict) -> Optional[str]:
    prod = ((p.get("targets") or {}).get("production") or {})
    alias = prod.get("alias") or []
    if alias and isinstance(alias, list):
        return _https(alias[0])
    if prod.get("url"):
        return _https(prod["url"])
    for a in p.get("alias") or []:
        if isinstance(a, dict) and a.get("domain"):
            return _https(a["domain"])
    return None


def _latest(d: Optional[dict]) -> Optional[Dict[str, Any]]:
    if not d:
        return None
    created = d.get("created") or d.get("createdAt")
    return {
        "state": d.get("state") or d.get("readyState"),
        "url": _https(d.get("url")),
        "created": int(created) // 1000 if isinstance(created, (int, float)) else None,
        "target": d.get("target"),
        "commit_message": ((d.get("meta") or {}).get("githubCommitMessage") or "")[:200] or None,
        "creator": (d.get("creator") or {}).get("username"),
    }


class VercelClient:
    def __init__(self, token: str, team_id: Optional[str] = None,
                 transport: Optional[httpx.BaseTransport] = None):
        if not token:
            raise VercelError("missing_connection:vercel")
        self._secrets = [token] + ([team_id] if team_id else [])
        self._team = team_id or None
        self._http = httpx.Client(base_url=API, transport=transport, timeout=20.0,
                                  headers={"Authorization": f"Bearer {token}",
                                           "User-Agent": "toolstone-runner/1"})

    def close(self) -> None:
        self._http.close()

    def _req(self, method: str, path: str, params: Optional[dict] = None,
             json: Optional[dict] = None) -> dict:
        params = dict(params or {})
        if self._team:
            params["teamId"] = self._team
        try:
            resp = self._http.request(method, path, params=params, json=json)
        except httpx.HTTPError as e:
            raise VercelError(f"vercel_unreachable:{type(e).__name__}") from None
        if resp.status_code >= 400:
            msg = ""
            try:
                err = resp.json().get("error") or {}
                msg = err.get("code") or err.get("message") or ""
            except (ValueError, AttributeError):
                pass
            code = f"vercel_http_{resp.status_code}" + (f":{msg}" if msg else "")
            if resp.status_code == 404:
                code = "not_found"
            raise VercelError(redact(code, self._secrets)[:200])
        try:
            data = resp.json()
        except ValueError:
            raise VercelError("vercel_bad_response") from None
        return data if isinstance(data, dict) else {}

    # -- lookups --------------------------------------------------------------------------
    def projects(self) -> List[dict]:
        return list(self._req("GET", "/v9/projects", {"limit": 10}).get("projects") or [])

    def find_project(self, name: str) -> dict:
        want = name.strip().lower()
        for p in self.projects():
            if str(p.get("name", "")).lower() == want or str(p.get("id", "")).lower() == want:
                return p
        try:
            return self._req("GET", f"/v9/projects/{quote(name.strip(), safe='')}")
        except VercelError as e:
            if e.code == "not_found":
                raise VercelError("project_not_found") from None
            raise

    def latest_deployment(self, project_id: str, target: Optional[str] = None) -> Optional[dict]:
        params: Dict[str, Any] = {"projectId": project_id, "limit": 1}
        if target:
            params["target"] = target
        deps = self._req("GET", "/v6/deployments", params).get("deployments") or []
        return deps[0] if deps else None

    # -- jobs -----------------------------------------------------------------------------
    def status(self, project: str = "") -> Dict[str, Any]:
        projs = [self.find_project(project)] if project.strip() else self.projects()[:5]
        out = []
        for p in projs[:5]:
            out.append({
                "name": p.get("name"),
                "framework": p.get("framework"),
                "url": _project_url(p),
                "latest": _latest(self.latest_deployment(str(p.get("id") or ""))),
            })
        out.sort(key=lambda x: (x["latest"] or {}).get("created") or 0, reverse=True)
        return {"projects": out}

    def redeploy(self, project: str) -> Dict[str, Any]:
        if not project.strip():
            raise VercelError("project_required")
        p = self.find_project(project)
        dep = self.latest_deployment(str(p.get("id") or ""), target="production")
        dep_id = (dep or {}).get("uid") or (dep or {}).get("id")
        if not dep_id:
            raise VercelError("no_production_deployment")
        body = {"name": p.get("name") or project.strip(), "deploymentId": dep_id,
                "target": "production"}
        d = self._req("POST", "/v13/deployments", {"forceNew": 1}, json=body)
        return {"deployment": {"id": d.get("id") or d.get("uid"), "url": _https(d.get("url")),
                               "state": d.get("readyState") or d.get("status") or d.get("state")}}
