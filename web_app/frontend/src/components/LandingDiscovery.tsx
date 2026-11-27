"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  ArrowRight,
  ArrowUpRight,
  Baby,
  BadgeCheck,
  ChevronDown,
  ChevronUp,
  Clock,
  Dumbbell,
  HeartPulse,
  HelpCircle,
  Home,
  Laptop,
  LayoutGrid,
  PawPrint,
  Search,
  ShieldAlert,
  Shirt,
  ShoppingBasket,
  Sofa,
  Sparkles,
  Store,
  TrendingDown,
  X,
  type LucideIcon,
} from "lucide-react";
import type {
  CrossStoreMatch,
  FeedCategoryFilter,
  StatsOverview,
  VerdictFilter,
} from "@/types/contract";
import { getAllDealsCount, getAllHikesCount } from "@/lib/verdicts";
import {
  categoryLabels,
  productHref,
  visibleCategories,
} from "@/lib/browse-state";
import { formatDateTime, formatNumber, formatPctPlain, formatPrice } from "@/lib/format";
import { useLanguage } from "@/lib/i18n";
import { lowestAvailablePrice, sortOffers } from "@/lib/offers";
import { storeDisplayName } from "@/lib/stores";
import { ProductImage } from "./ProductImage";
import { StoreBadge } from "./StoreBadge";

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

const POPULAR_STORE_SLUGS: readonly string[] = [
  "amazon_eg",
  "noon",
  "btech",
  "2b",
  "sigma",
  "elaraby",
  "raneen",
  "rayashop",
  "spinneys",
  "hyperone",
  "seoudi",
  "breadfast",
  "lcwaikiki",
  "defacto",
];

function formatCompactCount(value: number, lang: "en" | "ar"): string {
  if (value >= 1000) {
    const k = Math.floor(value / 1000);
    return lang === "ar" ? `+${formatNumber(k, lang)} ألف` : `${formatNumber(k, lang)}K+`;
  }
  return formatNumber(value, lang);
}

/* ==========================================================================
   1. Actionable Shopper Deck + Live Trust Bar + Searchable Store Finder
   ========================================================================== */

