"use client";

// "/" — PostMint front door. Explains the product and routes the two audiences:
// holders → /paddock (contest directory), project owners → /studio.
// The contest directory itself lives at /paddock since 2026-07-31.

import { displayFont, bodyFont } from "@/lib/fonts";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Crest } from "@/components/Crest";
import { ContestCard, RAMP } from "@/components/ContestCard";
import { HomeBento } from "@/components/HomeBento";
import { SiteHeader } from "@/components/SiteHeader";
import { CollectionSummary, listCollections } from "@/lib/collections";

const display = displayFont;
const mono = bodyFont;

export default function HomePage() {
  const [cols, setCols] = useState<CollectionSummary[] | null>(null);

  useEffect(() => {
    listCollections().then(setCols).catch(() => setCols(null));
  }, []);

  const live = (cols ?? []).filter((c) => c.status !== "full").slice(0, 3);

  return (
    <>
      <SiteHeader />
      <main className={`race-control home ${display.variable} ${mono.variable}`}>
      <div className="rc-grain" aria-hidden />
      <div className="rc-flag" aria-hidden />

      {/* ---- Hero: the race start (beams-and-grid backdrop, CSS-only) ---- */}
      <section className="home-hero">
        <div className="hero-bg" aria-hidden>
          <div className="hero-grid" />
          {[0, 1, 2, 3, 4].map((i) => (
            <span key={i} className="hero-beam" style={{ "--beam-i": i } as React.CSSProperties} />
          ))}
        </div>

        <p className="home-eyebrow">POSTMINT // POST-MINT SET COLLECTION · BUILT ON BASE</p>

        <h1 className="home-headline">
          <span className="home-line">Hold the set.</span>
          <span className="home-line">Beat the clock.</span>
          <span className="home-line home-line--gold">Claim your slot.</span>
        </h1>

        <p className="home-lede">
          PostMint turns any NFT collection into a live trait-collecting race. Assemble a
          qualifying set, hold it through the tier&apos;s window, and be one of the first
          finishers to secure a prize slot on-chain — no burns, no locks, no new mints.
        </p>

        <div className="home-cta-row">
          <Link href="/paddock" className="home-cta home-cta--gold">
            Enter The Paddock <em>for collectors</em>
          </Link>
          <Link href="/studio" className="home-cta home-cta--cyan">
            Open the Studio <em>for projects</em>
          </Link>
        </div>

        <div className="home-ramp" aria-hidden>
          {RAMP.map((tier) => (
            <Crest key={tier} tier={tier} state="qualified" size={52} />
          ))}
        </div>
      </section>

      {/* ---- How it works + the two audience doors, as one bento grid ---- */}
      <HomeBento />

      {/* ---- Live contests strip (real data) ---- */}
      {live.length > 0 && (
        <section className="home-live">
          <div className="home-live-head">
            <h2 className="home-kicker">// ON TRACK NOW</h2>
            <Link href="/paddock" className="home-live-all">
              View the full grid ▸
            </Link>
          </div>
          <div className="dir-grid home-live-grid">
            {live.map((c) => (
              <ContestCard key={c.slug} c={c} />
            ))}
          </div>
        </section>
      )}

      </main>
    </>
  );
}
