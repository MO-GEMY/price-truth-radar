import type { Metadata, Viewport } from "next";
import Script from "next/script";
import { Inter, IBM_Plex_Sans_Arabic } from "next/font/google";
import "./globals.css";
import { LanguageProvider } from "@/lib/i18n";
import {
  DEFAULT_OG_IMAGE_PATH,
  LAUNCH_PRODUCT_COUNT,
  LAUNCH_STORE_COUNT,
  SITE_NAME_AR,
  SITE_NAME_BILINGUAL,
  SITE_URL,
  absoluteUrl,
} from "@/lib/site";
import { Header } from "@/components/Header";
import { Footer } from "@/components/Footer";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

const plexArabic = IBM_Plex_Sans_Arabic({
  subsets: ["arabic"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-plex-arabic",
  display: "swap",
});

const HOME_TITLE = `${SITE_NAME_AR} — اكشف الخصومات الوهمية وقارن أسعار ${LAUNCH_STORE_COUNT} متجر مصري | Asarak`;
const HOME_DESCRIPTION = `أسعارك (Asarak): تابع سجل الأسعار الحقيقي وقارن العروض بالجنيه المصري عبر ${LAUNCH_STORE_COUNT} متجر مصري وأكثر من ${LAUNCH_PRODUCT_COUNT} منتج في الإلكترونيات والأجهزة المنزلية والأزياء والصيدليات والهايبرماركت — Track real EGP price history across ${LAUNCH_STORE_COUNT} Egyptian stores and ${LAUNCH_PRODUCT_COUNT} products.`;
const DEFAULT_OG_IMAGE = absoluteUrl(DEFAULT_OG_IMAGE_PATH);

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: HOME_TITLE,
    template: `%s | ${SITE_NAME_AR}`,
  },
  description: HOME_DESCRIPTION,
  applicationName: SITE_NAME_BILINGUAL,
  keywords: [
    "أسعارك",
    "Asarak",
    "مقارنة أسعار مصر",
    "سجل الأسعار مصر",
    "كشف الخصومات الوهمية",
    "عروض البلاك فرايداي مصر",
    "مقارنة أسعار أمازون ونون وبي تك وكارفور",
    "Egypt price tracker",
    "EGP price history",
  ],
  alternates: {
    canonical: absoluteUrl("/"),
  },
  robots: {
    index: true,
    follow: true,
    googleBot: {
      index: true,
      follow: true,
      "max-image-preview": "large",
      "max-snippet": -1,
    },
  },
  openGraph: {
    type: "website",
    url: absoluteUrl("/"),
    siteName: SITE_NAME_BILINGUAL,
    title: HOME_TITLE,
    description: HOME_DESCRIPTION,
    locale: "ar_EG",
    alternateLocale: ["en_EG", "en_US"],
    images: [
      {
        url: DEFAULT_OG_IMAGE,
        width: 1200,
        height: 630,
        alt: HOME_TITLE,
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: HOME_TITLE,
    description: HOME_DESCRIPTION,
    images: [DEFAULT_OG_IMAGE],
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#F7F5EF",
};

/**
 * Applies the persisted language before first paint (prevents an LTR flash
 * for Arabic readers). Kept intentionally tiny and dependency-free.
 */
const EARLY_LANG_SCRIPT = `(function(){try{var l=localStorage.getItem("ptr-lang");if(l==="ar"){var d=document.documentElement;d.lang="ar";d.dir="rtl";d.classList.add("lang-ar");}}catch(e){}})();`;

const ADSENSE_CLIENT = (process.env.NEXT_PUBLIC_ADSENSE_CLIENT ?? "").trim();
const GA_MEASUREMENT_ID = (process.env.NEXT_PUBLIC_GA_MEASUREMENT_ID ?? "").trim();

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      lang="en"
      dir="ltr"
      className={`${inter.variable} ${plexArabic.variable}`}
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: EARLY_LANG_SCRIPT }} />
        {ADSENSE_CLIENT && (
          <script
            async
            src={`https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=${encodeURIComponent(ADSENSE_CLIENT)}`}
            crossOrigin="anonymous"
          />
        )}
      </head>
      <body className="min-h-screen antialiased">
        <LanguageProvider>
          <div className="flex min-h-screen min-w-0 flex-col">
            <Header />
            <main id="main-content" tabIndex={-1} className="min-w-0 flex-1">{children}</main>
            <Footer />
          </div>
        </LanguageProvider>
        {GA_MEASUREMENT_ID && (
          <>
            <Script
              src={`https://www.googletagmanager.com/gtag/js?id=${encodeURIComponent(GA_MEASUREMENT_ID)}`}
              strategy="afterInteractive"
            />
            <Script id="ga4-init" strategy="afterInteractive">
              {`window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}window.gtag=gtag;gtag('js',new Date());gtag('config',${JSON.stringify(GA_MEASUREMENT_ID)},{anonymize_ip:true});`}
            </Script>
          </>
        )}
      </body>
    </html>
  );
}
