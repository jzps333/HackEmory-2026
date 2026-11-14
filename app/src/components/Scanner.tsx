"use client";

import { useEffect, useRef, useState } from "react";
import type { Html5Qrcode } from "html5-qrcode";

const READER_ID = "qr-reader";

interface Props {
  onResult: (text: string) => void;
}

/** Camera QR scanner. html5-qrcode is imported only when the user taps the button (client only). */
export default function Scanner({ onResult }: Props) {
  const [active, setActive] = useState(false);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const qr = useRef<Html5Qrcode | null>(null);
  const done = useRef(false);

  async function stop() {
    const inst = qr.current;
    qr.current = null;
    setActive(false);
    if (inst) {
      try {
        if (inst.isScanning) await inst.stop();
        inst.clear();
      } catch {
        /* already stopped */
      }
    }
  }

  async function start() {
    setError(null);
    setStarting(true);
    done.current = false;
    try {
      const { Html5Qrcode } = await import("html5-qrcode");
      setActive(true);
      // Wait a frame so the reader div is visible before the camera attaches.
      await new Promise((r) => requestAnimationFrame(() => r(null)));
      const inst = new Html5Qrcode(READER_ID, { verbose: false });
      qr.current = inst;
      await inst.start(
        { facingMode: "environment" },
        { fps: 10, qrbox: (w, h) => { const s = Math.floor(Math.min(w, h) * 0.75); return { width: s, height: s }; } },
        (text) => {
          if (done.current) return;
          done.current = true;
          if (navigator.vibrate) navigator.vibrate(80);
          void stop();
          onResult(text);
        },
        () => { /* no code in this frame yet */ },
      );
    } catch (e) {
      await stop();
      const msg = String((e as Error)?.message || e);
      if (/permission|notallowed/i.test(msg)) {
        setError("We couldn't use your camera. Please allow camera access in your browser settings, or paste the link below instead.");
      } else if (!window.isSecureContext) {
        setError("The camera only works on a secure (https) page. Paste the link below instead.");
      } else {
        setError("We couldn't start your camera. You can paste the link below instead.");
      }
    } finally {
      setStarting(false);
    }
  }

  useEffect(() => () => { void stop(); }, []);

  return (
    <section aria-labelledby="scan-heading">
      <h2 id="scan-heading" className="sr-only">Scan with your camera</h2>
      {!active && (
        <button type="button" className="btn btn-primary btn-huge" onClick={start} disabled={starting}>
          <svg width="36" height="36" viewBox="0 0 24 24" aria-hidden="true" focusable="false" fill="none" stroke="currentColor" strokeWidth="2.2">
            <path d="M3 8V4h4M17 4h4v4M21 16v4h-4M7 20H3v-4" strokeLinecap="round" />
            <rect x="8" y="8" width="8" height="8" rx="1" />
          </svg>
          {starting ? "Starting camera…" : "Scan a QR code"}
        </button>
      )}
      <div id={READER_ID} className="reader" hidden={!active} aria-label="Camera view. Point your camera at the QR code." role="img" />
      {active && (
        <>
          <p aria-live="polite" className="hint">Point your camera at the QR code. Hold still.</p>
          <button type="button" className="btn" onClick={stop}>Stop camera</button>
        </>
      )}
      {error && <p className="notice bad" role="alert">{error}</p>}
    </section>
  );
}
