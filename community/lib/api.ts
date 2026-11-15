// Client for the ScanSafe plugins API (api/routes_plugins.py). No cookies are sent; only the "My apps"
// calls (lib/auth.ts, lib/apps.ts) add an Authorization header.
// Everything that comes back is rendered as React text, never as HTML.

export const API_URL = (process.env.NEXT_PUBLIC_API_URL || "https://api.scansafe.nyc").replace(/\/+$/, "");

export const SUBMIT_URL = "https://github.com/jzps333/HackEmory-2026/new/main/plugins";

function httpUrl(value: string | undefined, fallback: string): string {
  try {
    const u = new URL(value || fallback);
    return u.protocol === "https:" || u.protocol === "http:" ? u.toString() : fallback;
  } catch {
    return fallback;
  }
}

export const CODER_URL = httpUrl(process.env.NEXT_PUBLIC_CODER_URL, "https://coder.com");

export const MONEY_TOOLS = new Set(["solana_pay", "parking"]);

export type Plugin = {
  id: string;
  name: string;
  summary: string;
  author: string;
  version: number;
  kind: string;
  runs_on: "server" | "vm" | string;
  phrases: string[];
  qr: boolean;
  tools: string[];
  effective_tools: string[];
  permissions: string;
  instructions: string;
  readme: string;
  sha256: string;
  verified: boolean;
  installs: number;
  /** Present on list/search cards and the detail reply. */
  enabled?: boolean;
};

export type PluginIndex = {
  plugins: Plugin[];
  skipped: Record<string, string>;
  enabled: string[];
};

export class ApiError extends Error {
  status: number;
  /** The API's error code, e.g. "needs_verification", "unknown_plugin", "origin_not_allowed". */
  code: string;
  constructor(status: number, message: string, code = "") {
    super(message);
    this.status = status;
    this.code = code;
  }
}

export const str = (v: unknown): string => (typeof v === "string" ? v : v == null ? "" : String(v));
export const strList = (v: unknown): string[] => (Array.isArray(v) ? v.map(str) : []);

/** Coerce whatever the API sent into the shape the UI expects. */
export function normalizePlugin(raw: unknown): Plugin {
  const r = (raw && typeof raw === "object" ? raw : {}) as Record<string, unknown>;
  const tools = strList(r.tools);
  const verified = r.verified === true;
  return {
    id: str(r.id),
    name: str(r.name) || str(r.id),
    summary: str(r.summary),
    author: str(r.author),
    version: Number(r.version) || 1,
    kind: str(r.kind),
    runs_on: str(r.runs_on),
    phrases: strList(r.phrases),
    qr: r.qr === true,
    tools,
    effective_tools: Array.isArray(r.effective_tools)
      ? strList(r.effective_tools)
      : tools.filter((t) => verified || !MONEY_TOOLS.has(t)),
    permissions: str(r.permissions),
    instructions: str(r.instructions),
    readme: str(r.readme),
    sha256: str(r.sha256),
    verified,
    installs: Number.isFinite(Number(r.installs)) ? Number(r.installs) : 0,
    enabled: typeof r.enabled === "boolean" ? r.enabled : undefined,
  };
}

/** `what` names the API in error messages, e.g. "plugins API" or "sign-in API". */
export async function request<T>(
  path: string,
  init?: Omit<RequestInit, "headers"> & { headers?: Record<string, string> },
  what = "plugins API",
): Promise<T> {
  let res: Response;
  try {
    res = await fetch(API_URL + path, {
      ...init,
      credentials: "omit",
      cache: "no-store",
      headers: { Accept: "application/json", ...init?.headers },
    });
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw e;
    throw new ApiError(
      0,
      `Couldn't reach the ${what} at ${API_URL}. It may be down, or this site isn't on its CORS list.`,
      "network",
    );
  }
  if (!res.ok) {
    // The API's errors look like {"ok": false, "error": code, "message": text}.
    let code = "";
    let message = "";
    try {
      const body = (await res.json()) as Record<string, unknown>;
      code = str(body.error);
      message = str(body.message);
    } catch {
      /* not JSON */
    }
    if (!message) {
      message =
        res.status === 404
          ? "That plugin doesn't exist (404)."
          : `The ${what} answered ${res.status}${res.statusText ? ` ${res.statusText}` : ""}.`;
    }
    throw new ApiError(res.status, message.slice(0, 300), code);
  }
  try {
    return (await res.json()) as T;
  } catch {
    throw new ApiError(res.status, `The ${what} sent a reply that isn't JSON.`);
  }
}

export async function listPlugins(): Promise<PluginIndex> {
  const data = await request<Record<string, unknown>>("/plugins");
  const skipped: Record<string, string> = {};
  if (data.skipped && typeof data.skipped === "object") {
    for (const [k, v] of Object.entries(data.skipped as Record<string, unknown>)) skipped[k] = str(v);
  }
  const plugins = Array.isArray(data.plugins) ? data.plugins.map(normalizePlugin) : [];
  return {
    plugins,
    skipped,
    enabled: Array.isArray(data.enabled) ? strList(data.enabled) : plugins.filter((p) => p.enabled).map((p) => p.id),
  };
}

export async function getPlugin(id: string): Promise<Plugin> {
  return normalizePlugin(await request<unknown>(`/plugins/${encodeURIComponent(id)}`));
}

export type SearchResult = { plugins: Plugin[]; engine: string };

export async function searchPlugins(q: string, signal?: AbortSignal): Promise<SearchResult> {
  const data = await request<Record<string, unknown>>(`/plugins/search?q=${encodeURIComponent(q)}`, { signal });
  return {
    plugins: Array.isArray(data.plugins) ? data.plugins.map(normalizePlugin) : [],
    engine: str(data.engine),
  };
}

export async function setPluginEnabled(id: string, on: boolean): Promise<string[]> {
  const data = await request<Record<string, unknown>>(
    `/plugins/${encodeURIComponent(id)}/${on ? "enable" : "disable"}`,
    { method: "POST" },
  );
  return strList(data.enabled);
}

export function errorText(e: unknown): string {
  return e instanceof ApiError ? e.message : "Something went wrong talking to the plugins API.";
}

export const NEEDS_VERIFICATION_HELP = "An admin has to verify this plugin before it can run on the demo agent.";

export function checkedAt(d = new Date()): string {
  return d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
}

export async function getBaseline(): Promise<boolean> {
  const data = await request<Record<string, unknown>>("/plugins/baseline", { method: "GET" });
  return data.baseline === true;
}

export async function setBaseline(on: boolean): Promise<boolean> {
  const data = await request<Record<string, unknown>>("/plugins/baseline", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ on }),
  });
  return data.baseline === true;
}
