"""Saved accounts: session cookie + logout, CORS allowlist, profile, linked accounts, the demo
Dogwood OAuth server + operator API + agent app view, and PayPal SANDBOX Vault (linking and
paying). Offline: PayPal is an httpx MockTransport, the store is in memory (plus one fake
Postgres connection for the Tiger SQL path), Chert texts are faked."""
import contextlib
import json
import os
import stat
import time
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from solders.keypair import Keypair

from api import (account_crypto, dogwood, main as api_main, meter_pay, paypal_vault, recent_scans,
                 result_store, routes_accounts, routes_call, session)
from api.merchants import KNOWN_MERCHANTS
from api.scan import parse_solana_pay, payment_result
from data import accounts_store, tiger_store

PHONE = "+14045559861"
OTHER = "+13125550123"
DOGWOOD = KNOWN_MERCHANTS["Dogwood Lot & Meter Co."]
MAGNOLIA = KNOWN_MERCHANTS["Magnolia Diner"]
METER_QR = (f"solana:{DOGWOOD}?amount=0.01&reference={Keypair().pubkey()}"
            "&label=Dogwood%20Lot%20%26%20Meter%20Co.&message=Meter%2042")
DINER_QR = f"solana:{MAGNOLIA}?amount=0.005&label=Magnolia%20Diner&message=Table%207"
REDIRECT = "https://api.scansafe.nyc/link/dogwood/callback"
AGENT = {"X-Agent-Key": "agent-test-key"}
REAL_CLIENT = httpx.Client

