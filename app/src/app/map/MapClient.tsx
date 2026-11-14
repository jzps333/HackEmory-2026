"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useState } from "react";
import { getPins, searchPins } from "@/lib/api";
import { percent, scamLabel, timeAgo } from "@/lib/labels";
import type { Pin } from "@/lib/types";

const ScamMap = dynamic(() => import("@/components/ScamMap"), {
  ssr: false,
  loading: () => <p className="progress" role="status">Loading the map…</p>,
});

const ATLANTA: [number, number] = [33.79, -84.32];

export default function MapClient() {
  const [center, setCenter] = useState<[number, number]>(ATLANTA);
  const [pins, setPins] = useState<Pin[]>([]);
  const [demo, setDemo] = useState(false);
  const [status, setStatus] = useState("Loading reported scams…");
  const [q, setQ] = useState("");
  const [results, setResults] = useState<Pin[] | null>(null);
  const [focus, setFocus] = useState<Pin | null>(null);

  const load = useCallback(async (c: [number, number]) => {
    setStatus("Loading reported scams…");
    const res = await getPins(c[0], c[1], 5);
    setPins(res.pins);
    setDemo(res.demo);
    setStatus(`${res.pins.length} reported scam${res.pins.length === 1 ? "" : "s"} within 5 kilometers.`);
  }, []);

  useEffect(() => { void load(ATLANTA); }, [load]);

  function locateMe() {
    if (!("geolocation" in navigator)) {
      setStatus("Your browser can't share location.");
      return;
    }
    setStatus("Finding your location…");
    navigator.geolocation.getCurrentPosition(
      (p) => {
        const c: [number, number] = [Math.round(p.coords.latitude * 1000) / 1000, Math.round(p.coords.longitude * 1000) / 1000];
        setCenter(c);
        void load(c);
      },
      () => setStatus("We couldn't get your location. Showing Atlanta instead."),
      { timeout: 8000, maximumAge: 300000 },
    );
  }

  async function onSearch(e: React.FormEvent) {
    e.preventDefault();
    const term = q.trim();
    if (!term) {
      setResults(null);
      return;
    }
    setStatus("Searching…");
    const res = await searchPins(term);
    setResults(res.pins);
    if (res.demo) setDemo(true);
    if (res.pins.length) setPins((prev) => {
      const seen = new Set(prev.map((p) => p.id ?? `${p.url}|${p.reported_at}`));
      return [...prev, ...res.pins.filter((p) => !seen.has(p.id ?? `${p.url}|${p.reported_at}`))];
    });
    setStatus(`${res.pins.length} result${res.pins.length === 1 ? "" : "s"} for "${term}".`);
  }

  return (
    <>
      <h1>Scam map</h1>
      <p>Red pins show scam QR codes that people reported. Tap a pin to see what it was.</p>
      {demo && <p className="notice"><span className="demo-badge">Demo</span> Showing sample pins around Atlanta.</p>}

      <form onSubmit={onSearch} role="search" aria-label="Search reported scams">
        <div className="search-row">
          <div>
            <label htmlFor="map-search">Search scams</label>
            <input id="map-search" type="search" placeholder="Try “parking” or a website name" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
          <button type="submit" className="btn btn-primary">Search</button>
        </div>
      </form>

      <p role="status" aria-live="polite" className="hint" style={{ marginTop: "0.75rem" }}>{status}</p>

      {results && results.length > 0 && (
        <ul className="result-list" aria-label="Search results">
          {results.map((p, i) => (
            <li key={p.id ?? `${p.url}-${i}`}>
              <button type="button" className="btn" onClick={() => setFocus(p)}>
                <span>{scamLabel(p.scam_type)} · {percent(p.jev_score)} likely a scam</span>
                <span className="hint" style={{ fontWeight: 400 }}>{p.domain || p.url} · {timeAgo(p.reported_at)}</span>
                <span className="sr-only">Show on map</span>
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="btn-row">
        <button type="button" className="btn" onClick={locateMe}>Show scams near me</button>
      </div>

      <div className="map-wrap">
        <ScamMap center={center} pins={pins} focus={focus} />
      </div>

      <h2>Reported nearby (list)</h2>
      <p className="hint">The same pins as the map, as a list for screen readers.</p>
      <ul>
        {pins.map((p, i) => (
          <li key={p.id ?? `${p.url}-${i}`} style={{ marginBottom: "0.5rem" }}>
            <strong>{scamLabel(p.scam_type)}</strong>, {percent(p.jev_score)} likely a scam, {timeAgo(p.reported_at)}. {p.explanation}
          </li>
        ))}
      </ul>
    </>
  );
}
