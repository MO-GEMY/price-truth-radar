/**
 * Lightweight, config-driven Affiliate URL builder for Asarak (أسعارك).
 *
 * Strictly pass-through when affiliate env vars are empty, and safely validates
 * URLs without throwing on malformed input.
 */

export const AFFILIATE_LINK_REL = "noopener noreferrer sponsored nofollow";
export const STANDARD_OUTBOUND_REL = "noopener noreferrer nofollow";

export function outboundLinkRel(isAffiliate: boolean): string {
  return isAffiliate ? AFFILIATE_LINK_REL : STANDARD_OUTBOUND_REL;
}

export interface AffiliateUrlResult {
  url: string;
  isAffiliate: boolean;
  network?: string;
}

export interface AffiliateConfigOverride {
  amazonEgTag?: string;
  deeplinkMapRaw?: string;
}

let cachedMapRaw: string | null = null;
let cachedMap: Readonly<Record<string, string>> = {};

function parseDeeplinkMap(raw: string): Readonly<Record<string, string>> {
  const trimmed = raw.trim();
  if (!trimmed) return {};
  if (cachedMapRaw === trimmed) return cachedMap;

  const normalized: Record<string, string> = {};
  try {
    const parsed: unknown = JSON.parse(trimmed);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      for (const [rawKey, rawVal] of Object.entries(parsed as Record<string, unknown>)) {
        if (typeof rawVal !== "string") continue;
        const template = rawVal.trim();
        if (!template || !template.includes("{url}")) continue;
        if (!/^https?:\/\//i.test(template)) continue;
        const key = rawKey.trim().toLowerCase();
        if (!key) continue;
        normalized[key] = template;
        const stripped = key.replace(/^www\./, "");
        if (stripped && !normalized[stripped]) {
          normalized[stripped] = template;
        }
      }
    }
  } catch {
    // Malformed JSON — fall back silently to empty map
  }

  cachedMapRaw = trimmed;
  cachedMap = normalized;
  return normalized;
}

function inferNetworkName(template: string, fallbackKey: string): string {
  try {
    const host = new URL(template.replace("{url}", "https://example.com")).hostname
      .toLowerCase()
      .replace(/^www\./, "");
    if (host) return host;
  } catch {
    // Fallback below
  }
  return fallbackKey || "deeplink";
}

/**
 * Safely rewrites an outbound retailer URL when matching affiliate configuration
 * is present. Always preserves rawUrl on invalid URLs, non-http(s) protocols,
 * or empty affiliate configuration.
 */
export function buildAffiliateUrl(
  rawUrl: string,
  storeName?: string,
  configOverride?: AffiliateConfigOverride,
): AffiliateUrlResult {
  if (!rawUrl || typeof rawUrl !== "string") {
    return { url: rawUrl ?? "", isAffiliate: false };
  }

  let parsed: URL;
  try {
    parsed = new URL(rawUrl);
  } catch {
    return { url: rawUrl, isAffiliate: false };
  }

  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    return { url: rawUrl, isAffiliate: false };
  }

  const host = parsed.hostname.toLowerCase();
  const bareHost = host.replace(/^www\./, "");

  const amazonTag = (
    configOverride?.amazonEgTag ??
    process.env.NEXT_PUBLIC_AMAZON_EG_TAG ??
    ""
  ).trim();

  if ((host === "amazon.eg" || host === "www.amazon.eg") && amazonTag) {
    parsed.searchParams.set("tag", amazonTag);
    return {
      url: parsed.toString(),
      isAffiliate: true,
      network: "amazon_eg",
    };
  }

  const deeplinkRaw =
    configOverride?.deeplinkMapRaw ??
    process.env.NEXT_PUBLIC_AFFILIATE_DEEPLINK_MAP ??
    "";
  const deeplinkMap = parseDeeplinkMap(deeplinkRaw);

  const storeKey = (storeName ?? "").trim().toLowerCase();
  const matchedKey =
    (bareHost && deeplinkMap[bareHost] ? bareHost : null) ??
    (host && deeplinkMap[host] ? host : null) ??
    (storeKey && deeplinkMap[storeKey] ? storeKey : null);

  if (matchedKey) {
    const template = deeplinkMap[matchedKey];
    const encoded = encodeURIComponent(rawUrl);
    const rewritten = template.replace(/\{url\}/g, encoded);
    return {
      url: rewritten,
      isAffiliate: true,
      network: inferNetworkName(template, matchedKey),
    };
  }

  return { url: rawUrl, isAffiliate: false };
}
