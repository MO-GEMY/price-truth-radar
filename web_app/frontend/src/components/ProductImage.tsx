"use client";

/* eslint-disable @next/next/no-img-element */

import { useEffect, useRef, useState } from "react";
import {
  Fan,
  Footprints,
  Gamepad2,
  Headphones,
  Home,
  Laptop,
  Microwave,
  Monitor,
  PackageOpen,
  Refrigerator,
  Shirt,
  Smartphone,
  Tv,
  Wind,
  type LucideIcon,
} from "lucide-react";
import type { Category } from "@/types/contract";

const SUBCATEGORY_ICON: Record<string, LucideIcon> = {
  smartphones: Smartphone,
  laptops: Laptop,
  monitors: Monitor,
  headphones: Headphones,
  gaming_consoles: Gamepad2,
  gaming: Gamepad2,
  tvs: Tv,
  air_conditioners: Wind,
  fans: Fan,
  refrigerators: Refrigerator,
  freezers: Refrigerator,
  microwaves: Microwave,
  ovens: Microwave,
  cookers: Microwave,
  kitchen_appliances: Microwave,
  large_appliances: Home,
  small_appliances: Home,
  washing_machines: Home,
  dishwashers: Home,
  vacuums: Home,
  water_heaters: Home,
  hoodies: Shirt,
  tees: Shirt,
  t_shirts: Shirt,
  knitwear: Shirt,
  jeans: Shirt,
  sneakers: Footprints,
  shoes: Footprints,
  footwear: Footprints,
};

function isUsableImageUrl(url: string | null | undefined): url is string {
  if (!url) return false;
  const trimmed = url.trim();
  if (trimmed.length === 0) return false;
  return /^(https?:\/\/|\/)/i.test(trimmed);
}

export interface ProductImageProps {
  src: string | null | undefined;
  alt: string;
  category: Category;
  subCategory?: string;
  brand?: string;
  fit?: "cover" | "contain";
  dimmed?: boolean;
  zoomOnGroupHover?: boolean;
  priority?: boolean;
  className?: string;
}

/**
 * Resilient product image with shimmer loading state and a clean branded
 * category fallback so slow, missing, or broken URLs never show raw browser
 * broken-image icons or clipped alt text.
 */
export function ProductImage({
  src,
  alt,
  category,
  subCategory,
  brand,
  fit = "cover",
  dimmed = false,
  zoomOnGroupHover = false,
  priority = false,
  className = "",
}: ProductImageProps) {
  const validUrl = isUsableImageUrl(src) ? src.trim() : null;
  const [status, setStatus] = useState<"loading" | "loaded" | "error">(
    validUrl ? "loading" : "error",
  );
  const imgRef = useRef<HTMLImageElement | null>(null);

  useEffect(() => {
    if (!validUrl) {
      setStatus("error");
      return;
    }
    const img = imgRef.current;
    if (img && img.complete) {
      setStatus(img.naturalWidth > 0 ? "loaded" : "error");
    } else {
      setStatus("loading");
    }
  }, [validUrl]);

  const FallbackIcon =
    (subCategory ? SUBCATEGORY_ICON[subCategory.toLowerCase()] : undefined) ??
    (category === "electronics"
      ? Laptop
      : category === "home_appliances"
        ? Home
        : Shirt) ??
    PackageOpen;

  const fitClass = fit === "contain" ? "object-contain p-3" : "object-cover";
  const labelText = [brand, subCategory?.replace(/_/g, " ")].filter(Boolean).join(" · ");

  return (
    <div
      className={`relative overflow-hidden bg-slate-900/80 ${className}`}
    >
      {/* Loading shimmer behind image until decoded */}
      {status === "loading" && validUrl ? (
        <div
          className="skeleton absolute inset-0 flex items-center justify-center rounded-none"
          aria-hidden
        >
          <FallbackIcon className="size-8 text-slate-700" strokeWidth={1.5} />
        </div>
      ) : null}

      {/* Branded fallback when image URL is missing or fails to load */}
      {status === "error" || !validUrl ? (
        <div
          role="img"
          aria-label={alt}
          className={`flex h-full w-full flex-col items-center justify-center gap-2 bg-gradient-to-br from-slate-800/80 via-slate-900/90 to-[#070d1a] px-4 text-center ${
            dimmed ? "opacity-50 saturate-0" : ""
          }`}
        >
          <span className="flex size-12 items-center justify-center rounded-2xl border border-white/10 bg-white/[0.04] text-slate-400">
            <FallbackIcon className="size-6" strokeWidth={1.6} />
          </span>
          {labelText ? (
            <span className="max-w-full truncate text-[11px] font-medium text-slate-500">
              {labelText}
            </span>
          ) : null}
        </div>
      ) : (
        <img
          ref={imgRef}
          src={validUrl}
          alt={alt}
          loading={priority ? "eager" : "lazy"}
          decoding="async"
          referrerPolicy="no-referrer"
          onLoad={(e) => {
            if (e.currentTarget.naturalWidth > 0) {
              setStatus("loaded");
            } else {
              setStatus("error");
            }
          }}
          onError={() => setStatus("error")}
          className={`h-full w-full transition-all duration-300 ${fitClass} ${
            status !== "loaded"
              ? "opacity-0"
              : dimmed
                ? "opacity-40 saturate-0"
                : "opacity-100"
          } ${zoomOnGroupHover ? "group-hover:scale-[1.04]" : ""}`}
        />
      )}
    </div>
  );
}
