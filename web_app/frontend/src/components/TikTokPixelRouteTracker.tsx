"use client";

import { useEffect, useRef } from "react";
import { usePathname } from "next/navigation";

/**
 * Fires `window.ttq.page()` on client-side App Router navigations.
 * Skips the initial mount because the TikTok Pixel base snippet already calls `ttq.page()`.
 */
export function TikTokPixelRouteTracker() {
  const pathname = usePathname();
  const initializedRef = useRef(false);

  useEffect(() => {
    if (!initializedRef.current) {
      initializedRef.current = true;
      return;
    }
    try {
      window.ttq?.page?.();
    } catch {
      // Ignore analytics failures (ad blockers, strict privacy browsers, etc.)
    }
  }, [pathname]);

  return null;
}
