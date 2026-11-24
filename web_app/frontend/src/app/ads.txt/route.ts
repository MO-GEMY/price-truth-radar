/**
 * Dynamic /ads.txt route for Asarak (asarak.com).
 *
 * When NEXT_PUBLIC_ADSENSE_CLIENT is configured (e.g. "ca-pub-1234567890123456"),
 * automatically serves the verified Google AdSense publisher line:
 *   google.com, pub-1234567890123456, DIRECT, f08c47fec0942fa0
 *
 * When unset, serves a documented placeholder so the route stays 200 OK
 * and clearly instructs where to configure the publisher ID.
 */

export const dynamic = "force-dynamic";

const GOOGLE_ADSENSE_CERT_AUTHORITY_ID = "f08c47fec0942fa0";

function normalizePublisherId(rawClient: string): string | null {
  const cleaned = rawClient.trim();
  if (!cleaned) return null;
  const withoutCaPrefix = cleaned.replace(/^ca-/i, "");
  if (!/^pub-\d+$/i.test(withoutCaPrefix)) return null;
  return withoutCaPrefix.toLowerCase();
}

export function GET() {
  const rawClient = process.env.NEXT_PUBLIC_ADSENSE_CLIENT ?? "";
  const publisherId = normalizePublisherId(rawClient);

  const body = publisherId
    ? `google.com, ${publisherId}, DIRECT, ${GOOGLE_ADSENSE_CERT_AUTHORITY_ID}\n`
    : [
        "# Asarak (asarak.com) — Google AdSense authorized sellers declaration.",
        "# Set NEXT_PUBLIC_ADSENSE_CLIENT (e.g. ca-pub-XXXXXXXXXXXXXXXX) in wrangler.jsonc",
        "# and .env.production, then redeploy to publish your verified publisher line:",
        `# google.com, pub-XXXXXXXXXXXXXXXX, DIRECT, ${GOOGLE_ADSENSE_CERT_AUTHORITY_ID}`,
        "",
      ].join("\n");

  return new Response(body, {
    status: 200,
    headers: {
      "Content-Type": "text/plain; charset=utf-8",
      "Cache-Control": "public, max-age=3600",
    },
  });
}
