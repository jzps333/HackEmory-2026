"""HTTP client for the Toolstone relay (api/routes_runner.py) and phone sign-in.

The runner token rides only in the Authorization header; it is never logged or echoed.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

import httpx

MAX_FRAME = 400_000
MAX_RESULT = 16_000
_JOB_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class RelayError(Exception):
    """A relay call failed. `status` is the HTTP status (0 = unreachable); the message never
    contains a token."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class AuthError(RelayError):
    pass


def valid_job_id(job_id: Any) -> bool:
    return isinstance(job_id, str) and bool(_JOB_ID_RE.match(job_id))


def _error_text(resp: httpx.Response) -> str:
    try:
        data = resp.json()
    except ValueError:
        return f"http_{resp.status_code}"
    if isinstance(data, dict):
        for k in ("message", "detail", "error"):
            v = data.get(k)
            if isinstance(v, str) and v:
                return v[:200]
    return f"http_{resp.status_code}"


def fit_result(result: Dict[str, Any], limit: int = MAX_RESULT) -> Dict[str, Any]:
    """Shrink a result to the relay's 16 KB cap by halving its longest lists."""
    result = dict(result)
    while len(json.dumps(result)) > limit:
        lists = [(len(v), k) for k, v in result.items() if isinstance(v, list) and len(v) > 1]
        if not lists:
            return {"truncated": True}
        _, k = max(lists)
        result[k] = result[k][: len(result[k]) // 2]
        result["truncated"] = True
    return result


class Relay:
    def __init__(self, base: str, runner_token: Optional[str] = None,
                 transport: Optional[httpx.BaseTransport] = None):
        self.base = base.rstrip("/")
        self._token = runner_token
        self._http = httpx.Client(base_url=self.base, transport=transport,
                                  timeout=httpx.Timeout(20.0, connect=10.0),
                                  headers={"User-Agent": "toolstone-runner/1"})

    def close(self) -> None:
        self._http.close()

    # -- low level ------------------------------------------------------------------------
    def _call(self, method: str, path: str, *, auth: Optional[str] = None,
              timeout: Optional[float] = None, **kw) -> httpx.Response:
        headers = dict(kw.pop("headers", {}) or {})
        if auth:
            headers["Authorization"] = auth
        try:
            resp = self._http.request(method, path, headers=headers,
                                      timeout=timeout if timeout is not None else httpx.USE_CLIENT_DEFAULT,
                                      **kw)
        except httpx.HTTPError as e:
            raise RelayError(0, f"unreachable ({type(e).__name__})") from None
        if resp.status_code in (401, 403):
            raise AuthError(resp.status_code, _error_text(resp))
        if resp.status_code >= 400:
            raise RelayError(resp.status_code, _error_text(resp))
        return resp

    def _json(self, resp: httpx.Response) -> dict:
        try:
            data = resp.json()
        except ValueError:
            raise RelayError(resp.status_code, "bad_json") from None
        if not isinstance(data, dict):
            raise RelayError(resp.status_code, "bad_json")
        return data

    def _runner_auth(self) -> str:
        if not self._token:
            raise AuthError(401, "not_paired")
        return f"Runner {self._token}"

    # -- sign-in + pairing ----------------------------------------------------------------
    def phone_start(self, phone: str) -> dict:
        return self._json(self._call("POST", "/auth/phone/start", json={"phone": phone}))

    def phone_verify(self, phone: str, request_id: str) -> dict:
        return self._json(self._call("POST", "/auth/phone/verify",
                                     json={"phone": phone, "request_id": request_id}))

    def pair(self, bearer: str, name: str) -> dict:
        return self._json(self._call("POST", "/runner/pair", auth=f"Bearer {bearer}",
                                     json={"name": name[:60]}))

    # -- runner ---------------------------------------------------------------------------
    def next_job(self, wait: int = 25) -> Optional[dict]:
        wait = max(0, min(int(wait), 25))
        resp = self._call("GET", "/runner/next", auth=self._runner_auth(),
                          params={"wait": wait}, timeout=wait + 15.0)
        job = self._json(resp).get("job")
        return job if isinstance(job, dict) else None

    def frame(self, job_id: str, jpeg: bytes) -> None:
        if not valid_job_id(job_id) or not jpeg or len(jpeg) > MAX_FRAME:
            return
        self._call("POST", f"/runner/jobs/{job_id}/frame", auth=self._runner_auth(),
                   content=jpeg, headers={"Content-Type": "image/jpeg"})

    def progress(self, job_id: str, note: str) -> None:
        if not valid_job_id(job_id):
            return
        self._call("POST", f"/runner/jobs/{job_id}/progress", auth=self._runner_auth(),
                   json={"note": str(note)[:200]})

    def result(self, job_id: str, status: str, result: Optional[dict] = None,
               error: str = "") -> None:
        if not valid_job_id(job_id):
            return
        body = {"status": "done" if status == "done" else "failed",
                "result": fit_result(result or {}), "error": str(error or "")[:200]}
        self._call("POST", f"/runner/jobs/{job_id}/result", auth=self._runner_auth(), json=body)


class JobReporter:
    """What a job handler talks to: progress notes, frames, one result. Never raises; every
    outgoing string is scrubbed of secrets first."""

    def __init__(self, relay: Relay, job_id: str, secrets: List[str]):
        self.relay = relay
        self.job_id = job_id
        self.secrets = secrets
        self.frames_sent = 0
        self.frame_errors = 0

    def _clean(self, text: str) -> str:
        from .config import redact
        return redact(text, self.secrets)

    def progress(self, note: str) -> None:
        try:
            self.relay.progress(self.job_id, self._clean(note))
        except RelayError:
            pass

    def frame(self, jpeg: bytes) -> None:
        try:
            self.relay.frame(self.job_id, jpeg)
            self.frames_sent += 1
        except RelayError:
            self.frame_errors += 1

    def result(self, status: str, result: Optional[dict] = None, error: str = "") -> None:
        try:
            safe = json.loads(self._clean(json.dumps(result or {})))
        except ValueError:
            safe = {"redacted": True}
        try:
            self.relay.result(self.job_id, status, safe, self._clean(error))
        except RelayError:
            pass
