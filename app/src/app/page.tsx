"use client";

import { useRef, useState } from "react";
import Scanner from "@/components/Scanner";
import ResultView from "@/components/ResultView";
import { DEMO_MODE, scanUrl } from "@/lib/api";
import type { ScanResult } from "@/lib/types";

type Phase = { kind: "idle" } | { kind: "checking"; url: string } | { kind: "result"; result: ScanResult } | { kind: "error"; url: string; msg: string };

function getLocation(): Promise<[number, number] | null> {
  return new Promise((resolve) => {
    if (!("geolocation" in navigator)) return resolve(null);
    navigator.geolocation.getCurrentPosition(
      // Round to ~100 m before it ever leaves the phone.
      (p) => resolve([Math.round(p.coords.latitude * 1000) / 1000, Math.round(p.coords.longitude * 1000) / 1000]),
      () => resolve(null),
      { enableHighAccuracy: false, timeout: 8000, maximumAge: 300000 },
    );
  });
}

export default function ScanPage() {
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const [link, setLink] = useState("");
  const [shareLocation, setShareLocation] = useState(false);
  const statusRef = useRef<HTMLDivElement>(null);

  // Location is off every time the page loads; the user has to turn it on.
  function toggleLocation(on: boolean) {
    setShareLocation(on);
  }

  async function check(raw: string) {
    const url = raw.trim();
    if (!url) return;
    setPhase({ kind: "checking", url });
    window.scrollTo({ top: 0 });
    requestAnimationFrame(() => statusRef.current?.focus());
    const loc = shareLocation ? await getLocation() : null;
    try {
      const result = await scanUrl(url, loc);
      setPhase({ kind: "result", result });
    } catch {
      setPhase({ kind: "error", url, msg: "We couldn't check this link right now. Please don't open it yet. Try again in a moment." });
    }
  }

  function reset() {
    setPhase({ kind: "idle" });
    setLink("");
  }

  if (phase.kind === "checking") {
    return (
      <div className="progress" role="status" aria-live="polite" tabIndex={-1} ref={statusRef}>
        <div className="spinner" aria-hidden="true" />
        <p>Opening it safely on our server…</p>
        <p className="hint" style={{ fontSize: "1rem", fontWeight: 400 }}>Nothing opens on your phone. This usually takes a few seconds.</p>
      </div>
    );
  }

  if (phase.kind === "result") return <ResultView result={phase.result} onDone={reset} />;

  return (
    <>
      <h1>Check a QR code before you open it</h1>
      <p>We open the link on our own server, look for scams, and tell you in plain words if it&apos;s safe.</p>
      {DEMO_MODE && (
        <p className="notice"><span className="demo-badge">Demo mode</span> No server is connected, so results are sample data. Paste a link starting with &quot;solana:&quot; to see a safe payment, or anything else to see a scam.</p>
      )}

      {phase.kind === "error" && (
        <div className="notice bad" role="alert">
          <p style={{ margin: 0 }}>{phase.msg}</p>
          <button type="button" className="btn" style={{ marginTop: "0.75rem" }} onClick={() => check(phase.url)}>Try again</button>
        </div>
      )}

      <Scanner onResult={check} />

      <div className="divider" aria-hidden="true">or</div>

      <form onSubmit={(e) => { e.preventDefault(); void check(link); }} aria-labelledby="paste-h">
        <h2 id="paste-h" style={{ marginTop: 0 }}>Paste a link</h2>
        <label htmlFor="link-input">Link or QR code text</label>
        <input
          id="link-input"
          type="text"
          inputMode="url"
          autoComplete="off"
          autoCapitalize="off"
          spellCheck={false}
          placeholder="https://…"
          value={link}
          onChange={(e) => setLink(e.target.value)}
          aria-describedby="link-hint"
        />
        <p id="link-hint" className="hint">Got a link in a text message? Paste it here and we&apos;ll check it.</p>
        <button type="submit" className="btn btn-primary" disabled={!link.trim()}>Check this link</button>
      </form>

      <section className="card" aria-labelledby="loc-h" style={{ marginTop: "1.5rem" }}>
        <h2 id="loc-h" className="sr-only">Location</h2>
        <label className="toggle" htmlFor="loc-toggle" style={{ marginBottom: 0 }}>
          <span>Share my rough location<span className="hint" style={{ display: "block", fontWeight: 400 }}>Helps warn people nearby about scam QR codes. Rounded to about 100 meters. Off unless you turn it on.</span></span>
          <span style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
            <span className="toggle-state" aria-hidden="true">{shareLocation ? "On" : "Off"}</span>
            <input id="loc-toggle" type="checkbox" role="switch" checked={shareLocation} onChange={(e) => toggleLocation(e.target.checked)} />
          </span>
        </label>
      </section>
    </>
  );
}
