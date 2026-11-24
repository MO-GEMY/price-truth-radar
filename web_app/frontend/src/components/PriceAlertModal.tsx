"use client";

import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { BellRing, Check, ExternalLink, Loader2, Mail, Send, X } from "lucide-react";
import type { AlertChannel } from "@/types/contract";
import { ApiError, fetchSubmissionsConfig, submitPriceAlert } from "@/lib/api";
import { formatPrice } from "@/lib/format";
import { useLanguage } from "@/lib/i18n";
import { storeDisplayName } from "@/lib/stores";

export interface PriceAlertModalProps {
  open: boolean;
  onClose: () => void;
  productKey: string;
  productTitle: string;
  storeName: string;
  currentPrice: number;
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

function maskedDestination(destination: string, channel: AlertChannel): string {
  if (channel === "email")
    return `${destination.charAt(0)}•••@${destination.split("@")[1]}`;
  return CHAT_ID.test(destination)
    ? `•••${destination.slice(-3)}`
    : `${destination.slice(0, 3)}•••`;
}

export function PriceAlertModal({
  open,
  onClose,
  productKey,
  productTitle,
  storeName,
  currentPrice,
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
    setTarget(
      currentPrice > 0 ? String(Math.floor(currentPrice * 90) / 100) : "",
    );
    setDestination("");
    setChannel("email");
    setPending(false);
    setError(null);
    setUncertain(false);
    setSaved(null);
    dialog.showModal();
    dialog.querySelector<HTMLElement>("input")?.focus();
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
      await submitPriceAlert(
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
      if (!controller.signal.aborted)
        setSaved({
          destination: maskedDestination(address, channel),
          target: amount,
        });
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
            {t("alert.title")}
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
      {saved ? (
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
          <button
            type="button"
            className="ptr-button ptr-primary w-full"
            ref={successClose}
            onClick={onClose}
          >
            {t("alert.close")}
          </button>
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
                    setChannel(value);
                    setDestination("");
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
                  // The translation appends its own "%", so pass bare digits.
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
