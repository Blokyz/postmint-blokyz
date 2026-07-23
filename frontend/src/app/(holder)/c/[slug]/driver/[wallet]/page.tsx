"use client";

import { displayFont, bodyFont } from "@/lib/fonts";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { useAccount } from "wagmi";
import { Crest } from "@/components/Crest";
import { ADDRESS_RE, API_URL, shortAddr } from "@/lib/api";
import { useCollection } from "@/lib/collection";
import { CrestState, STATE_META } from "@/lib/crests";

const display = displayFont;
const mono = bodyFont;

type DriverTier = {
  tier: string;
  rank: number;
  state: CrestState;
  won_count: number;
  slot_numbers: number[];
  held_count: number;
  count_required: number;
  progress_pct: number;
  needed: number;
  points: number;
};
type Driver = {
  contract_address: string;
  wallet_address: string;
  championship_points: number;
  badges_won: number;
  tiers: DriverTier[];
};

export default function DriverPage() {
  const { slug, contract_address } = useCollection();
  const contract = contract_address;
  const params = useParams();
  const wallet = String(params.wallet ?? "").toLowerCase();
  const { address } = useAccount();
  const isMe = address?.toLowerCase() === wallet;

  const [data, setData] = useState<Driver | null>(null);
  const [error, setError] = useState<string | null>(null);

  const validWallet = ADDRESS_RE.test(wallet);

  const load = useCallback(async () => {
    setError(null);
    try {
      const res = await fetch(`${API_URL}/driver/${contract}/${wallet}`);
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail ?? `No driver card for this collection (${res.status})`);
      }
      setData(await res.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load driver card");
      setData(null);
    }
  }, [contract, wallet]);

  useEffect(() => {
    if (validWallet) load();
  }, [validWallet, load]);

  return (
    <main className={`race-control ${display.variable} ${mono.variable}`}>
      <div className="rc-grain" aria-hidden />
      <div className="rc-flag" aria-hidden />

      <header className="rc-header">
        <div className="rc-id">
          <span className="rc-kicker">RACE CONTROL // driver card</span>
          <h1 className="rc-title">{validWallet ? shortAddr(wallet) : "Unknown"}</h1>
        </div>
        {data && (
          <div className="dc-score">
            <span className="dc-cp">{data.championship_points}</span>
            <span className="dc-cp-cap">CHAMPIONSHIP PTS</span>
          </div>
        )}
      </header>

      {!validWallet && (
        <section className="rc-empty">
          <p>That wallet address is not valid.</p>
        </section>
      )}
      {error && <p className="rc-alert">⨯ {error}</p>}

      {data && (
        <>
          <div className="dc-summary">
            <span className="dc-badges">
              <b>{data.badges_won}</b> crest{data.badges_won === 1 ? "" : "s"} secured
            </span>
            {isMe && (
              <Link href={`/c/${slug}/race`} className="dc-cta">
                Race for more ▸
              </Link>
            )}
          </div>

          <section className="dc-cabinet">
            <div className="rc-console-label">// trophy cabinet</div>
            <div className="dc-grid">
              {data.tiers.map((t) => (
                <article key={t.tier} className={`dc-slot is-${t.state}`}>
                  <Crest
                    tier={t.tier}
                    state={t.state}
                    size={88}
                    rank={t.rank}
                    progressPct={t.progress_pct}
                    count={t.won_count}
                  />
                  <span className="dc-tier">{t.tier}</span>
                  <span className={`dc-state is-${t.state}`}>{STATE_META[t.state].label}</span>
                  <span className="dc-detail">
                    {t.state === "won"
                      ? t.slot_numbers.length
                        ? `slot${t.slot_numbers.length > 1 ? "s" : ""} ${t.slot_numbers.map((s) => `#${s}`).join(", ")}`
                        : "secured"
                      : t.state === "locked"
                        ? `need ${t.needed} more`
                        : `${t.held_count}/${t.count_required} held`}
                  </span>
                </article>
              ))}
            </div>
          </section>
        </>
      )}
    </main>
  );
}
