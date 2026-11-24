"use client";

export interface AsarakEmblemProps {
  /**
   * "auto" adapts outer frame to current theme (--asarak-ink: #0B192E in light, #FFFFFF in dark).
   * "dark" forces white outer frame (for deep navy hero/footer surfaces).
   * "light" forces deep navy outer frame (for white surfaces).
   */
  variant?: "auto" | "light" | "dark";
  size?: number;
  className?: string;
}

/**
 * Official Asarak (أسعارك) geometric price-tag + verified checkmark emblem
 * sourced verbatim from asarak-brand-kit/svg/asarak-icon-*.svg.
 */
export function AsarakEmblem({
  variant = "auto",
  size = 40,
  className = "",
}: AsarakEmblemProps) {
  const frameFill =
    variant === "dark"
      ? "#FFFFFF"
      : variant === "light"
        ? "#0B192E"
        : "var(--asarak-ink)";

  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 120 120"
      width={size}
      height={size}
      fill="none"
      aria-hidden="true"
      className={className}
    >
      {/* Solid Emerald Lower-Right Base & Fold */}
      <path
        d="M48 103 L98 53 V95 C98 101 93 106 87 106 H55 C52 106 50 105 48 103 Z"
        fill="#0CAE79"
      />
      {/* Subtle Deep Emerald Fold Shadow */}
      <path
        d="M48 103 L98 53 L98 65 L58 105 C54 106 50 105 48 103 Z"
        fill="#0E7D60"
        opacity="0.45"
      />
      {/* Outer Frame: Navy (Light) or White (Dark) */}
      <path
        d="M98 14 H58 C54 14 50 16 47 19 L14 52 C10 56 10 62 14 66 L41 93 L49 85 L23 59 L56 26 H90 Z"
        fill={frameFill}
      />
      {/* Emerald Inner Checkmark & Right Ribbon */}
      <path
        d="M41 93 L47 99 C51 103 57 103 61 99 L98 62 V14 L87 25 V57 L54 90 L49 85 Z"
        fill="#0CAE79"
      />
      {/* Inner Verification Checkmark Stroke */}
      <path
        d="M36 62 L51 77 L98 30 V14 L51 61 L44 54 Z"
        fill="#0CAE79"
      />
    </svg>
  );
}

export interface AsarakLogoProps {
  variant?: "auto" | "light" | "dark";
  size?: "sm" | "md" | "lg";
  className?: string;
}

/**
 * Official bilingual Asarak lockup ("أسعارك" + "Asarak") adhering to
 * brand-kit sizing and typography rules.
 */
export function AsarakLogo({
  variant = "auto",
  size = "md",
  className = "",
}: AsarakLogoProps) {
  const iconSize = size === "sm" ? 32 : size === "lg" ? 46 : 38;
  const textColor =
    variant === "dark"
      ? "#FFFFFF"
      : variant === "light"
        ? "#0B192E"
        : "var(--asarak-ink)";

  return (
    <span
      className={`asarak-brand asarak-brand--${size} ${className}`}
      style={{ color: textColor }}
    >
      <AsarakEmblem variant={variant} size={iconSize} className="asarak-brand__icon" />
      <span className="asarak-brand__wordmarks">
        <span className="asarak-brand__wordmark-ar" lang="ar">
          أسعارك
        </span>
        <span className="asarak-brand__wordmark-en" lang="en">
          Asarak
        </span>
      </span>
    </span>
  );
}
