"use client";

import type { ReactNode } from "react";
import AnimatedContent from "@/components/reactbits/AnimatedContent/AnimatedContent";

/** Section entrance on scroll (react-bits AnimatedContent, which shows content at rest under reduced motion). */
export default function Reveal({ children, className, delay }: { children: ReactNode; className?: string; delay?: number }) {
  return (
    <AnimatedContent className={className} trigger="scroll" once delay={delay}>
      {children}
    </AnimatedContent>
  );
}
