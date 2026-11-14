import type { Metadata } from "next";
import type { ReactNode } from "react";
import Link from "next/link";
import { Icon } from "@/components/onboarding/Icon";
import s from "./about.module.css";

// Paste the demo video link here (YouTube, Vimeo or Loom). Empty = "coming soon" box.
const DEMO_VIDEO_URL: string = "";

const FACETIME_HREF = "facetime:+16504444331";
const FACETIME_NUMBER = "+1 (650) 444-4331";
const GITHUB_URL = "https://github.com/jzps333/HackEmory-2026";

export const metadata: Metadata = {
  title: "About ScanSafe",
  description:
    "ScanSafe checks a QR code before you open it. We open the link on our own locked-down computer, check it for scams, and tell you in plain words.",
};

/* Small decorative icons that the shared onboarding Icon set doesn't have. */
type GlyphName =
  | "check"
  | "x"
  | "video"
  | "chat"
  | "map"
  | "chart"
  | "speaker"
  | "play"
  | "code"
  | "meter"
  | "menu"
  | "flyer"
  | "box"
  | "spark";

const glyphs: Record<GlyphName, ReactNode> = {
  check: <path d="m5 12.5 4.5 4.5L19 7.5" />,
  x: <path d="M17 7 7 17M7 7l10 10" />,
  video: (
    <>
      <rect x="2.5" y="6" width="13.5" height="12" rx="2.5" />
      <path d="m16 10.5 5.5-3.2v9.4L16 13.5" />
    </>
  ),
  chat: (
    <>
      <path d="M20.5 11.5a8 8 0 0 1-11.7 7.1L3.5 20l1.4-4.9a8 8 0 1 1 15.6-3.6Z" />
      <path d="M8.5 10.5h7M8.5 14h4.5" />
    </>
  ),
  map: (
    <>
      <path d="M9 4 3 6.5V20l6-2.5 6 2.5 6-2.5V4l-6 2.5L9 4Z" />
      <path d="M9 4v13.5M15 6.5V20" />
    </>
  ),
  chart: (
    <>
      <path d="M4 4v16h16" />
      <path d="m7.5 15 4-4.5 3 3L20 7" />
    </>
  ),
  speaker: (
    <>
      <path d="M11 5 6.5 9H3.5v6h3L11 19V5Z" />
      <path d="M15.5 8.8a4.5 4.5 0 0 1 0 6.4M18.3 6a8.5 8.5 0 0 1 0 12" />
    </>
  ),
  play: <path d="M9 6.5v11l9-5.5-9-5.5Z" fill="currentColor" />,
  code: <path d="m8 8-4 4 4 4M16 8l4 4-4 4M13.5 5l-3 14" />,
  meter: (
    <>
      <rect x="6.5" y="2.5" width="11" height="11" rx="5.5" />
      <path d="M12 13.5V21M8.5 21h7M10 8h4" />
    </>
  ),
  menu: (
    <>
      <rect x="5" y="3" width="14" height="18" rx="2" />
      <path d="M9 8h6M9 12h6M9 16h3.5" />
    </>
  ),
  flyer: (
    <>
      <rect x="4" y="3" width="16" height="18" rx="2" />
      <circle cx="9.5" cy="9" r="2" />
      <path d="m4 17.5 5-4 4 3 3-2 4 3" />
    </>
  ),
  box: (
    <>
      <path d="M20.5 7.8 12 3 3.5 7.8v8.4L12 21l8.5-4.8V7.8Z" />
      <path d="m3.5 7.8 8.5 4.8 8.5-4.8M12 12.6V21" />
    </>
  ),
  spark: <path d="M12 3c.6 4.6 2.4 6.4 7 7-4.6.6-6.4 2.4-7 7-.6-4.6-2.4-6.4-7-7 4.6-.6 6.4-2.4 7-7ZM19 15.5c.25 1.9 1 2.6 2.5 2.9-1.5.3-2.25 1-2.5 2.9-.25-1.9-1-2.6-2.5-2.9 1.5-.3 2.25-1 2.5-2.9Z" />,
};

