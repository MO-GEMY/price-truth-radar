import type { Metadata } from "next";
import Link from "next/link";
import {
  CONTACT_EMAIL,
  SITE_DOMAIN,
  SITE_NAME,
  SITE_NAME_AR,
  absoluteUrl,
} from "@/lib/site";

export const metadata: Metadata = {
  title: `التنويه وإخلاء المسؤولية — Disclaimer`,
  description: `التنويه وإخلاء المسؤولية لمنصة ${SITE_NAME_AR} (${SITE_DOMAIN}): استقلال المنصة عن المتاجر والعلامات التجارية، دقة الأسعار، ملكية الأسماء والشعارات، والإفصاح عن التسويق بالعمولة.`,
  alternates: { canonical: absoluteUrl("/disclaimer") },
};

export default function DisclaimerPage() {
  return (
    <div className="ptr-wrap ptr-page" dir="rtl" lang="ar">
      <header className="ptr-page-heading">
        <p className="ptr-eyebrow">التنويه · DISCLAIMER</p>
        <h1>التنويه وإخلاء المسؤولية</h1>
        <p className="ptr-muted">آخر تحديث: نوفمبر 2026 · النطاق: {SITE_DOMAIN}</p>
      </header>

      <article className="surface ptr-section ptr-legal">
        <section className="ptr-legal-block">
          <h2>1. استقلال المنصة</h2>
          <p>
            <strong>{SITE_NAME_AR} ({SITE_NAME})</strong> منصة مستقلة تماماً لمقارنة الأسعار وتحليل
            الخصومات. لا تتبع أي متجر أو علامة تجارية معروضة على الموقع، ولا تمثّله، ولا ترتبط به بأي
            شكل من الأشكال. لا تبيع المنصة أي منتج، ولا تتقاضى مقابل مقابل ترتيب النتائج أو تعديل سجل
            الأسعار المرصودة. ظهور متجر أو منتج على المنصة لا يُعد توصية أو تأييداً له.
          </p>
        </section>

        <section className="ptr-legal-block">
          <h2>2. دقة الأسعار ومصدرها</h2>
          <p>
            تعتمد المنصة على لقطات سعرية يومية آلية تُجمع من الصفحات العامة للمتاجر. تُعرض الأسعار كما
            ظهرت وقت الرصد بالجنيه المصري، وقد تتغير الأسعار أو الخصومات أو رسوم الشحن أو حالة التوفر
            لدى المتجر في أي وقت قبل التحديث التالي. السعر النهائي المعتمد هو السعر الظاهر في سلة
            الشراء على موقع المتجر، وننصح دائماً بمراجعته قبل إتمام الشراء.
          </p>
          <p>
            لاحظت سعراً خاطئاً؟ أبلغنا عبر صفحة{" "}
            <Link className="ptr-link" href="/contact">
              تواصل معنا
            </Link>{" "}
            وسنراجع البيانات.
          </p>
        </section>

        <section className="ptr-legal-block">
          <h2>3. تقييم الخصومات</h2>
          <p>
            يُحسب تقييم مصداقية الخصم آلياً من سجل الأسعار المرصود تاريخياً لكل منتج. هذا التقييم معلومة
            استرشادية للمستهلك فقط، وليس استشارة مالية أو ضماناً تجارياً أو حكماً قانونياً على أي متجر.
          </p>
        </section>

        <section className="ptr-legal-block">
          <h2>4. الملكية الفكرية والعلامات التجارية</h2>
          <p>
            جميع أسماء المتاجر والعلامات التجارية والشعارات المذكورة أو الظاهرة على الموقع مملوكة لأصحابها
            من أصحاب الحقوق، وتُستخدم لأغراض التعريف بالمنتجات ومقارنة الأسعار فقط. لا ينشئ استخدامها أي
            انتماء أو رعاية أو تأييد من جانب مالك العلامة التجارية.
          </p>
          <p>
            إذا كنت مالك حق وترى أن هناك استخداماً يحتاج إلى مراجعة، تواصل معنا على{" "}
            <a className="ptr-link" href={`mailto:${CONTACT_EMAIL}`} dir="ltr">
              {CONTACT_EMAIL}
            </a>
            .
          </p>
        </section>

        <section className="ptr-legal-block">
          <h2>5. الإفصاح عن التسويق بالعمولة (Affiliate Disclosure)</h2>
          <p>
            قد نحصل على عمولة تسويق بالعمولة عند الشراء عبر بعض الروابط المعروضة على الموقع، دون أي
            تكلفة إضافية عليك؛ فسعر المنتج لدى المتجر لا يتغير بسبب ذلك. لا تؤثر هذه العمولات على ترتيب
            النتائج أو على تقييم مصداقية الخصومات، الذي يُحسب من سجل الأسعار وحده.
          </p>
          <ul>
            <li>
              <strong>Amazon Associates:</strong> كمشارك في برنامج Amazon Associates، تحصل{" "}
              {SITE_NAME_AR} على عمولة من المشتريات المؤهلة.
            </li>
            <li>
              <strong>شبكات التسويق بالعمولة:</strong> قد تكون بعض الروابط جزءاً من برامج شراكة مع
              المتاجر المصرية أو شبكات التسويق بالعمولة المعتمدة.
            </li>
          </ul>
        </section>

        <section className="ptr-legal-block">
          <h2>6. الإعلانات</h2>
          <p>
            قد نعرض إعلانات من شبكات إعلانية خارجية مثل Google AdSense لدعم استمرار الخدمة مجاناً.
            تُميَّز الإعلانات عن المحتوى، ولا تعبّر عن رأي المنصة، ولا تُعد توصية لأي منتج أو خدمة.
            للاطلاع على كيفية تعامل هذه الشبكات مع ملفات تعريف الارتباط، راجع{" "}
            <Link className="ptr-link" href="/privacy">
              سياسة الخصوصية
            </Link>
            .
          </p>
        </section>

        <section className="ptr-legal-block">
          <h2>7. حدود المسؤولية</h2>
          <p>
            تقدَّم المنصة وجميع محتوياتها «كما هي». لا تتحمل المنصة أي مسؤولية عن عمليات الشراء أو الدفع
            أو الشحن أو الضمان أو خدمة ما بعد البيع التي تتم عبر مواقع المتاجر الخارجية، وهي تخضع لشروط
            وسياسات كل متجر. للاطلاع على شروط الاستخدام الكاملة راجع صفحة{" "}
            <Link className="ptr-link" href="/terms">
              شروط الاستخدام وإخلاء المسؤولية
            </Link>
            .
          </p>
        </section>

        <section className="ptr-legal-block ptr-legal-en" dir="ltr" lang="en">
          <h2>Disclaimer (English Summary)</h2>
          <p>
            <strong>Independence:</strong> {SITE_NAME} ({SITE_DOMAIN}) is a fully independent
            price-comparison and discount-analysis platform. It is not affiliated with, sponsored by, or
            representing any store or brand shown on the site, and it does not sell any product.
          </p>
          <p>
            <strong>Price accuracy:</strong> Prices are automated daily snapshots in EGP and may change
            at any time on the retailer&apos;s website. The final price shown in the retailer&apos;s cart at
            checkout is the authoritative one.
          </p>
          <p>
            <strong>Trademarks:</strong> All store names, brand names, and logos are the property of
            their respective owners and are used for identification and price comparison only.
          </p>
          <p>
            <strong>Affiliate disclosure:</strong> We may earn an affiliate commission on purchases made
            through some links on this site, at no extra cost to you. Commissions never influence result
            ordering or discount verdicts. As an Amazon Associate, {SITE_NAME} earns from qualifying
            purchases.
          </p>
          <p>
            <strong>Advertising:</strong> Third-party ads (including Google AdSense) are clearly labelled,
            do not represent our opinion, and are not endorsements. See our{" "}
            <Link className="ptr-link" href="/privacy">
              Privacy Policy
            </Link>{" "}
            for cookie details, and{" "}
            <Link className="ptr-link" href="/terms">
              Terms &amp; Disclaimer
            </Link>{" "}
            for the full terms.
          </p>
        </section>
      </article>
    </div>
  );
}
