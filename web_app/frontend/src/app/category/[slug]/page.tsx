import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowUpRight } from "lucide-react";
import type { Category, RadarFeedResponse } from "@/types/contract";
import { fetchJson, isApiConfigured } from "@/lib/api";
import { serializeJsonLd } from "@/lib/jsonld";
import {
  CANONICAL_CATEGORIES,
  DEFAULT_OG_IMAGE_PATH,
  LAUNCH_STORE_COUNT,
  SITE_NAME_AR,
  SITE_NAME_BILINGUAL,
  absoluteUrl,
} from "@/lib/site";
import { EditorialGuide } from "@/components/EditorialGuide";
import { ProductCard } from "@/components/ProductCard";

/**
 * Clean, query-string-free canonical category landing page (`/category/<slug>`).
 * Cached 24h at Cloudflare Edge + Next.js ISR (`revalidate = 86400`) to stay
 * crawler-friendly while keeping Neon scaled to zero.
 */
export const revalidate = 86400;

const CATEGORY_SSR_TIMEOUT_MS = 4500;
const CATEGORY_SSR_LIMIT = 24;

interface CategoryMeta {
  ar: string;
  en: string;
  descriptionAr: string;
  descriptionEn: string;
}

const CATEGORY_META: Record<Category, CategoryMeta> = {
  electronics: {
    ar: "الإلكترونيات والموبايلات واللابتوب",
    en: "Electronics, Phones & Laptops",
    descriptionAr:
      "قارن أسعار الموبايلات واللابتوب والشاشات والإلكترونيات في مصر وتحقق من حقيقة الخصومات مقابل سجل آخر 60 يوم.",
    descriptionEn:
      "Compare Egypt prices for smartphones, laptops, TVs, and tech across 200 stores with 60-day price truth.",
  },
  home_appliances: {
    ar: "الأجهزة المنزلية والكهربائية",
    en: "Home Appliances",
    descriptionAr:
      "تابع أسعار الثلاجات والغسالات والتكييفات والبوتاجازات وأجهزة المطبخ في مصر واكتشف الخصومات الحقيقية.",
    descriptionEn:
      "Track real EGP prices on refrigerators, washing machines, ACs, and kitchen appliances across Egyptian stores.",
  },
  home_furniture: {
    ar: "الأثاث والمنزل والمفروشات",
    en: "Home & Furniture",
    descriptionAr:
      "قارن أسعار الأثاث والمراتب والمفروشات وأدوات المطبخ والديكور في مصر بسجل أسعار موثّق.",
    descriptionEn:
      "Compare furniture, mattresses, cookware, and home decor prices in EGP across Egyptian retailers.",
  },
  fashion: {
    ar: "الأزياء والملابس والأحذية",
    en: "Fashion & Footwear",
    descriptionAr:
      "تحقق من خصومات الملابس والأحذية الرياضية والشنط في أشهر متاجر وبراندات مصر بالجنيه المصري.",
    descriptionEn:
      "Verify real fashion, apparel, sneaker, and footwear discounts across Egyptian brands and stores.",
  },
  beauty: {
    ar: "الجمال والعطور والعناية بالبشرة",
    en: "Beauty, Perfumes & Skincare",
    descriptionAr:
      "قارن أسعار العطور ومنتجات العناية بالبشرة والشعر والمكياج في مصر مع متابعة تاريخ السعر الفعلي.",
    descriptionEn:
      "Compare perfumes, skincare, haircare, and cosmetics prices in Egypt with verified discount checks.",
  },
  groceries: {
    ar: "السوبر ماركت والسلع الغذائية",
    en: "Groceries & Supermarket",
    descriptionAr:
      "تابع أسعار السلع الغذائية والزيوت والألبان والمنظفات في الهايبرماركت المصرية وقارن سعر الكيلو واللتر.",
    descriptionEn:
      "Track supermarket and grocery prices in Egypt with unit-price EGP/kg and EGP/L comparisons.",
  },
  health: {
    ar: "الصحة والصيدليات والفيتامينات",
    en: "Health, Pharmacy & Wellness",
    descriptionAr:
      "قارن أسعار المكملات الغذائية والفيتامينات ومستحضرات الصيدليات في مصر بأسعار محدّثة يومياً.",
    descriptionEn:
      "Compare pharmacy wellness products, vitamins, and supplements in EGP across Egyptian stores.",
  },
  sports: {
    ar: "الرياضة واللياقة البدنية",
    en: "Sports & Fitness",
    descriptionAr:
      "تابع أسعار الأجهزة الرياضية والملابس والأحذية الرياضية ومستلزمات الجيم في مصر.",
    descriptionEn:
      "Compare fitness equipment, sportswear, and athletic gear prices across Egyptian retailers.",
  },
  pet_care: {
    ar: "مستلزمات الحيوانات الأليفة",
    en: "Pet Care & Supplies",
    descriptionAr:
      "قارن أسعار طعام القطط والكلاب ورمل القطط ومستلزمات الحيوانات الأليفة في مصر.",
    descriptionEn:
      "Compare cat food, dog food, litter, and pet supplies prices in EGP across Egypt.",
  },
  baby_kids: {
    ar: "مستلزمات الأطفال والألعاب",
    en: "Baby, Kids & Toys",
    descriptionAr:
      "تابع أسعار مستلزمات الرضّع والأطفال والألعاب وملابس الأطفال في المتاجر المصرية.",
    descriptionEn:
      "Track baby gear, kids clothing, and toys prices in EGP across Egyptian stores.",
  },
};