client = TestClient(api_main.app)


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    for k in ("APP_BASE_URL", "API_BASE_URL", "DOGWOOD_SITE_URL", "SESSION_COOKIE_DOMAIN", "CORS_EXTRA_ORIGINS",
              "PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "PAYPAL_ENV", "DOGWOOD_RATE_USD",
              "DEMO_USD_PER_SOL", "PAYPAL_MAX_USD", "TIGER_DATABASE_URL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ACCOUNTS_STORE", "memory")
    monkeypatch.setenv("ACCOUNT_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("ACCOUNT_PEPPER", "test-pepper")
    monkeypatch.setenv("AGENT_INTERNAL_KEY", "agent-test-key")
    monkeypatch.setenv("DOGWOOD_OPERATOR_FILE", str(tmp_path / "dogwood.json"))
    monkeypatch.setattr(routes_call, "CONSENT_FILE", str(tmp_path / "consent.json"))
    monkeypatch.setattr(routes_call, "_inbound_texts", lambda: [])
    monkeypatch.setattr(result_store, "RESULT_DIR", tmp_path / "results")
    routes_call._code_slots.clear()
    routes_call._ip_starts.clear()
    routes_call._start_times.clear()
    accounts_store._memory.clear()
    dogwood.clear()
    routes_accounts.clear()
    paypal_vault.reset()
    recent_scans.clear()
    account_crypto.reset_cache()
    yield
    accounts_store._memory.clear()
    recent_scans.clear()


def signed_in(phone: str = PHONE) -> str:
    return routes_call._issue_token(phone)


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def cookie(token: str) -> dict:
    return {"Cookie": f"{session.COOKIE_NAME}={token}"}


def scanned(qr: str = METER_QR) -> str:
    r = payment_result(qr, parse_solana_pay(qr))
    recent_scans.remember(r)
    return r.scan_id


def stored_blob() -> str:
    """Everything the memory store holds, as text (to look for plaintext secrets)."""
    s = accounts_store._memory
    return json.dumps({"a": s.accounts, "l": s.linked_rows}, default=str)


# --- A. session cookie, logout, CORS -------------------------------------------------------------

def test_verify_sets_session_cookie(monkeypatch):
    start = client.post("/auth/phone/start", json={"phone": PHONE}).json()
    body = {"phone": PHONE, "request_id": start["request_id"]}
    r = client.post("/auth/phone/verify", json=body)
    assert r.json() == {"verified": False} and "set-cookie" not in r.headers
    monkeypatch.setattr(routes_call, "_inbound_texts", lambda: [("9861", f"MY SIGN-IN CODE IS {start['code']}")])
    r = client.post("/auth/phone/verify", json=body)
    token = r.json()["token"]
    sc = r.headers["set-cookie"]
    assert sc.startswith(f"ss_session={token};")
    for part in ("HttpOnly", "Secure", "SameSite=lax", "Domain=.scansafe.nyc", "Path=/", "Max-Age=2592000"):
        assert part.lower() in sc.lower(), part


def test_cookie_and_bearer_both_sign_in():
    token = signed_in()
    assert client.get("/auth/me", headers=cookie(token)).json() == {"signed_in": True, "phone_masked": "•••9861"}
    assert client.get("/auth/me", headers=bearer(token)).json()["signed_in"] is True
    assert client.get("/me", headers=cookie(token)).json()["signed_in"] is True
    # A bad Bearer falls back to a good cookie; Bearer wins when both are good.
    other = signed_in(OTHER)
    assert client.get("/auth/me", headers={**bearer("nope"), **cookie(token)}).json()["phone_masked"] == "•••9861"
    assert client.get("/auth/me", headers={**bearer(other), **cookie(token)}).json()["phone_masked"] == "•••0123"
    assert client.get("/auth/me", headers=cookie("forged")).json() == {"signed_in": False}


def test_cookie_ignored_for_writes_from_foreign_origin():
    token = signed_in()
    evil = {**cookie(token), "Origin": "https://evil.example"}
    r = client.put("/me", json={"plate": "ABC123"}, headers=evil)
    assert r.status_code == 401 and r.json()["error"] == "not_signed_in"
    ok = {**cookie(token), "Origin": "https://app.scansafe.nyc"}
    assert client.put("/me", json={"plate": "ABC123"}, headers=ok).json()["plate"] == "ABC123"
    assert client.put("/me", json={"plate": "XYZ9"}, headers=cookie(token)).json()["plate"] == "XYZ9"   # no Origin (curl)
    # Bearer is never subject to the Origin check (it isn't sent automatically by browsers).
    assert client.put("/me", json={"plate": "B1"}, headers={**bearer(token), "Origin": "https://evil.example"}).status_code == 200


def test_logout_revokes_and_clears_cookie():
    token = signed_in()
    r = client.post("/auth/logout", headers=cookie(token))
    assert r.json() == {"ok": True, "signed_in": False, "revoked": True}
    sc = r.headers["set-cookie"].lower()
    assert sc.startswith("ss_session=") and "max-age=0" in sc and "domain=.scansafe.nyc" in sc
    assert client.get("/auth/me", headers=bearer(token)).json() == {"signed_in": False}
    assert client.post("/auth/logout").json()["revoked"] is False       # nobody signed in: still 200
    t2 = signed_in()
    assert client.post("/auth/logout", headers=bearer(t2)).json()["revoked"] is True
    # A cross-site form post can't sign someone out with their cookie.
    t3 = signed_in()
    client.post("/auth/logout", headers={**cookie(t3), "Origin": "https://evil.example"})
    assert client.get("/auth/me", headers=bearer(t3)).json()["signed_in"] is True


def test_cors_allowlist_with_credentials():
    for origin in session.CORS_ORIGINS[:6]:
        r = client.options("/me", headers={"Origin": origin, "Access-Control-Request-Method": "PUT",
                                           "Access-Control-Request-Headers": "content-type,authorization"})
        assert r.status_code == 200, origin
        assert r.headers["access-control-allow-origin"] == origin
        assert r.headers["access-control-allow-credentials"] == "true"
    assert set(session.CORS_ORIGINS[:6]) == {
        "https://scansafe.nyc", "https://app.scansafe.nyc", "https://scansafe-demo-sites.vercel.app",
        "http://localhost:3000", "http://localhost:3300", "http://localhost:3400"}
    r = client.options("/me", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert r.status_code == 400 and "access-control-allow-origin" not in r.headers
    r = client.get("/health", headers={"Origin": "https://evil.example"})
    assert r.status_code == 200 and "access-control-allow-origin" not in r.headers
    r = client.get("/health", headers={"Origin": "https://scansafe-demo-sites.vercel.app"})
    assert r.headers["access-control-allow-origin"] == "https://scansafe-demo-sites.vercel.app"


def test_cors_extra_origins(monkeypatch):
    monkeypatch.setenv("CORS_EXTRA_ORIGINS", "https://preview.example/ , https://scansafe.nyc")
    got = session.allowed_origins()
    assert got.count("https://scansafe.nyc") == 1 and got[-1] == "https://preview.example"


# --- B. profile ------------------------------------------------------------------------------

def test_profile_signed_out_and_defaults():
    assert client.get("/me").json() == {"signed_in": False}
    assert client.put("/me", json={"plate": "ABC"}).status_code == 401
    assert client.get("/me/linked").status_code == 401
    me = client.get("/me", headers=bearer(signed_in())).json()
    assert me == {"signed_in": True, "phone_masked": "•••9861", "plate": None,
                  "preferred_payment": "solana_devnet", "linked": [],
                  "providers": {"dogwood": True, "paypal": False},
                  "paypal_rates": {"dogwood_usd_per_hour": 2.5, "demo_usd_per_sol": 100.0}}


@pytest.mark.parametrize("raw,want", [("abc 123", "ABC 123"), ("  gx-42  ", "GX-42"), ("ab", "AB"),
                                      ("1234567890", "1234567890")])
def test_plate_ok(raw, want):
    r = client.put("/me", json={"plate": raw}, headers=bearer(signed_in()))
    assert r.status_code == 200 and r.json()["plate"] == want


@pytest.mark.parametrize("raw", ["A", "12345678901", "AB_12", "ÄBC", "AB.C", "--", "  -  ", "AB\n12"])
def test_plate_refused(raw):
    r = client.put("/me", json={"plate": raw}, headers=bearer(signed_in()))
    assert r.status_code == 400 and r.json()["error"] == "bad_plate"
    assert "2 to 10" in r.json()["message"]


def test_profile_partial_updates_and_clearing():
    h = bearer(signed_in())
    client.put("/me", json={"plate": "abc123"}, headers=h)
    r = client.put("/me", json={"preferred_payment": "solana_devnet"}, headers=h).json()
    assert r["plate"] == "ABC123" and r["preferred_payment"] == "solana_devnet"   # plate untouched
    assert client.put("/me", json={}, headers=h).json()["plate"] == "ABC123"
    assert client.put("/me", json={"plate": None}, headers=h).json()["plate"] is None
    client.put("/me", json={"plate": "abc123"}, headers=h)
    assert client.put("/me", json={"plate": ""}, headers=h).json()["plate"] is None
    r = client.put("/me", json={"preferred_payment": "venmo"}, headers=h)
    assert r.status_code == 400 and r.json()["error"] == "bad_preferred_payment"
    r = client.put("/me", json={"preferred_payment": "paypal"}, headers=h)
    assert r.status_code == 403 and r.json()["error"] == "paypal_not_linked"
    # Each phone has its own profile.
    assert client.get("/me", headers=bearer(signed_in(OTHER))).json()["plate"] is None


def test_rows_keyed_by_peppered_hash_never_the_phone(monkeypatch):
    client.put("/me", json={"plate": "ABC123"}, headers=bearer(signed_in()))
    (ph,) = accounts_store._memory.accounts
    assert ph == account_crypto.phone_hash(PHONE) and len(ph) == 64
    assert PHONE not in stored_blob() and "4045559861" not in stored_blob()
    import hashlib
    assert ph == hashlib.sha256((PHONE + "test-pepper").encode()).hexdigest()
    monkeypatch.setenv("ACCOUNT_PEPPER", "another")
    assert account_crypto.phone_hash(PHONE) != ph


def test_pepper_generated_once_and_kept(monkeypatch, tmp_path):
    monkeypatch.delenv("ACCOUNT_PEPPER")
    path = tmp_path / "pepper"
    monkeypatch.setenv("ACCOUNT_PEPPER_FILE", str(path))
    account_crypto.reset_cache()
    first = account_crypto.phone_hash(PHONE)
    assert path.exists() and stat.S_IMODE(os.stat(path).st_mode) == 0o600
    account_crypto.reset_cache()             # like a restart
    assert account_crypto.phone_hash(PHONE) == first


def test_store_not_configured_is_503(monkeypatch):
    monkeypatch.delenv("ACCOUNTS_STORE")
    r = client.get("/me", headers=bearer(signed_in()))
    assert r.status_code == 503 and r.json()["error"] == "accounts_not_configured"
    r = client.get("/link/dogwood/start", headers=bearer(signed_in()))
    assert r.status_code == 503


def test_tiger_store_failure_is_502(monkeypatch):
    monkeypatch.setenv("ACCOUNTS_STORE", "tiger")
    monkeypatch.setenv("TIGER_DATABASE_URL", "postgres://user:secret@db.invalid/x")

    def boom():
        raise OSError("connection to db.invalid failed: password=secret")

    monkeypatch.setattr(tiger_store, "_connect", boom)
    r = client.get("/me", headers=bearer(signed_in()))
    assert r.status_code == 502 and r.json()["error"] == "accounts_store_error" and "secret" not in r.text


# --- D. Dogwood OAuth --------------------------------------------------------------------------

def dogwood_start(token: str) -> dict:
    r = client.get("/link/dogwood/start", headers=bearer(token))
    assert r.status_code == 200, r.text
    url = urlparse(r.json()["authorize_url"])
    assert (url.scheme, url.netloc, url.path) == ("https", "scansafe-demo-sites.vercel.app", "/dogwood/authorize")
    return {k: v[0] for k, v in parse_qs(url.query).items()}


def consent(q: dict, decision: str = "allow", **over) -> httpx.Response:
    body = {"client_id": q["client_id"], "redirect_uri": q["redirect_uri"], "scope": q["scope"],
            "state": q["state"], "decision": decision, **over}
    return client.post("/operators/dogwood/oauth/authorize", json=body)


def follow(redirect: str, **headers) -> httpx.Response:
    """The browser following the consent page's redirect back to our API."""
    u = urlparse(redirect)
    assert f"{u.scheme}://{u.netloc}{u.path}" == REDIRECT
    return client.get(f"{u.path}?{u.query}", headers=headers, follow_redirects=False)


def link_dogwood(token: str) -> httpx.Response:
    q = dogwood_start(token)
    r = consent(q)
    assert r.status_code == 200, r.text
    return follow(r.json()["redirect"])


def test_dogwood_authorize_url_exact():
    q = dogwood_start(signed_in())
    assert q["client_id"] == "scansafe" and q["redirect_uri"] == REDIRECT and q["scope"] == "pay_parking"
    assert q["display"] == "•••9861"
    r = client.get("/link/dogwood/start", headers=bearer(signed_in()))
    raw = r.json()["authorize_url"]
    assert "redirect_uri=https%3A%2F%2Fapi.scansafe.nyc%2Flink%2Fdogwood%2Fcallback" in raw
    body, why = account_crypto.verify(dogwood.STATE_PURPOSE, q["state"])
    assert why == "" and body["ph"] == account_crypto.phone_hash(PHONE)
    assert 590 <= body["exp"] - time.time() <= 600
    assert client.get("/link/dogwood/start").status_code == 401


def test_dogwood_full_link_flow_and_encryption_at_rest():
    token = signed_in()
    r = link_dogwood(token)
    assert r.status_code == 302 and r.headers["location"] == "https://scansafe.nyc/?linked=dogwood"
    me = client.get("/me", headers=bearer(token)).json()
    assert [(x["provider"], x["display"]) for x in me["linked"]] == [("dogwood", "Dogwood Parking")]
    assert datetime.fromisoformat(me["linked"][0]["linked_at"]).tzinfo is not None
    assert client.get("/me/linked", headers=bearer(token)).json()["linked"] == me["linked"]
    (row,) = accounts_store._memory.linked_rows
    assert row["meta"] == {"account_name": "Dogwood Parking", "scope": "pay_parking"}
    secret = account_crypto.decrypt(row["secret_enc"])
    access = secret["access_token"]
    assert access.startswith("dwat_") and access not in stored_blob()      # ciphertext only
    assert Fernet(os.environ["ACCOUNT_KEY"].encode()).decrypt(row["secret_enc"].encode())
    # The operator file keeps only a hash of the token.
    assert access not in open(os.environ["DOGWOOD_OPERATOR_FILE"]).read()
    acct = client.get("/operators/dogwood/api/me", headers=bearer(access)).json()
    assert acct["account_id"].startswith("dw_") and acct["name"] == "Demo driver •••9861"


def test_app_base_url_redirect(monkeypatch):
    monkeypatch.setenv("APP_BASE_URL", "https://app.scansafe.nyc/")
    r = link_dogwood(signed_in())
    assert r.headers["location"] == "https://app.scansafe.nyc/accounts?linked=dogwood"


def test_dogwood_deny():
    q = dogwood_start(signed_in())
    redirect = consent(q, "deny").json()["redirect"]
    assert parse_qs(urlparse(redirect).query)["error"] == ["access_denied"]
    r = follow(redirect)
    assert r.headers["location"] == "https://scansafe.nyc/?link_error=access_denied&provider=dogwood"
    assert accounts_store._memory.linked_rows == []


@pytest.mark.parametrize("bad", [
    "https://api.scansafe.nyc/link/dogwood/callback.evil.com",
    "https://api.scansafe.nyc/link/dogwood/callback/",
    "https://api.scansafe.nyc/link/dogwood/callback?x=1",
    "http://api.scansafe.nyc/link/dogwood/callback",
    "https://evil.example/link/dogwood/callback",
    ""])
def test_authorize_only_exact_redirect_uri(bad):
    q = dogwood_start(signed_in())
    r = consent(q, redirect_uri=bad)
    assert r.status_code == 400 and r.json()["error"] == "invalid_redirect_uri" and "redirect" not in r.json()


def test_authorize_refusals():
    q = dogwood_start(signed_in())
    assert consent(q, client_id="other").json()["error"] == "invalid_client"
    assert consent(q, state=q["state"][:-2] + "AA").json()["error"] == "invalid_state"
    assert consent(q, state="").json()["error"] == "invalid_state"
    assert consent(q, decision="maybe").status_code == 400
    scope = consent(q, scope="everything").json()["redirect"]
    assert parse_qs(urlparse(scope).query)["error"] == ["invalid_scope"]
    # A state signed for something else (e.g. the PayPal flow) is not a Dogwood state.
    other = account_crypto.sign(routes_accounts.PAYPAL_STATE_PURPOSE, {"ph": "x", "n": "y"}, 600)
    assert consent(q, state=other).json()["error"] == "invalid_state"


def test_state_expires_after_10_minutes(monkeypatch):
    q = dogwood_start(signed_in())
    redirect = consent(q).json()["redirect"]
    later = time.time() + 601
    monkeypatch.setattr(time, "time", lambda: later)
    assert consent(q).json()["error"] == "invalid_state"
    r = follow(redirect)
    assert r.headers["location"].endswith("link_error=link_expired&provider=dogwood")


def test_state_and_code_single_use():
    q = dogwood_start(signed_in())
    redirect = consent(q).json()["redirect"]
    assert follow(redirect).headers["location"].endswith("linked=dogwood")
    again = follow(redirect)
    assert again.headers["location"].endswith("link_error=invalid_state&provider=dogwood")
    assert len(accounts_store._memory.linked_rows) == 1


def test_code_single_use_at_token_endpoint_and_replay_revokes():
    q = dogwood_start(signed_in())
    code = parse_qs(urlparse(consent(q).json()["redirect"]).query)["code"][0]
    form = {"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT,
            "client_id": "scansafe", "client_secret": dogwood.client_secret()}
    r = client.post("/operators/dogwood/oauth/token", data=form)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    access = r.json()["access_token"]
    assert r.json()["token_type"] == "Bearer" and r.json()["scope"] == "pay_parking"
    assert client.get("/operators/dogwood/api/me", headers=bearer(access)).status_code == 200
    r2 = client.post("/operators/dogwood/oauth/token", data=form)
    assert r2.status_code == 400 and r2.json()["error"] == "invalid_grant"
    assert client.get("/operators/dogwood/api/me", headers=bearer(access)).status_code == 401


def test_token_endpoint_refusals(monkeypatch):
    q = dogwood_start(signed_in())

    def fresh_code():
        return parse_qs(urlparse(consent(q).json()["redirect"]).query)["code"][0]

    base = {"grant_type": "authorization_code", "redirect_uri": REDIRECT, "client_id": "scansafe",
            "client_secret": dogwood.client_secret()}
    r = client.post("/operators/dogwood/oauth/token", data={**base, "code": fresh_code(), "client_secret": "guess"})
    assert r.status_code == 401 and r.json()["error"] == "invalid_client"
    r = client.post("/operators/dogwood/oauth/token", data={**base, "code": fresh_code(), "grant_type": "password"})
    assert r.json()["error"] == "unsupported_grant_type"
    r = client.post("/operators/dogwood/oauth/token",
                    data={**base, "code": fresh_code(), "redirect_uri": REDIRECT + "x"})
    assert r.json()["error"] == "invalid_grant"
    code = fresh_code()
    later = time.time() + 301
    with monkeypatch.context() as m:
        m.setattr(time, "time", lambda: later)
        r = client.post("/operators/dogwood/oauth/token", data={**base, "code": code})
    assert r.json() == {"error": "invalid_grant", "error_description": "The code expired."}
    # HTTP Basic client authentication works too.
    import base64
    basic = base64.b64encode(f"scansafe:{dogwood.client_secret()}".encode()).decode()
    r = client.post("/operators/dogwood/oauth/token",
                    data={"grant_type": "authorization_code", "code": fresh_code(), "redirect_uri": REDIRECT},
                    headers={"Authorization": f"Basic {basic}"})
    assert r.status_code == 200, r.text


def test_callback_refuses_when_signed_in_as_someone_else():
    q = dogwood_start(signed_in())
    redirect = consent(q).json()["redirect"]
    r = follow(redirect, Cookie=f"ss_session={signed_in(OTHER)}")
    assert r.headers["location"].endswith("link_error=signed_in_as_someone_else&provider=dogwood")
    assert accounts_store._memory.linked_rows == []


def test_disconnect_dogwood_revokes_everywhere():
    token = signed_in()
    link_dogwood(token)
    access = account_crypto.decrypt(accounts_store._memory.linked_rows[0]["secret_enc"])["access_token"]
    r = client.delete("/me/linked/dogwood", headers=bearer(token))
    assert r.json() == {"ok": True, "provider": "dogwood", "revoked": True}
    assert client.get("/me", headers=bearer(token)).json()["linked"] == []
    row = accounts_store._memory.linked_rows[0]
    assert row["revoked_at"] is not None and row["secret_enc"] == ""
    assert client.get("/operators/dogwood/api/me", headers=bearer(access)).status_code == 401
    assert client.delete("/me/linked/dogwood", headers=bearer(token)).json()["revoked"] is False
    assert client.delete("/me/linked/venmo", headers=bearer(token)).status_code == 404
    assert client.delete("/me/linked/dogwood").status_code == 401


def test_relink_replaces_and_revokes_old_token():
    token = signed_in()
    link_dogwood(token)
    old = account_crypto.decrypt(accounts_store._memory.linked_rows[0]["secret_enc"])["access_token"]
    link_dogwood(token)
    rows = accounts_store._memory.linked_rows
    assert [r["revoked_at"] is None for r in rows] == [False, True] and rows[0]["secret_enc"] == ""
    assert client.get("/operators/dogwood/api/me", headers=bearer(old)).status_code == 401
    assert len(client.get("/me", headers=bearer(token)).json()["linked"]) == 1


def test_link_needs_account_key(monkeypatch):
    monkeypatch.delenv("ACCOUNT_KEY")
    r = client.get("/link/dogwood/start", headers=bearer(signed_in()))
    assert r.status_code == 503 and r.json()["error"] == "accounts_not_configured"
    monkeypatch.setenv("ACCOUNT_KEY", "not-a-fernet-key")
    assert client.get("/link/dogwood/start", headers=bearer(signed_in())).status_code == 503


# --- Dogwood operator API ----------------------------------------------------------------------

def operator_token(phone: str = PHONE) -> str:
    link_dogwood(signed_in(phone))
    rows = [r for r in accounts_store._memory.linked_rows
            if r["phone_hash"] == account_crypto.phone_hash(phone) and r["revoked_at"] is None]
    return account_crypto.decrypt(rows[0]["secret_enc"])["access_token"]


def test_operator_sessions():
    tok = operator_token()
    r = client.post("/operators/dogwood/api/sessions", json={"meter_id": "42", "plate": "abc 123", "hours": 3},
                    headers=bearer(tok))
    assert r.status_code == 200, r.text
    s = r.json()
    assert s == {"session_id": s["session_id"], "meter_id": "42", "plate": "ABC 123", "hours": 3,
                 "amount_sol": 0.03, "status": "pending_payment"}
    assert client.get(f"/operators/dogwood/api/sessions/{s['session_id']}", headers=bearer(tok)).json() == s
    other = operator_token(OTHER)
    assert client.get(f"/operators/dogwood/api/sessions/{s['session_id']}", headers=bearer(other)).status_code == 404
    assert client.get(f"/operators/dogwood/api/sessions/{s['session_id']}").status_code == 401
    bad = [({"meter_id": "7", "plate": "AB1", "hours": 1}, 404, "unknown_meter"),
           ({"meter_id": "42", "plate": "A", "hours": 1}, 400, "bad_plate"),
           ({"meter_id": "42", "plate": None, "hours": 1}, 400, "bad_plate"),
           ({"meter_id": "42", "plate": "AB1", "hours": 5}, 400, "bad_hours"),
           ({"meter_id": "42", "plate": "AB1", "hours": "2"}, 400, "bad_hours")]
    for body, status, code in bad:
        r = client.post("/operators/dogwood/api/sessions", json=body, headers=bearer(tok))
        assert (r.status_code, r.json()["error"]) == (status, code), body
    r = client.post("/operators/dogwood/api/sessions", json=bad[0][0], headers=bearer("dwat_fake"))
    assert r.status_code == 401 and r.headers["www-authenticate"].startswith("Bearer")


# --- Dogwood app session (agent live view) -----------------------------------------------------

def app_token(sid: str) -> str:
    r = client.post("/operators/dogwood/app-session", json={"scan_id": sid}, headers=AGENT)
    assert r.status_code == 200, r.text
    url = urlparse(r.json()["app_url"])
    assert (url.netloc, url.path) == ("scansafe-demo-sites.vercel.app", "/dogwood/app")
    return parse_qs(url.query)["s"][0]


def test_app_session_needs_agent_key(monkeypatch):
    sid = scanned()
    assert client.post("/operators/dogwood/app-session", json={"scan_id": sid}).status_code == 401
    assert client.post("/operators/dogwood/app-session", json={"scan_id": sid},
                       headers={"X-Agent-Key": "wrong"}).status_code == 401
    monkeypatch.delenv("AGENT_INTERNAL_KEY")
    r = client.post("/operators/dogwood/app-session", json={"scan_id": sid}, headers={"X-Agent-Key": ""})
    assert r.status_code == 503 and r.json()["error"] == "agent_key_not_configured"


def test_app_session_refuses_non_meters():
    r = client.post("/operators/dogwood/app-session", json={"scan_id": scanned(DINER_QR)}, headers=AGENT)
    assert r.status_code == 400 and r.json()["error"] == "not_a_meter"
    r = client.post("/operators/dogwood/app-session", json={"scan_id": "nope"}, headers=AGENT)
    assert r.status_code == 404


def test_app_session_plate_and_linked_from_the_scan_owner():
    sid = scanned()
    r = client.post("/operators/dogwood/app-session", json={"scan_id": sid}, headers=AGENT).json()
    assert r["plate"] is None and r["linked"] is False and r["expires_in"] == 900
    token = signed_in()
    client.put("/me", json={"plate": "gx 42"}, headers=bearer(token))
    link_dogwood(token)
    routes_call._remember_scan_owner(sid, PHONE)           # what /call-me does for a meter code
    r = client.post("/operators/dogwood/app-session", json={"scan_id": sid}, headers=AGENT).json()
    assert r["plate"] == "GX 42" and r["linked"] is True
    # A signed-in quote claims an unowned scan (but never takes over an owned one).
    sid2 = scanned()
    client.post("/pay/quote", json={"scan_id": sid2, "hours": 1}, headers=bearer(token))
    assert meter_pay.get_owner(sid2) == account_crypto.phone_hash(PHONE)
    client.post("/pay/quote", json={"scan_id": sid2, "hours": 1}, headers=bearer(signed_in(OTHER)))
    assert meter_pay.get_owner(sid2) == account_crypto.phone_hash(PHONE)


def test_app_state_follows_quote_and_status(monkeypatch):
    from api import solana_pay
    sid = scanned()
    s = app_token(sid)
    st = client.get(f"/operators/dogwood/app-state?s={s}")
    assert st.headers["cache-control"] == "no-store"
    assert st.json() == {"meter_id": "42", "operator": "Dogwood Lot & Meter Co.", "plate": None,
                         "hours": None, "rate_per_hour_sol": 0.01, "amount_sol": None,
                         "min_hours": 1, "max_hours": 4, "status": "choose"}
    client.post("/pay/quote", json={"scan_id": sid, "hours": 3})
    st = client.get(f"/operators/dogwood/app-state?s={s}").json()
    assert (st["status"], st["hours"], st["amount_sol"]) == ("waiting_for_approval", 3, 0.03)
    # The Dogwood app's own hours control changes the quote (what the agent shows), never pays.
    r = client.post(f"/operators/dogwood/app-state?s={s}", json={"hours": 2})
    assert r.json()["hours"] == 2 and client.get(f"/pay/quote/{sid}").json()["hours"] == 2
    assert client.post(f"/operators/dogwood/app-state?s={s}", json={"hours": 9}).json()["error"] == "bad_hours"
    assert meter_pay.get_status(sid)["state"] == "none"
    from api import routes_pay
    monkeypatch.setattr(routes_pay, "send_payment",
                        lambda p: {"signature": "5" * 88, "explorer_url": solana_pay.explorer_url("5" * 88)})
    assert client.post("/pay", json={"scan_id": sid, "hours": 4, "approved": True}).status_code == 200
    st = client.get(f"/operators/dogwood/app-state?s={s}").json()
    assert (st["status"], st["hours"], st["amount_sol"], st["payment_method"]) == ("paid", 4, 0.04, "solana_devnet")
    assert st["receipt"]["signature"] == "5" * 88 and "cluster=devnet" in st["receipt"]["explorer_url"]
    assert abs(st["receipt"]["paid_at"] - time.time()) < 5
    r = client.post(f"/operators/dogwood/app-state?s={s}", json={"hours": 1})
    assert r.status_code == 409 and r.json()["error"] == "already_paid"


def test_app_link_one_time_and_expiry(monkeypatch):
    sid, other_sid = scanned(), scanned()
    first = app_token(sid)
    assert client.get(f"/operators/dogwood/app-state?s={first}").status_code == 200
    second = app_token(sid)                       # a newer link replaces the old one
    r = client.get(f"/operators/dogwood/app-state?s={first}")
    assert r.status_code == 401 and r.json()["error"] == "app_link_invalid"
    assert client.get(f"/operators/dogwood/app-state?s={second}").status_code == 200
    app_token(other_sid)                          # other scans don't interfere
    assert client.get(f"/operators/dogwood/app-state?s={second}").status_code == 200
    tampered = second[:-3] + ("AAA" if not second.endswith("AAA") else "BBB")
    assert client.get(f"/operators/dogwood/app-state?s={tampered}").json()["error"] == "app_link_invalid"
    assert client.get("/operators/dogwood/app-state").status_code == 401
    # An OAuth state is not an app link, even though both are signed by us.
    state = account_crypto.sign(dogwood.STATE_PURPOSE, {"sid": sid, "n": "x"}, 600)
    assert client.get(f"/operators/dogwood/app-state?s={state}").status_code == 401
    later = time.time() + 901
    monkeypatch.setattr(time, "time", lambda: later)
    r = client.get(f"/operators/dogwood/app-state?s={second}")
    assert r.status_code == 401 and r.json()["error"] == "app_link_expired"


def test_app_state_cors_for_demo_sites():
    s = app_token(scanned())
    r = client.get(f"/operators/dogwood/app-state?s={s}", headers={"Origin": "https://scansafe-demo-sites.vercel.app"})
    assert r.headers["access-control-allow-origin"] == "https://scansafe-demo-sites.vercel.app"


# --- E. PayPal sandbox ---------------------------------------------------------------------------

class FakePayPal:
    def __init__(self):
        self.calls: list[tuple[str, str, dict, dict]] = []
        self.order_status = "CREATED"
        self.capture_status = "COMPLETED"

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api-m.sandbox.paypal.com"      # never anything but the sandbox
        path = request.url.path
        try:
            body = json.loads(request.content) if request.content else {}
        except ValueError:
            body = {"form": request.content.decode()}
        self.calls.append((request.method, path, body, dict(request.headers)))
        if path == "/v1/oauth2/token":
            assert request.headers["authorization"].startswith("Basic ")
            return httpx.Response(200, json={"access_token": "A21-test-token", "expires_in": 32400})
        assert request.headers["authorization"] == "Bearer A21-test-token"
        if path == "/v3/vault/setup-tokens":
            return httpx.Response(201, json={"id": "SETUP-TOK-1", "status": "PAYER_ACTION_REQUIRED", "links": [
                {"rel": "self", "href": "https://api-m.sandbox.paypal.com/v3/vault/setup-tokens/SETUP-TOK-1"},
                {"rel": "approve", "href": "https://www.sandbox.paypal.com/agreements/approve?approval_session_id=S1"}]})
        if path == "/v3/vault/payment-tokens":
            return httpx.Response(201, json={"id": "VAULT-SECRET-9", "customer": {"id": "CUST-1"},
                                             "payment_source": {"paypal": {"email_address": "jane.doe@example.com"}}})
        if path == "/v3/vault/payment-tokens/VAULT-SECRET-9" and request.method == "DELETE":
            return httpx.Response(204)
        if path == "/v2/checkout/orders":
            done = {"payments": {"captures": [{"id": "CAP-1", "status": self.capture_status}]}}
            if self.order_status == "COMPLETED":
                return httpx.Response(201, json={"id": "ORDER-1", "status": "COMPLETED",
                                                 "purchase_units": [done]})
            return httpx.Response(201, json={"id": "ORDER-1", "status": self.order_status})
        if path == "/v2/checkout/orders/ORDER-1/capture":
            return httpx.Response(201, json={"id": "ORDER-1", "status": "COMPLETED", "purchase_units": [
                {"payments": {"captures": [{"id": "CAP-1", "status": self.capture_status}]}}]})
        return httpx.Response(404, json={"name": "RESOURCE_NOT_FOUND", "debug_id": "d1"})

    def paths(self) -> list[str]:
        return [f"{m} {p}" for m, p, _, _ in self.calls]


@pytest.fixture
def paypal(monkeypatch):
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "sandbox-client-id")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "sandbox-client-secret")
    monkeypatch.setenv("PAYPAL_ENV", "sandbox")
    fake = FakePayPal()
    monkeypatch.setattr(paypal_vault, "_http", lambda: REAL_CLIENT(transport=httpx.MockTransport(fake.handler)))
    return fake


