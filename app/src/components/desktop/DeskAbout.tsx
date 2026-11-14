"use client";

import Link from "next/link";
import Particles from "@/components/reactbits/Particles/Particles";
import ScrollReveal from "@/components/reactbits/ScrollReveal/ScrollReveal";
import SpotlightCard from "@/components/reactbits/SpotlightCard/SpotlightCard";
import StarBorder from "@/components/reactbits/StarBorder/StarBorder";
import { Icon } from "@/components/onboarding/Icon";
import DeskHero from "./DeskHero";
import Reveal from "./Reveal";
import s from "./about.module.css";

const FACETIME_HREF = "facetime:+16504444331";
const FACETIME_NUMBER = "+1 (650) 444-4331";
const LIME_GLOW = "rgba(10, 228, 68, 0.28)";

type IconName = Parameters<typeof Icon>[0]["name"];

const FEATURES: { icon: IconName; title: string; body: string; by: string }[] = [
  { icon: "phone", title: "Live view on FaceTime", body: "Call us and hold the code up to your camera. We check it, tell you out loud, and you can watch the page open live.", by: "With Chert" },
  { icon: "help", title: "Plain-language answers", body: "No tech words. You get what we found and what to do next, in a sentence or two.", by: "With Google Gemini" },
  { icon: "location", title: "Scam map near you", body: "See where fake codes were reported nearby, so you know which meters and flyers to skip.", by: "With Typesense geosearch" },
  { icon: "target", title: "Trends dashboard", body: "See how many codes were checked and how many turned out to be scams, hour by hour.", by: "With Tiger Data" },
  { icon: "wallet", title: "Safe payments check", body: "Solana Pay codes are checked before you pay: who gets the money and how much. Test money (devnet) only, and you approve every payment.", by: "With Solana (devnet)" },
  { icon: "user", title: "Accessible by design", body: "Big text, large buttons, results read aloud, and simple words. Built for anyone, including grandparents.", by: "For everyone" },
];

const PRIVACY = [
  <>Your profile is saved <strong>only on your phone</strong>.</>,
  <>Your location is <strong>rounded to about 100 meters</strong>, and only sent when you check a code.</>,
  <>We <strong>never ask for passwords or card numbers</strong>.</>,
];

export default function DeskAbout() {
  return (
    <>
      <DeskHero
        bg={<Particles particleColors={["#0ae448", "#abff84", "#ffffff"]} />}
        kicker="EmoryHacks 2026 · Security track"
        title="Check a QR code before you open it."
        sub="We open the link on our own locked-down computer, check it for scams, and tell you in plain words."
      />

      <section className={s.section} aria-labelledby="problem-h">
        <p className={s.kicker}>The problem</p>
        <h2 id="problem-h" className={s.h2}>Fake QR codes are easy to make and hard to spot.</h2>
        <ScrollReveal textClassName={s.reveal}>
          Scammers stick their own codes over real ones, or send them as payment requests. It’s called quishing. One scan
          can open a fake page that asks for your card number or password, and older adults are a favorite target.
        </ScrollReveal>
      </section>

      <Reveal>
        <section className={s.section} aria-labelledby="features-h">
          <p className={s.kicker}>What you get</p>
          <h2 id="features-h" className={s.h2}>Made to be simple, built to be safe.</h2>
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
        </section>
      </Reveal>

      <Reveal>
        <section className={`${s.section} ${s.privacy}`} aria-labelledby="privacy-h">
          <h2 id="privacy-h" className={s.h2}><Icon name="lock" size={28} /> Private by default</h2>
          <ul className={s.checks}>{PRIVACY.map((p, i) => <li key={i}>{p}</li>)}</ul>
        </section>
      </Reveal>

      <Reveal>
        <section className={s.section} aria-labelledby="demo-h">
          <p className={s.kicker}>Demo</p>
          <h2 id="demo-h" className={s.h2}>See it in action</h2>
          <div className={s.video}>
            <p className={s.videoTitle}>Demo video coming soon</p>
            <p>A two-minute walkthrough of a real scan.</p>
          </div>
        </section>
      </Reveal>

      <Reveal>
        <section className={s.closing} aria-labelledby="closing-h">
          <h2 id="closing-h" className={s.h2}>Not sure about a link?</h2>
          <p className={s.lead}>Check it first. It only takes a few seconds.</p>
          <div className={s.ctaRow}>
            <StarBorder as={Link} href="/" color="#0ae448" className={s.cta}>Check a link</StarBorder>
            <a href={FACETIME_HREF} className={s.ctaGhost} aria-label={`FaceTime ScanSafe at ${FACETIME_NUMBER}`}>
              <Icon name="phone" size={20} /> FaceTime {FACETIME_NUMBER}
            </a>
          </div>
        </section>
      </Reveal>

      <footer className={s.footer}>
        <p>Made at EmoryHacks 2026 · Atlanta</p>
        <p><a href="https://github.com/jzps333/HackEmory-2026" target="_blank" rel="noopener noreferrer">View the code on GitHub<span className="sr-only"> (opens in a new tab)</span></a></p>
        <p className={s.note}>Every business in our demo, like Dogwood Lot &amp; Meter Co., is made up. Payments use Solana devnet test money only.</p>
      </footer>
    </>
  );
}