function Glyph({ name, size = 22 }: { name: GlyphName; size?: number }) {
  return (
    <svg
      aria-hidden="true"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {glyphs[name]}
    </svg>
  );
}

/* A decorative, made-up QR pattern (not scannable on purpose). */
const QR_MODULES: [number, number][] = [
  [9, 0], [11, 1], [8, 2], [10, 3], [12, 4], [9, 5], [11, 6], [8, 8], [10, 8], [13, 8],
  [0, 9], [2, 9], [5, 9], [9, 9], [12, 10], [16, 9], [19, 9], [1, 11], [4, 11], [7, 10],
  [10, 11], [15, 11], [18, 11], [20, 12], [3, 12], [9, 13], [13, 12], [17, 13], [8, 14],
  [11, 15], [14, 14], [19, 15], [16, 16], [9, 17], [12, 17], [18, 18], [10, 19], [14, 19],
  [20, 19], [8, 20], [12, 20], [16, 20], [11, 13], [15, 17],
];

function QrArt() {
  const finder = (x: number, y: number) => (
    <g key={`${x}-${y}`}>
      <rect x={x + 0.5} y={y + 0.5} width="6" height="6" rx="1.2" fill="none" stroke="currentColor" strokeWidth="1" />
      <rect x={x + 2} y={y + 2} width="3" height="3" rx="0.6" fill="currentColor" />
    </g>
  );
  return (
    <svg aria-hidden="true" viewBox="0 0 21 21" className={s.qrSvg}>
      {finder(0, 0)}
      {finder(14, 0)}
      {finder(0, 14)}
      {QR_MODULES.map(([x, y]) => (
        <rect key={`${x}.${y}`} x={x + 0.1} y={y + 0.1} width="0.8" height="0.8" rx="0.2" fill="currentColor" />
      ))}
    </svg>
  );
}

/** Turn a normal video page link into an embeddable player URL. Unknown hosts get a plain link instead. */
function toEmbedUrl(url: string): string | null {
  try {
    const u = new URL(url);
    const host = u.hostname.replace(/^www\./, "");
    const parts = u.pathname.split("/").filter(Boolean);
    if (host === "youtu.be" && parts[0]) return `https://www.youtube-nocookie.com/embed/${encodeURIComponent(parts[0])}`;
    if (host === "youtube.com" || host === "m.youtube.com") {
      const id = u.searchParams.get("v") ?? (["embed", "shorts", "live"].includes(parts[0]) ? parts[1] : null);
      if (id) return `https://www.youtube-nocookie.com/embed/${encodeURIComponent(id)}`;
    }
    if (host === "youtube-nocookie.com" || host === "player.vimeo.com") return url;
    if (host === "vimeo.com" && parts[0] && /^\d+$/.test(parts[0])) return `https://player.vimeo.com/video/${parts[0]}`;
    if (host === "loom.com" && (parts[0] === "share" || parts[0] === "embed") && parts[1]) {
      return `https://www.loom.com/embed/${encodeURIComponent(parts[1])}`;
    }
  } catch {
    // Not a valid URL: fall through to no embed.
  }
  return null;
}

const PROBLEM_PLACES: { glyph?: GlyphName; icon?: "wallet"; label: string }[] = [
  { glyph: "meter", label: "Parking meters" },
  { glyph: "menu", label: "Restaurant menus" },
  { glyph: "flyer", label: "Flyers and posters" },
  { icon: "wallet", label: "Payment requests" },
];

const FEATURES: { glyph?: GlyphName; icon?: "location" | "wallet"; title: string; body: string; by: string; live?: boolean }[] = [
  {
    glyph: "video",
    title: "Live view on FaceTime",
    body: "Call us and hold the code up to your camera. We check it, tell you out loud, and you can watch the page open live.",
    by: "With Chert",
    live: true,
  },
  {
    glyph: "chat",
    title: "Plain-language answers",
    body: "No tech words. You get what we found and what to do next, in a sentence or two.",
    by: "With Google Gemini",
  },
  {
    icon: "location",
    title: "Scam map near you",
    body: "See where fake codes were reported nearby, so you know which meters and flyers to skip.",
    by: "With Typesense geosearch",
  },
  {
    glyph: "chart",
    title: "Trends dashboard",
    body: "See how many codes were checked and how many turned out to be scams, hour by hour.",
    by: "With Tiger Data",
  },
  {
    icon: "wallet",
    title: "Safe payments check",
    body: "Solana Pay codes are checked before you pay: who gets the money and how much. Test money (devnet) only, and you approve every payment.",
    by: "With Solana (devnet)",
  },
  {
    glyph: "speaker",
    title: "Accessible by design",
    body: "Big text, large buttons, results read aloud, and simple words. Built for anyone, including grandparents.",
    by: "For everyone",
  },
];

