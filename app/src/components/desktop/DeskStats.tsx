"use client";

import DashboardClient from "@/app/dashboard/DashboardClient";
import { GridScan } from "@/components/reactbits/GridScan/GridScan";
import DeskHero from "./DeskHero";
import DeskStatTiles from "./DeskStatTiles";
import Reveal from "./Reveal";
import s from "./pages.module.css";

export default function DeskStats() {
  return (
    <>
      <DeskHero
        bg={<GridScan linesColor="#3a3a3a" scanColor="#0ae448" />}
        kicker="Live numbers"
        title="What people checked with ScanSafe."
        sub="Every check is logged. These numbers update every 30 seconds."
      />
      <Reveal>
        <div className={s.block}><DeskStatTiles /></div>
      </Reveal>
      <Reveal>
        {/* The existing dashboard: its own title, intro and number tiles are replaced by the ones above. */}
        <div className={s.statsPage}><DashboardClient /></div>
      </Reveal>
    </>
  );
}
