"use client";

import { ArrowRight, Dumbbell, Layers, LogOut, NotebookPen, PhoneCall, Puzzle } from "lucide-react";
import { callMeNow } from "@/lib/auth";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, checkedAt, errorText } from "@/lib/api";
import { formatDate, listMyApps, timeAgo, type AppKind, type MyApp } from "@/lib/apps";
import { useAuth } from "./AuthProvider";
import PageHeader from "./PageHeader";
import SignInCard from "./PhoneSignIn";
import { ErrorBox } from "./PluginBits";

export const KIND_LABEL: Record<AppKind, string> = {
  sessions: "Sessions",
  flashcards: "Flashcards",
  notes: "Notes",
};

const KIND_ICON = { sessions: Dumbbell, flashcards: Layers, notes: NotebookPen } as const;

export function KindBadge({ kind }: { kind: AppKind }) {
  const Icon = KIND_ICON[kind];
  return (
    <span className="badge badge-kind">
      <Icon size={13} strokeWidth={2} />
      {KIND_LABEL[kind]}
    </span>
  );
}

export function SignedInAs() {
  const { phoneMasked, signOut, token } = useAuth();
  const [leaving, setLeaving] = useState(false);
  const [calling, setCalling] = useState<"idle" | "calling" | "sent" | "error">("idle");
  const [callError, setCallError] = useState("");
  async function callMe() {
    const t = token();
    if (!t || calling === "calling") return;
    setCalling("calling");
    setCallError("");
    try {
      await callMeNow(t);
      setCalling("sent");
    } catch (e) {
      setCalling("error");
      setCallError(e instanceof Error ? e.message : "Couldn't place the call.");
    }
  }
  return (
    <div className="signed-in-row">
      <span className="small">
        Signed in as <span className="mono">{phoneMasked}</span>
      </span>
      <button type="button" className="btn btn-primary btn-small" onClick={callMe} disabled={calling === "calling"}>
        <PhoneCall size={13} strokeWidth={1.75} />
        {calling === "calling" ? "Calling…" : calling === "sent" ? "Ringing your phone" : "Call me now"}
      </button>
      {calling === "error" ? <span className="small error-text">{callError}</span> : null}
      <button
        type="button"
        className="btn btn-secondary btn-small"
        disabled={leaving}
        onClick={async () => {
          setLeaving(true);
          await signOut();
        }}
      >
        <LogOut size={13} strokeWidth={1.75} />
        {leaving ? "Signing out…" : "Sign out"}
      </button>
    </div>
  );
}

export function HowToStart() {
  return (
    <ul className="how-to small">
      <li>
        <Dumbbell size={14} strokeWidth={1.75} />
        <span>
          Call the Chert line and say <span className="say">“coach my squats”</span>. Each set is saved as a session.
        </span>
      </li>
      <li>
        <Layers size={14} strokeWidth={1.75} />
        <span>
          Say <span className="say">“add a card: …”</span> then <span className="say">“quiz me”</span> to build and
          review flashcards.
        </span>
      </li>
    </ul>
  );
}

function AppsList() {
  const { token, expired } = useAuth();
  const [apps, setApps] = useState<MyApp[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [checked, setChecked] = useState("");
  const seq = useRef(0);

  const load = useCallback(async () => {
    const mine = ++seq.current;
    const t = token();
    if (!t) return expired();
    setLoading(true);
    setError(null);
    try {
      const list = await listMyApps(t);
      if (mine !== seq.current) return;
      setApps(list.sort((a, b) => b.updatedAt - a.updatedAt));
    } catch (e) {
      if (mine !== seq.current) return;
      if (e instanceof ApiError && e.status === 401) return expired();
      setError(errorText(e));
    } finally {
      if (mine === seq.current) {
        setLoading(false);
        setChecked(checkedAt());
      }
    }
  }, [token, expired]);

  useEffect(() => {
    load();
    return () => {
      seq.current++;
    };
  }, [load]);

  return (
    <>
      <PageHeader
        title="My apps"
        subtitle="What your plugins saved for you on calls: squat sessions, flashcards and notes."
        checked={checked}
        onRefresh={load}
        refreshing={loading}
      >
        <SignedInAs />
      </PageHeader>

      {error ? <ErrorBox message={error} onRetry={load} /> : null}

      {loading && !apps ? (
        <div className="plugin-grid" aria-busy="true">
          {[0, 1].map((i) => (
            <div key={i} className="card plugin-card skeleton" />
          ))}
        </div>
      ) : apps && apps.length ? (
        <div className={`plugin-grid${loading ? " dim" : ""}`}>
          {apps.map((a) => {
            const href = `/apps/${encodeURIComponent(a.pluginId)}`;
            return (
              <article key={a.pluginId} className="card plugin-card app-card">
                <div className="plugin-top">
                  <Link href={href} className="plugin-name">
                    {a.name}
                  </Link>
                  <KindBadge kind={a.kind} />
                </div>
                {a.summary ? <p className="plugin-summary">{a.summary}</p> : <div className="plugin-summary" />}
                <div className="plugin-meta">
                  <span className="meta-item">
                    <span className="mono">{a.records.toLocaleString("en-US")}</span>
                    {a.records === 1 ? " record" : " records"}
                  </span>
                  <span className="meta-item" title={formatDate(a.updatedAt)}>
                    Updated {timeAgo(a.updatedAt)}
                  </span>
                </div>
                <div className="plugin-actions">
                  <span className="muted small mono">{a.pluginId}</span>
                  <Link href={href} className="btn btn-secondary" aria-label={`Open ${a.name}`}>
                    Open
                    <ArrowRight size={14} strokeWidth={1.75} />
                  </Link>
                </div>
              </article>
            );
          })}
        </div>
      ) : apps ? (
        <div className="card empty">
          <div className="empty-title">No app data yet</div>
          <p className="muted">Plugins save things here when you use them on a call.</p>
          <HowToStart />
          <Link href="/plugins" className="btn btn-secondary">
            <Puzzle size={15} strokeWidth={1.75} />
            Browse Community plugins
          </Link>
        </div>
      ) : null}
    </>
  );
}

export default function MyApps() {
  const { status, error, recheck } = useAuth();

  if (status === "signed_in") return <AppsList />;

  return (
    <>
      <PageHeader
        title="My apps"
        subtitle="What your plugins saved for you on calls: squat sessions, flashcards and notes."
      />
      {status === "checking" ? (
        <div className="card signin-card skeleton signin-skeleton" aria-busy="true" />
      ) : status === "error" ? (
        <ErrorBox message={error || "Couldn't check your sign-in."} onRetry={recheck} />
      ) : (
        <SignInCard />
      )}
    </>
  );
}
