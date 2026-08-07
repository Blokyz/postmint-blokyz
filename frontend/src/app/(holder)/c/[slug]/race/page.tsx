"use client";

import { ConnectButton } from "@rainbow-me/rainbowkit";
import { displayFont, bodyFont } from "@/lib/fonts";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  useAccount,
  useChainId,
  useSwitchChain,
  useWaitForTransactionReceipt,
  useWriteContract,
} from "wagmi";
import { API_URL, apiPost, shortAddr } from "@/lib/api";
import { useCollection } from "@/lib/collection";
import { explorerTxUrl } from "@/lib/manifestRegistry";
import { ClaimAttestation, SET_CLAIM_MANAGER_ABI, claimArgs } from "@/lib/setClaimManager";
import { ShoppingPanel } from "@/components/ShoppingPanel";
import { ClaimConfirmModal } from "@/components/ClaimConfirmModal";
import { InfoTip } from "@/components/InfoTip";

const display = displayFont;
const mono = bodyFont;

const REFRESH_MS = 15000;
const CLAIM_CHAIN = 84532; // Base Sepolia — the chain seasons deploy on (podium tx links)
// The backend verifies the claim tx on-chain; its RPC can briefly lag behind the
// wallet's, so a freshly-mined tx may not be visible yet (409 retryable). Retry a
// bounded number of times before giving up rather than falsely claiming success.
const CONFIRM_MAX_RETRIES = 6;
const CONFIRM_RETRY_MS = 4000;

const TIER_ACCENT: Record<string, string> = {
  Common: "#8b93a0",
  Uncommon: "#6fd08c",
  Rare: "#5aa9ff",
  "Super Rare": "#c07bff",
  Mythic: "#ffd23f",
};

type Eligibility = {
  tier: string;
  archetype: string;
  count_required: number;
  held_count: number;
  qualifying_token_ids: number[];
  qualifies: boolean;
  progress_pct: number;
  needed: number;
};

type WindowStatus = {
  tier: string;
  window_seconds: number;
  qualifies: boolean;
  held_count: number;
  count_required: number;
  progress_pct: number;
  qualifying_token_ids: number[];
  // The moment the wallet completed the set on-chain (its X-th qualifying
  // acquisition) — the window runs from here automatically. Null for
  // zero-window tiers and non-qualifying wallets.
  window_started: string | null;
  status: "not_started" | "racing" | "ready" | "won";
  ready_at?: string | null;
  seconds_remaining: number | null;
};

type Winner = {
  wallet_address: string;
  slot_number: number | null;
  tokens: number[];
  tx_hash: string;
  won_at: string | null;
};

type Leaderboard = {
  tier: string;
  cap: number;
  window_seconds: number;
  slots_filled: number;
  slots_remaining: number;
  winners: Winner[];
  // Wallets currently holding the qualifying set (every one is racing by
  // definition — windows derive from acquisition history).
  racers: { wallet_address: string; held_count: number; status: string }[];
  total_racers: number;
};

type Lane = { elig: Eligibility; ws: WindowStatus; lb: Leaderboard };

const STATE_LABEL: Record<string, string> = {
  racing: "ON TRACK",
  ready: "GO",
  won: "FINISHED",
  full: "GRID FULL",
  locked: "NOT ELIGIBLE",
};

// HH:MM:SS scoreboard clock; prefixes whole days when the window is long.
function formatClock(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  const days = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  const hms = `${pad(h)}:${pad(m)}:${pad(sec)}`;
  return days > 0 ? `${days}d ${hms}` : hms;
}

function humanizeError(e: unknown): string {
  const msg = e instanceof Error ? e.message : String(e);
  if (/User rejected|User denied|rejected the request/i.test(msg)) return "Transaction rejected in your wallet.";
  if (/Tier full/.test(msg)) return "This tier's grid is full — every slot is taken.";
  if (/Window not elapsed/.test(msg)) return "Holding window hasn't elapsed yet.";
  if (/Nonce used/.test(msg)) return "That claim ticket was already used — refresh and retry.";
  if (/Signature expired/.test(msg)) return "Claim ticket expired — request a fresh one.";
  if (/Unauthorized|bad backend signature/.test(msg)) return "Contract rejected the backend signature.";
  return msg.split("\n")[0].slice(0, 200);
}

