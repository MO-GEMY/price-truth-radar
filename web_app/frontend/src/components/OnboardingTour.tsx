"use client";

/**
 * First-visit interactive onboarding guide (spotlight tour) for the homepage.
 *
 * Design constraints (see task brief):
 * - Pure client-side: no new dependencies, no API calls.
 * - Hydration-safe: renders nothing until mounted, then follows the same
 *   localStorage-after-mount pattern as lib/i18n.tsx and lib/theme.tsx.
 * - Auto-opens only once, only on the homepage (this component is mounted
 *   only by src/app/page.tsx), and only when `asarak_onboarding_v1_done`
 *   is not set in localStorage. Deep links never mount it.
 * - `/?tour=1` forces it open (navbar replay button). Closing or finishing
 *   a forced tour removes `tour=1` via history.replaceState (through
 *   setBrowseParams) so a refresh does not replay it.
 * - Step 4 targets the nav; on small screens the nav is a fixed bottom tab
 *   bar, and if the nav target is missing/hidden the tour falls back to
 *   the header bar, then to a centered card with a plain backdrop.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { setBrowseParams, useBrowseParams } from "@/lib/browse-state";
import { formatNumber } from "@/lib/format";
import { useLanguage } from "@/lib/i18n";
import type { TranslationKey } from "@/lib/translations";

const STORAGE_KEY = "asarak_onboarding_v1_done";
const SPOTLIGHT_MAX_HEIGHT = 500;
const CARD_WIDTH = 360;
const CARD_GAP = 16;

interface TourStep {
  /** CSS selectors tried in order; first visible match wins. Empty = no target (centered card). */
  selectors: string[];
  scrollBlock: ScrollLogicalPosition;
  title: TranslationKey;
  body: TranslationKey;
}

const STEPS: TourStep[] = [
  {
    selectors: [],
    scrollBlock: "center",
    title: "tour.welcome.title",
    body: "tour.welcome.body",
  },
  {
    selectors: ['[data-tour="search"]'],
    scrollBlock: "center",
    title: "tour.search.title",
    body: "tour.search.body",
  },
  {
    selectors: ['[data-tour="deals"]'],
    scrollBlock: "start",
    title: "tour.deals.title",
    body: "tour.deals.body",
  },
  {
    // Nav first; the sticky header bar is the fallback when the nav links
    // are collapsed/hidden (e.g. very small screens), and if neither is
    // measurable the card simply centers over the backdrop.
    selectors: ['[data-tour="nav"]', '[data-tour="mast"]'],
    scrollBlock: "center",
    title: "tour.alerts.title",
    body: "tour.alerts.body",
  },
];

interface SpotRect {
  top: number;
  left: number;
  width: number;
  height: number;
  bottom: number;
}

function isVisible(el: HTMLElement): boolean {
  if (el.getClientRects().length === 0) return false;
  const style = window.getComputedStyle(el);
  if (style.display === "none" || style.visibility === "hidden") return false;
  const rect = el.getBoundingClientRect();
  return rect.width > 0 && rect.height > 0;
}

function resolveTarget(step: TourStep): HTMLElement | null {
  for (const selector of step.selectors) {
    const el = document.querySelector(selector);
    if (el instanceof HTMLElement && isVisible(el)) return el;
  }
  return null;
}

function measure(el: HTMLElement): SpotRect | null {
  const rect = el.getBoundingClientRect();
  if (rect.width === 0 || rect.height === 0) return null;
  const pad = 8;
  const top = rect.top - pad;
  // Tall targets (the results section) are capped so the spotlight frames
  // their top — heading, filters and first listings — not the whole feed.
  const height = Math.min(rect.height + pad * 2, SPOTLIGHT_MAX_HEIGHT);
  return {
    top,
    left: rect.left - pad,
    width: rect.width + pad * 2,
    height,
    bottom: top + height,
  };
}

function markDone(): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, "1");
  } catch {
    // Storage unavailable (private mode) — the tour just may re-offer next visit.
  }
}

