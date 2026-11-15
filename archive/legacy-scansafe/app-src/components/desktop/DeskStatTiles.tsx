"use client";

import { useEffect, useState } from "react";
import Counter from "@/components/reactbits/Counter/Counter";
import SpotlightCard from "@/components/reactbits/SpotlightCard/SpotlightCard";
import { getStats, type SampleReason } from "@/lib/api";
import type { StatsSummary } from "@/lib/types";
import s from "./statTiles.module.css";

const LIME_GLOW = "rgba(10, 228, 68, 0.28)";

/** Four live totals from getStats(24): react-bits Counter inside react-bits SpotlightCard. */
export default function DeskStatTiles() {
  const [summary, setSummary] = useState<StatsSummary | null>(null);
  const [sample, setSample] = useState<SampleReason | null>(null);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      const res = await getStats(24);
      if (!alive) return;
      setSummary(res.summary);
      setSample(res.reason);
    };
    void load();
    const t = setInterval(load, 30000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  if (!summary) return <p className="progress" role="status">Loading stats…</p>;

  const avg = summary.avg_scan_ms ? Math.round(summary.avg_scan_ms / 100) / 10 : null;
  const tiles: { label: string; value: number | null; color: string; decimals?: number; suffix?: string }[] = [
    { label: "Links and codes checked", value: summary.total_scans, color: "#ffffff" },
    { label: "Scams caught", value: summary.malicious, color: "#c0262d" },
    { label: "Looked risky", value: summary.suspicious, color: "#ffffff" },
    { label: "Average check time", value: avg, color: "#0ae448", decimals: 1, suffix: "s" },
  ];

  return (
    <>
      {sample && <p className="notice" role="status">Live stats aren&apos;t available right now. These are sample numbers.</p>}
      <ul className={s.tiles}>
        {tiles.map((t) => (
          <li key={t.label}>
            <SpotlightCard className={s.tile} spotlightColor={LIME_GLOW}>
              <span className="sr-only">{t.value === null ? "Not available" : `${t.value}${t.suffix ?? ""}`}: </span>
              <span aria-hidden="true" className={s.num}>
                {t.value === null ? "–" : (
                  <Counter value={t.value} decimals={t.decimals} suffix={t.suffix} fontSize={56} fontWeight={800} textColor={t.color} />
                )}
              </span>
              <span className={s.label}>{t.label}</span>
            </SpotlightCard>
          </li>
        ))}
      </ul>
    </>
  );
}
