// Mirrors api/schema.py (the shared contract). Change only with the team.
export type Verdict = "safe" | "suspicious" | "malicious";
export type ScamType =
  | "none" | "fake_bank" | "fake_payment_app" | "fake_parking_or_toll" | "fake_delivery"
  | "fake_government" | "tech_support" | "fake_login_other" | "malware_download" | "other";

export interface JevChecks {
  impersonates: string;
  impersonates_p: number;
  asks_password_p: number;
  asks_payment_p: number;
  prompt_injection_p: number;
  malicious_p: number;
}

export interface Payment {
  recipient: string;
  amount_sol: number;
  label: string;
  message: string;
  reference: string;
  merchant_verified: boolean;
  tx_signature: string | null;
}

export interface ScanResult {
  scan_id: string;
  url: string;
  final_url: string | null;
  redirect_chain: string[];
  domain: string | null;
  page_title: string | null;
  verdict: Verdict;
  jev_score: number;
  scam_type: ScamType;
  explanation: string;
  checks: JevChecks;
  screenshots: string[];
  flagged_before: number;
  payment: Payment | null;
  location: [number, number] | null;
  scanned_at: number;
  scan_ms: number | null;
}

/** One reported scam on the map (Typesense `scam_pins` document). */
export interface Pin {
  id?: string;
  url: string;
  domain: string | null;
  scam_type: ScamType | string;
  jev_score: number;
  explanation: string;
  location: [number, number];
  reported_at: number; // unix seconds
}

export interface StatsSummary {
  total_scans: number;
  safe: number;
  suspicious: number;
  malicious: number;
  avg_scan_ms: number | null;
  top_scam_types: { scam_type: string; count: number }[];
}

export interface HourlyBucket {
  hour: string | number; // ISO time or unix seconds
  total: number;
  malicious: number;
}

export interface PayResponse {
  tx_signature: string;
  explorer_url?: string;
}
