"use client";

/**
 * Production-grade interactive spotlight onboarding tour for Asarak (أسعارك).
 *
 * Architecture:
 * - Pure client-side, zero extra npm deps, zero API calls, hydration-safe.
 * - Full-viewport SVG `<mask>` cutout + animated emerald ring (zero 9999px shadow hacks).
 * - Sticky-header & mobile bottom-nav aware scrolling + rAF scroll sync +
 *   ResizeObserver + MutationObserver (for async ProductCard load).
 * - Desktop/Tablet floating popover with 4-way collision detection & directional caret;
 *   Mobile (<640px) sleek docked sheet that never covers the spotlighted target.
 * - Full keyboard navigation (Escape, RTL-aware ArrowLeft/ArrowRight), click-outside
 *   dismissal, `asarak_onboarding_v1_done` persistence, and `/?tour=1` replay cleanup.
 */

import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import {
  ArrowLeft,
  ArrowRight,
  BellRing,
  Check,
  Compass,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Tag,
  X,
  type LucideIcon,
} from "lucide-react";
import { setBrowseParams, useBrowseParams } from "@/lib/browse-state";
import { formatNumber } from "@/lib/format";
import { useLanguage } from "@/lib/i18n";
import type { TranslationKey } from "@/lib/translations";

const STORAGE_KEY = "asarak_onboarding_v1_done";
const DESKTOP_CARD_WIDTH = 380;
const CARD_GAP = 16;
const VIEWPORT_MARGIN = 14;

interface TourStep {
  id: string;
  /** CSS selectors tried in order; first visible match wins. Empty = centered hero card. */
  selectors: string[];
  icon: LucideIcon;
  title: TranslationKey;
  body: TranslationKey;
  /** True when target lives inside sticky/fixed chrome (.ptr-mast / .ptr-nav). */
  isChrome?: boolean;
  /** Observe `#radar-results` mutations so async ProductCard upgrades the fallback target. */
  observeFeed?: boolean;
}

const STEPS: readonly TourStep[] = [
  {
    id: "welcome",
    selectors: [],
    icon: Sparkles,
    title: "tour.welcome.title",
    body: "tour.welcome.body",
  },
  {
    id: "search",
    selectors: ['[data-tour="search"]'],
    icon: Search,
    title: "tour.search.title",
    body: "tour.search.body",
  },
  {
    id: "filters",
    selectors: ['[data-tour="filters"]'],
    icon: SlidersHorizontal,
    title: "tour.filters.title",
    body: "tour.filters.body",
  },
  {
    id: "deals",
    selectors: ['[data-tour="product-card"]', '[data-tour="deals"]'],
    icon: ShieldCheck,
    title: "tour.deals.title",
    body: "tour.deals.body",
    observeFeed: true,
  },
  {
    id: "nav",
    selectors: ['[data-tour="nav"]', '[data-tour="mast"]'],
    icon: Tag,
    title: "tour.nav.title",
    body: "tour.nav.body",
    isChrome: true,
  },
  {
    id: "alerts",
    selectors: ['[data-tour="tour-replay"]', '[data-tour="mast"]'],
    icon: BellRing,
    title: "tour.alerts.title",
    body: "tour.alerts.body",
    isChrome: true,
  },
];

interface SpotRect {
  top: number;
  left: number;
  width: number;
  height: number;
  bottom: number;
  right: number;
  radius: number;
  isBottomChrome: boolean;
  isTopChrome: boolean;
}

interface ChromeInsets {
  mastBottom: number;
  bottomNavHeight: number;
}

type CaretSide = "top" | "bottom" | "left" | "right" | null;

interface CardPlacement {
  className: string;
  style?: CSSProperties;
  caretSide: CaretSide;
  caretOffset: number;
}

