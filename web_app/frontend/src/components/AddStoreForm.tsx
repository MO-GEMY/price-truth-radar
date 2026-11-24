"use client";

import Link from "next/link";
import { ChevronDown, ShieldCheck } from "lucide-react";
import { useId, useState, type FormEvent } from "react";
import { buildMailto, CONTACT_EMAIL_RE, isHttpUrl, isWhatsAppNumber } from "@/lib/forms";
import { SITE_NAME_AR } from "@/lib/site";
import { FieldError, FieldHint, focusFirstInvalid, Honeypot, Required } from "@/components/forms/FormBits";
import {
  FailureNotice,
  FormUnavailableNotice,
  SubmitButton,
  SuccessNotice,
} from "@/components/forms/SubmissionNotice";
import { useSubmission } from "@/components/forms/useSubmission";

const MODES = [
  { value: "suggest", label: "مستخدم يقترح متجر" },
  { value: "owner", label: "صاحب متجر أو شركة" },
] as const;

type Mode = (typeof MODES)[number]["value"];

const PLATFORMS = [
  { value: "shopify", label: "Shopify" },
  { value: "woocommerce", label: "WooCommerce" },
  { value: "salla_zid", label: "سلة / زد" },
  { value: "custom", label: "مخصص / أخرى" },
] as const;

const MODE_LABEL: Record<Mode, string> = {
  suggest: "مستخدم يقترح متجر",
  owner: "صاحب متجر أو شركة",
};

type Field = "storeName" | "storeUrl" | "platform" | "contactEmail" | "contactWhatsapp";
type Errors = Partial<Record<Field, string>>;

const MAX_NOTES = 2000;

/** API field names → this form's fields, for server-side validation replies. */
const SERVER_FIELD: Record<string, Field> = {
  store_name: "storeName",
  store_url: "storeUrl",
  platform: "platform",
  contact_email: "contactEmail",
  contact_whatsapp: "contactWhatsapp",
};