function isDone(): boolean {
  try {
    return window.localStorage.getItem(STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

export function OnboardingTour() {
  const { lang, dir, t } = useLanguage();
  const params = useBrowseParams();
  const forced = params.get("tour") === "1";

  const [open, setOpen] = useState(false);
  const [stepIndex, setStepIndex] = useState(0);
  const [rect, setRect] = useState<SpotRect | null>(null);
  const [cardHeight, setCardHeight] = useState(240);

  const cardRef = useRef<HTMLDivElement>(null);
  const autoCheckedRef = useRef(false);

  const close = useCallback(() => {
    markDone();
    setOpen(false);
    setStepIndex(0);
    setRect(null);
    // Polish: a tour opened via /?tour=1 must not replay on refresh.
    if (new URLSearchParams(window.location.search).get("tour") === "1") {
      setBrowseParams({ tour: undefined }, true);
    }
  }, []);

  /* Opening rules: forced via ?tour=1 (replay), otherwise once for
     first-time visitors, shortly after mount so the hero has settled. */
  useEffect(() => {
    if (forced) {
      if (!open) {
        setStepIndex(0);
        setOpen(true);
      }
      return;
    }
    if (autoCheckedRef.current) return;
    autoCheckedRef.current = true;
    if (isDone()) return;
    const id = window.setTimeout(() => setOpen(true), 600);
    return () => window.clearTimeout(id);
  }, [forced, open]);

  /* Spotlight tracking: scroll the target into view, then keep the
     spotlight glued to it on scroll / resize while the tour is open. */
  useEffect(() => {
    if (!open) return;
    const step = STEPS[stepIndex];
    cardRef.current?.focus({ preventScroll: true });

    if (step.selectors.length === 0) {
      setRect(null);
      return;
    }
    const el = resolveTarget(step);
    if (!el) {
      setRect(null);
      return;
    }

    let cancelled = false;
    const update = () => {
      if (!cancelled) setRect(measure(el));
    };

    el.scrollIntoView({ behavior: "smooth", block: step.scrollBlock });
    const raf = window.requestAnimationFrame(update);
    const settle = window.setTimeout(update, 450);
    const late = window.setTimeout(update, 950);
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    return () => {
      cancelled = true;
      window.cancelAnimationFrame(raf);
      window.clearTimeout(settle);
      window.clearTimeout(late);
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
    };
  }, [open, stepIndex]);

  /* Escape closes from anywhere in the tour. */
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        close();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, close]);

  /* Track the card's real height so desktop placement can sit above the
     target when there is no room below it. */
  useEffect(() => {
    if (!open) return;
    const node = cardRef.current;
    if (!node) return;
    const height = node.offsetHeight;
    if (height > 0) setCardHeight((prev) => (prev === height ? prev : height));
  }, [open, stepIndex, rect]);

  if (!open) return null;

  const step = STEPS[stepIndex];
  const isFirst = stepIndex === 0;
  const isLast = stepIndex === STEPS.length - 1;

  const next = () => {
    if (isLast) close();
    else setStepIndex((value) => Math.min(value + 1, STEPS.length - 1));
  };
  const back = () => setStepIndex((value) => Math.max(value - 1, 0));

  /* Card placement. Mobile (<640px) is docked: bottom by default, top when
     the spotlight target lives at the bottom of the screen (Step 4's fixed
     bottom tab bar) so the card never covers the highlighted element. */
  const viewportWidth = window.innerWidth;
  const viewportHeight = window.innerHeight;
  const isMobile = viewportWidth < 640;
  let cardStyle: React.CSSProperties | undefined;
  let cardClassName = "asarak-tour-card";
  if (!rect) {
    cardClassName += " asarak-tour-card--centered";
  } else if (isMobile) {
    cardClassName += " asarak-tour-card--docked";
    const targetNearBottom = rect.top > viewportHeight - 180;
    cardStyle = targetNearBottom ? { top: 76 } : { bottom: 12 };
  } else {
    const left = Math.min(
      Math.max(rect.left + rect.width / 2 - CARD_WIDTH / 2, 16),
      Math.max(viewportWidth - CARD_WIDTH - 16, 16),
    );
    let top: number;
    if (rect.bottom + CARD_GAP + cardHeight <= viewportHeight - 16) {
      top = rect.bottom + CARD_GAP;
    } else if (rect.top - CARD_GAP - cardHeight >= 16) {
      top = rect.top - CARD_GAP - cardHeight;
    } else {
      top = Math.min(
        Math.max((viewportHeight - cardHeight) / 2, 16),
        Math.max(viewportHeight - cardHeight - 16, 16),
      );
    }
    cardStyle = { top, left, width: CARD_WIDTH };
  }

  return (
    <div
      className="asarak-tour"
      dir={dir}
      onClick={(event) => {
        if (!cardRef.current?.contains(event.target as Node)) {
          close();
        }
      }}
    >
      {rect ? (
        <div
          className="asarak-tour-spotlight"
          aria-hidden="true"
          style={{
            top: rect.top,
            left: rect.left,
            width: rect.width,
            height: rect.height,
          }}
        />
      ) : (
        <div className="asarak-tour-backdrop" aria-hidden="true" />
      )}

      <div
        ref={cardRef}
        className={cardClassName}
        style={cardStyle}
        role="dialog"
        aria-modal="true"
        aria-labelledby="asarak-tour-title"
        aria-describedby="asarak-tour-body"
        tabIndex={-1}
      >
        <button
          type="button"
          className="asarak-tour-close"
          onClick={close}
          aria-label={t("ui.close")}
        >
          <X size={16} aria-hidden="true" />
        </button>

        <p className="asarak-tour-progress" role="status">
          {t("tour.stepOf", {
            current: formatNumber(stepIndex + 1, lang),
            total: formatNumber(STEPS.length, lang),
          })}
        </p>
        <div className="asarak-tour-dots" aria-hidden="true">
          {STEPS.map((item, index) => (
            <span
              key={item.title}
              className={
                index === stepIndex
                  ? "asarak-tour-dot asarak-tour-dot--active"
                  : "asarak-tour-dot"
              }
            />
          ))}
        </div>

        <h2 id="asarak-tour-title" className="asarak-tour-title">
          {t(step.title)}
        </h2>
        <p id="asarak-tour-body" className="asarak-tour-body">
          {t(step.body)}
        </p>

        <div className="asarak-tour-actions">
          {!isLast && (
            <button type="button" className="ptr-button" onClick={close}>
              {t("tour.skip")}
            </button>
          )}
          <span className="asarak-tour-actions-spacer" />
          {!isFirst && (
            <button type="button" className="ptr-button" onClick={back}>
              {t("tour.back")}
            </button>
          )}
          <button
            type="button"
            className="ptr-button ptr-primary"
            onClick={next}
            autoFocus
          >
            {t(isFirst ? "tour.start" : isLast ? "tour.finish" : "tour.next")}
          </button>
        </div>
      </div>
    </div>
  );
}
