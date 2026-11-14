"use client";

/**
 * "Get Dogwood Parking": a store-style install screen for the made-up official app.
 * Inert: Install only plays a 2.5 s progress bar (nothing is downloaded or installed), then
 * Open links to /dogwood/app with the same ?s session. No network requests.
 * Stable selectors for the ScanSafe operator automation: data-testid="install" and "open".
 */
import { useEffect, useRef, useState } from "react";
import { AppIcon, GREEN, Shell, queryParam } from "../shared";

const INSTALL_MS = 2500;

export default function InstallClient() {
  const [session, setSession] = useState("");
  const [phase, setPhase] = useState<"get" | "installing" | "open">("get");
  const [pct, setPct] = useState(0);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    setSession(queryParam("s"));
    return () => { if (timer.current) clearInterval(timer.current); };
  }, []);

  function install() {
    if (phase !== "get") return;
    setPhase("installing");
    const started = Date.now();
    timer.current = setInterval(() => {
      const p = Math.min(100, Math.round(((Date.now() - started) / INSTALL_MS) * 100));
      setPct(p);
      if (p >= 100) {
        if (timer.current) clearInterval(timer.current);
        setPhase("open");
      }
    }, 100);
  }

  const openHref = session ? `/dogwood/app?s=${encodeURIComponent(session)}` : "/dogwood/app";

  return (
    <Shell>
      <div className="dw-muted" style={{ fontWeight: 700, margin: "4px 0 14px" }}>Apps · Parking</div>
      <div className="dw-card" style={{ display: "flex", gap: 14, alignItems: "center" }}>
        <AppIcon size={92} />
        <div style={{ minWidth: 0 }}>
          <h1 style={{ marginBottom: 2 }}>Dogwood Parking</h1>
          <div style={{ fontSize: 15, color: GREEN, fontWeight: 700 }}>Official app by Dogwood Lot &amp; Meter Co.</div>
          <div className="dw-muted">Parking · Free</div>
        </div>
      </div>

      <div style={{ marginBottom: 16 }} aria-live="polite">
        {phase === "get" && (
          <button type="button" className="dw-btn" data-testid="install" onClick={install}>Install</button>
        )}
        {phase === "installing" && (
          <div data-testid="installing" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}
            aria-label="Installing Dogwood Parking">
            <div style={{ display: "flex", justifyContent: "space-between", fontWeight: 700, marginBottom: 6 }}>
              <span>Installing…</span><span>{pct}%</span>
            </div>
            <div style={{ height: 14, background: "#dfe8e2", borderRadius: 7, overflow: "hidden" }}>
              <div style={{ width: `${pct}%`, height: "100%", background: GREEN, transition: "width 100ms linear" }} />
            </div>
          </div>
        )}
        {phase === "open" && (
          <a className="dw-btn" data-testid="open" href={openHref}>Open</a>
        )}
      </div>

      <div className="dw-card">
        <h2>About this app</h2>
        <p>Pay for parking at Dogwood lots and meters. Pick your hours, check your plate, and pay with your
          linked ScanSafe account.</p>
        <p style={{ marginBottom: 0 }}>Every payment still needs your OK in ScanSafe. This app never asks for
          your card number.</p>
      </div>

      <div className="dw-card" aria-label="App details">
        <div className="dw-row"><span>Publisher</span><span>Dogwood Lot &amp; Meter Co.</span></div>
        <div className="dw-row"><span>Category</span><span>Parking</span></div>
        <div className="dw-row"><span>Price</span><span>Free</span></div>
        <div className="dw-row"><span>Payments</span><span>Devnet test SOL only</span></div>
      </div>
    </Shell>
  );
}
