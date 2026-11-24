import { ImageResponse } from "next/og";
import { SITE_DOMAIN, SITE_NAME } from "./site";

export const OG_SIZE = { width: 1200, height: 630 } as const;

export interface OgStatPill {
  value: string;
  label: string;
}

export interface OgCardData {
  eyebrow?: string;
  title: string;
  subtitle?: string;
  store?: string;
  price?: string;
  stats?: readonly OgStatPill[];
  footer?: string;
}

export function makeOgResponse(data: OgCardData): ImageResponse {
  const title =
    data.title.length > 88 ? data.title.slice(0, 85).trimEnd() + "…" : data.title;
  const titleSize = title.length > 52 ? 46 : 56;

  return new ImageResponse(
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        flexDirection: "column",
        justifyContent: "space-between",
        backgroundColor: "#F7F5EF",
        padding: "48px 56px",
        color: "#192722",
        fontFamily: "sans-serif",
        borderTop: "12px solid #005E53",
      }}
    >
      {/* Top Brand Bar */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          width: "100%",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              backgroundColor: "#005E53",
              color: "#FFFFFF",
              borderRadius: 10,
              padding: "10px 16px",
              fontSize: 24,
              fontWeight: 800,
              letterSpacing: "0.04em",
            }}
          >
            ASARAK
          </div>
          <div style={{ display: "flex", flexDirection: "column" }}>
            <span style={{ display: "flex", fontSize: 28, fontWeight: 800, color: "#192722" }}>
              {SITE_NAME}
            </span>
            <span style={{ display: "flex", fontSize: 17, color: "#52605A" }}>
              Egypt Price Comparison &amp; Deal Verification
            </span>
          </div>
        </div>

        <div
          style={{
            display: "flex",
            alignItems: "center",
            backgroundColor: "#E3EFEA",
            border: "1px solid #B7D6CB",
            color: "#005E53",
            borderRadius: 999,
            padding: "8px 18px",
            fontSize: 18,
            fontWeight: 700,
          }}
        >
          {data.eyebrow ?? "EGYPT · EGP"}
        </div>
      </div>

      {/* Main Content Card */}
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          gap: 16,
          padding: "34px 38px",
          border: "1px solid #D3E2DA",
          borderRadius: 18,
          backgroundColor: "#FFFFFF",
        }}
      >
        {data.store && (
          <span
            style={{
              display: "flex",
              color: "#005E53",
              fontSize: 22,
              fontWeight: 700,
              textTransform: "uppercase",
              letterSpacing: "0.04em",
            }}
          >
            {data.store}
          </span>
        )}
        <span
          style={{
            display: "flex",
            fontSize: titleSize,
            lineHeight: 1.14,
            fontWeight: 800,
            color: "#12211C",
          }}
        >
          {title}
        </span>
        {data.subtitle && (
          <span style={{ display: "flex", fontSize: 24, lineHeight: 1.35, color: "#4B5B55" }}>
            {data.subtitle}
          </span>
        )}
        {data.price && (
          <div style={{ display: "flex", alignItems: "center", gap: 16, marginTop: 4 }}>
            <span
              style={{
                display: "flex",
                backgroundColor: "#005E53",
                color: "#FFFFFF",
                borderRadius: 10,
                padding: "8px 20px",
                fontSize: 38,
                fontWeight: 800,
              }}
            >
              {data.price}
            </span>
          </div>
        )}
        {data.stats && data.stats.length > 0 && (
          <div style={{ display: "flex", gap: 18, marginTop: 8 }}>
            {data.stats.map((stat) => (
              <div
                key={stat.label}
                style={{
                  display: "flex",
                  flexDirection: "column",
                  backgroundColor: "#F2F7F4",
                  border: "1px solid #D6E6DF",
                  borderRadius: 12,
                  padding: "12px 20px",
                  flex: 1,
                }}
              >
                <span style={{ display: "flex", fontSize: 28, fontWeight: 800, color: "#005E53" }}>
                  {stat.value}
                </span>
                <span style={{ display: "flex", fontSize: 16, color: "#4B5B55", marginTop: 2 }}>
                  {stat.label}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Footer */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          color: "#52605A",
          fontSize: 20,
          width: "100%",
        }}
      >
        <span style={{ display: "flex" }}>
          {data.footer ?? "Verify real discounts vs. 60-day recorded price history"}
        </span>
        <span style={{ display: "flex", fontWeight: 700, color: "#005E53" }}>
          {SITE_DOMAIN}
        </span>
      </div>
    </div>,
    OG_SIZE,
  );
}
