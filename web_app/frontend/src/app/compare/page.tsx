"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  Baby,
  BadgeCheck,
  ChevronDown,
  ChevronUp,
  Dumbbell,
  ExternalLink,
  HeartPulse,
  Home,
  Laptop,
  LayoutGrid,
  PawPrint,
  Search,
  Shirt,
  ShoppingBasket,
  Sofa,
  Sparkles,
  Trophy,
  X,
  type LucideIcon,
} from "lucide-react";
import type {
  CompareResponse,
  CrossStoreMatch,
  FeedCategoryFilter,
} from "@/types/contract";
import { fetchCategories, fetchCompare, fetchProductDetail, type ApiResult } from "@/lib/api";
import { buildAffiliateUrl, outboundLinkRel } from "@/lib/affiliate";
import { trackStoreOutbound } from "@/lib/analytics";
import {
  browseHref,
  categoryLabelKey,
  categoryLabels,
  parseCategory,
  parsePage,
  productHref,
  setBrowseParams,
  useBrowseParams,
  visibleCategories,
} from "@/lib/browse-state";
import { formatNumber, formatPctPlain, formatPrice } from "@/lib/format";
import { useLanguage } from "@/lib/i18n";
import { lowestAvailablePrice, retailerHref, sortOffers } from "@/lib/offers";
import { storeDisplayName } from "@/lib/stores";
import { AdSlot } from "@/components/AdSlot";
import { CouponPill } from "@/components/CouponPill";
import { EditorialGuide } from "@/components/EditorialGuide";
import { MockBanner } from "@/components/MockBanner";
import { Pagination } from "@/components/Pagination";
import { ProductImage } from "@/components/ProductImage";
import { CompareCardSkeletons, ErrorState } from "@/components/states";
import { StoreBadge } from "@/components/StoreBadge";
import { VerdictBadge } from "@/components/VerdictBadge";

const PAGE_LIMIT = 10;
const SPREAD_OPTIONS = [0, 5, 10, 20];
const INITIAL_VISIBLE_STORES = 3;

// Cache hydrated compare match images across page/filter transitions so images
// never re-fetch when revisiting a page.
const matchImageCache = new Map<string, string | null>();

function useMatchImage(match: CrossStoreMatch, sample: boolean): string | null {
  const directImage = match.image_url?.trim() || null;
  const cached = matchImageCache.has(match.canonical_product_key)
    ? (matchImageCache.get(match.canonical_product_key) ?? null)
    : undefined;
  const [resolved, setResolved] = useState<string | null>(
    directImage ?? cached ?? null,
  );

  useEffect(() => {
    if (directImage) {
      matchImageCache.set(match.canonical_product_key, directImage);
      setResolved(directImage);
      return;
    }
    if (matchImageCache.has(match.canonical_product_key)) {
      setResolved(matchImageCache.get(match.canonical_product_key) ?? null);
      return;
    }
    if (sample || match.listings_json.length === 0) return;

    const controller = new AbortController();
    const candidates = sortOffers(match.listings_json).slice(0, 2);

    (async () => {
      for (const offer of candidates) {
        if (controller.signal.aborted) return;
        try {
          const detail = await fetchProductDetail(
            offer.product_sk,
            controller.signal,
            6000,
          );
          const url = detail.data.product.image_url?.trim() || null;
          if (url) {
            matchImageCache.set(match.canonical_product_key, url);
            if (!controller.signal.aborted) setResolved(url);
            return;
          }
        } catch {
          // Try next store listing if available
        }
      }
      if (!controller.signal.aborted) {
        matchImageCache.set(match.canonical_product_key, null);
      }
    })();

    return () => controller.abort();
  }, [directImage, match.canonical_product_key, match.listings_json, sample]);

  return directImage ?? resolved;
}

const CATEGORY_ICONS: Record<FeedCategoryFilter, LucideIcon> = {
  all: LayoutGrid,
  electronics: Laptop,
  home_appliances: Home,
  home_furniture: Sofa,
  fashion: Shirt,
  beauty: Sparkles,
  groceries: ShoppingBasket,
  health: HeartPulse,
  sports: Dumbbell,
  pet_care: PawPrint,
  baby_kids: Baby,
};

