"use client";

import { displayFont, bodyFont } from "@/lib/fonts";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useAccount } from "wagmi";
import { Crest } from "@/components/Crest";
import { InfoTip } from "@/components/InfoTip";
import { WalletAvatar } from "@/components/WalletAvatar";
import { apiGet, shortAddr } from "@/lib/api";
import { useCollection } from "@/lib/collection";
import { tierMeta } from "@/lib/crests";

const display = displayFont;
const mono = bodyFont;

type TierRow = {
  tier: string;
  rank: number;
  cap: number;
  slots_filled: number;
  slots_remaining: number;
  racers: number;
  points: number;
};
type Collector = {
  wallet_address: string;
  tiers_won: string[];
  championship_points: number;
  badges_won: number;
  rank: number;
  latest_at: string | null;
};
type Standings = { contract_address: string; tiers: TierRow[]; collectors: Collector[] };

const SHOW_OPTIONS = [25, 50, 100];

// Collapse a wallet's repeated tier wins into {tier: count}.
function tierCounts(tiers: string[]): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const t of tiers) counts[t] = (counts[t] ?? 0) + 1;
  return counts;
}

// useSearchParams requires a Suspense boundary at build time.
export default function StandingsPage() {
  return (
    <Suspense fallback={null}>
      <StandingsInner />
    </Suspense>
  );
}

