"use client";

/**
 * Dogwood's consent screen for linking ScanSafe (made-up brand, demo only):
 *   /dogwood/authorize?client_id=...&redirect_uri=...&scope=...&state=...&display=<masked phone>
 * Allow / Deny POSTs JSON {client_id, redirect_uri, scope, state, decision: "allow" | "deny"} to
 * {API}/operators/dogwood/oauth/authorize, then goes to the `redirect` it returns.
 * Errors are shown in plain words. No passwords or card numbers are ever asked for here.
 */
import { useEffect, useState } from "react";
import { API_BASE, AppIcon, GREEN, Shell, errorText, queryParam } from "../shared";

type Params = { client_id: string; redirect_uri: string; scope: string; state: string; display: string };

const AUTHORIZE_URL = `${API_BASE}/operators/dogwood/oauth/authorize`;

export default function AuthorizeClient() {
  const [p, setP] = useState<Params | null>(null);
  const [busy, setBusy] = useState<"" | "allow" | "deny">("");
  const [error, setError] = useState("");
  const [leaving, setLeaving] = useState(false);

  useEffect(() => {
    setP({
      client_id: queryParam("client_id"), redirect_uri: queryParam("redirect_uri"), scope: queryParam("scope"),
      state: queryParam("state"), display: queryParam("display").slice(0, 40),
    });
  }, []);

  const missing = p !== null && (!p.client_id || !p.redirect_uri || !p.state);

  async function decide(decision: "allow" | "deny") {
    if (!p || busy || missing) return;
    setBusy(decision);
    setError("");
    try {
      const res = await fetch(AUTHORIZE_URL, {
        method: "POST", headers: { "Content-Type": "application/json" }, cache: "no-store",
        body: JSON.stringify({ client_id: p.client_id, redirect_uri: p.redirect_uri, scope: p.scope, state: p.state, decision }),
      });
      if (!res.ok) {
        setError(await errorText(res));
        setBusy("");
        return;
      }
      const body = await res.json().catch(() => null);
      const redirect = body && typeof body.redirect === "string" ? body.redirect : "";
      if (!/^https?:\/\//i.test(redirect)) {
        setError("Dogwood answered, but didn't say where to go next. Go back to ScanSafe and try again.");
        setBusy("");
        return;
      }
      setLeaving(true);
      window.location.href = redirect;
    } catch {
      setError("Couldn't reach Dogwood. Check your connection and try again.");
      setBusy("");
    }
  }

  return (
    <Shell>
      <div style={{ display: "flex", alignItems: "center", gap: 10, margin: "6px 0 16px" }}>
        <AppIcon size={44} />
        <div>
          <div style={{ fontWeight: 800, fontSize: 18 }}>Dogwood Parking</div>
          <div className="dw-muted">Dogwood Lot &amp; Meter Co.</div>
        </div>
      </div>

      <div className="dw-card" data-testid="consent">
        <h1 style={{ fontSize: 22 }}>ScanSafe wants to:</h1>
        <div style={{ display: "flex", gap: 10, alignItems: "flex-start", padding: "10px 0 12px" }}>
          <svg width="26" height="26" viewBox="0 0 26 26" aria-hidden="true" style={{ flex: "none", marginTop: 1 }}>
            <circle cx="13" cy="13" r="13" fill={GREEN} />
            <path d="M7 13.5 L11 17.5 L19 9" fill="none" stroke="#fff" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <div style={{ fontSize: 18, fontWeight: 700 }}>Pay for parking with your Dogwood account.</div>
        </div>
        {p?.display && (
          <div className="dw-row" style={{ borderTop: "1px solid #edf1ee" }}>
            <span>Dogwood account</span><span data-testid="display">{p.display}</span>
          </div>
        )}
        <p className="dw-muted" style={{ margin: "12px 0 0" }}>
          You still approve every payment in ScanSafe. You can disconnect ScanSafe from your Dogwood account
          anytime, in Dogwood Parking or in ScanSafe.
        </p>
      </div>

      {missing && (
        <div className="dw-alert" role="alert">This link is missing some details. Go back to ScanSafe and try again.</div>
      )}
      {error && <div className="dw-alert" role="alert" data-testid="error">{error}</div>}
      {leaving && <div className="dw-note" role="status">Going back to ScanSafe…</div>}

      <div style={{ display: "grid", gap: 10 }}>
        <button type="button" className="dw-btn" data-testid="allow" onClick={() => decide("allow")}
          disabled={!p || missing || !!busy || leaving}>
          {busy === "allow" ? "Allowing…" : "Allow"}
        </button>
        <button type="button" className="dw-btn secondary" data-testid="deny" onClick={() => decide("deny")}
          disabled={!p || missing || !!busy || leaving}>
          {busy === "deny" ? "Saying no…" : "Deny"}
        </button>
      </div>
      <p className="dw-muted" style={{ textAlign: "center", marginTop: 12 }}>
        Dogwood never asks for your ScanSafe password here.
      </p>
    </Shell>
  );
}
