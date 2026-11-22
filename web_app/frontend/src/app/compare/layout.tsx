import type { Metadata } from "next";
import { absoluteUrl, SITE_NAME } from "@/lib/site";

const title = "Compare stores";
const description = "Compare observed prices and availability for matched offers across Egyptian retailers.";

export const metadata: Metadata = {
  title,
  description,
  alternates: { canonical: absoluteUrl("/compare") },
  openGraph: { title, description, url: absoluteUrl("/compare"), siteName: SITE_NAME, locale: "en_EG", alternateLocale: ["ar_EG"] },
  twitter: { card: "summary_large_image", title, description },
};

export default function CompareLayout({ children }: { children: React.ReactNode }) {
  return children;
}
