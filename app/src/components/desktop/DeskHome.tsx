"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useLenis } from "lenis/react";
import LiveCheck, { createLiveFeed, type LiveFeed } from "@/components/LiveCheck";
import ResultView from "@/components/ResultView";
import SplitText from "@/components/reactbits/SplitText/SplitText";
import StarBorder from "@/components/reactbits/StarBorder/StarBorder";
import { DEMO_MODE, getPins, scanUrlLive } from "@/lib/api";
import type { Pin, ScanResult } from "@/lib/types";
import DeskStatTiles from "./DeskStatTiles";
import Reveal from "./Reveal";
import VantaNet from "./VantaNet";
import s from "./home.module.css";

const ScamMap = dynamic(() => import("@/components/ScamMap"), {
  ssr: false,
  loading: () => <p className="progress" role="status">Loading the map…</p>,
});

const ATLANTA: [number, number] = [33.79, -84.32];

type Phase =
  | { kind: "idle" }
  | { kind: "checking"; feed: LiveFeed }
  | { kind: "result"; result: ScanResult }
  | { kind: "error"; url: string; msg: string };

const STEPS = [
  { title: "Paste the link", body: "Got a strange link in an email or a text? Paste it above. Nothing opens on your computer." },
  { title: "We open it, not you", body: "The link opens in a throwaway, locked-down browser on our server. It can’t reach private networks, and it’s thrown away after." },
  { title: "AI checks for tricks", body: "Jev scores the page for pretending to be someone else, asking for passwords or card numbers, and hidden tricks. Gemini explains what it found in plain words." },
  { title: "You get a clear answer", body: "Looks safe, be careful, or stop: this is a scam. Scams get pinned on the map so your neighbors are warned." },
];

const BUILT_WITH = [
  "Vultr", "Chert", "LiveKit", "Google Gemini", "Jev (via OpenRouter)", "Typesense", "Tiger Data", "Solana (devnet)",
  "Coder", "Next.js", "FastAPI", "Playwright", "Docker", "react-bits", "Vanta.js", "GSAP", "Lenis",
];

