"use client";

import { useEffect, useRef, useState } from "react";
import ConfirmDialog from "./ConfirmDialog";
import FaceTimeCard from "@/components/FaceTimeCard";
import VerdictIcon from "./VerdictIcon";
import { DEMO_MODE, pay, report, screenshotSrc } from "@/lib/api";
import { VERDICT_TEXT, isWebLink, percent, scamLabel } from "@/lib/labels";
import type { ScanResult } from "@/lib/types";

const FTC_URL = "https://reportfraud.ftc.gov/";

function ftcSummary(r: ScanResult): string {
  const when = new Date(r.scanned_at * 1000).toLocaleString();
  const lines = [
    `I scanned a QR code that led to a scam website (${scamLabel(r.scam_type).toLowerCase()}).`,
    `When: ${when}`,
    r.location ? `Where (approximate): ${r.location[0]}, ${r.location[1]}` : null,
    `What the QR code contained: ${r.url}`,
    r.final_url && r.final_url !== r.url ? `Where it really went: ${r.final_url}` : null,
    r.page_title ? `The page said: "${r.page_title}"` : null,
    r.payment ? `It asked for a payment of ${r.payment.amount_sol} SOL to wallet ${r.payment.recipient} (labeled "${r.payment.label}").` : null,
    `What ScanSafe found: ${r.explanation}`,
    `I did not enter any personal or payment details.`,
  ];
  return lines.filter(Boolean).join("\n");
}

function ScreenshotImg({ src, index }: { src: string; index: number }) {
  const [url, setUrl] = useState(screenshotSrc(src));
  const [failed, setFailed] = useState(false);
  if (failed) return <p className="hint">Picture {index + 1} could not load.</p>;
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={url}
      alt={`Picture ${index + 1} of the website, taken safely on our server`}
      loading="lazy"
      onError={() => {
        // Backend mock mode returns names like "mock/mal-1.png": fall back to the copies in /public.
        const local = `/${src.replace(/^\/+/, "")}`;
        if (url !== local && !/^(data:|https?:)/i.test(src)) setUrl(local);
        else setFailed(true);
      }}
    />
  );
}

interface Props {
  result: ScanResult;
  onDone: () => void;
  /** Set when the user agreed to calls in onboarding: shows "FaceTime me and show me". */
  facetime?: { phone: string; location: [number, number] | null } | null;
}

