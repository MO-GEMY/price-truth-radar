import type { Metadata } from "next";
import { SITE_NAME_AR, absoluteUrl } from "@/lib/site";

export const metadata: Metadata = {
  title: `تنبيهاتي — My Price Alerts`,
  description: `تابع تنبيهات انخفاض الأسعار المحفوظة على متصفحك في ${SITE_NAME_AR} وقارن السعر المستهدف بالسعر الحالي اليوم — Track your saved EGP price-drop alerts and cancel anytime.`,
  alternates: {
    canonical: absoluteUrl("/my-alerts"),
  },
  robots: {
    index: false,
    follow: true,
  },
};

export default function MyAlertsLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return children;
}
