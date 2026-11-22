import type { Metadata, Viewport } from "next";
import { Inter, IBM_Plex_Sans_Arabic } from "next/font/google";
import "./globals.css";
import { LanguageProvider } from "@/lib/i18n";
import { SITE_URL } from "@/lib/site";
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

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: "Price Truth Radar — Real discounts vs fake ones",
    template: "%s · Price Truth Radar",
  },
  description:
    "Bilingual price-integrity radar: expose fake discounts and pre-sale hikes, surface genuine deals and all-time lows across Egyptian e-commerce stores. Prices in EGP.",
};

export const viewport: Viewport = {
  themeColor: "#03060b",
};

/**
 * Applies the persisted language before first paint (prevents an LTR flash
 * for Arabic readers). Kept intentionally tiny and dependency-free.
 */
const EARLY_LANG_SCRIPT = `(function(){try{var l=localStorage.getItem("ptr-lang");if(l==="ar"){var d=document.documentElement;d.lang="ar";d.dir="rtl";d.classList.add("lang-ar");}}catch(e){}})();`;

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
      </head>
      <body className="min-h-screen antialiased">
        <LanguageProvider>
          <div className="flex min-h-screen flex-col">
            <Header />
            <main className="flex-1">{children}</main>
            <Footer />
          </div>
        </LanguageProvider>
      </body>
    </html>
  );
}
