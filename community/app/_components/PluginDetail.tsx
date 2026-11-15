"use client";

import { ArrowLeft, Lock, QrCode } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, MONEY_TOOLS, errorText, getPlugin, listPlugins, type Plugin } from "@/lib/api";
import { EnableButton, ErrorBox, Installs, RunsOn, VerifiedBadge, VerifyHelp } from "./PluginBits";
import { useEnabled } from "./useEnabled";

const TOOL_LABELS: Record<string, string> = {
  camera: "Camera",
  speak: "Speak",
  screen: "Screen",
  memory: "Memory",
  safe_browser: "Safe browser",
  scam_check: "Scam check",
  plugin_search: "Plugin search",
  solana_pay: "Solana pay",
  parking: "Parking",
  flashcards: "Flashcards",
  research: "Research",
  computer: "Your computer",
  whiteboard: "Whiteboard",
};

export default function PluginDetail({ id }: { id: string }) {
  const [plugin, setPlugin] = useState<Plugin | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [loading, setLoading] = useState(true);
  const { enabled, pending, errors, reset, toggle } = useEnabled();

  const seq = useRef(0);
  const load = useCallback(async () => {
    const mine = ++seq.current;
    setLoading(true);
    setError(null);
    setNotFound(false);
    try {
      const p = await getPlugin(id);
      // The detail reply carries "enabled"; fall back to the list for an older API.
      const ids =
        typeof p.enabled === "boolean" ? (p.enabled ? [p.id] : []) : (await listPlugins()).enabled;
      if (mine !== seq.current) return;
      setPlugin(p);
      reset(ids);
    } catch (e) {
      if (mine !== seq.current) return;
      if (e instanceof ApiError && e.status === 404) setNotFound(true);
      else setError(errorText(e));
    } finally {
      if (mine === seq.current) setLoading(false);
    }
  }, [id, reset]);

  useEffect(() => {
    load();
  }, [load]);

  const back = (
    <Link href="/plugins" className="back-link">
      <ArrowLeft size={14} />
      Community plugins
    </Link>
  );

  if (notFound) {
    return (
      <>
        {back}
        <div className="card empty">
          <div className="empty-title">No plugin called “{id}”</div>
          <p className="muted">It may have been renamed, or its folder failed the plugin check.</p>
        </div>
      </>
    );
  }

  if (error) {
    return (
      <>
        {back}
        <ErrorBox message={error} onRetry={load} />
      </>
    );
  }

  if (loading || !plugin) {
    return (
      <>
        {back}
        <div className="card skeleton tall" aria-busy="true" />
      </>
    );
  }

  const p = plugin;
  const effective = new Set(p.effective_tools);
  const yamlFields: [string, string][] = [
    ["id", p.id],
    ["name", p.name],
    ["author", p.author],
    ["version", String(p.version)],
    ["kind", p.kind],
    ["runs_on", p.runs_on],
    ["triggers.phrases", p.phrases.length ? p.phrases.map((s) => JSON.stringify(s)).join(", ") : "none"],
    ["triggers.qr", String(p.qr)],
    ["tools", p.tools.join(", ")],
    ["sha256", p.sha256],
  ];

  return (
    <>
      {back}
      <div className="page-header">
        <div className="page-heading">
          <div className="detail-title-row">
            <h1 className="page-title">{p.name}</h1>
            <VerifiedBadge verified={p.verified} />
          </div>
          <p className="page-subtitle">{p.summary}</p>
          <div className="plugin-meta">
            <span className="meta-item">by {p.author}</span>
            <span className="meta-item">
              version <span className="mono">{p.version}</span>
            </span>
            <RunsOn plugin={p} />
            <Installs n={p.installs} />
          </div>
        </div>
        <div className="detail-enable">
          <EnableButton
            name={p.name}
            verified={p.verified}
            enabled={enabled.has(p.id)}
            pending={pending.has(p.id)}
            onToggle={() => toggle(p.id)}
          />
          <VerifyHelp verified={p.verified} enabled={enabled.has(p.id)} />
          {errors[p.id] ? (
            <p className="inline-error small" role="alert">
              {errors[p.id]}
            </p>
          ) : null}
        </div>
      </div>

      {!p.verified ? (
        <div className="notice small">
          Unverified: this plugin isn&apos;t in <span className="mono">plugins/verified.json</span>, or it changed after
          an admin approved it. It can&apos;t be turned on for the shared demo agent, and it never gets payment or
          parking tools, until an admin verifies it.
        </div>
      ) : null}

      <div className="detail-grid">
        <section className="card">
          <h2 className="card-title">Permissions</h2>
          <p className="section-hint muted small">Read aloud to the caller before the first run.</p>
          <blockquote className="quote">“{p.permissions}”</blockquote>
        </section>

        <section className="card">
          <h2 className="card-title">Tools</h2>
          <p className="section-hint muted small">Wired by name from Toolstone&apos;s code. Plugin text is never run.</p>
          <div className="chips">
            {p.tools.map((t) => {
              const blocked = !effective.has(t);
              return (
                <span key={t} className={`chip${blocked ? " chip-blocked" : ""}`}>
                  {blocked ? <Lock size={12} strokeWidth={2} /> : null}
                  <span className="chip-name">{TOOL_LABELS[t] ?? t}</span>
                  {blocked ? <span className="chip-note">needs verification</span> : null}
                </span>
              );
            })}
          </div>
          {p.tools.some((t) => MONEY_TOOLS.has(t)) && p.verified ? (
            <p className="muted small chips-note">Payment and parking tools are allowed because this plugin is verified.</p>
          ) : null}
        </section>

        <section className="card">
          <h2 className="card-title">Starts when the caller says</h2>
          <div className="chips">
            {p.phrases.map((ph) => (
              <span key={ph} className="chip chip-phrase">
                “{ph}”
              </span>
            ))}
            {p.qr ? (
              <span className="chip">
                <QrCode size={12} strokeWidth={2} />
                or holds up a QR code
              </span>
            ) : null}
            {!p.phrases.length && !p.qr ? <span className="muted small">Only by name.</span> : null}
          </div>
        </section>

        <section className="card">
          <h2 className="card-title">Instructions for the agent</h2>
          <p className="text-block">{p.instructions}</p>
        </section>
      </div>

      <section className="card">
        <h2 className="card-title">README</h2>
        <pre className="readme">{p.readme || "No README."}</pre>
      </section>

      <section className="card">
        <h2 className="card-title">plugin.yaml</h2>
        <dl className="fields">
          {yamlFields.map(([k, v]) => (
            <div key={k} className="field">
              <dt className="mono">{k}</dt>
              <dd className={k === "sha256" ? "mono break" : undefined}>{v}</dd>
            </div>
          ))}
        </dl>
      </section>
    </>
  );
}
