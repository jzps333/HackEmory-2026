"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { ReactLenis, useLenis, type LenisRef } from "lenis/react";
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import "lenis/dist/lenis.css";
import PillNav from "@/components/reactbits/PillNav/PillNav";
import { Icon } from "@/components/onboarding/Icon";
import { sectionFor } from "@/lib/view";
import { usePrefersReducedMotion } from "./motion";

gsap.registerPlugin(ScrollTrigger);

const ITEMS = [
  { label: "Home", href: "#top" },
  { label: "Map", href: "#map" },
  { label: "Stats", href: "#stats" },
  { label: "About", href: "#about" },
];

/** Keeps GSAP ScrollTrigger in step with Lenis. */
function ScrollSync() {
  useLenis(() => ScrollTrigger.update());
  return null;
}

/** The nav item for the section crossing the middle of the screen. */
function useActiveSection(): string {
  const [active, setActive] = useState("#top");
  useEffect(() => {
    const els = ITEMS.map((i) => document.getElementById(i.href.slice(1))).filter((el): el is HTMLElement => !!el);
    const io = new IntersectionObserver((entries) => {
      for (const e of entries) if (e.isIntersecting) setActive(`#${e.target.id}`);
    }, { rootMargin: "-45% 0px -50% 0px" });
    els.forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, []);
  return active;
}

export default function DesktopShell({ children }: { children: ReactNode }) {
  const reduced = usePrefersReducedMotion();
  const lenisRef = useRef<LenisRef>(null);
  const active = useActiveSection();

  // Lenis runs on GSAP's ticker (the setup from the Lenis README) so scroll animations stay in sync.
  useEffect(() => {
    if (reduced) return;
    const update = (time: number) => lenisRef.current?.lenis?.raf(time * 1000);
    gsap.ticker.add(update);
    gsap.ticker.lagSmoothing(0);
    return () => gsap.ticker.remove(update);
  }, [reduced]);

  // ScrollTrigger measures section positions once; the map, stats and scan list load later and push the lower
  // sections down (and a check hides the whole page). Re-measure whenever the page's height changes, or the
  // open/close scenes would run at the wrong scroll positions.
  const bodyRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const body = bodyRef.current;
    if (!body) return;
    let t = 0;
    const ro = new ResizeObserver(() => {
      window.clearTimeout(t);
      t = window.setTimeout(() => ScrollTrigger.refresh(), 150);
    });
    ro.observe(body);
    return () => {
      ro.disconnect();
      window.clearTimeout(t);
    };
  }, []);

  // /map, /dashboard and /about open the one page at their section.
  useEffect(() => {
    const target = sectionFor(window.location.pathname);
    if (target === "top") return;
    const t = window.setTimeout(() => {
      const lenis = lenisRef.current?.lenis;
      if (lenis) lenis.scrollTo(`#${target}`, { immediate: true });
      else document.getElementById(target)?.scrollIntoView();
    }, 400);
    return () => window.clearTimeout(t);
  }, []);

  return (
    <>
      {!reduced && (
        <ReactLenis root options={{ autoRaf: false, anchors: true, prevent: (node) => !!node.closest(".scan-hits") }} ref={lenisRef}>
          <ScrollSync />
        </ReactLenis>
      )}
      <header className="desk-header">
        <PillNav
          logo={<Icon name="shield" size={22} />}
          logoAlt="ScanSafe, back to top"
          logoHref="#top"
          items={ITEMS}
          activeHref={active}
          theme="dark"
          highlightColor="#0ae448"
          highlightTextColor="#000000"
          ariaLabel="Main"
        />
      </header>
      <div className="desk-body" ref={bodyRef}>{children}</div>
    </>
  );
}
