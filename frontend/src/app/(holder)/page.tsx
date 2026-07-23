"use client";

import { ConnectButton } from "@rainbow-me/rainbowkit";
import { displayFont, bodyFont } from "@/lib/fonts";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Crest } from "@/components/Crest";
import { TIER_META } from "@/lib/crests";
import { CollectionSummary, listCollections } from "@/lib/collections";

const display = displayFont;
const mono = bodyFont;

// The default rarity ramp (Common → Mythic) for the card hero — we only know the
// tier *count* per collection at the directory level, so we render that many
// crests off the canonical ramp.
const RAMP = Object.entries(TIER_META)
  .sort((a, b) => a[1].rank - b[1].rank)
  .map(([tier]) => tier);

const STATUS_LABEL: Record<string, string> = {
  live: "LIVE",
  ending_soon: "ENDING SOON",
  full: "GRID FULL",
  pending: "SETUP",
};

export default function DirectoryPage() {
  const [cols, setCols] = useState<CollectionSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listCollections()
      .then(setCols)
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load contests"));
  }, []);

  return (
    <main className={`race-control ${display.variable} ${mono.variable}`}>
      <div className="rc-grain" aria-hidden />
      <div className="rc-flag" aria-hidden />

      <header className="rc-header">
        <div className="rc-id">
          <span className="rc-kicker">POSTMINT // live contests</span>
          <h1 className="rc-title">The&nbsp;Paddock</h1>
        </div>
        <div className="dir-actions">
          <Link href="/studio" className="dir-forprojects">
            For projects ▸
          </Link>
          <ConnectButton accountStatus="address" chainStatus="icon" showBalance={false} />
        </div>
      </header>

      {error && <p className="rc-alert">⨯ {error}</p>}

      {cols && cols.length === 0 && (
        <section className="rc-empty">
          <p>No live contests yet. Once a project publishes its set atlas, it shows up here.</p>
        </section>
      )}

      {cols && cols.length > 0 && (
        <section className="dir-grid">
          {cols.map((c) => (
            <Link key={c.slug} href={`/c/${c.slug}`} className="dir-card">
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
              <span className="dir-enter">ENTER RACE ▸</span>
            </Link>
          ))}
        </section>
      )}
    </main>
  );
}
