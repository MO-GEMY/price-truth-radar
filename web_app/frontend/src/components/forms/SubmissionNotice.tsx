"use client";

/**
 * Presentational state UI for the public forms: unavailable, failed, accepted.
 * Every dead end offers the direct-email route so a visitor is never stranded.
 */

import Link from "next/link";
import { useEffect, useRef, type ReactNode } from "react";
import { Check, Loader2, Send, TriangleAlert } from "lucide-react";
import type { SubmissionFailure } from "@/lib/api";
import { formatWaitArabic } from "@/lib/forms";
import { CONTACT_EMAIL } from "@/lib/site";

export function ContactEmailLink() {
  return (
    <a className="ptr-link" href={`mailto:${CONTACT_EMAIL}`} dir="ltr">
      {CONTACT_EMAIL}
    </a>
  );
}

/** The API has no notification channel configured (or no API URL is set). */
export function FormUnavailableNotice({ children }: { children: ReactNode }) {
  return (
    <div className="ptr-notice ptr-warning ptr-notice-stack" role="status">
      <p className="flex items-center gap-2 font-semibold">
        <TriangleAlert size={18} aria-hidden="true" />
        الإرسال من الموقع غير متاح حالياً
      </p>
      <div>{children}</div>
      <Link className="ptr-button ptr-primary w-fit" href={`mailto:${CONTACT_EMAIL}`}>
        <Send size={16} aria-hidden="true" />
        <span dir="ltr">{CONTACT_EMAIL}</span>
      </Link>
    </div>
  );
}

const FAILURE_TITLE: Record<SubmissionFailure["reason"], string> = {
  validation: "تحقق من الحقول المحددة",
  rate_limited: "أرسلت عدة رسائل خلال وقت قصير",
  turnstile: "تعذّر التحقق من أنك لست روبوتاً",
  network: "تعذّر الاتصال بالخادم",
  unavailable: "تعذّر إرسال الرسالة من الموقع",
};

/** What to do next; `null` means the visitor only needs to fix the highlighted fields. */
const FAILURE_NEXT_STEP: Record<SubmissionFailure["reason"], string | null> = {
  validation: null,
  rate_limited: "انتظر قليلاً ثم أعد المحاولة.",
  turnstile: "أعد المحاولة، وإن استمرت المشكلة أرسل رسالتك بالبريد مباشرة.",
  network: "تحقق من اتصالك بالإنترنت وأعد المحاولة.",
  unavailable: "افتح تطبيق البريد وأرسلها مباشرة؛ ستُنسخ بياناتك تلقائياً.",
};

export function FailureNotice({
  failure,
  mailto,
  fallbackPrimary = false,
}: {
  failure: SubmissionFailure;
  /** Pre-filled `mailto:` carrying what the visitor already typed. */
  mailto: string;
  /** Promote the email route to the main action when submitting cannot succeed. */
  fallbackPrimary?: boolean;
}) {
  const nextStep =
    failure.reason === "rate_limited"
      ? `انتظر ${formatWaitArabic(failure.retryAfterSeconds)} ثم أعد المحاولة.`
      : FAILURE_NEXT_STEP[failure.reason];

  return (
    <div className="ptr-notice ptr-warning ptr-notice-stack" role="alert">
      <p className="flex items-center gap-2 font-semibold">
        <TriangleAlert size={18} aria-hidden="true" />
        {FAILURE_TITLE[failure.reason]}
      </p>
      {nextStep && (
        <>
          <div>
            <p>{nextStep}</p>
            <p className="mt-2">
              أو راسلنا مباشرة عبر <ContactEmailLink />
            </p>
          </div>
          <a
            className={`ptr-button w-fit${fallbackPrimary ? " ptr-primary" : ""}`}
            href={mailto}
          >
            <Send size={16} aria-hidden="true" />
            إرسال عبر تطبيق البريد
          </a>
        </>
      )}
    </div>
  );
}

export function SuccessNotice({
  title,
  children,
  onReset,
  resetLabel,
}: {
  title: string;
  children: ReactNode;
  onReset: () => void;
  resetLabel: string;
}) {
  const button = useRef<HTMLButtonElement>(null);
  useEffect(() => button.current?.focus(), []);

  return (
    <div className="ptr-notice ptr-notice-stack" role="status">
      <p className="flex items-center gap-2 font-semibold">
        <Check size={18} aria-hidden="true" />
        {title}
      </p>
      <div>{children}</div>
      <button
        ref={button}
        type="button"
        className="ptr-button ptr-primary w-fit"
        onClick={onReset}
      >
        {resetLabel}
      </button>
    </div>
  );
}

export function SubmitButton({
  pending,
  disabled,
  label,
  pendingLabel,
}: {
  pending: boolean;
  disabled: boolean;
  label: string;
  pendingLabel: string;
}) {
  return (
    <button
      type="submit"
      disabled={disabled || pending}
      className="ptr-button ptr-primary ptr-submit"
    >
      {pending ? (
        <Loader2 size={16} className="animate-spin" aria-hidden="true" />
      ) : (
        <Send size={16} aria-hidden="true" />
      )}
      {pending ? pendingLabel : label}
    </button>
  );
}
