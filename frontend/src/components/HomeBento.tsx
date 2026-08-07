"use client";

// Homepage bento feature grid — inspired by Aceternity's symmetric-bento-grid
// block, rebuilt natively for this app (no Tailwind / framer-motion here).
// Symmetric layout on a 4-col grid: [2·1·1] over [1·1·2]. Cards bounce in with
// a staggered rotateX reveal the first time the grid scrolls into view
// (IntersectionObserver → .is-in); interiors run small CSS-only loops (trait
// chips collecting, holding-window clock sweep, slot grid filling, CP pop,
// atlas tier bars). Hover lift uses the separate `translate` property so it
// composes with the reveal animation's `forwards` fill. All animation respects
// prefers-reduced-motion (see .bento-* CSS in globals.css).

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Crest } from "@/components/Crest";

function useInView<T extends HTMLElement>() {
  const ref = useRef<T | null>(null);
  const [inView, setInView] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setInView(true);
          obs.disconnect();
        }
      },
      { threshold: 0.12 },
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, []);
  return { ref, inView };
}

const CHIPS = ["EYES · LASER", "FUR · GOLD", "HAT · CROWN"];

export function HomeBento() {
  const { ref, inView } = useInView<HTMLDivElement>();

  return (
    <section className="home-bento">
      <h2 className="home-kicker">// THE CIRCUIT — how a contest works</h2>

      <div ref={ref} className={`bento-grid${inView ? " is-in" : ""}`}>
        {/* 01 — assemble the set (wide) */}
        <article className="bento-card bento-card--w2" style={{ "--bento-i": 0 } as React.CSSProperties}>
          <span className="bento-tag">01 · HOLD THE SET</span>
          <h3>Assemble the qualifying set</h3>
          <p>
            Every tier asks for a set of qualifying traits — the rarer the tier, the tougher
            the set. Your NFTs are never locked or burned.
          </p>
          <div className="bento-viz bento-viz--chips" aria-hidden>
            <div className="bento-chiprow">
              {CHIPS.map((c, i) => (
                <span key={c} className="bento-chip" style={{ "--chip-i": i } as React.CSSProperties}>
                  {c}
                </span>
              ))}
            </div>
            <div className="bento-meter">
              <span className="bento-meter-fill" />
            </div>
            <span className="bento-viz-label">SET PROGRESS · 3 / 3</span>
          </div>
        </article>

        {/* 02 — beat the clock */}
        <article className="bento-card" style={{ "--bento-i": 1 } as React.CSSProperties}>
          <span className="bento-tag">02 · BEAT THE CLOCK</span>
          <h3>Survive the holding window</h3>
          <p>Your clock runs from the moment you complete the set on-chain — long holders claim instantly. Sell a piece and it restarts.</p>
          <div className="bento-viz bento-viz--clock" aria-hidden>
            <span className="bento-dial">
              <span className="bento-dial-hand" />
            </span>
            <span className="bento-clock-digits">
              24<em>:</em>00<em>:</em>00
            </span>
          </div>
        </article>

        {/* 03 — claim the slot */}
        <article className="bento-card" style={{ "--bento-i": 2 } as React.CSSProperties}>
          <span className="bento-tag">03 · CLAIM YOUR SLOT</span>
          <h3>First finishers win on-chain</h3>
          <p>First N per tier secure a slot on-chain. Rarer tiers, bigger prizes.</p>
          <div className="bento-viz bento-viz--slots" aria-hidden>
            {["P1", "P2", "P3", "P4", "P5"].map((p, i) => (
              <span key={p} className="bento-slot" style={{ "--slot-i": i } as React.CSSProperties}>
                {p}
              </span>
            ))}
          </div>
        </article>

        {/* Crests & CP */}
        <article className="bento-card" style={{ "--bento-i": 3 } as React.CSSProperties}>
          <span className="bento-tag">THE TROPHIES</span>
          <h3>Crests &amp; Championship Points</h3>
          <p>Wins mint Crests onto your Driver Card and score CP on the Standings.</p>
          <div className="bento-viz bento-viz--crests" aria-hidden>
            <Crest tier="Rare" state="qualified" size={44} />
            <Crest tier="Super Rare" state="ready" size={44} />
            <Crest tier="Mythic" state="won" size={52} />
            <span className="bento-cp">+50 CP</span>
          </div>
        </article>

        {/* collectors door */}
        <article className="bento-card bento-card--door" style={{ "--bento-i": 4 } as React.CSSProperties}>
          <span className="bento-tag">FOR COLLECTORS</span>
          <h3>Race for Crests</h3>
          <p>
            See exactly which of your traits qualify — and what to buy to finish a set. Live
            grids, clocks and standings per collection.
          </p>
          <Link href="/paddock" className="home-cta home-cta--gold bento-cta">
            Enter The Paddock
          </Link>
        </article>

        {/* projects door (wide, cyan) */}
        <article
          className="bento-card bento-card--w2 bento-card--cyan"
          style={{ "--bento-i": 5 } as React.CSSProperties}
        >
          <span className="bento-tag">FOR PROJECTS</span>
          <h3>Give your mint a second act</h3>
          <p>
            Ingest your collection, tune tier caps and set sizes in the Set Atlas, lock
            the season on-chain — then watch measurable buy pressure form around your traits.
          </p>
          <div className="bento-viz bento-viz--bars" aria-hidden>
            {[0, 1, 2, 3, 4].map((i) => (
              <span key={i} className="bento-bar" style={{ "--bar-i": i } as React.CSSProperties} />
            ))}
          </div>
          <Link href="/studio" className="home-cta home-cta--cyan bento-cta">
            Open the Studio
          </Link>
        </article>
      </div>
    </section>
  );
}
