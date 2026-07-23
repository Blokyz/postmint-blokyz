// Tier -> crest metadata + state model. A "crest" is the earned emblem for a tier
// (our own heraldry layer over the atlas tiers). Colors mirror the atlas TIER_COLOR
// ramp (cold Common -> hot Mythic) so the crest world is visually one with /atlas
// and /race. CP weights match the backend app/claims/standings.py table.

export type CrestState = "won" | "ready" | "racing" | "qualified" | "reset" | "locked";

export type TierMeta = { rank: number; color: string; glyph: string; points: number };

export const TIER_META: Record<string, TierMeta> = {
  Common: { rank: 0, color: "#7c8aa3", glyph: "○", points: 5 },
  Uncommon: { rank: 1, color: "#4f9bd9", glyph: "◇", points: 10 },
  Rare: { rank: 2, color: "#2fc7c0", glyph: "◆", points: 15 },
  "Super Rare": { rank: 3, color: "#8b6df0", glyph: "✦", points: 25 },
  Mythic: { rank: 4, color: "#ffd23f", glyph: "✹", points: 50 },
};

export function tierMeta(tier: string, fallbackRank = 0): TierMeta {
  return TIER_META[tier] ?? { rank: fallbackRank, color: "#7c8aa3", glyph: "◆", points: 5 };
}

// Ring colour + label per crest state (aligned with the race-control palette:
// gold secured, green ready/GO, amber on-track, red reset).
export const STATE_META: Record<CrestState, { label: string; ring: string }> = {
  won: { label: "SECURED", ring: "#ffd23f" },
  ready: { label: "READY", ring: "#c6f24e" },
  racing: { label: "ON TRACK", ring: "#ff9f1c" },
  qualified: { label: "QUALIFIED", ring: "#8b93a0" },
  reset: { label: "RESET", ring: "#ff4d4d" },
  locked: { label: "LOCKED", ring: "#3a3f47" },
};

export function isEarned(state: CrestState): boolean {
  return state === "won";
}