def link_paypal(token: str, fake: FakePayPal) -> httpx.Response:
    r = client.get("/link/paypal/start", headers=bearer(token))
    assert r.status_code == 200, r.text
    assert r.json() == {"approve_url": "https://www.sandbox.paypal.com/agreements/approve?approval_session_id=S1"}
    setup = [c for c in fake.calls if c[1] == "/v3/vault/setup-tokens"][-1][2]["payment_source"]["paypal"]
    ret = urlparse(setup["experience_context"]["return_url"])
    assert f"{ret.scheme}://{ret.netloc}{ret.path}" == "https://api.scansafe.nyc/link/paypal/callback"
    state = parse_qs(ret.query)["state"][0]
    # PayPal appends approval_token_id (the setup token id) to the return URL.
    return client.get(f"/link/paypal/callback?state={state}&approval_token_id=SETUP-TOK-1&approval_session_id=S1",
                      follow_redirects=False)


def test_paypal_not_configured(monkeypatch):
    r = client.get("/link/paypal/start", headers=bearer(signed_in()))
    assert r.status_code == 503 and r.json()["error"] == "paypal_not_configured"
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "id")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "secret")
    for env in (None, "live", "production", "Sandbox2"):
        if env is None:
            monkeypatch.delenv("PAYPAL_ENV", raising=False)
        else:
            monkeypatch.setenv("PAYPAL_ENV", env)
        r = client.get("/link/paypal/start", headers=bearer(signed_in()))
        assert r.status_code == 503 and r.json()["error"] == "paypal_not_configured", env
    sid = scanned()
    r = client.post("/pay", json={"scan_id": sid, "hours": 1, "approved": True, "payment_method": "paypal"},
                    headers=bearer(signed_in()))
    assert r.status_code == 503 and r.json()["error"] == "paypal_not_configured"


