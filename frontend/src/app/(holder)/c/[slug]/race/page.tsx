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
import { API_URL, shortAddr } from "@/lib/api";
import { useCollection } from "@/lib/collection";
import { explorerTxUrl } from "@/lib/manifestRegistry";
import { ClaimAttestation, SET_CLAIM_MANAGER_ABI, claimArgs } from "@/lib/setClaimManager";

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
  window_started: string | null;
  status: "not_started" | "racing" | "ready" | "won" | "reset";
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
  racers: { wallet_address: string; window_started: number; status: string; seconds_remaining: number | null }[];
};

type Lane = { elig: Eligibility; ws: WindowStatus; lb: Leaderboard };

const STATE_LABEL: Record<string, string> = {
  not_started: "STANDBY",
  racing: "ON TRACK",
  ready: "GO",
  won: "FINISHED",
  reset: "RESET",
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
  const { contract_address, display_name } = useCollection();
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
  // receipt with a hook, then POST /claim/confirm.
  const [pending, setPending] = useState<{ tier: string; hash: `0x${string}`; chainId: number } | null>(null);
  const [busyTier, setBusyTier] = useState<string | null>(null);
  const { isSuccess: mined } = useWaitForTransactionReceipt({ hash: pending?.hash, chainId: pending?.chainId });
  const confirmAttempt = useRef(0);

  // 1s ticker so racing countdowns move without refetching.
  const [, setTick] = useState(0);
  const loadedAt = useRef<number>(0);

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

  async function startWindow(tier: string) {
    if (!wallet) return;
    setBusyTier(tier);
    setError(null);
    try {
      const res = await fetch(`${API_URL}/claim/submit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ contract_address: contract, tier, wallet_address: wallet }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        const d = body?.detail;
        throw new Error(typeof d === "string" ? d : d?.error === "not_qualified" ? "You no longer hold the set." : `Submit failed (${res.status})`);
      }
      await load(wallet);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to start window");
    } finally {
      setBusyTier(null);
    }
  }

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
      setPending({ tier, hash, chainId: att.chain_id });
      // busyTier stays set until the receipt effect clears it.
    } catch (e) {
      setError(humanizeError(e));
      setBusyTier(null);
    }
  }

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

      {grid.length > 0 && (
        <section className="rc-tower">
          {grid.map((lane, i) => (
            <Lane
              key={lane.elig.tier}
              lane={lane}
              index={i}
              nowMs={Date.now()}
              loadedAt={loadedAt.current}
              busy={busyTier === lane.elig.tier || pending?.tier === lane.elig.tier}
              pendingHash={pending?.tier === lane.elig.tier ? pending.hash : null}
              pendingChain={pending?.tier === lane.elig.tier ? pending.chainId : null}
              connected={isConnected}
              myWallet={wallet}
              onStart={() => startWindow(lane.elig.tier)}
              onClaim={() => claimSlot(lane.elig.tier)}
            />
          ))}
        </section>
      )}

      {isConnected && !loading && grid.length === 0 && !error && (
        <section className="rc-empty">
          <p>No tiers found. This collection needs a generated atlas before the race can run.</p>
        </section>
      )}
    </main>
  );
}

function Lane({
  lane,
  index,
  nowMs,
  loadedAt,
  busy,
  pendingHash,
  pendingChain,
  connected,
  myWallet,
  onStart,
  onClaim,
}: {
  lane: Lane;
  index: number;
  nowMs: number;
  loadedAt: number;
  busy: boolean;
  pendingHash: `0x${string}` | null;
  pendingChain: number | null;
  connected: boolean;
  myWallet?: string;
  onStart: () => void;
  onClaim: () => void;
}) {
  const { elig, ws, lb } = lane;
  const accent = TIER_ACCENT[elig.tier] ?? "#8b93a0";
  const full = lb.slots_remaining <= 0;

  // Live countdown: seconds_remaining captured at load, minus elapsed since.
  const elapsed = Math.floor((nowMs - loadedAt) / 1000);
  const liveRemaining = ws.seconds_remaining != null ? Math.max(0, ws.seconds_remaining - elapsed) : null;

  // Effective state (server status, overlaid with local countdown + grid-full).
  let state: string = ws.status;
  if (state === "racing" && liveRemaining === 0) state = "ready";
  if (!elig.qualifies && state !== "won") state = ws.status === "reset" ? "reset" : "locked";
  if (full && state !== "won") state = "full";

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
        </div>

        <div className="rc-lane-grid">
          {/* Holdings meter */}
          <div className="rc-meter-block">
            <div className="rc-meter-top">
              <span className="rc-meter-label">SET PROGRESS</span>
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
              </span>
            </div>

            <div className="rc-action">
              {state === "won" ? (
                <span className="rc-won-badge">● Slot secured</span>
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
              ) : elig.qualifies ? (
                <button className="rc-btn rc-btn--start" onClick={onStart} disabled={!connected || busy}>
                  {busy ? "STARTING…" : state === "reset" ? "RESTART CLOCK ▸" : "START CLOCK ▸"}
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
              <b>{lb.slots_filled}</b> / {lb.cap} slots · {lb.slots_remaining} open · {lb.racers.length} racing
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
