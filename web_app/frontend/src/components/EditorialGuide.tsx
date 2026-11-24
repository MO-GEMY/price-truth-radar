"use client";

import Link from "next/link";
import { useLanguage } from "@/lib/i18n";

type EditorialVariant = "home" | "deals" | "compare";

interface GuideBlock {
  title: string;
  body: string;
}

interface GuideContent {
  eyebrow: string;
  heading: string;
  lead: string;
  blocks: readonly GuideBlock[];
  footerNote: string;
}

const CONTENT: Record<EditorialVariant, { ar: GuideContent; en: GuideContent }> = {
  home: {
    ar: {
      eyebrow: "دليل المشتري المصري · شفافية الأسعار",
      heading: "كيف يكشف أسعارك الخصومات الوهمية عبر 200 متجر مصري؟",
      lead:
        "قبل أن تشتري في عروض البلاك فرايداي أو التخفيضات الموسمية في مصر، يعرض لك أسعارك سجل السعر الفعلي بالجنيه المصري بدلاً من الاعتماد على السعر المشطوب الذي يكتبه المتجر.",
      blocks: [
        {
          title: "1. مقارنة السعر بوسيط آخر 60 يوماً",
          body:
            "نلتقط أسعار أكثر من 112,000 منتج يومياً عبر متاجر الإلكترونيات، الأجهزة المنزلية، الأزياء، الصيدليات، والهايبرماركت في مصر. نحسب وسيط السعر الحقيقي خلال 60 يوماً لنكشف فوراً هل السعر الحالي خصم فعلي أم مجرد عودة للسعر الطبيعي بعد تضخيم مؤقت.",
        },
        {
          title: "2. قواعد صارمة تمنع التقييمات المتسرّعة",
          body:
            "لا يصدر أسعارك وسم «خصم حقيقي» أو «خصم وهمي» عشوائياً؛ بل يشترط تراكم 3 أيام رصد على الأقل أو ملاحظة تغيّر سعري فعلي. المنتجات الجديدة تظهر بوضوح في مرحلة تجميع سجل الأسعار لحماية دقة القرار.",
        },
        {
          title: "3. ابحث بالاسم أو الصق رابط المنتج مباشرة",
          body:
            "يمكنك البحث باسم الموديل بالعربية أو الإنجليزية، أو لصق رابط أي منتج من أمازون مصر أو نون أو بي تك أو جوميا أو غيرها للاطلاع على تاريخ السعر، والبدائل المتطابقة والمشابهة، وتفعيل تنبيه مجاني عند انخفاض السعر.",
        },
      ],
      footerNote: "هل تريد معرفة المزيد عن منهجية الرصد اليومي ومصادر البيانات؟",
    },
    en: {
      eyebrow: "EGYPTIAN SHOPPER GUIDE · PRICE TRANSPARENCY",
      heading: "How Asarak Verifies Fake Discounts Across 200 Egyptian Stores",
      lead:
        "Before buying during White Friday or seasonal sales in Egypt, Asarak checks every retailer's strikethrough price against independent daily EGP price history.",
      blocks: [
        {
          title: "1. Measured Against a 60-Day Historical Median",
          body:
            "We record daily EGP snapshots for over 112,000 products across Egyptian electronics, home appliances, fashion, pharmacies, and supermarkets. Comparing today's checkout price to the 60-day median reveals whether a deal is genuine or an inflated strikethrough mark-up.",
        },
        {
          title: "2. Evidence-First Verdict Rules",
          body:
            "Asarak never guesses discount honesty from a single snapshot. A verdict is only issued after at least 3 days of recorded observations or an observed price change—preventing false alarms on newly tracked products.",
        },
        {
          title: "3. Paste Any Store URL or Compare Across Retailers",
          body:
            "Search by model name in Arabic or English, or paste a direct product link from Amazon Egypt, Noon, B.TECH, Jumia, and 200 local retailers to inspect the price receipt, check cross-store offers, and set free price-drop alerts.",
        },
      ],
      footerNote: "Want full details on our daily snapshot methodology and data sources?",
    },
  },
  deals: {
    ar: {
      eyebrow: "فهم العروض اليومية · مصر",
      heading: "الفرق بين الخصم الحقيقي والتخفيض الوهمي في المتاجر المصرية",
      lead:
        "تقسّم صفحة أبرز الأسعار العروض اليومية إلى قسمين واضحين حتى تميّز بسهولة بين التخفيض الموثّق بسجل تاريخي والخصم الترويجي المبالغ فيه.",
      blocks: [
        {
          title: "أقل من الوسيط المرصود (خصومات حقيقية)",
          body:
            "تضم المنتجات التي انخفض سعرها الحالي فعلياً عن وسيط أسعارها المرصودة خلال الأسابيع الماضية بالجنيه المصري، مع توضيح نسبة التوفير الحقيقية وأقل سعر تاريخي تم تسجيله.",
        },
        {
          title: "خصومات تحتاج مراجعة (تضخيم السعر المشطوب)",
          body:
            "ترصد العروض التي يرفع فيها المتجر السعر الأصلي المشطوب أو يرفع السعر قبل فترة التخفيضات ثم يعلن خصماً كبيراً رغم أن سعر البيع الفعلي مساوٍ أو أعلى من السعر المعتاد.",
        },
        {
          title: "لماذا نعرض السعر الأساسي بجانب نسبة الخصم؟",
          body:
            "قد يعلن متجر خصماً بنسبة 30% بينما يبيع متجر آخر نفس الموديل بسعر أقل بدون أي لافتة خصم. لذلك نعرض السعر الفعلي والوسيط التاريخي جنباً إلى جنب لتقرر بالرقم لا بالنسبة المئوية.",
        },
      ],
      footerNote: "قارن نفس الموديل بين المتاجر أو راجع منهجية أسعارك الكاملة.",
    },
    en: {
      eyebrow: "DAILY DEAL VERIFICATION · EGYPT",
      heading: "How to Tell Real EGP Price Drops from Inflated Sale Tags",
      lead:
        "Asarak separates daily highlights into two evidence-backed tabs so shoppers can immediately distinguish verified discounts from deceptive strikethrough pricing.",
      blocks: [
        {
          title: "Below Tracked Median (Verified Real Drops)",
          body:
            "Highlights listings where today's in-stock price is demonstrably below the store's own recent 60-day EGP median, backed by multi-day observation history rather than marketing claims.",
        },
        {
          title: "Discounts to Check (Inflated Reference Prices)",
          body:
            "Flags listings advertising steep percentage discounts where the claimed original price sits well above the product's usual selling price—or where the price was raised right before a sale event.",
        },
        {
          title: "Compare Real Checkout Price, Not Just Percentages",
          body:
            "A store advertising 30% off can still charge more than a competitor offering zero discount badge. Always check both the EGP baseline and matched store alternatives before checking out.",
        },
      ],
      footerNote: "Explore cross-store price gaps or read more about Asarak's methodology.",
    },
  },
  compare: {
    ar: {
      eyebrow: "مقارنة المتاجر · الجنيه المصري",
      heading: "كيف يطابق أسعارك نفس المنتج عبر المتاجر المصرية؟",
      lead:
        "كثيراً ما يختلف سعر نفس الموبايل أو الشاشة أو الجهاز المنزلي بنسبة تتراوح بين 10% و30% بين متجر مصري وآخر في نفس اليوم. تجمع صفحة المقارنة العروض المتطابقة في مكان واحد.",
      blocks: [
        {
          title: "مطابقة دقيقة بالموديل والباركود (EAN / SKU)",
          body:
            "نوحّد أسماء المنتجات ونطابق رموز الموديل والمواصفات الأساسية (مثل السعة التخزينية والحجم والعبوة) عبر المتاجر المصرية حتى تقارن عروضاً متكافئة بالفعل وليس موديلات مختلفة.",
        },
        {
          title: "فهم «أقل سعر متوفر» و«فرق السعر المرصود»",
          body:
            "يُظهر كل منتج أدنى سعر متوفر حالياً في المخزون إلى جانب الفجوة السعرية بالجنيه والنسبة المئوية بين أرخص وأغلى متجر، مع استبعاد العروض غير المتوفرة من حساب الأرخص.",
        },
        {
          title: "السعر الأقل ومصداقية الخصم مؤشران منفصلان",
          body:
            "نعرض سعر كل متجر وتقييم مصداقية خصمه بشكل منفصل لتعرف أرخص متجر متاح للشراء الآن، وهل السعر الحالي يمثل فرصة شراء قوية مقارنة بسجل الشهرين الماضيين.",
        },
      ],
      footerNote: "اكتشف أبرز التخفيضات الحقيقية اليوم أو تعرف على سياسة الشفافية لدينا.",
    },
    en: {
      eyebrow: "CROSS-STORE COMPARISON · EGP",
      heading: "How Asarak Matches Identical Products Across Egyptian Retailers",
      lead:
        "The exact same phone, TV, appliance, or perfume often varies by 10% to 30% in EGP across Egyptian stores on the same day. This page brings verified store matches together.",
      blocks: [
        {
          title: "Model, Barcode (EAN/SKU) & Spec Matching",
          body:
            "We normalize Arabic and English titles alongside key specifications—storage capacity, screen size, and pack weight—so you compare genuinely equivalent offers across Amazon Egypt, Noon, B.TECH, Jumia, and specialty retailers.",
        },
        {
          title: "Reading Lowest Available Price & Tracked Spread",
          body:
            "Each group highlights the lowest currently in-stock EGP price alongside the full tracked spread in EGP and percentage terms, ensuring out-of-stock listings never distort the cheapest offer.",
        },
        {
          title: "Lowest Price vs. Discount Honesty",
          body:
            "Store price ranking and discount honesty are displayed separately so you can spot the cheapest retailer immediately while checking whether today's market price is historically low.",
        },
      ],
      footerNote: "Browse today's verified price highlights or read more about how Asarak works.",
    },
  },
};

