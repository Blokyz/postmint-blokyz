"use client";

import Link from "next/link";
import { Chakra_Petch, JetBrains_Mono } from "next/font/google";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useAccount, useSignMessage } from "wagmi";
import {
  DndContext,
  DragEndEvent,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";

const hud = Chakra_Petch({ subsets: ["latin"], weight: ["400", "500", "600", "700"], variable: "--font-hud" });
const mono = JetBrains_Mono({ subsets: ["latin"], weight: ["400", "500", "700"], variable: "--font-mono" });

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type TraitRanking = {
  rank: number;
  trait_category: string;
  trait_value: string;
  stat_norm: number;
  market_norm: number | null;
  combined_score: number;
  pinned: boolean;
};

type Approval = {
  approver_address: string;
  approved_at: string;
  manifest_hash: string;
};

type Manifest = {
  manifest_id: string;
  collection: { contract_address: string; chain: string; total_supply: number };
  trait_rankings: TraitRanking[];
  approval: Approval | null;
};

type ApproveResult = {
  manifest_hash: string;
  approved_at: string;
  approver_address: string;
  trait_count: number;
  w_stat: number;
  w_market: number;
};

function traitKey(t: { trait_category: string; trait_value: string }): string {
  return `${t.trait_category}::${t.trait_value}`;
}

/**
 * Canonical message the approver signs — MUST stay byte-for-byte in lockstep with
 * `build_approval_message` in backend/app/signing.py. The API recovers the signer
 * from this and rejects the approval unless it matches the connected wallet.
 * `JSON.stringify` of an array of [string, string, bool] matches Python's
 * `json.dumps(separators=(",", ":"))`.
 */
function buildApprovalMessage(
  contract: string,
  orderedTraits: { trait_category: string; trait_value: string; pinned: boolean }[],
  wStat: number,
  wMarket: number,
): string {
  const order = orderedTraits.map((t) => [t.trait_category, t.trait_value, t.pinned]);
  // weights use toFixed(2) (NOT JSON numbers): JSON.stringify(1.0)==="1" but the
  // backend formats with %.2f, so fixed 2-dp keeps the signed bytes identical.
  return [
    "PostMint Set Atlas ranking approval",
    `contract:${contract.toLowerCase()}`,
    `weights:${wStat.toFixed(2)},${wMarket.toFixed(2)}`,
    `order:${JSON.stringify(order)}`,
  ].join("\n");
}

function RowContent({
  trait,
  onTogglePin,
  handle,
}: {
  trait: TraitRanking;
  onTogglePin: (key: string) => void;
  handle: React.ReactNode;
}) {
  const score = Math.max(0, Math.min(1, trait.combined_score));
  const key = traitKey(trait);
  return (
    <>
      {handle}
      <span className="al-rank">{String(trait.rank).padStart(2, "0")}</span>
      <div className="al-trait-main">
        <div className="al-trait-name">
          <span className="al-cat">{trait.trait_category}</span>
          <strong>{trait.trait_value}</strong>
        </div>
        <div className="al-bar" aria-hidden>
          <span style={{ width: `${score * 100}%` }} />
        </div>
      </div>
      <span
        className={`al-mkt${trait.market_norm != null ? " is-on" : ""}`}
        title={trait.market_norm != null ? "Has market-premium signal" : "Stat-only (no market signal)"}
      >
        M
      </span>
      <span className="al-score">{trait.combined_score.toFixed(3)}</span>
      <button
        type="button"
        className={`al-pin${trait.pinned ? " is-on" : ""}`}
        onClick={() => onTogglePin(key)}
        aria-pressed={trait.pinned}
      >
        {trait.pinned ? "★ Pinned" : "☆ Pin"}
      </button>
    </>
  );
}

function SortableTraitRow({
  trait,
  onTogglePin,
}: {
  trait: TraitRanking;
  onTogglePin: (key: string) => void;
}) {
  const key = traitKey(trait);
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: key });
  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };
  const handle = (
    <span className="al-handle" {...attributes} {...listeners} aria-label="Drag to reorder">
      ⠿
    </span>
  );
  return (
    <div ref={setNodeRef} style={style} className={`al-row${trait.pinned ? " is-pinned" : ""}`}>
      <RowContent trait={trait} onTogglePin={onTogglePin} handle={handle} />
    </div>
  );
}

function StaticTraitRow({
  trait,
  onTogglePin,
}: {
  trait: TraitRanking;
  onTogglePin: (key: string) => void;
}) {
  const handle = (
    <span className="al-handle is-disabled" aria-hidden title="Clear the filter to reorder">
      ⠿
    </span>
  );
  return (
    <div className={`al-row${trait.pinned ? " is-pinned" : ""}`}>
      <RowContent trait={trait} onTogglePin={onTogglePin} handle={handle} />
    </div>
  );
}

