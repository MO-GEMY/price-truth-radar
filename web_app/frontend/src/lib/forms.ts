/**
 * Shared helpers for the public contact / add-store forms.
 *
 * Validation here mirrors the backend rules so users get instant Arabic
 * feedback; the API remains the source of truth.
 */

import { CONTACT_EMAIL } from "./site";

export const CONTACT_EMAIL_RE = /^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$/;

const MAX_URL_LENGTH = 2048;
const INTERNATIONAL_PHONE_RE = /^\+\d{8,15}$/;

/** Syntax-only http(s) URL check — mirrors the API. The URL is never fetched. */
export function isHttpUrl(value: string): boolean {
  const candidate = value.trim();
  if (!candidate || candidate.length > MAX_URL_LENGTH || /\s/.test(candidate)) return false;
  try {
    const url = new URL(candidate);
    if (url.protocol !== "http:" && url.protocol !== "https:") return false;
    if (url.username || url.password) return false;
    return url.hostname.includes(".");
  } catch {
    return false;
  }
}

/** E.164-style number; an Egyptian local mobile (`01xxxxxxxxx`) is accepted as `+20`. */
export function isWhatsAppNumber(value: string): boolean {
  let digits = value.replace(/[\s().\-]/g, "");
  if (digits.startsWith("00")) digits = `+${digits.slice(2)}`;
  else if (digits.startsWith("0")) digits = `+20${digits.slice(1)}`;
  if (!digits.startsWith("+")) digits = `+${digits}`;
  return INTERNATIONAL_PHONE_RE.test(digits);
}

/** `mailto:` link that opens the visitor's mail client with everything pre-filled. */
export function buildMailto(subject: string, body: string): string {
  return `mailto:${CONTACT_EMAIL}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
}

/** Arabic plural forms by count (1, 2, 3–10, 11+). */
function countArabic(count: number, one: string, two: string, few: string, many: string): string {
  if (count === 2) return two;
  if (count >= 3 && count <= 10) return few;
  return many || one;
}

/** Human wait hint for rate-limit replies. */
export function formatWaitArabic(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds)) return "بضع دقائق";
  if (seconds < 60) return "دقيقة تقريباً";
  if (seconds < 3600) {
    const minutes = Math.max(2, Math.round(seconds / 60));
    return `نحو ${minutes} ${countArabic(minutes, "دقيقة", "دقيقتين", "دقائق", "دقيقة")}`;
  }
  const hours = Math.max(2, Math.round(seconds / 3600));
  return `نحو ${hours} ${countArabic(hours, "ساعة", "ساعتين", "ساعات", "ساعة")}`;
}
