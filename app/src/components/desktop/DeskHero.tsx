"use client";

import type { ReactNode } from "react";
import SplitText from "@/components/reactbits/SplitText/SplitText";
import s from "./pages.module.css";

/** Page header band: a react-bits / Vanta background behind a SplitText title. */
export default function DeskHero({ bg, kicker, title, sub }: { bg: ReactNode; kicker: string; title: string; sub: string }) {
  return (
    <section className={s.hero} aria-labelledby="page-title">
      <div className={s.heroBg} aria-hidden="true">{bg}</div>
      <div className={s.heroContent}>
        <p className={s.kicker}>{kicker}</p>
        <h1 id="page-title" className={s.title} aria-label={title}>
          <SplitText text={title} tag="span" textAlign="left" splitType="words, chars" trigger="load" />
        </h1>
        <p className={s.sub}>{sub}</p>
      </div>
    </section>
  );
}