const BUILT_WITH = [
  "Vultr",
  "Chert",
  "LiveKit",
  "Google Gemini",
  "Jev (via OpenRouter)",
  "Typesense",
  "Tiger Data",
  "Solana (devnet)",
  "Coder",
  "Next.js",
  "FastAPI",
  "Playwright",
  "Docker",
];

function FaceTimeButton({ variant = "secondary" }: { variant?: "secondary" | "onDark" }) {
  return (
    <a
      href={FACETIME_HREF}
      className={`${s.btn} ${variant === "onDark" ? s.btnOnDarkOutline : s.btnSecondary}`}
      aria-label={`FaceTime ScanSafe at ${FACETIME_NUMBER}`}
    >
      <Icon name="phone" size={20} />
      <span className={s.btnLabel}>
        <span>FaceTime</span> <span className={s.nowrap}>{FACETIME_NUMBER}</span>
      </span>
    </a>
  );
}

export default function AboutPage() {
  const embed = DEMO_VIDEO_URL ? toEmbedUrl(DEMO_VIDEO_URL) : null;

  return (
    <div className={s.page}>
      {/* Hero */}
      <section className={s.hero} aria-labelledby="about-title">
        <div className={s.heroTop}>
          <span className={s.brandMark} aria-hidden="true">
            <Icon name="shield" size={22} />
          </span>
          <span className={s.eyebrow}>EmoryHacks 2026 · Security track</span>
        </div>

        <h1 id="about-title" className={s.heroTitle}>
          Check a QR code <span className={s.accent}>before you open it.</span>
        </h1>
        <p className={s.heroSub}>
          We open the link on our own locked-down computer, check it for scams, and tell you in plain words.
        </p>

        <div className={s.ctaRow}>
          <Link href="/" className={`${s.btn} ${s.btnPrimary}`}>
            <span>Scan a code</span>
            <Icon name="arrow-right" size={20} />
          </Link>
          <FaceTimeButton />
        </div>
        <p className={s.ctaNote}>FaceTime works on iPhone, iPad and Mac. Just call and hold the code up to your camera.</p>

        <figure className={s.example}>
          <figcaption className={s.exampleCaption}>
            <span className={s.exampleTag}>Example</span> A made-up business, for illustration
          </figcaption>
          <div className={s.exampleTop}>
            <div className={s.qrBox}>
              <QrArt />
              <span className={s.scanLine} aria-hidden="true" />
            </div>
            <div className={s.exampleSource}>
              <p className={s.exampleLabel}>Sticker on a parking meter</p>
              <p className={s.exampleName}>“Pay Peachtree Parking Co.”</p>
            </div>
          </div>
          <div className={s.verdictBad}>
            <span className={s.verdictIcon} aria-hidden="true">
              <Glyph name="x" size={22} />
            </span>
            <div>
              <p className={s.verdictTitle}>Stop. This is a scam</p>
              <p className={s.verdictSub}>Fake parking or toll website</p>
            </div>
          </div>
          <ul className={s.reasons}>
            <li>Asks for your card number</li>
            <li>Pretends to be the parking company</li>
            <li>Hides secret text that says “this site is safe”</li>
          </ul>
        </figure>
      </section>

      {/* Problem */}
      <section className={s.section} aria-labelledby="problem-title">
        <p className={s.kicker}>The problem</p>
        <h2 id="problem-title" className={s.h2}>
          Fake QR codes are easy to make and hard to spot.
        </h2>
        <p className={s.lead}>
          Scammers stick their own codes over real ones, or send them as payment requests. It’s called{" "}
          <strong>“quishing.”</strong> One scan can open a fake page that asks for your card number or password, and
          older adults are a favorite target.
        </p>
        <ul className={s.places} aria-label="Where fake QR codes show up">
          {PROBLEM_PLACES.map((p) => (
            <li key={p.label} className={s.place}>
              <span className={s.placeIcon} aria-hidden="true">
                {p.icon ? <Icon name={p.icon} size={22} /> : <Glyph name={p.glyph!} />}
              </span>
              {p.label}
            </li>
          ))}
        </ul>
      </section>

      {/* How it works */}
      <section className={s.section} aria-labelledby="how-title">
        <p className={s.kicker}>How it works</p>
        <h2 id="how-title" className={s.h2}>
          Four steps. Your phone never opens the link.
        </h2>
        <ol className={s.steps}>
          <li className={s.step}>
            <span className={s.stepNum} aria-hidden="true">1</span>
            <div className={s.stepCard}>
              <h3 className={s.h3}>Scan it, or show it</h3>
              <p>Scan the code in the ScanSafe app, or hold it up to your camera on a FaceTime call with us.</p>
            </div>
          </li>
          <li className={s.step}>
            <span className={s.stepNum} aria-hidden="true">2</span>
            <div className={s.stepCard}>
              <h3 className={s.h3}>We open it, not you</h3>
              <p>
                The link opens in a throwaway, locked-down browser on our server. It can’t reach private networks, and
                it’s thrown away after. Your phone never loads the page.
              </p>
              <ul className={s.tags} aria-label="Tools used in this step">
                <li><Glyph name="box" size={16} /> Docker</li>
                <li>Playwright</li>
                <li><Icon name="lock" size={16} /> No private networks</li>
              </ul>
            </div>
          </li>
          <li className={s.step}>
            <span className={s.stepNum} aria-hidden="true">3</span>
            <div className={s.stepCard}>
              <h3 className={s.h3}>AI checks for tricks</h3>
              <p>
                <strong>Jev</strong> scores the page for pretending to be someone else, asking for passwords or card
                numbers, and hidden tricks. <strong>Gemini</strong> then explains what it found in plain words.
              </p>
              <ul className={s.tags} aria-label="Tools used in this step">
                <li><Glyph name="spark" size={16} /> Jev</li>
                <li><Glyph name="spark" size={16} /> Gemini</li>
              </ul>
            </div>
          </li>
          <li className={s.step}>
            <span className={s.stepNum} aria-hidden="true">4</span>
            <div className={s.stepCard}>
              <h3 className={s.h3}>You get a clear answer</h3>
              <p>
                One of three simple verdicts. On FaceTime you can watch the page live, and scams get pinned on a map so
                your neighbors are warned.
              </p>
              <ul className={s.verdictPills} aria-label="The three verdicts">
                <li className={s.pillSafe}><Glyph name="check" size={16} /> Looks safe</li>
                <li className={s.pillWarn}><Icon name="help" size={16} /> Be careful</li>
                <li className={s.pillBad}><Glyph name="x" size={16} /> Stop. This is a scam</li>
              </ul>
            </div>
          </li>
        </ol>
      </section>

      {/* Features */}
      <section className={s.section} aria-labelledby="features-title">
        <p className={s.kicker}>What you get</p>
        <h2 id="features-title" className={s.h2}>
          Made to be simple, built to be safe.
        </h2>
        <ul className={s.features}>
          {FEATURES.map((f) => (
            <li key={f.title} className={s.feature}>
              <div className={s.featureHead}>
                <span className={s.featureIcon} aria-hidden="true">
                  {f.icon ? <Icon name={f.icon} size={22} /> : <Glyph name={f.glyph!} />}
                </span>
                {f.live && (
                  <span className={s.liveBadge}>
                    <span className={s.liveDot} aria-hidden="true" /> Live
                  </span>
                )}
              </div>
              <h3 className={s.h3}>{f.title}</h3>
              <p>{f.body}</p>
              <p className={s.by}>{f.by}</p>
            </li>
          ))}
        </ul>
      </section>

      {/* Privacy */}
      <section className={`${s.section} ${s.privacy}`} aria-labelledby="privacy-title">
        <div className={s.privacyHead}>
          <span className={s.privacyIcon} aria-hidden="true">
            <Icon name="lock" size={24} />
          </span>
          <h2 id="privacy-title" className={s.h2}>
            Private by default
          </h2>
        </div>
        <ul className={s.checks}>
          <li>
            <span className={s.checkIcon} aria-hidden="true"><Glyph name="check" size={18} /></span>
            <span>Your profile is saved <strong>only on your phone</strong>.</span>
          </li>
          <li>
            <span className={s.checkIcon} aria-hidden="true"><Glyph name="check" size={18} /></span>
            <span>
              Your location is <strong>rounded to about 100 meters</strong>, and only sent when you check a code.
            </span>
          </li>
          <li>
            <span className={s.checkIcon} aria-hidden="true"><Glyph name="check" size={18} /></span>
            <span>We <strong>never ask for passwords or card numbers</strong>.</span>
          </li>
        </ul>
      </section>

      {/* Demo video */}
      <section className={s.section} aria-labelledby="demo-title">
        <p className={s.kicker}>Demo</p>
        <h2 id="demo-title" className={s.h2}>
          See it in action
        </h2>
        {embed ? (
          <div className={s.videoFrame}>
            <iframe
              src={embed}
              title="ScanSafe demo video"
              loading="lazy"
              allow="accelerometer; clipboard-write; encrypted-media; gyroscope; picture-in-picture; fullscreen"
              allowFullScreen
              referrerPolicy="strict-origin-when-cross-origin"
            />
          </div>
        ) : DEMO_VIDEO_URL ? (
          <a className={s.videoLink} href={DEMO_VIDEO_URL} target="_blank" rel="noopener noreferrer">
            <span className={s.playCircle} aria-hidden="true"><Glyph name="play" size={26} /></span>
            <span>Watch the demo video<span className="sr-only"> (opens in a new tab)</span></span>
          </a>
        ) : (
          <div className={s.videoPlaceholder}>
            <span className={s.playCircle} aria-hidden="true"><Glyph name="play" size={26} /></span>
            <p className={s.videoTitle}>Demo video coming soon</p>
            <p className={s.videoSub}>A two-minute walkthrough of a real scan.</p>
          </div>
        )}
        {embed && (
          <p className={s.videoAlt}>
            <a href={DEMO_VIDEO_URL} target="_blank" rel="noopener noreferrer">
              Open the video in a new tab<span className="sr-only"> (opens in a new tab)</span>
            </a>
          </p>
        )}
      </section>

      {/* Built with */}
      <section className={s.section} aria-labelledby="built-title">
        <p className={s.kicker}>Under the hood</p>
        <h2 id="built-title" className={s.h2}>
          Built with
        </h2>
        <ul className={s.chips}>
          {BUILT_WITH.map((t) => (
            <li key={t} className={s.chip}>
              {t}
            </li>
          ))}
        </ul>
      </section>

      {/* Closing CTA */}
      <section className={s.closing} aria-labelledby="closing-title">
        <h2 id="closing-title" className={s.closingTitle}>
          Not sure about a code?
        </h2>
        <p className={s.closingSub}>Check it first. It only takes a few seconds.</p>
        <div className={s.ctaRow}>
          <Link href="/" className={`${s.btn} ${s.btnOnDark}`}>
            <span>Scan a code</span>
            <Icon name="arrow-right" size={20} />
          </Link>
          <FaceTimeButton variant="onDark" />
        </div>
      </section>

      <footer className={s.footer}>
        <p className={s.footerMade}>
          <Icon name="shield" size={18} /> Made at EmoryHacks 2026 · Atlanta
        </p>
        <p>
          <a href={GITHUB_URL} className={s.footerLink} target="_blank" rel="noopener noreferrer">
            <Glyph name="code" size={18} />
            View the code on GitHub<span className="sr-only"> (opens in a new tab)</span>
          </a>
        </p>
        <p className={s.footerNote}>
          Every business in our demo, like Peachtree Parking Co., is made up. Payments use Solana devnet test money only.
        </p>
      </footer>
    </div>
  );
}