def test_paypal_link_flow(paypal, monkeypatch):
    monkeypatch.setenv("APP_BASE_URL", "https://app.scansafe.nyc")
    token = signed_in()
    assert client.get("/link/paypal/start").status_code == 401
    r = link_paypal(token, paypal)
    assert r.status_code == 302 and r.headers["location"] == "https://app.scansafe.nyc/accounts?linked=paypal"
    setup = [c for c in paypal.calls if c[1] == "/v3/vault/setup-tokens"][0]
    src = setup[2]["payment_source"]["paypal"]
    assert src["usage_type"] == "MERCHANT" and src["experience_context"]["cancel_url"].endswith("&cancelled=1")
    assert setup[3]["paypal-request-id"].startswith("scansafe-setup-")
    pt = [c for c in paypal.calls if c[1] == "/v3/vault/payment-tokens"][0][2]
    assert pt == {"payment_source": {"token": {"id": "SETUP-TOK-1", "type": "SETUP_TOKEN"}}}
    me = client.get("/me", headers=bearer(token)).json()
    assert me["providers"]["paypal"] is True
    assert [(x["provider"], x["display"]) for x in me["linked"]] == [("paypal", "j•••@example.com")]
    (row,) = accounts_store._memory.linked_rows
    assert "VAULT-SECRET-9" not in stored_blob() and "CUST-1" not in stored_blob()
    assert account_crypto.decrypt(row["secret_enc"]) == {"vault_id": "VAULT-SECRET-9", "customer_id": "CUST-1"}
    assert row["meta"] == {"display": "j•••@example.com", "env": "sandbox"}
    assert client.put("/me", json={"preferred_payment": "paypal"}, headers=bearer(token)).json()["preferred_payment"] == "paypal"


