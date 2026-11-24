import type { Metadata } from "next";
import {
  CONTACT_EMAIL,
  SITE_DOMAIN,
  SITE_NAME,
  SITE_NAME_AR,
  absoluteUrl,
} from "@/lib/site";

export const metadata: Metadata = {
  title: `سياسة الخصوصية — Privacy Policy`,
  description: `سياسة الخصوصية لموقع ${SITE_NAME_AR} (${SITE_DOMAIN}): كيفية التعامل مع ملفات تعريف الارتباط، التحليلات، إعلانات Google AdSense، وتنبيهات الأسعار الاختيارية.`,
  alternates: { canonical: absoluteUrl("/privacy") },
};

export default function PrivacyPage() {
  return (
    <div className="ptr-wrap ptr-page" dir="rtl" lang="ar">
      <header className="ptr-page-heading">
        <p className="ptr-eyebrow">الخصوصية · PRIVACY POLICY</p>
        <h1>سياسة الخصوصية — {SITE_NAME_AR}</h1>
        <p className="ptr-muted">آخر تحديث: نوفمبر 2026 · النطاق: {SITE_DOMAIN}</p>
      </header>

      <article className="surface ptr-section ptr-legal">
        <section className="ptr-legal-block">
          <h2>1. البيانات التي نجمعها</h2>
          <p>
            يمكنك تصفح موقع <strong>{SITE_NAME_AR} ({SITE_NAME})</strong> ومقارنة الأسعار بالكامل دون الحاجة لإنشاء
            حساب. لا نجمع أي بيانات شخصية حساسة. البيانات الوحيدة التي قد تقدمها باختيارك هي:
          </p>
          <ul>
            <li>
              <strong>تنبيهات انخفاض السعر الاختيارية:</strong> عند تفعيل تنبيه سعر، نحتفظ بعنوان بريدك الإلكتروني أو
              معرّف تليجرام الخاص بك مع المنتج والسعر المستهدف لغرض واحد فقط هو إرسال إشعار عند تحقق السعر المطلوب.
            </li>
            <li>
              <strong>تفضيلات المتصفح المحلية:</strong> نستخدم التخزين المحلي للمتصفح (<code>localStorage</code>)
              لحفظ تفضيل اللغة (العربية أو الإنجليزية) فقط.
            </li>
          </ul>
        </section>

        <section className="ptr-legal-block">
          <h2>2. ملفات تعريف الارتباط (Cookies) والتحليلات</h2>
          <p>
            قد يستخدم الموقع ملفات تعريف الارتباط وتقنيات قياس الأداء والتحليلات لفهم حركة الزيارات وتحسين سرعة
            الموقع وتجربة البحث. يمكنك التحكم في ملفات تعريف الارتباط أو تعطيلها في أي وقت من خلال إعدادات متصفحك.
          </p>
        </section>

        <section className="ptr-legal-block">
          <h2>3. الإعلانات وخدمات الطرف الثالث (Google AdSense)</h2>
          <p>
            قد نعرض إعلانات مقدمة من شبكات إعلانية خارجية بما في ذلك <strong>Google AdSense</strong> لدعم استمرارية
            الخدمة مجاناً:
          </p>
          <ul>
            <li>
              يستخدم موردو الطرف الثالث، بما في ذلك شركة Google، ملفات تعريف الارتباط لعرض إعلانات بناءً على زياراتك
              السابقة لموقعنا أو لمواقع أخرى على الإنترنت.
            </li>
            <li>
              يتيح استخدام Google لملفات تعريف الارتباط الإعلانية لها ولشركائها عرض إعلانات ملائمة للمستخدمين بناءً
              على تصفحهم.
            </li>
            <li>
              يمكنك إيقاف الإعلانات المخصصة في أي وقت عبر زيارة{" "}
              <a
                className="ptr-link"
                href="https://adssettings.google.com"
                target="_blank"
                rel="noopener noreferrer"
              >
                إعدادات إعلانات Google
              </a>{" "}
              أو موقع{" "}
              <a
                className="ptr-link"
                href="https://www.aboutads.info/choices/"
                target="_blank"
                rel="noopener noreferrer"
              >
                aboutads.info
              </a>
              .
            </li>
          </ul>
        </section>

        <section className="ptr-legal-block">
          <h2>4. روابط المتاجر الخارجية والتسويق بالعمولة</h2>
          <p>
            يحتوي الموقع على روابط تنتقل بك مباشرة إلى المتاجر الإلكترونية المصرية. عند مغادرة موقع{" "}
            <strong>{SITE_NAME_AR}</strong> إلى أي متجر خارجي، تخضع تفاعلاتك لسياسة الخصوصية الخاصة بذلك المتجر.
            قد تتضمن بعض الروابط وسوم تسويق بالعمولة لمساعدتنا في تشغيل الخدمة دون أي رسوم إضافية عليك.
          </p>
        </section>

        <section className="ptr-legal-block">
          <h2>5. حذف بياناتك والتواصل</h2>
          <p>
            لا نبيع أو نشارك بريدك الإلكتروني مع أي جهات تسويقية خارجية. لطلب حذف أي تنبيه سعر نشط أو لأي استفسار
            يتعلق بالخصوصية، راسلنا على{" "}
            <a className="ptr-link" href={`mailto:${CONTACT_EMAIL}`}>
              {CONTACT_EMAIL}
            </a>
            .
          </p>
        </section>

        <section className="ptr-legal-block ptr-legal-en" dir="ltr" lang="en">
          <h2>Privacy Policy (English Summary)</h2>
          <p>
            {SITE_NAME} ({SITE_DOMAIN}) does not require account registration. Optional price-drop alert emails or
            Telegram identifiers are used solely to notify you when a tracked product reaches your target price. We
            may use cookies, analytics, and third-party advertising networks including Google AdSense, which may use
            cookies to serve relevant ads. You can manage ad personalization at{" "}
            <a
              className="ptr-link"
              href="https://adssettings.google.com"
              target="_blank"
              rel="noopener noreferrer"
            >
              Google Ad Settings
            </a>
            . For privacy or deletion requests, email{" "}
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
