/**
 * "Dogwood Parking", the official app of Dogwood Lot & Meter Co.: a MADE-UP brand for the ScanSafe
 * demo (EmoryHacks 2026). Not a real business, not a real app. Solana devnet test SOL only.
 *
 * Shared pieces for /dogwood/install, /dogwood/app and /dogwood/authorize: the phone-shaped shell,
 * the app icon, and the ScanSafe API base. The only network calls these pages make are the
 * Dogwood operator endpoints on the ScanSafe API (see each page).
 */
import FictionalFooter from "../components/FictionalFooter";

export const API_BASE = "https://api.scansafe.nyc";
export const GREEN = "#1f6f43";
export const GREEN_DARK = "#14512f";

/** 0.03 -> "0.03", 0.1 -> "0.1": no float noise, no trailing zeros (same as the agent says it). */
export function solText(amount: number): string {
  if (!Number.isFinite(amount)) return "0";
  const s = amount.toFixed(9).replace(/0+$/, "").replace(/\.$/, "");
  return s || "0";
}

/** rate * hours in whole lamports, like the server, for the total shown before the server echoes. */
export function amountFor(rate: number, hours: number): number {
  return (Math.round(rate * 1_000_000_000) * hours) / 1_000_000_000;
}

export function hoursText(n: number): string {
  return n === 1 ? "1 hour" : `${n} hours`;
}

/** The ?name=value from the page's own URL (client only). */
export function queryParam(name: string): string {
  if (typeof window === "undefined") return "";
  return new URLSearchParams(window.location.search).get(name) || "";
}

/** Plain-words message from a FastAPI-style error body ({detail} or {message}), else the status. */
export async function errorText(res: Response): Promise<string> {
  try {
    const body = await res.json();
    const d = body && (body.detail ?? body.message ?? body.error);
    if (typeof d === "string" && d.trim()) return d.trim().slice(0, 200);
    if (d && typeof d === "object" && typeof d.message === "string") return d.message.slice(0, 200);
  } catch {
    /* not JSON */
  }
  return `The server answered ${res.status}${res.statusText ? ` (${res.statusText})` : ""}.`;
}

export function AppIcon({ size = 64 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" role="img" aria-label="Dogwood Parking icon"
      style={{ display: "block", borderRadius: size * 0.23, flex: "none" }}>
      <rect width="64" height="64" fill={GREEN} />
      {/* a dogwood blossom: four notched petals around a gold centre */}
      {[0, 90, 180, 270].map((r) => (
        <g key={r} transform={`rotate(${r} 32 32)`}>
          <path d="M32 31 C24 24 23 13 32 9 C41 13 40 24 32 31 Z" fill="#fff8f4" />
          <path d="M29.5 10.2 L32 13 L34.5 10.2" fill="none" stroke="#e7a3b3" strokeWidth="1.8" strokeLinecap="round" />
        </g>
      ))}
      <circle cx="32" cy="32" r="5.5" fill="#f2c14e" />
      <circle cx="32" cy="32" r="2.4" fill="#c98f1d" />
    </svg>
  );
}