function computeInStockSaving(match: CrossStoreMatch): {
  lowestInStock: number | null;
  highestInStock: number | null;
  inStockGapEgp: number;
  inStockGapPct: number;
  winnerStore: string | null;
} {
  const inStock = match.listings_json.filter(
    (offer) => offer.in_stock && Number.isFinite(offer.price) && offer.price > 0,
  );
  if (inStock.length === 0) {
    return {
      lowestInStock: null,
      highestInStock: null,
      inStockGapEgp: 0,
      inStockGapPct: 0,
      winnerStore: null,
    };
  }
  const sorted = [...inStock].sort((a, b) => a.price - b.price);
  const low = sorted[0];
  const high = sorted[sorted.length - 1];
  const gap = Math.max(0, high.price - low.price);
  const pct = low.price > 0 ? (gap / low.price) * 100 : 0;
  return {
    lowestInStock: low.price,
    highestInStock: high.price,
    inStockGapEgp: gap,
    inStockGapPct: pct,
    winnerStore: low.store_name,
  };
}

function ArenaMatchCard({
  match,
  from,
  featured,
  sample,
}: {
  match: CrossStoreMatch;
  from: string;
  featured: boolean;
  sample: boolean;
}) {
  const { lang, t } = useLanguage();
  const [expanded, setExpanded] = useState(featured);

  const ordered = useMemo(
    () => sortOffers(match.listings_json),
    [match.listings_json],
  );
  const lowestAvailable = lowestAvailablePrice(ordered);
  const maxPrice = ordered.reduce(
    (highest, offer) =>
      Number.isFinite(offer.price) ? Math.max(highest, offer.price) : highest,
    0,
  );
  const { inStockGapEgp, inStockGapPct, winnerStore } =
    computeInStockSaving(match);
  const catKey = categoryLabelKey(match.category);
  const imageUrl = useMatchImage(match, sample);

  const primaryOffer = ordered[0];
  const visibleOffers = expanded
    ? ordered
    : ordered.slice(0, INITIAL_VISIBLE_STORES);
  const hiddenCount = Math.max(0, ordered.length - INITIAL_VISIBLE_STORES);

  const savingAmount =
    inStockGapEgp >= 1 ? inStockGapEgp : match.price_spread_egp;
  const savingPct =
    inStockGapEgp >= 1 ? inStockGapPct : match.price_spread_pct;
  const showSavingBadge = savingAmount >= 1;

  return (
    <article
      className={`surface asarak-arena-card ${
        featured ? "asarak-arena-card--featured" : ""
      }`}
    >
      <header className="asarak-arena-head">
        <div className="asarak-arena-identity">
          <ProductImage
            src={imageUrl}
            alt=""
            category={match.category}
            brand={match.brand}
            className="asarak-arena-thumb"
            fit={match.category === "fashion" ? "cover" : "contain"}
            studio={match.category !== "fashion"}
            priority={featured}
          />
          <div className="min-w-0 space-y-1.5">
            <div className="ptr-controls text-xs">
              {featured && (
                <span className="ptr-badge ptr-badge-good">
                  <Trophy size={12} aria-hidden="true" />
                  {t("compare.topSavingBadge")}
                </span>
              )}
              {match.brand && match.brand.toLowerCase() !== "other" && (
                <span className="ptr-badge">{match.brand}</span>
              )}
              {catKey && <span className="ptr-badge">{t(catKey)}</span>}
              <span className="ptr-badge ptr-badge-variant">
                {t("compare.storesCount", {
                  count: formatNumber(match.stores_count, lang),
                })}
              </span>
            </div>

            <h2 className="asarak-arena-title">
              {primaryOffer ? (
                <Link href={productHref(primaryOffer.product_sk, from, sample)}>
                  <bdi>{match.product_title_clean}</bdi>
                </Link>
              ) : (
                <bdi>{match.product_title_clean}</bdi>
              )}
            </h2>

            <p className="asarak-arena-range">
              {t("ui.trackedRange")} ·{" "}
              <bdi className="ptr-mono">
                {formatPrice(match.lowest_price, lang)} –{" "}
                {formatPrice(match.highest_price, lang)}
              </bdi>
            </p>
          </div>
        </div>

        <div className="asarak-arena-summary">
          <span className="text-xs font-semibold ptr-muted">
            {winnerStore
              ? `${t("compare.bestInStock")} · ${storeDisplayName(winnerStore, lang)}`
              : t("ui.lowestAvailable")}
          </span>
          <p className="asarak-arena-best-price">
            {lowestAvailable === null ? (
              <span className="text-base ptr-muted">{t("ui.noAvailable")}</span>
            ) : (
              <bdi>{formatPrice(lowestAvailable, lang)}</bdi>
            )}
          </p>
          {showSavingBadge && (
            <span className="ptr-badge ptr-badge-good">
              <Sparkles size={11} aria-hidden="true" />
              <bdi>
                {t("spotlight.save", {
                  amount: formatPrice(savingAmount, lang),
                })}{" "}
                ({formatPctPlain(savingPct, lang)})
              </bdi>
            </span>
          )}
        </div>
      </header>

      <ul className="asarak-bar-ladder">
        {visibleOffers.map((offer) => {
          const isWinner =
            offer.in_stock &&
            lowestAvailable !== null &&
            offer.price === lowestAvailable;
          const delta =
            offer.in_stock && lowestAvailable !== null
              ? offer.price - lowestAvailable
              : null;
          const ratio =
            maxPrice > 0 ? Math.min(100, Math.max(20, (offer.price / maxPrice) * 100)) : 100;
          const safeUrl = retailerHref(offer.product_url);
          const storeLink = safeUrl
            ? buildAffiliateUrl(safeUrl, offer.store_name)
            : null;

          return (
            <li
              key={offer.product_sk}
              className={`asarak-bar-row ${
                isWinner
                  ? "asarak-bar-row--winner"
                  : !offer.in_stock
                    ? "asarak-bar-row--oos"
                    : ""
              }`}
            >
              {/* Col 1: Store & Stock */}
              <div className="min-w-0 space-y-1">
                <StoreBadge name={offer.store_name} size="sm" />
                <p className="ptr-stock-pill text-xs">
                  <span
                    className={`ptr-stock-dot ${
                      offer.in_stock ? "" : "ptr-stock-dot--oos"
                    }`}
                    aria-hidden="true"
                  />
                  {t(offer.in_stock ? "detail.inStock" : "card.outOfStock")}
                </p>
              </div>

              {/* Col 2: Visual Proportional Price Bar */}
              <div className="asarak-bar-cell">
                <div className="asarak-bar-track" aria-hidden="true">
                  <div
                    className={`asarak-bar-fill ${
                      isWinner
                        ? "asarak-bar-fill--winner"
                        : !offer.in_stock
                          ? "asarak-bar-fill--oos"
                          : ""
                    }`}
                    style={{ width: `${ratio.toFixed(1)}%` }}
                  />
                </div>
                <div className="asarak-bar-meta">
                  {isWinner ? (
                    <span
                      className="inline-flex items-center gap-1 font-bold"
                      style={{ color: "var(--asarak-verified-ink)" }}
                    >
                      <BadgeCheck size={13} aria-hidden="true" />
                      {t("ui.lowestAvailable")}
                    </span>
                  ) : delta !== null && delta > 0 ? (
                    <span className="ptr-muted ptr-mono">
                      {t("compare.aboveLowest", {
                        amount: formatPrice(delta, lang),
                      })}
                    </span>
                  ) : (
                    <span className="ptr-muted">{t("card.outOfStock")}</span>
                  )}
                  {offer.discount_verdict && offer.discount_verdict !== "NORMAL_PRICE" && (
                    <VerdictBadge verdict={offer.discount_verdict} size="sm" />
                  )}
                </div>
              </div>

              {/* Col 3: Price + Unit Price + Coupon Estimate */}
              <div className="min-w-0 space-y-0.5">
                <p className="ptr-price">
                  <bdi>{formatPrice(offer.price, lang)}</bdi>
                </p>
                <CouponPill
                  coupons={offer.applicable_coupons}
                  estimatedPrice={offer.estimated_price_after_coupon}
                  compact
                />
                {offer.unit_price_egp != null && offer.unit_price_unit && (
                  <p className="text-xs ptr-muted ptr-mono">
                    <bdi>
                      {formatPrice(offer.unit_price_egp, lang)} /{" "}
                      {offer.unit_price_unit}
                    </bdi>
                  </p>
                )}
              </div>

              {/* Col 4: Actions */}
              <div className="ptr-controls">
                <Link
                  className="ptr-button ptr-small-button"
                  href={productHref(offer.product_sk, from, sample)}
                >
                  {t("detail.viewLocal")}
                </Link>
                {!sample && storeLink && offer.in_stock && (
                  <a
                    className={`ptr-button ptr-small-button ${
                      isWinner ? "ptr-primary" : ""
                    }`}
                    href={storeLink.url}
                    target="_blank"
                    rel={outboundLinkRel(storeLink.isAffiliate)}
                    onClick={() =>
                      trackStoreOutbound({
                        store: offer.store_name,
                        product_id: offer.product_sk,
                        price: offer.price,
                        category: match.category,
                        is_affiliate: storeLink.isAffiliate,
                        network: storeLink.network,
                        placement: "alternatives_table",
                      })
                    }
                    aria-label={t("detail.openAtStore", {
                      store: storeDisplayName(offer.store_name, lang),
                    })}
                  >
                    {t("detail.openAtStoreGeneric")}{" "}
                    <ExternalLink size={13} aria-hidden="true" />
                  </a>
                )}
              </div>
            </li>
          );
        })}
      </ul>

      {hiddenCount > 0 && (
        <button
          type="button"
          className="asarak-arena-toggle"
          aria-expanded={expanded}
          onClick={() => setExpanded((prev) => !prev)}
        >
          {expanded ? (
            <>
              <ChevronUp size={15} aria-hidden="true" />
              <span>{t("compare.fewerOffers")}</span>
            </>
          ) : (
            <>
              <ChevronDown size={15} aria-hidden="true" />
              <span>
                {t("compare.moreOffers", {
                  count: formatNumber(hiddenCount, lang),
                })}
              </span>
            </>
          )}
        </button>
      )}
    </article>
  );
}

