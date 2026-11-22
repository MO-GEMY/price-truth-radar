"use client";

/**
 * "نبّهني لما السعر ينزل" — bilingual price-drop alert modal.
 *
 * Picks Telegram or Email, takes a target price in EGP (defaulting ~10% below
 * the current price) and posts to `POST /api/alerts`. All states are explicit:
 * idle / submitting / success (server id + message) / validation / error.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { BellRing, Check, Loader2, Send, X } from "lucide-react";
import type { AlertChannel, PriceAlertResponse } from "@/types/contract";
import { ApiError, submitPriceAlert } from "@/lib/api";
import { formatPrice } from "@/lib/format";
import { useLanguage } from "@/lib/i18n";
import type { TranslationKey } from "@/lib/translations";

export interface PriceAlertModalProps {
  open: boolean;
  onClose: () => void;
  productKey: string;
  productTitle: string;
  storeName: string;
  currentPrice: number;
}

type Phase = "idle" | "submitting" | "success" | "error";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;
const TELEGRAM_RE = /^@?[a-zA-Z][a-zA-Z0-9_]{2,32}$|^\+?\d{8,15}$/;

export function PriceAlertModal({
  open,
  onClose,
  productKey,
  productTitle,
  storeName,
  currentPrice,
}: PriceAlertModalProps) {
  const { lang, t } = useLanguage();
  const [channel, setChannel] = useState<AlertChannel>("telegram");
  const [target, setTarget] = useState<string>("");
  const [destination, setDestination] = useState<string>("");
  const [phase, setPhase] = useState<Phase>("idle");
  const [serverMessage, setServerMessage] = useState<string>("");
  const dialogRef = useRef<HTMLDivElement>(null);

  // Reset per open + sensible default: ~10% below the current price.
  useEffect(() => {
    if (!open) return;
    setTarget(currentPrice > 0 ? String(Math.floor(currentPrice * 0.9)) : "");
    setDestination("");
    setChannel("telegram");
    setPhase("idle");
    setServerMessage("");
  }, [open, currentPrice]);

  // Escape-to-close + lock body scroll while open.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [open, onClose]);

  const targetNumber = useMemo(() => Number(target), [target]);
  const pctBelow = useMemo(() => {
    if (!targetNumber || currentPrice <= 0) return null;
    const pct = Math.round(((currentPrice - targetNumber) / currentPrice) * 100);
    return pct > 0 ? pct : null;
  }, [targetNumber, currentPrice]);

  const destinationInvalid =
    destination.trim().length > 0 &&
    (channel === "email"
      ? !EMAIL_RE.test(destination.trim())
      : !TELEGRAM_RE.test(destination.trim().startsWith("@") ? destination.trim() : `@${destination.trim()}`));

  const priceInvalid = target.trim().length > 0 && (!targetNumber || targetNumber <= 0 || targetNumber >= currentPrice);

  const canSubmit =
    phase !== "submitting" &&
    target.trim().length > 0 &&
    destination.trim().length > 0 &&
    !priceInvalid &&
    !destinationInvalid;

  async function handleSubmit() {
    if (!canSubmit) return;
    setPhase("submitting");
    setServerMessage("");
    try {
      const res: PriceAlertResponse = await submitPriceAlert({
        product_key: productKey,
        product_title: productTitle,
        store_name: storeName,
        target_price: targetNumber,
        channel,
        destination: destination.trim().startsWith("@")
          ? destination.trim()
          : channel === "telegram"
            ? `@${destination.trim().replace(/^@/, "")}`
            : destination.trim(),
      });
      setServerMessage(res.message || "");
      setPhase("success");
    } catch (err) {
      setServerMessage(err instanceof ApiError ? err.message : "");
      setPhase("error");
    }
  }

  if (!open) return null;

  const channelBtn = (value: AlertChannel, icon: React.ReactNode, labelKey: TranslationKey) => (
    <button
      type="button"
      onClick={() => {
        setChannel(value);
        setDestination("");
      }}
      aria-pressed={channel === value}
      className={`inline-flex flex-1 items-center justify-center gap-2 rounded-xl border px-3 py-2.5 text-sm font-semibold transition ${
        channel === value
          ? "border-teal-400/50 bg-teal-400/15 text-teal-200"
          : "border-white/10 bg-white/[0.03] text-slate-300 hover:border-white/25 hover:text-white"
      }`}
    >
      {icon}
      {t(labelKey)}
    </button>
  );

  return (
    <div
      className="fixed inset-0 z-[60] flex items-end justify-center bg-black/70 p-3 backdrop-blur-sm sm:items-center sm:p-6"
      role="dialog"
      aria-modal="true"
      aria-label={t("alert.title")}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={dialogRef}
        className="surface w-full max-w-md rounded-2xl p-5 shadow-[0_24px_80px_rgba(0,0,0,0.7)] sm:p-6"
      >
        {/* Header */}
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <span className="flex size-10 shrink-0 items-center justify-center rounded-xl border border-teal-400/30 bg-teal-400/12 text-teal-300">
              <BellRing className="size-5" />
            </span>
            <div className="min-w-0">
              <h2 className="text-base font-extrabold leading-snug text-white">
                {t("alert.title")}
              </h2>
              <p className="num mt-0.5 text-xs text-slate-400">
                {t("alert.currentPriceLabel")}: {formatPrice(currentPrice, lang)}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={t("alert.close")}
            className="rounded-lg p-1.5 text-slate-400 transition hover:bg-white/[0.06] hover:text-white"
          >
            <X className="size-4" />
          </button>
        </div>

        <p className="mt-2.5 text-xs leading-relaxed text-slate-400">{t("alert.subtitle")}</p>

        {phase === "success" ? (
          /* ---------- Success state ---------- */
          <div className="mt-5 space-y-4">
            <div className="flex items-start gap-3 rounded-xl border border-emerald-400/35 bg-emerald-500/12 p-4">
              <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-emerald-500/20 text-emerald-300">
                <Check className="size-4.5" />
              </span>
              <div className="min-w-0 text-sm">
                <p className="font-bold text-emerald-200">{t("alert.successShort")}</p>
                <p className="mt-1 leading-relaxed text-emerald-100/80">
                  {serverMessage || t("alert.success")}
                </p>
              </div>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="w-full rounded-xl bg-gradient-to-r from-teal-400 to-emerald-500 px-4 py-2.5 text-sm font-bold text-[#031214] transition hover:brightness-110"
            >
              {t("alert.close")}
            </button>
          </div>
        ) : (
          /* ---------- Form ---------- */
          <div className="mt-5 space-y-4">
            {/* Channel picker */}
            <div>
              <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                {t("alert.channel")}
              </p>
              <div className="flex gap-2">
                {channelBtn("telegram", <Send className="size-4 shrink-0" />, "alert.telegram")}
                {channelBtn("email", <BellRing className="size-4 shrink-0" />, "alert.email")}
              </div>
            </div>

            {/* Destination */}
            <div>
              <label
                htmlFor="alert-destination"
                className="mb-1.5 block text-[11px] font-semibold uppercase tracking-wide text-slate-500"
              >
                {channel === "email" ? t("alert.email") : t("alert.telegram")}
              </label>
              <input
                id="alert-destination"
                type={channel === "email" ? "email" : "text"}
                dir="auto"
                value={destination}
                onChange={(e) => setDestination(e.target.value)}
                placeholder={
                  channel === "email"
                    ? t("alert.destinationEmail")
                    : t("alert.destinationTelegram")
                }
                className={`h-11 w-full rounded-xl border bg-[#050912] px-3.5 text-sm text-slate-100 outline-none transition placeholder:text-slate-600 focus:outline-none ${
                  destinationInvalid
                    ? "border-rose-400/60 focus:border-rose-400"
                    : "border-white/10 focus:border-teal-400/50"
                }`}
              />
              {destinationInvalid ? (
                <p className="mt-1 text-[11px] font-medium text-rose-300">
                  {channel === "email"
                    ? t("alert.invalidDestinationEmail")
                    : t("alert.invalidDestinationTelegram")}
                </p>
              ) : null}
            </div>

            {/* Target price */}
            <div>
              <label
                htmlFor="alert-target"
                className="mb-1.5 block text-[11px] font-semibold uppercase tracking-wide text-slate-500"
              >
                {t("alert.targetPrice")}
              </label>
              <div className="relative">
                <input
                  id="alert-target"
                  type="number"
                  inputMode="decimal"
                  min="0"
                  step="1"
                  dir="ltr"
                  value={target}
                  onChange={(e) => setTarget(e.target.value)}
                  className={`num h-11 w-full rounded-xl border bg-[#050912] px-3.5 text-sm font-bold text-slate-100 outline-none transition focus:outline-none ${
                    priceInvalid
                      ? "border-rose-400/60 focus:border-rose-400"
                      : "border-white/10 focus:border-teal-400/50"
                  }`}
                />
                {pctBelow ? (
                  <span className="absolute inset-y-0 end-3 my-auto h-fit rounded-md border border-emerald-400/30 bg-emerald-500/10 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-300">
                    {t("alert.belowHint", { pct: pctBelow })}
                  </span>
                ) : null}
              </div>
              {priceInvalid ? (
                <p className="mt-1 text-[11px] font-medium text-rose-300">
                  {t("alert.invalidPrice")}
                </p>
              ) : null}
            </div>

            {/* Error banner */}
            {phase === "error" ? (
              <p className="rounded-xl border border-rose-400/35 bg-rose-500/10 px-3 py-2 text-xs font-semibold text-rose-200">
                {serverMessage || t("alert.error")}
              </p>
            ) : null}

            {/* Submit */}
            <button
              type="button"
              onClick={handleSubmit}
              disabled={!canSubmit}
              className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-teal-400 to-emerald-500 px-4 py-3 text-sm font-bold text-[#031214] transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {phase === "submitting" ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <BellRing className="size-4" />
              )}
              {phase === "submitting" ? t("alert.submitting") : t("alert.submit")}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