def test_paypal_callback_refusals(paypal):
    token = signed_in()
    client.get("/link/paypal/start", headers=bearer(token))
    ret = [c for c in paypal.calls if c[1] == "/v3/vault/setup-tokens"][-1][2]["payment_source"]["paypal"]
    state = parse_qs(urlparse(ret["experience_context"]["return_url"]).query)["state"][0]
    r = client.get(f"/link/paypal/callback?state={state}&approval_token_id=SOMEONE-ELSES", follow_redirects=False)
    assert r.headers["location"].endswith("link_error=invalid_state&provider=paypal")
    r = client.get(f"/link/paypal/callback?state={state}&approval_token_id=SETUP-TOK-1", follow_redirects=False)
    assert r.headers["location"].endswith("link_error=invalid_state&provider=paypal")    # state spent
    client.get("/link/paypal/start", headers=bearer(token))
    ret = [c for c in paypal.calls if c[1] == "/v3/vault/setup-tokens"][-1][2]["payment_source"]["paypal"]
    r = client.get(urlparse(ret["experience_context"]["cancel_url"]).path + "?" +
                   urlparse(ret["experience_context"]["cancel_url"]).query, follow_redirects=False)
    assert r.headers["location"] == "https://scansafe.nyc/?link_error=cancelled&provider=paypal"
    assert client.get("/link/paypal/callback?state=junk&approval_token_id=SETUP-TOK-1",
                      follow_redirects=False).headers["location"].endswith("link_error=invalid_state&provider=paypal")
    assert accounts_store._memory.linked_rows == []
    assert "/v3/vault/payment-tokens" not in [c[1] for c in paypal.calls]


