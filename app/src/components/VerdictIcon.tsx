import type { Verdict } from "@/lib/types";

/** Shape carries the meaning too (check / triangle / stop sign), so color is never the only signal. */
export default function VerdictIcon({ verdict }: { verdict: Verdict }) {
  if (verdict === "safe") {
    return (
      <svg viewBox="0 0 100 100" aria-hidden="true" focusable="false">
        <circle cx="50" cy="50" r="46" fill="#18794e" />
        <path d="M28 52 L44 68 L74 34" fill="none" stroke="#fff" strokeWidth="11" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }
  if (verdict === "suspicious") {
    return (
      <svg viewBox="0 0 100 100" aria-hidden="true" focusable="false">
        <path d="M50 6 L96 90 H4 Z" fill="#f2a516" stroke="#b45309" strokeWidth="6" strokeLinejoin="round" />
        <rect x="44" y="32" width="12" height="32" rx="5" fill="#3a2400" />
        <circle cx="50" cy="76" r="7" fill="#3a2400" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 100 100" aria-hidden="true" focusable="false">
      <polygon points="30,3 70,3 97,30 97,70 70,97 30,97 3,70 3,30" fill="#c0262d" stroke="#fff" strokeWidth="4" />
      <text x="50" y="61" textAnchor="middle" fontSize="28" fontWeight="900" fill="#fff" fontFamily="Arial, sans-serif">STOP</text>
    </svg>
  );
}
