import { mockHourly, mockPins, mockScan, mockSummary } from "./mockData";
import type { HourlyBucket, PayResponse, Pin, ScanResult, StatsSummary } from "./types";

/** Backend base URL. Unset = demo mode on the built-in mock data. */
export const API = (process.env.NEXT_PUBLIC_API_URL || "").replace(/\/+$/, "");
export const DEMO_MODE = !API;

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));

async function request<T>(path: string, init?: RequestInit, timeoutMs = 60000): Promise<T> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(`${API}${path}`, {
      ...init,
      signal: ctrl.signal,
      headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    });
    if (!res.ok) throw new Error(`Server answered ${res.status}`);
    return (await res.json()) as T;
  } finally {
    clearTimeout(timer);
  }
}

export async function scanUrl(url: string, location: [number, number] | null): Promise<ScanResult> {
  if (DEMO_MODE) {
    await wait(1800);
    return mockScan(url, location);
  }
  const body: { url: string; lat?: number; lng?: number } = { url };
  if (location) {
    body.lat = location[0];
    body.lng = location[1];
  }
  return request<ScanResult>("/scan", { method: "POST", body: JSON.stringify(body) }, 90000);
}

export interface LiveScanHandlers {
  /** A new screen from the sandbox browser, as a ready-to-use `data:image/jpeg;base64,...` URL. */
  onFrame?: (dataUrl: string) => void;
  /** The sandbox browser moved to a new address. */
  onNav?: (url: string) => void;
  /** The live stream failed before a result, so we are falling back to the plain /scan request. */
  onFallback?: () => void;
}

/**
 * Same scan as scanUrl, but streams the sandbox browser while it works (POST /scan/stream, NDJSON).
 * Any failure before the result line (non-200, network, timeout, no result) falls back to scanUrl.
 * Aborting `signal` stops everything and rejects without falling back.
 */
