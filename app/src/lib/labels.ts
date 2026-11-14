import type { Verdict } from "./types";

// Plain words only. Never "phishing" or "redirect" in anything a user sees.
const SCAM_LABELS: Record<string, string> = {
  none: "No scam found",
  fake_bank: "Fake bank website",
  fake_payment_app: "Fake payment request",
  fake_parking_or_toll: "Fake parking or toll website",
  fake_delivery: "Fake delivery website",
  fake_government: "Fake government website",
  tech_support: "Fake tech support",
  fake_login_other: "Fake sign-in page",
  malware_download: "Harmful download",
  other: "Other scam",
};

export function scamLabel(t: string | null | undefined): string {
  if (!t) return "Scam";
  return SCAM_LABELS[t] ?? t.replace(/_/g, " ");
}

export const VERDICT_TEXT: Record<Verdict, { title: string; sub: string }> = {
  safe: { title: "Looks safe", sub: "We opened it on our server and found nothing wrong." },
  suspicious: { title: "Be careful", sub: "Something about this looks off. Don't enter any personal details." },
  malicious: { title: "Stop. This is a scam", sub: "Don't pay and don't type anything into this website." },
};

export function percent(p: number): string {
  return `${Math.round(Math.max(0, Math.min(1, p)) * 100)}%`;
}

export function timeAgo(unixSeconds: number): string {
  const s = Math.max(0, Math.floor(Date.now() / 1000 - unixSeconds));
  if (s < 60) return "just now";
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} minute${m === 1 ? "" : "s"} ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} hour${h === 1 ? "" : "s"} ago`;
  const d = Math.floor(h / 24);
  return `${d} day${d === 1 ? "" : "s"} ago`;
}

export function isWebLink(u: string | null | undefined): u is string {
  return !!u && /^https?:\/\//i.test(u);
}
