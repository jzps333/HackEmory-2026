"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, errorText } from "@/lib/api";
import {
  formatDate,
  getMyApp,
  isCardKey,
  isSessionKey,
  nextReview,
  noteText,
  timeAgo,
  toSession,
  topCues,
  type AppDetail,
  type AppRecord,
  type Flashcards,
  type Session,
} from "@/lib/apps";
import { useAuth } from "./AuthProvider";
import { HowToStart, SignedInAs } from "./MyApps";
import SignInCard from "./PhoneSignIn";
import { ErrorBox } from "./PluginBits";

const plural = (n: number, one: string, many = `${one}s`) => `${n.toLocaleString("en-US")} ${n === 1 ? one : many}`;

function CueChart({ sessions }: { sessions: Session[] }) {
  const cues = topCues(sessions);
  const max = cues.length ? cues[0].n : 0;
  return (
    <section className="card">
      <div className="card-head">
        <h2 className="card-title">Most common cues</h2>
        <span className="muted small">across {plural(sessions.length, "session")}</span>
      </div>
      {cues.length ? (
        <ol className="cue-chart">
          {cues.map((c) => (
            <li key={c.cue} className="cue-row">
              <span className="cue-label">{c.cue}</span>
              <span className="cue-track" aria-hidden="true">
                <span className="cue-bar" style={{ width: `${(c.n / max) * 100}%` }} />
              </span>
              <span className="cue-count mono">
                {c.n}
                <span className="sr-only">{c.n === 1 ? " time" : " times"}</span>
              </span>
            </li>
          ))}
        </ol>
      ) : (
        <p className="muted small">No cues saved yet.</p>
      )}
      <p className="muted small chart-note">Bars are to scale: the number of times the coach gave each cue.</p>
    </section>
  );
}

