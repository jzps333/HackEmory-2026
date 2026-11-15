"use client";

import { useEffect, useState, type FormEvent } from "react";
import { DEMO_VERIFICATION_CODE } from "@/services/appServices";

export function Verify({
  phone,
  onVerify,
}: {
  phone: string;
  onVerify: (code: string) => boolean;
}) {
  const [code, setCode] = useState("");
  const [seconds, setSeconds] = useState(30);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (seconds <= 0) return;
    const timer = window.setTimeout(() => setSeconds((value) => value - 1), 1000);
    return () => window.clearTimeout(timer);
  }, [seconds]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (onVerify(code)) {
      setError("");
      return;
    }
    setError("That code doesn’t match. Please try again.");
  }

  return (
    <section className="screen-content">
      <div className="screen-heading">
        <span className="eyebrow">QUICK CHECK</span>
        <h1>Confirm it’s you.</h1>
        <p>Enter the six-digit demo code to confirm your parking session.</p>
      </div>
      <div className="quiet-note">
        <span aria-hidden="true">✓</span>
        <p>No text message is sent. For this demo, use <strong>{DEMO_VERIFICATION_CODE}</strong>{phone ? ` for ${phone}` : ""}.</p>
      </div>
      <form className="verify-form" onSubmit={submit}>
        <label className="field">
          <span>Six-digit code</span>
          <div className="otp-container">
            <div className="otp-slots" aria-hidden="true">
              {Array.from({ length: 6 }, (_, index) => (
                <span className={index === code.length ? "otp-current" : ""} key={index}>
                  {code[index] || ""}
                </span>
              ))}
            </div>
            <input
              className="otp-input"
              aria-label="Six-digit verification code"
              autoComplete="one-time-code"
              inputMode="numeric"
              pattern="[0-9]{6}"
              maxLength={6}
              required
              value={code}
              onChange={(event) => {
                setCode(event.target.value.replace(/\D/g, "").slice(0, 6));
                setError("");
              }}
              placeholder="000000"
            />
          </div>
        </label>
        {error && <p className="form-error" role="alert">{error}</p>}
        <button className="primary-button full-button" type="submit">Confirm parking</button>
      </form>
      <p className="resend-note" aria-live="polite">
        {seconds > 0
          ? `You can reset the demo code in 0:${String(seconds).padStart(2, "0")}.`
          : "You can reset the demo code now."}
      </p>
      {notice && <p className="resend-note" role="status">{notice}</p>}
      <button
        className="text-button full-button"
        type="button"
        disabled={seconds > 0}
        onClick={() => {
          setSeconds(30);
          setCode("");
          setError("");
          setNotice("Demo code reset. Use the code shown above; no message was sent.");
        }}
      >
        Reset demo code
      </button>
      <p className="fine-print">This is a local simulation. No SMS or payment is processed.</p>
    </section>
  );
}