export default function RacePage() {
  const { contract_address, display_name, chain } = useCollection();
  const contract = contract_address;
  const { address, isConnected } = useAccount();
  const wallet = address?.toLowerCase();
  const chainId = useChainId();
  const { switchChainAsync } = useSwitchChain();
  const { writeContractAsync } = useWriteContract();

  const [lanes, setLanes] = useState<Lane[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // The single in-flight claim (users claim one lane at a time). We wait on its
  // receipt with a hook, then POST /claim/confirm. `startedAt` powers the
  // chain-sync fallback below (smart-account wallets wrap the tx, so this hash
  // can be a phantom that never mines even though the real claim succeeded).
  const [pending, setPending] = useState<{ tier: string; hash: `0x${string}`; chainId: number; startedAt?: number } | null>(null);
  const [busyTier, setBusyTier] = useState<string | null>(null);
  const { isSuccess: mined } = useWaitForTransactionReceipt({ hash: pending?.hash, chainId: pending?.chainId });
  const confirmAttempt = useRef(0);

  // 1s ticker so racing countdowns move without refetching.
  const [, setTick] = useState(0);
  const loadedAt = useRef<number>(0);

  // Ready notifications (the retention lever). Tiers already ready when the grid
  // first evaluates are seeded silently — only a live racing→ready flip notifies.
  const notifiedTiers = useRef<Set<string>>(new Set());
  const notifySeeded = useRef(false);

  // Persist the in-flight claim so a reload / tab-close can resume confirmation:
  // the tx is already on-chain, only the DB record is missing. Keyed per contract.
  const pendingKey = contract ? `pmb:pendingClaim:${contract.toLowerCase()}` : null;

  // Restore a persisted pending claim on mount. useWaitForTransactionReceipt then
  // re-subscribes to its hash, re-driving the confirm effect below.
  useEffect(() => {
    if (!pendingKey) return;
    try {
      const raw = localStorage.getItem(pendingKey);
      if (raw) {
        const saved = JSON.parse(raw);
        if (saved?.hash && saved?.tier) {
          setPending(saved);
          setBusyTier(saved.tier);
        }
      }
    } catch {
      /* ignore malformed storage */
    }
  }, [pendingKey]);

  // Mirror pending → localStorage (written before the tx is sent, cleared on resolve).
  useEffect(() => {
    if (!pendingKey) return;
    try {
      if (pending) localStorage.setItem(pendingKey, JSON.stringify(pending));
      else localStorage.removeItem(pendingKey);
    } catch {
      /* ignore quota / disabled storage */
    }
  }, [pending, pendingKey]);

  const load = useCallback(
    async (wal: string) => {
      setLoading(true);
      setError(null);
      try {
        const eRes = await fetch(`${API_URL}/eligibility/${contract}/${wal}`);
        if (!eRes.ok) {
          const body = await eRes.json().catch(() => null);
          throw new Error(body?.detail ?? `No race for this collection (${eRes.status})`);
        }
        const elig: { tiers: Eligibility[] } = await eRes.json();
        const details = await Promise.all(
          elig.tiers.map(async (t) => {
            const [ws, lb] = await Promise.all([
              fetch(`${API_URL}/claim/status/${contract}/${encodeURIComponent(t.tier)}/${wal}`).then((r) => r.json()),
              fetch(`${API_URL}/leaderboard/${contract}/${encodeURIComponent(t.tier)}`).then((r) => r.json()),
            ]);
            return { elig: t, ws, lb } as Lane;
          }),
        );
        loadedAt.current = Date.now();
        setLanes(details);
        // Windows run automatically now (no opt-in click), so ask for
        // notification permission as soon as a countdown is actually live.
        if (
          details.some((l) => l.ws.status === "racing") &&
          typeof Notification !== "undefined" &&
          Notification.permission === "default"
        ) {
          Notification.requestPermission().catch(() => {});
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load race");
        setLanes(null);
      } finally {
        setLoading(false);
      }
    },
    [contract],
  );

  // Auto-load once a wallet is connected (the grid is per-wallet).
  useEffect(() => {
    if (wallet) load(wallet);
    else setLanes(null);
  }, [wallet, load]);

  // Periodic refresh while any lane is on track / ready, plus the 1s ticker.
  useEffect(() => {
    if (!wallet) return;
    const anyRacing = lanes?.some((l) => l.ws.status === "racing" || l.ws.status === "ready");
    const tickId = setInterval(() => setTick((n) => n + 1), 1000);
    const refreshId = anyRacing ? setInterval(() => load(wallet), REFRESH_MS) : null;
    return () => {
      clearInterval(tickId);
      if (refreshId) clearInterval(refreshId);
    };
  }, [wallet, lanes, load]);

  // Fire a notification the moment a racing lane's countdown crosses zero. Runs
  // every render (the 1s ticker drives it) but each tier notifies at most once.
  useEffect(() => {
    if (!lanes) return;
    const elapsed = Math.floor((Date.now() - loadedAt.current) / 1000);
    const readyTiers = lanes
      .filter((l) => {
        if (l.ws.status === "ready") return true;
        if (l.ws.status === "racing" && l.ws.seconds_remaining != null)
          return l.ws.seconds_remaining - elapsed <= 0;
        return false;
      })
      .map((l) => l.elig.tier);

    if (!notifySeeded.current) {
      readyTiers.forEach((t) => notifiedTiers.current.add(t));
      notifySeeded.current = true;
      return;
    }

    // A tier actively counting down again (e.g. a fresh window after a win)
    // re-arms its notification.
    for (const l of lanes) {
      if (l.ws.status === "racing" && l.ws.seconds_remaining != null && l.ws.seconds_remaining - elapsed > 0)
        notifiedTiers.current.delete(l.elig.tier);
    }

    for (const tier of readyTiers) {
      if (notifiedTiers.current.has(tier)) continue;
      notifiedTiers.current.add(tier);
      setNotice(`${tier} holding window complete — you can claim your slot.`);
      if (typeof Notification !== "undefined" && Notification.permission === "granted") {
        try {
          new Notification(`${display_name}: ${tier} is ready to claim`, {
            body: "Your holding window is complete — claim your slot before the grid fills.",
            tag: `pmb-ready-${contract}-${tier}`,
          });
        } catch {
          /* constructor unsupported (e.g. Android Chrome without a SW) */
        }
      }
    }
  });

  // Chain-sync fallback: if the receipt hasn't arrived after a grace period,
  // the hash may be a phantom (smart-account wallets submit a different wrapped
  // tx). Ask the backend to scan the season's Claimed logs directly — the win
  // is recorded from the chain and the lane flips without user action.
  useEffect(() => {
    if (!pending || mined || !wallet) return;
    const claim = pending;
    const startedAt = claim.startedAt ?? 0; // restored pendings sync immediately
    let cancelled = false;

    const id = setInterval(async () => {
      if (Date.now() - startedAt < 30_000) return; // give the receipt a fair chance
      try {
        const body = await apiPost<{ won: boolean; slot_number?: number }>("/claim/sync", {
          contract_address: contract,
          tier: claim.tier,
          wallet_address: wallet,
        });
        if (cancelled) return;
        if (body.won) {
          setNotice(
            `Slot ${body.slot_number ? `P${body.slot_number} ` : ""}secured in ${claim.tier} — recovered from the chain.`,
          );
          setPending(null);
          setBusyTier(null);
          load(wallet);
        }
      } catch {
        /* transient — next tick retries */
      }
    }, 12_000);

    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [pending, mined, wallet, contract, load]);

  // When a claim tx is mined, record it with the backend (which verifies it
  // on-chain). We must NOT show success unless the backend actually confirms —
  // otherwise a wallet is a winner on-chain but invisible in the DB. The RPC can
  // lag, so a retryable 409 / 503 is retried before giving up.
  useEffect(() => {
    if (!mined || !pending || !wallet) return;
    const claim = pending; // stable non-null capture for the nested closures
    let cancelled = false;
    confirmAttempt.current = 0;

    const settle = () => {
      setPending(null);
      setBusyTier(null);
      load(wallet);
    };
    const retry = () => {
      confirmAttempt.current += 1;
      setNotice(`Claim landed on-chain — syncing… (${confirmAttempt.current}/${CONFIRM_MAX_RETRIES})`);
      setTimeout(() => {
        if (!cancelled) doConfirm();
      }, CONFIRM_RETRY_MS);
    };

    async function doConfirm() {
      try {
        const res = await fetch(`${API_URL}/claim/confirm`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            contract_address: contract,
            tier: claim.tier,
            wallet_address: wallet,
            tx_hash: claim.hash,
          }),
        });
        if (cancelled) return;

        if (res.ok) {
          setNotice(`Slot claimed in ${claim.tier} — you're on the board.`);
          settle();
          return;
        }
        // 404 = window already consumed (a prior confirm succeeded, e.g. before a
        // reload). Treat as done rather than erroring.
        if (res.status === 404) {
          settle();
          return;
        }

        const body = await res.json().catch(() => null);
        const detail = body?.detail;
        const retryable =
          (res.status === 409 && detail && typeof detail === "object" && detail.retryable) ||
          res.status === 503;
        if (retryable && confirmAttempt.current < CONFIRM_MAX_RETRIES) {
          retry();
          return;
        }

        // Non-retryable (e.g. 400 the tx didn't verify) or retries exhausted.
        const msg =
          typeof detail === "string" ? detail : detail?.message ?? `Recording failed (${res.status}).`;
        setError(`${msg} Your tx is on-chain — it should sync on refresh; contact support if it persists.`);
        settle();
      } catch {
        if (cancelled) return;
        if (confirmAttempt.current < CONFIRM_MAX_RETRIES) {
          retry();
          return;
        }
        setNotice("Claim landed on-chain, but recording it failed — refresh to sync.");
        settle();
      }
    }

    doConfirm();
    return () => {
      cancelled = true;
    };
  }, [mined, pending, contract, wallet, load]);

  async function claimSlot(tier: string) {
    if (!wallet) return;
    setBusyTier(tier);
    setError(null);
    setNotice(null);
    try {
      const res = await fetch(`${API_URL}/claim/sign`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ contract_address: contract, tier, wallet_address: wallet }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        const d = body?.detail;
        throw new Error(typeof d === "string" ? d : d?.status ? `Window is ${d.status}, not ready.` : `Sign failed (${res.status})`);
      }
      const att = (await res.json()) as ClaimAttestation;
      if (chainId !== att.chain_id) await switchChainAsync({ chainId: att.chain_id });
      const hash = await writeContractAsync({
        abi: SET_CLAIM_MANAGER_ABI,
        address: att.manager_address,
        functionName: "claim",
        args: claimArgs(att),
        chainId: att.chain_id,
      });
      setPending({ tier, hash, chainId: att.chain_id, startedAt: Date.now() });
      // busyTier stays set until the receipt effect (or the chain-sync
      // fallback) clears it.
    } catch (e) {
      setError(humanizeError(e));
      setBusyTier(null);
    }
  }

  const [confirmTier, setConfirmTier] = useState<string | null>(null);

  const grid = useMemo(() => lanes ?? [], [lanes]);

  return (
    <main className={`race-control ${display.variable} ${mono.variable}`}>
      <div className="rc-grain" aria-hidden />
      <div className="rc-flag" aria-hidden />

      <header className="rc-header">
        <div className="rc-id">
          <span className="rc-kicker">RACE CONTROL // {display_name}</span>
          <h1 className="rc-title">The&nbsp;Grid</h1>
        </div>
        <div className={`rc-driver ${isConnected ? "is-live" : ""}`}>
          <span className="rc-driver-dot" />
          {isConnected && wallet ? shortAddr(wallet) : "NO DRIVER"}
        </div>
      </header>

      {!isConnected && (
        <section className="rc-connectbar">
          <p className="rc-hint">Connect a wallet to see your grid position and race.</p>
          <ConnectButton accountStatus="address" chainStatus="icon" showBalance={false} />
        </section>
      )}
      {error && <p className="rc-alert">⨯ {error}</p>}
      {notice && <p className="rc-notice">✓ {notice}</p>}
      {pending && (
        <div className="rc-notice" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span>
            Claim transaction pending ({pending.hash.slice(0, 10)}…) — smart-account wallets can take
            a minute; the chain is checked automatically.
          </span>
          <button
            style={{ background: "none", border: "none", color: "#ffd23f", cursor: "pointer", textDecoration: "underline", fontSize: "0.85rem" }}
            onClick={() => {
              setPending(null);
              setBusyTier(null);
              if (pendingKey) localStorage.removeItem(pendingKey);
            }}
          >
            Clear stuck status
          </button>
        </div>
      )}

      {grid.length > 0 && (
        <section className="rc-tower">
          {grid.map((lane, i) => (
            <Lane
              key={lane.elig.tier}
              contract={contract}
              chain={chain}
              lane={lane}
              index={i}
              nowMs={Date.now()}
              loadedAt={loadedAt.current}
              busy={busyTier === lane.elig.tier || pending?.tier === lane.elig.tier}
              pendingHash={pending?.tier === lane.elig.tier ? pending.hash : null}
              pendingChain={pending?.tier === lane.elig.tier ? pending.chainId : null}
              connected={isConnected}
              myWallet={wallet}
              onClaim={() => setConfirmTier(lane.elig.tier)}
            />
          ))}
        </section>
      )}

      {isConnected && !loading && grid.length === 0 && !error && (
        <section className="rc-empty">
          <p>No tiers found. This collection needs a generated atlas before the race can run.</p>
        </section>
      )}

      {confirmTier !== null && (
        <ClaimConfirmModal
          tier={confirmTier}
          collectionName={display_name}
          chain={chain}
          onConfirm={async () => {
            try {
              await claimSlot(confirmTier);
            } finally {
              setConfirmTier(null);
            }
          }}
          onCancel={() => setConfirmTier(null)}
          loading={busyTier === confirmTier}
        />
      )}
    </main>
  );
}