export async function scanUrlLive(
  url: string,
  location: [number, number] | null,
  handlers: LiveScanHandlers = {},
  signal?: AbortSignal,
): Promise<ScanResult> {
  if (DEMO_MODE) return scanUrl(url, location);
  if (signal?.aborted) throw new DOMException("Aborted", "AbortError");

  const body: { url: string; lat?: number; lng?: number } = { url };
  if (location) {
    body.lat = location[0];
    body.lng = location[1];
  }

  const ctrl = new AbortController();
  const stop = () => ctrl.abort();
  signal?.addEventListener("abort", stop, { once: true });
  // Give up on the stream if it goes quiet for 30 s or runs past 100 s in total.
  let idle: ReturnType<typeof setTimeout> | undefined;
  const bumpIdle = () => {
    clearTimeout(idle);
    idle = setTimeout(stop, 30000);
  };
  const overall = setTimeout(stop, 100000);
  const safe = (fn: () => void) => {
    try {
      fn();
    } catch {
      /* a UI callback failing must not kill the scan */
    }
  };

  try {
    bumpIdle();
    const res = await fetch(`${API}/scan/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/x-ndjson" },
      body: JSON.stringify(body),
      signal: ctrl.signal,
    });
    if (!res.ok || !res.body) throw new Error(`Server answered ${res.status}`);

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    let result: ScanResult | null = null;

    const handleLine = (line: string): ScanResult | null => {
      const s = line.trim();
      if (!s) return null;
      let msg: { type?: string; jpeg?: string; url?: string; data?: ScanResult };
      try {
        msg = JSON.parse(s);
      } catch {
        return null; // one garbled line (e.g. a frame) is skipped; a missing result still falls back below
      }
      if (msg.type === "frame" && typeof msg.jpeg === "string" && msg.jpeg) {
        const jpeg = msg.jpeg;
        safe(() => handlers.onFrame?.(`data:image/jpeg;base64,${jpeg}`));
      } else if (msg.type === "nav" && typeof msg.url === "string") {
        const nav = msg.url;
        safe(() => handlers.onNav?.(nav));
      } else if (msg.type === "result" && msg.data && typeof msg.data === "object" && typeof msg.data.verdict === "string") {
        return msg.data;
      }
      return null;
    };

    while (!result) {
      const { value, done } = await reader.read();
      if (done) break;
      bumpIdle();
      buf += decoder.decode(value, { stream: true });
      let nl: number;
      while (!result && (nl = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, nl);
        buf = buf.slice(nl + 1);
        result = handleLine(line);
      }
    }
    if (!result) {
      buf += decoder.decode();
      result = handleLine(buf); // a last line without a trailing newline
    } else {
      reader.cancel().catch(() => {});
    }
    if (!result) throw new Error("Stream ended without a result");
    return result;
  } catch (err) {
    if (signal?.aborted) throw err;
    safe(() => handlers.onFallback?.());
    return scanUrl(url, location);
  } finally {
    clearTimeout(idle);
    clearTimeout(overall);
    signal?.removeEventListener("abort", stop);
  }
}

export interface CallMeResponse {
  call_id?: string;
  status?: string;
}

/** Ask ScanSafe to FaceTime this phone and show the page for `url` live (Chert outbound call). */
export async function callMe(url: string, phone: string, location: [number, number] | null): Promise<CallMeResponse> {
  if (DEMO_MODE) {
    await wait(1200);
    return { status: "demo" };
  }
  const body: { url: string; phone: string; lat?: number; lng?: number } = { url, phone };
  if (location) {
    body.lat = location[0];
    body.lng = location[1];
  }
  return request<CallMeResponse>("/call-me", { method: "POST", body: JSON.stringify(body) }, 45000);
}

interface BackendSummary {
  by_verdict?: Record<string, { total: number; last_24h: number } | undefined>;
  top_scam_types_24h?: { scam_type: string; total: number }[];
  avg_scan_ms_24h?: number | null;
}

interface BackendHourlyRow {
  hour: string;
  scam_type: string;
  verdict: string;
  total: number;
}

/** Only call after the user tapped confirm in the pay dialog: sends approved: true. */
export async function pay(result: ScanResult): Promise<PayResponse> {
  if (DEMO_MODE) {
    await wait(1200);
    return { tx_signature: "demo-mode-no-money-moved" };
  }
  const res = await request<{ signature: string; explorer_url?: string }>("/pay", {
    method: "POST",
    body: JSON.stringify({ scan_id: result.scan_id, payment: result.payment, approved: true }),
  });
  return { tx_signature: res.signature, explorer_url: res.explorer_url };
}

export async function report(result: ScanResult): Promise<void> {
  if (DEMO_MODE) {
    await wait(600);
    return;
  }
  await request<unknown>("/report", { method: "POST", body: JSON.stringify(result) });
}

/** Accept a bare array, {pins:[...]}, {results:[...]} or a raw Typesense {hits:[{document}]}. */
function toPins(data: unknown): Pin[] {
  const d = data as Record<string, unknown>;
  let list: unknown[] = [];
  if (Array.isArray(data)) list = data;
  else if (Array.isArray(d?.pins)) list = d.pins as unknown[];
  else if (Array.isArray(d?.results)) list = d.results as unknown[];
  else if (Array.isArray(d?.hits)) list = (d.hits as { document?: unknown }[]).map((h) => h.document ?? h);
  return list
    .map((p) => p as Pin)
    .filter((p) => Array.isArray(p?.location) && p.location.length === 2 && isFinite(p.location[0]) && isFinite(p.location[1]));
}

export async function getPins(lat: number, lng: number, radiusKm = 5): Promise<{ pins: Pin[]; demo: boolean }> {
  if (DEMO_MODE) return { pins: mockPins(), demo: true };
  try {
    const data = await request<unknown>(`/pins?lat=${lat}&lng=${lng}&radius_km=${radiusKm}`, undefined, 15000);
    return { pins: toPins(data), demo: false };
  } catch {
    return { pins: mockPins(), demo: true };
  }
}

export async function searchPins(q: string): Promise<{ pins: Pin[]; demo: boolean }> {
  const local = () => {
    const s = q.toLowerCase();
    return mockPins().filter((p) =>
      [p.url, p.domain, p.explanation, p.scam_type].some((f) => (f || "").toLowerCase().includes(s)),
    );
  };
  if (DEMO_MODE) return { pins: local(), demo: true };
  try {
    const data = await request<unknown>(`/search?q=${encodeURIComponent(q)}`, undefined, 15000);
    return { pins: toPins(data), demo: false };
  } catch {
    return { pins: local(), demo: true };
  }
}

export async function getStats(hours = 24): Promise<{ summary: StatsSummary; hourly: HourlyBucket[]; demo: boolean }> {
  if (DEMO_MODE) return { summary: mockSummary(), hourly: mockHourly(hours), demo: true };
  try {
    const [raw, hourlyRaw] = await Promise.all([
      request<BackendSummary>("/stats/summary", undefined, 15000),
      request<{ rows?: BackendHourlyRow[] }>(`/stats/hourly?hours=${hours}`, undefined, 15000),
    ]);
    // Backend summary (data/tiger_store.py) -> the shape the dashboard draws.
    const v = raw.by_verdict ?? {};
    const summary: StatsSummary = {
      total_scans: Object.values(v).reduce((n, x) => n + (x?.total ?? 0), 0),
      safe: v.safe?.total ?? 0,
      suspicious: v.suspicious?.total ?? 0,
      malicious: v.malicious?.total ?? 0,
      avg_scan_ms: raw.avg_scan_ms_24h ?? null,
      top_scam_types: (raw.top_scam_types_24h ?? []).map((t) => ({ scam_type: t.scam_type, count: t.total })),
    };
    // Backend hourly rows are split by scam_type and verdict: add them up per hour.
    const byHour = new Map<string, HourlyBucket>();
    for (const row of hourlyRaw.rows ?? []) {
      const b = byHour.get(row.hour) ?? { hour: row.hour, total: 0, malicious: 0 };
      b.total += row.total;
      if (row.verdict === "malicious") b.malicious += row.total;
      byHour.set(row.hour, b);
    }
    return { summary, hourly: [...byHour.values()], demo: false };
  } catch {
    return { summary: mockSummary(), hourly: mockHourly(hours), demo: true };
  }
}

/** Screenshots may be data: URLs, full URLs, or plain file names served by the backend. */
export function screenshotSrc(s: string): string {
  if (/^(data:|https?:|blob:)/i.test(s)) return s;
  const name = s.replace(/^\/+/, "");
  if (DEMO_MODE) return `/${name}`;
  return `${API}/screenshots/${name}`;
}
