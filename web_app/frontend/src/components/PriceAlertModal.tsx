"use client";

import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import Link from "next/link";
import {
  BellOff,
  BellRing,
  Check,
  CheckCircle2,
  ExternalLink,
  Loader2,
  Mail,
  Send,
  X,
} from "lucide-react";
import type { AlertChannel, Category } from "@/types/contract";
import {
  ApiError,
  cancelPriceAlert,
  fetchSubmissionsConfig,
  submitPriceAlert,
} from "@/lib/api";
import { formatDate, formatPrice } from "@/lib/format";
import { useLanguage } from "@/lib/i18n";
import {
  maskAlertDestination,
  readAlertPrefs,
  removeAlertLocally,
  saveAlertLocally,
  type SavedPriceAlert,
} from "@/lib/saved-alerts";
import { storeDisplayName } from "@/lib/stores";

export interface PriceAlertModalProps {
  open: boolean;
  onClose: () => void;
  productKey: string;
  productSk?: string;
  productTitle: string;
  imageUrl?: string | null;
  category?: Category;
  storeName: string;
  currentPrice: number;
  existingAlert?: SavedPriceAlert | null;
}

const EMAIL = /^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$/;
const CHAT_ID = /^-?\d{5,20}$/;

const ENV_TELEGRAM_BOT_USERNAME = (
  process.env.NEXT_PUBLIC_TELEGRAM_BOT_USERNAME ?? ""
)
  .trim()
  .replace(/^@+/, "");

let cachedBotUsername: string | null = ENV_TELEGRAM_BOT_USERNAME || null;

export function normalizeTelegramDestination(value: string): string {
  return value.trim();
}

