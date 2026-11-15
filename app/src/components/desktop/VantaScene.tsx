"use client";

import { useEffect, useRef } from "react";
import { usePrefersReducedMotion } from "./motion";

export type VantaEffectName = "net" | "waves" | "dots" | "globe" | "rings" | "birds";

// One static import per effect so the bundler can split them; each loads only when its section is near the screen.
const LOADERS: Record<VantaEffectName, () => Promise<unknown>> = {
  net: () => import("vanta/dist/vanta.net.min"),
  waves: () => import("vanta/dist/vanta.waves.min"),
  dots: () => import("vanta/dist/vanta.dots.min"),
  globe: () => import("vanta/dist/vanta.globe.min"),
  rings: () => import("vanta/dist/vanta.rings.min"),
  birds: () => import("vanta/dist/vanta.birds.min"),
};

type Create = (options: Record<string, unknown>) => { destroy: () => void };

/** The UMD build can arrive wrapped once or twice depending on the bundler's interop. */
function unwrap(mod: unknown): Create {
  const m = mod as { default?: unknown };
  return ((m.default as { default?: unknown } | undefined)?.default ?? m.default ?? mod) as Create;
}

/**
 * A Vanta.js effect filling its positioned parent. Runs only while on (or near) the screen and is destroyed when
 * scrolled away, so several scenes on one page don't all hold a WebGL context. Nothing under reduced motion.
 */
export default function VantaScene({ effect, options, className }: { effect: VantaEffectName; options: Record<string, unknown>; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const optionsRef = useRef(options);
  optionsRef.current = options;
  const reduced = usePrefersReducedMotion();

  useEffect(() => {
    const el = ref.current;
    if (reduced || !el) return;
    let instance: { destroy: () => void } | null = null;
    let loading = false;
    let visible = false;
    let alive = true;

    const start = async () => {
      if (instance || loading) return;
      loading = true;
      // Some Vanta builds (DOTS) read window.THREE when their module loads instead of options.THREE.
      const THREE = await import("three");
      const w = window as unknown as { THREE?: unknown };
      w.THREE ??= THREE;
      const mod = await LOADERS[effect]();
      loading = false;
      if (!alive || !visible || instance) return;
      try {
        instance = unwrap(mod)({ el, THREE, mouseControls: true, touchControls: false, gyroControls: false, ...optionsRef.current });
      } catch (err) {
        // No WebGL (or the effect failed): the black background stays.
        console.warn("Vanta effect could not start:", effect, err);
      }
    };
    const stop = () => {
      try {
        instance?.destroy();
      } catch {
        // An effect whose init failed has no canvas to remove.
      }
      instance = null;
    };

    const io = new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting;
      if (visible) void start();
      else stop();
    }, { rootMargin: "200px 0px" });
    io.observe(el);
    return () => {
      alive = false;
      io.disconnect();
      stop();
    };
  }, [effect, reduced]);

  if (reduced) return null;
  return <div ref={ref} className={className} aria-hidden="true" />;
}
