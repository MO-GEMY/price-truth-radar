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
    data.title.length > 88
      ? data.title.slice(0, 85).trimEnd() + "…"
      : data.title;
  const titleSize = title.length > 52 ? 44 : 54;

  return new ImageResponse(
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        flexDirection: "column",
        justifyContent: "space-between",
        backgroundColor: "#0B192E",
        padding: "46px 56px",
        color: "#FFFFFF",
        fontFamily: "sans-serif",
        borderTop: "10px solid #0CAE79",
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
        <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 120 120"
            width="60"
            height="60"
            fill="none"
          >
            <path
              d="M48 103 L98 53 V95 C98 101 93 106 87 106 H55 C52 106 50 105 48 103 Z"
              fill="#0CAE79"
            />
            <path
              d="M48 103 L98 53 L98 65 L58 105 C54 106 50 105 48 103 Z"
              fill="#0E7D60"
              opacity="0.45"
            />
            <path
              d="M98 14 H58 C54 14 50 16 47 19 L14 52 C10 56 10 62 14 66 L41 93 L49 85 L23 59 L56 26 H90 Z"
              fill="#FFFFFF"
            />
            <path
              d="M41 93 L47 99 C51 103 57 103 61 99 L98 62 V14 L87 25 V57 L54 90 L49 85 Z"
              fill="#0CAE79"
            />
            <path
              d="M36 62 L51 77 L98 30 V14 L51 61 L44 54 Z"
              fill="#0CAE79"
            />
          </svg>
          <div style={{ display: "flex", flexDirection: "column" }}>
            <span
              style={{
                display: "flex",
                fontSize: 32,
                fontWeight: 800,
                color: "#FFFFFF",
                letterSpacing: "0.02em",
              }}
            >
              {SITE_NAME}
            </span>
            <span style={{ display: "flex", fontSize: 17, color: "#94A3B8" }}>
              Egypt Price Comparison &amp; Deal Verification
            </span>
          </div>
        </div>

        <div
          style={{
            display: "flex",
            alignItems: "center",
            backgroundColor: "rgba(12, 174, 121, 0.16)",
            border: "1px solid rgba(52, 211, 153, 0.38)",
            color: "#34D399",
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
          border: "1px solid #1E3557",
          borderRadius: 20,
          backgroundColor: "#11223D",
        }}
      >
        {data.store && (
          <span
            style={{
              display: "flex",
              color: "#34D399",
              fontSize: 22,
              fontWeight: 700,
              textTransform: "uppercase",
              letterSpacing: "0.05em",
            }}
          >
            {data.store}
          </span>
        )}
        <span
          style={{
            display: "flex",
            fontSize: titleSize,
            lineHeight: 1.15,
            fontWeight: 800,
            color: "#FFFFFF",
          }}
        >
          {title}
        </span>
        {data.subtitle && (
          <span
            style={{
              display: "flex",
              fontSize: 23,
              lineHeight: 1.38,
              color: "#CBD5E1",
            }}
          >
            {data.subtitle}
          </span>
        )}
        {data.price && (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 16,
              marginTop: 4,
            }}
          >
            <span
              style={{
                display: "flex",
                backgroundColor: "#0CAE79",
                color: "#FFFFFF",
                borderRadius: 12,
                padding: "10px 22px",
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
                  backgroundColor: "#0B192E",
                  border: "1px solid #1E3557",
                  borderRadius: 14,
                  padding: "14px 20px",
                  flex: 1,
                }}
              >
                <span
                  style={{
                    display: "flex",
                    fontSize: 28,
                    fontWeight: 800,
                    color: "#34D399",
                  }}
                >
                  {stat.value}
                </span>
                <span
                  style={{
                    display: "flex",
                    fontSize: 16,
                    color: "#94A3B8",
                    marginTop: 4,
                  }}
                >
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
          color: "#94A3B8",
          fontSize: 20,
          width: "100%",
        }}
      >
        <span style={{ display: "flex" }}>
          {data.footer ??
            "Verify real discounts vs. 60-day recorded price history"}
        </span>
        <span style={{ display: "flex", fontWeight: 700, color: "#34D399" }}>
          {SITE_DOMAIN}
        </span>
      </div>
    </div>,
    OG_SIZE,
  );
}
