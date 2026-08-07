"use client";

import { displayFont, bodyFont } from "@/lib/fonts";
import Link from "next/link";
import { useCollection } from "@/lib/collection";

const display = displayFont;
const mono = bodyFont;

export default function RulesPage() {
  const { slug, display_name } = useCollection();

  return (
    <main className={`race-control ${display.variable} ${mono.variable}`}>
      <div className="rc-grain" aria-hidden />
      <div className="rc-flag" aria-hidden />

      <header className="rc-header">
        <div className="rc-id">
          <span className="rc-kicker">RACE CONTROL // contest rules & guide</span>
          <h1 className="rc-title">Rules &amp; Mechanics</h1>
        </div>
      </header>

      <section className="rc-rules-content">
        <div className="rc-rules-card">
          <h2 className="rc-rules-h2">🏁 Overview</h2>
          <p className="rc-rules-p">
            <strong>{display_name}</strong> is running a Set Collection Race powered by PostMint.
            Holders complete token sets categorized by rarity tiers (from Common up to Mythic).
            Each tier has a limited slot cap — the first holders to complete their sets and hold them
            through the required holding window secure their reward slots on-chain.
          </p>
        </div>

        <div className="rc-rules-grid">
          <article className="rc-rules-card">
            <h3 className="rc-rules-h3">1. Qualify for a Tier</h3>
            <p className="rc-rules-p">
              Each tier specifies a required set rule:
            </p>
            <ul className="rc-rules-list">
              <li>
                <strong>Count of Pool:</strong> Hold a required number of NFTs matching any of the qualifying traits in the pool.
              </li>
              <li>
                <strong>Apex Combo:</strong> Hold distinct NFTs each carrying a specific rare trait requirement.
              </li>
            </ul>
            <p className="rc-rules-sub">
              💡 <em>Tokens are reusable across tiers! A single qualifying NFT can contribute to multiple tier requirements simultaneously.</em>
            </p>
          </article>

          <article className="rc-rules-card">
            <h3 className="rc-rules-h3">2. Your Holding Window Runs Itself</h3>
            <p className="rc-rules-p">
              There is nothing to opt into — your window starts <strong>the moment you completed the set on-chain</strong>
              (your latest qualifying purchase). Long-time holders arrive already eligible to claim;
              fresh buyers see a live 24-hour countdown from their purchase.
            </p>
            <ul className="rc-rules-list">
              <li>
                <strong>Flat Window:</strong> Every tier above Common requires 24 hours of holding. Common tiers claim instantly on qualification.
              </li>
              <li>
                <strong>Transfer Safeguard:</strong> Sell below the required count and your clock restarts from whenever you re-complete the set — holding history is read from the chain, so it can&apos;t be gamed.
              </li>
            </ul>
          </article>

          <article className="rc-rules-card">
            <h3 className="rc-rules-h3">3. Claim On-Chain</h3>
            <p className="rc-rules-p">
              When your window reaches <strong>&ldquo;READY&rdquo;</strong> status:
            </p>
            <ul className="rc-rules-list">
              <li>
                Click <strong>&ldquo;CLAIM SLOT&rdquo;</strong> to request a backend-signed claim attestation.
              </li>
              <li>
                Submit the on-chain transaction via Web3 wallet (e.g. MetaMask, Rabby).
              </li>
              <li>
                Once mined, your slot is locked on-chain and your profile earns <strong>Championship Points (CP)</strong>.
              </li>
            </ul>
          </article>

          <article className="rc-rules-card">
            <h3 className="rc-rules-h3">🏆 Championship Points (CP) &amp; Crests</h3>
            <p className="rc-rules-p">
              Every on-chain slot won awards procedural heraldic <strong>Crests</strong> and CP based on rarity tier:
            </p>
            <ul className="rc-rules-list">
              <li><strong>Mythic:</strong> 50 CP</li>
              <li><strong>Super Rare:</strong> 30 CP</li>
              <li><strong>Rare:</strong> 15 CP</li>
              <li><strong>Uncommon / Common:</strong> 5–10 CP</li>
            </ul>
          </article>
        </div>

        <div className="rc-rules-footer">
          <Link href={`/c/${slug}/race`} className="rc-btn is-green">
            Go to Race Dashboard ▸
          </Link>
          <Link href={`/c/${slug}/standings`} className="rc-btn is-ghost">
            View Championship Standings ↗
          </Link>
        </div>
      </section>
    </main>
  );
}