function isVisible(el: HTMLElement): boolean {
  if (el.getClientRects().length === 0) return false;
  const style = window.getComputedStyle(el);
  if (style.display === "none" || style.visibility === "hidden" || style.opacity === "0") {
    return false;
  }
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

function getChromeInsets(): ChromeInsets {
  const mast = document.querySelector(".ptr-mast");
  const mastBottom =
    mast instanceof HTMLElement && isVisible(mast)
      ? Math.ceil(mast.getBoundingClientRect().bottom)
      : 68;

  const nav = document.querySelector(".ptr-nav");
  let bottomNavHeight = 0;
  if (nav instanceof HTMLElement && isVisible(nav)) {
    const style = window.getComputedStyle(nav);
    if (style.position === "fixed") {
      bottomNavHeight = Math.ceil(nav.getBoundingClientRect().height);
    }
  }
  return { mastBottom, bottomNavHeight };
}

function isFixedOrInMast(el: HTMLElement): boolean {
  if (el.closest(".ptr-mast")) return true;
  const pos = window.getComputedStyle(el).position;
  return pos === "fixed" || pos === "sticky";
}

function measureSpotlight(
  el: HTMLElement,
  step: TourStep,
  vw: number,
  vh: number,
  chrome: ChromeInsets,
  cardHeight: number,
): SpotRect | null {
  const r = el.getBoundingClientRect();
  if (r.width === 0 || r.height === 0) return null;

  const isMobile = vw < 640;
  const chromeTarget = Boolean(step.isChrome || isFixedOrInMast(el));
  const pad = chromeTarget ? 4 : 8;
  const radius = el.dataset.tour === "tour-replay" ? 11 : chromeTarget ? 12 : 14;

  const left = Math.max(4, r.left - pad);
  const right = Math.min(vw - 4, r.right + pad);
  const width = Math.max(24, right - left);

  const isBottomChrome = chromeTarget && r.top > vh - 140;
  const isTopChrome = chromeTarget && !isBottomChrome;

  let top = r.top - pad;
  let bottom = r.bottom + pad;

  if (chromeTarget) {
    top = Math.max(4, top);
    bottom = Math.min(vh - 4, bottom);
  } else {
    const minSafeTop = Math.max(4, chrome.mastBottom + 4);
    top = Math.max(minSafeTop, top);
    const maxHeight = isMobile
      ? Math.max(72, Math.min(340, vh - cardHeight - 28 - top))
      : Math.max(96, Math.min(420, vh - chrome.mastBottom - 120));
    bottom = Math.min(bottom, top + maxHeight, vh - 12);
    if (bottom - top < 44) {
      bottom = Math.min(vh - 12, top + 44);
    }
  }

  return {
    top,
    left,
    width,
    height: Math.max(32, bottom - top),
    bottom: Math.max(top + 32, bottom),
    right: left + width,
    radius,
    isBottomChrome,
    isTopChrome,
  };
}

function scrollTargetIntoSafeZone(
  el: HTMLElement,
  step: TourStep,
  vh: number,
  vw: number,
  chrome: ChromeInsets,
  cardHeight: number,
): void {
  if (step.isChrome || isFixedOrInMast(el)) return;

  const rect = el.getBoundingClientRect();
  const isMobile = vw < 640;
  const safeTop = chrome.mastBottom + 16;
  const safeBottom = isMobile ? vh - cardHeight - 28 : vh - 40;
  const safeHeight = Math.max(120, safeBottom - safeTop);

  // If element is already comfortably inside the safe zone, avoid jarring scroll.
  if (rect.top >= safeTop && rect.bottom <= safeBottom) return;

  const absTop = rect.top + window.scrollY;
  const extraOffset =
    rect.height < safeHeight ? Math.min(28, Math.floor((safeHeight - rect.height) / 3)) : 0;
  const desiredY = Math.max(0, Math.round(absTop - safeTop - extraOffset));

  if (Math.abs(window.scrollY - desiredY) <= 6) return;

  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  window.scrollTo({
    top: desiredY,
    behavior: reducedMotion ? "auto" : "smooth",
  });
}

function computePlacement(
  spot: SpotRect | null,
  vw: number,
  vh: number,
  chrome: ChromeInsets,
  cardHeight: number,
  dir: "rtl" | "ltr",
): CardPlacement {
  if (!spot) {
    return {
      className: "asarak-tour-card asarak-tour-card--centered",
      caretSide: null,
      caretOffset: 0,
    };
  }

  const isMobile = vw < 640;
  if (isMobile) {
    const sheetWidth = vw - 24;
    const targetCenterX = spot.left + spot.width / 2;
    const caretOffset = Math.min(
      Math.max(targetCenterX - 12, 24),
      Math.max(sheetWidth - 24, 24),
    );

    if (spot.isBottomChrome) {
      // Dock directly above the spotlighted mobile bottom tab bar — zero overlap, zero disconnect!
      const bottomGap = Math.max(vh - spot.top + 14, chrome.bottomNavHeight + 14);
      const maxBottom = Math.max(16, vh - chrome.mastBottom - cardHeight - 12);
      return {
        className: "asarak-tour-card asarak-tour-card--docked",
        style: { bottom: Math.min(bottomGap, maxBottom) },
        caretSide: "bottom",
        caretOffset,
      };
    }

    if (spot.isTopChrome) {
      // Dock directly below the header spotlight (e.g. Step 6 replay button)
      const top = Math.min(spot.bottom + 14, Math.max(chrome.mastBottom + 10, vh - cardHeight - 16));
      return {
        className: "asarak-tour-card asarak-tour-card--docked",
        style: { top },
        caretSide: "top",
        caretOffset,
      };
    }

    // Normal page-flow targets: attach directly below the spotlight when it fits
    // cleanly above the bottom nav; otherwise dock neatly at the bottom of the screen.
    const directBelowTop = spot.bottom + 14;
    const maxBottomY = vh - chrome.bottomNavHeight - 10;
    if (directBelowTop + cardHeight <= maxBottomY) {
      return {
        className: "asarak-tour-card asarak-tour-card--docked",
        style: { top: directBelowTop },
        caretSide: "top",
        caretOffset,
      };
    }

    return {
      className: "asarak-tour-card asarak-tour-card--docked asarak-tour-card--bottom",
      caretSide: "top",
      caretOffset,
    };
  }

  // Tablet (>= 640px) & Desktop (>= 1024px): smart 4-way collision detection
  const cardWidth = Math.min(DESKTOP_CARD_WIDTH, vw - 32);
  const safeTop = chrome.mastBottom + 12;
  const targetCenterX = spot.left + spot.width / 2;
  const targetCenterY = spot.top + spot.height / 2;

  const clampedLeft = Math.min(
    Math.max(targetCenterX - cardWidth / 2, VIEWPORT_MARGIN),
    Math.max(vw - cardWidth - VIEWPORT_MARGIN, VIEWPORT_MARGIN),
  );
  const clampedTopForSide = Math.min(
    Math.max(targetCenterY - cardHeight / 2, safeTop),
    Math.max(vh - cardHeight - VIEWPORT_MARGIN, safeTop),
  );

  // 1. Try below target
  const belowTop = spot.bottom + CARD_GAP;
  if (belowTop + cardHeight <= vh - VIEWPORT_MARGIN) {
    return {
      className: "asarak-tour-card",
      style: { top: belowTop, left: clampedLeft, width: cardWidth },
      caretSide: "top",
      caretOffset: Math.min(Math.max(targetCenterX - clampedLeft, 24), cardWidth - 24),
    };
  }

  // 2. Try above target
  const aboveTop = spot.top - CARD_GAP - cardHeight;
  if (aboveTop >= safeTop) {
    return {
      className: "asarak-tour-card",
      style: { top: aboveTop, left: clampedLeft, width: cardWidth },
      caretSide: "bottom",
      caretOffset: Math.min(Math.max(targetCenterX - clampedLeft, 24), cardWidth - 24),
    };
  }

  // 3. Try inline-end / inline-start sides
  const sideOrder: readonly ("right" | "left")[] =
    dir === "rtl" ? ["left", "right"] : ["right", "left"];

  for (const side of sideOrder) {
    if (side === "right" && spot.right + CARD_GAP + cardWidth <= vw - VIEWPORT_MARGIN) {
      const left = spot.right + CARD_GAP;
      return {
        className: "asarak-tour-card",
        style: { top: clampedTopForSide, left, width: cardWidth },
        caretSide: "left",
        caretOffset: Math.min(Math.max(targetCenterY - clampedTopForSide, 24), cardHeight - 24),
      };
    }
    if (side === "left" && spot.left - CARD_GAP - cardWidth >= VIEWPORT_MARGIN) {
      const left = spot.left - CARD_GAP - cardWidth;
      return {
        className: "asarak-tour-card",
        style: { top: clampedTopForSide, left, width: cardWidth },
        caretSide: "right",
        caretOffset: Math.min(Math.max(targetCenterY - clampedTopForSide, 24), cardHeight - 24),
      };
    }
  }

  // 4. Fallback: clamp safely near bottom of viewport
  const fallbackTop = Math.min(
    Math.max(vh - cardHeight - VIEWPORT_MARGIN, safeTop),
    Math.max(vh - cardHeight - VIEWPORT_MARGIN, VIEWPORT_MARGIN),
  );
  return {
    className: "asarak-tour-card",
    style: { top: fallbackTop, left: clampedLeft, width: cardWidth },
    caretSide: null,
    caretOffset: 0,
  };
}

function markDone(): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, "1");
  } catch {
    // Private browsing or blocked storage — fail gracefully.
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
  const rawId = useId();
  const maskId = `asarak-tour-mask-${rawId.replace(/[^a-zA-Z0-9_-]/g, "")}`;

  const [open, setOpen] = useState(false);
  const [stepIndex, setStepIndex] = useState(0);
  const [viewport, setViewport] = useState<{ w: number; h: number }>({ w: 0, h: 0 });
  const [chrome, setChrome] = useState<ChromeInsets>({ mastBottom: 68, bottomNavHeight: 0 });
  const [spot, setSpot] = useState<SpotRect | null>(null);
  const [cardHeight, setCardHeight] = useState(250);

  const cardRef = useRef<HTMLDivElement>(null);
  const cardHeightRef = useRef(250);
  const autoCheckedRef = useRef(false);

  useEffect(() => {
    cardHeightRef.current = cardHeight;
  }, [cardHeight]);

  const close = useCallback(() => {
    markDone();
    setOpen(false);
    setStepIndex(0);
    setSpot(null);
    if (new URLSearchParams(window.location.search).get("tour") === "1") {
      setBrowseParams({ tour: undefined }, true);
    }
  }, []);

  const goNext = useCallback(() => {
    setStepIndex((prev) => {
      if (prev >= STEPS.length - 1) {
        return prev;
      }
      return prev + 1;
    });
  }, []);

  const goBack = useCallback(() => {
    setStepIndex((prev) => Math.max(prev - 1, 0));
  }, []);

  /* Auto-open once on first visit to `/`, or immediately when forced via `/?tour=1`. */
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
    const id = window.setTimeout(() => setOpen(true), 650);
    return () => window.clearTimeout(id);
  }, [forced, open]);

  /* Reactive viewport dimensions (never read window.innerWidth non-reactively during render). */
  useEffect(() => {
    if (!open) return;
    const syncViewport = () => {
      const w = document.documentElement.clientWidth || window.innerWidth;
      const h = window.visualViewport?.height ? Math.round(window.visualViewport.height) : window.innerHeight;
      setViewport((prev) => (prev.w === w && prev.h === h ? prev : { w, h }));
      setChrome(getChromeInsets());
    };
    syncViewport();
    window.addEventListener("resize", syncViewport, { passive: true });
    window.addEventListener("orientationchange", syncViewport, { passive: true });
    window.visualViewport?.addEventListener("resize", syncViewport);
    return () => {
      window.removeEventListener("resize", syncViewport);
      window.removeEventListener("orientationchange", syncViewport);
      window.visualViewport?.removeEventListener("resize", syncViewport);
    };
  }, [open]);

  /* Track card's exact rendered height via ResizeObserver (avoids drift on language/step changes). */
  useEffect(() => {
    if (!open) return;
    const node = cardRef.current;
    if (!node) return;
    const updateHeight = () => {
      const h = Math.ceil(node.getBoundingClientRect().height);
      if (h > 0) {
        cardHeightRef.current = h;
        setCardHeight((prev) => (prev === h ? prev : h));
      }
    };
    updateHeight();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(updateHeight);
    ro.observe(node);
    return () => ro.disconnect();
  }, [open, stepIndex, lang]);

  /* Target tracking: exact offset scroll + rAF smooth-scroll lockstep + ResizeObserver + MutationObserver. */
  useEffect(() => {
    if (!open) return;
    const step = STEPS[stepIndex];
    cardRef.current?.focus({ preventScroll: true });

    if (step.selectors.length === 0) {
      setSpot(null);
      return;
    }

    let cancelled = false;
    let activeTarget: HTMLElement | null = null;
    let rafId = 0;
    let resizeObs: ResizeObserver | null = null;
    let mutationObs: MutationObserver | null = null;

    const measureAndSet = () => {
      if (cancelled) return;
      const vw = document.documentElement.clientWidth || window.innerWidth;
      const vh = window.visualViewport?.height ? Math.round(window.visualViewport.height) : window.innerHeight;
      const insets = getChromeInsets();
      setChrome((prev) =>
        prev.mastBottom === insets.mastBottom && prev.bottomNavHeight === insets.bottomNavHeight
          ? prev
          : insets,
      );

      const resolved = resolveTarget(step);
      if (resolved !== activeTarget) {
        resizeObs?.disconnect();
        activeTarget = resolved;
        if (resolved && typeof ResizeObserver !== "undefined") {
          resizeObs = new ResizeObserver(() => measureAndSet());
          resizeObs.observe(resolved);
        }
      }

      if (!activeTarget) {
        setSpot(null);
        return;
      }

      const nextSpot = measureSpotlight(
        activeTarget,
        step,
        vw,
        vh,
        insets,
        cardHeightRef.current,
      );
      setSpot(nextSpot);
    };

    const initialTarget = resolveTarget(step);
    if (initialTarget) {
      const vw = document.documentElement.clientWidth || window.innerWidth;
      const vh = window.visualViewport?.height ? Math.round(window.visualViewport.height) : window.innerHeight;
      const insets = getChromeInsets();
      scrollTargetIntoSafeZone(initialTarget, step, vh, vw, insets, cardHeightRef.current);
    }

    // Track smoothly every animation frame during smooth scroll (~620ms) so the spotlight never lags.
    const startedAt = performance.now();
    const tick = (now: number) => {
      measureAndSet();
      if (!cancelled && now - startedAt < 650) {
        rafId = window.requestAnimationFrame(tick);
      }
    };
    rafId = window.requestAnimationFrame(tick);

    const onScrollOrResize = () => {
      window.cancelAnimationFrame(rafId);
      rafId = window.requestAnimationFrame(measureAndSet);
    };
    window.addEventListener("scroll", onScrollOrResize, { passive: true, capture: true });
    window.addEventListener("resize", onScrollOrResize, { passive: true });

    if (step.observeFeed && typeof MutationObserver !== "undefined") {
      const feedRoot = document.getElementById("radar-results");
      if (feedRoot) {
        mutationObs = new MutationObserver(() => {
          const prevEl = activeTarget;
          const nextEl = resolveTarget(step);
          if (nextEl && nextEl !== prevEl) {
            const vw = document.documentElement.clientWidth || window.innerWidth;
            const vh = window.visualViewport?.height
              ? Math.round(window.visualViewport.height)
              : window.innerHeight;
            scrollTargetIntoSafeZone(nextEl, step, vh, vw, getChromeInsets(), cardHeightRef.current);
          }
          measureAndSet();
        });
        mutationObs.observe(feedRoot, { childList: true, subtree: true });
      }
    }

    return () => {
      cancelled = true;
      window.cancelAnimationFrame(rafId);
      resizeObs?.disconnect();
      mutationObs?.disconnect();
      window.removeEventListener("scroll", onScrollOrResize, true);
      window.removeEventListener("resize", onScrollOrResize);
    };
  }, [open, stepIndex]);

  /* Keyboard shortcuts: Escape closes; RTL-aware ArrowLeft / ArrowRight navigate steps. */
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        close();
        return;
      }
      if (event.key === "ArrowRight") {
        event.preventDefault();
        if (dir === "rtl") goBack();
        else if (stepIndex === STEPS.length - 1) close();
        else goNext();
      } else if (event.key === "ArrowLeft") {
        event.preventDefault();
        if (dir === "rtl") {
          if (stepIndex === STEPS.length - 1) close();
          else goNext();
        } else {
          goBack();
        }
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, dir, stepIndex, close, goNext, goBack]);

  const placement = useMemo(
    () =>
      viewport.w > 0 && viewport.h > 0
        ? computePlacement(spot, viewport.w, viewport.h, chrome, cardHeight, dir)
        : {
            className: "asarak-tour-card asarak-tour-card--centered",
            caretSide: null as CaretSide,
            caretOffset: 0,
          },
    [spot, viewport.w, viewport.h, chrome, cardHeight, dir],
  );

  if (!open || viewport.w === 0) return null;

  const step = STEPS[stepIndex];
  const StepIcon = step.icon;
  const isFirst = stepIndex === 0;
  const isLast = stepIndex === STEPS.length - 1;
  const progressPct = Math.round(((stepIndex + 1) / STEPS.length) * 100);
  const NextArrow = dir === "rtl" ? ArrowLeft : ArrowRight;
  const BackArrow = dir === "rtl" ? ArrowRight : ArrowLeft;

  const handleNext = () => {
    if (isLast) close();
    else goNext();
  };

  const caretStyle: CSSProperties | undefined =
    placement.caretSide === "top" || placement.caretSide === "bottom"
      ? { left: placement.caretOffset }
      : placement.caretSide === "left" || placement.caretSide === "right"
        ? { top: placement.caretOffset }
        : undefined;

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
      <svg
        className="asarak-tour-svg"
        width={viewport.w}
        height={viewport.h}
        viewBox={`0 0 ${viewport.w} ${viewport.h}`}
        aria-hidden="true"
      >
        <defs>
          <mask id={maskId}>
            <rect x="0" y="0" width={viewport.w} height={viewport.h} fill="white" />
            {spot && (
              <rect
                x={spot.left}
                y={spot.top}
                width={spot.width}
                height={spot.height}
                rx={spot.radius}
                ry={spot.radius}
                fill="black"
              />
            )}
          </mask>
        </defs>
        <rect
          x="0"
          y="0"
          width={viewport.w}
          height={viewport.h}
          className="asarak-tour-scrim"
          mask={`url(#${maskId})`}
        />
      </svg>

      {spot && (
        <div
          className="asarak-tour-ring"
          aria-hidden="true"
          style={{
            top: spot.top,
            left: spot.left,
            width: spot.width,
            height: spot.height,
            borderRadius: spot.radius,
          }}
        />
      )}

      <div
        ref={cardRef}
        key={step.id}
        className={placement.className}
        style={placement.style}
        role="dialog"
        aria-modal="true"
        aria-labelledby="asarak-tour-title"
        aria-describedby="asarak-tour-body"
        tabIndex={-1}
      >
        {placement.caretSide && (
          <span
            className={`asarak-tour-caret asarak-tour-caret--${placement.caretSide}`}
            style={caretStyle}
            aria-hidden="true"
          />
        )}

        <button
          type="button"
          className="asarak-tour-close"
          onClick={close}
          aria-label={t("ui.close")}
        >
          <X size={16} aria-hidden="true" />
        </button>

        <div className="asarak-tour-head">
          <span className="asarak-tour-icon-badge" aria-hidden="true">
            <StepIcon size={18} strokeWidth={2.2} />
          </span>
          <div className="min-w-0">
            <p className="asarak-tour-progress" role="status">
              {t("tour.stepOf", {
                current: formatNumber(stepIndex + 1, lang),
                total: formatNumber(STEPS.length, lang),
              })}
            </p>
            {isFirst && (
              <span className="asarak-tour-hero-pill">
                <Compass size={12} aria-hidden="true" />
                {t("tour.badge")}
              </span>
            )}
          </div>
        </div>

        <div
          className="asarak-tour-bar"
          role="progressbar"
          aria-valuenow={progressPct}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-hidden="true"
        >
          <span className="asarak-tour-bar-fill" style={{ width: `${progressPct}%` }} />
        </div>

        <h2 id="asarak-tour-title" className="asarak-tour-title">
          {t(step.title)}
        </h2>
        <p id="asarak-tour-body" className="asarak-tour-body">
          {t(step.body)}
        </p>

        <div className="asarak-tour-actions">
          {!isLast && (
            <button type="button" className="ptr-button asarak-tour-btn-skip" onClick={close}>
              {t("tour.skip")}
            </button>
          )}
          <span className="asarak-tour-actions-spacer" />
          {!isFirst && (
            <button type="button" className="ptr-button asarak-tour-btn-nav" onClick={goBack}>
              <BackArrow size={15} aria-hidden="true" />
              <span>{t("tour.back")}</span>
            </button>
          )}
          <button
            type="button"
            className="ptr-button ptr-primary asarak-tour-btn-nav"
            onClick={handleNext}
          >
            <span>{t(isFirst ? "tour.start" : isLast ? "tour.finish" : "tour.next")}</span>
            {isLast ? (
              <Check size={15} strokeWidth={2.5} aria-hidden="true" />
            ) : (
              <NextArrow size={15} aria-hidden="true" />
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
