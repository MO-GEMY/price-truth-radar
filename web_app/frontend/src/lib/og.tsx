import { ImageResponse } from "next/og";

export const OG_SIZE = { width: 1200, height: 630 } as const;

interface OgCardData {
  title: string;
  store?: string;
  price?: string;
  footer?: string;
}

export function makeOgResponse(data: OgCardData): ImageResponse {
  const title = data.title.length > 96 ? data.title.slice(0, 93).trimEnd() + "…" : data.title;
  return new ImageResponse(
    <div style={{
      width: "100%", height: "100%", display: "flex", flexDirection: "column",
      justifyContent: "space-between", backgroundColor: "#F7F5EF", padding: 57,
      color: "#192722", fontFamily: "sans-serif",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 14, fontSize: 27, fontWeight: 700 }}>
        <span style={{ display: "flex", backgroundColor: "#005E53", color: "#fff", borderRadius: 8, padding: "9px 12px" }}>PTR</span>
        <span>Price Truth Radar</span>
      </div>
      <div style={{
        display: "flex", flexDirection: "column", justifyContent: "center", gap: 15,
        padding: 34, border: "1px solid #dce7dc", borderRadius: 14, backgroundColor: "#EAF1E9",
      }}>
        {data.store && <span style={{ display: "flex", color: "#52605a", fontSize: 22 }}>{data.store}</span>}
        <span style={{ display: "flex", fontSize: 53, lineHeight: 1.12, fontWeight: 700 }}>{title}</span>
        {data.price && <span style={{ display: "flex", color: "#005E53", fontSize: 43, fontWeight: 700 }}>{data.price}</span>}
      </div>
      <div style={{ display: "flex", color: "#52605a", fontSize: 22 }}>
        {data.footer ?? "Observed prices and matched offers in Egypt"}
      </div>
    </div>, OG_SIZE,
  );
}
