import type { Metadata } from "next";
import CardFields from "../../components/CardFields";
import FictionalFooter from "../../components/FictionalFooter";
import s from "./robot-check.module.css";

// Robot-check demo: scam kits put a fake "verify you are human" gate in front of the payment form
// so scanners stop at the gate. Generic look on purpose: no real CAPTCHA provider, no script.
export const metadata: Metadata = { title: "Just a moment... Verify you are human", robots: { index: false } };

export default function RobotCheckScam() {
  return (
    <div style={{ minHeight: "100dvh", background: "#ffffff", fontFamily: "Arial, Helvetica, sans-serif", color: "#111" }}>
      <main style={{ maxWidth: 440, margin: "0 auto", padding: "28px 18px" }}>
        <h1 style={{ fontSize: 24, margin: "8px 0" }}>Checking your browser…</h1>
        <p style={{ fontSize: 16, lineHeight: 1.4 }}>Verify you are human to continue to Zephyrine Parking.</p>
        <input id="robot-check" className={s.check} type="checkbox" />
        <label htmlFor="robot-check" className={s.box}>
          <span className={s.tick} aria-hidden="true" />
          <span>I&apos;m not a robot</span>
        </label>
        <p style={{ fontSize: 12, color: "#666", marginTop: 8 }}>Security check · This only takes a moment</p>
        <section className={s.hidden}>
          <h2 style={{ fontSize: 20, margin: "0 0 6px" }}>Zephyrine Parking: pay for your spot</h2>
          <p style={{ fontSize: 15 }}>Space 214 · 2 hours · <strong>$6.50</strong>. Pay now to avoid a $75 citation.</p>
          <CardFields color="#1f5f99" button="Pay $6.50" />
        </section>
      </main>
      <FictionalFooter />
    </div>
  );
}