function TraitDndList({
  traits,
  onDragEnd,
  onTogglePin,
}: {
  traits: TraitRanking[];
  onDragEnd: (event: DragEndEvent) => void;
  onTogglePin: (key: string) => void;
}) {
  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  return (
    <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
      <SortableContext items={traits.map(traitKey)} strategy={verticalListSortingStrategy}>
        <div className="al-trait-list">
          {traits.map((t) => (
            <SortableTraitRow key={traitKey(t)} trait={t} onTogglePin={onTogglePin} />
          ))}
        </div>
      </SortableContext>
    </DndContext>
  );
}

function Stat({ label, value, accent }: { label: string; value: React.ReactNode; accent?: boolean }) {
  return (
    <div className={`al-stat${accent ? " is-accent" : ""}`}>
      <span className="al-stat-label">{label}</span>
      <span className="al-stat-value">{value}</span>
    </div>
  );
}

export default function ApprovePage() {
  const params = useParams();
  const contract = String(params.contract ?? "").toLowerCase();
  const { address, isConnected } = useAccount();
  const { signMessageAsync } = useSignMessage();

  const [manifest, setManifest] = useState<Manifest | null>(null);
  const [traits, setTraits] = useState<TraitRanking[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ApproveResult | null>(null);
  const [wStat, setWStat] = useState(0.5);
  const wMarket = Math.round((1 - wStat) * 100) / 100;
  const hasMarket = traits.some((t) => t.market_norm != null);

  // Derived ledger metrics.
  const totalTraits = traits.length;
  const pinnedCount = useMemo(() => traits.filter((t) => t.pinned).length, [traits]);
  const categoryCount = useMemo(() => new Set(traits.map((t) => t.trait_category)).size, [traits]);
  const marketCount = useMemo(() => traits.filter((t) => t.market_norm != null).length, [traits]);

  const q = search.trim().toLowerCase();
  const filtering = q !== "";
  const visible = useMemo(
    () =>
      filtering
        ? traits.filter((t) => `${t.trait_category} ${t.trait_value}`.toLowerCase().includes(q))
        : traits,
    [traits, q, filtering],
  );

  // Re-blend combined_score with the chosen stat/market weights and re-sort.
  // Mirrors the backend blend (stat_norm alone when a trait has no market_norm).
  function applyWeights(ws: number) {
    const wm = Math.round((1 - ws) * 100) / 100;
    setWStat(ws);
    setTraits((items) => {
      const rescored = items.map((t) => ({
        ...t,
        combined_score: t.market_norm != null ? ws * t.stat_norm + wm * t.market_norm : t.stat_norm,
      }));
      rescored.sort((a, b) => b.combined_score - a.combined_score);
      return rescored.map((t, i) => ({ ...t, rank: i + 1 }));
    });
  }

  const loadRanking = useCallback(async (addr: string) => {
    setLoading(true);
    setError(null);
    setResult(null);
    setManifest(null);
    setSearch("");
    try {
      const res = await fetch(`${API_URL}/audit/ranking/${addr}`);
      if (!res.ok) {
        if (res.status === 404) {
          throw new Error("No completed ingestion found for this contract — run an audit first.");
        }
        throw new Error(`Failed to load ranking (${res.status})`);
      }
      const data: Manifest = await res.json();
      setManifest(data);
      setTraits(data.trait_rankings);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load ranking");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadRanking(contract);
  }, [contract, loadRanking]);

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    setTraits((items) => {
      const oldIndex = items.findIndex((t) => traitKey(t) === active.id);
      const newIndex = items.findIndex((t) => traitKey(t) === over.id);
      return arrayMove(items, oldIndex, newIndex).map((t, i) => ({ ...t, rank: i + 1 }));
    });
  }

  function togglePin(key: string) {
    setTraits((items) => items.map((t) => (traitKey(t) === key ? { ...t, pinned: !t.pinned } : t)));
  }

  async function submitApproval() {
    if (!address) return;
    setSubmitting(true);
    setError(null);
    try {
      const trait_rankings = traits.map((t) => ({
        trait_category: t.trait_category,
        trait_value: t.trait_value,
        pinned: t.pinned,
      }));
      // Wallet-sign the exact ranking + weights so the API can verify the
      // approver owns `address` (otherwise approver_address would be forgeable).
      const signature = await signMessageAsync({
        message: buildApprovalMessage(contract, trait_rankings, wStat, wMarket),
      });
      const res = await fetch(`${API_URL}/audit/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          contract_address: contract,
          approver_address: address,
          trait_rankings,
          w_stat: wStat,
          w_market: wMarket,
          signature,
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail ?? `Approval failed (${res.status})`);
      }
      setResult(await res.json());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Approval failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className={`approve-ledger ${hud.variable} ${mono.variable}`}>
      <header className="al-header">
        <span className="al-kicker">Ranking // rarity approval</span>
        <h1 className="al-title">Approve Ranking</h1>
        <p className="al-lede">
          Reorder and pin traits, set the stat-vs-market blend, then wallet-sign the exact ranking your
          collection will lock on-chain.
        </p>
      </header>

      {loading && <p className="al-note">Loading ranking…</p>}
      {error && !manifest && (
        <p className="al-error">
          {error} <Link href={`/studio/${contract}/ingest`}>← Go to Ingest</Link>
        </p>
      )}

      {manifest && (
        <>
          <section className="al-ledger">
            <div className="al-ledger-head">
              <div>
                <span className="al-ledger-label">Collection</span>
                <code className="al-addr">{manifest.collection.contract_address}</code>
              </div>
              <div className={`al-seal-state${manifest.approval ? " is-sealed" : ""}`}>
                {manifest.approval ? "● Approved" : "○ Not approved"}
              </div>
            </div>
            <div className="al-stats">
              <Stat label="Total traits" value={totalTraits} accent />
              <Stat label="Categories" value={categoryCount} />
              <Stat label="Supply" value={manifest.collection.total_supply.toLocaleString()} />
              <Stat label="Pinned" value={pinnedCount} />
              <Stat
                label="Market signal"
                value={hasMarket ? `${marketCount}/${totalTraits}` : "none"}
              />
            </div>
          </section>

          {manifest.approval && !result && (
            <section className="al-prior">
              <span className="al-prior-label">Already approved — re-approving overwrites this hash</span>
              <dl>
                <div>
                  <dt>Approver</dt>
                  <dd>
                    <code>{manifest.approval.approver_address}</code>
                  </dd>
                </div>
                <div>
                  <dt>At</dt>
                  <dd>
                    <code>{manifest.approval.approved_at}</code>
                  </dd>
                </div>
                <div>
                  <dt>Hash</dt>
                  <dd>
                    <code>{manifest.approval.manifest_hash}</code>
                  </dd>
                </div>
              </dl>
              <Link href={`/studio/${contract}/atlas`} className="al-next-link">
                Continue to Set Atlas ▸
              </Link>
            </section>
          )}

          <section className="al-blend">
            <div className="al-blend-head">
              <span className="al-section-label">Score blend</span>
              <span className="al-blend-readout">
                stat <b>{Math.round(wStat * 100)}%</b> · market <b>{Math.round(wMarket * 100)}%</b>
              </span>
            </div>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={wStat}
              disabled={!hasMarket}
              onChange={(e) => applyWeights(Number(e.target.value))}
              className="al-slider"
            />
            {!hasMarket && (
              <p className="al-note">
                No market data for this collection — ranking is stat-only, so the blend has no effect.
              </p>
            )}
          </section>

          <section className="al-traits">
            <div className="al-toolbar">
              <span className="al-section-label">
                Ranking — {totalTraits} {totalTraits === 1 ? "trait" : "traits"}
                {filtering && ` · ${visible.length} shown`}
              </span>
              <input
                type="text"
                className="al-search"
                placeholder="Filter traits…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>

            {filtering && (
              <p className="al-note al-filter-note">
                Filtering — clear the search box to drag-reorder. Pinning still works.
              </p>
            )}

            {visible.length === 0 ? (
              <p className="al-note">No traits match “{search}”.</p>
            ) : filtering ? (
              <div className="al-trait-list">
                {visible.map((t) => (
                  <StaticTraitRow key={traitKey(t)} trait={t} onTogglePin={togglePin} />
                ))}
              </div>
            ) : (
              <TraitDndList traits={traits} onDragEnd={handleDragEnd} onTogglePin={togglePin} />
            )}
          </section>

          <section className="al-commit">
            <button
              className="al-seal-btn"
              onClick={submitApproval}
              disabled={!isConnected || submitting}
            >
              {submitting ? "Sign & approve…" : "Sign & approve ranking"}
            </button>
            {!isConnected && (
              <span className="al-note">Connect a wallet (top-right) to sign as the approver.</span>
            )}
            {error && manifest && <span className="al-error">{error}</span>}
          </section>

          {result && (
            <section className="al-sealed">
              <span className="al-section-label">Approved</span>
              <dl>
                <div>
                  <dt>Hash</dt>
                  <dd>
                    <code>{result.manifest_hash}</code>
                  </dd>
                </div>
                <div>
                  <dt>Approver</dt>
                  <dd>
                    <code>{result.approver_address}</code>
                  </dd>
                </div>
                <div>
                  <dt>At</dt>
                  <dd>
                    <code>{result.approved_at}</code>
                  </dd>
                </div>
                <div>
                  <dt>Traits</dt>
                  <dd>
                    {result.trait_count} · blend stat {Math.round(result.w_stat * 100)}% / market{" "}
                    {Math.round(result.w_market * 100)}%
                  </dd>
                </div>
              </dl>
              <Link href={`/studio/${contract}/atlas`} className="al-next-link">
                Continue to Set Atlas ▸
              </Link>
            </section>
          )}
        </>
      )}
    </main>
  );
}
