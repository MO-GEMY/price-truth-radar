import type { Metadata } from "next";
import Link from "next/link";
import {
  CONTACT_EMAIL,
  LAUNCH_STORE_COUNT,
  SITE_DOMAIN,
  SITE_NAME,
  SITE_NAME_AR,
  absoluteUrl,
} from "@/lib/site";
import { AddStoreForm } from "@/components/AddStoreForm";

export const metadata: Metadata = {
  title: `أضف متجرك أو اقترح متجراً — Add Store ${SITE_NAME}`,
  description: `اقترح متجراً إلكترونياً مصرياً لمقارنة الأسعار على ${SITE_NAME_AR} (${SITE_DOMAIN})، أو قدّم متجرك للانضمام إلى أكثر من ${LAUNCH_STORE_COUNT} متجر تتابعها المنصة. تتم المراجعة يدوياً ولا تُجمع الروابط تلقائياً.`,
  alternates: { canonical: absoluteUrl("/add-store") },
};

export default function AddStorePage() {
  return (
    <div className="ptr-wrap ptr-page" dir="rtl" lang="ar">
      <header className="ptr-page-heading">
        <p className="ptr-eyebrow">المتاجر · ADD YOUR STORE</p>
        <h1>أضف متجرك أو اقترح متجراً</h1>
        <p className="ptr-muted">
          تتابع منصة {SITE_NAME_AR} ({SITE_NAME}) أسعار المتاجر الإلكترونية المصرية يومياً. اقترح متجراً
          تودّ مقارنة أسعاره، أو قدّم متجرك ليدرسه فريقنا.
        </p>
      </header>

      <div className="ptr-form-layout">
        <section className="surface ptr-section" aria-labelledby="add-store-form-title">
          <h2 id="add-store-form-title">أرسل طلبك</h2>
          <AddStoreForm />
        </section>

        <aside className="surface ptr-section ptr-aside" aria-labelledby="add-store-process-title">
          <h2 id="add-store-process-title">ماذا يحدث بعد الإرسال؟</h2>
          <ol>
            <li>يراجع فريقنا الطلب يدوياً.</li>
            <li>ندرس إمكانية تتبّع أسعار المتجر وعرضها على المنصة.</li>
            <li>نتواصل معك على بيانات التواصل التي أرسلتها عند الحاجة.</li>
          </ol>
          <h3>قبل الإرسال</h3>
          <ul>
            <li>تأكد من أن الرابط هو الصفحة الرئيسية لمتجر إلكتروني يعمل فعلاً.</li>
            <li>الإرسال لا يضمن الانضمام؛ لا يُضاف أي متجر تلقائياً.</li>
          </ul>
          <p>
            لاستفسار آخر راسلنا عبر صفحة{" "}
            <Link className="ptr-link" href="/contact">
              تواصل معنا
            </Link>{" "}
            أو على{" "}
            <a className="ptr-link" href={`mailto:${CONTACT_EMAIL}`} dir="ltr">
              {CONTACT_EMAIL}
            </a>
            .
          </p>
        </aside>
      </div>

      <article className="surface ptr-section ptr-legal">
        <section className="ptr-legal-block" dir="ltr" lang="en">
          <h2>Add your store / Suggest a store</h2>
          <p>
            Suggest an Egyptian online store for price comparison, or submit your own store for
            review. Every request is reviewed manually by the {SITE_NAME} team: submitted URLs are
            never fetched or scraped automatically, and submitting a store does not guarantee it will
            be added.
          </p>
        </section>
      </article>
    </div>
  );
}
