"use client";

import { useEffect, useState } from "react";
import { getStats, type SampleReason } from "@/lib/api";
import { scamLabel } from "@/lib/labels";
import type { HourlyBucket, StatsSummary } from "@/lib/types";

function hourLabel(h: string | number): string {
  const d = typeof h === "number" ? new Date(h * 1000) : new Date(h);
  if (isNaN(d.getTime())) return String(h);
  return d.toLocaleTimeString([], { hour: "numeric" });
}

export default function DashboardClient() {
  const [summary, setSummary] = useState<StatsSummary | null>(null);
  const [hourly, setHourly] = useState<HourlyBucket[]>([]);
  const [sample, setSample] = useState<SampleReason | null>(null);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      const res = await getStats(24);
      if (!alive) return;
      setSummary(res.summary);
      setHourly(res.hourly);
      setSample(res.reason);
    };
    void load();
    const t = setInterval(load, 30000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  if (!summary) return <p className="progress" role="status">Loading stats…</p>;

  const max = Math.max(1, ...hourly.map((b) => b.total || 0));
  const totalScams = hourly.reduce((a, b) => a + (b.malicious || 0), 0);
  const totalScans = hourly.reduce((a, b) => a + (b.total || 0), 0);
  const topMax = Math.max(1, ...summary.top_scam_types.map((t) => t.count));

  return (
    <>
      <h1>Stats</h1>
      <p>What people checked with ScanSafe. Updates every 30 seconds.</p>
      {sample === "demo_mode" && <p className="notice"><span className="demo-badge">Demo</span> Sample numbers. No server is connected.</p>}
      {sample === "unavailable" && <p className="notice" role="status">Live stats aren&apos;t available right now. You&apos;re seeing sample numbers.</p>}

      <section aria-labelledby="tiles-h">
        <h2 id="tiles-h" className="sr-only">Totals</h2>
        <div className="tiles">
          <div className="tile"><span className="num">{summary.total_scans.toLocaleString()}</span><span className="lbl">QR codes checked</span></div>
          <div className="tile"><span className="num" style={{ color: "var(--bad-strong)" }}>{summary.malicious.toLocaleString()}</span><span className="lbl">Scams caught</span></div>
          <div className="tile"><span className="num" style={{ color: "var(--warn-strong)" }}>{summary.suspicious.toLocaleString()}</span><span className="lbl">Looked risky</span></div>
          <div className="tile"><span className="num">{summary.avg_scan_ms ? `${(summary.avg_scan_ms / 1000).toFixed(1)}s` : "–"}</span><span className="lbl">Average check time</span></div>
        </div>
      </section>

      <section className="card" aria-labelledby="hourly-h">
        <h2 id="hourly-h">Last 24 hours</h2>
        <p>{totalScans} checks, {totalScams} of them scams.</p>
        <div className="legend" aria-hidden="true"><span className="l-scam">Scams</span><span className="l-ok">Other checks</span></div>
        <div className="chart" role="img" aria-label={`Bar chart of checks per hour over the last 24 hours. ${totalScans} checks, ${totalScams} scams. A table with the same numbers follows.`}>
          {hourly.map((b, i) => {
            const scam = b.malicious || 0;
            const other = Math.max(0, (b.total || 0) - scam);
            return (
              <div className="bar" key={i} title={`${hourLabel(b.hour)}: ${b.total} checks, ${scam} scams`} style={{ height: "100%" }}>
                <div className="scam" style={{ height: `${(scam / max) * 100}%` }} />
                <div className="ok" style={{ height: `${(other / max) * 100}%` }} />
              </div>
            );
          })}
        </div>
        {hourly.length > 0 && (
          <div className="chart-axis" aria-hidden="true">
            <span>{hourLabel(hourly[0].hour)}</span>
            <span>{hourLabel(hourly[Math.floor(hourly.length / 2)].hour)}</span>
            <span>{hourLabel(hourly[hourly.length - 1].hour)}</span>
          </div>
        )}
        <details>
          <summary>Show the numbers as a table</summary>
          <div>
            <table>
              <caption className="sr-only">Checks per hour</caption>
              <thead><tr><th scope="col">Hour</th><th scope="col">Checks</th><th scope="col">Scams</th></tr></thead>
              <tbody>
                {hourly.map((b, i) => (
                  <tr key={i}><td>{hourLabel(b.hour)}</td><td>{b.total}</td><td>{b.malicious}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      </section>

      {summary.top_scam_types.length > 0 && (
        <section className="card" aria-labelledby="types-h">
          <h2 id="types-h">Most common scams</h2>
          <ul className="hbar" style={{ listStyle: "none", padding: 0 }}>
            {summary.top_scam_types.map((t) => (
              <li className="hbar-row" key={t.scam_type}>
                <div><strong>{scamLabel(t.scam_type)}</strong>: {t.count}</div>
                <div className="track" aria-hidden="true"><div className="fill" style={{ width: `${(t.count / topMax) * 100}%` }} /></div>
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}