function isCanonicalCategory(slug: string): slug is Category {
  return (CANONICAL_CATEGORIES as readonly string[]).includes(slug);
}

async function loadCategoryFeed(slug: Category): Promise<RadarFeedResponse | null> {
  if (!isApiConfigured()) return null;
  try {
    return await fetchJson<RadarFeedResponse>(
      "/api/v1/radar/feed",
      {
        category: slug,
        sort: "real_discount_pct_desc",
        page: 1,
        limit: CATEGORY_SSR_LIMIT,
      },
      undefined,
      CATEGORY_SSR_TIMEOUT_MS,
      revalidate,
    );
  } catch {
    return null;
  }
}

interface CategoryPageProps {
  params: Promise<{ slug: string }>;
}

export async function generateMetadata({ params }: CategoryPageProps): Promise<Metadata> {
  const { slug } = await params;
  if (!isCanonicalCategory(slug)) {
    return {
      title: "القسم غير موجود — Category Not Found",
      robots: { index: false, follow: false },
    };
  }

  const meta = CATEGORY_META[slug];
  const canonical = absoluteUrl(`/category/${slug}`);
  const ogImage = absoluteUrl(DEFAULT_OG_IMAGE_PATH);
  const title = `أسعار ${meta.ar} في مصر — ${meta.en} Prices Egypt`;
  const description = `${meta.descriptionAr} — ${meta.descriptionEn}`;

  return {
    title,
    description,
    alternates: { canonical },
    openGraph: {
      title: `${title} | ${SITE_NAME_AR}`,
      description,
      url: canonical,
      siteName: SITE_NAME_BILINGUAL,
      locale: "ar_EG",
      alternateLocale: ["en_EG", "en_US"],
      type: "website",
      images: [{ url: ogImage, width: 1200, height: 630, alt: title }],
    },
    twitter: {
      card: "summary_large_image",
      title: `${title} | ${SITE_NAME_AR}`,
      description,
      images: [ogImage],
    },
  };
}

export default async function CategoryPage({ params }: CategoryPageProps) {
  const { slug } = await params;
  if (!isCanonicalCategory(slug)) notFound();

  const meta = CATEGORY_META[slug];
  const feed = await loadCategoryFeed(slug);
  const items = feed?.items ?? [];
  const totalCount = feed?.total ?? 0;
  const canonicalUrl = absoluteUrl(`/category/${slug}`);

  const jsonLd = serializeJsonLd({
    "@context": "https://schema.org",
    "@type": "CollectionPage",
    name: `${meta.ar} — ${meta.en}`,
    description: `${meta.descriptionAr} ${meta.descriptionEn}`,
    url: canonicalUrl,
    mainEntity: {
      "@type": "ItemList",
      numberOfItems: items.length,
      itemListElement: items.slice(0, 24).map((item, idx) => ({
        "@type": "ListItem",
        position: idx + 1,
        url: absoluteUrl(`/products/${encodeURIComponent(item.product_sk)}`),
        name: item.product_title,
      })),
    },
  });

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: jsonLd }}
      />
      <div className="ptr-wrap ptr-page space-y-6">
        <header className="ptr-page-heading space-y-2">
          <p className="ptr-eyebrow">
            {SITE_NAME_BILINGUAL} · {LAUNCH_STORE_COUNT} Stores in EGP
          </p>
          <h1>
            {meta.ar} — {meta.en}
          </h1>
          <p className="ptr-muted">{meta.descriptionAr}</p>
          <p className="text-sm ptr-muted">{meta.descriptionEn}</p>
          <div className="flex flex-wrap items-center gap-2 pt-2">
            {totalCount > 0 && (
              <span className="ptr-badge ptr-badge-good">
                <bdi>{totalCount.toLocaleString("en-US")}</bdi> tracked products
              </span>
            )}
            <Link className="ptr-button ptr-primary" href="/compare">
              Compare Stores <ArrowUpRight size={15} aria-hidden="true" />
            </Link>
            <Link className="ptr-button" href="/deals">
              Verified Deals <ArrowUpRight size={15} aria-hidden="true" />
            </Link>
            <a
              className="ptr-button"
              href={`/?category=${slug}`}
              rel="nofollow"
            >
              Filter &amp; Search Category
            </a>
          </div>
        </header>

        <nav
          aria-label="Categories"
          className="ptr-category-bar"
        >
          {CANONICAL_CATEGORIES.map((cat) => {
            const c = CATEGORY_META[cat];
            const active = cat === slug;
            return (
              <Link
                key={cat}
                href={`/category/${cat}`}
                className="ptr-chip"
                aria-current={active ? "page" : undefined}
              >
                <span>{c.en}</span>
              </Link>
            );
          })}
        </nav>

        <section className="min-w-0 space-y-4">
          {items.length > 0 ? (
            <div className="asarak-product-grid">
              {items.map((product) => (
                <ProductCard
                  key={product.product_sk}
                  product={product}
                  from=""
                  source="api"
                  view="grid"
                />
              ))}
            </div>
          ) : (
            <div className="surface p-6 space-y-2">
              <p className="font-semibold">
                Explore {meta.en} ({meta.ar}) on {SITE_NAME_BILINGUAL}
              </p>
              <p className="ptr-muted text-sm">
                Browse live EGP price history and cross-store comparisons on the{" "}
                <Link className="ptr-link" href="/compare">
                  Compare Stores
                </Link>{" "}
                or{" "}
                <Link className="ptr-link" href="/deals">
                  Verified Deals
                </Link>{" "}
                pages.
              </p>
            </div>
          )}
        </section>

        <EditorialGuide variant="home" />
      </div>
    </>
  );
}
