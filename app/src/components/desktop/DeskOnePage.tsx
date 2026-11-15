"use client";

import { useEffect, useRef, useState } from "react";
import { useLenis } from "lenis/react";
import LiveCheck, { createLiveFeed, type LiveFeed } from "@/components/LiveCheck";
import ResultView from "@/components/ResultView";
import DashboardClient from "@/app/dashboard/DashboardClient";
import { Icon } from "@/components/onboarding/Icon";
import SplitText from "@/components/reactbits/SplitText/SplitText";
import StarBorder from "@/components/reactbits/StarBorder/StarBorder";
import ScrollReveal from "@/components/reactbits/ScrollReveal/ScrollReveal";
import SpotlightCard from "@/components/reactbits/SpotlightCard/SpotlightCard";
import Radar from "@/components/reactbits/Radar/Radar";
import { GridScan } from "@/components/reactbits/GridScan/GridScan";
import { DEMO_MODE, scanUrlLive } from "@/lib/api";
import type { ScanResult } from "@/lib/types";
import DeskStatTiles from "./DeskStatTiles";
import MapSection from "./MapSection";
import Reveal from "./Reveal";
import Section from "./Section";
import VantaScene from "./VantaScene";
import s from "./onepage.module.css";

const LIME = 0x0ae448;
const LIGHT_LIME = 0xabff84;
const BLACK = 0x000000;
const LIME_GLOW = "rgba(10, 228, 68, 0.28)";
const FACETIME_HREF = "facetime:+16504444331";
const FACETIME_NUMBER = "+1 (650) 444-4331";

type IconName = Parameters<typeof Icon>[0]["name"];

type Phase =
  | { kind: "idle" }
  | { kind: "checking"; feed: LiveFeed }
  | { kind: "result"; result: ScanResult }
  | { kind: "error"; url: string; msg: string };

const PLACES = ["Parking meters", "Restaurant menus", "Flyers and posters", "Payment requests"];

const STEPS = [
  { title: "Paste the link", body: "Got a strange link in an email or a text? Paste it at the top. Nothing opens on your computer." },
  { title: "We open it, not you", body: "The link opens in a throwaway, locked-down browser on our server. It can’t reach private networks, and it’s thrown away after." },
  { title: "AI checks for tricks", body: "Jev scores the page for pretending to be someone else, asking for passwords or card numbers, and hidden tricks. Gemini explains what it found in plain words." },
  { title: "You get a clear answer", body: "Looks safe, be careful, or stop: this is a scam. Scams get pinned on the map so your neighbors are warned." },
];

const FEATURES: { icon: IconName; title: string; body: string; by: string }[] = [
  { icon: "phone", title: "Live view on FaceTime", body: "Call us and hold the code up to your camera. We check it, tell you out loud, and you can watch the page open live.", by: "With Chert" },
  { icon: "help", title: "Plain-language answers", body: "No tech words. You get what we found and what to do next, in a sentence or two.", by: "With Google Gemini" },
  { icon: "location", title: "Scam map near you", body: "See where fake codes were reported nearby, so you know which meters and flyers to skip.", by: "With Typesense geosearch" },
  { icon: "target", title: "Trends dashboard", body: "See how many codes were checked and how many turned out to be scams, hour by hour.", by: "With Tiger Data" },
  { icon: "wallet", title: "Safe payments check", body: "Solana Pay codes are checked before you pay: who gets the money and how much. Test money (devnet) only, and you approve every payment.", by: "With Solana (devnet)" },
  { icon: "user", title: "Accessible by design", body: "Big text, large buttons, results read aloud, and simple words. Built for anyone, including grandparents.", by: "For everyone" },
];

const BUILT_WITH = [
  "Vultr", "Chert", "LiveKit", "Google Gemini", "Jev (via OpenRouter)", "Typesense", "Tiger Data", "Solana (devnet)",
  "Coder", "Next.js", "FastAPI", "Playwright", "Docker", "react-bits", "Vanta.js", "GSAP", "Lenis",
];

