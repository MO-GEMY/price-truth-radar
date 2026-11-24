"use client";

/**
 * Submit pipeline shared by the public forms (contact / add store).
 *
 * Owns everything that is identical between them: availability check, the
 * honeypot value, the optional Turnstile challenge (tokens are single-use), the
 * in-flight request, and the failure state the UI renders as a fallback.
 */

import { useEffect, useRef, useState, type ReactNode } from "react";
import { fetchSubmissionsConfig, postSubmission, type SubmissionFailure } from "@/lib/api";
import { useTheme } from "@/lib/theme";
import { FailureNotice } from "./SubmissionNotice";
import { TurnstileWidget } from "./TurnstileWidget";

const SERVER_REJECTED = "هذه القيمة غير مقبولة، راجعها وأعد المحاولة.";

export type SubmissionOutcome<F extends string> =
  | { kind: "sent" }
  | { kind: "failed" }
  /** A submit was already in flight; this one was dropped. */
  | { kind: "busy" }
  /** The API rejected specific fields; `errors` maps them onto this form's fields. */
  | { kind: "invalid"; errors: Partial<Record<F, string>> };

export function useSubmission<F extends string>(
  endpoint: "/api/submissions/contact" | "/api/submissions/store-suggestion",
  /** API field names → this form's fields. */
  serverField: Record<string, F>,
) {
  const { theme } = useTheme();
  const request = useRef<AbortController | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const [siteKey, setSiteKey] = useState("");
  const [website, setWebsite] = useState(""); // honeypot: stays empty for humans
  const [token, setToken] = useState("");
  const [challenge, setChallenge] = useState(0);
  const [challengeBlocked, setChallengeBlocked] = useState(false);
  const [pending, setPending] = useState(false);
  const [failure, setFailure] = useState<SubmissionFailure | null>(null);
  const [sent, setSent] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    fetchSubmissionsConfig(controller.signal).then((config) => {
      if (controller.signal.aborted) return;
      // An unreachable API counts as available; the submit call surfaces the fallback.
      setUnavailable(config !== null && !config.form_enabled);
      setSiteKey(config?.turnstile_site_key ?? "");
    });
    return () => controller.abort();
  }, []);

  useEffect(() => () => request.current?.abort(), []);

  async function submit(payload: Record<string, unknown>): Promise<SubmissionOutcome<F>> {
    if (request.current) return { kind: "busy" };
    const controller = new AbortController();
    request.current = controller;
    setPending(true);
    setFailure(null);
    try {
      const result = await postSubmission(
        endpoint,
        { ...payload, website, turnstile_token: token },
        controller.signal,
      );
      if (controller.signal.aborted) return { kind: "failed" };
      if (result.ok) {
        setSent(true);
        return { kind: "sent" };
      }
      setFailure(result);
      setToken(""); // Turnstile tokens are single-use
      setChallenge((count) => count + 1);
      if (result.reason === "validation") {
        const errors: Partial<Record<F, string>> = {};
        for (const field of result.fields) {
          const local = serverField[field];
          if (local) errors[local] = SERVER_REJECTED;
        }
        if (Object.keys(errors).length > 0) return { kind: "invalid", errors };
        // Rejected for a reason the form cannot map onto a field.
        setFailure({ reason: "unavailable" });
      }
      return { kind: "failed" };
    } finally {
      if (request.current === controller) {
        request.current = null;
        setPending(false);
      }
    }
  }

  function reset() {
    setSent(false);
    setFailure(null);
    setToken("");
    setChallenge((count) => count + 1);
  }

  /** The challenge widget, or the direct-email notice when it cannot load. Null while disabled. */
  const turnstile = (mailto: string): ReactNode =>
    !siteKey ? null : challengeBlocked ? (
      // No token can ever be produced here, so the direct-email route is the main action.
      <FailureNotice failure={{ reason: "turnstile" }} mailto={mailto} fallbackPrimary />
    ) : (
      <TurnstileWidget
        key={challenge}
        siteKey={siteKey}
        theme={theme}
        onToken={setToken}
        onError={() => setChallengeBlocked(true)}
      />
    );

  return {
    /** The API cannot deliver (no notification channel): show the direct-email route. */
    unavailable,
    pending,
    sent,
    failure,
    website,
    setWebsite,
    /** True while a required challenge has not been solved (or can never be). */
    needsToken: challengeBlocked || (siteKey !== "" && token === ""),
    turnstile,
    submit,
    reset,
  };
}
