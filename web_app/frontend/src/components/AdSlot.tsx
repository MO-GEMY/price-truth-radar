"use client";

import { useEffect, useRef } from "react";
import { useLanguage } from "@/lib/i18n";

declare global {
  interface Window {
    adsbygoogle?: unknown[];
  }
}

const ADSENSE_CLIENT = (process.env.NEXT_PUBLIC_ADSENSE_CLIENT ?? "").trim();

export interface AdSlotProps {
  /** AdSense ad unit slot ID (numeric string from your AdSense dashboard). */
  slot?: string;
  /** AdSense responsive format attribute. */
  format?: "auto" | "horizontal" | "rectangle" | "fluid";
  /** Minimum height in pixels reserved to prevent CLS layout shifts. */
  minHeight?: number;
  className?: string;
}

/**
 * Lightweight, CLS-safe Google AdSense slot component.
 * Renders nothing when NEXT_PUBLIC_ADSENSE_CLIENT or `slot` is empty,
 * so unconfigured deployments show zero empty boxes and zero console errors.
 */
export function AdSlot({
  slot,
  format = "auto",
  minHeight = 100,
  className,
}: AdSlotProps) {
  const { lang } = useLanguage();
  const pushedRef = useRef(false);
  const slotId = (slot ?? "").trim();
  const enabled = Boolean(ADSENSE_CLIENT && slotId);

  useEffect(() => {
    if (!enabled || pushedRef.current) return;
    pushedRef.current = true;
    try {
      (window.adsbygoogle = window.adsbygoogle || []).push({});
    } catch {
      // Ignore AdSense load/blocker errors gracefully
    }
  }, [enabled]);

  if (!enabled) return null;

  const ariaLabel = lang === "ar" ? "إعلان" : "Advertisement";

  return (
    <aside
      className={className ? `ptr-ad-slot ${className}` : "ptr-ad-slot"}
      aria-label={ariaLabel}
      style={{ minHeight }}
    >
      <span className="ptr-ad-label" aria-hidden="true">
        {ariaLabel}
      </span>
      <ins
        className="adsbygoogle"
        style={{ display: "block", width: "100%", minHeight }}
        data-ad-client={ADSENSE_CLIENT}
        data-ad-slot={slotId}
        data-ad-format={format}
        data-full-width-responsive="true"
      />
    </aside>
  );
}
