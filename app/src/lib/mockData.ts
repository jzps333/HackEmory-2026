import mockSafe from "@/mock/mock_safe.json";
import mockMalicious from "@/mock/mock_malicious.json";
import type { HourlyBucket, Pin, ScanResult, StatsSummary } from "./types";

export const MOCK_SAFE = mockSafe as unknown as ScanResult;
export const MOCK_MALICIOUS = mockMalicious as unknown as ScanResult;

/** Same rule as the backend's mock mode: solana: payments -> safe mock, anything else -> scam mock. */
export function mockScan(url: string, location: [number, number] | null): ScanResult {
  const base = url.trim().toLowerCase().startsWith("solana:") ? MOCK_SAFE : MOCK_MALICIOUS;
  return {
    ...structuredClone(base),
    scan_id: `mock-${Math.random().toString(36).slice(2, 10)}`,
    url: url.trim(),
    location: location ?? base.location,
    scanned_at: Math.floor(Date.now() / 1000),
  };
}

const now = () => Math.floor(Date.now() / 1000);

export function mockPins(): Pin[] {
  const t = now();
  return [
    { id: "m1", url: "https://bit.ly/peachtree-park-42", domain: "peachtree-parking-pay.xyz", scam_type: "fake_parking_or_toll", jev_score: 0.94, explanation: "Fake parking page using the Peachtree Parking name. It asks for your card number.", location: [33.7925, -84.324], reported_at: t - 600 },
    { id: "m2", url: "https://peachtree-parking-pay.xyz/meter/17", domain: "peachtree-parking-pay.xyz", scam_type: "fake_parking_or_toll", jev_score: 0.91, explanation: "Same fake parking website, on a different meter sticker.", location: [33.7931, -84.3229], reported_at: t - 3600 },
    { id: "m3", url: "https://usps-redelivery-help.top/track", domain: "usps-redelivery-help.top", scam_type: "fake_delivery", jev_score: 0.88, explanation: "Fake delivery page that asks for a small fee and your card details.", location: [33.7988, -84.3266], reported_at: t - 7200 },
    { id: "m4", url: "https://secure-chase-verify.co/login", domain: "secure-chase-verify.co", scam_type: "fake_bank", jev_score: 0.97, explanation: "Fake bank sign-in page. It is not your bank's real website.", location: [33.7853, -84.3357], reported_at: t - 18000 },
    { id: "m5", url: "https://ga-tolls-pay.info", domain: "ga-tolls-pay.info", scam_type: "fake_parking_or_toll", jev_score: 0.9, explanation: "Fake toll payment page claiming you owe a late fee.", location: [33.7759, -84.3104], reported_at: t - 43000 },
    { id: "m6", url: "https://free-wifi-emory.click", domain: "free-wifi-emory.click", scam_type: "fake_login_other", jev_score: 0.83, explanation: "Fake Wi-Fi sign-in page that asks for your school password.", location: [33.7905, -84.3253], reported_at: t - 90000 },
  ];
}

export function mockSummary(): StatsSummary {
  return {
    total_scans: 412, safe: 298, suspicious: 47, malicious: 67, avg_scan_ms: 4100,
    top_scam_types: [
      { scam_type: "fake_parking_or_toll", count: 29 },
      { scam_type: "fake_delivery", count: 17 },
      { scam_type: "fake_bank", count: 12 },
      { scam_type: "fake_login_other", count: 9 },
    ],
  };
}

export function mockHourly(hours = 24): HourlyBucket[] {
  const t = now();
  const out: HourlyBucket[] = [];
  for (let i = hours - 1; i >= 0; i--) {
    const hourStart = (Math.floor(t / 3600) - i) * 3600;
    const h = new Date(hourStart * 1000).getHours();
    const busy = h >= 8 && h <= 22 ? 1 : 0.25;
    const total = Math.round((10 + ((h * 7) % 13)) * busy) + 2;
    out.push({ hour: hourStart, total, malicious: Math.round(total * (0.12 + ((h * 3) % 5) / 30)) });
  }
  return out;
}