def pay(sid: str, token=None, **over):
    body = {"scan_id": sid, "hours": 3, "approved": True, "payment_method": "paypal", **over}
    return client.post("/pay", json=body, headers=bearer(token) if token else {})


def test_paypal_charge_meter(paypal):
    token = signed_in()
    link_paypal(token, paypal)
    sid = scanned()
    r = pay(sid, token)
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["ok"], body["method"], body["paypal_order_id"], body["amount_usd"], body["hours"]) == \
        (True, "paypal", "ORDER-1", 7.5, 3)
    assert "usd_note" not in body and body["payment"]["merchant_verified"] is True
    order = [c for c in paypal.calls if c[1] == "/v2/checkout/orders"][0]
    assert order[2]["intent"] == "CAPTURE"
    assert order[2]["payment_source"] == {"paypal": {"vault_id": "VAULT-SECRET-9"}}
    assert order[2]["purchase_units"][0]["amount"] == {"currency_code": "USD", "value": "7.50"}
    assert order[3]["paypal-request-id"] == f"scansafe-{sid}-750"
    assert "POST /v2/checkout/orders/ORDER-1/capture" in paypal.paths()
    st = client.get(f"/pay/status/{sid}").json()
    assert (st["state"], st["method"], st["paypal_order_id"], st["amount_usd"], st["hours"]) == \
        ("paid", "paypal", "ORDER-1", 7.5, 3)
    # One payment per scan, whatever the method.
    n = len(paypal.calls)
    assert pay(sid, token).json()["error"] == "already_paid"
    r = client.post("/pay", json={"scan_id": sid, "hours": 3, "approved": True})
    assert r.status_code == 409 and len(paypal.calls) == n
    # The Dogwood app view shows the PayPal receipt.
    s = app_token(sid)
    st = client.get(f"/operators/dogwood/app-state?s={s}").json()
    assert st["status"] == "paid" and st["payment_method"] == "paypal" and st["amount_usd"] == 7.5
    assert st["receipt"]["paypal_order_id"] == "ORDER-1" and st["receipt"]["signature"] is None