function SessionList({ sessions }: { sessions: Session[] }) {
  return (
    <section className="card">
      <div className="card-head">
        <h2 className="card-title">Sessions</h2>
        <span className="muted small">newest first</span>
      </div>
      <ul className="record-list">
        {sessions.map((s) => (
          <li key={s.key} className="record-row session-row">
            <span className="record-date mono" title={formatDate(s.at)}>
              {formatDate(s.at)}
            </span>
            <span className="record-main">
              <span className="record-text">{s.summary || "Squat session"}</span>
              {s.cues.length ? <span className="record-sub muted small">{s.cues.join(" · ")}</span> : null}
            </span>
            <span className="pill pill-neutral">{plural(s.cues.length, "cue")}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function FlashcardsView({ f }: { f: Flashcards }) {
  const now = Date.now();
  const cards = [...f.cards].sort((a, b) => (a.dueAt || Infinity) - (b.dueAt || Infinity));
  return (
    <>
      <section className="mini-stats" aria-label="Flashcards">
        <div className="mini-stat">
          <div className="stat-label">Due now</div>
          <div className={`stat-value mono${f.due ? " due" : ""}`}>{f.due}</div>
        </div>
        <div className="mini-stat">
          <div className="stat-label">Total cards</div>
          <div className="stat-value mono">{f.total}</div>
        </div>
        <div className="mini-stat">
          <div className="stat-label">Reviews</div>
          <div className="stat-value mono">{cards.reduce((n, c) => n + c.reps, 0)}</div>
        </div>
      </section>
      <section className="card">
        <div className="card-head">
          <h2 className="card-title">Cards</h2>
          <span className="muted small">soonest review first</span>
        </div>
        {cards.length ? (
          <table className="cards-table">
            <thead>
              <tr>
                <th scope="col">Front</th>
                <th scope="col">Back</th>
                <th scope="col">Next review</th>
                <th scope="col" className="num">
                  Reps
                </th>
              </tr>
            </thead>
            <tbody>
              {cards.map((c, i) => {
                const when = nextReview(c.dueAt, now);
                return (
                  <tr key={c.id || i}>
                    <td className="card-front">{c.front}</td>
                    <td className="card-back muted">{c.back}</td>
                    <td className={`card-due small${when === "Due now" ? " due" : ""}`} title={formatDate(c.dueAt)}>
                      {when}
                    </td>
                    <td className="num mono small">
                      {c.reps}
                      <span className="reps-unit">{c.reps === 1 ? " rep" : " reps"}</span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : (
          <div className="empty compact">
            <div className="empty-title">No cards yet</div>
            <p className="muted">
              On a call, say <span className="say">“add a card: …”</span> then <span className="say">“quiz me”</span>.
            </p>
          </div>
        )}
      </section>
    </>
  );
}

function NotesList({ notes }: { notes: AppRecord[] }) {
  return (
    <section className="card">
      <div className="card-head">
        <h2 className="card-title">Notes</h2>
        <span className="muted small">newest first</span>
      </div>
      <ul className="record-list">
        {notes.map((r, i) => (
          <li key={r.key || i} className="record-row note-row">
            <span className="record-date mono">{formatDate(r.updatedAt)}</span>
            <span className="record-text note-text">{noteText(r)}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function EmptyApp({ app }: { app: AppDetail }) {
  const id = `${app.plugin.id} ${app.plugin.name}`.toLowerCase();
  const squat = id.includes("squat");
  const cards = app.flashcards !== null || /study|flash|card|quiz/.test(id);
  return (
    <div className="card empty">
      <div className="empty-title">Nothing saved yet</div>
      {squat && !cards ? (
        <p className="muted">
          Call the Chert line and say <span className="say">“coach my squats”</span>. Each set shows up here.
        </p>
      ) : cards && !squat ? (
        <p className="muted">
          Call the Chert line, say <span className="say">“add a card: …”</span> then{" "}
          <span className="say">“quiz me”</span>.
        </p>
      ) : (
        <HowToStart />
      )}
    </div>
  );
}

function Detail({ id }: { id: string }) {
  const { token, expired } = useAuth();
  const [app, setApp] = useState<AppDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [missing, setMissing] = useState(false);
  const [loading, setLoading] = useState(true);
  const seq = useRef(0);

  const load = useCallback(async () => {
    const mine = ++seq.current;
    const t = token();
    if (!t) return expired();
    setLoading(true);
    setError(null);
    setMissing(false);
    try {
      const d = await getMyApp(t, id);
      if (mine !== seq.current) return;
      setApp(d);
    } catch (e) {
      if (mine !== seq.current) return;
      if (e instanceof ApiError && e.status === 401) return expired();
      if (e instanceof ApiError && e.status === 404) setMissing(true);
      else setError(errorText(e));
    } finally {
      if (mine === seq.current) setLoading(false);
    }
  }, [id, token, expired]);

  useEffect(() => {
    load();
    return () => {
      seq.current++;
    };
  }, [load]);

  if (missing) {
    return (
      <div className="card empty">
        <div className="empty-title">No data for “{id}”</div>
        <p className="muted">This plugin hasn&apos;t saved anything for your number yet.</p>
        <HowToStart />
      </div>
    );
  }
  if (error) return <ErrorBox message={error} onRetry={load} />;
  if (loading || !app) return <div className="card skeleton tall" aria-busy="true" />;

  const sessions = app.records.filter((r) => isSessionKey(r.key)).map(toSession);
  const notes = app.records.filter((r) => !isSessionKey(r.key) && !(app.flashcards && isCardKey(r.key)));
  const latest = Math.max(0, ...app.records.map((r) => r.updatedAt));
  const hasCards = app.flashcards !== null && (app.flashcards.total > 0 || app.flashcards.cards.length > 0);
  const nothing = !sessions.length && !notes.length && !hasCards;

  return (
    <>
      <div className="page-header">
        <div className="page-heading">
          <h1 className="page-title">{app.plugin.name}</h1>
          {app.plugin.summary ? <p className="page-subtitle">{app.plugin.summary}</p> : null}
          <div className="plugin-meta">
            <span className="meta-item">{plural(app.records.length, "record")}</span>
            {latest ? (
              <span className="meta-item" title={formatDate(latest)}>
                Updated {timeAgo(latest)}
              </span>
            ) : null}
            {app.records.length >= 100 ? <span className="meta-item">Showing the latest 100</span> : null}
          </div>
          <SignedInAs />
        </div>
      </div>

      <div className="app-sections">
        {nothing && !app.flashcards ? <EmptyApp app={app} /> : null}

        {sessions.length ? (
          <div className="apps-grid">
            <CueChart sessions={sessions} />
            <SessionList sessions={sessions} />
          </div>
        ) : null}

        {app.flashcards ? <FlashcardsView f={app.flashcards} /> : null}

        {notes.length ? <NotesList notes={notes} /> : null}
      </div>
    </>
  );
}

export default function MyAppDetail({ id }: { id: string }) {
  const { status, error, recheck } = useAuth();
  return (
    <>
      <Link href="/apps" className="back-link">
        <ArrowLeft size={14} />
        My apps
      </Link>
      {status === "signed_in" ? (
        <Detail id={id} />
      ) : status === "checking" ? (
        <div className="card skeleton tall" aria-busy="true" />
      ) : status === "error" ? (
        <ErrorBox message={error || "Couldn't check your sign-in."} onRetry={recheck} />
      ) : (
        <SignInCard />
      )}
    </>
  );
}
