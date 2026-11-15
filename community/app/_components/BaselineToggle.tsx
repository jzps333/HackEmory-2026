"use client";

import { useEffect, useState } from "react";
import { errorText, getBaseline, setBaseline } from "@/lib/api";

/** Demo switch: calls use plain Chert (no skills) or Chert with community skills. */
export default function BaselineToggle() {
  const [baseline, setBaselineState] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getBaseline().then(setBaselineState).catch(() => setBaselineState(false));
  }, []);

  async function choose(on: boolean) {
    if (busy || baseline === on) return;
    const before = baseline;
    setBaselineState(on);
    setBusy(true);
    setError(null);
    try {
      setBaselineState(await setBaseline(on));
    } catch (e) {
      setBaselineState(before);
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="baseline-toggle" role="group" aria-label="What your next Chert call uses">
      <span className="baseline-label">Next call uses</span>
      <button
        type="button"
        className={`pill ${baseline === true ? "pill-on" : ""}`}
        aria-pressed={baseline === true}
        onClick={() => choose(true)}
        disabled={busy || baseline === null}
      >
        Chert out of the box
      </button>
      <button
        type="button"
        className={`pill ${baseline === false ? "pill-on" : ""}`}
        aria-pressed={baseline === false}
        onClick={() => choose(false)}
        disabled={busy || baseline === null}
      >
        Chert + community skills
      </button>
      {error ? <span className="baseline-error">{error}</span> : null}
    </div>
  );
}
