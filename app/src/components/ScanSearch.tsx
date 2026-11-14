"use client";

import { useEffect, useRef, useState } from "react";
import { DEMO_MODE, searchScans, type ScanHit, type ScanSearchResult } from "@/lib/api";
import { scamLabel } from "@/lib/labels";

const VERDICTS: { value: string; label: string }[] = [
  { value: "", label: "All" },
  { value: "malicious", label: "Scams" },
  { value: "suspicious", label: "Be careful" },
  { value: "safe", label: "Safe" },
];

/** Typesense highlights are escaped server-side; allow only <mark> through, as a second guard. */
function safeHighlight(html: string): string {
  return html.replace(/<(?!\/?mark>)[^>]*>/g, "");
}

function when(ts: number): string {
  const mins = Math.round((Date.now() / 1000 - ts) / 60);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const h = Math.round(mins / 60);
  return h < 24 ? `${h} h ago` : new Date(ts * 1000).toLocaleDateString();
}

function Hit({ h }: { h: ScanHit }) {
  const domainHtml = h.highlight?.domain ? safeHighlight(h.highlight.domain) : null;
  return (
    <li className={`scan-hit scan-hit-${h.verdict}`}>
      <div className="scan-hit-top">
        <span className={`scan-hit-verdict verdict-chip-${h.verdict}`}>
          {h.verdict === "malicious" ? "Scam" : h.verdict === "suspicious" ? "Be careful" : "Safe"}
        </span>
        <span className="scan-hit-when">{when(h.scanned_at)}</span>
      </div>
      <p className="scan-hit-domain">
        {domainHtml ? <span dangerouslySetInnerHTML={{ __html: domainHtml }} /> : (h.domain || "QR code")}
      </p>
      {h.scam_type && h.scam_type !== "none" && <p className="scan-hit-type">{scamLabel(h.scam_type)}</p>}
      {h.explanation && h.verdict !== "safe" && <p className="scan-hit-expl">{h.explanation}</p>}
    </li>
  );
}

export default function ScanSearch() {
  const [q, setQ] = useState("");
  const [verdict, setVerdict] = useState("");
  const [res, setRes] = useState<ScanSearchResult | null>(null);
  const [error, setError] = useState(false);
  const seq = useRef(0);

  useEffect(() => {
    const mine = ++seq.current;
    const t = window.setTimeout(async () => {
      try {
        const r = await searchScans(q.trim() || "*", verdict || undefined);
        if (mine === seq.current) { setRes(r); setError(false); }
      } catch {
        if (mine === seq.current) setError(true);
      }
    }, 250); // debounce typing
    return () => window.clearTimeout(t);
  }, [q, verdict]);

  return (
    <section className="card scan-search" aria-labelledby="search-h">
      <h2 id="search-h">Search every check</h2>
      <p className="hint">Every scan is saved in Tiger Data and searchable with Typesense. Typos are fine: try “wikipeda”.</p>
      <label htmlFor="scan-q" className="sr-only">Search checks by website</label>
      <input
        id="scan-q"
        type="search"
        inputMode="search"
        enterKeyHint="search"
        autoComplete="off"
        autoCapitalize="off"
        spellCheck={false}
        placeholder="Search by website, e.g. parking"
        value={q}
        onChange={(e) => setQ(e.target.value)}
      />
      <div className="chip-row" role="group" aria-label="Filter by result">
        {VERDICTS.map((v) => (
          <button
            key={v.value || "all"}
            type="button"
            className={`chip ${verdict === v.value ? "chip-on" : ""}`}
            aria-pressed={verdict === v.value}
            onClick={() => setVerdict(v.value)}
          >
            {v.label}
          </button>
        ))}
      </div>
      <div aria-live="polite">
        {DEMO_MODE && <p className="hint">Search needs the live server.</p>}
        {error && <p className="notice bad" role="alert">Search isn&apos;t available right now.</p>}
        {res && !error && <p className="hint">{res.found} {res.found === 1 ? "check" : "checks"} found</p>}
      </div>
      {res && res.hits.length > 0 && (
        <ul className="scan-hits">{res.hits.map((h) => <Hit key={h.id} h={h} />)}</ul>
      )}
    </section>
  );
}
