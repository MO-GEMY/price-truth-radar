"use client";

import { useState } from "react";
import { Share2 } from "lucide-react";
import { useLanguage } from "@/lib/i18n";

export function ShareButton({ title, url, text }: { title: string; url: string; text?: string }) {
  const { ready, t } = useLanguage();
  const [status, setStatus] = useState<"idle" | "copied" | "manual">("idle");

  async function share() {
    setStatus("idle");
    if (navigator.share) {
      try {
        await navigator.share({ title, url, text });
        return;
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") return;
      }
    }
    try {
      await navigator.clipboard.writeText(url);
      setStatus("copied");
    } catch {
      setStatus("manual");
    }
  }

  return (
    <div className="ptr-share">
      <button type="button" className="ptr-button" disabled={!ready} onClick={() => void share()}>
        <Share2 size={15} aria-hidden="true" /> {t("ui.share")}
      </button>
      <div role="status" className="text-xs ptr-muted">
        {status === "copied" && t("deals.copied")}
        {status === "manual" && <label className="mt-2 block">
          {t("ui.copyFailed")}
          <input className="ptr-field" dir="ltr" readOnly value={url} onFocus={(event) => event.currentTarget.select()} />
        </label>}
      </div>
    </div>
  );
}