export default function ResultView({ result: r, onDone, facetime }: Props) {
  const headingRef = useRef<HTMLHeadingElement>(null);
  const [speaking, setSpeaking] = useState(false);
  const [canSpeak, setCanSpeak] = useState(false);
  const [dialog, setDialog] = useState<"pay" | "report" | null>(null);
  const [payState, setPayState] = useState<{ status: "idle" | "busy" | "done" | "error"; msg?: string; link?: string }>({ status: "idle" });
  const [reportState, setReportState] = useState<"idle" | "busy" | "done" | "error">("idle");
  const [copied, setCopied] = useState(false);

  const v = VERDICT_TEXT[r.verdict] ?? VERDICT_TEXT.suspicious;
  const openUrl = r.final_url || r.url;
  const canOpen = r.verdict === "safe" && isWebLink(openUrl);
  const canPay = r.verdict === "safe" && !!r.payment && r.payment.merchant_verified && !r.payment.tx_signature;
  const chain = r.redirect_chain?.length ? r.redirect_chain : r.final_url && r.final_url !== r.url ? [r.url, r.final_url] : [];
  const summary = ftcSummary(r);
  const scoreColor = r.jev_score >= 0.7 ? "var(--bad-strong)" : r.jev_score >= 0.35 ? "var(--warn-strong)" : "var(--safe-strong)";

  useEffect(() => {
    headingRef.current?.focus();
    setCanSpeak(typeof window !== "undefined" && "speechSynthesis" in window);
    return () => { if ("speechSynthesis" in window) window.speechSynthesis.cancel(); };
  }, []);

  function readAloud() {
    const synth = window.speechSynthesis;
    if (speaking) {
      synth.cancel();
      setSpeaking(false);
      return;
    }
    synth.cancel();
    const u = new SpeechSynthesisUtterance(`${v.title}. ${r.explanation}`);
    u.rate = 0.85;
    u.lang = "en-US";
    u.onend = () => setSpeaking(false);
    u.onerror = () => setSpeaking(false);
    setSpeaking(true);
    synth.speak(u);
  }

  async function doPay() {
    setDialog(null);
    setPayState({ status: "busy" });
    try {
      const res = await pay(r);
      setPayState({
        status: "done",
        msg: DEMO_MODE ? "Demo mode: no money moved." : `Paid. Receipt number: ${res.tx_signature}`,
        link: res.explorer_url || (DEMO_MODE ? undefined : `https://explorer.solana.com/tx/${res.tx_signature}?cluster=devnet`),
      });
    } catch {
      setPayState({ status: "error", msg: "The payment didn't go through. No money moved. You can try again." });
    }
  }

  async function doReport() {
    setDialog(null);
    setReportState("busy");
    try {
      await report(r);
      setReportState("done");
    } catch {
      setReportState("error");
    }
  }

  async function copySummary() {
    try {
      await navigator.clipboard.writeText(summary);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  return (
    <article aria-labelledby="verdict-title">
      <div className={`verdict verdict-${r.verdict}`}>
        <VerdictIcon verdict={r.verdict} />
        <div>
          <h1 id="verdict-title" ref={headingRef} tabIndex={-1}>{v.title}</h1>
          <p>{v.sub}</p>
        </div>
      </div>

      {DEMO_MODE && <p className="hint" style={{ marginTop: "0.75rem" }}><span className="demo-badge">Demo</span> This is sample data, not a real check.</p>}

      <p className="explanation">{r.explanation}</p>

      {facetime && !r.payment && (
        <FaceTimeCard url={r.url} phone={facetime.phone} location={facetime.location} />
      )}

      {canSpeak && (
        <button type="button" className="btn" onClick={readAloud} aria-pressed={speaking}>
          {speaking ? "Stop reading" : "Read aloud"}
        </button>
      )}

      <section className="card" aria-labelledby="score-h">
        <h2 id="score-h" className="sr-only">How likely it is a scam</h2>
        <p className="score">{percent(r.jev_score)} likely a scam</p>
        <div className="meter" role="img" aria-label={`${percent(r.jev_score)} likely a scam`}>
          <span style={{ width: percent(r.jev_score), background: scoreColor }} />
        </div>
        {r.scam_type && r.scam_type !== "none" && <p style={{ marginTop: "0.75rem", marginBottom: 0 }}><strong>Type:</strong> {scamLabel(r.scam_type)}</p>}
        {r.flagged_before > 0 && (
          <p style={{ marginTop: "0.5rem", marginBottom: 0 }}><strong>Reported nearby {r.flagged_before} time{r.flagged_before === 1 ? "" : "s"} before.</strong></p>
        )}
        {r.payment && (
          <p style={{ marginTop: "0.5rem", marginBottom: 0 }}>
            <strong>Payment:</strong> {r.payment.amount_sol} test SOL to {r.payment.label || "an unnamed wallet"}
            {r.payment.message ? ` (${r.payment.message})` : ""}.{" "}
            {r.payment.merchant_verified ? "The wallet matches this business." : "The wallet does NOT match this business."}
          </p>
        )}
      </section>

      <div className="btn-row">
        {canOpen && (
          <a className="btn btn-safe" href={openUrl} target="_blank" rel="noopener noreferrer">
            Open link<span className="sr-only"> (opens in a new tab)</span>
          </a>
        )}
        {canPay && r.payment && (
          <button type="button" className="btn btn-safe" onClick={() => setDialog("pay")} disabled={payState.status === "busy" || payState.status === "done"}>
            {payState.status === "busy" ? "Paying…" : `Pay ${r.payment.amount_sol} test SOL`}
          </button>
        )}
        {(
          <button type="button" className={`btn ${r.verdict === "safe" ? "" : "btn-danger"}`} onClick={() => setDialog("report")} disabled={reportState === "busy" || reportState === "done"}>
            {reportState === "busy" ? "Sending report…" : reportState === "done" ? "Reported. Thank you" : r.verdict === "safe" ? "Report scam anyway" : "Report scam"}
          </button>
        )}
        <button type="button" className="btn" onClick={onDone}>
          {r.verdict === "safe" ? "Nevermind" : "Nevermind, I won't open it"}
        </button>
      </div>

      <div aria-live="polite">
        {payState.msg && (
          <p className={`notice ${payState.status === "error" ? "bad" : ""}`} role={payState.status === "error" ? "alert" : "status"}>
            {payState.msg}{" "}
            {payState.link && <a href={payState.link} target="_blank" rel="noopener noreferrer">See the receipt<span className="sr-only"> (opens in a new tab)</span></a>}
          </p>
        )}
        {reportState === "error" && <p className="notice bad" role="alert">We couldn't send your report. You can still tell the FTC below.</p>}
      </div>

      {(reportState === "done" || reportState === "error") && (
        <section className="card" aria-labelledby="ftc-h">
          <h2 id="ftc-h" style={{ marginTop: 0 }}>Tell the FTC too</h2>
          {reportState === "done" && <p>Thanks. We added this to the scam map so people nearby are warned.</p>}
          <p>The FTC (the U.S. government&apos;s consumer protection office) collects scam reports. We wrote a summary for you. Copy it, open their website, and paste it in. You send it yourself.</p>
          <label htmlFor="ftc-summary">Summary to paste</label>
          <textarea id="ftc-summary" readOnly value={summary} />
          <div className="btn-row two">
            <button type="button" className="btn" onClick={copySummary}>{copied ? "Copied" : "Copy summary"}</button>
            <a className="btn btn-primary" href={FTC_URL} target="_blank" rel="noopener noreferrer">
              Open FTC website<span className="sr-only"> (opens in a new tab)</span>
            </a>
          </div>
          <p className="sr-only" aria-live="polite">{copied ? "Summary copied." : ""}</p>
        </section>
      )}

      {r.screenshots?.length > 0 && (
        <section aria-labelledby="shots-h">
          <h2 id="shots-h">What the website looks like</h2>
          <p className="hint">We took these pictures on our server, so nothing ran on your phone.</p>
          <div className="shots">
            {r.screenshots.map((s, i) => <ScreenshotImg key={`${s}-${i}`} src={s} index={i} />)}
          </div>
        </section>
      )}

      {chain.length > 0 && (
        <details>
          <summary>Where this link really goes</summary>
          <div>
            <p>The QR code sent you through {chain.length} web address{chain.length === 1 ? "" : "es"}, in this order:</p>
            <ol className="chain">
              {chain.map((u, i) => (
                <li key={`${u}-${i}`} className={i === chain.length - 1 ? "final" : undefined}>
                  {u}{i === chain.length - 1 ? " (where you end up)" : ""}
                </li>
              ))}
            </ol>
          </div>
        </details>
      )}

      <ConfirmDialog
        open={dialog === "pay"}
        title="Pay with test money?"
        confirmLabel={`Yes, pay ${r.payment?.amount_sol ?? ""} test SOL`}
        onConfirm={doPay}
        onCancel={() => setDialog(null)}
      >
        <p>This pays <strong>{r.payment?.amount_sol} SOL</strong> to <strong>{r.payment?.label || "this wallet"}</strong>.</p>
        <p>This is <strong>Solana devnet test money</strong>. It is not real money and has no value.</p>
      </ConfirmDialog>

      <ConfirmDialog
        open={dialog === "report"}
        title="Report this scam?"
        confirmLabel="Yes, report it"
        danger
        onConfirm={doReport}
        onCancel={() => setDialog(null)}
      >
        <p>We&apos;ll add a warning pin to the scam map so people nearby know. We never save who reported it.</p>
        <p>We send the web address, what we found{r.location ? ", and the rough area where you scanned it" : ""}.</p>
      </ConfirmDialog>
    </article>
  );
}
