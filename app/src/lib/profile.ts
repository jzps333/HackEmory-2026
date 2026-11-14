// The user's ScanSafe profile from onboarding. Saved only in this browser (localStorage).
import type { OnboardingData } from "./onboarding";

const KEY = "scansafe.profile.v1";

export interface Profile extends OnboardingData {
  /** Phone in international format (+15551234567), or null if we couldn't read it. */
  phoneE164: string | null;
  createdAt: number;
}

/** "+1 (555) 123-4567", "555-123-4567", "15551234567" -> "+15551234567". US default for 10 digits. */
export function toE164(raw: string): string | null {
  const digits = raw.replace(/\D/g, "");
  if (raw.trim().startsWith("+")) return digits.length >= 8 && digits.length <= 15 ? `+${digits}` : null;
  if (digits.length === 10) return `+1${digits}`;
  if (digits.length === 11 && digits.startsWith("1")) return `+${digits}`;
  return null;
}

export function loadProfile(): Profile | null {
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return null;
    const p = JSON.parse(raw) as Profile;
    return p && typeof p.fullName === "string" ? p : null;
  } catch {
    return null; // private mode, blocked storage, or bad data: just onboard again
  }
}

export function saveProfile(data: OnboardingData): Profile {
  const profile: Profile = { ...data, phoneE164: toE164(data.phone), createdAt: Date.now() };
  try {
    window.localStorage.setItem(KEY, JSON.stringify(profile));
  } catch {
    // Storage unavailable: the app still works for this visit.
  }
  return profile;
}

export function clearProfile(): void {
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    /* nothing to clear */
  }
}
