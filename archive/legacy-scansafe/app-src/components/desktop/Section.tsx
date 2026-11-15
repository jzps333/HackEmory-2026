import type { ReactNode } from "react";
import ScrollScene from "./ScrollScene";
import s from "./onepage.module.css";

/** A full-width, full-height band of the one-page site with an animated background behind its content. */
export default function Section({ id, labelledBy, bg, children, className }: { id?: string; labelledBy: string; bg?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section id={id} aria-labelledby={labelledBy} className={`${s.section}${className ? ` ${className}` : ""}`}>
      {bg && <ScrollScene className={s.bg}>{bg}</ScrollScene>}
      <div className={s.inner}>{children}</div>
    </section>
  );
}