function Lane({
  contract,
  chain,
  lane,
  index,
  nowMs,
  loadedAt,
  busy,
  pendingHash,
  pendingChain,
  connected,
  myWallet,
  onClaim,
}: {
  contract: string;
  chain?: string;
  lane: Lane;
  index: number;
  nowMs: number;
  loadedAt: number;
  busy: boolean;
  pendingHash: `0x${string}` | null;
  pendingChain: number | null;
  connected: boolean;
  myWallet?: string;
  onClaim: () => void;
}) {
  const { elig, ws, lb } = lane;
  const accent = TIER_ACCENT[elig.tier] ?? "#8b93a0";
  const full = lb.slots_remaining <= 0;

  // Slots this wallet already secured in the tier (from the winners board).
  const myWins = myWallet
    ? lb.winners.filter((w) => w.wallet_address?.toLowerCase() === myWallet.toLowerCase())
    : [];
  const winLabel = myWins.map((w) => (w.slot_number != null ? `P${w.slot_number}` : "—")).join(", ");

  // Live countdown: seconds_remaining captured at load, minus elapsed since.
  const elapsed = Math.floor((nowMs - loadedAt) / 1000);
  const liveRemaining = ws.seconds_remaining != null ? Math.max(0, ws.seconds_remaining - elapsed) : null;

  // Effective state (server status, overlaid with local countdown + grid-full).
  // Qualification implies a running window — the clock started at the wallet's
  // X-th qualifying acquisition, so lanes are only ever GO / ON TRACK / locked.
  // A won slot consumes its set, so after a win eligibility drops until the
  // wallet assembles a fresh set — lead with FINISHED, not NOT ELIGIBLE.
  let state: string = ws.status;
  if (state === "racing" && liveRemaining === 0) state = "ready";
  if (!elig.qualifies && state !== "won") state = "locked";
  if (full && state !== "won") state = "full";
  if (myWins.length > 0 && (state === "locked" || state === "full" || state === "not_started")) state = "won";

  const txUrl = pendingChain && pendingHash ? explorerTxUrl(pendingChain, pendingHash) : null;

  return (
    <article className={`rc-lane is-${state}`} style={{ "--accent": accent, "--i": index } as React.CSSProperties}>
      <div className="rc-lane-pos">
        <span className="rc-pos-num">{String(index + 1).padStart(2, "0")}</span>
      </div>

      <div className="rc-lane-main">
        <div className="rc-lane-head">
          <div className="rc-lane-name">
            <span className="rc-tier">{elig.tier}</span>
            <span className="rc-arch">{elig.archetype.replace(/_/g, " ")}</span>
          </div>
          <span className={`rc-state is-${state}`}>{STATE_LABEL[state] ?? state.toUpperCase()}</span>
          {myWins.length > 0 && state !== "won" && (
            <span className="rc-state is-won">{winLabel} SECURED</span>
          )}
        </div>

        <div className="rc-lane-grid">
          {/* Holdings meter */}
          <div className="rc-meter-block">
            <div className="rc-meter-top">
              <span className="rc-meter-label">
                SET PROGRESS
                <InfoTip
                  text={`Hold ${elig.count_required} NFT${elig.count_required === 1 ? "" : "s"} carrying any qualifying trait for this tier. Tokens are reusable across tiers — the same NFT can count toward several sets at once — but each token can only back ONE winning claim per tier: a claimed set is spent, and another slot needs a fresh set.`}
                />
              </span>
              <span className="rc-meter-count">
                {elig.held_count}
                <span className="rc-meter-req">/{elig.count_required}</span>
              </span>
            </div>
            <div className="rc-meter">
              <div className="rc-meter-fill" style={{ width: `${Math.min(100, elig.progress_pct)}%` }} />
            </div>
            {elig.qualifying_token_ids.length > 0 && (
              <div className="rc-chips">
                {elig.qualifying_token_ids.slice(0, 10).map((id) => (
                  <span key={id} className="rc-chip">
                    #{id}
                  </span>
                ))}
                {elig.qualifying_token_ids.length > 10 && (
                  <span className="rc-chip rc-chip--more">+{elig.qualifying_token_ids.length - 10}</span>
                )}
              </div>
            )}
            {!elig.qualifies && state !== "won" && (
              <p className="rc-need">Need {elig.needed} more qualifying token{elig.needed === 1 ? "" : "s"}.</p>
            )}
            {state === "won" && !elig.qualifies && !full && elig.needed > 0 && (
              <p className="rc-need">
                Winning set spent — {elig.needed} fresh token{elig.needed === 1 ? "" : "s"} unlocks another slot.
              </p>
            )}
            {!elig.qualifies && elig.needed > 0 && myWallet && (state !== "won" || !full) && (
              <ShoppingPanel
                contract={contract}
                wallet={myWallet}
                tier={elig.tier}
                needed={elig.needed}
                chain={chain ?? "eth"}
              />
            )}
          </div>

          {/* Clock / action */}
          <div className="rc-clock-block">
            <div className={`rc-clock is-${state}`}>
              {state === "won" ? (
                <span className="rc-clock-flag">◼ ◻ ◼</span>
              ) : state === "ready" ? (
                <span className="rc-clock-go">GO</span>
              ) : state === "racing" ? (
                <span className="rc-clock-time">{formatClock(liveRemaining ?? 0)}</span>
              ) : (
                <span className="rc-clock-idle">{formatClock(ws.window_seconds)}</span>
              )}
              <span className="rc-clock-cap">
                {state === "racing" ? "TIME REMAINING" : state === "ready" ? "READY TO CLAIM" : state === "won" ? "FINISHED" : "HOLD WINDOW"}
                <InfoTip text="Your clock runs automatically from the moment you assembled the set on-chain — long holders are ready immediately. Keep the set together: selling below the required count restarts the clock from your rebuy. When it hits zero you can claim a slot." />
              </span>
            </div>

            <div className="rc-action">
              {state === "won" ? (
                <span className="rc-won-badge">
                  ● Slot{myWins.length > 1 ? "s" : ""} {winLabel} secured
                </span>
              ) : state === "full" ? (
                <button className="rc-btn" disabled>
                  GRID FULL
                </button>
              ) : state === "ready" ? (
                <button className="rc-btn rc-btn--go" onClick={onClaim} disabled={!connected || busy}>
                  {busy ? "CLAIMING…" : "CLAIM SLOT ▸"}
                </button>
              ) : state === "racing" ? (
                <button className="rc-btn" disabled>
                  ON TRACK
                </button>
              ) : (
                <button className="rc-btn" disabled>
                  NOT ELIGIBLE
                </button>
              )}
              {txUrl && (
                <a className="rc-tx" href={txUrl} target="_blank" rel="noopener noreferrer">
                  pending tx ↗
                </a>
              )}
            </div>
          </div>
        </div>

        {/* Standings */}
        <div className="rc-standings">
          <div className="rc-standings-head">
            <span className="rc-standings-label">// grid</span>
            <span className="rc-slots">
              <b>{lb.slots_filled}</b> / {lb.cap} slots · {lb.slots_remaining} open · {lb.total_racers ?? lb.racers.length} racing
            </span>
          </div>
          {lb.winners.length > 0 ? (
            <ol className="rc-podium">
              {lb.winners.slice(0, 5).map((w, wi) => {
                const isMe = myWallet && w.wallet_address.toLowerCase() === myWallet;
                return (
                  <li key={`${w.wallet_address}-${w.slot_number ?? wi}`} className={isMe ? "is-me" : ""}>
                    <span className="rc-podium-pos">P{w.slot_number ?? wi + 1}</span>
                    <span className="rc-podium-addr">
                      {shortAddr(w.wallet_address)}
                      {isMe ? " (you)" : ""}
                    </span>
                    {explorerTxUrl(CLAIM_CHAIN, w.tx_hash) ? (
                      <a className="rc-podium-tx" href={explorerTxUrl(CLAIM_CHAIN, w.tx_hash)!} target="_blank" rel="noopener noreferrer">
                        ↗
                      </a>
                    ) : null}
                  </li>
                );
              })}
            </ol>
          ) : (
            <p className="rc-podium-empty">No finishers yet — grid is open.</p>
          )}
        </div>
      </div>
    </article>
  );
}
