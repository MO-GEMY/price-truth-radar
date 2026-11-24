import type { Metadata } from "next";
import Link from "next/link";
import { Mail } from "lucide-react";
import { CONTACT_EMAIL, SITE_DOMAIN, SITE_NAME, SITE_NAME_AR, absoluteUrl } from "@/lib/site";
import { ContactForm } from "@/components/ContactForm";

export const metadata: Metadata = {
  title: `تواصل معنا — Contact ${SITE_NAME}`,
  description: `تواصل مع فريق ${SITE_NAME_AR} (${SITE_DOMAIN}) عبر نموذج التواصل أو البريد الإلكتروني ${CONTACT_EMAIL} للإبلاغ عن سعر خاطئ أو للاستفسارات العامة وطلبات التعاون والإعلانات.`,
  alternates: { canonical: absoluteUrl("/contact") },
};

export default function ContactPage() {
  return (
    <div className="ptr-wrap ptr-page" dir="rtl" lang="ar">
      <header className="ptr-page-heading">
        <p className="ptr-eyebrow">الدعم والتواصل · CONTACT US</p>
        <h1>تواصل معنا</h1>
        <p className="ptr-muted">
          يسعدنا سماع ملاحظاتك، أو الإبلاغ عن سعر خاطئ، أو دراسة طلبات التعاون والإعلانات.
        </p>
      </header>

      <div className="ptr-form-layout">
        <section className="surface ptr-section" aria-labelledby="contact-form-title">
          <h2 id="contact-form-title">أرسل رسالة</h2>
          <ContactForm />
        </section>

        <aside className="surface ptr-section ptr-aside" aria-labelledby="contact-direct-title">
          <h2 id="contact-direct-title">أو راسلنا مباشرة</h2>
          <p>
            إذا فضّلت البريد الإلكتروني، تواصل مع فريق {SITE_NAME_AR} ({SITE_NAME}) على:
          </p>
          <p>
            <a className="ptr-button ptr-primary w-fit" href={`mailto:${CONTACT_EMAIL}`} dir="ltr">
              <Mail size={16} aria-hidden="true" />
              {CONTACT_EMAIL}
            </a>
          </p>
          <h3>ماذا يحدث بعد الإرسال؟</h3>
          <ul>
            <li>نراجع الرسائل بالترتيب ونرد عادةً خلال 1–2 يوم عمل.</li>
            <li>
              للإبلاغ عن سعر خاطئ: أرفق رابط المنتج على {SITE_DOMAIN} والسعر الصحيح الظاهر في
              المتجر.
            </li>
            <li>
              لإضافة متجر جديد أو اقتراح متجر: استخدم صفحة{" "}
              <Link className="ptr-link" href="/add-store">
                أضف متجرك
              </Link>
              .
            </li>
            <li>لحذف تنبيه سعر نشط: أرسل طلبك من البريد الإلكتروني المسجّل في التنبيه.</li>
          </ul>
        </aside>
      </div>

      <article className="surface ptr-section ptr-legal">
        <section className="ptr-legal-block" dir="ltr" lang="en">
          <h2>Contact {SITE_NAME}</h2>
          <p>
            Have feedback, a wrong-price report, or a partnership inquiry? Use the form above or email
            us directly at{" "}
            <a className="ptr-link" href={`mailto:${CONTACT_EMAIL}`} dir="ltr">
              {CONTACT_EMAIL}
            </a>
            . We usually reply within 1–2 business days.
          </p>
        </section>
      </article>
    </div>
  );
}
