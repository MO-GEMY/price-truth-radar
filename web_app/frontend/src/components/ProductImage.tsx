"use client";

/* eslint-disable @next/next/no-img-element */

import { useEffect, useRef, useState } from "react";
import {
  Coffee,
  CookingPot,
  CupSoda,
  Droplets,
  Fan,
  Footprints,
  Gamepad2,
  Headphones,
  Home,
  Laptop,
  Microwave,
  Monitor,
  Milk,
  PackageOpen,
  Refrigerator,
  ShoppingBasket,
  Shirt,
  Smartphone,
  SprayCan,
  Tv,
  Wheat,
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
  oils_ghee: Droplets,
  rice_pasta: Wheat,
  dairy_cheese: Milk,
  tea_coffee: Coffee,
  canned_sauces: CookingPot,
  beverages: CupSoda,
  detergents: SprayCan,
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
  objectPosition?: "center" | "top";
  /** Renders retailer photos inside a crisp white studio frame (ideal for e-commerce cutouts). */
  studio?: boolean;
  dimmed?: boolean;
  zoomOnGroupHover?: boolean;
  priority?: boolean;
  className?: string;
}

/**
 * Studio-clean product thumbnail with light-frame shimmer and branded dark
 * fallback so retailer photos with white backgrounds integrate cleanly onto
 * the dark obsidian canvas without jagged edges or broken-image icons.
 */
export function ProductImage({
  src,
  alt,
  category,
  subCategory,
  brand,
  fit = "contain",
  objectPosition = "center",
  studio = true,
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
        : category === "groceries"
          ? ShoppingBasket
          : Shirt) ??
    PackageOpen;

  const isFailed = status === "error" || !validUrl;
  const fitClass =
    fit === "contain"
      ? "object-contain p-3.5"
      : objectPosition === "top"
        ? "object-cover object-top"
        : "object-cover object-center";
  const labelText = [brand, subCategory?.replace(/_/g, " ")].filter(Boolean).join(" · ");

  return (
    <div
      className={`relative overflow-hidden ${
        !isFailed && studio ? "studio-frame" : "bg-[#111827]"
      } ${className}`}
    >
      {/* Loading shimmer behind image until decoded */}
      {status === "loading" && validUrl ? (
        <div
          className={`absolute inset-0 flex items-center justify-center ${
            studio ? "skeleton-light" : "skeleton rounded-none"
          }`}
          aria-hidden
        >
          <FallbackIcon
            className={`size-8 ${studio ? "text-slate-300" : "text-slate-700"}`}
            strokeWidth={1.5}
          />
        </div>
      ) : null}

      {/* Branded dark fallback when image URL is missing or fails to load */}
      {isFailed ? (
        <div
          role="img"
          aria-label={alt}
          className={`flex h-full w-full flex-col items-center justify-center gap-2 bg-gradient-to-br from-[#0e1627] via-[#090f1c] to-[#050810] px-4 text-center ${
            dimmed ? "opacity-50 saturate-0" : ""
          }`}
        >
          <span className="flex size-11 items-center justify-center rounded-xl border border-white/10 bg-white/[0.04] text-slate-400">
            <FallbackIcon className="size-5" strokeWidth={1.6} />
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
                ? "opacity-45 saturate-0"
                : "opacity-100"
          } ${zoomOnGroupHover ? "group-hover:scale-[1.04]" : ""}`}
        />
      )}
    </div>
  );
}
