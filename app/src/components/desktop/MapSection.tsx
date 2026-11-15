"use client";

import { useState, type MouseEvent } from "react";
import MapClient from "@/app/map/MapClient";
import s from "./onepage.module.css";

/**
 * The existing interactive map (search, "near me", live Typesense pins). The mouse wheel scrolls the page until
 * the map is clicked; then it pans and zooms the map until the pointer leaves it.
 */
export default function MapSection() {
  const [active, setActive] = useState(false);

  function onClick(e: MouseEvent<HTMLDivElement>) {
    if (active) return;
    const wrap = e.currentTarget.querySelector(".map-wrap");
    const r = wrap?.getBoundingClientRect();
    if (r && e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top && e.clientY <= r.bottom) setActive(true);
  }

  return (
    <div
      className={`${s.mapArea}${active ? "" : ` ${s.mapLocked}`}`}
      onClick={onClick}
      onMouseLeave={() => setActive(false)}
      {...(active ? { "data-lenis-prevent": "" } : {})}
    >
      <MapClient />
    </div>
  );
}
