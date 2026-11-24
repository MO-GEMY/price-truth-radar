import type { Metadata } from "next";
import Link from "next/link";
import {
  CONTACT_EMAIL,
  LAUNCH_PRODUCT_COUNT,
  LAUNCH_STORE_COUNT,
  SITE_NAME,
  SITE_NAME_AR,
  absoluteUrl,
} from "@/lib/site";

export const metadata: Metadata = {
  title: `من نحن — About ${SITE_NAME}`,
  description: `تعرف على منصة ${SITE_NAME_AR} (${SITE_NAME}) لمتابعة سجل الأسعار اليومي عبر ${LAUNCH_STORE_COUNT} متجر مصري والتحقّق من الخصومات المعلنة ومقارنة العروض بالجنيه المصري.`,
  alternates: { canonical: absoluteUrl("/about") },
};

export default function AboutPage() {
  return (
    <div className="ptr-wrap ptr-page" dir="rtl" lang="ar">
      <header className="ptr-page-heading">
        <p className="ptr-eyebrow">عن المنصة · ABOUT ASARAK</p>
        <h1>من نحن — {SITE_NAME_AR} ({SITE_NAME})</h1>
        <p className="ptr-muted">
          منصة مصرية مستقلة لمتابعة سجل الأسعار التاريخي ومقارنة العروض الفعلية بالجنيه المصري.
        </p>
      </header>

      <article className="surface ptr-section ptr-legal">
        <section className="ptr-legal-block">
          <h2>مهمتنا في السوق المصري</h2>
          <p>
            تهدف منصة <strong>{SITE_NAME_AR} ({SITE_NAME})</strong> إلى مساعدة المستهلك المصري على اتخاذ قرار شراء
            واعٍ ومبني على بيانات تاريخية موضوعية، مع توضيح الفارق بين الأسعار المرجعية المعلنة وأسعار البيع الفعلية
            المرصودة خلال مواسم التخفيضات مثل البلاك فرايداي والعروض الموسمية.
          </p>
        </section>

        <section className="ptr-legal-block">
          <h2>كيف نرصد الأسعار ونتحقّق من الخصومات المعلنة؟</h2>
          <ul>
            <li>
              <strong>تتبع يومي لـ {LAUNCH_STORE_COUNT} متجر مصري:</strong> نجمع لقطات يومية تلقائية لأكثر من{" "}
              <strong>{LAUNCH_PRODUCT_COUNT} منتج</strong> عبر الإلكترونيات، الأجهزة المنزلية، الأثاث، الأزياء،
              العطور والتجميل، الصيدليات، والهايبرماركت في مصر.
            </li>
            <li>
              <strong>التحقّق الموضوعي من الخصومات:</strong> نقارن السعر الحالي والسعر المرجعي المشطوب بوسيط
              الأسعار التاريخي المرصود خلال آخر 60 يوماً. لا نصدر تقييم خصم إلا بعد تراكم سجل تاريخي كافٍ أو رصد
              تغيّر سعري فعلي لضمان دقة المقارنة.
            </li>
            <li>
              <strong>مقارنة دقيقة بين المتاجر:</strong> نطابق نفس الموديل أو الباركود (EAN/SKU) عبر المتاجر المصرية
              المختلفة لتعرف أرخص متجر متوفر حالياً بضغطة واحدة، مع عرض بدائل مشابهة في نفس الفئة السعرية عندما لا
              يتوفر نفس الموديل في متاجر أخرى.
            </li>
            <li>
              <strong>تنبيهات انخفاض السعر:</strong> يمكنك تفعيل تنبيه مجاني ليصلك إشعار عبر البريد الإلكتروني أو
              تليجرام بمجرد نزول سعر المنتج إلى الحد الذي تختاره.
            </li>
          </ul>
        </section>

        <section className="ptr-legal-block">
          <h2>الاستقلالية والشفافية</h2>
          <p>
            لا تبيع منصة <strong>{SITE_NAME_AR}</strong> أي منتجات بشكل مباشر ولا تتقاضى أي مقابل من المتاجر لتغيير
            ترتيب النتائج أو تعديل سجل الأسعار المرصودة. قد تحتوي بعض روابط المتاجر على روابط تسويق بالعمولة تساعدنا في
            إبقاء <strong>{SITE_NAME_AR}</strong> مجانياً دون أي تكلفة إضافية عليك، كما قد نعرض إعلانات لتغطية تكاليف
            التشغيل والاستضافة.
          </p>
          <p>
            للاقتراحات أو إضافة متجر مصري جديد، يسعدنا تواصلك معنا عبر{" "}
            <a className="ptr-link" href={`mailto:${CONTACT_EMAIL}`}>
              {CONTACT_EMAIL}
            </a>{" "}
            أو من خلال صفحة{" "}
            <Link className="ptr-link" href="/contact">
              تواصل معنا
            </Link>
            .
          </p>
        </section>

        <section className="ptr-legal-block ptr-legal-en" dir="ltr" lang="en">
          <h2>About {SITE_NAME} (English Summary)</h2>
          <p>
            <strong>{SITE_NAME}</strong> is an independent Egyptian price-tracking and comparison platform monitoring{" "}
            {LAUNCH_PRODUCT_COUNT} products across {LAUNCH_STORE_COUNT} online stores in EGP. By recording daily
            historical price snapshots, {SITE_NAME} helps shoppers verify real discounts, compare advertised reference
            prices against 60-day baselines, and find the best available offer across retailers.
          </p>
          <p>
            Some store links may be affiliate links that help keep {SITE_NAME} free at no extra cost to you.
          </p>
        </section>
      </article>
    </div>
  );
}
