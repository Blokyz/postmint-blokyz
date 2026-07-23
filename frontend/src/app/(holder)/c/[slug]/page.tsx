"use client";

import { displayFont, bodyFont } from "@/lib/fonts";
import Link from "next/link";
import { Crest } from "@/components/Crest";
import { TIER_META } from "@/lib/crests";
import { useCollection } from "@/lib/collection";

const display = displayFont;
const mono = bodyFont;

const RAMP = Object.entries(TIER_META)
  .sort((a, b) => a[1].rank - b[1].rank)
  .map(([tier]) => tier);

const STEPS = [
  { n: "01", label: "Hold the set", body: "Own the qualifying traits for a tier — the rarer the tier, the tougher the set." },
  { n: "02", label: "Start the clock", body: "Opt in and hold the set continuously through the tier's holding window." },
  { n: "03", label: "Claim your slot", body: "First N per tier to finish take a prize slot on-chain. No per-wallet cap." },
];

export default function CollectionLanding() {
  const { slug, display_name } = useCollection();

  return (
    <main className={`race-control ${display.variable} ${mono.variable}`}>
      <div className="rc-grain" aria-hidden />
      <div className="rc-flag" aria-hidden />

      <header className="rc-header">
        <div className="rc-id">
          <span className="rc-kicker">POSTMINT // contest</span>
          <h1 className="rc-title">{display_name}</h1>
        </div>
      </header>

      <section className="land-hero">
        <div className="land-crests">
          {RAMP.map((tier) => (
            <Crest key={tier} tier={tier} state="qualified" size={64} />
          ))}
        </div>
        <p className="land-lede">
          Assemble a qualifying set of <b>{display_name}</b> traits, hold it through the window, and race to
          be one of the first finishers in your tier. Rarer tiers, bigger prizes.
        </p>
        <div className="land-cta">
          <Link href={`/c/${slug}/race`} className="rc-load">
            ENTER THE RACE <span className="rc-load-arrow">▸</span>
          </Link>
          <Link href={`/c/${slug}/standings`} className="land-secondary">
            View standings
          </Link>
        </div>
      </section>

      <section className="land-how">
        <div className="rc-console-label">// how it works</div>
        <div className="land-steps">
          {STEPS.map((s) => (
            <div key={s.n} className="land-step">
              <span className="land-step-n">{s.n}</span>
              <span className="land-step-label">{s.label}</span>
              <span className="land-step-body">{s.body}</span>
            </div>
          ))}
        </div>
      </section>
    </main>
  );
}
