"use client";

import { useEffect, useRef, useState } from "react";
import Scanner from "@/components/Scanner";
import ResultView from "@/components/ResultView";
import { OnboardingFlow } from "@/components/onboarding/OnboardingFlow";
import { clearProfile, loadProfile, saveProfile, type Profile } from "@/lib/profile";
import type { OnboardingData } from "@/lib/onboarding";
import LiveCheck, { createLiveFeed, type LiveFeed } from "@/components/LiveCheck";
import { DEMO_MODE, scanUrlLive } from "@/lib/api";
import type { ScanResult } from "@/lib/types";

type Phase = { kind: "idle" } | { kind: "checking"; url: string; feed: LiveFeed } | { kind: "result"; result: ScanResult } | { kind: "error"; url: string; msg: string };

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
  // undefined = still reading this phone's saved profile; null = first visit, show onboarding.
  const [profile, setProfile] = useState<Profile | null | undefined>(undefined);
  const statusRef = useRef<HTMLDivElement>(null);
  const linkRef = useRef<HTMLInputElement>(null);
  // The scan in flight, so a new scan (or leaving the page) stops the old live stream.
  const scanAbort = useRef<AbortController | null>(null);

  useEffect(() => {
    const saved = loadProfile();
    setProfile(saved);
    // Location stays off unless they chose to share it during onboarding.
    if (saved?.location) setShareLocation(true);
    return () => scanAbort.current?.abort();
  }, []);

  function toggleLocation(on: boolean) {
    setShareLocation(on);
  }

  async function finishOnboarding(data: OnboardingData) {
    const saved = saveProfile(data);
    setShareLocation(!!saved.location);
    // Let the "You're all set" message show for a moment, then open the scanner (from the top).
    window.setTimeout(() => {
      setProfile(saved);
      window.scrollTo({ top: 0 });
    }, 1200);
  }

  function editDetails() {
    clearProfile();
    setProfile(null);
    reset();
  }

  async function check(raw: string) {
    const url = raw.trim();
    if (!url) return;
    scanAbort.current?.abort();
    const ctrl = new AbortController();
    scanAbort.current = ctrl;
    const feed = createLiveFeed(url);
    setPhase({ kind: "checking", url, feed });
    window.scrollTo({ top: 0 });
    // Focus the step text for screen readers without letting focus scroll only it into view, then show
    // the whole checking card (title, live view and steps), which LiveCheck sizes to fit the screen.
    requestAnimationFrame(() => {
      const el = statusRef.current;
      el?.focus({ preventScroll: true });
      el?.closest("section")?.scrollIntoView({ block: "nearest" });
    });
    const saved = profile?.location ? [profile.location.latitude, profile.location.longitude] as [number, number] : null;
    const loc = shareLocation ? (await getLocation()) ?? saved : null;
    if (ctrl.signal.aborted) return;
    try {
      const result = await scanUrlLive(url, loc, feed.handlers, ctrl.signal);
      if (ctrl.signal.aborted) return;
      setPhase({ kind: "result", result });
      // The checking screen may have scrolled the header away; start the verdict at the top.
      window.scrollTo({ top: 0 });
    } catch {
      if (ctrl.signal.aborted) return;
      setPhase({ kind: "error", url, msg: "We couldn't check this link right now. Please don't open it yet. Try again in a moment." });
      window.scrollTo({ top: 0 });
    }
  }

  function reset() {
    setPhase({ kind: "idle" });
    setLink("");
  }

  if (phase.kind === "checking") {
    return <LiveCheck feed={phase.feed} statusRef={statusRef} />;
  }

  if (profile === undefined) return null;
  if (profile === null) return <OnboardingFlow onComplete={finishOnboarding} />;

  if (phase.kind === "result") {
    const facetime = profile.facetimeOk && profile.phoneE164
      ? { phone: profile.phoneE164, location: shareLocation && profile.location ? [profile.location.latitude, profile.location.longitude] as [number, number] : null }
      : null;
    return <ResultView result={phase.result} onDone={reset} facetime={facetime} />;
  }

  return (
    <>
      <h1>{profile.fullName ? `Hi ${profile.fullName.split(" ")[0]}. ` : ""}Check a QR code before you open it</h1>
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

      <Scanner
        onResult={check}
        onPasteInstead={() => {
          linkRef.current?.focus();
          linkRef.current?.scrollIntoView({ block: "center" });
        }}
      />

      <div className="divider" aria-hidden="true">or</div>

      <form onSubmit={(e) => { e.preventDefault(); void check(link); }} aria-labelledby="paste-h">
        <h2 id="paste-h" style={{ marginTop: 0 }}>Paste a link</h2>
        <label htmlFor="link-input">Link or QR code text</label>
        <input
          id="link-input"
          ref={linkRef}
          type="text"
          inputMode="url"
          enterKeyHint="go"
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
        <label className="toggle stacked" htmlFor="loc-toggle" style={{ marginBottom: 0 }}>
          <span className="toggle-title">Share my rough location</span>
          <span className="toggle-control">
            <span className="toggle-state" aria-hidden="true">{shareLocation ? "On" : "Off"}</span>
            <input id="loc-toggle" type="checkbox" role="switch" checked={shareLocation} onChange={(e) => toggleLocation(e.target.checked)} />
          </span>
          <span className="hint toggle-desc">Helps warn people nearby about scam QR codes. Rounded to about 100 meters. Off unless you turn it on.</span>
        </label>
      </section>

      <p className="hint" style={{ marginTop: "1.5rem", textAlign: "center" }}>
        Set up as {profile.fullName || "you"}.{" "}
        <button type="button" className="link-button" onClick={editDetails}>Change my details</button>
      </p>
    </>
  );
}
