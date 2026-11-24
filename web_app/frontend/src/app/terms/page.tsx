import type { Metadata } from "next";
import {
  CONTACT_EMAIL,
  SITE_DOMAIN,
  SITE_NAME,
  SITE_NAME_AR,
  absoluteUrl,
} from "@/lib/site";

export const metadata: Metadata = {
  title: `شروط الاستخدام وإخلاء المسؤولية — Terms & Disclaimer`,
  description: `شروط الاستخدام وإخلاء المسؤولية لمنصة ${SITE_NAME_AR} (${SITE_DOMAIN}): طبيعة مقارنة الأسعار المستقلة وتغيّر الأسعار والتوفر لدى المتاجر.`,
  alternates: { canonical: absoluteUrl("/terms") },
};

export default function TermsPage() {
  return (
    <div className="ptr-wrap ptr-page" dir="rtl" lang="ar">
      <header className="ptr-page-heading">
        <p className="ptr-eyebrow">الشروط · TERMS &amp; DISCLAIMER</p>
        <h1>شروط الاستخدام وإخلاء المسؤولية</h1>
        <p className="ptr-muted">آخر تحديث: نوفمبر 2026 · {SITE_NAME_AR} ({SITE_DOMAIN})</p>
      </header>

      <article className="surface ptr-section ptr-legal">
        <section className="ptr-legal-block">
          <h2>1. طبيعة الخدمة</h2>
          <p>
            موقع <strong>{SITE_NAME_AR} ({SITE_NAME})</strong> هو أداة مستقلة لمتابعة ومقارنة الأسعار عبر المتاجر
            الإلكترونية المصرية لأغراض إرشادية ومعلوماتية فقط. نحن لسنا متجراً إلكترونياً، ولا نبيع أو نشحن المنتجات،
            ولا نمثل أي بائع أو علامة تجارية مذكورة على الموقع.
          </p>
        </section>

        <section className="ptr-legal-block">
          <h2>2. دقة الأسعار وتوفر المخزون</h2>
          <p>
            نقوم بتحديث بيانات الأسعار والمخزون بشكل دوري وتلقائي، ومع ذلك قد تتغير الأسعار أو الخصومات أو رسوم
            الشحن أو حالة التوفر لدى المتاجر في أي لحظة قبل موعد التحديث التالي. يُرجى دائماً مراجعة السعر النهائي
            ومواصفات المنتج وسياسة الاسترجاع والضمان مباشرة على صفحة المتجر قبل إتمام الشراء.
          </p>
        </section>

        <section className="ptr-legal-block">
          <h2>3. تقييمات الخصومات</h2>
          <p>
            تصنيفات العروض والخصومات على <strong>{SITE_NAME_AR}</strong> تُحسب آلياً وبشكل موضوعي بناءً على اللقطات
            السعرية المرصودة تاريخياً فقط، ولا تُعد بأي حال استشارة مالية أو ضماناً تجارياً أو حكماً قانونياً على أي
            متجر.
          </p>
        </section>

        <section className="ptr-legal-block">
          <h2>4. الإفصاح عن الروابط الإعلانية والتسويق بالعمولة</h2>
          <p>
            قد تحتوي بعض الروابط المؤدية إلى المتاجر على معرّفات تسويق بالعمولة (Affiliate Links)، ما يعني أن الموقع
            قد يحصل على عمولة رمزية عند الشراء من خلالها دون أي زيادة في السعر على المستخدم.
          </p>
        </section>

        <section className="ptr-legal-block">
          <h2>5. حدود المسؤولية والعلامات التجارية</h2>
          <p>
            جميع أسماء المتاجر والعلامات التجارية والشعارات المذكورة هي ملك لأصحابها وتُستخدم فقط للتعريف بالمنتجات
            والعروض. لا يتحمل موقع <strong>{SITE_NAME_AR}</strong> أي مسؤولية عن عمليات الشراء أو الشحن أو الضمان أو
            خدمة ما بعد البيع التي تتم عبر مواقع المتاجر الخارجية. للإبلاغ عن خطأ سعري أو استفسار قانوني، تواصل معنا
            على{" "}
            <a className="ptr-link" href={`mailto:${CONTACT_EMAIL}`}>
              {CONTACT_EMAIL}
            </a>
            .
          </p>
        </section>

        <section className="ptr-legal-block ptr-legal-en" dir="ltr" lang="en">
          <h2>Terms &amp; Disclaimer (English Summary)</h2>
          <p>
            {SITE_NAME} ({SITE_DOMAIN}) is an independent price comparison and historical tracking service. Prices,
            discounts, shipping fees, and stock availability change frequently on retailer websites; always verify the
            final checkout details directly on the retailer&apos;s page before purchasing. Outbound store links may
            include affiliate tracking parameters at no extra cost to you.
          </p>
        </section>
      </article>
    </div>
  );
}
