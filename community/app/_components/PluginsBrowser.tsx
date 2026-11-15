"use client";

import { ExternalLink, GitPullRequest, Search, Terminal } from "lucide-react";
import BaselineToggle from "./BaselineToggle";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  CODER_URL,
  SUBMIT_URL,
  checkedAt,
  errorText,
  listPlugins,
  searchPlugins,
  setPluginEnabled,
  type Plugin,
  type PluginIndex,
} from "@/lib/api";
import PageHeader from "./PageHeader";
import { EnableButton, ErrorBox, Installs, RunsOn, VerifiedBadge, VerifyHelp } from "./PluginBits";
import { useEnabled } from "./useEnabled";

type Filter = "all" | "verified" | "unverified";
const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "verified", label: "Verified" },
  { key: "unverified", label: "Unverified" },
];

export default function PluginsBrowser() {
  const [index, setIndex] = useState<PluginIndex | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [checked, setChecked] = useState("");

  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Plugin[] | null>(null);
  const [engine, setEngine] = useState("");
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [searchNonce, setSearchNonce] = useState(0);
  const [filter, setFilter] = useState<Filter>("all");

  const { enabled, pending, errors, reset, toggle } = useEnabled();

  const loadSeq = useRef(0);
  const load = useCallback(async () => {
    const seq = ++loadSeq.current;
    setLoading(true);
    setLoadError(null);
    try {
      const data = await listPlugins();
      if (seq !== loadSeq.current) return;
      setIndex(data);
      reset(data.enabled);
    } catch (e) {
      if (seq !== loadSeq.current) return;
      setLoadError(errorText(e));
    } finally {
      if (seq === loadSeq.current) {
        setLoading(false);
        setChecked(checkedAt());
      }
    }
  }, [reset]);

  useEffect(() => {
    load();
  }, [load]);

  // Debounced search through the API (Typesense, with a substring fallback on the server).
  useEffect(() => {
    const q = query.trim();
    if (!q) {
      setResults(null);
      setSearchError(null);
      setSearching(false);
      return;
    }
    const ctrl = new AbortController();
    setSearching(true);
    const t = setTimeout(async () => {
      try {
        const found = await searchPlugins(q, ctrl.signal);
        if (ctrl.signal.aborted) return;
        setResults(found.plugins);
        setEngine(found.engine);
        setSearchError(null);
      } catch (e) {
        if (ctrl.signal.aborted) return;
        setSearchError(errorText(e));
      } finally {
        if (!ctrl.signal.aborted) setSearching(false);
      }
    }, 250);
    return () => {
      clearTimeout(t);
      ctrl.abort();
    };
  }, [query, searchNonce]);

  const base = query.trim() ? results ?? [] : index?.plugins ?? [];
  const counts = {
    all: base.length,
    verified: base.filter((p) => p.verified).length,
    unverified: base.filter((p) => !p.verified).length,
  };
  const shown = base.filter((p) => filter === "all" || (filter === "verified" ? p.verified : !p.verified));
  const skipped = Object.entries(index?.skipped ?? {});

  return (
    <>
      <PageHeader
        title="Community plugins"
        subtitle="Open-source skills for your Chert agent. Unverified until an admin verifies them."
        checked={checked}
        onRefresh={load}
        refreshing={loading}
      >
        <div className="header-actions">
          <a className="btn btn-primary" href={SUBMIT_URL} target="_blank" rel="noopener noreferrer">
            <GitPullRequest size={15} strokeWidth={1.75} />
            Submit a plugin
          </a>
          <a className="btn btn-secondary" href={CODER_URL} target="_blank" rel="noopener noreferrer">
            <Terminal size={15} strokeWidth={1.75} />
            Open in Coder
            <ExternalLink size={13} className="muted-icon" />
          </a>
        </div>
      </PageHeader>

      <BaselineToggle />

      <div className="toolbar">
        <label className="search">
          <Search size={15} className="muted-icon" />
          <input
            type="search"
            placeholder="Search plugins, e.g. squats, parking, QR"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Search plugins"
            maxLength={100}
          />
        </label>
        <div className="pills" role="group" aria-label="Filter plugins">
          {FILTERS.map(({ key, label }) => (
            <button
              key={key}
              type="button"
              className={`pill-btn${filter === key ? " active" : ""}`}
              aria-pressed={filter === key}
              onClick={() => setFilter(key)}
            >
              {label}
              <span className="pill-count mono">{counts[key]}</span>
            </button>
          ))}
        </div>
      </div>
      <p className="sponsor-line muted small">
        {query.trim() && results && !searching
          ? `${results.length} result${results.length === 1 ? "" : "s"} · searched with ${
              engine === "typesense" ? "Typesense" : "a plain text match"
            }`
          : "Search by Typesense · install counts in Tiger Data · VM plugins run in a locked-down Vultr browser."}
      </p>

      {loadError ? <ErrorBox message={loadError} onRetry={load} /> : null}
      {searchError ? (
        <ErrorBox message={`Search failed. ${searchError}`} onRetry={() => setSearchNonce((n) => n + 1)} />
      ) : null}

      {loading && !index ? (
        <div className="plugin-grid" aria-busy="true">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="card plugin-card skeleton" />
          ))}
        </div>
      ) : index && !searchError ? (
        shown.length ? (
          <div className={`plugin-grid${searching ? " dim" : ""}`}>
            {shown.map((p) => (
              <article key={p.id} className="card plugin-card">
                <div className="plugin-top">
                  <Link href={`/plugins/${encodeURIComponent(p.id)}`} className="plugin-name">
                    {p.name}
                  </Link>
                  <VerifiedBadge verified={p.verified} />
                </div>
                <p className="plugin-summary">{p.summary}</p>
                <div className="plugin-meta">
                  <span className="meta-item">by {p.author}</span>
                  <RunsOn plugin={p} />
                  <Installs n={p.installs} />
                </div>
                <div className="plugin-actions">
                  <Link href={`/plugins/${encodeURIComponent(p.id)}`} className="link small">
                    Details
                  </Link>
                  <EnableButton
                    name={p.name}
                    verified={p.verified}
                    enabled={enabled.has(p.id)}
                    pending={pending.has(p.id)}
                    onToggle={() => toggle(p.id)}
                  />
                </div>
                <VerifyHelp verified={p.verified} enabled={enabled.has(p.id)} />
                {errors[p.id] ? (
                  <p className="inline-error small" role="alert">
                    {errors[p.id]}
                  </p>
                ) : null}
              </article>
            ))}
          </div>
        ) : (
          <div className="card empty">
            <div className="empty-title">{searching ? "Searching…" : "No plugins match"}</div>
            {!searching ? (
              <p className="muted">Try another search or filter, or submit the plugin you wish existed.</p>
            ) : null}
          </div>
        )
      ) : null}

      {skipped.length ? (
        <details className="card skipped">
          <summary>
            {skipped.length === 1
              ? "1 plugin folder was skipped because it didn't pass the check"
              : `${skipped.length} plugin folders were skipped because they didn't pass the check`}
          </summary>
          <ul>
            {skipped.map(([folder, why]) => (
              <li key={folder}>
                <span className="mono">{folder}</span>: {why}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </>
  );
}