export function PriceAlertModal({
  open,
  onClose,
  productKey,
  productSk,
  productTitle,
  imageUrl,
  category,
  storeName,
  currentPrice,
  existingAlert = null,
}: PriceAlertModalProps) {
  const { lang, t } = useLanguage();
  const id = useId();
  const dialogRef = useRef<HTMLDialogElement>(null);
  const request = useRef<AbortController | null>(null);
  const successClose = useRef<HTMLButtonElement>(null);
  const [channel, setChannel] = useState<AlertChannel>("email");
  const [target, setTarget] = useState("");
  const [destination, setDestination] = useState("");
  const [pending, setPending] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [cancelError, setCancelError] = useState<string | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [uncertain, setUncertain] = useState(false);
  const [telegramBotUsername, setTelegramBotUsername] = useState<string>(
    cachedBotUsername ?? "",
  );
  const [saved, setSaved] = useState<{
    destination: string;
    target: number;
  } | null>(null);

  useEffect(() => {
    if (!open || cachedBotUsername !== null) return;
    const controller = new AbortController();
    fetchSubmissionsConfig(controller.signal)
      .then((cfg) => {
        if (controller.signal.aborted) return;
        const resolved = (cfg?.telegram_bot_username ?? "")
          .trim()
          .replace(/^@+/, "");
        cachedBotUsername = resolved;
        setTelegramBotUsername(resolved);
      })
      .catch(() => {
        /* Keep empty fallback when unreachable */
      });
    return () => controller.abort();
  }, [open]);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!open || !dialog) return;
    const opener =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    const prefs = readAlertPrefs();
    setTarget(
      currentPrice > 0 ? String(Math.floor(currentPrice * 90) / 100) : "",
    );
    setChannel(prefs.lastChannel);
    setDestination(
      prefs.lastChannel === "telegram" ? prefs.telegramChatId : prefs.email,
    );
    setPending(false);
    setCancelling(false);
    setCancelError(null);
    setError(null);
    setUncertain(false);
    setSaved(null);
    if (!dialog.open) dialog.showModal();
    dialog.querySelector<HTMLElement>("input, button")?.focus();
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      request.current?.abort();
      request.current = null;
      if (dialog.open) dialog.close();
      document.body.style.overflow = overflow;
      if (opener?.isConnected) opener.focus({ preventScroll: true });
    };
  }, [open, currentPrice]);

  useEffect(() => {
    if (saved) successClose.current?.focus();
  }, [saved]);

  if (!open) return null;

  const isActiveManageMode = Boolean(existingAlert && !saved);

  const amount = Number(target);
  const address =
    channel === "telegram"
      ? normalizeTelegramDestination(destination)
      : destination.trim();
  const validAddress =
    channel === "email"
      ? EMAIL.test(address)
      : CHAT_ID.test(address);
  const validTarget =
    Number.isFinite(amount) &&
    amount > 0 &&
    amount < currentPrice &&
    amount <= 50_000_000;
  const addressInvalid = Boolean(
    (address && !validAddress) || error?.fields.destination,
  );
  const targetInvalid = Boolean(
    (target && !validTarget) || error?.fields.target_price,
  );
  const addressMessage = t(
    channel === "email"
      ? "alert.invalidDestinationEmail"
      : "alert.invalidDestinationTelegram",
  );
  const belowPct =
    validTarget && currentPrice > 0
      ? ((currentPrice - amount) / currentPrice) * 100
      : null;
  const status = error?.status;
  const message = uncertain
    ? t("alert.errUncertain")
    : status === 409
      ? t("alert.errDuplicate")
      : status === 429
        ? t("alert.errRateLimit")
        : status === 400 || status === 422
          ? t("alert.errInvalid")
          : status === 404
            ? t("alert.errServiceNotLive")
            : error
              ? t("alert.error")
              : null;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!validAddress || !validTarget || request.current) return;
    const controller = new AbortController();
    request.current = controller;
    setPending(true);
    setError(null);
    setUncertain(false);
    try {
      const res = await submitPriceAlert(
        {
          product_key: productKey,
          product_title: productTitle,
          store_name: storeName,
          target_price: amount,
          channel,
          destination: address,
        },
        controller.signal,
      );
      if (!controller.signal.aborted) {
        saveAlertLocally({
          alert_id: res.id,
          product_sk: productSk ?? productKey,
          product_key: productKey,
          title: productTitle,
          image_url: imageUrl ?? null,
          store_name: storeName,
          category,
          price_when_set: currentPrice,
          target_price: amount,
          channel,
          destination: address,
          cancel_token: res.cancel_token ?? null,
          created_at: new Date().toISOString(),
        });
        setSaved({
          destination: maskAlertDestination(address, channel),
          target: amount,
        });
      }
    } catch (cause) {
      if (controller.signal.aborted) return;
      if (cause instanceof ApiError && cause.status !== 502) setError(cause);
      else setUncertain(true);
    } finally {
      if (request.current === controller) {
        request.current = null;
        setPending(false);
      }
    }
  }

  async function handleCancelExisting() {
    if (!existingAlert || cancelling) return;
    setCancelling(true);
    setCancelError(null);
    const controller = new AbortController();
    request.current = controller;
    try {
      if (existingAlert.alert_id && existingAlert.cancel_token) {
        await cancelPriceAlert(
          existingAlert.alert_id,
          existingAlert.cancel_token,
          controller.signal,
        );
      }
      if (!controller.signal.aborted) {
        removeAlertLocally({
          alert_id: existingAlert.alert_id,
          product_sk: existingAlert.product_sk,
          product_key: existingAlert.product_key,
          store_name: existingAlert.store_name,
        });
        onClose();
      }
    } catch (cause) {
      if (controller.signal.aborted) return;
      // Treat 404 (already deleted or backend cancel route not yet live) cleanly
      if (cause instanceof ApiError && cause.status === 404) {
        removeAlertLocally({
          alert_id: existingAlert.alert_id,
          product_sk: existingAlert.product_sk,
          product_key: existingAlert.product_key,
          store_name: existingAlert.store_name,
        });
        onClose();
        return;
      }
      setCancelError(t("alert.cancelError"));
    } finally {
      if (request.current === controller) {
        request.current = null;
      }
      setCancelling(false);
    }
  }

  function handleForceLocalRemove() {
    if (!existingAlert) return;
    removeAlertLocally({
      alert_id: existingAlert.alert_id,
      product_sk: existingAlert.product_sk,
      product_key: existingAlert.product_key,
      store_name: existingAlert.store_name,
    });
    onClose();
  }

  return (
    <dialog
      ref={dialogRef}
      className="ptr-dialog surface"
      aria-labelledby={`${id}-title`}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 id={`${id}-title`} className="text-xl font-bold">
            {t(isActiveManageMode ? "alert.activeTitle" : "alert.title")}
          </h2>
          <p className="mt-1 text-sm ptr-muted" dir="auto">
            {productTitle}
          </p>
          <p className="mt-1 text-sm ptr-muted">
            {storeDisplayName(storeName, lang)} · {t("alert.currentPriceLabel")}{" "}
            <bdi className="ptr-mono font-semibold">
              {formatPrice(currentPrice, lang)}
            </bdi>
          </p>
        </div>
        <button
          type="button"
          className="ptr-icon-button"
          aria-label={t("alert.close")}
          onClick={onClose}
        >
          <X size={18} aria-hidden="true" />
        </button>
      </div>

      {isActiveManageMode && existingAlert ? (
        <div className="mt-4 space-y-4">
          <div className="ptr-notice flex-col items-start" role="status">
            <p className="flex items-center gap-2 font-bold" style={{ color: "var(--asarak-emerald-text)" }}>
              <CheckCircle2 size={16} aria-hidden="true" />
              {t("alert.activeButton")}
            </p>
            <p className="text-sm">{t("alert.activeSubtitle")}</p>
          </div>

          <dl className="ptr-receipt-rows">
            <div>
              <dt>{t("alert.savedTargetLabel")}</dt>
              <dd style={{ color: "var(--asarak-emerald-text)" }}>
                <bdi>{formatPrice(existingAlert.target_price, lang)}</bdi>
              </dd>
            </div>
            <div>
              <dt>{t("alert.savedViaLabel")}</dt>
              <dd>
                <bdi>
                  {t(existingAlert.channel === "telegram" ? "alert.telegram" : "alert.email")}
                  {" · "}
                  {maskAlertDestination(existingAlert.destination, existingAlert.channel)}
                </bdi>
              </dd>
            </div>
            <div>
              <dt>{t("alert.savedOnLabel")}</dt>
              <dd>
                <bdi>{formatDate(existingAlert.created_at, lang)}</bdi>
              </dd>
            </div>
          </dl>

          {cancelError && (
            <div className="ptr-notice ptr-warning flex-col items-start" role="alert">
              <p>{cancelError}</p>
              <button
                type="button"
                className="ptr-link text-xs"
                onClick={handleForceLocalRemove}
              >
                {t("alert.cancelRemoveLocal")}
              </button>
            </div>
          )}

          <div className="grid gap-2.5 pt-1">
            <Link
              href="/my-alerts"
              className="ptr-button ptr-primary w-full"
              onClick={onClose}
            >
              <BellRing size={15} aria-hidden="true" />
              <span>{t("alert.viewAllMyAlerts")}</span>
            </Link>
            <button
              type="button"
              disabled={cancelling}
              className="ptr-button ptr-alert-cancel-btn w-full"
              onClick={() => void handleCancelExisting()}
            >
              {cancelling ? (
                <Loader2 size={15} className="animate-spin" aria-hidden="true" />
              ) : (
                <BellOff size={15} aria-hidden="true" />
              )}
              <span>{t(cancelling ? "alert.cancelling" : "alert.cancelButton")}</span>
            </button>
          </div>
        </div>
      ) : saved ? (
        <div className="mt-5 space-y-4">
          <div className="ptr-notice flex-col items-start" role="status">
            <p className="flex items-center gap-2 font-semibold">
              <Check size={16} aria-hidden="true" />
              {t("alert.successShort")}
            </p>
            <p>
              {t("alert.success", {
                destination: `\u2068${saved.destination}\u2069`,
                target: formatPrice(saved.target, lang),
              })}
            </p>
          </div>
          <div className="grid gap-2.5">
            <Link
              href="/my-alerts"
              className="ptr-button ptr-primary w-full"
              onClick={onClose}
            >
              <BellRing size={15} aria-hidden="true" />
              <span>{t("alert.viewAllMyAlerts")}</span>
            </Link>
            <button
              type="button"
              className="ptr-button w-full"
              ref={successClose}
              onClick={onClose}
            >
              {t("alert.close")}
            </button>
          </div>
        </div>
      ) : (
        <form
          className="mt-4 space-y-4"
          onSubmit={submit}
          noValidate
          aria-busy={pending}
        >
          <p className="text-sm ptr-muted">{t("alert.subtitle")}</p>
          <fieldset className="space-y-2" disabled={pending}>
            <legend className="ptr-label">{t("alert.channel")}</legend>
            <div className="asarak-segmented">
              {(["email", "telegram"] as const).map((value) => (
                <button
                  key={value}
                  type="button"
                  aria-pressed={channel === value}
                  onClick={() => {
                    const prefs = readAlertPrefs();
                    setChannel(value);
                    setDestination(
                      value === "telegram" ? prefs.telegramChatId : prefs.email,
                    );
                    setError(null);
                  }}
                >
                  {value === "email" ? (
                    <Mail size={14} aria-hidden="true" />
                  ) : (
                    <Send size={14} aria-hidden="true" />
                  )}
                  <span>
                    {t(value === "email" ? "alert.email" : "alert.telegram")}
                  </span>
                </button>
              ))}
            </div>
          </fieldset>
          <div>
            <label className="ptr-label" htmlFor={`${id}-destination`}>
              {t(channel === "email" ? "alert.email" : "alert.telegram")}
            </label>
            {channel === "telegram" && telegramBotUsername && (
              <div className="mb-2">
                <a
                  href={`https://t.me/${encodeURIComponent(telegramBotUsername)}?start=alerts`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="ptr-button ptr-small-button w-full"
                >
                  <Send size={14} aria-hidden="true" />
                  <span>{t("alert.openTelegramBot")}</span>
                  <ExternalLink size={13} aria-hidden="true" />
                </a>
              </div>
            )}
            <input
              id={`${id}-destination`}
              className={`ptr-field${channel === "telegram" ? " ptr-mono" : ""}`}
              type={channel === "email" ? "email" : "text"}
              inputMode={channel === "telegram" ? "numeric" : "email"}
              dir="ltr"
              value={destination}
              disabled={pending}
              required
              aria-invalid={addressInvalid || undefined}
              aria-describedby={
                addressInvalid ? `${id}-destination-error` : undefined
              }
              onChange={(event) => {
                setDestination(event.target.value);
                setError(null);
              }}
              placeholder={t(
                channel === "email"
                  ? "alert.destinationEmail"
                  : "alert.destinationTelegram",
              )}
            />
            {channel === "telegram" && (
              <p className="mt-1 text-xs ptr-muted">
                {t("alert.telegramHelp")}
              </p>
            )}
            {addressInvalid && (
              <p className="ptr-error mt-1" id={`${id}-destination-error`}>
                {addressMessage}
              </p>
            )}
          </div>
          <div>
            <label className="ptr-label" htmlFor={`${id}-target`}>
              {t("alert.targetPrice")}
            </label>
            <input
              id={`${id}-target`}
              className="ptr-field num ptr-mono"
              type="number"
              inputMode="decimal"
              min="0.01"
              step="0.01"
              dir="ltr"
              value={target}
              disabled={pending}
              required
              aria-invalid={targetInvalid || undefined}
              aria-describedby={
                targetInvalid ? `${id}-target-error` : undefined
              }
              onChange={(event) => {
                setTarget(event.target.value);
                setError(null);
              }}
            />
            {belowPct !== null && belowPct >= 0.5 && (
              <p
                className="mt-1 text-xs font-semibold"
                style={{ color: "var(--asarak-emerald-text)" }}
              >
                {t("alert.belowHint", {
                  pct: Math.round(belowPct),
                })}
              </p>
            )}
            {targetInvalid && (
              <p className="ptr-error mt-1" id={`${id}-target-error`}>
                {t("alert.invalidPrice")}
              </p>
            )}
          </div>
          {message && (
            <p className="ptr-notice ptr-warning" role="alert">
              {message}
            </p>
          )}
          <button
            type="submit"
            disabled={!validAddress || !validTarget || pending}
            className="ptr-button ptr-primary w-full"
          >
            {pending ? (
              <Loader2 size={16} className="animate-spin" aria-hidden="true" />
            ) : (
              <BellRing size={16} aria-hidden="true" />
            )}
            {t(pending ? "alert.submitting" : "alert.submit")}
          </button>
        </form>
      )}
    </dialog>
  );
}
