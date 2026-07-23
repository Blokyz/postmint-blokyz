"use client";

import { useId } from "react";
import { CrestState, STATE_META, tierMeta } from "@/lib/crests";

// A procedural heraldic crest for a tier. Shield fills from the bottom by
// `progressPct` (how much of the set is held); a won crest is fully lit with a
// gold ring + glow, a locked one is a dim outline. Rank pips run along the crown.
// Purely derived — no hand-drawn art — so it works for any auto-generated tier.
export function Crest({
  tier,
  state,
  size = 96,
  progressPct = 100,
  rank,
  count = 0,
}: {
  tier: string;
  state: CrestState;
  size?: number;
  progressPct?: number;
  rank?: number;
  count?: number;
}) {
  const uid = useId().replace(/:/g, "");
  const meta = tierMeta(tier, rank ?? 0);
  const r = rank ?? meta.rank;
  const ring = STATE_META[state].ring;
  const earned = state === "won";
  const dim = state === "locked";

  // Shield outline in a 100x116 box.
  const shield = "M50 6 L92 22 L92 60 Q92 96 50 110 Q8 96 8 60 L8 22 Z";
  // Fill clip: a rect covering the bottom `fill`% of the shield.
  const fill = Math.max(0, Math.min(100, earned ? 100 : progressPct));
  const fillY = 6 + (110 - 6) * (1 - fill / 100);

  const pips = Array.from({ length: r + 1 }, (_, i) => i);

  return (
    <div
      className={`crest is-${state}`}
      style={{ width: size, height: size * 1.16, "--crest-ring": ring, "--crest-color": meta.color } as React.CSSProperties}
    >
      <svg viewBox="0 0 100 116" width="100%" height="100%" aria-label={`${tier} crest — ${STATE_META[state].label}`}>
        <defs>
          <clipPath id={`clip-${uid}`}>
            <path d={shield} />
          </clipPath>
          <linearGradient id={`grad-${uid}`} x1="0" y1="1" x2="0" y2="0">
            <stop offset="0%" stopColor={meta.color} stopOpacity="0.85" />
            <stop offset="100%" stopColor={meta.color} stopOpacity="0.35" />
          </linearGradient>
        </defs>

        {/* Dim base */}
        <path d={shield} fill="#0e1114" />
        {/* Progress / earned fill */}
        {!dim && (
          <rect
            x="0"
            y={fillY}
            width="100"
            height={116 - fillY}
            fill={`url(#grad-${uid})`}
            clipPath={`url(#clip-${uid})`}
          />
        )}
        {/* Outline */}
        <path d={shield} fill="none" stroke={ring} strokeWidth={earned ? 3 : 2} opacity={dim ? 0.5 : 1} />

        {/* Crown pips (rank) */}
        {pips.map((i) => (
          <circle
            key={i}
            cx={50 + (i - r / 2) * 11}
            cy={20}
            r={2.6}
            fill={dim ? "#3a3f47" : meta.color}
          />
        ))}

        {/* Glyph */}
        <text
          x="50"
          y="70"
          textAnchor="middle"
          fontSize="34"
          fill={dim ? "#4b525c" : earned ? "#ffffff" : meta.color}
          style={{ fontFamily: "var(--font-race-display), sans-serif" }}
        >
          {meta.glyph}
        </text>
      </svg>

      {count > 1 && <span className="crest-count">×{count}</span>}
    </div>
  );
}