export default function DeskOnePage() {
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const [link, setLink] = useState("");
  const statusRef = useRef<HTMLDivElement>(null);
  const scanAbort = useRef<AbortController | null>(null);
  const lenis = useLenis();

  const toTop = () => (lenis ? lenis.scrollTo(0, { immediate: true }) : window.scrollTo({ top: 0 }));

  useEffect(() => () => scanAbort.current?.abort(), []);

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

  const inFlow = phase.kind === "checking" || phase.kind === "result";

  return (
    <>
      {phase.kind === "checking" && <section className={s.flow}><LiveCheck feed={phase.feed} statusRef={statusRef} /></section>}
      {phase.kind === "result" && <section className={s.flow}><ResultView result={phase.result} onDone={reset} facetime={null} /></section>}

      {/* The page stays mounted (just hidden) while a check runs, so the map and scroll position survive. */}
      <div hidden={inFlow}>
        <Section id="top" labelledBy="desk-title" className={s.hero} bg={<VantaScene className={s.fill} effect="net" options={{ color: LIME, backgroundColor: BLACK }} />}>
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
            <input id="desk-link" className={s.input} type="text" inputMode="url" autoComplete="off" spellCheck={false}
              placeholder="Paste a link from an email or text…" value={link} onChange={(e) => setLink(e.target.value)} />
            <StarBorder as="button" type="submit" className={s.checkBtn} color="#0ae448" disabled={!link.trim()}>Check this link</StarBorder>
          </form>
        </Section>

        <Section labelledBy="problem-h" bg={<VantaScene className={s.fill} effect="waves" options={{ color: 0x03170b }} />}>
          <div className={s.panel}>
            <p className={s.kicker}>The problem</p>
            <h2 id="problem-h" className={s.h2}>Fake QR codes are easy to make and hard to spot.</h2>
            <ScrollReveal textClassName={s.reveal}>
              Scammers stick their own codes over real ones, or send them as payment requests. It’s called quishing. One
              scan can open a fake page that asks for your card number or password, and older adults are a favorite target.
            </ScrollReveal>
            <ul className={s.chips} aria-label="Where fake QR codes show up">{PLACES.map((p) => <li key={p} className={s.chip}>{p}</li>)}</ul>
          </div>
        </Section>

        <Section labelledBy="how-h" bg={<VantaScene className={s.fill} effect="dots" options={{ color: LIME, color2: LIGHT_LIME, backgroundColor: BLACK }} />}>
          <p className={s.kicker}>How it works</p>
          <h2 id="how-h" className={s.h2}>Four steps. Your computer never opens the link.</h2>
          <Reveal>
            <ol className={s.steps}>
              {STEPS.map((st, i) => (
                <li key={st.title} className={s.step}>
                  <span className={s.stepNum} aria-hidden="true">{i + 1}</span>
                  <h3 className={s.h3}>{st.title}</h3>
                  <p>{st.body}</p>
                </li>
              ))}
            </ol>
          </Reveal>
        </Section>

        <Section id="map" labelledBy="map-h" className={s.interactive} bg={<Radar color="#0ae448" backgroundColor="#000000" />}>
          <p className={s.kicker}>Scam map</p>
          <h2 id="map-h" className={s.h2}>Scam QR codes reported near you.</h2>
          <p className={s.lead}>Red pins are codes people reported. Click the map to explore it, or search by website or scam type.</p>
          <MapSection />
        </Section>

        <Section id="stats" labelledBy="stats-h" className={s.interactive} bg={<GridScan linesColor="#3a3a3a" scanColor="#0ae448" />}>
          <p className={s.kicker}>Live numbers</p>
          <h2 id="stats-h" className={s.h2}>What people checked with ScanSafe.</h2>
          <Reveal><DeskStatTiles /></Reveal>
          {/* The existing dashboard: its own title, intro and tiles are replaced by the ones above. */}
          <div className={s.dashboard}><DashboardClient /></div>
        </Section>

        <Section id="about" labelledBy="features-h" bg={<VantaScene className={s.fill} effect="globe" options={{ color: LIME, color2: 0xffffff, backgroundColor: BLACK }} />}>
          <p className={s.kicker}>What you get</p>
          <h2 id="features-h" className={s.h2}>Made to be simple, built to be safe.</h2>
          <Reveal>
            <ul className={s.features}>
              {FEATURES.map((f) => (
                <li key={f.title}>
                  <SpotlightCard className={s.feature} spotlightColor={LIME_GLOW}>
                    <span className={s.featureIcon} aria-hidden="true"><Icon name={f.icon} size={22} /></span>
                    <h3 className={s.h3}>{f.title}</h3>
                    <p>{f.body}</p>
                    <p className={s.by}>{f.by}</p>
                  </SpotlightCard>
                </li>
              ))}
            </ul>
          </Reveal>
        </Section>

        <Section labelledBy="privacy-h" bg={<VantaScene className={s.fill} effect="rings" options={{ color: LIME, backgroundColor: BLACK }} />}>
          <div className={s.panel}>
            <h2 id="privacy-h" className={s.h2}><Icon name="lock" size={28} /> Private by default</h2>
            <ul className={s.checks}>
              <li>Your profile is saved <strong>only on your phone</strong>.</li>
              <li>Your location is <strong>rounded to about 100 meters</strong>, and only sent when you check a code.</li>
              <li>We <strong>never ask for passwords or card numbers</strong>.</li>
            </ul>
          </div>
        </Section>

        <Section labelledBy="closing-h" className={s.closing} bg={<VantaScene className={s.fill} effect="birds" options={{ backgroundColor: BLACK, color1: LIME, color2: LIGHT_LIME }} />}>
          <h2 id="closing-h" className={s.closingTitle}>Not sure about a link?</h2>
          <p className={s.lead}>Check it first. It only takes a few seconds.</p>
          <div className={s.ctaRow}>
            <StarBorder as="a" href="#top" color="#0ae448" className={s.cta}>Check a link</StarBorder>
            <a href={FACETIME_HREF} className={s.ctaGhost} aria-label={`FaceTime ScanSafe at ${FACETIME_NUMBER}`}>
              <Icon name="phone" size={20} /> FaceTime {FACETIME_NUMBER}
            </a>
          </div>
        </Section>

        <footer className={s.footer}>
          <ul className={s.chips} aria-label="Built with">{BUILT_WITH.map((t) => <li key={t} className={s.chip}>{t}</li>)}</ul>
          <p>Made at EmoryHacks 2026 · Atlanta · <a href="https://github.com/jzps333/HackEmory-2026" target="_blank" rel="noopener noreferrer">View the code on GitHub<span className="sr-only"> (opens in a new tab)</span></a></p>
          <p className={s.note}>Every business in our demo, like Dogwood Lot &amp; Meter Co., is made up. Payments use Solana devnet test money only.</p>
        </footer>
      </div>
    </>
  );
}
