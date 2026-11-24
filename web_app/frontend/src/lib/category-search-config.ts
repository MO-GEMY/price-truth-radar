/**
 * Category-aware search placeholders & quick-try examples (AR + EN).
 * Keeps SearchBar contextually tailored to the currently selected category.
 */

import type { Category, FeedCategoryFilter } from "@/types/contract";

export interface CategorySearchCopy {
  placeholderEn: string;
  placeholderAr: string;
  chipsEn: readonly [string, string, string];
  chipsAr: readonly [string, string, string];
}

export const CATEGORY_SEARCH_COPY: Record<Category, CategorySearchCopy> = {
  groceries: {
    placeholderEn: "Search groceries (e.g. Crystal oil, Juhayna milk, pasta, Nescafe)…",
    placeholderAr: "ابحث في السوبر ماركت (مثل: زيت كريستال، لبن جهينة، مكرونة، نسكافيه)…",
    chipsEn: ["Crystal oil", "Juhayna milk", "Nescafe"],
    chipsAr: ["زيت كريستال", "لبن جهينة", "نسكافيه"],
  },
  electronics: {
    placeholderEn: "Search electronics (e.g. iPhone 16, RTX laptop, AirPods, Galaxy S25)…",
    placeholderAr: "ابحث في الإلكترونيات (مثل: آيفون 16، لابتوب، سماعة، شاشة جيمنج)…",
    chipsEn: ["iPhone 16", "AirPods", "Gaming laptop"],
    chipsAr: ["آيفون 16", "سماعة", "لابتوب"],
  },
  home_appliances: {
    placeholderEn: "Search appliances (e.g. Sharp fridge, Carrier AC, LG washer, air fryer)…",
    placeholderAr: "ابحث في الأجهزة المنزلية (مثل: ثلاجة شارب، تكييف كاريير، غسالة، اير فراير)…",
    chipsEn: ["Sharp fridge", "Carrier AC", "Air fryer"],
    chipsAr: ["تلاجة شارب", "تكييف كاريير", "اير فراير"],
  },
  home_furniture: {
    placeholderEn: "Search furniture & home (e.g. L-shape sofa, mattress, Tefal cookware)…",
    placeholderAr: "ابحث في الأثاث والمنزل (مثل: ركنة، مرتبة، طقم حلل، مكتب)…",
    chipsEn: ["Sofa", "Mattress", "Cookware"],
    chipsAr: ["ركنة", "مرتبة", "طقم حلل"],
  },
  fashion: {
    placeholderEn: "Search fashion (e.g. Nike sneakers, hoodie, jeans, leather bag)…",
    placeholderAr: "ابحث في الأزياء (مثل: كوتشي، هودي، جينز، شنطة جلد)…",
    chipsEn: ["Sneakers", "Hoodie", "Jeans"],
    chipsAr: ["كوتشي", "هودي", "جينز"],
  },
  beauty: {
    placeholderEn: "Search beauty & perfumes (e.g. La Roche sunscreen, perfume, shampoo)…",
    placeholderAr: "ابحث في العطور والتجميل (مثل: واقي شمس، برفان، سيروم، شامبو)…",
    chipsEn: ["Sunscreen", "Perfume", "Serum"],
    chipsAr: ["واقي شمس", "برفان", "سيروم"],
  },
  health: {
    placeholderEn: "Search health & pharmacy (e.g. Whey protein, Vitamin D, CeraVe, creatine)…",
    placeholderAr: "ابحث في الصيدليات والصحة (مثل: واي بروتين، فيتامين د، كرياتين، سيرافي)…",
    chipsEn: ["Whey protein", "Vitamin D", "Creatine"],
    chipsAr: ["واي بروتين", "فيتامين د", "كرياتين"],
  },
  sports: {
    placeholderEn: "Search sports & fitness (e.g. Adidas running shoe, dumbbell, padel racket)…",
    placeholderAr: "ابحث في الرياضة واللياقة (مثل: حذاء جري، دمبل، مضرب بادل، مشاية)…",
    chipsEn: ["Running shoes", "Dumbbell", "Padel racket"],
    chipsAr: ["حذاء جري", "دمبل", "مضرب بادل"],
  },
  baby_kids: {
    placeholderEn: "Search baby & kids (e.g. Lego, stroller, kids backpack, Pampers)…",
    placeholderAr: "ابحث في الأطفال والألعاب (مثل: ليجو، عربية أطفال، شنطة مدرسة، ألعاب)…",
    chipsEn: ["Lego", "Stroller", "School bag"],
    chipsAr: ["ليجو", "عربية أطفال", "شنطة مدرسة"],
  },
  pet_care: {
    placeholderEn: "Search pet care (e.g. Royal Canin, cat food, cat litter, dog food)…",
    placeholderAr: "ابحث في مستلزمات الحيوانات (مثل: طعام قطط، رمل قطط، طعام كلاب)…",
    chipsEn: ["Cat food", "Cat litter", "Dog food"],
    chipsAr: ["طعام قطط", "رمل قطط", "طعام كلاب"],
  },
};

export function getCategorySearchCopy(
  category: FeedCategoryFilter,
): CategorySearchCopy | null {
  if (category === "all") return null;
  return CATEGORY_SEARCH_COPY[category] ?? null;
}
