// Phone-number sign-in against the ScanSafe API (/auth/*). The caller texts a short code to the
// ScanSafe Chert line; we poll until the API has seen that text, then keep the session token in
// localStorage and send it as a Bearer token on /auth/me, /auth/logout and /me/*.
// The request_id and the token are never logged or put in a URL.

import { ApiError, request, str } from "./api";

const TOKEN_KEY = "scansafe.chert.session";
const WHAT = "sign-in API";

export function readToken(): string | null {
  try {
    const t = window.localStorage.getItem(TOKEN_KEY);
    return t && t.length < 4096 ? t : null;
  } catch {
    return null;
  }
}

export function saveToken(token: string): void {
  try {
    window.localStorage.setItem(TOKEN_KEY, token);
  } catch {
    /* private mode or storage blocked: the session lasts until the tab closes */
  }
}

export function clearToken(): void {
  try {
    window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* nothing stored */
  }
}

export const bearer = (token: string): Record<string, string> => ({ Authorization: `Bearer ${token}` });

/** US by default: 10 digits get +1. Anything starting with + is kept as an international number. */
export function toE164(input: string): string | null {
  const s = input.trim();
  const digits = s.replace(/\D/g, "");
  if (s.startsWith("+")) return digits.length >= 8 && digits.length <= 15 ? `+${digits}` : null;
  if (digits.length === 10) return `+1${digits}`;
  if (digits.length === 11 && digits.startsWith("1")) return `+${digits}`;
  return null;
}

export function maskPhone(phone: string): string {
  const d = phone.replace(/\D/g, "");
  return d.length >= 4 ? `•••${d.slice(-4)}` : "•••";
}

/** sms: link that opens Messages with the code filled in. Only digits and + go into the address. */
export function smsHref(line: string, body: string): string {
  const to = line.replace(/[^\d+]/g, "");
  return `sms:${to}?&body=${encodeURIComponent(body)}`;
}

const postJson = (body: unknown, headers: Record<string, string> = {}) => ({
  method: "POST",
  body: JSON.stringify(body),
  headers: { "Content-Type": "application/json", ...headers },
});

export type PhoneStart = { code: string; requestId: string; line: string; smsBody: string };

export async function startPhoneSignIn(phone: string): Promise<PhoneStart> {
  const d = await request<Record<string, unknown>>("/auth/phone/start", postJson({ phone }), WHAT);
  const out = { code: str(d.code), requestId: str(d.request_id), line: str(d.line), smsBody: str(d.sms_body) };
  if (!out.code || !out.requestId || !out.line) {
    throw new ApiError(200, "The sign-in API sent an incomplete reply. Try again.");
  }
  if (!out.smsBody) out.smsBody = out.code;
  return out;
}

export type VerifyResult = { verified: false } | { verified: true; phone: string; token: string };

export async function verifyPhoneSignIn(phone: string, requestId: string, signal?: AbortSignal): Promise<VerifyResult> {
  const d = await request<Record<string, unknown>>(
    "/auth/phone/verify",
    { ...postJson({ phone, request_id: requestId }), signal },
    WHAT,
  );
  if (d.verified !== true) return { verified: false };
  const token = str(d.token);
  if (!token) throw new ApiError(200, "The sign-in API didn't send a session. Send a new code.");
  return { verified: true, phone: str(d.phone) || phone, token };
}

export type Me = { signedIn: boolean; phoneMasked: string };

export async function getMe(token: string): Promise<Me> {
  const d = await request<Record<string, unknown>>("/auth/me", { headers: bearer(token) }, WHAT);
  return { signedIn: d.signed_in === true, phoneMasked: str(d.phone_masked) };
}

export async function logout(token: string): Promise<void> {
  await request<unknown>("/auth/logout", postJson({}, bearer(token)), WHAT);
}