export function ShopperActionDeck({
  stats,
  statsSource,
  checkedAt,
  activeVerdict,
  activeStore,
  drawerStores,
  storesOpen,
  onToggleStores,
  onSelectDrops,
  onSelectFake,
  onSelectStore,
}: {
  stats: StatsOverview;
  statsSource: "api" | "mock" | null;
  checkedAt: string | null;
  activeVerdict: VerdictFilter | "";
  activeStore: string;
  drawerStores: string[];
  storesOpen: boolean;
  onToggleStores: () => void;
  onSelectDrops: (verdict: VerdictFilter) => void;
  onSelectFake: (verdict: VerdictFilter) => void;
  onSelectStore: (storeSlug: string) => void;
}) {
  const { lang, dir, t } = useLanguage();
  const [storeQuery, setStoreQuery] = useState("");
  const ForwardArrow = dir === "rtl" ? ArrowLeft : ArrowRight;

  const dropsVerdict: VerdictFilter = "ALL_DEALS";
  const dropsCount = getAllDealsCount(stats);
  const dropsActive = activeVerdict === dropsVerdict;

  const fakeVerdict: VerdictFilter = "ALL_HIKES";
  const fakeCount = getAllHikesCount(stats);
  const fakeActive = activeVerdict === fakeVerdict;

  const storeCount = stats.available_stores.length;

  const popularStores = useMemo(() => {
    const availableSet = new Set(drawerStores);
    return POPULAR_STORE_SLUGS.filter((slug) => availableSet.has(slug));
  }, [drawerStores]);

  const normalizedStoreQuery = storeQuery.trim().toLowerCase();
  const filteredStores = useMemo(() => {
    if (!normalizedStoreQuery) return drawerStores;
    return drawerStores.filter((slug) => {
      const en = storeDisplayName(slug, "en").toLowerCase();
      const ar = storeDisplayName(slug, "ar").toLowerCase();
      return (
        slug.toLowerCase().includes(normalizedStoreQuery) ||
        en.includes(normalizedStoreQuery) ||
        ar.includes(normalizedStoreQuery)
      );
    });
  }, [drawerStores, normalizedStoreQuery]);

  return (
    <div className="asarak-intent-section" aria-label={t("intent.heading")}>
      <div className="asarak-intent-grid">
        {/* Card 1: Real Price Drops Today */}
        <button
          type="button"
          className="asarak-intent-card asarak-intent-card--emerald"
          aria-pressed={dropsActive}
          onClick={() => onSelectDrops(dropsVerdict)}
        >
          <div className="asarak-intent-card__top">
            <span className="asarak-intent-icon asarak-intent-icon--emerald" aria-hidden="true">
              <TrendingDown size={18} strokeWidth={2.2} />
            </span>
            <span className="asarak-intent-metric asarak-intent-metric--emerald">
              <bdi>{formatNumber(dropsCount, lang)}</bdi>
            </span>
          </div>
          <div className="asarak-intent-card__copy">
            <span className="asarak-intent-title">{t("intent.dropsTitle")}</span>
            <span className="asarak-intent-desc">{t("intent.dropsDesc")}</span>
          </div>
          <span className="asarak-intent-cta">
            <span>{t("intent.dropsCta")}</span>
            <ForwardArrow size={14} aria-hidden="true" />
          </span>
        </button>

        {/* Card 2: Current Fake Discounts */}
        <button
          type="button"
          className="asarak-intent-card asarak-intent-card--warning"
          aria-pressed={fakeActive}
          onClick={() => onSelectFake(fakeVerdict)}
        >
          <div className="asarak-intent-card__top">
            <span className="asarak-intent-icon asarak-intent-icon--warning" aria-hidden="true">
              <ShieldAlert size={18} strokeWidth={2.2} />
            </span>
            <span className="asarak-intent-metric asarak-intent-metric--warning">
              <bdi>{formatNumber(fakeCount, lang)}</bdi>
            </span>
          </div>
          <div className="asarak-intent-card__copy">
            <span className="asarak-intent-title">{t("intent.fakeTitle")}</span>
            <span className="asarak-intent-desc">{t("intent.fakeDesc")}</span>
          </div>
          <span className="asarak-intent-cta asarak-intent-cta--warning">
            <span>{t("intent.fakeCta")}</span>
            <ForwardArrow size={14} aria-hidden="true" />
          </span>
        </button>

        {/* Card 3: Searchable Egyptian Stores Directory */}
        <button
          type="button"
          className="asarak-intent-card"
          aria-expanded={storesOpen}
          onClick={onToggleStores}
        >
          <div className="asarak-intent-card__top">
            <span className="asarak-intent-icon" aria-hidden="true">
              <Store size={18} strokeWidth={2.2} />
            </span>
            <span className="asarak-intent-metric">
              <bdi>{formatNumber(storeCount, lang)}</bdi>
            </span>
          </div>
          <div className="asarak-intent-card__copy">
            <span className="asarak-intent-title">{t("intent.storesTitle")}</span>
            <span className="asarak-intent-desc">{t("intent.storesDesc")}</span>
          </div>
          <span className="asarak-intent-cta">
            <span>{storesOpen ? t("intent.storesHideCta") : t("intent.storesCta")}</span>
            {storesOpen ? (
              <ChevronUp size={14} aria-hidden="true" />
            ) : (
              <ChevronDown size={14} aria-hidden="true" />
            )}
          </span>
        </button>
      </div>

      {/* Live Trust Strip */}
      <div className="asarak-trust-strip">
        <span className="asarak-trust-item">
          <BadgeCheck size={14} aria-hidden="true" style={{ color: "var(--asarak-emerald)" }} />
          <span>
            {t("intent.trustTotal", {
              count: formatNumber(stats.total_tracked, lang),
            })}
          </span>
          {statsSource === "mock" && (
            <span className="ptr-badge">{t("ui.sample")}</span>
          )}
        </span>
        {checkedAt && (
          <span className="asarak-trust-item">
            <Clock size={13} aria-hidden="true" />
            <span>
              {t("intent.trustUpdated", {
                time: formatDateTime(checkedAt, lang),
              })}
            </span>
          </span>
        )}
      </div>

      {/* Searchable Store Finder Drawer */}
      {storesOpen && (
        <div className="asarak-store-drawer" role="region" aria-label={t("intent.storesTitle")}>
          <div className="asarak-store-drawer__head">
            <div className="asarak-store-search">
              <Search size={15} aria-hidden="true" className="shrink-0" />
              <input
                type="search"
                dir={storeQuery ? "auto" : undefined}
                value={storeQuery}
                onChange={(e) => setStoreQuery(e.target.value)}
                placeholder={t("intent.storeSearchPlaceholder", {
                  count: formatNumber(drawerStores.length, lang),
                })}
                aria-label={t("intent.storeSearchPlaceholder", {
                  count: formatNumber(drawerStores.length, lang),
                })}
              />
              {storeQuery && (
                <button
                  type="button"
                  className="ptr-icon-button !min-w-7 !min-h-7 !border-0 !bg-transparent"
                  onClick={() => setStoreQuery("")}
                  aria-label={t("search.clear")}
                >
                  <X size={14} aria-hidden="true" />
                </button>
              )}
            </div>
            <button
              type="button"
              className="ptr-chip"
              aria-pressed={activeStore === ""}
              onClick={() => onSelectStore("")}
            >
              {t("stores.allLabel")}
            </button>
          </div>

          {!normalizedStoreQuery && popularStores.length > 0 && (
            <div className="asarak-store-group">
              <p className="asarak-store-group__label">{t("intent.popularStores")}</p>
              <div className="ptr-controls">
                {popularStores.map((slug) => (
                  <button
                    key={`pop-${slug}`}
                    type="button"
                    className="ptr-chip"
                    aria-pressed={activeStore === slug}
                    onClick={() => onSelectStore(slug)}
                  >
                    {storeDisplayName(slug, lang)}
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className="asarak-store-group">
            <p className="asarak-store-group__label">
              {normalizedStoreQuery
                ? `${t("intent.allMatchingStores")} (${formatNumber(filteredStores.length, lang)})`
                : t("stores.stripLabel")}
            </p>
            {filteredStores.length === 0 ? (
              <p className="text-sm ptr-muted py-2">
                {t("intent.noStoresMatch", { query: storeQuery })}
              </p>
            ) : (
              <div className="ptr-controls ptr-stores-scroll">
                {filteredStores.map((slug) => (
                  <button
                    className="ptr-chip"
                    type="button"
                    key={slug}
                    aria-pressed={activeStore === slug}
                    onClick={() => onSelectStore(slug)}
                  >
                    {storeDisplayName(slug, lang)}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/* ==========================================================================
   2. Visual Category Launchpad (Icon-led discovery on default landing)
   ========================================================================== */

export function CategoryQuickGrid({
  categoryCounts,
  onSelectCategory,
}: {
  categoryCounts?: Record<string, number> | null;
  onSelectCategory: (category: FeedCategoryFilter) => void;
}) {
  const { lang, t } = useLanguage();
  const categories = visibleCategories(categoryCounts, "all").filter((c) => c !== "all");

  if (categories.length === 0) return null;

  return (
    <section className="asarak-landing-block" aria-labelledby="landing-categories-heading">
      <div className="asarak-block-head">
        <div>
          <h2 id="landing-categories-heading">{t("categories.heading")}</h2>
          <p className="ptr-muted text-sm">{t("categories.subtitle")}</p>
        </div>
      </div>

      <div className="asarak-cat-grid">
        {categories.map((cat) => {
          const Icon = CATEGORY_ICONS[cat] ?? LayoutGrid;
          const count = categoryCounts?.[cat];
          return (
            <button
              key={cat}
              type="button"
              className="asarak-cat-tile"
              onClick={() => onSelectCategory(cat)}
            >
              <span className="asarak-cat-tile__icon" aria-hidden="true">
                <Icon size={18} strokeWidth={2} />
              </span>
              <span className="asarak-cat-tile__copy">
                <span className="asarak-cat-tile__name">
                  {t(categoryLabels[cat] ?? "filters.catAll")}
                </span>
                {typeof count === "number" && count > 0 && (
                  <span className="asarak-cat-tile__count">
                    <bdi>{formatCompactCount(count, lang)}</bdi>
                  </span>
                )}
              </span>
            </button>
          );
        })}
      </div>
    </section>
  );
}

/* ==========================================================================
   3. Live Cross-Store Savings Spotlight (Immediate Proof of Value)
   ========================================================================== */

export function CrossStoreSpotlight({
  matches,
  totalMatches,
  loading,
  from,
  sample,
}: {
  matches: CrossStoreMatch[];
  totalMatches: number;
  loading: boolean;
  from: string;
  sample: boolean;
}) {
  const { lang, dir, t } = useLanguage();
  const ForwardArrow = dir === "rtl" ? ArrowLeft : ArrowRight;

  const diverseMatches = useMemo(() => {
    // Only highlight matches where at least 2 in-stock offers create a real buyable EGP saving
    const eligible = matches.filter((m) => {
      const inStockPrices = m.listings_json
        .filter((o) => o.in_stock && Number.isFinite(o.price) && o.price > 0)
        .map((o) => o.price);
      if (inStockPrices.length < 2) return false;
      const spread = Math.max(...inStockPrices) - Math.min(...inStockPrices);
      return spread >= 10;
    });
    const pool = eligible.length > 0 ? eligible : matches;
    const picked: CrossStoreMatch[] = [];
    const seenBrands = new Set<string>();
    const seenCategories = new Set<string>();

    // Pass 1: maximize both category & brand diversity
    for (const m of pool) {
      if (picked.length >= 3) break;
      const bKey = (m.brand || m.lowest_price_store || "").trim().toLowerCase();
      if (!seenCategories.has(m.category) && (!bKey || !seenBrands.has(bKey))) {
        picked.push(m);
        seenCategories.add(m.category);
        if (bKey) seenBrands.add(bKey);
      }
    }
    // Pass 2: maximize brand diversity
    for (const m of pool) {
      if (picked.length >= 3) break;
      if (picked.includes(m)) continue;
      const bKey = (m.brand || m.lowest_price_store || "").trim().toLowerCase();
      if (!bKey || !seenBrands.has(bKey)) {
        picked.push(m);
        if (bKey) seenBrands.add(bKey);
      }
    }
    // Pass 3: fill remaining slots
    for (const m of pool) {
      if (picked.length >= 3) break;
      if (!picked.includes(m)) picked.push(m);
    }
    return picked;
  }, [matches]);

  if (!loading && diverseMatches.length === 0) return null;

  return (
    <section className="asarak-landing-block" aria-labelledby="landing-spotlight-heading">
      <div className="asarak-block-head">
        <div>
          <p className="ptr-eyebrow !mb-1.5">{t("spotlight.overline")}</p>
          <h2 id="landing-spotlight-heading">{t("spotlight.title")}</h2>
          <p className="ptr-muted text-sm">{t("spotlight.subtitle")}</p>
        </div>
        <Link href="/compare" className="ptr-button shrink-0">
          <span>
            {totalMatches > 0
              ? t("spotlight.viewAll", { count: formatNumber(totalMatches, lang) })
              : t("nav.compare")}
          </span>
          <ForwardArrow size={15} aria-hidden="true" />
        </Link>
      </div>

      {loading ? (
        <div className="asarak-spotlight-grid" role="status">
          <span className="sr-only">{t("common.loading")}</span>
          {[0, 1, 2].map((item) => (
            <div key={item} className="surface p-4 space-y-3" aria-hidden="true">
              <div className="flex gap-3">
                <div className="skeleton size-16 rounded-xl shrink-0" />
                <div className="flex-1 space-y-2">
                  <div className="skeleton h-4 w-4/5" />
                  <div className="skeleton h-4 w-2/5" />
                </div>
              </div>
              <div className="skeleton h-10 w-full rounded-xl" />
            </div>
          ))}
        </div>
      ) : (
        <div className="asarak-spotlight-grid">
          {diverseMatches.map((match) => {
            const ordered = sortOffers(match.listings_json);
            const bestOffer = ordered.find((o) => o.in_stock) ?? ordered[0];
            const lowest = lowestAvailablePrice(ordered) ?? match.lowest_price;
            const inStockPrices = ordered
              .filter((o) => o.in_stock && o.price > 0)
              .map((o) => o.price);
            const highest =
              inStockPrices.length > 1
                ? Math.max(...inStockPrices)
                : match.highest_price;
            const savingEgp = Math.max(0, highest - lowest);
            const savingPct = highest > 0 ? (savingEgp / highest) * 100 : match.price_spread_pct;
            const href = bestOffer
              ? productHref(bestOffer.product_sk, from, sample)
              : "/compare";

            return (
              <Link
                key={match.canonical_product_key}
                href={href}
                className="surface asarak-spotlight-card group"
              >
                <div className="asarak-spotlight-card__head">
                  <ProductImage
                    src={match.image_url}
                    alt=""
                    category={match.category}
                    brand={match.brand}
                    className="asarak-spotlight-card__thumb"
                    fit={match.category === "fashion" ? "cover" : "contain"}
                    studio={match.category !== "fashion"}
                    zoomOnGroupHover
                  />
                  <div className="min-w-0 flex-1 space-y-1.5">
                    <div className="ptr-controls text-xs">
                      {savingEgp >= 1 && (
                        <span className="ptr-badge ptr-badge-good">
                          <Sparkles size={11} aria-hidden="true" />
                          <bdi>
                            {t("spotlight.save", {
                              amount: formatPrice(Math.round(savingEgp), lang),
                            })}
                          </bdi>
                        </span>
                      )}
                      <span className="ptr-badge">
                        {t("compare.storesCount", {
                          count: formatNumber(match.stores_count, lang),
                        })}
                      </span>
                    </div>
                    <h3 className="asarak-spotlight-card__title" dir="auto">
                      {match.product_title_clean}
                    </h3>
                  </div>
                </div>

                <div className="asarak-spotlight-card__prices">
                  <div className="min-w-0">
                    <div className="flex items-center gap-1.5 mb-1">
                      <StoreBadge
                        name={bestOffer?.store_name ?? match.lowest_price_store}
                        size="sm"
                      />
                      {savingPct >= 1 && (
                        <span
                          className="text-xs font-bold ptr-mono"
                          style={{ color: "var(--asarak-emerald-text)" }}
                        >
                          <bdi>-{formatPctPlain(savingPct, lang, 0)}</bdi>
                        </span>
                      )}
                    </div>
                    <p className="ptr-price asarak-spotlight-card__low">
                      <bdi>{formatPrice(lowest, lang)}</bdi>
                    </p>
                    {highest > lowest + 1 && (
                      <p className="text-xs ptr-muted">
                        {t("spotlight.vsHighest", {
                          price: formatPrice(highest, lang),
                        })}
                      </p>
                    )}
                  </div>
                  <span className="ptr-result-action shrink-0">
                    {t("spotlight.inspectOffer")}
                    <ArrowUpRight size={14} aria-hidden="true" />
                  </span>
                </div>
              </Link>
            );
          })}
        </div>
      )}
    </section>
  );
}

/* ==========================================================================
   4. Inline Collapsible Badge Guide (Right beside the catalog!)
   ========================================================================== */

export function InlineBadgeGuide() {
  const { t } = useLanguage();
  const [open, setOpen] = useState(false);

  return (
    <div className="asarak-badge-guide-wrap">
      <button
        type="button"
        className="asarak-badge-guide-toggle"
        aria-expanded={open}
        onClick={() => setOpen((prev) => !prev)}
      >
        <HelpCircle size={14} aria-hidden="true" />
        <span>{t(open ? "feed.badgeGuideClose" : "feed.badgeGuideToggle")}</span>
      </button>

      {open && (
        <div className="asarak-badge-guide surface" role="region" aria-label={t("verdict.legendToggle")}>
          <div className="asarak-badge-guide__item">
            <span className="ptr-badge ptr-badge-good">
              <BadgeCheck size={12} aria-hidden="true" />
              {t("market.cheapestBadge")}
            </span>
            <p className="text-xs ptr-muted">{t("feed.badgeGuideCheapest")}</p>
          </div>

          <div className="asarak-badge-guide__item">
            <span className="ptr-badge ptr-badge-good">
              <TrendingDown size={12} aria-hidden="true" />
              {t("verdict.RECENT_DROP")}
            </span>
            <p className="text-xs ptr-muted">{t("feed.badgeGuideDrop")}</p>
          </div>

          <div className="asarak-badge-guide__item">
            <span className="ptr-badge ptr-badge-amber">
              <ShieldAlert size={12} aria-hidden="true" />
              {t("deals.aboveMarketBadge")}
            </span>
            <p className="text-xs ptr-muted">{t("feed.badgeGuideReview")}</p>
          </div>

          <div className="asarak-badge-guide__item">
            <span className="ptr-badge">
              <Clock size={12} aria-hidden="true" />
              {t("verdict.NEWLY_TRACKED")}
            </span>
            <p className="text-xs ptr-muted">{t("feed.badgeGuideEarly")}</p>
          </div>
        </div>
      )}
    </div>
  );
}
