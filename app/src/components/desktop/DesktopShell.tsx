"use client";

import { useEffect, useRef, type ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ReactLenis, useLenis, type LenisRef } from "lenis/react";
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import "lenis/dist/lenis.css";
import PillNav from "@/components/reactbits/PillNav/PillNav";
import { Icon } from "@/components/onboarding/Icon";
import { publicPath } from "@/lib/view";
import { usePrefersReducedMotion } from "./motion";

gsap.registerPlugin(ScrollTrigger);

const ITEMS = [
  { label: "Home", href: "/" },
  { label: "Map", href: "/map" },
  { label: "Stats", href: "/dashboard" },
  { label: "About", href: "/about" },
];

/** Keeps GSAP ScrollTrigger in step with Lenis and starts each page at the top. */
function ScrollSync({ path }: { path: string }) {
  const lenis = useLenis(() => ScrollTrigger.update());
  useEffect(() => {
    lenis?.scrollTo(0, { immediate: true });
    ScrollTrigger.refresh();
  }, [path, lenis]);
  return null;
}

export default function DesktopShell({ children }: { children: ReactNode }) {
  const path = publicPath(usePathname());
  const reduced = usePrefersReducedMotion();
  const lenisRef = useRef<LenisRef>(null);

  // Lenis runs on GSAP's ticker (the setup from the Lenis README) so scroll animations stay in sync.
  useEffect(() => {
    if (reduced) return;
    const update = (time: number) => lenisRef.current?.lenis?.raf(time * 1000);
    gsap.ticker.add(update);
    gsap.ticker.lagSmoothing(0);
    return () => gsap.ticker.remove(update);
  }, [reduced]);

  return (
    <>
      {!reduced && (
        <ReactLenis root options={{ autoRaf: false }} ref={lenisRef}>
          <ScrollSync path={path} />
        </ReactLenis>
      )}
      <header className="desk-header">
        <PillNav
          logo={<Icon name="shield" size={22} />}
          logoAlt="ScanSafe home"
          logoHref="/"
          items={ITEMS}
          activeHref={path}
          linkComponent={Link}
          theme="dark"
          highlightColor="#0ae448"
          highlightTextColor="#000000"
          ariaLabel="Main"
        />
      </header>
      <div className="desk-body">{children}</div>
    </>
  );
}
