import type { Metadata } from "next";
import { SITE_NAME, absoluteUrl } from "@/lib/site";

const title = "Price highlights";
const description = "Selected listings with recorded price evidence from tracked retailers in Egypt.";

export const metadata: Metadata = {
  title,
  description,
  alternates: { canonical: absoluteUrl("/deals") },
  openGraph: {
    title,
    description,
    url: absoluteUrl("/deals"),
    siteName: SITE_NAME,
    locale: "en_EG",
    alternateLocale: ["ar_EG"],
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title,
    description,
  },
};

export default function DealsLayout({ children }: { children: React.ReactNode }) {
  return children;
}
