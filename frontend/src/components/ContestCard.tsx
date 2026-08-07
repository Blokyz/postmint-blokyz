import Link from "next/link";
import { Crest } from "@/components/Crest";
import { TIER_META } from "@/lib/crests";
import { CollectionSummary } from "@/lib/collections";

// The default rarity ramp (Common → Mythic) — at the directory level we only
// know the tier *count* per collection, so cards render that many crests off
// the canonical ramp.
export const RAMP = Object.entries(TIER_META)
  .sort((a, b) => a[1].rank - b[1].rank)
  .map(([tier]) => tier);

const STATUS_LABEL: Record<string, string> = {
  live: "LIVE",
  ending_soon: "ENDING SOON",
  full: "GRID FULL",
  pending: "SETUP",
};

// One contest card (crest-ramp hero + status + stats), shared by the Paddock
// directory grid and the homepage live-contests strip.
export function ContestCard({ c }: { c: CollectionSummary }) {
  return (
    <Link href={`/c/${c.slug}`} className="dir-card">
      <div className="dir-card-hero">
        <div className="dir-crests">
          {RAMP.slice(0, Math.max(1, c.tier_count)).map((tier) => (
            <Crest key={tier} tier={tier} state="qualified" size={38} />
          ))}
        </div>
        <span className={`dir-status is-${c.status}`}>● {STATUS_LABEL[c.status] ?? c.status}</span>
      </div>
      <span className="dir-name">{c.display_name}</span>
      <span className="dir-stats">
        {c.tier_count} tiers · <b>{c.total_filled.toLocaleString()}</b> / {c.total_cap.toLocaleString()} secured
      </span>
      <span className="dir-stats dir-stats--dim">{c.racers} racing now</span>
      <span className="dir-enter">{c.status === "full" ? "VIEW RESULTS ▸" : "ENTER RACE ▸"}</span>
    </Link>
  );
}