def test_quote_shows_the_paypal_price(monkeypatch):
    sid = scanned()
    q = client.post("/pay/quote", json={"scan_id": sid, "hours": 3}).json()
    assert (q["amount_sol"], q["rate_per_hour_usd"], q["amount_usd"]) == (0.03, 2.5, 7.5)
    for bad in ("abc", "-1", "NaN", "Infinity", "0"):
        monkeypatch.setenv("DOGWOOD_RATE_USD", bad)
        assert client.post("/pay/quote", json={"scan_id": sid, "hours": 1}).json()["amount_usd"] == 2.5, bad


def test_paypal_completed_on_create_and_custom_rate(paypal, monkeypatch):
    monkeypatch.setenv("DOGWOOD_RATE_USD", "1.25")
    paypal.order_status = "COMPLETED"
    token = signed_in()
    link_paypal(token, paypal)
    sid = scanned()
    assert client.post("/pay/quote", json={"scan_id": sid, "hours": 2}).json()["amount_usd"] == 2.5
    r = pay(sid, token, hours=2)
    assert r.status_code == 200 and r.json()["amount_usd"] == 2.5
    assert not any(p.endswith("/capture") for p in paypal.paths())


def test_paypal_fixed_price_uses_labelled_demo_rate(paypal):
    token = signed_in()
    link_paypal(token, paypal)
    r = pay(scanned(DINER_QR), token, hours=None)
    assert r.status_code == 200, r.text
    assert r.json()["amount_usd"] == 0.5 and "demo" in r.json()["usd_note"].lower()
    assert client.get(f"/pay/status/{r.json()['scan_id']}").json()["usd_note"] == r.json()["usd_note"]