export default function ComparePage() {
  const { lang, t } = useLanguage();
  const search = useBrowseParams();
  const category = parseCategory(search.get("category"));
  const page = parsePage(search.get("page"));
  const spread =
    SPREAD_OPTIONS.find((option) => option === Number(search.get("gap"))) ?? 0;
  const key = `${category}:${page}:${spread}`;
  const [result, setResult] = useState<{
    key: string;
    value: ApiResult<CompareResponse>;
  } | null>(null);
  const [compareCounts, setCompareCounts] = useState<Record<
    string,
    number
  > | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [quickFilter, setQuickFilter] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    fetchCategories(controller.signal)
      .then((res) => {
        if (controller.signal.aborted) return;
        const counts: Record<string, number> = {};
        for (const item of res.data.items) {
          if (item.compare_count > 0) counts[item.slug] = item.compare_count;
        }
        if (Object.keys(counts).length > 0) setCompareCounts(counts);
      })
      .catch(() => {});
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setFailed(null);
    fetchCompare(
      { category, min_spread_pct: spread, page, limit: PAGE_LIMIT },
      controller.signal,
    )
      .then((value) => {
        if (!controller.signal.aborted) setResult({ key, value });
      })
      .catch(() => {
        if (!controller.signal.aborted) setFailed(key);
      });
    return () => controller.abort();
  }, [key, category, spread, page, attempt]);

  const current = result?.key === key ? result.value : null;
  const shownCategories = visibleCategories(compareCounts, category);
  const loading = !current && failed !== key;
  const totalPages = Math.max(
    1,
    Math.ceil((current?.data.total ?? 0) / (current?.data.limit ?? PAGE_LIMIT)),
  );
  const from = browseHref("/compare", search);

  const normalizedFilter = quickFilter.trim().toLowerCase();
  const visibleMatches = useMemo(() => {
    const items = current?.data.items ?? [];
    if (!normalizedFilter) return items;
    return items.filter((match) => {
      if (match.product_title_clean.toLowerCase().includes(normalizedFilter))
        return true;
      if (match.brand?.toLowerCase().includes(normalizedFilter)) return true;
      return match.listings_json.some((offer) => {
        const displayEn = storeDisplayName(offer.store_name, "en").toLowerCase();
        const displayAr = storeDisplayName(offer.store_name, "ar").toLowerCase();
        return (
          offer.store_name.toLowerCase().includes(normalizedFilter) ||
          displayEn.includes(normalizedFilter) ||
          displayAr.includes(normalizedFilter)
        );
      });
    });
  }, [current?.data.items, normalizedFilter]);

  const pageStats = useMemo(() => {
    const items = current?.data.items ?? [];
    if (items.length === 0) return null;
    let topSaving = 0;
    let totalStores = 0;
    for (const item of items) {
      const { inStockGapEgp } = computeInStockSaving(item);
      const effectiveSaving =
        inStockGapEgp >= 1 ? inStockGapEgp : item.price_spread_egp;
      if (effectiveSaving > topSaving) topSaving = effectiveSaving;
      totalStores += item.stores_count;
    }
    return {
      topSaving,
      avgStores: (totalStores / items.length).toFixed(1),
    };
  }, [current?.data.items]);

  return (
    <>
      <section className="asarak-compare-hero">
        <div className="ptr-wrap asarak-compare-hero__inner">
          <div className="min-w-0">
            <p className="ptr-eyebrow">{t("spotlight.overline")}</p>
            <h1>{t("compare.title")}</h1>
            <p className="ptr-muted">{t("compare.subtitle")}</p>
          </div>

          <div className="asarak-compare-stats">
            <div className="asarak-compare-stat">
              <span className="asarak-compare-stat__value">
                <bdi>
                  {current ? formatNumber(current.data.total, lang) : "—"}
                </bdi>
              </span>
              <span className="asarak-compare-stat__label">
                {t("compare.statMatches")}
              </span>
            </div>

            <div className="asarak-compare-stat">
              <span className="asarak-compare-stat__value asarak-compare-stat__value--emerald">
                <bdi>
                  {pageStats && pageStats.topSaving > 0
                    ? formatPrice(pageStats.topSaving, lang)
                    : "—"}
                </bdi>
              </span>
              <span className="asarak-compare-stat__label">
                {t("compare.statTopSpread")}
              </span>
            </div>

            <div className="asarak-compare-stat">
              <span className="asarak-compare-stat__value">
                <bdi>{pageStats ? pageStats.avgStores : "—"}</bdi>
              </span>
              <span className="asarak-compare-stat__label">
                {t("compare.statAvgStores")}
              </span>
            </div>
          </div>
        </div>
      </section>

      <div className="ptr-wrap ptr-page">
        <div className="surface asarak-compare-deck">
          <div
            className="ptr-category-bar"
            role="group"
            aria-label={t("filters.category")}
          >
            {shownCategories.map((value) => {
              const catCount = value === "all" ? null : compareCounts?.[value];
              const Icon = CATEGORY_ICONS[value] ?? LayoutGrid;
              return (
                <button
                  key={value}
                  className="ptr-chip"
                  type="button"
                  aria-pressed={category === value}
                  onClick={() =>
                    setBrowseParams({
                      category: value === "all" ? undefined : value,
                      page: undefined,
                    })
                  }
                >
                  <Icon size={14} aria-hidden="true" />
                  <span>{t(categoryLabels[value] ?? "filters.catAll")}</span>
                  {typeof catCount === "number" && catCount > 0 && (
                    <span className="ptr-chip-count">
                      <bdi>{formatNumber(catCount, lang)}</bdi>
                    </span>
                  )}
                </button>
              );
            })}
          </div>

          <div className="asarak-compare-deck__row">
            <div className="flex flex-wrap items-center gap-2">
              <span className="ptr-control-label">{t("compare.minSpread")}</span>
              <div
                className="asarak-segmented"
                role="group"
                aria-label={t("compare.minSpread")}
              >
                {SPREAD_OPTIONS.map((option) => (
                  <button
                    key={option}
                    type="button"
                    aria-pressed={spread === option}
                    onClick={() =>
                      setBrowseParams({
                        gap: option || undefined,
                        page: undefined,
                      })
                    }
                  >
                    {option
                      ? `≥ ${formatPctPlain(option, lang, 0)}`
                      : t("compare.spreadAny")}
                  </button>
                ))}
              </div>
            </div>

            <div className="asarak-compare-filter">
              <Search size={15} aria-hidden="true" className="shrink-0" />
              <input
                type="search"
                dir={quickFilter ? "auto" : undefined}
                value={quickFilter}
                onChange={(event) => setQuickFilter(event.target.value)}
                placeholder={t("compare.filterPlaceholder")}
                aria-label={t("compare.filterPlaceholder")}
              />
              {quickFilter && (
                <button
                  type="button"
                  className="ptr-icon-button !min-w-7 !min-h-7 !border-0 !bg-transparent"
                  onClick={() => setQuickFilter("")}
                  aria-label={t("compare.clearFilter")}
                >
                  <X size={14} aria-hidden="true" />
                </button>
              )}
            </div>
          </div>
        </div>

        {(category !== "all" || spread !== 0 || page !== 1 || quickFilter) && (
          <button
            className="ptr-link w-fit text-sm"
            type="button"
            onClick={() => {
              setQuickFilter("");
              setBrowseParams({
                category: undefined,
                gap: undefined,
                page: undefined,
              });
            }}
          >
            {t("filters.reset")}
          </button>
        )}

        <MockBanner
          source={current?.source ?? null}
          onRetry={() => setAttempt((value) => value + 1)}
        />
        {failed === key && (
          <ErrorState onRetry={() => setAttempt((value) => value + 1)} />
        )}

        <section
          aria-busy={loading}
          className="min-w-0 space-y-4"
          id="compare-results"
        >
          {loading && (
            <div role="status">
              <span className="sr-only">{t("common.loading")}</span>
              <CompareCardSkeletons />
            </div>
          )}

          {current && (
            <div className="ptr-toolbar">
              <p className="text-sm ptr-muted" role="status">
                {t("filters.showing", {
                  total: formatNumber(current.data.total, lang),
                })}
              </p>
            </div>
          )}

          {current && current.data.items.length === 0 && (
            <div className="surface p-6 space-y-1">
              <p className="font-semibold">{t("compare.empty")}</p>
              <p className="ptr-muted text-sm">{t("compare.emptyHint")}</p>
            </div>
          )}

          {current &&
            current.data.items.length > 0 &&
            visibleMatches.length === 0 && (
              <div className="surface ptr-empty">
                <p className="font-semibold">
                  {t("compare.filterEmpty", { query: quickFilter })}
                </p>
                <button
                  type="button"
                  className="ptr-button"
                  onClick={() => setQuickFilter("")}
                >
                  {t("compare.clearFilter")}
                </button>
              </div>
            )}

          {current && visibleMatches.length > 0 && (
            <div className="asarak-arena-list">
              {visibleMatches.map((match, index) => (
                <ArenaMatchCard
                  key={match.canonical_product_key}
                  match={match}
                  featured={page === 1 && index === 0 && !normalizedFilter}
                  from={from}
                  sample={current.source === "mock"}
                />
              ))}
            </div>
          )}

          {current && (
            <Pagination
              page={page}
              totalPages={totalPages}
              onPage={(next) => {
                setQuickFilter("");
                setBrowseParams({ page: next > 1 ? next : undefined });
                document
                  .getElementById("compare-results")
                  ?.scrollIntoView({ block: "start", behavior: "smooth" });
              }}
            />
          )}
        </section>

        <AdSlot
          slot={process.env.NEXT_PUBLIC_ADSENSE_SLOT_COMPARE}
          format="auto"
          minHeight={100}
        />
        <EditorialGuide variant="compare" />
      </div>
    </>
  );
}