export default function DeskHome() {
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const [link, setLink] = useState("");
  const [pins, setPins] = useState<Pin[]>([]);
  const [mapActive, setMapActive] = useState(false);
  const statusRef = useRef<HTMLDivElement>(null);
  const scanAbort = useRef<AbortController | null>(null);
  const lenis = useLenis();

  const toTop = () => (lenis ? lenis.scrollTo(0, { immediate: true }) : window.scrollTo({ top: 0 }));

  useEffect(() => {
    let alive = true;
    void getPins(ATLANTA[0], ATLANTA[1], 5).then((r) => { if (alive) setPins(r.pins); });
    return () => { alive = false; scanAbort.current?.abort(); };
  }, []);

  async function check(raw: string) {
    const url = raw.trim();
    if (!url) return;
    scanAbort.current?.abort();
    const ctrl = new AbortController();
    scanAbort.current = ctrl;
    const feed = createLiveFeed(url);
    setPhase({ kind: "checking", feed });
    toTop();
    requestAnimationFrame(() => statusRef.current?.focus({ preventScroll: true }));
    try {
      // Desktop never sends a location.
      const result = await scanUrlLive(url, null, feed.handlers, ctrl.signal);
      if (ctrl.signal.aborted) return;
      setPhase({ kind: "result", result });
    } catch {
      if (ctrl.signal.aborted) return;
      setPhase({ kind: "error", url, msg: "We couldn't check this link right now. Please don't open it yet. Try again in a moment." });
    }
    toTop();
  }

  function reset() {
    setPhase({ kind: "idle" });
    setLink("");
    toTop();
  }

  if (phase.kind === "checking") {
    return <section className={s.flow}><LiveCheck feed={phase.feed} statusRef={statusRef} /></section>;
  }
  if (phase.kind === "result") {
    return <section className={s.flow}><ResultView result={phase.result} onDone={reset} facetime={null} /></section>;
  }

  return (
    <>
      <section className={s.hero} aria-labelledby="desk-title">
        <VantaNet className={s.heroBg} />
        <div className={s.heroContent}>
          <p className={s.eyebrow}>EmoryHacks 2026 · Security track</p>
          <h1 id="desk-title" className={s.title} aria-label="Check a link before you open it.">
            <SplitText text="Check a link before you open it." tag="span" textAlign="left" splitType="words, chars" trigger="load" />
          </h1>
          <p className={s.sub}>We open it on our own locked-down computer, check it for scams, and tell you in plain words.</p>

          {DEMO_MODE && <p className="notice"><span className="demo-badge">Demo mode</span> No server is connected, so results are sample data.</p>}
          {phase.kind === "error" && (
            <div className="notice bad" role="alert">
              <p style={{ margin: 0 }}>{phase.msg}</p>
              <button type="button" className="btn" style={{ marginTop: "0.75rem" }} onClick={() => check(phase.url)}>Try again</button>
            </div>
          )}

          <form className={s.form} onSubmit={(e) => { e.preventDefault(); void check(link); }}>
            <label htmlFor="desk-link" className="sr-only">Link to check</label>
            <input
              id="desk-link"
              className={s.input}
              type="text"
              inputMode="url"
              autoComplete="off"
              spellCheck={false}
              placeholder="Paste a link from an email or text…"
              value={link}
              onChange={(e) => setLink(e.target.value)}
            />
            <StarBorder as="button" type="submit" className={s.checkBtn} color="#0ae448" disabled={!link.trim()}>
              Check this link
            </StarBorder>
          </form>
        </div>
      </section>

      <Reveal>
        <section className={s.section} aria-labelledby="map-h">
          <p className={s.kicker}>Scam map</p>
          <h2 id="map-h" className={s.h2}>Scam QR codes reported near you</h2>
          <p className={s.lead}>Red pins are codes people reported. Click one to see what it was.</p>
          {/* The wheel scrolls the page until the map is clicked; leaving the map hands the wheel back. */}
          <div className={s.mapBox} onMouseLeave={() => setMapActive(false)}>
            <div className={s.mapInner} data-lenis-prevent style={{ pointerEvents: mapActive ? "auto" : "none" }}>
              <ScamMap center={ATLANTA} pins={pins} focus={null} />
            </div>
            {!mapActive && (
              <button type="button" className={s.mapCover} onClick={() => setMapActive(true)}>
                <span>Click to explore the map</span>
              </button>
            )}
          </div>
          <Link href="/map" className={s.more}>Open the full map →</Link>
        </section>
      </Reveal>

      <Reveal>
        <section className={s.section} aria-labelledby="how-h">
          <p className={s.kicker}>How it works</p>
          <h2 id="how-h" className={s.h2}>Four steps. Your computer never opens the link.</h2>
          <ol className={s.steps}>
            {STEPS.map((st, i) => (
              <li key={st.title} className={s.step}>
                <span className={s.stepNum} aria-hidden="true">{i + 1}</span>
                <h3 className={s.h3}>{st.title}</h3>
                <p>{st.body}</p>
              </li>
            ))}
          </ol>
        </section>
      </Reveal>

      <Reveal>
        <section className={s.section} aria-labelledby="stats-h">
          <p className={s.kicker}>Live numbers</p>
          <h2 id="stats-h" className={s.h2}>What people checked with ScanSafe</h2>
          <DeskStatTiles />
          <Link href="/dashboard" className={s.more}>See all stats →</Link>
        </section>
      </Reveal>

      <Reveal>
        <section className={s.section} aria-labelledby="built-h">
          <p className={s.kicker}>Under the hood</p>
          <h2 id="built-h" className={s.h2}>Built with</h2>
          <ul className={s.chips}>{BUILT_WITH.map((t) => <li key={t} className={s.chip}>{t}</li>)}</ul>
        </section>
      </Reveal>

      <footer className={s.footer}>
        <p>Made at EmoryHacks 2026 · Atlanta</p>
        <p><a href="https://github.com/jzps333/HackEmory-2026" target="_blank" rel="noopener noreferrer">View the code on GitHub<span className="sr-only"> (opens in a new tab)</span></a></p>
      </footer>
    </>
  );
}
