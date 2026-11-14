"use client";

import { useEffect, useState, useSyncExternalStore, type Ref } from "react";
import type { LiveScanHandlers } from "@/lib/api";
import s from "./LiveCheck.module.css";

const STEPS = ["Opening safely", "Following where it leads", "Looking at the page", "Checking for scams"] as const;
/** Show at most ~8 frames a second, however fast the server sends them. */
const FRAME_MS = 125;

export interface LiveSnapshot {
  frame: string | null;
  sawFrame: boolean;
  host: string;
  navs: number;
  fallback: boolean;
}

export interface LiveFeed {
  /** Pass these to scanUrlLive. */
  handlers: Required<LiveScanHandlers>;
  subscribe: (fn: () => void) => () => void;
  getSnapshot: () => LiveSnapshot;
}

/** Only the host name, so "Now on" stays short. Falls back to the raw text for non-web codes. */
export function hostOf(raw: string): string {
  for (const candidate of [raw, `https://${raw}`]) {
    try {
      const h = new URL(candidate).host;
      if (h) return h;
    } catch {
      /* try the next form */
    }
  }
  return raw.length > 48 ? `${raw.slice(0, 48)}…` : raw;
}

/**
 * A tiny store between the stream and the screen: frames are throttled here, so a fast
 * stream never re-renders React more than ~8 times a second.
 */
export function createLiveFeed(url: string): LiveFeed {
  let snap: LiveSnapshot = { frame: null, sawFrame: false, host: hostOf(url), navs: 0, fallback: false };
  let pending: string | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let lastFlush = 0;
  const listeners = new Set<() => void>();
  const emit = () => listeners.forEach((fn) => fn());

  const flush = () => {
    timer = null;
    lastFlush = Date.now();
    if (!pending || snap.fallback) return;
    snap = { ...snap, frame: pending, sawFrame: true };
    pending = null;
    emit();
  };

  return {
    handlers: {
      onFrame(dataUrl) {
        pending = dataUrl;
        if (!timer) timer = setTimeout(flush, Math.max(0, FRAME_MS - (Date.now() - lastFlush)));
      },
      onNav(navUrl) {
        snap = { ...snap, host: hostOf(navUrl) || snap.host, navs: snap.navs + 1 };
        emit();
      },
      onFallback() {
        pending = null;
        snap = { ...snap, frame: null, fallback: true };
        emit();
      },
    },
    subscribe(fn) {
      listeners.add(fn);
      return () => {
        listeners.delete(fn);
      };
    },
    getSnapshot: () => snap,
  };
}

function stepFor(snap: LiveSnapshot, ms: number): number {
  const started = snap.sawFrame || snap.navs > 0 || snap.fallback;
  let step = 0;
  if (started || ms >= 3000) step = 1;
  if ((snap.sawFrame && snap.navs > 0 && ms >= 2000) || snap.navs >= 2 || ms >= 4500) step = 2;
  // Last step stays "in progress" until the result replaces this screen: never shown as done.
  if (ms >= 6000 && (started || ms >= 10000)) step = 3;
  return step;
}

export default function LiveCheck({ feed, statusRef }: { feed: LiveFeed; statusRef?: Ref<HTMLDivElement> }) {
  const snap = useSyncExternalStore(feed.subscribe, feed.getSnapshot, feed.getSnapshot);
  const [ms, setMs] = useState(0);

  useEffect(() => {
    setMs(0);
    const ids = [2000, 3000, 4500, 6000, 10000].map((t) => setTimeout(() => setMs(t), t));
    return () => ids.forEach(clearTimeout);
  }, [feed]);

  const step = stepFor(snap, ms);
  const live = !snap.fallback;

  return (
    <section className={s.card} aria-labelledby="live-h">
      <header className={s.head}>
        <h1 id="live-h" className={s.title}>Opening it safely on our computer</h1>
        <p className={s.sub}>
          {live && (
            <span className={s.pill}>
              <span className={s.dot} aria-hidden="true" />
              LIVE
            </span>
          )}
          <span>on our computer, not your phone</span>
        </p>
      </header>

      <p className={s.now}>
        Now on: <strong className={s.host}>{snap.host}</strong>
      </p>

      <div className={s.phone}>
        {snap.frame ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img className={s.screen} src={snap.frame} alt="Live view of the page on our computer" />
        ) : (
          <div className={s.placeholder}>
            <div className={s.spinner} aria-hidden="true" />
            <p>{snap.fallback ? "Still checking…" : "Starting a safe browser…"}</p>
          </div>
        )}
      </div>

      <div className={s.progress}>
        <ol className={s.bar} aria-hidden="true">
          {STEPS.map((label, i) => (
            <li key={label} className={i < step ? s.done : i === step ? s.current : undefined} />
          ))}
        </ol>
        <div className={s.status} role="status" aria-live="polite" tabIndex={-1} ref={statusRef}>
          Step {step + 1} of {STEPS.length}: {STEPS[step]}…
        </div>
        <p className={s.hint}>Nothing opens on your phone. This usually takes a few seconds.</p>
      </div>
    </section>
  );
}
