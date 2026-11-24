"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowUpRight, BadgeCheck, ShieldAlert } from "lucide-react";
import { fetchRadarHighlights, fetchStatsOverview, type HighlightsView } from "@/lib/api";
import {
  browseHref,
  categoryLabelKey,
  categoryLabels,
  parseCategory,
  productHref,
  setBrowseParams,
  useBrowseParams,
  visibleCategories,
} from "@/lib/browse-state";
import { formatDateTime, formatNumber, formatPctPlain, formatPrice } from "@/lib/format";
import { isStaleObservation, type PriceHighlight } from "@/lib/highlights";
import { useLanguage } from "@/lib/i18n";
import { absoluteUrl } from "@/lib/site";
import { AdSlot } from "@/components/AdSlot";
import { EditorialGuide } from "@/components/EditorialGuide";
import { MockBanner } from "@/components/MockBanner";
import { ProductImage } from "@/components/ProductImage";
import { ShareButton } from "@/components/ShareButton";
import { StoreBadge } from "@/components/StoreBadge";
import { ErrorState } from "@/components/states";

function HighlightCard({
  item,
  warning,
  from,
  live,
  canSharePrice,
}: {
  item: PriceHighlight;
  warning: boolean;
  from: string;
  live: boolean;
  canSharePrice: boolean;
}) {
  const { lang, t } = useLanguage();
  const title = item.title ?? t("deals.unknownTitle");
  const category = parseCategory(item.category);
  const href = item.id ? productHref(item.id, from, !live) : null;
  const savings = item.observedSavings;
  const takeaway =
    savings === null
      ? null
      : Math.abs(savings) < 0.05
        ? t("ui.same")
        : t(savings > 0 ? "ui.below" : "ui.above", {
            pct: formatPctPlain(Math.abs(savings), lang),
          });
  const hasPriceRange =
    item.hasMultipleVariants &&
    item.minVariantPrice !== null &&
    item.maxVariantPrice !== null &&
    item.maxVariantPrice > item.minVariantPrice + 0.01;
  const displayPrice =
    hasPriceRange && item.minVariantPrice !== null
      ? t("variant.fromPrice", { price: formatPrice(item.minVariantPrice, lang) })
      : item.price === null
        ? null
        : formatPrice(item.price, lang);

  return (
    <article
      className={`surface ptr-highlight ${warning ? "ptr-highlight--warning" : ""}`}
    >
      <ProductImage
        src={item.image}
        alt=""
        category={category === "all" ? "electronics" : category}
        fit="contain"
        className="ptr-thumbnail"
        studio
      />
      <div className="min-w-0 space-y-2">
        <div className="ptr-controls text-xs ptr-muted">
          {item.store && <StoreBadge name={item.store} size="sm" />}
          {categoryLabelKey(item.category) && (
            <span className="ptr-badge">{t(categoryLabelKey(item.category)!)}</span>
          )}
          {item.hasMultipleVariants && (
            <span className="ptr-badge ptr-badge-variant">
              <bdi>
                {t(
                  item.variantCount >= 11
                    ? "variant.optionsCountMany"
                    : "variant.optionsCount",
                  { count: formatNumber(item.variantCount, lang) },
                )}
              </bdi>
            </span>
          )}
        </div>
        <h2 className="text-base font-bold leading-snug">
          {href ? (
            <Link href={href}>
              <bdi>{title}</bdi>
            </Link>
          ) : (
            <bdi>{title}</bdi>
          )}
        </h2>
        <span
          className={`ptr-badge ${warning ? "ptr-badge-warning" : "ptr-badge-good"}`}
        >
          {warning ? (
            <ShieldAlert size={13} aria-hidden="true" />
          ) : (
            <BadgeCheck size={13} aria-hidden="true" />
          )}
          {t(
            item.priceHike
              ? "verdict.PRESALE_HIKE"
              : warning
                ? "deals.scandalBadge"
                : "deals.dealBadge",
          )}
        </span>
        {takeaway && <p className="text-sm font-medium">{takeaway}</p>}
        {warning && item.advertisedSavings !== null && (
          <p className="text-sm ptr-muted">
            {t("deals.advertised", {
              pct: formatPctPlain(item.advertisedSavings, lang),
            })}
          </p>
        )}
      </div>
      <dl className="ptr-highlight-prices">
        {displayPrice && (
          <div>
            <dt>{t("detail.current")}</dt>
            <dd className="ptr-price">
              <bdi>{displayPrice}</bdi>
            </dd>
            {hasPriceRange &&
              item.minVariantPrice !== null &&
              item.maxVariantPrice !== null && (
                <p className="text-xs ptr-muted ptr-variant-range">
                  <bdi>
                    {t("variant.priceRange", {
                      min: formatPrice(item.minVariantPrice, lang),
                      max: formatPrice(item.maxVariantPrice, lang),
                    })}
                  </bdi>
                </p>
              )}
          </div>
        )}
        {item.baseline !== null && (
          <div>
            <dt>{t("deals.baselinePrice")}</dt>
            <dd>
              <bdi>{formatPrice(item.baseline, lang)}</bdi>
            </dd>
          </div>
        )}
        {warning && item.advertisedPrice !== null && (
          <div>
            <dt>{t("deals.claimedPrice")}</dt>
            <dd className="ptr-strike">
              <bdi>{formatPrice(item.advertisedPrice, lang)}</bdi>
            </dd>
          </div>
        )}
      </dl>
      <div className="ptr-highlight-actions">
        <Link className="ptr-button ptr-primary" href={href ?? "/"}>
          {t(href ? "deals.viewTruth" : "nav.feed")}{" "}
          <ArrowUpRight size={15} aria-hidden="true" />
        </Link>
        {item.id && live && (
          <ShareButton
            title={title}
            url={absoluteUrl(productHref(item.id))}
            text={
              canSharePrice && displayPrice
                ? [title, displayPrice, takeaway].filter(Boolean).join(" · ")
                : undefined
            }
          />
        )}
      </div>
    </article>
  );
}

