/**
 * Display metadata for tracked Egyptian retailers. API payloads always carry
 * the raw `store_name` slug (CONTRACTS.md); this module only maps slugs to
 * polished, bilingual display names and a subtle brand accent dot.
 */

import type { Lang } from "./i18n";

export interface StoreMeta {
  name: { en: string; ar: string };
  domain: string;
  /** Brand accent used only for a small identity dot. */
  accent: string;
  /** Whether pasted product links from this store are matched by direct lookup. */
  urlLookup: boolean;
}

export const STORE_META: Record<string, StoreMeta> = {
  noon: { name: { en: "Noon", ar: "نون" }, domain: "noon.com", accent: "#f5e400", urlLookup: true },
  amazon_eg: {
    name: { en: "Amazon.eg", ar: "أمازون مصر" },
    domain: "amazon.eg",
    accent: "#ff9900",
    urlLookup: true,
  },
  btech: { name: { en: "B.Tech", ar: "بي تك" }, domain: "btech.com", accent: "#ef4444", urlLookup: true },
  "2b": { name: { en: "2B", ar: "2B" }, domain: "2b.com.eg", accent: "#3b82f6", urlLookup: true },
  sigma: {
    name: { en: "Sigma", ar: "سيجما" },
    domain: "sigma-computer.com",
    accent: "#22d3ee",
    urlLookup: true,
  },
  town_team: {
    name: { en: "Town Team", ar: "تاون تيم" },
    domain: "townteam.com",
    accent: "#cbd5e1",
    urlLookup: true,
  },
  dejavu: { name: { en: "Dejavu", ar: "ديجافو" }, domain: "dejavu.shoes", accent: "#e879f9", urlLookup: true },
  dalydress: {
    name: { en: "Daly Dress", ar: "دالي دريس" },
    domain: "dalydress.com",
    accent: "#f9a8d4",
    urlLookup: true,
  },
  spinneys: {
    name: { en: "Spinneys", ar: "سبينيس" },
    domain: "spinneys-egypt.com",
    accent: "#10b981",
    urlLookup: true,
  },
  hyperone: {
    name: { en: "HyperOne", ar: "هايبر وان" },
    domain: "hyperone.com.eg",
    accent: "#e11d48",
    urlLookup: true,
  },
  /* ---- Verified (Wave 3 candidates) ---- */
  seoudi: {
    name: { en: "Seoudi", ar: "سعودي" },
    domain: "seoudisupermarket.com",
    accent: "#f97316",
    urlLookup: true,
  },
  raneen: {
    name: { en: "Raneen", ar: "رنين" },
    domain: "raneen.com",
    accent: "#8b5cf6",
    urlLookup: true,
  },
  rayashop: {
    name: { en: "Raya Shop", ar: "راية شوب" },
    domain: "rayashop.com",
    accent: "#0ea5e9",
    urlLookup: true,
  },
  /* ---- Fashion & footwear candidates ---- */
  ravin: { name: { en: "Ravin", ar: "رافين" }, domain: "ravin.eg", accent: "#f43f5e", urlLookup: true },
  activ: {
    name: { en: "Activ Abou Alaa", ar: "أكتيف أبو علاء" },
    domain: "activaboualaa.com",
    accent: "#f59e0b",
    urlLookup: true,
  },
  mobaco: { name: { en: "Mobaco", ar: "موباكو" }, domain: "mobaco.com", accent: "#84cc16", urlLookup: true },
  concrete: {
    name: { en: "Concrete", ar: "كونكريت" },
    domain: "concrete.com.eg",
    accent: "#64748b",
    urlLookup: true,
  },
  tiehouse: {
    name: { en: "Tie House", ar: "تاي هاوس" },
    domain: "tiehouse.com",
    accent: "#a16207",
    urlLookup: true,
  },
  khotwh: { name: { en: "Khotwh", ar: "خطوة" }, domain: "khotwh.com", accent: "#059669", urlLookup: true },
  carina: { name: { en: "Carina", ar: "كارينا" }, domain: "carinawear.com", accent: "#ec4899", urlLookup: true },
  tomato: { name: { en: "Tomato", ar: "توماتو" }, domain: "tomato.com.eg", accent: "#dc2626", urlLookup: true },
  mitcha: { name: { en: "Mitcha", ar: "ميتشا" }, domain: "mitcha.com", accent: "#c084fc", urlLookup: true },
  lcwaikiki: {
    name: { en: "LC Waikiki", ar: "إل سي وايكيكي" },
    domain: "lcwaikiki.eg",
    accent: "#2563eb",
    urlLookup: true,
  },
  defacto: {
    name: { en: "DeFacto", ar: "ديفاكتو" },
    domain: "defacto.com",
    accent: "#475569",
    urlLookup: true,
  },
  /* ---- Groceries & food candidates ---- */
  gourmet: {
    name: { en: "Gourmet Egypt", ar: "جورميه مصر" },
    domain: "gourmetegypt.com",
    accent: "#d946ef",
    urlLookup: true,
  },
  metro_market: {
    name: { en: "Metro Market", ar: "مترو ماركت" },
    domain: "metro-markets.com",
    accent: "#eab308",
    urlLookup: true,
  },
  oscar: { name: { en: "Oscar", ar: "أوسكار" }, domain: "oscarstores.com", accent: "#14b8a6", urlLookup: true },
  abu_auf: { name: { en: "Abu Auf", ar: "أبو عوف" }, domain: "abuauf.com", accent: "#92400e", urlLookup: true },
  imtenan: { name: { en: "Imtenan", ar: "امتنان" }, domain: "imtenan.com", accent: "#65a30d", urlLookup: true },
  fathalla: {
    name: { en: "Fathalla Market", ar: "فتح الله ماركت" },
    domain: "fathallamarket.com",
    accent: "#0891b2",
    urlLookup: true,
  },
  breadfast: {
    name: { en: "Breadfast", ar: "بريدفاست" },
    domain: "breadfast.com",
    accent: "#fb923c",
    urlLookup: false,
  },
  talabat_eg: {
    name: { en: "Talabat Egypt", ar: "طلبات مصر" },
    domain: "talabat.com",
    accent: "#ff5a00",
    urlLookup: true,
  },
  /* ---- Electronics, PC & appliances candidates ---- */
  elaraby: {
    name: { en: "El Araby", ar: "العربي جروب" },
    domain: "elarabygroup.com",
    accent: "#b91c1c",
    urlLookup: true,
  },
  compuscience: {
    name: { en: "CompuScience", ar: "كومبيوساينس" },
    domain: "compuscience.com.eg",
    accent: "#7c3aed",
    urlLookup: true,
  },
  elbadr: {
    name: { en: "El Badr Group", ar: "البدر جروب" },
    domain: "elbadrgroupeg.store",
    accent: "#facc15",
    urlLookup: true,
  },
  compumarts: {
    name: { en: "CompuMarts", ar: "كومبيومارتس" },
    domain: "compumarts.com",
    accent: "#0e7490",
    urlLookup: true,
  },
  egyptlaptop: {
    name: { en: "Egypt Laptop", ar: "إيجيبت لابتوب" },
    domain: "egyptlaptop.com",
    accent: "#334155",
    urlLookup: true,
  },
  dubaiphone: {
    name: { en: "Dubai Phone", ar: "دبي فون" },
    domain: "dubaiphone.net",
    accent: "#ea580c",
    urlLookup: true,
  },
  tradeline: {
    name: { en: "Tradeline", ar: "تريدلاين" },
    domain: "tradelineegypt.com",
    accent: "#16a34a",
    urlLookup: true,
  },
  cairosales: {
    name: { en: "Cairo Sales", ar: "كايرو سيلز" },
    domain: "cairosales.com",
    accent: "#db2777",
    urlLookup: true,
  },
  aswaq_mozhela: {
    name: { en: "Aswaq Mozhela", ar: "أسواق مذهلة" },
    domain: "play.google.com",
    accent: "#f59e0b",
    urlLookup: false,
  },
  madiesta: {
    name: { en: "Madiesta", ar: "ماديستا" },
    domain: "sllr.co",
    accent: "#16a34a",
    urlLookup: true,
  },
  mi_egypt: {
    name: { en: "Mi Store Egypt", ar: "شاومي مصر" },
    domain: "mistore-eg.com",
    accent: "#ff6900",
    urlLookup: true,
  },
  samsung_eg: {
    name: { en: "Samsung Egypt", ar: "سامسونج مصر" },
    domain: "samsung.com",
    accent: "#1428a0",
    urlLookup: true,
  },
  max_fashion_eg: {
    name: { en: "Max Fashion Egypt", ar: "ماكس فاشون مصر" },
    domain: "maxfashion.com",
    accent: "#e11d48",
    urlLookup: true,
  },
  oraimo_eg: {
    name: { en: "Oraimo Egypt", ar: "أورايمو مصر" },
    domain: "eg.oraimo.com",
    accent: "#84cc16",
    urlLookup: true,
  },
  bath_and_body_works_eg: {
    name: { en: "Bath & Body Works Egypt", ar: "باث آند بودي وركس مصر" },
    domain: "bathandbodyworks.com.eg",
    accent: "#2563eb",
    urlLookup: true,
  },
  the_body_shop_eg: {
    name: { en: "The Body Shop (Est. EGP)", ar: "ذا بودي شوب (سعر تقريبي)" },
    domain: "thebodyshop.ae",
    accent: "#15803d",
    urlLookup: false,
  },
  olympic_electric: {
    name: { en: "Olympic Electric", ar: "أوليمبيك إلكتريك" },
    domain: "olympic-electric.com",
    accent: "#ef4444",
    urlLookup: true,
  },
  fut_electronics: {
    name: { en: "Future Electronics EG", ar: "فيوتشر إلكترونكس" },
    domain: "store.fut-electronics.com",
    accent: "#3b82f6",
    urlLookup: true,
  },
  enarat: {
    name: { en: "Enarat", ar: "إنارات" },
    domain: "enarat.com",
    accent: "#f59e0b",
    urlLookup: true,
  },
  gc_shop_eg: {
    name: { en: "GC Shop Egypt", ar: "جي سي شوب" },
    domain: "gcshopeg.com",
    accent: "#ec4899",
    urlLookup: true,
  },
  mavin_wear: {
    name: { en: "Mavin Wear", ar: "مافين وير" },
    domain: "mavin-wear.com",
    accent: "#ec4899",
    urlLookup: true,
  },
  ramla_store: {
    name: { en: "Ramla Store", ar: "رملة" },
    domain: "ramlastore.com",
    accent: "#ec4899",
    urlLookup: true,
  },
  ecadra: {
    name: { en: "Ecadra", ar: "إيكادرا" },
    domain: "ecadra.com",
    accent: "#ec4899",
    urlLookup: true,
  },
  versattire: {
    name: { en: "Versattire", ar: "فيرساتاير" },
    domain: "versattirecollections.com",
    accent: "#ec4899",
    urlLookup: true,
  },
  twentyseven_eg: {
    name: { en: "27 Egypt", ar: "27 إيجيبت" },
    domain: "twentyseven-eg.com",
    accent: "#ec4899",
    urlLookup: true,
  },
  le_voile: {
    name: { en: "Le Voile", ar: "لو فوال" },
    domain: "levoilestores.com",
    accent: "#ec4899",
    urlLookup: true,
  },
  tree_stores: {
    name: { en: "Tree Stores", ar: "تري ستورز" },
    domain: "tree-stores.com",
    accent: "#ec4899",
    urlLookup: true,
  },
  footcourt_eg: {
    name: { en: "Footcourt Egypt", ar: "فوت كورت" },
    domain: "footcourt-eg.com",
    accent: "#ec4899",
    urlLookup: true,
  },
  essentials_egy: {
    name: { en: "Essentials Egypt", ar: "إيسنشالز إيجيبت" },
    domain: "essentials-egy.com",
    accent: "#ec4899",
    urlLookup: true,
  },
  katerji_leather: {
    name: { en: "Katerji Leather", ar: "كاترجي للجلود" },
    domain: "katerjileather.com",
    accent: "#ec4899",
    urlLookup: true,
  },
  jlood_eg: {
    name: { en: "Jlood Egypt", ar: "جلود" },
    domain: "jlood.com",
    accent: "#ec4899",
    urlLookup: true,
  },
  the_closet_eg: {
    name: { en: "The Closet Egypt", ar: "ذا كلوزيت" },
    domain: "theclosetonlineshop.com",
    accent: "#ec4899",
    urlLookup: true,
  },
  binokids: {
    name: { en: "Bino Kids", ar: "بينو كيدز" },
    domain: "binokids.com",
    accent: "#8b5cf6",
    urlLookup: true,
  },
  junior_tex: {
    name: { en: "Junior Tex", ar: "جونيور تكس" },
    domain: "junior-tex.com",
    accent: "#8b5cf6",
    urlLookup: true,
  },
  feel22_eg: {
    name: { en: "Feel22 Egypt", ar: "فيل 22" },
    domain: "feel22.com",
    accent: "#d946ef",
    urlLookup: true,
  },
  beautyshop_eg: {
    name: { en: "BeautyShop EG", ar: "بيوتي شوب" },
    domain: "beautyshopeg.com",
    accent: "#d946ef",
    urlLookup: true,
  },
  alejon: {
    name: { en: "Alejon Cosmetics", ar: "أليجون" },
    domain: "alejon.com",
    accent: "#d946ef",
    urlLookup: true,
  },
  lajolie_perfumes: {
    name: { en: "La Jolie Perfumes", ar: "لا جولي للعطور" },
    domain: "lajolieperfumes.com",
    accent: "#d946ef",
    urlLookup: true,
  },
  nelli_beauty: {
    name: { en: "Nelli Beauty", ar: "نيلي بيوتي" },
    domain: "nellibeauty.com",
    accent: "#d946ef",
    urlLookup: true,
  },
  dr_diamond: {
    name: { en: "Dr. Diamond", ar: "دكتور دايموند" },
    domain: "drdiamond.store",
    accent: "#06b6d4",
    urlLookup: true,
  },
  azzam_pharmacy: {
    name: { en: "Azzam Pharmacy", ar: "صيدليات عزام" },
    domain: "azzampharmacy.com",
    accent: "#06b6d4",
    urlLookup: true,
  },
  homepro_eg: {
    name: { en: "HomePro Egypt", ar: "هوم برو" },
    domain: "homeproeg.com",
    accent: "#f59e0b",
    urlLookup: true,
  },
  cilantro_eg: {
    name: { en: "Cilantro", ar: "سيلانترو" },
    domain: "cilantro.cafe",
    accent: "#10b981",
    urlLookup: true,
  },
  sevengear: {
    name: { en: "SevenGear", ar: "سيفن جير" },
    domain: "sevengear.net",
    accent: "#84cc16",
    urlLookup: true,
  },
  eabc_books: {
    name: { en: "EABC Books", ar: "مكتبة EABC" },
    domain: "eabcbooks.com",
    accent: "#8b5cf6",
    urlLookup: true,
  },
  kalimat_store: {
    name: { en: "Kalimat Store", ar: "كلمات" },
    domain: "kalimatstore.com",
    accent: "#8b5cf6",
    urlLookup: true,
  },
  almasriah_books: {
    name: { en: "Almasriah Bookstores", ar: "المكتبة المصرية" },
    domain: "almasriahbookstores.com",
    accent: "#8b5cf6",
    urlLookup: true,
  },
  pet_station_eg: {
    name: { en: "Pet Station", ar: "بيت ستيشن" },
    domain: "petstationeg.com",
    accent: "#f97316",
    urlLookup: true,
  },
  pets_office: {
    name: { en: "PetsOffice", ar: "بيتس أوفيس" },
    domain: "petsoffice.com",
    accent: "#f97316",
    urlLookup: true,
  },
  dockland_eg: {
    name: { en: "Dockland Egypt", ar: "دوكلاند" },
    domain: "dockland.com.eg",
    accent: "#ec4899",
    urlLookup: true,
  },
  hk_designs: {
    name: { en: "HK Designs", ar: "إتش كيه ديزاينز" },
    domain: "hkdesigns-eg.com",
    accent: "#ec4899",
    urlLookup: true,
  },
  the_bag_maker: {
    name: { en: "The Bag Maker", ar: "ذا باج ميكر" },
    domain: "thebagmakereg.com",
    accent: "#ec4899",
    urlLookup: true,
  },
  couch_eg: {
    name: { en: "Couch Furniture", ar: "كاوتش للأثاث" },
    domain: "couch.com.eg",
    accent: "#f59e0b",
    urlLookup: true,
  },
  vero_eg: {
    name: { en: "Vero Appliances", ar: "فيرو للأجهزة" },
    domain: "vero.com.eg",
    accent: "#ef4444",
    urlLookup: true,
  },
  sony_world_eg: {
    name: { en: "Sony World Egypt", ar: "سوني وورلد مصر" },
    domain: "sonyworld.eg",
    accent: "#3b82f6",
    urlLookup: true,
  },
  beurer_eg: {
    name: { en: "Beurer Egypt", ar: "بيورير مصر" },
    domain: "beurer.eg",
    accent: "#06b6d4",
    urlLookup: true,
  },
  hanso_eg: {
    name: { en: "Hanso Egypt", ar: "هانسو مصر" },
    domain: "hanso.eg",
    accent: "#ef4444",
    urlLookup: true,
  },
  dr_scent_eg: {
    name: { en: "Dr. Scent Egypt", ar: "دكتور سينت" },
    domain: "dr-scent.com.eg",
    accent: "#f59e0b",
    urlLookup: true,
  },
  joy_scent_eg: {
    name: { en: "Joy Scent Egypt", ar: "جوي سينت" },
    domain: "joy-scent.com.eg",
    accent: "#f59e0b",
    urlLookup: true,
  },
  "3alababak": {
    name: { en: "3alababak", ar: "على بابك" },
    domain: "3alababak.com",
    accent: "#d946ef",
    urlLookup: true,
  },
  or_egypt: {
    name: { en: "Or Egypt", ar: "أور إيجيبت" },
    domain: "or-egypt.com",
    accent: "#ec4899",
    urlLookup: true,
  },
  pixi_shoes: {
    name: { en: "PIXI Shoes", ar: "بيكسي شوز" },
    domain: "pixishoes.com",
    accent: "#ec4899",
    urlLookup: true,
  },
  zuri_cairo: {
    name: { en: "Zuri Cairo", ar: "زوري كايرو" },
    domain: "zuricairo.com",
    accent: "#ec4899",
    urlLookup: true,
  },
  jessica_eg: {
    name: { en: "Jessica Egypt", ar: "جيسيكا" },
    domain: "jessicaeg.com",
    accent: "#ec4899",
    urlLookup: true,
  },
  alarabiya_comp: {
    name: { en: "Alarabiya Computer", ar: "العربية للكمبيوتر" },
    domain: "alarabiya-computer.com",
    accent: "#3b82f6",
    urlLookup: true,
  },
  more_shopping: {
    name: { en: "More Shopping", ar: "مور شوبينج" },
    domain: "moreshopping.com",
    accent: "#3b82f6",
    urlLookup: true,
  },
  coffee_and_cream: {
    name: { en: "Coffee & Cream", ar: "كوفي آند كريم" },
    domain: "coffeeandcream.app",
    accent: "#10b981",
    urlLookup: true,
  },
  snacks_roastery: {
    name: { en: "Snacks Roastery", ar: "محمصة سناكس" },
    domain: "snacks-roastery.com",
    accent: "#10b981",
    urlLookup: true,
  },
  brown_nose: {
    name: { en: "Brown Nose Coffee", ar: "براون نوز كوفي" },
    domain: "brownnosecoffee.com",
    accent: "#10b981",
    urlLookup: true,
  },
  rebel_cairo: {
    name: { en: "Rebel Cairo", ar: "ريبيل كايرو" },
    domain: "rebelcairo.com",
    accent: "#ec4899",
    urlLookup: true,
  },
  malaika_linens: {
    name: { en: "Malaika Linens", ar: "ملايكة ليننز" },
    domain: "malaikalinens.com",
    accent: "#f59e0b",
    urlLookup: true,
  },
  carpets_eg: {
    name: { en: "Kiliim", ar: "كليم" },
    domain: "kiliim.com",
    accent: "#f59e0b",
    urlLookup: true,
  },
  reform_studio: {
    name: { en: "Reform Studio", ar: "ريفورم ستوديو" },
    domain: "reformstudio.net",
    accent: "#f59e0b",
    urlLookup: true,
  },
  cairo_design: {
    name: { en: "Aura Home EG", ar: "أورا هوم" },
    domain: "aurahomeeg.com",
    accent: "#f59e0b",
    urlLookup: true,
  },
  home_art_eg: {
    name: { en: "Home Art EG", ar: "هوم آرت" },
    domain: "homearteg.com",
    accent: "#f59e0b",
    urlLookup: true,
  },
  nut_botanicals: {
    name: { en: "NUT Botanicals", ar: "نات بوتانيكالز" },
    domain: "nutbotanicals.com",
    accent: "#d946ef",
    urlLookup: true,
  },
  damson_furniture: {
    name: { en: "Damson Furniture", ar: "دامسون للأثاث" },
    domain: "damsonfurniture.com",
    accent: "#f59e0b",
    urlLookup: true,
  },
  wasilaah: {
    name: { en: "Wasilaah Smart Furniture", ar: "وسيلة للأثاث" },
    domain: "wasilaah.com",
    accent: "#f59e0b",
    urlLookup: true,
  },
  arafa_interiors: {
    name: { en: "Arafa Interiors", ar: "عرفة إنتيريورز" },
    domain: "arafa-interiors.com",
    accent: "#f59e0b",
    urlLookup: true,
  },
  farsha_home: {
    name: { en: "Farsha Home", ar: "فرشة هوم" },
    domain: "farsha.store",
    accent: "#f59e0b",
    urlLookup: true,
  },
  sereno_eg: {
    name: { en: "Sereno Outdoor", ar: "سيرينو" },
    domain: "serenoegypt.com",
    accent: "#f59e0b",
    urlLookup: true,
  },
  sofa_zone_eg: {
    name: { en: "Sofa Zone", ar: "صوفا زون" },
    domain: "sofazoneeg.com",
    accent: "#f59e0b",
    urlLookup: true,
  },
  magalis_eg: {
    name: { en: "Magalis Egypt", ar: "مجالس" },
    domain: "magalis-egypt.com",
    accent: "#f59e0b",
    urlLookup: true,
  },
  pencilight: {
    name: { en: "Pencilight", ar: "بنسل لايت" },
    domain: "pencilight.com",
    accent: "#f59e0b",
    urlLookup: true,
  },
  kitchanova: {
    name: { en: "Kitchanova", ar: "كيتشانوفا" },
    domain: "kitchanova.com",
    accent: "#f59e0b",
    urlLookup: true,
  },
  sheffield_eg: {
    name: { en: "Sheffield Egypt", ar: "شيفيلد مصر" },
    domain: "sheffieldeg.com",
    accent: "#f59e0b",
    urlLookup: true,
  },
  kk_cookware: {
    name: { en: "K&K Cookware", ar: "كيه آند كيه" },
    domain: "kk-cookware.com",
    accent: "#f59e0b",
    urlLookup: true,
  },
  helal_group: {
    name: { en: "El Helal & Silver Star", ar: "الهلال والنجمة" },
    domain: "helalgroup.store",
    accent: "#f59e0b",
    urlLookup: true,
  },
  duro_cookware: {
    name: { en: "Duro Cookware", ar: "دورو" },
    domain: "durocookware.com",
    accent: "#f59e0b",
    urlLookup: true,
  },
  prifix_eg: {
    name: { en: "Prifix", ar: "بريفيكس" },
    domain: "prifix.com",
    accent: "#ef4444",
    urlLookup: true,
  },
  iq_mobiles: {
    name: { en: "IQ Store", ar: "آي كيو ستور" },
    domain: "iq-mobiles.com",
    accent: "#3b82f6",
    urlLookup: true,
  },
  cloud_clothing: {
    name: { en: "Cloud Clothing", ar: "كلاود" },
    domain: "cloud-clothing.co",
    accent: "#ec4899",
    urlLookup: true,
  },
  egypuppy: {
    name: { en: "EgyPuppy", ar: "إيجي بابي" },
    domain: "egypuppy.com",
    accent: "#f97316",
    urlLookup: true,
  },
  zima_pets: {
    name: { en: "Zima Pets", ar: "زيما بيتس" },
    domain: "zimapets.com",
    accent: "#f97316",
    urlLookup: true,
  },
};

/** Stores highlighted in the direct-link guidance (largest catalogs first). */
export const FEATURED_LINK_STORES = ["noon", "amazon_eg", "btech", "2b", "sigma"] as const;

function prettifySlug(slug: string): string {
  return slug
    .split(/[_-]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

export function storeDisplayName(slug: string, lang: Lang): string {
  const meta = STORE_META[slug];
  if (meta) return meta.name[lang];
  return prettifySlug(slug) || slug;
}

export function storeAccent(slug: string): string {
  return STORE_META[slug]?.accent ?? "#64748b";
}