def test_paypal_refusals(paypal, monkeypatch):
    token = signed_in()
    sid = scanned()
    assert pay(sid).status_code == 401                                         # not signed in
    r = pay(sid, token)
    assert r.status_code == 403 and r.json()["error"] == "paypal_not_linked"   # signed in, not linked
    link_paypal(token, paypal)
    assert pay(sid, token, approved=False).json()["error"] == "not_approved"
    r = pay(sid, token, hours=None)
    assert r.status_code == 400 and r.json()["error"] == "hours_required"
    assert pay(sid, token, hours=7).json()["error"] == "bad_hours"
    assert pay(sid, token, payment_method="venmo").json()["error"] == "bad_payment_method"
    monkeypatch.setenv("PAYPAL_MAX_USD", "5")
    assert pay(sid, token).json()["error"] == "over_cap"
    monkeypatch.delenv("PAYPAL_MAX_USD")
    # Someone else's linked PayPal is never used for my payment.
    assert pay(sid, signed_in(OTHER)).json()["error"] == "paypal_not_linked"
    assert not any("/v2/checkout/orders" in p for p in paypal.paths())
    assert client.get(f"/pay/status/{sid}").json()["state"] == "none"
    # A cookie from a foreign origin doesn't authorize a PayPal charge.
    r = client.post("/pay", json={"scan_id": sid, "hours": 3, "approved": True, "payment_method": "paypal"},
                    headers={**cookie(token), "Origin": "https://evil.example"})
    assert r.status_code == 401


def test_paypal_decline_then_retry(paypal):
    token = signed_in()
    link_paypal(token, paypal)
    sid = scanned()
    paypal.capture_status = "DECLINED"
    r = pay(sid, token)
    assert r.status_code == 402 and r.json()["error"] == "paypal_declined"
    st = client.get(f"/pay/status/{sid}").json()
    assert st["state"] == "failed" and st["method"] == "paypal"
    paypal.capture_status = "COMPLETED"
    assert pay(sid, token, hours=2).status_code == 200


def test_paypal_disconnect_resets_preference_and_deletes_vault_token(paypal):
    token = signed_in()
    link_paypal(token, paypal)
    client.put("/me", json={"preferred_payment": "paypal"}, headers=bearer(token))
    r = client.delete("/me/linked/paypal", headers=bearer(token))
    assert r.json()["revoked"] is True
    assert "DELETE /v3/vault/payment-tokens/VAULT-SECRET-9" in paypal.paths()
    me = client.get("/me", headers=bearer(token)).json()
    assert me["linked"] == [] and me["preferred_payment"] == "solana_devnet"
    assert pay(scanned(), token).json()["error"] == "paypal_not_linked"


def test_paypal_unreachable_is_502(paypal, monkeypatch):
    def down():
        def handler(request):
            raise httpx.ConnectError("down")
        return REAL_CLIENT(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(paypal_vault, "_http", down)
    r = client.get("/link/paypal/start", headers=bearer(signed_in()))
    assert r.status_code == 502 and r.json()["error"] == "paypal_unreachable"


def test_secrets_never_logged(paypal, caplog):
    caplog.set_level("DEBUG")
    token = signed_in()
    link_paypal(token, paypal)
    pay(scanned(), token)
    link_dogwood(token)
    text = caplog.text
    for secret in ("sandbox-client-secret", "A21-test-token", "VAULT-SECRET-9", os.environ["ACCOUNT_KEY"],
                   token, "dwat_", dogwood.client_secret()):
        assert secret not in text


# --- Tiger store (SQL path, fake connection) -----------------------------------------------------

class FakeConn:
    def __init__(self, log):
        self.log = log

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def transaction(self):
        return contextlib.nullcontext()

    def execute(self, sql, params=None):
        self.log.append((sql, params))
        now = datetime.now(timezone.utc)
        row = None
        if sql.startswith("INSERT INTO linked_accounts"):
            row = {"provider": params[1], "meta": params[3].obj, "linked_at": now}
        elif sql.startswith("INSERT INTO accounts"):
            row = {"plate": params[1], "preferred_payment": None, "created_at": now, "updated_at": now}

        class Cur:
            def fetchone(self):
                return row

            def fetchall(self):
                return [row] if row else []
        return Cur()


def test_tiger_store_creates_tables_and_stores_only_ciphertext(monkeypatch):
    log: list = []
    monkeypatch.setenv("ACCOUNTS_STORE", "tiger")
    monkeypatch.setenv("TIGER_DATABASE_URL", "postgres://x")
    monkeypatch.setattr(tiger_store, "_connect", lambda: FakeConn(log))
    monkeypatch.setattr(accounts_store._tiger, "_ready", False)
    token = signed_in()
    assert client.put("/me", json={"plate": "abc123"}, headers=bearer(token)).status_code == 200
    created = [sql for sql, _ in log if sql.lstrip().startswith("CREATE")]
    assert len(created) == 3 and "accounts" in created[0] and "linked_accounts" in created[1]
    assert "WHERE revoked_at IS NULL" in created[2]
    upsert = [(sql, p) for sql, p in log if sql.startswith("INSERT INTO accounts")][0]
    assert "ON CONFLICT (phone_hash) DO UPDATE SET plate = EXCLUDED.plate" in upsert[0]
    assert upsert[1] == (account_crypto.phone_hash(PHONE), "ABC123")
    link_dogwood(token)
    ins = [p for sql, p in log if sql.startswith("INSERT INTO linked_accounts")][0]
    assert ins[0] == account_crypto.phone_hash(PHONE) and ins[1] == "dogwood"
    plain = account_crypto.decrypt(ins[2])["access_token"]
    assert plain not in repr(log).replace(ins[2], "")                    # only the ciphertext went in
    assert ins[3].obj == {"account_name": "Dogwood Parking", "scope": "pay_parking"}
    assert len([s for s, _ in log if s.lstrip().startswith("CREATE")]) == 3   # created once


def test_setup_mentions_accounts(capsys):
    from data import setup
    assert setup.main() == 1
    assert capsys.readouterr().out.count("SKIP Tiger Data") == 2
