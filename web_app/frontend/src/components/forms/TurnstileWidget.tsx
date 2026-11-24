"use client";

/**
 * Cloudflare Turnstile widget — rendered only when the API reports a site key
 * (`TURNSTILE_SITE_KEY`). Nothing loads from Cloudflare otherwise.
 *
 * Tokens are single-use: remount the widget (via `key`) after a failed submit.
 */

import { useEffect, useRef } from "react";

type TurnstileApi = {
  render: (container: HTMLElement, options: Record<string, unknown>) => string | undefined;
  remove: (widgetId: string) => void;
};

declare global {
  interface Window {
    turnstile?: TurnstileApi;
  }
}

const SCRIPT_SRC = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
const LOAD_TIMEOUT_MS = 12000;

function loadTurnstile(): Promise<TurnstileApi> {
  if (window.turnstile) return Promise.resolve(window.turnstile);
  return new Promise((resolve, reject) => {
    const settle = () => {
      if (window.turnstile) resolve(window.turnstile);
      else reject(new Error("Turnstile unavailable"));
    };
    const blocked = () => reject(new Error("Turnstile blocked"));

    const existing = document.querySelector<HTMLScriptElement>(`script[src="${SCRIPT_SRC}"]`);
    if (existing) {
      existing.addEventListener("load", settle);
      existing.addEventListener("error", blocked);
      return;
    }
    const script = document.createElement("script");
    script.src = SCRIPT_SRC;
    script.async = true;
    script.defer = true;
    script.onload = settle;
    script.onerror = blocked;
    document.head.appendChild(script);
  });
}

export function TurnstileWidget({
  siteKey,
  theme,
  onToken,
  onError,
}: {
  siteKey: string;
  theme: "light" | "dark";
  /** Fresh token once solved; "" when it expires or the challenge errors. */
  onToken: (token: string) => void;
  /** The script is blocked or unreachable, so a token can never be produced. */
  onError: () => void;
}) {
  const container = useRef<HTMLDivElement>(null);
  const onTokenRef = useRef(onToken);
  const onErrorRef = useRef(onError);

  useEffect(() => {
    onTokenRef.current = onToken;
    onErrorRef.current = onError;
  });

  useEffect(() => {
    let cancelled = false;
    let widgetId: string | undefined;

    const timeout = setTimeout(() => {
      if (!cancelled && widgetId === undefined) onErrorRef.current();
    }, LOAD_TIMEOUT_MS);

    loadTurnstile()
      .then((api) => {
        if (cancelled || !container.current) return;
        clearTimeout(timeout);
        widgetId = api.render(container.current, {
          sitekey: siteKey,
          theme,
          language: "ar",
          size: "flexible",
          callback: (token: string) => onTokenRef.current(token),
          "expired-callback": () => onTokenRef.current(""),
          "error-callback": () => onTokenRef.current(""),
        });
      })
      .catch(() => {
        clearTimeout(timeout);
        if (!cancelled) onErrorRef.current();
      });

    return () => {
      cancelled = true;
      clearTimeout(timeout);
      if (widgetId !== undefined) window.turnstile?.remove(widgetId);
    };
  }, [siteKey, theme]);

  return <div ref={container} className="ptr-turnstile" />;
}