function StandingsInner() {
  const { slug, contract_address, display_name } = useCollection();
  const contract = contract_address;
  const { address } = useAccount();
  const me = address?.toLowerCase();
  const router = useRouter();

  // The active tab lives in the URL (?tab=tiers) so navigating into a tier page
  // and coming BACK restores the Tiers view instead of resetting to Standings.
  const tab: "standings" | "tiers" =
    useSearchParams().get("tab") === "tiers" ? "tiers" : "standings";
  const setTab = (t: "standings" | "tiers") =>
    router.replace(t === "tiers" ? `/c/${slug}/standings?tab=tiers` : `/c/${slug}/standings`, {
      scroll: false,
    });

  const [data, setData] = useState<Standings | null>(null);
  const [query, setQuery] = useState("");
  const [show, setShow] = useState(25);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setData(await apiGet<Standings>(`/standings/${contract}`));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load standings");
      setData(null);
    }
  }, [contract]);

  useEffect(() => {
    load();
  }, [load]);

  // Full tier ramp (Common -> Mythic), the medallion strip shown on every row.
  const ramp = useMemo(
    () => (data ? [...data.tiers].sort((a, b) => a.rank - b.rank) : []),
    [data],
  );

  const filtered = useMemo(() => {
    if (!data) return [];
    const q = query.trim().toLowerCase();
    const rows = q
      ? data.collectors.filter((c) => c.wallet_address.toLowerCase().includes(q))
      : data.collectors;
    return rows.slice(0, show);
  }, [data, query, show]);

  const totalTiers = ramp.length;

  return (
    <main className={`race-control lb ${display.variable} ${mono.variable}`}>
      <div className="rc-grain" aria-hidden />
      <div className="rc-flag" aria-hidden />

      <header className="lb-hero">
        <span className="rc-kicker">RACE CONTROL // {display_name}</span>
        <h1 className="lb-title">Championship Standings</h1>
        <p className="lb-hero-sub">
          See who&apos;s securing crests — or dive into the tier grid.
          <InfoTip text="Championship Points (CP) are earned for every slot won on-chain — rarer tiers pay more. A Crest lights up for each tier a driver has secured." />
        </p>
      </header>

      <div className="lb-tabs">
        <div className="cb-tabs" role="tablist">
          <button className={`cb-tab${tab === "standings" ? " is-on" : ""}`} onClick={() => setTab("standings")}>
            Standings
          </button>
          <button className={`cb-tab${tab === "tiers" ? " is-on" : ""}`} onClick={() => setTab("tiers")}>
            Tiers
          </button>
        </div>
      </div>

      {error && <p className="rc-alert">⨯ {error}</p>}

      {data && tab === "standings" && (
        <>
          <div className="lb-controls">
            <div className="lb-search">
              <span className="lb-search-icon" aria-hidden>⌕</span>
              <input
                type="search"
                placeholder="Search by wallet address…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                aria-label="Search standings by wallet address"
              />
            </div>
            <div className="lb-show">
              <span>Show</span>
              {SHOW_OPTIONS.map((n) => (
                <button key={n} className={`lb-show-opt${show === n ? " is-on" : ""}`} onClick={() => setShow(n)}>
                  {n}
                </button>
              ))}
            </div>
          </div>

          {data.collectors.length === 0 ? (
            <section className="rc-empty">
              <p>No finishers yet — nobody has secured a slot on this collection.</p>
            </section>
          ) : filtered.length === 0 ? (
            <section className="rc-empty">
              <p>No wallet matches “{query}”.</p>
            </section>
          ) : (
            <section className="lb-board">
              {filtered.map((c) => {
                const mine = me && c.wallet_address.toLowerCase() === me;
                const counts = tierCounts(c.tiers_won);
                const distinctWon = Object.keys(counts).length;
                return (
                  <Link
                    key={c.wallet_address}
                    href={`/c/${slug}/driver/${c.wallet_address}`}
                    className={`lb-row${mine ? " is-me" : ""}`}
                  >
                    <span className="lb-rank">{String(c.rank).padStart(2, "0")}</span>
                    <WalletAvatar address={c.wallet_address} size={46} />
                    <span className="lb-who">
                      <span className="lb-name">
                        {shortAddr(c.wallet_address)}
                        {mine && <span className="lb-you">you</span>}
                      </span>
                      <span className="lb-sub">
                        <b>{c.championship_points}</b> CP
                        {c.badges_won > distinctWon && ` · ${c.badges_won} slots swept`}
                      </span>
                    </span>
                    <span className="lb-crests">
                      {ramp.map((t) => (
                        <Crest
                          key={t.tier}
                          tier={t.tier}
                          state={counts[t.tier] ? "won" : "locked"}
                          size={30}
                          count={counts[t.tier] ?? 0}
                        />
                      ))}
                    </span>
                    <span className="lb-frac">
                      <b>{distinctWon}</b>
                      <span className="lb-frac-sep">/</span>
                      {totalTiers}
                    </span>
                  </Link>
                );
              })}
            </section>
          )}
        </>
      )}

      {data && tab === "tiers" && (
        <section className="cb-tiergrid">
          {ramp.map((t) => {
            const pct = t.cap > 0 ? Math.min(100, (t.slots_filled / t.cap) * 100) : 0;
            const state = t.slots_remaining <= 0 ? "won" : t.racers > 0 ? "racing" : "qualified";
            return (
              <Link
                key={t.tier}
                href={`/c/${slug}/tiers/${t.tier.toLowerCase().replace(/\s+/g, "-")}`}
                className="cb-tiercard"
                style={{ "--tier-color": tierMeta(t.tier, t.rank).color } as React.CSSProperties}
              >
                <Crest tier={t.tier} state={state} size={72} rank={t.rank} progressPct={pct} />
                <div className="cb-tierbody">
                  <div className="cb-tiertop">
                    <span className="cb-tiername">{t.tier}</span>
                    <span className="cb-tierpts">{t.points} CP</span>
                  </div>
                  <div className="cb-tierbar">
                    <div className="cb-tierbar-fill" style={{ width: `${pct}%` }} />
                  </div>
                  <div className="cb-tiermeta">
                    <b>{t.slots_filled}</b> / {t.cap} secured · {t.slots_remaining} open · {t.racers} racing
                  </div>
                  <span className="cb-tierview">View qualifying NFTs →</span>
                </div>
              </Link>
            );
          })}
        </section>
      )}
    </main>
  );
}
