// "My apps": what plugins saved for the signed-in phone number (GET /me/apps, /me/apps/{id}).
// Every call needs the Bearer token; a 401 means the session is gone (the caller signs out).

import { request, str, strList } from "./api";
import { bearer } from "./auth";

const WHAT = "My apps API";

export type AppKind = "sessions" | "flashcards" | "notes";

export type MyApp = {
  pluginId: string;
  name: string;
  summary: string;
  records: number;
  /** ms since epoch, 0 if unknown */
  updatedAt: number;
  kind: AppKind;
};

export type AppRecord = { key: string; data: Record<string, unknown>; updatedAt: number };

export type Flashcard = {
  id: string;
  front: string;
  back: string;
  dueAt: number;
  intervalS: number;
  reps: number;
};

export type Flashcards = { due: number; total: number; cards: Flashcard[] };

export type AppDetail = {
  plugin: { id: string; name: string; summary: string };
  records: AppRecord[];
  flashcards: Flashcards | null;
};

const obj = (v: unknown): Record<string, unknown> =>
  v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : {};

const num = (v: unknown): number => (Number.isFinite(Number(v)) ? Number(v) : 0);

/** Unix seconds (or ms, or an ISO string) to ms since epoch; 0 if unusable. */
export function toMs(v: unknown): number {
  if (typeof v === "string" && v && !/^\d+(\.\d+)?$/.test(v)) {
    const t = Date.parse(v);
    return Number.isFinite(t) ? t : 0;
  }
  const n = num(v);
  if (n <= 0) return 0;
  return n > 1e12 ? n : n * 1000;
}

const KINDS: AppKind[] = ["sessions", "flashcards", "notes"];

export async function listMyApps(token: string): Promise<MyApp[]> {
  const d = await request<Record<string, unknown>>("/me/apps", { headers: bearer(token) }, WHAT);
  const apps = Array.isArray(d.apps) ? d.apps : [];
  return apps.map((raw) => {
    const r = obj(raw);
    const kind = str(r.kind) as AppKind;
    return {
      pluginId: str(r.plugin_id),
      name: str(r.name) || str(r.plugin_id),
      summary: str(r.summary),
      records: num(r.records),
      updatedAt: toMs(r.updated_at),
      kind: KINDS.includes(kind) ? kind : "notes",
    };
  });
}

export async function getMyApp(token: string, id: string): Promise<AppDetail> {
  const d = await request<Record<string, unknown>>(
    `/me/apps/${encodeURIComponent(id)}`,
    { headers: bearer(token) },
    WHAT,
  );
  const p = obj(d.plugin);
  const records = (Array.isArray(d.records) ? d.records : []).map((raw) => {
    const r = obj(raw);
    return { key: str(r.key), data: obj(r.data), updatedAt: toMs(r.updated_at) };
  });
  let flashcards: Flashcards | null = null;
  if (d.flashcards && typeof d.flashcards === "object") {
    const f = obj(d.flashcards);
    const cards = (Array.isArray(f.cards) ? f.cards : []).map((raw) => {
      const c = obj(raw);
      return {
        id: str(c.id),
        front: str(c.front),
        back: str(c.back),
        dueAt: toMs(c.due_at),
        intervalS: num(c.interval_s),
        reps: num(c.reps),
      };
    });
    flashcards = { due: num(f.due), total: num(f.total) || cards.length, cards };
  }
  return {
    plugin: { id: str(p.id) || id, name: str(p.name) || str(p.id) || id, summary: str(p.summary) },
    records,
    flashcards,
  };
}

// ---------- Shaping records for the detail page ----------

export type Session = { key: string; at: number; summary: string; cues: string[] };

export const isSessionKey = (key: string) => key.startsWith("session:");

/** Flashcard rows may also come back as records; they're shown in the cards table instead. */
export const isCardKey = (key: string) => /^(card|cards|flashcard|flashcards|deck)[:/]/.test(key);

export function toSession(r: AppRecord): Session {
  return {
    key: r.key,
    at: toMs(r.data.at) || r.updatedAt,
    summary: str(r.data.summary),
    cues: strList(r.data.cues)
      .map((c) => c.trim())
      .filter(Boolean),
  };
}

export type CueCount = { cue: string; n: number };

/** Most common cues across sessions, grouped case-insensitively, keeping the first spelling seen. */
export function topCues(sessions: Session[], limit = 8): CueCount[] {
  const counts = new Map<string, CueCount>();
  for (const s of sessions) {
    for (const cue of s.cues) {
      const k = cue.toLowerCase();
      const hit = counts.get(k);
      if (hit) hit.n += 1;
      else counts.set(k, { cue, n: 1 });
    }
  }
  return [...counts.values()].sort((a, b) => b.n - a.n || a.cue.localeCompare(b.cue)).slice(0, limit);
}

export function noteText(r: AppRecord): string {
  const note = str(r.data.note || r.data.text || r.data.summary);
  return note || r.key;
}

// ---------- Time ----------

export function formatDate(ms: number): string {
  if (!ms) return "Unknown date";
  return new Date(ms).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    year: new Date(ms).getFullYear() === new Date().getFullYear() ? undefined : "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function span(diffMs: number): string {
  const s = Math.round(Math.abs(diffMs) / 1000);
  if (s < 60) return `${s} s`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h} h`;
  const d = Math.round(h / 24);
  if (d < 60) return `${d} d`;
  const mo = Math.round(d / 30);
  return mo < 24 ? `${mo} mo` : `${Math.round(d / 365)} y`;
}

export function timeAgo(ms: number, now = Date.now()): string {
  if (!ms) return "never";
  const diff = now - ms;
  if (diff < 45_000) return "just now";
  return diff > 0 ? `${span(diff)} ago` : `in ${span(diff)}`;
}

export function nextReview(dueAt: number, now = Date.now()): string {
  if (!dueAt) return "Not scheduled";
  return dueAt <= now ? "Due now" : `in ${span(dueAt - now)}`;
}
