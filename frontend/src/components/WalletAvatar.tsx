"use client";

import { useId } from "react";

// A deterministic gradient avatar derived from a wallet address — our stand-in
// for the pfp circle a holder-engagement leaderboard would show. Purely derived
// (no image dependency), so every wallet gets a stable, distinct medallion.
export function WalletAvatar({ address, size = 44 }: { address: string; size?: number }) {
  const uid = useId().replace(/:/g, "");
  const a = (address || "").toLowerCase().replace(/^0x/, "").padEnd(14, "0");

  const h1 = parseInt(a.slice(0, 6), 16) % 360;
  const h2 = (h1 + 60 + (parseInt(a.slice(6, 10), 16) % 160)) % 360;
  const rot = parseInt(a.slice(10, 12), 16) % 360;
  const bx = 8 + (parseInt(a.slice(12, 13), 16) % 18);
  const by = 6 + (parseInt(a.slice(13, 14), 16) % 16);

  return (
    <span className="wallet-av" style={{ width: size, height: size }} aria-hidden>
      <svg viewBox="0 0 40 40" width="100%" height="100%">
        <defs>
          <linearGradient id={`av-${uid}`} gradientTransform={`rotate(${rot} 0.5 0.5)`}>
            <stop offset="0%" stopColor={`hsl(${h1} 72% 60%)`} />
            <stop offset="100%" stopColor={`hsl(${h2} 74% 44%)`} />
          </linearGradient>
        </defs>
        <rect width="40" height="40" rx="20" fill={`url(#av-${uid})`} />
        <circle cx={bx} cy={by} r="8" fill="rgba(255,255,255,0.18)" />
        <circle cx={40 - bx / 2} cy={34} r="5" fill="rgba(0,0,0,0.16)" />
      </svg>
    </span>
  );
}
