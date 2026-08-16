"use client";

import { displayFont, bodyFont } from "@/lib/fonts";
import Image from "next/image";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Crest } from "@/components/Crest";
import { apiGet } from "@/lib/api";
import { useCollection } from "@/lib/collection";
import { tierMeta } from "@/lib/crests";

const display = displayFont;
const mono = bodyFont;

const PAGE_SIZE = 48;

type GalleryTrait = { trait_category: string; trait_value: string };
type GalleryToken = {
  token_id: number;
  image_url: string | null;
  price_eth: number | null;
  opensea_url: string | null;
  traits: GalleryTrait[];
};
type Gallery = {
  contract_address: string;
  tier: string;
  pool_size: number;
  listed_count: number;
  listings_supported: boolean;
  offset: number;
  tokens: GalleryToken[];
};

// ipfs:// metadata URIs need a public gateway; http(s)/data URIs pass through.
function imgSrc(url: string | null): string | null {
  if (!url) return null;
  return url.startsWith("ipfs://") ? `https://ipfs.io/ipfs/${url.slice(7)}` : url;
}

export default function TierPage() {
  const { slug, contract_address, display_name } = useCollection();
  const contract = contract_address;
  const params = useParams();
  // Slug-style param ("super-rare"); the API matches it case/hyphen-insensitively
  // and echoes the canonical tier name back. Until it loads, title-case the slug.
  const tier = decodeURIComponent(String(params.tier ?? ""));

  const [meta, setMeta] = useState<Omit<Gallery, "tokens"> | null>(null);
  const [tokens, setTokens] = useState<GalleryToken[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadPage = useCallback(
    async (offset: number) => {
      setLoading(true);
      setError(null);
      try {
        const g = await apiGet<Gallery>(
          `/gallery/${contract}/${encodeURIComponent(tier)}?limit=${PAGE_SIZE}&offset=${offset}`,
        );
        setMeta(g);
        setTokens((cur) => (offset === 0 ? g.tokens : [...cur, ...g.tokens]));
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load the tier gallery");
      } finally {
        setLoading(false);
      }
    },
    [contract, tier],
  );

  useEffect(() => {
    setTokens([]);
    setMeta(null);
    loadPage(0);
  }, [loadPage]);

  const hasMore = meta !== null && tokens.length < meta.pool_size;
  const tierName = meta?.tier ?? tier.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

  return (
    <main
      className={`race-control tierpage ${display.variable} ${mono.variable}`}
      style={{ "--tier-color": tierMeta(tierName).color } as React.CSSProperties}
    >
      <div className="rc-grain" aria-hidden />
      <div className="rc-flag" aria-hidden />

      <header className="lb-hero">
        <span className="rc-kicker">RACE CONTROL // {display_name}</span>
        <div className="tg-crest">
          <Crest tier={tierName} state="qualified" size={84} />
        </div>
        <h1 className="lb-title">{tierName} Qualifiers</h1>
        <p className="lb-hero-sub">
          Every NFT below carries a trait that qualifies it for the {tierName} tier
          {meta?.listings_supported && " — listed ones first, cheapest on top"}.
        </p>
        <Link href={`/c/${slug}/standings?tab=tiers`} className="tg-back">
          ← Back to the tier grid
        </Link>
      </header>

      {error && <p className="rc-alert">⨯ {error}</p>}

      {meta && (
        <p className="cb-tiergal-note tg-note">
          <b>{meta.pool_size.toLocaleString()}</b> qualifying {tierName} NFTs
          {meta.listings_supported &&
            (meta.listed_count > 0 ? (
              <>
                {" · "}
                <b>{meta.listed_count}</b> listed on OpenSea
              </>
            ) : (
              " · none listed on OpenSea right now"
            ))}
        </p>
      )}

      {meta && meta.pool_size === 0 && (
        <section className="rc-empty">
          <p>No tokens qualify for this tier.</p>
        </section>
      )}

      <section className="cb-tiergal-grid">
        {tokens.map((tok) => {
          const src = imgSrc(tok.image_url);
          const inner = (
            <>
              {src ? (
                src.startsWith("https://") ? (
                  // Server-side optimizer: users get ~20KB cached thumbs
                  // instead of multi-MB originals from IPFS/project hosts.
                  <Image
                    src={src}
                    alt={`#${tok.token_id}`}
                    width={400}
                    height={400}
                    sizes="(max-width: 640px) 45vw, 220px"
                  />
                ) : (
                  // data:/http sources bypass the optimizer (it rejects them).
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={src} alt={`#${tok.token_id}`} loading="lazy" />
                )
              ) : (
                <span className="cb-tiergal-noimg">#{tok.token_id}</span>
              )}
              <span className="cb-tiergal-cap">
                #{tok.token_id}
                {tok.price_eth != null ? (
                  <b>{+tok.price_eth.toFixed(4)} ETH</b>
                ) : (
                  <span className="tg-unlisted">not listed</span>
                )}
              </span>
              <span className="tg-traits">
                {tok.traits.map((tr) => (
                  <span
                    key={`${tr.trait_category}:${tr.trait_value}`}
                    className="tg-trait"
                    title={`${tr.trait_category}: ${tr.trait_value}`}
                  >
                    <span className="tg-trait-cat">{tr.trait_category}</span>
                    <span className="tg-trait-val">{tr.trait_value}</span>
                  </span>
                ))}
              </span>
              {tok.opensea_url && (
                <span className="tg-buy">{tok.price_eth != null ? "Buy on OpenSea ↗" : "View on OpenSea ↗"}</span>
              )}
            </>
          );
          return tok.opensea_url ? (
            <a
              key={tok.token_id}
              className="cb-tiergal-item"
              href={tok.opensea_url}
              target="_blank"
              rel="noreferrer"
            >
              {inner}
            </a>
          ) : (
            <span key={tok.token_id} className="cb-tiergal-item">
              {inner}
            </span>
          );
        })}
      </section>

      {loading && <p className="cb-tiergal-note tg-note">Loading…</p>}
      {meta && hasMore && !loading && (
        <button className="tg-more" onClick={() => loadPage(tokens.length)}>
          Load more ({tokens.length.toLocaleString()} of {meta.pool_size.toLocaleString()})
        </button>
      )}
    </main>
  );
}
