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
              <strong>نماذج التواصل واقتراح المتاجر:</strong> عند إرسال رسالة عبر صفحة{" "}
              <Link className="ptr-link" href="/contact">
                تواصل معنا
              </Link>{" "}
              أو صفحة{" "}
              <Link className="ptr-link" href="/add-store">
                أضف متجرك
              </Link>
              ، نستخدم البيانات التي تكتبها بنفسك (مثل الاسم والبريد الإلكتروني ونص الرسالة ورابط المتجر
              وبيانات التواصل) لغرض واحد هو الرد عليك أو مراجعة طلبك. تُمرَّر هذه البيانات إلى فريقنا عبر
              مزوّد إرسال البريد أو قناة تليجرام داخلية ولا تُحفَظ في قاعدة بيانات الموقع. ولمنع الرسائل
              المزعجة نحتفظ في ذاكرة الخادم بنسخة مشفّرة من عنوان IP لعدّ معدل الإرسال فقط لفترة قصيرة.
            </li>
            <li>
              <strong>تفضيلات المتصفح المحلية:</strong> نستخدم التخزين المحلي للمتصفح (<code>localStorage</code>)
              لحفظ تفضيل اللغة (العربية أو الإنجليزية) فقط.
            </li>
          </ul>
        </section>

        <section className="ptr-legal-block">
          <h2>2. ملفات تعريف الارتباط (Cookies) وقياس الزيارات (Google Analytics)</h2>
          <p>
            نستخدم <strong>Google Analytics (GA4)</strong> لقياس حركة الزيارات بشكل مجهول الهوية، وفهم الصفحات الأكثر
            استخداماً، وتحسين سرعة البحث وتجربة التصفح دون ربط هذه الإحصائيات بهويتك الشخصية. يتم إرسال بيانات القياس
            في صورة تقارير مجمّعة فقط، كما يمكنك تعطيل ملفات تعريف الارتباط في أي وقت عبر إعدادات متصفحك أو باستخدام{" "}
            <a
              className="ptr-link"
              href="https://tools.google.com/dlpage/gaoptout"
              target="_blank"
              rel="noopener noreferrer"
            >
              إضافة تعطيل Google Analytics
            </a>
            .
          </p>
        </section>

        <section className="ptr-legal-block">
          <h2>3. الإعلانات وخدمات الطرف الثالث (Google AdSense)</h2>
          <p>
            نستعين بشبكات إعلانية خارجية بما في ذلك <strong>Google AdSense</strong> لدعم استمرارية خدمة تتبع ومقارنة
            الأسعار مجاناً:
          </p>
          <ul>
            <li>
              يستخدم موردو الطرف الثالث، بما في ذلك شركة Google، ملفات تعريف الارتباط لعرض إعلانات بناءً على زياراتك
              السابقة لموقعنا ({SITE_DOMAIN}) أو لمواقع أخرى على الإنترنت.
            </li>
            <li>
              يتيح استخدام Google لملفات تعريف الارتباط الإعلانية لها ولشركائها عرض إعلانات ملائمة للمستخدمين بناءً
              على تصفحهم لموقعنا ومواقع أخرى على الويب.
            </li>
            <li>
              يمكنك إيقاف الإعلانات المخصصة في أي وقت عبر زيارة{" "}
              <a
                className="ptr-link"
                href="https://adssettings.google.com"
                target="_blank"
                rel="noopener noreferrer"
              >
                إعدادات إعلانات Google (adssettings.google.com)
              </a>{" "}
              أو موقع{" "}
              <a
                className="ptr-link"
                href="https://www.aboutads.info"
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
            Telegram identifiers are used solely to notify you when a tracked product reaches your target price.
          </p>
          <p>
            Contact and add-store submissions are used only to reply to you or review your request: they are
            forwarded to our team through our email or Telegram provider and are not stored in the site&apos;s
            database. A hashed copy of your IP address is kept in server memory for a short time solely to rate-limit
            the forms.
          </p>
          <ul>
            <li>
              <strong>Google Analytics (GA4):</strong> We use Google Analytics for anonymous traffic measurement,
              performance diagnostics, and aggregate usage statistics. No personally identifiable information is sold
              or shared with marketing brokers.
            </li>
            <li>
              <strong>Google AdSense &amp; Third-Party Cookies:</strong> Third-party vendors, including Google, use
              cookies to serve ads based on a user&apos;s prior visits to {SITE_DOMAIN} or other websites. Google&apos;s
              use of advertising cookies enables it and its partners to serve ads based on visits to this site and/or
              other sites on the Internet.
            </li>
            <li>
              <strong>Opt-Out Controls:</strong> Users may opt out of personalized advertising at any time by visiting{" "}
              <a
                className="ptr-link"
                href="https://adssettings.google.com"
                target="_blank"
                rel="noopener noreferrer"
              >
                Google Ads Settings (adssettings.google.com)
              </a>{" "}
              or by visiting{" "}
              <a
                className="ptr-link"
                href="https://www.aboutads.info"
                target="_blank"
                rel="noopener noreferrer"
              >
                www.aboutads.info
              </a>{" "}
              to opt out of a third-party vendor&apos;s use of cookies for personalized advertising.
            </li>
          </ul>
          <p>
            For privacy or data deletion requests, email{" "}
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