export function AddStoreForm() {
  const id = useId();
  const fieldId = (field: Field) => `${id}-${field}`;
  const submission = useSubmission<Field>("/api/submissions/store-suggestion", SERVER_FIELD);

  const [mode, setMode] = useState<Mode>("suggest");
  const [storeName, setStoreName] = useState("");
  const [storeUrl, setStoreUrl] = useState("");
  const [notes, setNotes] = useState("");
  const [platform, setPlatform] = useState("");
  const [contactEmail, setContactEmail] = useState("");
  const [contactWhatsapp, setContactWhatsapp] = useState("");
  const [errors, setErrors] = useState<Errors>({});

  const isOwner = mode === "owner";
  const mailto = buildMailto(
    `اقتراح متجر (${MODE_LABEL[mode]}) — ${SITE_NAME_AR}`,
    [
      `اسم المتجر: ${storeName.trim() || "-"}`,
      `رابط المتجر: ${storeUrl.trim() || "-"}`,
      `المنصة: ${isOwner && platform ? platform : "-"}`,
      `بريد التواصل: ${isOwner && contactEmail.trim() ? contactEmail.trim() : "-"}`,
      `رقم واتساب: ${isOwner && contactWhatsapp.trim() ? contactWhatsapp.trim() : "-"}`,
      "",
      ...(notes.trim() && !isOwner ? [`ملاحظات: ${notes.trim()}`] : []),
    ].join("\n"),
  );

  function validate(): Errors {
    const found: Errors = {};
    if (storeName.trim().length < 2) found.storeName = "أدخل اسم المتجر.";
    if (!isHttpUrl(storeUrl)) found.storeUrl = "أدخل رابط المتجر كاملاً يبدأ بـ https://";
    if (isOwner) {
      if (!platform) found.platform = "اختر منصة المتجر.";
      const hasEmail = contactEmail.trim() !== "";
      const hasWhatsapp = contactWhatsapp.trim() !== "";
      if (hasEmail && !CONTACT_EMAIL_RE.test(contactEmail.trim())) {
        found.contactEmail = "أدخل بريداً إلكترونياً صحيحاً.";
      }
      if (hasWhatsapp && !isWhatsAppNumber(contactWhatsapp)) {
        found.contactWhatsapp = "أدخل رقم واتساب صحيحاً، مثل 01012345678.";
      }
      if (!hasEmail && !hasWhatsapp) {
        found.contactEmail = "أدخل بريداً إلكترونياً أو رقم واتساب للتواصل معك.";
      }
    }
    return found;
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const found = validate();
    setErrors(found);
    const invalid = Object.keys(found) as Field[];
    if (invalid.length > 0) {
      focusFirstInvalid(invalid.map(fieldId));
      return;
    }

    const outcome = await submission.submit({
      kind: mode,
      store_name: storeName.trim(),
      store_url: storeUrl.trim(),
      notes: isOwner ? "" : notes,
      platform: isOwner ? platform : null,
      contact_email: isOwner ? contactEmail.trim() || null : null,
      contact_whatsapp: isOwner ? contactWhatsapp.trim() || null : null,
    });
    if (outcome.kind === "invalid") {
      setErrors(outcome.errors);
      focusFirstInvalid(Object.keys(outcome.errors).map((field) => fieldId(field as Field)));
    }
  }

  if (submission.unavailable) {
    return (
      <FormUnavailableNotice>
        <p>
          راسلنا مباشرة على بريد الفريق مع اسم المتجر ورابطه، ومع بيانات التواصل إن كنت صاحب
          المتجر، وسيدرس فريقنا الطلب يدوياً.
        </p>
      </FormUnavailableNotice>
    );
  }
  if (submission.sent) {
    return (
      <SuccessNotice
        title="تم استلام طلبك"
        resetLabel="إرسال طلب آخر"
        onReset={() => {
          // Keep the owner's contact details; clear the store that was just submitted.
          submission.reset();
          setStoreName("");
          setStoreUrl("");
          setNotes("");
          setPlatform("");
        }}
      >
        <p>سيراجع فريقنا الطلب يدوياً، وسنتواصل معك على بيانات التواصل عند الحاجة.</p>
        <p className="mt-2">لا يُضاف أي متجر تلقائياً، ويعتمد الانضمام على نتيجة المراجعة.</p>
      </SuccessNotice>
    );
  }

  const { pending, failure } = submission;
  // When nothing can deliver, the direct-email route replaces the submit button.
  const cannotSubmit = failure?.reason === "unavailable";

  return (
    <form className="ptr-form" onSubmit={submit} noValidate aria-busy={pending}>
      <Honeypot id={`${id}-website`} value={submission.website} onChange={submission.setWebsite} />

      <fieldset className="grid gap-1.5" disabled={pending}>
        <legend className="ptr-label">نوع الطلب</legend>
        <div className="asarak-segmented ptr-form-segmented">
          {MODES.map(({ value, label }) => (
            <button
              key={value}
              type="button"
              aria-pressed={mode === value}
              onClick={() => {
                setMode(value);
                setErrors({});
              }}
            >
              {label}
            </button>
          ))}
        </div>
        <FieldHint>
          {isOwner
            ? "قدّم متجرك الإلكتروني، وسنتواصل معك بعد المراجعة."
            : "أخبرنا بمتجر تودّ مقارنة أسعاره، وسيدرسه فريقنا."}
        </FieldHint>
      </fieldset>

      <div className="grid gap-1">
        <label className="ptr-label" htmlFor={fieldId("storeName")}>
          اسم المتجر <Required />
        </label>
        <input
          id={fieldId("storeName")}
          className="ptr-field"
          type="text"
          autoComplete="organization"
          maxLength={120}
          value={storeName}
          disabled={pending}
          aria-invalid={errors.storeName ? true : undefined}
          aria-describedby={errors.storeName ? `${fieldId("storeName")}-error` : undefined}
          onChange={(event) => {
            setStoreName(event.target.value);
            setErrors((prev) => ({ ...prev, storeName: undefined }));
          }}
        />
        {errors.storeName && <FieldError id={`${fieldId("storeName")}-error`}>{errors.storeName}</FieldError>}
      </div>

      <div className="grid gap-1">
        <label className="ptr-label" htmlFor={fieldId("storeUrl")}>
          رابط المتجر <Required />
        </label>
        <input
          id={fieldId("storeUrl")}
          className="ptr-field ptr-mono"
          type="url"
          inputMode="url"
          autoComplete="url"
          dir="ltr"
          spellCheck={false}
          maxLength={2048}
          placeholder="https://www.example.com"
          value={storeUrl}
          disabled={pending}
          aria-invalid={errors.storeUrl ? true : undefined}
          aria-describedby={`${fieldId("storeUrl")}-hint`}
          onChange={(event) => {
            setStoreUrl(event.target.value);
            setErrors((prev) => ({ ...prev, storeUrl: undefined }));
          }}
        />
        {errors.storeUrl ? (
          <FieldError id={`${fieldId("storeUrl")}-hint`}>{errors.storeUrl}</FieldError>
        ) : (
          <FieldHint>الصفحة الرئيسية للمتجر، وليس رابط منتج.</FieldHint>
        )}
      </div>

      {!isOwner && (
        <div className="grid gap-1">
          <div className="flex items-baseline justify-between gap-3">
            <label className="ptr-label" htmlFor={`${id}-notes`}>
              ملاحظات <span className="ptr-muted font-normal">(اختياري)</span>
            </label>
            <span className="text-xs ptr-muted num" dir="ltr" aria-hidden="true">
              {notes.length} / {MAX_NOTES}
            </span>
          </div>
          <textarea
            id={`${id}-notes`}
            className="ptr-field"
            rows={4}
            maxLength={MAX_NOTES}
            placeholder="ما الفئات التي يبيعها المتجر؟ ولماذا تودّ إضافته؟"
            value={notes}
            disabled={pending}
            onChange={(event) => setNotes(event.target.value)}
          />
        </div>
      )}

      {isOwner && (
        <>
          <div className="grid gap-1">
            <label className="ptr-label" htmlFor={fieldId("platform")}>
              منصة المتجر <Required />
            </label>
            <div className="ptr-select">
              <select
                id={fieldId("platform")}
                className="ptr-field"
                value={platform}
                disabled={pending}
                aria-invalid={errors.platform ? true : undefined}
                aria-describedby={errors.platform ? `${fieldId("platform")}-error` : undefined}
                onChange={(event) => {
                  setPlatform(event.target.value);
                  setErrors((prev) => ({ ...prev, platform: undefined }));
                }}
              >
                <option value="" disabled>
                  اختر المنصة…
                </option>
                {PLATFORMS.map(({ value, label }) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
              <ChevronDown size={16} aria-hidden="true" />
            </div>
            {errors.platform && <FieldError id={`${fieldId("platform")}-error`}>{errors.platform}</FieldError>}
          </div>

          <fieldset className="grid gap-1.5" disabled={pending}>
            <legend className="ptr-label">بيانات التواصل</legend>
            <div className="ptr-form-row">
              <div className="grid gap-1">
                <label className="ptr-label ptr-sublabel" htmlFor={fieldId("contactEmail")}>
                  بريد التواصل
                </label>
                <input
                  id={fieldId("contactEmail")}
                  className="ptr-field"
                  type="email"
                  inputMode="email"
                  autoComplete="email"
                  dir="ltr"
                  spellCheck={false}
                  maxLength={254}
                  placeholder="you@store.com"
                  value={contactEmail}
                  aria-invalid={errors.contactEmail ? true : undefined}
                  aria-describedby={errors.contactEmail ? `${fieldId("contactEmail")}-error` : undefined}
                  onChange={(event) => {
                    setContactEmail(event.target.value);
                    setErrors((prev) => ({ ...prev, contactEmail: undefined }));
                  }}
                />
                {errors.contactEmail && (
                  <FieldError id={`${fieldId("contactEmail")}-error`}>{errors.contactEmail}</FieldError>
                )}
              </div>
              <div className="grid gap-1">
                <label className="ptr-label ptr-sublabel" htmlFor={fieldId("contactWhatsapp")}>
                  أو رقم واتساب
                </label>
                <input
                  id={fieldId("contactWhatsapp")}
                  className="ptr-field ptr-mono"
                  type="tel"
                  inputMode="tel"
                  autoComplete="tel"
                  dir="ltr"
                  maxLength={32}
                  placeholder="+20 10…"
                  value={contactWhatsapp}
                  aria-invalid={errors.contactWhatsapp ? true : undefined}
                  aria-describedby={`${fieldId("contactWhatsapp")}-hint`}
                  onChange={(event) => {
                    setContactWhatsapp(event.target.value);
                    setErrors((prev) => ({ ...prev, contactWhatsapp: undefined }));
                  }}
                />
                {errors.contactWhatsapp ? (
                  <FieldError id={`${fieldId("contactWhatsapp")}-hint`}>{errors.contactWhatsapp}</FieldError>
                ) : (
                  <FieldHint>مثل 01012345678</FieldHint>
                )}
              </div>
            </div>
            <FieldHint>أدخل واحداً على الأقل حتى نتمكن من التواصل معك.</FieldHint>
          </fieldset>
        </>
      )}

      {submission.turnstile(mailto)}
      {failure && <FailureNotice failure={failure} mailto={mailto} fallbackPrimary={cannotSubmit} />}

      <p className="ptr-notice">
        <ShieldCheck size={18} className="flex-none" aria-hidden="true" />
        <span>
          مراجعة يدوية فقط: لا نجلب ولا نفحص أي روابط تلقائياً عند الإرسال، ولا يعني الإرسال إضافة
          المتجر تلقائياً.
        </span>
      </p>

      <div className="grid gap-3">
        {!cannotSubmit && (
          <SubmitButton
            pending={pending}
            disabled={submission.needsToken}
            label="إرسال الطلب"
            pendingLabel="جارٍ الإرسال…"
          />
        )}
        <p className="text-xs ptr-muted">
          تُستخدم بياناتك لمراجعة الطلب والتواصل معك فقط ولا تُحفَظ في قاعدة بيانات الموقع. راجع{" "}
          <Link className="ptr-link" href="/privacy">
            سياسة الخصوصية
          </Link>
          .
        </p>
      </div>
    </form>
  );
}
