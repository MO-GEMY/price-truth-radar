import type { Metadata } from "next";
import {
  CONTACT_EMAIL,
  SITE_DOMAIN,
  SITE_NAME,
  SITE_NAME_AR,
  absoluteUrl,
} from "@/lib/site";

export const metadata: Metadata = {
  title: `تواصل معنا — Contact ${SITE_NAME}`,
  description: `تواصل مع فريق ${SITE_NAME_AR} (${SITE_DOMAIN}) عبر البريد الإلكتروني ${CONTACT_EMAIL} لاقتراح متجر جديد أو الإبلاغ عن خطأ سعري أو استفسارات الشراكات.`,
  alternates: { canonical: absoluteUrl("/contact") },
};

export default function ContactPage() {
  return (
    <div className="ptr-wrap ptr-page" dir="rtl" lang="ar">
      <header className="ptr-page-heading">
        <p className="ptr-eyebrow">الدعم والتواصل · CONTACT US</p>
        <h1>تواصل معنا</h1>
        <p className="ptr-muted">
          يسعدنا سماع ملاحظاتك، اقتراحات المتاجر الجديدة، أو أي استفسارات تقنية وتجارية.
        </p>
      </header>

      <article className="surface ptr-section ptr-legal">
        <section className="ptr-legal-block">
          <h2>البريد الإلكتروني الرسمي</h2>
          <p>
            للتواصل المباشر مع فريق <strong>{SITE_NAME_AR} ({SITE_NAME})</strong> يرجى مراسلتنا على:
          </p>
          <p>
            <a
              className="ptr-button ptr-primary"
              href={`mailto:${CONTACT_EMAIL}`}
              dir="ltr"
            >
              {CONTACT_EMAIL}
            </a>
          </p>
        </section>

        <section className="ptr-legal-block">
          <h2>كيف يمكننا مساعدتك؟</h2>
          <ul>
            <li>
              <strong>الإبلاغ عن خطأ في السعر أو المطابقة:</strong> أرسل لنا رابط صفحة المنتج على {SITE_DOMAIN} مع
              الرابط الأصلي في المتجر وسنراجع البيانات فوراً.
            </li>
            <li>
              <strong>اقتراح متجر مصري جديد:</strong> إذا كنت صاحب متجر إلكتروني في مصر أو متسوقاً ترغب في تتبع متجر
              معين، أرسل لنا رابط المتجر لدراسة إضافته.
            </li>
            <li>
              <strong>الخصوصية أو الشراكات التجارية:</strong> نرد عادةً خلال 1–2 يوم عمل على جميع الاستفسارات الواردة
              إلى{" "}
              <a className="ptr-link" href={`mailto:${CONTACT_EMAIL}`} dir="ltr">
                {CONTACT_EMAIL}
              </a>
              .
            </li>
          </ul>
        </section>

        <section className="ptr-legal-block ptr-legal-en" dir="ltr" lang="en">
          <h2>Contact {SITE_NAME}</h2>
          <p>
            Have feedback, a price mismatch report, a store suggestion, or a partnership inquiry? Email us directly at{" "}
            <a className="ptr-link" href={`mailto:${CONTACT_EMAIL}`}>
              {CONTACT_EMAIL}
            </a>
            .
          </p>
        </section>
      </article>
    </div>
  );
}
