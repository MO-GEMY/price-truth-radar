"use client";

import Link from "next/link";
import { useLanguage } from "@/lib/i18n";

export default function MissingProduct() {
  const { t } = useLanguage();
  return (
    <div className="ptr-wrap ptr-page">
      <div className="surface ptr-empty">
        <h1 className="text-2xl font-bold">{t("detail.notFound")}</h1>
        <p className="ptr-muted">{t("detail.notFoundBody")}</p>
        <Link href="/" className="ptr-button ptr-primary">{t("nav.feed")}</Link>
      </div>
    </div>
  );
}
