"use client";

import { useState, type FormEvent } from "react";
import { QRScanner } from "@/components/QRScanner";
import { DEMO_SCAN_EXAMPLES } from "@/services/appServices";

export function Scanner({
  onResult,
  onClose,
  feedback,
}: {
  onResult: (value: string) => void;
  onClose: () => void;
  feedback?: string;
}) {
  const [value, setValue] = useState("");
  const [error, setError] = useState("");

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!value.trim()) {
      setError("Enter a web address to check.");
      return;
    }
    setError("");
    onResult(value);
  }

  return (
    <section className="screen-content">
      <div className="screen-heading">
        <span className="eyebrow">QR CHECK</span>
        <h1>Check a QR code before you open it.</h1>
        <p>Point your camera at a QR code, or paste its link below.</p>
      </div>
      <QRScanner onResult={onResult} onClose={onClose} />
      <form className="manual-entry" onSubmit={submit}>
        <label className="field">
          <span>Paste a web address</span>
          <input
            type="url"
            inputMode="url"
            autoComplete="url"
            placeholder="https://example.com"
            value={value}
            onChange={(event) => setValue(event.target.value)}
          />
        </label>
        {(error || feedback) && <p className="form-error" role="alert">{error || feedback}</p>}
        <button className="primary-button full-button" type="submit">Check this link</button>
      </form>
      <div className="example-links">
        <span className="eyebrow">TRY A DEMO LINK</span>
        {DEMO_SCAN_EXAMPLES.map((example) => (
          <button
            className="example-link"
            type="button"
            key={example.label}
            onClick={() => onResult(example.url)}
          >
            {example.label}<span aria-hidden="true">↗</span>
          </button>
        ))}
      </div>
      <p className="fine-print">We check the address only. It won’t open unless you choose to leave this app.</p>
    </section>
  );
}
