"use client";

import Link from "next/link";
import { useId, useState, type FormEvent } from "react";
import { buildMailto, CONTACT_EMAIL_RE, isHttpUrl } from "@/lib/forms";
import { SITE_NAME_AR } from "@/lib/site";
import { FieldError, FieldHint, focusFirstInvalid, Honeypot, Required } from "@/components/forms/FormBits";
import {
  FailureNotice,
  FormUnavailableNotice,
  SubmitButton,
  SuccessNotice,
} from "@/components/forms/SubmissionNotice";
import { useSubmission } from "@/components/forms/useSubmission";

const CATEGORIES = [
  { value: "price_error", label: "الإبلاغ عن سعر خطأ" },
  { value: "general", label: "استفسار عام" },
  { value: "partnership", label: "تعاون وإعلانات" },
] as const;

type Category = (typeof CATEGORIES)[number]["value"];

const CATEGORY_LABEL: Record<Category, string> = {
  price_error: "الإبلاغ عن سعر خطأ",
  general: "استفسار عام",
  partnership: "تعاون وإعلانات",
};

type Field = "name" | "email" | "productUrl" | "message";
type Errors = Partial<Record<Field, string>>;

const MAX_MESSAGE = 3000;

/** API field names → this form's fields, for server-side validation replies. */
const SERVER_FIELD: Record<string, Field> = {
  name: "name",
  email: "email",
  message: "message",
  product_url: "productUrl",
};

