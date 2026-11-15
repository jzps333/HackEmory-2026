"use client";

import { useEffect, useRef, useState } from "react";
import type { Html5Qrcode } from "html5-qrcode";

const READER_ID = "qr-reader";

interface Props {
  onResult: (text: string) => void;
  /** Called from the "Paste a link instead" button shown when the camera can't be used. */
  onPasteInstead?: () => void;
}

function cameraErrorMessage(e: unknown): string {
  const msg = String((e as Error)?.message || e);
  if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
    return "The camera only works on a secure (https) page. Paste the link below instead.";
  }
  if (/permission|notallowed|denied/i.test(msg)) {
    return "We couldn't use your camera. Please allow camera access in your browser settings, or paste the link below instead.";
  }
  return "We couldn't start your camera. You can paste the link below instead.";
}

async function shutdown(inst: Html5Qrcode) {
  try {
    if (inst.isScanning) await inst.stop();
    inst.clear();
  } catch {
    /* already stopped */
  }
}

/** Camera QR scanner. html5-qrcode is imported only when the user taps the button (client only). */
export default function Scanner({ onResult, onPasteInstead }: Props) {
  const [active, setActive] = useState(false);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const qr = useRef<Html5Qrcode | null>(null);
  const done = useRef(false);
  // Bumped by stop(): a start() still waiting on the camera sees it changed and turns the camera back off.
  const session = useRef(0);
  const sectionRef = useRef<HTMLElement>(null);

  async function stop() {
    session.current++;
    done.current = true;
    const inst = qr.current;
    qr.current = null;
    setActive(false);
    if (inst) await shutdown(inst);
  }

  async function start() {
    const mine = ++session.current;
    setError(null);
    setStarting(true);
    done.current = false;
    try {
      const { Html5Qrcode, Html5QrcodeSupportedFormats } = await import("html5-qrcode");
      if (mine !== session.current) return;
      setActive(true);
      // Wait a frame so the reader div is visible before the camera attaches.
      await new Promise((r) => requestAnimationFrame(() => r(null)));
      if (mine !== session.current) return;
      // Only look for QR codes: decoding is much faster on phones than trying every barcode type.
      const inst = new Html5Qrcode(READER_ID, { verbose: false, formatsToSupport: [Html5QrcodeSupportedFormats.QR_CODE] });
      qr.current = inst;
      // Back camera. html5-qrcode makes the <video> muted + playsinline, which iPhone needs to show it inline.
      await inst.start(
        { facingMode: "environment" },
        { fps: 10, qrbox: (w, h) => { const s = Math.max(50, Math.floor(Math.min(w, h) * 0.75)); return { width: s, height: s }; } },
        (text) => {
          if (done.current) return;
          done.current = true;
          if (navigator.vibrate) navigator.vibrate(80);
          void stop();
          onResult(text);
        },
        () => { /* no code in this frame yet */ },
      );
      if (mine !== session.current) {
        // Stopped, or the page was left, while the camera was starting: don't leave it running.
        await shutdown(inst);
        return;
      }
      // Bring the whole camera view and the Stop button on screen (the page may be scrolled).
      const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
      sectionRef.current?.scrollIntoView({ block: "nearest", behavior: reduce ? "auto" : "smooth" });
    } catch (e) {
      if (mine !== session.current) return;
      await stop();
      setError(cameraErrorMessage(e));
    } finally {
      setStarting(false);
    }
  }

  useEffect(() => {
    // iPhone freezes the camera when Safari goes to the background: stop cleanly, they can tap Scan again.
    const onHide = () => {
      if (document.visibilityState === "hidden" && qr.current) void stop();
    };
    document.addEventListener("visibilitychange", onHide);
    return () => {
      document.removeEventListener("visibilitychange", onHide);
      void stop();
    };
    // stop() only touches refs and state setters, so the first render's copy is fine.
  }, []);

  return (
    <section aria-labelledby="scan-heading" ref={sectionRef}>
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
      {error && (
        <div className="notice bad" role="alert">
          <p style={{ margin: 0 }}>{error}</p>
          {onPasteInstead && (
            <button type="button" className="btn" style={{ marginTop: "0.75rem" }} onClick={onPasteInstead}>
              Paste a link instead
            </button>
          )}
        </div>
      )}
    </section>
  );
}
