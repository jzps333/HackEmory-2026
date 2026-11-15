"use client";

import { ArrowLeft, Info, LoaderCircle, MessageSquareText, Smartphone } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, errorText } from "@/lib/api";
import { smsHref, startPhoneSignIn, toE164, verifyPhoneSignIn } from "@/lib/auth";
import { useAuth } from "./AuthProvider";

const POLL_MS = 3000;
const LIMIT_MS = 15 * 60 * 1000;

type Step = "phone" | "code" | "stopped";
type Shown = { phone: string; code: string; line: string; smsBody: string };

/** Network blips, rate limits and 5xx are worth another try; anything else ends this code. */
const retryable = (e: unknown) => e instanceof ApiError && (e.status === 0 || e.status === 429 || e.status >= 500);

function PhoneSignInFlow() {
  const { completeSignIn } = useAuth();
  const [step, setStep] = useState<Step>("phone");
  const [input, setInput] = useState("");
  const [inputError, setInputError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [shown, setShown] = useState<Shown | null>(null);
  const [trouble, setTrouble] = useState(false);
  const [stopReason, setStopReason] = useState("");

  // request_id lives only here, in memory, for the life of one code.
  const pending = useRef<{ phone: string; requestId: string; startedAt: number } | null>(null);
  const gen = useRef(0);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inflight = useRef<AbortController | null>(null);

  const stopPolling = useCallback(() => {
    gen.current++;
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    inflight.current?.abort();
    inflight.current = null;
  }, []);

  useEffect(() => stopPolling, [stopPolling]);

  const stop = useCallback(
    (reason: string) => {
      stopPolling();
      pending.current = null;
      setTrouble(false);
      setStopReason(reason);
      setStep("stopped");
    },
    [stopPolling],
  );

  const poll = useCallback(
    async (g: number) => {
      const p = pending.current;
      if (g !== gen.current || !p) return;
      if (Date.now() - p.startedAt >= LIMIT_MS) {
        stop("This code expired after 15 minutes without a text.");
        return;
      }
      const ctrl = new AbortController();
      inflight.current = ctrl;
      try {
        const r = await verifyPhoneSignIn(p.phone, p.requestId, ctrl.signal);
        if (g !== gen.current) return;
        if (r.verified) {
          stopPolling();
          pending.current = null;
          completeSignIn(r.token, r.phone);
          return;
        }
        setTrouble(false);
      } catch (e) {
        if (g !== gen.current) return;
        if (!retryable(e)) {
          stop(`That code can't be used any more. ${errorText(e)}`);
          return;
        }
        setTrouble(true);
      } finally {
        if (inflight.current === ctrl) inflight.current = null;
      }
      timer.current = setTimeout(() => poll(g), POLL_MS);
    },
    [completeSignIn, stop, stopPolling],
  );

  const send = useCallback(
    async (phone: string) => {
      stopPolling();
      pending.current = null;
      const g = gen.current;
      setSending(true);
      setInputError(null);
      try {
        const s = await startPhoneSignIn(phone);
        if (g !== gen.current) return;
        pending.current = { phone, requestId: s.requestId, startedAt: Date.now() };
        setShown({ phone, code: s.code, line: s.line, smsBody: s.smsBody });
        setTrouble(false);
        setStep("code");
        timer.current = setTimeout(() => poll(g), POLL_MS);
      } catch (e) {
        if (g !== gen.current) return;
        setInputError(`Couldn't get a code. ${errorText(e)}`);
        setStep("phone");
      } finally {
        if (g === gen.current) setSending(false);
      }
    },
    [poll, stopPolling],
  );

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const phone = toE164(input);
    if (!phone) {
      setInputError("Enter a 10-digit US number, or a full number starting with + and the country code.");
      return;
    }
    send(phone);
  };

  const differentNumber = () => {
    stopPolling();
    pending.current = null;
    setSending(false);
    setStep("phone");
  };

  if (step === "code" && shown) {
    return (
      <div className="signin-code-step">
        <p className="signin-lead">
          From the phone ending in <span className="mono">{shown.phone.replace(/\D/g, "").slice(-4)}</span>, text
          this code to the ScanSafe Chert line:
        </p>
        <p className="signin-code mono">
          <span className="sr-only">Your code: </span>
          {shown.code}
        </p>
        <div className="signin-actions">
          <a className="btn btn-primary" href={smsHref(shown.line, shown.smsBody)}>
            <MessageSquareText size={15} strokeWidth={1.75} />
            Text it
          </a>
          <span className="muted small">
            or text the code to <span className="line-number-select mono">{shown.line}</span>
          </span>
        </div>
        <p className={`signin-wait small${trouble ? " trouble" : ""}`} role="status" aria-live="polite">
          <LoaderCircle size={14} className="spin-icon" />
          {trouble
            ? "Having trouble reaching the sign-in API. Still checking…"
            : "Waiting for your text. This page signs you in as soon as it arrives."}
        </p>
        <button type="button" className="text-btn small" onClick={differentNumber}>
          <ArrowLeft size={13} />
          Use a different number
        </button>
      </div>
    );
  }

  if (step === "stopped" && shown) {
    return (
      <div className="signin-code-step">
        <p className="notice small signin-stopped" role="alert">
          {stopReason}
        </p>
        <div className="signin-actions">
          <button type="button" className="btn btn-primary" onClick={() => send(shown.phone)} disabled={sending}>
            {sending ? <LoaderCircle size={15} className="spin-icon" /> : null}
            Send a new code
          </button>
          <button type="button" className="text-btn small" onClick={differentNumber}>
            Use a different number
          </button>
        </div>
        {inputError ? (
          <p className="inline-error small" role="alert">
            {inputError}
          </p>
        ) : null}
      </div>
    );
  }

  return (
    <form className="signin-form" onSubmit={onSubmit} noValidate>
      <label className="field-label" htmlFor="signin-phone">
        Your phone number
      </label>
      <div className="signin-row">
        <label className="search phone-input">
          <Smartphone size={15} className="muted-icon" />
          <input
            id="signin-phone"
            type="tel"
            inputMode="tel"
            autoComplete="tel"
            placeholder="(555) 010-0123"
            value={input}
            onChange={(e) => {
              setInput(e.target.value);
              if (inputError) setInputError(null);
            }}
            maxLength={24}
            aria-invalid={inputError ? true : undefined}
            aria-describedby="signin-phone-help"
          />
        </label>
        <button type="submit" className="btn btn-primary" disabled={sending}>
          {sending ? <LoaderCircle size={15} className="spin-icon" /> : null}
          {sending ? "Getting a code…" : "Get a code"}
        </button>
      </div>
      <p id="signin-phone-help" className="muted small">
        US numbers by default. For other countries start with + and the country code.
      </p>
      {inputError ? (
        <p className="inline-error small" role="alert">
          {inputError}
        </p>
      ) : null}
    </form>
  );
}

/** The card shown on /apps and /apps/[id] while signed out. */
export default function SignInCard() {
  const { notice } = useAuth();
  return (
    <section className="card signin-card" aria-labelledby="signin-title">
      <h2 id="signin-title" className="signin-title">
        Sign in with your phone
      </h2>
      <p className="muted signin-explain">
        Your apps&apos; data is tied to your phone number. Sign in by texting a code to the ScanSafe Chert line.
      </p>
      {notice ? (
        <p className="notice small signin-notice">
          <Info size={14} strokeWidth={2} />
          {notice}
        </p>
      ) : null}
      <PhoneSignInFlow />
    </section>
  );
}
