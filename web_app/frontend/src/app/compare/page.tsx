"use client";

import { useEffect, useState } from "react";
import { ChevronDown } from "lucide-react";
import type { CompareResponse, CrossStoreMatch } from "@/types/contract";
import { fetchCategories, fetchCompare, type ApiResult } from "@/lib/api";
import { browseHref, categoryLabelKey, categoryLabels, parseCategory, parsePage, setBrowseParams, useBrowseParams, visibleCategories } from "@/lib/browse-state";
import { formatNumber, formatPctPlain, formatPrice } from "@/lib/format";
import { useLanguage } from "@/lib/i18n";
import { lowestAvailablePrice } from "@/lib/offers";
import { AlternativesTable } from "@/components/AlternativesTable";
import { MockBanner } from "@/components/MockBanner";
import { Pagination } from "@/components/Pagination";
import { CompareCardSkeletons, ErrorState } from "@/components/states";

const PAGE_LIMIT = 10;
const SPREAD_OPTIONS = [0, 5, 10, 20];

function MatchCard({ match, from, first, sample }: { match: CrossStoreMatch; from: string; first: boolean; sample: boolean }) {
  const { lang, t } = useLanguage();
  const lowest = lowestAvailablePrice(match.listings_json);
  const catKey = categoryLabelKey(match.category);
  return (
    <details className="surface ptr-match" open={first ? true : undefined}>
      <summary className="ptr-match-summary">
        <div className="min-w-0">
          <h2 className="font-bold"><bdi>{match.product_title_clean}</bdi></h2>
          <div className="ptr-controls mt-1 text-sm ptr-muted">
            {catKey && <span className="ptr-badge">{t(catKey)}</span>}
            <span>{t("compare.storesCount", { count: formatNumber(match.stores_count, lang) })}</span>
          </div>
        </div>
        <div>
          <p className="text-xs ptr-muted">{t("ui.lowestAvailable")}</p>
          <p className="ptr-price">{lowest === null ? t("ui.noAvailable") : <bdi>{formatPrice(lowest, lang)}</bdi>}</p>
          <p className="text-xs ptr-muted">
            {t("ui.trackedGap")} · <bdi>{formatPrice(match.price_spread_egp, lang)} ({formatPctPlain(match.price_spread_pct, lang)})</bdi>
          </p>
        </div>
        <ChevronDown className="ptr-disclosure-arrow" size={17} aria-hidden="true" />
      </summary>
      <div className="ptr-match-body">
        <p className="text-sm ptr-muted">
          {t("ui.trackedRange")} · <bdi>{formatPrice(match.lowest_price, lang)} – {formatPrice(match.highest_price, lang)}</bdi>
        </p>
        <AlternativesTable alternatives={match.listings_json} from={from} sample={sample} />
      </div>
    </details>
  );
}

export default function ComparePage() {
  const { lang, t } = useLanguage();
  const search = useBrowseParams();
  const category = parseCategory(search.get("category"));
  const page = parsePage(search.get("page"));
  const spread = SPREAD_OPTIONS.find((option) => option === Number(search.get("gap"))) ?? 0;
  const key = `${category}:${page}:${spread}`;
  const [result, setResult] = useState<{ key: string; value: ApiResult<CompareResponse> } | null>(null);
  const [compareCounts, setCompareCounts] = useState<Record<string, number> | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    fetchCategories(controller.signal).then((res) => {
      if (controller.signal.aborted) return;
      const counts: Record<string, number> = {};
      for (const item of res.data.items) {
        if (item.compare_count > 0) counts[item.slug] = item.compare_count;
      }
      if (Object.keys(counts).length > 0) setCompareCounts(counts);
    }).catch(() => {});
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setFailed(null);
    fetchCompare({ category, min_spread_pct: spread, page, limit: PAGE_LIMIT }, controller.signal).then((value) => {
      if (!controller.signal.aborted) setResult({ key, value });
    }).catch(() => {
      if (!controller.signal.aborted) setFailed(key);
    });
    return () => controller.abort();
  }, [key, category, spread, page, attempt]);

  const current = result?.key === key ? result.value : null;
  const shownCategories = visibleCategories(compareCounts, category);
  const loading = !current && failed !== key;
  const totalPages = Math.max(1, Math.ceil((current?.data.total ?? 0) / (current?.data.limit ?? PAGE_LIMIT)));
  const from = browseHref("/compare", search);
  return (
    <div className="ptr-wrap ptr-page">
      <header className="ptr-page-heading">
        <h1>{t("nav.compare")}</h1>
        <p className="ptr-muted">{t("compare.subtitle")}</p>
      </header>
      <div className="ptr-toolbar">
        <div className="ptr-category-bar" role="group" aria-label={t("filters.category")}>
          {shownCategories.map((value) => {
            const catCount = value === "all" ? null : compareCounts?.[value];
            return (
              <button key={value} className="ptr-chip" type="button" aria-pressed={category === value}
                onClick={() => setBrowseParams({ category: value === "all" ? undefined : value, page: undefined })}>
                <span>{t(categoryLabels[value])}</span>
                {typeof catCount === "number" && catCount > 0 && (
                  <span className="ptr-chip-count"><bdi>{formatNumber(catCount, lang)}</bdi></span>
                )}
              </button>
            );
          })}
        </div>
        <label className="ptr-control-label">{t("compare.minSpread")}
          <select className="ptr-field" value={spread} onChange={(event) => setBrowseParams({ gap: Number(event.target.value) || undefined, page: undefined })}>
            {SPREAD_OPTIONS.map((option) => <option value={option} key={option}>{option ? `≥ ${formatPctPlain(option, lang, 0)}` : t("compare.spreadAny")}</option>)}
          </select>
        </label>
      </div>
      {(category !== "all" || spread !== 0 || page !== 1) && (
        <button className="ptr-link" type="button" onClick={() => setBrowseParams({ category: undefined, gap: undefined, page: undefined })}>{t("filters.reset")}</button>
      )}
      <MockBanner source={current?.source ?? null} onRetry={() => setAttempt((value) => value + 1)} />
      {failed === key && <ErrorState onRetry={() => setAttempt((value) => value + 1)} />}
      <section aria-busy={loading} className="space-y-3" id="compare-results">
        {loading && <div role="status"><span className="sr-only">{t("common.loading")}</span><CompareCardSkeletons /></div>}
        {current && <p className="text-sm ptr-muted" role="status">{t("filters.showing", { total: formatNumber(current.data.total, lang) })}</p>}
        {current && current.data.items.length === 0 && (
          <div className="surface p-5"><p className="font-semibold">{t("compare.empty")}</p><p className="ptr-muted text-sm">{t("compare.emptyHint")}</p></div>
        )}
        {current?.data.items.map((match, index) => <MatchCard key={match.canonical_product_key} match={match} first={index === 0}
          from={from} sample={current.source === "mock"} />)}
        {current && <Pagination page={page} totalPages={totalPages} onPage={(next) => {
          setBrowseParams({ page: next > 1 ? next : undefined });
          document.getElementById("compare-results")?.scrollIntoView({ block: "start" });
        }} />}
      </section>
    </div>
  );
}