export function EditorialGuide({ variant }: { variant: EditorialVariant }) {
  const { lang } = useLanguage();
  const copy = CONTENT[variant][lang === "ar" ? "ar" : "en"];

  return (
    <section
      className="surface ptr-section ptr-editorial"
      aria-labelledby={`editorial-${variant}-heading`}
    >
      <div className="ptr-editorial-head">
        <p className="ptr-eyebrow">{copy.eyebrow}</p>
        <h2 id={`editorial-${variant}-heading`}>{copy.heading}</h2>
        <p className="ptr-muted">{copy.lead}</p>
      </div>
      <div className="ptr-editorial-grid">
        {copy.blocks.map((block) => (
          <article key={block.title} className="ptr-editorial-card">
            <h3>{block.title}</h3>
            <p className="ptr-muted">{block.body}</p>
          </article>
        ))}
      </div>
      <div className="ptr-editorial-links">
        <span className="ptr-muted text-sm">{copy.footerNote}</span>
        <div className="ptr-controls text-sm">
          <Link href="/about" className="ptr-link">
            {lang === "ar" ? "منهجية أسعارك" : "About Asarak"}
          </Link>
          {variant !== "deals" && (
            <Link href="/deals" className="ptr-link">
              {lang === "ar" ? "أبرز الأسعار اليوم" : "Price highlights"}
            </Link>
          )}
          {variant !== "compare" && (
            <Link href="/compare" className="ptr-link">
              {lang === "ar" ? "مقارنة المتاجر" : "Compare stores"}
            </Link>
          )}
          <Link href="/privacy" className="ptr-link">
            {lang === "ar" ? "سياسة الخصوصية" : "Privacy policy"}
          </Link>
        </div>
      </div>
    </section>
  );
}
