import type { Metadata } from "next";
import { SITE_NAME_AR, absoluteUrl } from "@/lib/site";

export const metadata: Metadata = {
  title: `تصفّح المنتجات حسب الوسم — Browse Products by Tag`,
  description: `تصفّح المنتجات المرصودة حسب الفئة أو القسم الفرعي أو المتجر أو الماركة على ${SITE_NAME_AR} — Browse tracked Egyptian store listings filtered by category, subcategory, store, or brand.`,
  alternates: {
    canonical: absoluteUrl("/tags"),
  },
  robots: {
    index: false,
    follow: true,
  },
};

export default function TagsLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return children;
}
