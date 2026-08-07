// Global footer — Aceternity footer-with-big-text inspired, rebuilt natively.
// Mounted once in the root layout, so it renders on every page. Link columns +
// fine print, then a giant clipped "POSTMINT" wordmark along the bottom edge
// (gradient-filled, masked, cropped by overflow). Colors flow through --sf-*
// vars with per-scope overrides in globals.css: gold on the holder side, cyan
// under .op-scope, plus light-theme variants.

import Link from "next/link";

const REGISTRY_URL =
  "https://sepolia.basescan.org/address/0x3f9dbffceaea2ed40763765b58009df715494c59";

export function SiteFooter() {
  return (
    <footer className="site-footer">
      <div className="site-footer__inner">
        <div className="site-footer__cols">
          <div className="site-footer__brand">
            <span className="site-footer__logo">PostMint Blocky</span>
            <p>
              The post-mint set collection engine. Trait races, holding windows and
              on-chain prize slots for any NFT collection on Base.
            </p>
          </div>
          <nav className="site-footer__links">
            <span>Race</span>
            <Link href="/">Home</Link>
            <Link href="/paddock">The Paddock</Link>
          </nav>
          <nav className="site-footer__links">
            <span>Build</span>
            <Link href="/studio">Studio console</Link>
          </nav>
          <nav className="site-footer__links">
            <span>On-chain</span>
            <a href={REGISTRY_URL} target="_blank" rel="noreferrer">
              ManifestRegistry ↗
            </a>
            <a href="https://base.org" target="_blank" rel="noreferrer">
              Built on Base ↗
            </a>
          </nav>
        </div>

        <div className="site-footer__fine">
          <p>Crests are earned, never bought. No burns, no locks — your NFTs stay yours.</p>
          <p>© 2026 PostMint</p>
        </div>
      </div>

      <div className="site-footer__bigwrap" aria-hidden>
        <span className="site-footer__big">POSTMINT</span>
      </div>
    </footer>
  );
}
