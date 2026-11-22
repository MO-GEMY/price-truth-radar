/**
 * Shared OpenGraph card factory (next/og ImageResponse) for the viral share
 * surfaces: product cards, /deals, /compare, and the site default.
 *
 * NOTE: cards render ENGLISH text only. Satori cannot shape Arabic (GSUB
 * lookupType 5 / substFormat 3 is unsupported), so Arabic badges crash at
 * prerender. Arabic lives in the page meta tags and the Web-Share text —
 * both of which WhatsApp/Facebook render natively.
 */

import { ImageResponse } from "next/og";

export const OG_SIZE = { width: 1200, height: 630 } as const;

export interface OgCardData {
  title: string;
  store?: string;
  price?: string;
  claimedPrice?: string | null;
  /** Verdict badge label shown on the card (English — satori cannot shape Arabic). */
  verdictEn?: string;
  isScandal?: boolean;
  footer?: string;
}

export function makeOgResponse(data: OgCardData): ImageResponse {
  const accent = data.isScandal ? "#fb7185" : "#34d399";
  const verdictText = data.verdictEn ?? "";
  const title = data.title.length > 96 ? `${data.title.slice(0, 93)}…` : data.title;

  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          backgroundColor: "#05080f",
          backgroundImage:
            "radial-gradient(circle at 12% 0%, rgba(20,184,166,0.16), transparent 46%), radial-gradient(circle at 92% 110%, rgba(251,113,133,0.14), transparent 46%)",
          padding: 56,
          fontFamily: "sans-serif",
        }}
      >
        {/* Brand row */}
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              width: 44,
              height: 44,
              borderRadius: 12,
              background: "linear-gradient(135deg, #2dd4bf, #10b981)",
              color: "#031214",
              fontSize: 24,
              fontWeight: 700,
            }}
          >
            PTR
          </div>
          <div style={{ display: "flex", flexDirection: "column" }}>
            <span style={{ color: "#f1f5f9", fontSize: 20, fontWeight: 700 }}>Price Truth Radar</span>
            <span style={{ color: "#94a3b8", fontSize: 14 }}>Egyptian price intelligence</span>
          </div>
        </div>

        {/* Store + verdict badges, title, price */}
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 22,
            flex: 1,
            justifyContent: "center",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
            {data.store ? (
              <div
                style={{
                  display: "flex",
                  padding: "6px 16px",
                  borderRadius: 999,
                  border: "1px solid rgba(148,163,184,0.35)",
                  color: "#e2e8f0",
                  fontSize: 20,
                  fontWeight: 700,
                }}
              >
                {data.store}
              </div>
            ) : null}
            {verdictText ? (
              <div
                style={{
                  display: "flex",
                  padding: "6px 18px",
                  borderRadius: 999,
                  border: `2px solid ${accent}`,
                  background: data.isScandal ? "rgba(251,113,133,0.16)" : "rgba(52,211,153,0.16)",
                  color: accent,
                  fontSize: 24,
                  fontWeight: 700,
                }}
              >
                {verdictText}
              </div>
            ) : null}
          </div>

          <div
            style={{
              color: "#ffffff",
              fontSize: 50,
              fontWeight: 700,
              lineHeight: 1.18,
              display: "flex",
            }}
          >
            {title}
          </div>

          {data.price ? (
            <div style={{ display: "flex", alignItems: "baseline", gap: 18 }}>
              <span style={{ color: "#5eead4", fontSize: 46, fontWeight: 700 }}>{data.price}</span>
              {data.claimedPrice ? (
                <span
                  style={{
                    color: "#64748b",
                    fontSize: 28,
                    fontWeight: 600,
                    textDecoration: "line-through",
                  }}
                >
                  {data.claimedPrice}
                </span>
              ) : null}
            </div>
          ) : null}
        </div>

        {/* Footer */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            color: "#64748b",
            fontSize: 17,
          }}
        >
          <span>{data.footer ?? "Price Truth Radar — Egyptian price intelligence"}</span>
          <span>price-truth-radar.vercel.app</span>
        </div>
      </div>
    ),
    { ...OG_SIZE },
  );
}