const CSS = `
body:has(.dw-root) .site-header, body:has(.dw-root) .skip-link { display: none !important; }
body:has(.dw-root) { background: #e4ebe6; }
body:has(.dw-root) > main { max-width: none; padding: 0; margin: 0; }
.dw-root { min-height: 100dvh; display: flex; justify-content: center; color: #15231b;
  font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", system-ui, "Segoe UI", Roboto, Arial, sans-serif;
  font-size: 16px; line-height: 1.4; }
.dw-phone { width: 100%; max-width: 430px; min-height: 100dvh; background: #f6f8f6; display: flex; flex-direction: column; }
.dw-body { flex: 1; padding: 16px; }
.dw-root h1, .dw-root h2, .dw-root p { margin-top: 0; }
.dw-root h1 { font-size: 24px; line-height: 1.2; margin-bottom: 6px; }
.dw-root h2 { font-size: 17px; margin-bottom: 8px; }
.dw-root p { margin-bottom: 10px; }
.dw-card { background: #fff; border-radius: 16px; padding: 16px; margin-bottom: 14px; box-shadow: 0 1px 3px #0001, 0 0 0 1px #0000000d; }
.dw-btn { display: flex; align-items: center; justify-content: center; width: 100%; min-height: 54px; padding: 12px 16px;
  border-radius: 14px; border: 0; font: inherit; font-size: 17px; font-weight: 700; cursor: pointer; text-decoration: none;
  background: ${GREEN}; color: #fff; }
.dw-btn:hover { background: ${GREEN_DARK}; }
.dw-btn:disabled { opacity: .5; cursor: not-allowed; }
.dw-btn.secondary { background: #fff; color: ${GREEN}; box-shadow: inset 0 0 0 2px ${GREEN}; }
.dw-btn.secondary:hover { background: #eef6f1; }
.dw-btn:focus-visible, .dw-input:focus-visible, .dw-seg button:focus-visible { outline: 3px solid #1a56db; outline-offset: 2px; }
.dw-muted { color: #55655c; font-size: 14px; }
.dw-label { display: block; font-size: 14px; font-weight: 700; color: #33443a; margin-bottom: 6px; }
.dw-input { width: 100%; box-sizing: border-box; padding: 12px 14px; font: inherit; font-size: 22px; font-weight: 700;
  letter-spacing: .12em; text-transform: uppercase; border: 2px solid #c9d6ce; border-radius: 12px; background: #fff; color: #111; }
.dw-input:focus { border-color: ${GREEN}; }
.dw-seg { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; background: #e8efea; padding: 5px; border-radius: 14px; }
.dw-seg button { min-height: 52px; border: 0; border-radius: 10px; background: transparent; font: inherit; font-size: 18px;
  font-weight: 700; color: #2b3d32; cursor: pointer; }
.dw-seg button[aria-pressed="true"] { background: #fff; color: ${GREEN}; box-shadow: 0 1px 3px #0002; }
.dw-row { display: flex; justify-content: space-between; gap: 12px; padding: 8px 0; border-bottom: 1px solid #edf1ee; }
.dw-row:last-child { border-bottom: 0; }
.dw-row span:first-child { color: #55655c; }
.dw-row span:last-child { font-weight: 700; text-align: right; word-break: break-word; }
.dw-spin { width: 44px; height: 44px; border-radius: 50%; border: 5px solid #d5e6dc; border-top-color: ${GREEN};
  animation: dw-spin 1s linear infinite; margin: 6px auto 14px; }
@keyframes dw-spin { to { transform: rotate(360deg); } }
.dw-alert { background: #fde7e7; color: #8a1111; border-radius: 12px; padding: 10px 12px; font-size: 15px; margin-bottom: 12px; }
.dw-note { background: #fff4d6; color: #5a3700; border-radius: 12px; padding: 10px 12px; font-size: 14px; margin-bottom: 12px; }
@media (min-width: 640px) {
  .dw-root { padding: 24px 0; min-height: auto; }
  .dw-phone { min-height: 844px; border-radius: 44px; overflow: hidden; box-shadow: 0 0 0 10px #101512, 0 24px 60px #0004; }
}
@media (prefers-reduced-motion: reduce) { .dw-spin { animation-duration: 3s; } }
`;

export function Shell({ children, header }: { children: React.ReactNode; header?: React.ReactNode }) {
  return (
    <div className="dw-root">
      <style>{CSS}</style>
      <div className="dw-phone">
        {header}
        <div className="dw-body">{children}</div>
        <FictionalFooter />
      </div>
    </div>
  );
}

/** The green app bar of the Dogwood Parking app. */
export function AppBar({ right }: { right?: React.ReactNode }) {
  return (
    <div style={{ background: GREEN, color: "#fff", padding: "14px 16px", display: "flex", alignItems: "center", gap: 10 }}>
      <span style={{ borderRadius: 9, boxShadow: "0 0 0 2px #ffffff70", flex: "none" }}><AppIcon size={34} /></span>
      <div style={{ fontWeight: 800, fontSize: 20, flex: 1 }}>Dogwood Parking</div>
      {right}
    </div>
  );
}