export default function DealsPage() {
  const { lang, t } = useLanguage();
  const params = useBrowseParams();
  const category = parseCategory(params.get("category"));
  const tab = params.get("tab") === "scandals" ? "scandals" : "deals";
  const [data, setData] = useState<{
    category: typeof category;
    value: HighlightsView;
  } | null>(null);
  const [categoryCounts, setCategoryCounts] = useState<Record<
    string,
    number
  > | null>(null);
  const [error, setError] = useState<false | typeof category>(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    fetchStatsOverview(controller.signal)
      .then((res) => {
        if (!controller.signal.aborted && res.data.category_counts) {
          setCategoryCounts(res.data.category_counts);
        }
      })
      .catch(() => {});
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setError(false);
    fetchRadarHighlights(category, 24, controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) setData({ category, value });
      })
      .catch(() => {
        if (!controller.signal.aborted) setError(category);
      });
    return () => controller.abort();
  }, [category, attempt]);

  const shownCategories = visibleCategories(categoryCounts, category);

  const current = data?.category === category ? data.value : null;
  const bucket = current?.[tab];
  const items = bucket?.items ?? [];
  const checked = items.length ? bucket?.updatedAt : null;
  const stale = isStaleObservation(checked);
  const failed = error === category || (current !== null && !bucket);
  const loading = !current && !failed;
  const from = browseHref("/deals", params);

  return (
    <div className="ptr-wrap ptr-page">
      <header className="ptr-page-heading">
        <p className="ptr-eyebrow">{t("hero.overline")}</p>
        <h1>{t("deals.title")}</h1>
        <p className="ptr-muted">{t("deals.subtitle")}</p>
        {checked && bucket?.source === "api" && (
          <p className="text-sm ptr-muted">
            {t("deals.updated", { time: formatDateTime(checked, lang) })}
          </p>
        )}
      </header>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div
          className="asarak-segmented"
          role="group"
          aria-label={t("deals.title")}
        >
          <button
            type="button"
            className="is-deal"
            aria-pressed={tab === "deals"}
            onClick={() => setBrowseParams({ tab: undefined })}
          >
            <BadgeCheck size={15} aria-hidden="true" />
            <span>{t("deals.tabDeals")}</span>
          </button>
          <button
            type="button"
            className="is-scandal"
            aria-pressed={tab === "scandals"}
            onClick={() => setBrowseParams({ tab: "scandals" })}
          >
            <ShieldAlert size={15} aria-hidden="true" />
            <span>{t("deals.tabScandals")}</span>
          </button>
        </div>
      </div>

      <div
        className="ptr-category-bar"
        role="group"
        aria-label={t("filters.category")}
      >
        {shownCategories.map((value) => {
          const catCount = value === "all" ? null : categoryCounts?.[value];
          return (
            <button
              type="button"
              key={value}
              className="ptr-chip"
              aria-pressed={category === value}
              onClick={() =>
                setBrowseParams({
                  category: value === "all" ? undefined : value,
                })
              }
            >
              <span>{t(categoryLabels[value])}</span>
              {typeof catCount === "number" && catCount > 0 && (
                <span className="ptr-chip-count">
                  <bdi>{formatNumber(catCount, lang)}</bdi>
                </span>
              )}
            </button>
          );
        })}
      </div>

      <MockBanner
        source={bucket?.source ?? null}
        onRetry={() => setAttempt((value) => value + 1)}
      />
      {current?.limited && <p className="ptr-notice">{t("deals.limited")}</p>}
      {stale && <p className="ptr-notice ptr-warning">{t("ui.stale")}</p>}
      {failed && <ErrorState onRetry={() => setAttempt((value) => value + 1)} />}

      <section className="min-w-0 space-y-3" aria-busy={loading}>
        {loading && (
          <div role="status">
            <span className="sr-only">{t("common.loading")}</span>
            {[0, 1, 2].map((index) => (
              <div key={index} className="skeleton my-3 h-36 rounded-2xl" />
            ))}
          </div>
        )}
        {!loading && !failed && items.length === 0 && (
          <p className="surface p-6 font-medium" role="status">
            {t("deals.empty")}
          </p>
        )}
        {items.map((item, index) => (
          <HighlightCard
            item={item}
            key={item.id ?? index}
            warning={tab === "scandals"}
            from={from}
            live={bucket?.source === "api"}
            canSharePrice={
              bucket?.source === "api" && Boolean(checked) && !stale
            }
          />
        ))}
      </section>

      <AdSlot
        slot={process.env.NEXT_PUBLIC_ADSENSE_SLOT_DEALS}
        format="auto"
        minHeight={100}
      />
      <EditorialGuide variant="deals" />
    </div>
  );
}
