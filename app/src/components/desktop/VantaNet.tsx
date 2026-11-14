"use client";

import { useEffect, useRef } from "react";
import { usePrefersReducedMotion } from "./motion";

/** Vanta NET (lime on black) filling its positioned parent. Nothing under reduced motion or without WebGL. */
export default function VantaNet({ className }: { className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const reduced = usePrefersReducedMotion();

  useEffect(() => {
    if (reduced || !ref.current) return;
    let effect: { destroy: () => void } | null = null;
    let cancelled = false;
    void (async () => {
      const [THREE, mod] = await Promise.all([import("three"), import("vanta/dist/vanta.net.min")]);
      if (cancelled || !ref.current) return;
      // The UMD build can arrive wrapped once or twice depending on the bundler's interop.
      const m = mod as unknown as { default?: unknown };
      const NET = ((m.default as { default?: unknown })?.default ?? m.default ?? mod) as typeof mod.default;
      try {
        effect = NET({ el: ref.current, THREE, color: 0x0ae448, backgroundColor: 0x000000, mouseControls: true, touchControls: false, gyroControls: false });
      } catch {
        // No WebGL: the black background stays.
      }
    })();
    return () => {
      cancelled = true;
      effect?.destroy();
    };
  }, [reduced]);

  if (reduced) return null;
  return <div ref={ref} className={className} aria-hidden="true" />;
}
