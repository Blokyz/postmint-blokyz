"use client";

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api";
import { buildOpenSeaTokenUrl, buildOpenSeaTraitUrl } from "@/lib/marketplace";

type PoolTrait = {
  trait_category: string;
  trait_value: string;
  token_count: number;
};

type CrossTierImpact = {
  tier: string;
  current_progress_pct: number;
  projected_progress_pct: number;
  current_needed: number;
  projected_needed: number;
};

type ShortTierGuidance = {
  tier: string;
  needed: number;
  pool_traits: PoolTrait[];
  candidate_token_ids: number[];
  cross_tier_impact: CrossTierImpact[];
};

type ShoppingResponse = {
  chain: string;
  short_tiers: ShortTierGuidance[];
};

interface ShoppingPanelProps {
  contract: string;
  wallet: string;
  tier: string;
  needed: number;
  chain: string;
}

export function ShoppingPanel({
  contract,
  wallet,
  tier,
  needed,
  chain: chainProp,
}: ShoppingPanelProps) {
  const [data, setData] = useState<ShoppingResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open || !contract || !wallet) return;
    let cancelled = false;

    async function fetchShopping() {
      setLoading(true);
      try {
        const json = await apiGet<ShoppingResponse>(
          `/eligibility/${contract}/${wallet}/shopping`
        );
        if (!cancelled) setData(json);
      } catch {
        /* ignore fetch errors */
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    fetchShopping();
    return () => {
      cancelled = true;
    };
  }, [open, contract, wallet]);

  const chain = data?.chain ?? chainProp;
  const guidance = data?.short_tiers?.find((st) => st.tier === tier);

  return (
    <div className="rc-shopping">
      <button
        type="button"
        className="rc-shopping-toggle"
        onClick={() => setOpen((prev) => !prev)}
      >
        <span className="rc-shopping-icon">🛒</span>
        <span className="rc-shopping-toggle-text">
          {open ? "Hide Shopping Guidance" : `Complete Your Set (Need ${needed} more)`}
        </span>
        <span className="rc-shopping-arrow">{open ? "▲" : "▼"}</span>
      </button>

      {open && (
        <div className="rc-shopping-body">
          {loading && !guidance && (
            <p className="rc-shopping-loading">Searching candidate tokens & traits…</p>
          )}

          {guidance && (
            <>
              {/* Needed Header */}
              <div className="rc-shopping-head">
                <span className="rc-shopping-badge">GUIDANCE</span>
                <p className="rc-shopping-lede">
                  Need <strong>{guidance.needed}</strong> more qualifying token
                  {guidance.needed === 1 ? "" : "s"} to qualify for <strong>{tier}</strong>.
                  Hold any NFT matching the pool traits below.
                </p>
              </div>

              {/* Pool Traits (Commoner first) */}
              {guidance.pool_traits.length > 0 && (
                <div className="rc-shopping-section">
                  <div className="rc-shopping-subhead">
                    <span>QUALIFYING TRAITS</span>
                    <span className="rc-shopping-subhead-hint">
                      Sorted commoner-first ≈ cheaper floor
                    </span>
                  </div>
                  <div className="rc-shopping-traits">
                    {guidance.pool_traits.slice(0, 8).map((pt) => {
                      const osUrl = buildOpenSeaTraitUrl(
                        chain,
                        contract,
                        pt.trait_category,
                        pt.trait_value
                      );
                      return (
                        <div
                          key={`${pt.trait_category}-${pt.trait_value}`}
                          className="rc-shopping-trait-card"
                        >
                          <div className="rc-shopping-trait-info">
                            <span className="rc-shopping-trait-cat" title={pt.trait_category}>
                              {pt.trait_category.toLowerCase() === "background" ? "BG" : pt.trait_category}:
                            </span>
                            <span className="rc-shopping-trait-val" title={pt.trait_value}>
                              {pt.trait_value}
                            </span>
                            {pt.token_count > 0 && (
                              <span className="rc-shopping-trait-count">
                                {pt.token_count} in collection
                              </span>
                            )}
                          </div>
                          <div className="rc-shopping-links">
                            <a
                              href={osUrl}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="rc-shopping-btn os"
                              title="Search listings on OpenSea"
                            >
                              OpenSea ↗
                            </a>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Unowned candidate token IDs */}
              {guidance.candidate_token_ids.length > 0 && (
                <div className="rc-shopping-section">
                  <div className="rc-shopping-subhead">
                    <span>QUALIFYING TOKEN SAMPLES</span>
                    <span className="rc-shopping-subhead-hint">
                      Token IDs owned by others
                    </span>
                  </div>
                  <div className="rc-shopping-tokens">
                    {guidance.candidate_token_ids.map((id) => {
                      const osTokenUrl = buildOpenSeaTokenUrl(chain, contract, id);
                      return (
                        <a
                          key={id}
                          href={osTokenUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="rc-shopping-token-chip"
                          title={`View token #${id} on OpenSea`}
                        >
                          #{id} ↗
                        </a>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Cross-Tier Impact */}
              {guidance.cross_tier_impact.length > 0 && (
                <div className="rc-shopping-impact">
                  <div className="rc-shopping-impact-title">
                    <span>⚡ CROSS-TIER IMPACT</span>
                  </div>
                  {guidance.cross_tier_impact.map((ci) => (
                    <p key={ci.tier} className="rc-shopping-impact-desc">
                      Buying tokens for {tier} also boosts <strong>{ci.tier}</strong> progress
                      from <strong>{ci.current_progress_pct}%</strong> to{" "}
                      <strong>{ci.projected_progress_pct}%</strong> (needs {ci.projected_needed}{" "}
                      instead of {ci.current_needed}).
                    </p>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