export function ContactForm() {
  const id = useId();
  const fieldId = (field: Field) => `${id}-${field}`;
  const submission = useSubmission<Field>("/api/submissions/contact", SERVER_FIELD);

  const [category, setCategory] = useState<Category>("general");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [productUrl, setProductUrl] = useState("");
  const [message, setMessage] = useState("");
  const [errors, setErrors] = useState<Errors>({});

  const needsProductUrl = category === "price_error";
  const trimmedMessage = message.trim();
  const signature = [
    `الاسم: ${name.trim() || "-"}`,
    `البريد الإلكتروني: ${email.trim()}`,
    ...(needsProductUrl ? [`رابط المنتج: ${productUrl.trim()}`] : []),
  ];
  const mailto = buildMailto(
    `${CATEGORY_LABEL[category]} — ${SITE_NAME_AR}`,
    `${trimmedMessage}\n\n—\n${signature.join("\n")}`,
  );

  function validate(): Errors {
    const found: Errors = {};
    if (!CONTACT_EMAIL_RE.test(email.trim())) found.email = "أدخل بريداً إلكترونياً صحيحاً.";
    if (trimmedMessage.length < 10) found.message = "اكتب رسالة من 10 أحرف على الأقل.";
    if ((needsProductUrl || productUrl.trim()) && !isHttpUrl(productUrl)) {
      found.productUrl = "أدخل رابطاً كاملاً يبدأ بـ https://";
    }
    if (name.trim().length > 80) found.name = "الاسم طويل جداً (80 حرفاً كحد أقصى).";
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
      category,
      name: name.trim(),
      email: email.trim(),
      message,
      product_url: needsProductUrl ? productUrl.trim() : "",
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
          راسلنا مباشرة على بريد الفريق وسنرد عليك عادةً خلال 1–2 يوم عمل. إن كان طلبك بخصوص سعر
          خاطئ، أرفق رابط المنتج على الموقع والسعر الصحيح الظاهر في المتجر.
        </p>
      </FormUnavailableNotice>
    );
  }
  if (submission.sent) {
    return (
      <SuccessNotice
        title="تم استلام رسالتك"
        resetLabel="إرسال رسالة أخرى"
        onReset={() => {
          // Keep name/email so a follow-up is quick; clear what was just sent.
          submission.reset();
          setMessage("");
          setProductUrl("");
        }}
      >
        <p>سنراجعها ونرد على بريدك الإلكتروني عادةً خلال 1–2 يوم عمل.</p>
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
          {CATEGORIES.map(({ value, label }) => (
            <button
              key={value}
              type="button"
              aria-pressed={category === value}
              onClick={() => {
                setCategory(value);
                setErrors({});
              }}
            >
              {label}
            </button>
          ))}
        </div>
      </fieldset>

      <div className="ptr-form-row">
        <div className="grid gap-1">
          <label className="ptr-label" htmlFor={fieldId("name")}>
            الاسم <span className="ptr-muted font-normal">(اختياري)</span>
          </label>
          <input
            id={fieldId("name")}
            className="ptr-field"
            type="text"
            autoComplete="name"
            maxLength={80}
            value={name}
            disabled={pending}
            aria-invalid={errors.name ? true : undefined}
            aria-describedby={errors.name ? `${fieldId("name")}-error` : undefined}
            onChange={(event) => {
              setName(event.target.value);
              setErrors((prev) => ({ ...prev, name: undefined }));
            }}
          />
          {errors.name && <FieldError id={`${fieldId("name")}-error`}>{errors.name}</FieldError>}
        </div>

        <div className="grid gap-1">
          <label className="ptr-label" htmlFor={fieldId("email")}>
            البريد الإلكتروني <Required />
          </label>
          <input
            id={fieldId("email")}
            className="ptr-field"
            type="email"
            inputMode="email"
            autoComplete="email"
            dir="ltr"
            spellCheck={false}
            maxLength={254}
            placeholder="you@email.com"
            value={email}
            disabled={pending}
            aria-invalid={errors.email ? true : undefined}
            aria-describedby={errors.email ? `${fieldId("email")}-error` : undefined}
            onChange={(event) => {
              setEmail(event.target.value);
              setErrors((prev) => ({ ...prev, email: undefined }));
            }}
          />
          {errors.email ? (
            <FieldError id={`${fieldId("email")}-error`}>{errors.email}</FieldError>
          ) : (
            <FieldHint>سنرد على هذا البريد.</FieldHint>
          )}
        </div>
      </div>

      {needsProductUrl && (
        <div className="grid gap-1">
          <label className="ptr-label" htmlFor={fieldId("productUrl")}>
            رابط المنتج على الموقع <Required />
          </label>
          <input
            id={fieldId("productUrl")}
            className="ptr-field ptr-mono"
            type="url"
            inputMode="url"
            autoComplete="off"
            dir="ltr"
            spellCheck={false}
            maxLength={2048}
            placeholder="https://asarak.com/products/…"
            value={productUrl}
            disabled={pending}
            aria-invalid={errors.productUrl ? true : undefined}
            aria-describedby={`${fieldId("productUrl")}-hint`}
            onChange={(event) => {
              setProductUrl(event.target.value);
              setErrors((prev) => ({ ...prev, productUrl: undefined }));
            }}
          />
          {errors.productUrl ? (
            <FieldError id={`${fieldId("productUrl")}-hint`}>{errors.productUrl}</FieldError>
          ) : (
            <FieldHint>
              انسخ الرابط من صفحة المنتج، واذكر السعر الصحيح الظاهر في المتجر داخل الرسالة.
            </FieldHint>
          )}
        </div>
      )}

      <div className="grid gap-1">
        <div className="flex items-baseline justify-between gap-3">
          <label className="ptr-label" htmlFor={fieldId("message")}>
            رسالتك <Required />
          </label>
          <span className="text-xs ptr-muted num" dir="ltr" aria-hidden="true">
            {message.length} / {MAX_MESSAGE}
          </span>
        </div>
        <textarea
          id={fieldId("message")}
          className="ptr-field"
          rows={6}
          maxLength={MAX_MESSAGE}
          placeholder="كيف يمكننا مساعدتك؟"
          value={message}
          disabled={pending}
          aria-invalid={errors.message ? true : undefined}
          aria-describedby={errors.message ? `${fieldId("message")}-error` : undefined}
          onChange={(event) => {
            setMessage(event.target.value);
            setErrors((prev) => ({ ...prev, message: undefined }));
          }}
        />
        {errors.message && <FieldError id={`${fieldId("message")}-error`}>{errors.message}</FieldError>}
      </div>

      {submission.turnstile(mailto)}
      {failure && <FailureNotice failure={failure} mailto={mailto} fallbackPrimary={cannotSubmit} />}

      <div className="grid gap-3">
        {!cannotSubmit && (
          <SubmitButton
            pending={pending}
            disabled={submission.needsToken}
            label="إرسال الرسالة"
            pendingLabel="جارٍ الإرسال…"
          />
        )}
        <p className="text-xs ptr-muted">
          تُستخدم بياناتك للرد عليك فقط ولا تُحفَظ في قاعدة بيانات الموقع. راجع{" "}
          <Link className="ptr-link" href="/privacy">
            سياسة الخصوصية
          </Link>
          .
        </p>
      </div>
    </form>
  );
}
