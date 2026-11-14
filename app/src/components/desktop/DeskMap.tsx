"use client";

import MapClient from "@/app/map/MapClient";
import Radar from "@/components/reactbits/Radar/Radar";
import DeskHero from "./DeskHero";
import Reveal from "./Reveal";
import s from "./pages.module.css";

export default function DeskMap() {
  return (
    <>
      <DeskHero
        bg={<Radar color="#0ae448" backgroundColor="#000000" />}
        kicker="Scam map"
        title="Scam QR codes reported near you."
        sub="Red pins are codes people reported. Click one to see what it was, or search by website or scam type."
      />
      <Reveal>
        {/* data-lenis-prevent: the wheel zooms the map here instead of smooth-scrolling the page. */}
        <div className={s.mapPage} data-lenis-prevent>
          <MapClient />
        </div>
      </Reveal>
    </>
  );
}
