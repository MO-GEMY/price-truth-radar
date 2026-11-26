"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import {
  ArrowLeftRight,
  ArrowUpRight,
  BellOff,
  BellRing,
  CheckCircle2,
  Info,
  Loader2,
  Mail,
  RefreshCw,
  Send,
  Sparkles,
  TrendingDown,
} from "lucide-react";
import type { ProductPriceSnapshot } from "@/types/contract";
import {
  ApiError,
  cancelPriceAlert,
  fetchProductPricesBatch,
} from "@/lib/api";
import { productHref } from "@/lib/browse-state";
import { formatDate, formatNumber, formatPrice } from "@/lib/format";
import { useLanguage } from "@/lib/i18n";
import {
  maskAlertDestination,
  useSavedAlerts,
  type SavedPriceAlert,
} from "@/lib/saved-alerts";
import { ProductImage } from "@/components/ProductImage";
import { StoreBadge } from "@/components/StoreBadge";

export default function MyAlertsPage() {
  const { lang, t } = useLanguage();
  const { alerts, count, hydrated, removeAlert } = useSavedAlerts();
  const [livePrices, setLivePrices] = useState<
    Record<string, ProductPriceSnapshot>
  >({});
  const [refreshing, setRefreshing] = useState(false);
  const [cancellingIds, setCancellingIds] = useState<Record<string, boolean>>({});
  const [cancelErrors, setCancelErrors] = useState<Record<string, string>>({});
  const lastFetchedSigRef = useRef<string>("");

  const sksKey = useMemo(
    () =>
      [...new Set(alerts.map((a) => a.product_sk).filter(Boolean))]
        .sort()
        .join(","),
    [alerts],
  );

  const loadLivePrices = useCallback(
    async (skList: string[], signal?: AbortSignal) => {
      if (skList.length === 0) {
        setLivePrices({});
        return;
      }
      setRefreshing(true);
      try {
        const snapshots = await fetchProductPricesBatch(skList, signal);
        if (!signal?.aborted) {
          setLivePrices(snapshots);
        }
      } catch {
        // Keep graceful fallback to saved `price_when_set`
      } finally {
        if (!signal?.aborted) {
          setRefreshing(false);
        }
      }
    },
    [],
  );

  useEffect(() => {
    if (!hydrated) return;
    if (!sksKey) {
      lastFetchedSigRef.current = "";
      setLivePrices({});
      return;
    }
    if (lastFetchedSigRef.current === sksKey) return;
    lastFetchedSigRef.current = sksKey;
    const controller = new AbortController();
    void loadLivePrices(sksKey.split(","), controller.signal);
    return () => controller.abort();
  }, [hydrated, sksKey, loadLivePrices]);

  async function handleCancel(item: SavedPriceAlert) {
    if (cancellingIds[item.alert_id]) return;
    setCancellingIds((prev) => ({ ...prev, [item.alert_id]: true }));
    setCancelErrors((prev) => {
      const next = { ...prev };
      delete next[item.alert_id];
      return next;
    });
    try {
      if (item.alert_id && item.cancel_token) {
        await cancelPriceAlert(item.alert_id, item.cancel_token);
      }
      removeAlert({
        alert_id: item.alert_id,
        product_sk: item.product_sk,
        product_key: item.product_key,
        store_name: item.store_name,
      });
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 404) {
        removeAlert({
          alert_id: item.alert_id,
          product_sk: item.product_sk,
          product_key: item.product_key,
          store_name: item.store_name,
        });
      } else {
        setCancelErrors((prev) => ({
          ...prev,
          [item.alert_id]: t("alert.cancelError"),
        }));
      }
    } finally {
      setCancellingIds((prev) => {
        const next = { ...prev };
        delete next[item.alert_id];
        return next;
      });
    }
  }

  function handleForceLocalRemove(item: SavedPriceAlert) {
    removeAlert({
      alert_id: item.alert_id,
      product_sk: item.product_sk,
      product_key: item.product_key,
      store_name: item.store_name,
    });
  }

  return (
    <div className="ptr-wrap ptr-page">
      <header className="ptr-page-heading">
        <p className="ptr-eyebrow">{t("myAlerts.eyebrow")}</p>
        <div className="asarak-alerts-head-row">
          <div className="min-w-0 space-y-1">
            <h1>{t("myAlerts.title")}</h1>
            <p className="ptr-muted">{t("myAlerts.subtitle")}</p>
          </div>

          {hydrated && count > 0 && (
            <div className="ptr-controls shrink-0">
              <span className="ptr-badge ptr-badge-good">
                <BellRing size={13} aria-hidden="true" />
                {count === 1
                  ? t("myAlerts.countOne")
                  : t("myAlerts.count", { count: formatNumber(count, lang) })}
              </span>
              <button
                type="button"
                className="ptr-button ptr-small-button"
                disabled={refreshing}
                onClick={() => void loadLivePrices(sksKey.split(",").filter(Boolean))}
              >
                <RefreshCw
                  size={14}
                  className={refreshing ? "animate-spin" : undefined}
                  aria-hidden="true"
                />
                <span>{t(refreshing ? "myAlerts.refreshing" : "myAlerts.refresh")}</span>
              </button>
            </div>
          )}
        </div>
      </header>

      {!hydrated ? (
        <div className="space-y-3" role="status">
          <span className="sr-only">{t("common.loading")}</span>
          {[0, 1].map((i) => (
            <div key={i} className="surface p-5 space-y-3" aria-hidden="true">
              <div className="flex gap-3">
                <div className="skeleton size-16 rounded-xl shrink-0" />
                <div className="flex-1 space-y-2">
                  <div className="skeleton h-4 w-2/3" />
                  <div className="skeleton h-4 w-1/3" />
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : alerts.length === 0 ? (
        <section className="surface asarak-alerts-empty" aria-label={t("myAlerts.emptyTitle")}>
          <span className="asarak-alerts-empty__icon" aria-hidden="true">
            <BellRing size={26} strokeWidth={2} />
          </span>
          <h2>{t("myAlerts.emptyTitle")}</h2>
          <p className="ptr-muted">{t("myAlerts.emptyBody")}</p>
          <div className="ptr-controls justify-center pt-1">
            <Link href="/deals" className="ptr-button ptr-primary">
              <Sparkles size={15} aria-hidden="true" />
              <span>{t("myAlerts.browseDeals")}</span>
            </Link>
            <Link href="/compare" className="ptr-button">
              <ArrowLeftRight size={15} aria-hidden="true" />
              <span>{t("myAlerts.browseCompare")}</span>
            </Link>
          </div>
        </section>
      ) : (
        <section className="asarak-alerts-list" aria-busy={refreshing}>
          {alerts.map((item) => {
            const live = livePrices[item.product_sk] ?? null;
            const displayedCurrentPrice = live
              ? live.current_price
              : item.price_when_set;
            const inStock = live ? live.in_stock : true;
            const targetReached =
              inStock &&
              Number.isFinite(displayedCurrentPrice) &&
              displayedCurrentPrice > 0 &&
              displayedCurrentPrice <= item.target_price;
            const diffAboveTarget =
              inStock && displayedCurrentPrice > item.target_price
                ? displayedCurrentPrice - item.target_price
                : null;
            const isCancelling = Boolean(cancellingIds[item.alert_id]);
            const errMsg = cancelErrors[item.alert_id];
            const href = productHref(item.product_sk);

            return (
              <article
                key={item.alert_id}
                className={`surface asarak-alert-card${
                  targetReached ? " asarak-alert-card--hit" : ""
                }`}
              >
                <div className="asarak-alert-card__main">
                  <Link href={href} className="shrink-0" aria-hidden="true" tabIndex={-1}>
                    <ProductImage
                      src={item.image_url}
                      alt=""
                      category={item.category ?? "electronics"}
                      className="ptr-thumbnail"
                      fit={item.category === "fashion" ? "cover" : "contain"}
                      studio={item.category !== "fashion"}
                    />
                  </Link>

                  <div className="min-w-0 flex-1 space-y-2">
                    <div className="ptr-controls text-xs ptr-muted">
                      <StoreBadge name={item.store_name} size="sm" />
                      <span className="ptr-badge">
                        {item.channel === "telegram" ? (
                          <Send size={11} aria-hidden="true" />
                        ) : (
                          <Mail size={11} aria-hidden="true" />
                        )}
                        <bdi>
                          {maskAlertDestination(item.destination, item.channel)}
                        </bdi>
                      </span>
                      <span className="text-xs ptr-muted">
                        {t("myAlerts.createdAt", {
                          date: formatDate(item.created_at, lang),
                        })}
                      </span>
                    </div>

                    <h2 className="asarak-alert-card__title" dir="auto">
                      <Link href={href}>
                        <bdi>{item.title}</bdi>
                      </Link>
                    </h2>

                    <div className="ptr-controls">
                      {targetReached ? (
                        <span className="ptr-badge ptr-badge-good">
                          <CheckCircle2 size={13} aria-hidden="true" />
                          <span>{t("myAlerts.targetHit")}</span>
                        </span>
                      ) : !inStock ? (
                        <span className="ptr-badge">{t("card.outOfStock")}</span>
                      ) : diffAboveTarget !== null && diffAboveTarget >= 1 ? (
                        <span className="ptr-badge">
                          <TrendingDown size={12} aria-hidden="true" />
                          <bdi>
                            {t("myAlerts.awayBy", {
                              amount: formatPrice(Math.round(diffAboveTarget), lang),
                            })}
                          </bdi>
                        </span>
                      ) : null}
                    </div>
                  </div>
                </div>

                <dl className="asarak-alert-card__prices">
                  <div>
                    <dt>{t("myAlerts.targetPrice")}</dt>
                    <dd
                      className="ptr-price"
                      style={{ color: "var(--asarak-emerald-text)" }}
                    >
                      <bdi>{formatPrice(item.target_price, lang)}</bdi>
                    </dd>
                  </div>
                  <div>
                    <dt>
                      {t(live ? "myAlerts.currentPrice" : "myAlerts.priceWhenSet")}
                    </dt>
                    <dd className="ptr-price">
                      <bdi>{formatPrice(displayedCurrentPrice, lang)}</bdi>
                    </dd>
                  </div>
                </dl>

                <div className="asarak-alert-card__actions">
                  <Link href={href} className="ptr-button ptr-small-button">
                    <span>{t("myAlerts.inspectProduct")}</span>
                    <ArrowUpRight size={14} aria-hidden="true" />
                  </Link>
                  <button
                    type="button"
                    disabled={isCancelling}
                    className="ptr-button ptr-small-button ptr-alert-cancel-btn"
                    onClick={() => void handleCancel(item)}
                  >
                    {isCancelling ? (
                      <Loader2 size={14} className="animate-spin" aria-hidden="true" />
                    ) : (
                      <BellOff size={14} aria-hidden="true" />
                    )}
                    <span>
                      {t(isCancelling ? "alert.cancelling" : "alert.cancelButton")}
                    </span>
                  </button>
                </div>

                {errMsg && (
                  <div className="asarak-alert-card__err ptr-notice ptr-warning" role="alert">
                    <span>{errMsg}</span>
                    <button
                      type="button"
                      className="ptr-link text-xs"
                      onClick={() => handleForceLocalRemove(item)}
                    >
                      {t("alert.cancelRemoveLocal")}
                    </button>
                  </div>
                )}
              </article>
            );
          })}
        </section>
      )}

      <p className="asarak-alerts-device-note">
        <Info size={14} aria-hidden="true" className="shrink-0" />
        <span>{t("myAlerts.deviceNote")}</span>
      </p>
    </div>
  );
}
