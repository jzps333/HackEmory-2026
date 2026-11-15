"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { usePrefersReducedMotion } from "./motion";

gsap.registerPlugin(ScrollTrigger);

const CLOSED = { clipPath: "inset(16% 12% 16% 12% round 40px)", opacity: 0 };
const OPEN = { clipPath: "inset(0% 0% 0% 0% round 0px)", opacity: 1 };

/**
 * A section's animated background that opens as the section scrolls in and closes as it scrolls out (GSAP
 * ScrollTrigger, scrubbed to the scroll), so only the scene in front of you is showing. Static under reduced motion.
 */
export default function ScrollScene({ children, className }: { children: ReactNode; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const reduced = usePrefersReducedMotion();

  useEffect(() => {
    const el = ref.current;
    const section = el?.parentElement;
    if (reduced || !el || !section) return;
    const ctx = gsap.context(() => {
      gsap.timeline({ scrollTrigger: { trigger: section, start: "top bottom", end: "bottom top", scrub: 0.5 } })
        .fromTo(el, CLOSED, { ...OPEN, ease: "power2.out", duration: 0.35 })
        .to(el, { duration: 0.3 })
        .to(el, { ...CLOSED, ease: "power2.in", duration: 0.35 });
    });
    return () => ctx.revert();
  }, [reduced]);

  return <div ref={ref} className={className} aria-hidden="true">{children}</div>;
}
