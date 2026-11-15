"""Who is calling: the phone sign-in token, from `Authorization: Bearer <token>` or the
`ss_session` cookie, plus the CORS allowlist that makes the cookie usable from our own sites.

The cookie holds the same token /auth/phone/verify returns (30 days). It is HttpOnly, Secure,
SameSite=Lax and scoped to .scansafe.nyc, so app.scansafe.nyc and scansafe.nyc share it.
Env: SESSION_COOKIE_DOMAIN (default ".scansafe.nyc"; set it to "" for a host-only cookie in local
dev), CORS_EXTRA_ORIGINS (comma-separated, added to the allowlist below).
"""
from __future__ import annotations

import os
from typing import Optional

from fastapi import Request, Response

from api import config  # noqa: F401  (loads .env)

COOKIE_NAME = "ss_session"
COOKIE_MAX_AGE = 30 * 24 * 3600

# Browser origins allowed to call the API with credentials (cookie). The last one is the
# existing Vercel alias of the web app (HANDOFF.md), kept so that URL keeps working.
CORS_ORIGINS = [
    "https://scansafe.nyc",
    "https://app.scansafe.nyc",
    "https://scansafe-demo-sites.vercel.app",
    "http://localhost:3000",
    "http://localhost:3300",
    "http://localhost:3400",
    "https://app-blond-xi-88.vercel.app",
]

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def allowed_origins() -> list[str]:
    extra = [o.strip().rstrip("/") for o in os.getenv("CORS_EXTRA_ORIGINS", "").split(",") if o.strip()]
    return CORS_ORIGINS + [o for o in extra if o not in CORS_ORIGINS]


def cookie_domain() -> Optional[str]:
    raw = os.getenv("SESSION_COOKIE_DOMAIN")
    if raw is None:
        return ".scansafe.nyc"
    return raw.strip() or None


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(COOKIE_NAME, token, max_age=COOKIE_MAX_AGE, path="/", domain=cookie_domain(),
                        secure=True, httponly=True, samesite="lax")


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/", domain=cookie_domain(), secure=True,
                           httponly=True, samesite="lax")


def bearer_token(authorization: str) -> str:
    """The token from an `Authorization: Bearer <token>` header ("" if there isn't one)."""
    scheme, _, value = (authorization or "").strip().partition(" ")
    return value.strip() if scheme.lower() == "bearer" else ""


def request_tokens(request: Request) -> list[tuple[str, str]]:
    """[(token, "bearer" | "cookie")] the request carries, Bearer first."""
    out = []
    bearer = bearer_token(request.headers.get("authorization", ""))
    if bearer:
        out.append((bearer, "bearer"))
    cookie = (request.cookies.get(COOKIE_NAME) or "").strip()
    if cookie and cookie != bearer:
        out.append((cookie, "cookie"))
    return out


def _cookie_ok(request: Request) -> bool:
    """A cookie only counts for a state-changing request when it comes from one of our own
    origins (or from no browser at all). Defense in depth on top of SameSite=Lax."""
    if request.method.upper() in SAFE_METHODS:
        return True
    origin = (request.headers.get("origin") or "").rstrip("/")
    return not origin or origin in allowed_origins()


def current_phone(request: Request) -> Optional[str]:
    """The signed-in phone (E.164) for this request, or None. Bearer wins over the cookie;
    an invalid Bearer token falls back to the cookie."""
    from api.routes_call import phone_for_token   # routes_call imports this module
    for token, source in request_tokens(request):
        if source == "cookie" and not _cookie_ok(request):
            continue
        phone = phone_for_token(token)
        if phone:
            return phone
    return None
