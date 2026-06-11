"use client";

import { useCallback, useState } from "react";
import { ConnectButton } from "@rainbow-me/rainbowkit";
import { useAccount } from "wagmi";
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

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const _ADDRESS_RE = /^0x[a-fA-F0-9]{40}$/;

type TraitRanking = {
  rank: number;
  trait_category: string;
  trait_value: string;
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
};

function traitKey(t: { trait_category: string; trait_value: string }): string {
  return `${t.trait_category}::${t.trait_value}`;
}

const BAND_DEFS = [
  { key: "legendary", label: "Legendary", cumPct: 0.01 },
  { key: "super_rare", label: "Super Rare", cumPct: 0.10 },
  { key: "rare", label: "Rare", cumPct: 0.30 },
  { key: "common", label: "Common", cumPct: 1.0 },
] as const;

type Band = { key: string; label: string; start: number; items: TraitRanking[] };

/** Slice the (rank-ordered) trait list into rarity bands by cumulative percentile of count. */
function computeBands(traits: TraitRanking[]): Band[] {
  const n = traits.length;
  const bands: Band[] = [];
  let prev = 0;
  for (const def of BAND_DEFS) {
    const end = def.key === "common" ? n : Math.min(n, Math.max(prev, Math.ceil(n * def.cumPct)));
    if (end > prev) {
      bands.push({ key: def.key, label: def.label, start: prev, items: traits.slice(prev, end) });
    }
    prev = end;
  }
  return bands;
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

  return (
    <div ref={setNodeRef} style={style} className="trait-row">
      <span className="trait-handle" {...attributes} {...listeners} aria-label="Drag to reorder">
        ⠿
      </span>
      <span className="trait-rank muted">#{trait.rank}</span>
      <span className="trait-name">
        {trait.trait_category}: <strong>{trait.trait_value}</strong>
      </span>
      <span className="muted trait-score">{trait.combined_score.toFixed(4)}</span>
      <label className="trait-pin">
        <input type="checkbox" checked={trait.pinned} onChange={() => onTogglePin(key)} />
        Pin
      </label>
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
        <div className="trait-list">
          {traits.map((t) => (
            <SortableTraitRow key={traitKey(t)} trait={t} onTogglePin={onTogglePin} />
          ))}
        </div>
      </SortableContext>
    </DndContext>
  );
}

export default function ApprovePage() {
  const { address, isConnected } = useAccount();

  const [contractInput, setContractInput] = useState("");
  const [contract, setContract] = useState<string | null>(null);
  const [manifest, setManifest] = useState<Manifest | null>(null);
  const [traits, setTraits] = useState<TraitRanking[]>([]);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ApproveResult | null>(null);
  const [viewMode, setViewMode] = useState<"bands" | "list">("bands");
  const [expandedBands, setExpandedBands] = useState<Set<string>>(new Set());

  const loadRanking = useCallback(async (addr: string) => {
    setLoading(true);
    setError(null);
    setResult(null);
    setManifest(null);
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
      setContract(addr);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load ranking");
    } finally {
      setLoading(false);
    }
  }, []);

  function handleLoadSubmit(e: React.FormEvent) {
    e.preventDefault();
    const addr = contractInput.trim().toLowerCase();
    if (!_ADDRESS_RE.test(addr)) {
      setError("Enter a valid contract address (0x + 40 hex characters).");
      return;
    }
    loadRanking(addr);
  }

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

  function handleBandDragEnd(band: Band, event: DragEndEvent) {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    setTraits((items) => {
      const bandItems = items.slice(band.start, band.start + band.items.length);
      const oldIndex = bandItems.findIndex((t) => traitKey(t) === active.id);
      const newIndex = bandItems.findIndex((t) => traitKey(t) === over.id);
      if (oldIndex === -1 || newIndex === -1) return items;
      const reordered = arrayMove(bandItems, oldIndex, newIndex);
      const next = [...items];
      for (let i = 0; i < reordered.length; i++) next[band.start + i] = reordered[i];
      return next.map((t, i) => ({ ...t, rank: i + 1 }));
    });
  }

  function toggleBand(key: string) {
    setExpandedBands((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  async function submitApproval() {
    if (!contract || !address) return;
    setSubmitting(true);
    setError(null);
    try {
      const res = await fetch(`${API_URL}/audit/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          contract_address: contract,
          approver_address: address,
          trait_rankings: traits.map((t) => ({
            trait_category: t.trait_category,
            trait_value: t.trait_value,
            pinned: t.pinned,
          })),
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
    <main>
      <header>
        <div>
          <h1 style={{ margin: 0, fontSize: "1.35rem" }}>Approve Ranking</h1>
          <p className="muted" style={{ margin: "0.25rem 0 0" }}>
            Reorder and pin traits, then commit the ranking your wallet will lock on-chain.
          </p>
        </div>
        <ConnectButton />
      </header>

      <section className="card">
        <h2>Load a collection</h2>
        <form onSubmit={handleLoadSubmit} style={{ display: "flex", gap: "0.5rem" }}>
          <input
            type="text"
            placeholder="0x… contract address"
            value={contractInput}
            onChange={(e) => setContractInput(e.target.value)}
          />
          <button type="submit" disabled={loading}>
            {loading ? "Loading…" : "Load ranking"}
          </button>
        </form>
        {error && (
          <p style={{ color: "#f87171", marginTop: "0.75rem" }}>{error}</p>
        )}
      </section>

      {manifest && (
        <section className="card">
          <h2>
            Trait rankings — <code>{manifest.collection.contract_address}</code>
          </h2>

          {manifest.approval && !result && (
            <div className="muted" style={{ marginBottom: "1rem" }}>
              <p style={{ margin: "0 0 0.35rem" }}>Already approved:</p>
              <ul style={{ margin: 0, paddingLeft: "1.2rem" }}>
                <li>
                  Approver: <code>{manifest.approval.approver_address}</code>
                </li>
                <li>
                  Approved at: <code>{manifest.approval.approved_at}</code>
                </li>
                <li>
                  Manifest hash: <code>{manifest.approval.manifest_hash}</code>
                </li>
              </ul>
              <p style={{ margin: "0.35rem 0 0" }}>Re-approving will overwrite this with a new hash.</p>
            </div>
          )}

          <div className="view-toggle">
            <button className={viewMode === "bands" ? "active" : ""} onClick={() => setViewMode("bands")}>
              Bands
            </button>
            <button className={viewMode === "list" ? "active" : ""} onClick={() => setViewMode("list")}>
              Full list
            </button>
          </div>

          {viewMode === "bands" ? (
            <div className="band-grid">
              {computeBands(traits).map((band) => {
                const expanded = expandedBands.has(band.key);
                return (
                  <div key={band.key} style={{ gridColumn: expanded ? "1 / -1" : undefined }}>
                    <button className={`band-card${expanded ? " expanded" : ""}`} onClick={() => toggleBand(band.key)}>
                      <div className="band-card-header">
                        <h3>{band.label}</h3>
                        <span className="muted">{band.items.length}</span>
                      </div>
                      <ul className="band-preview">
                        {band.items.slice(0, 5).map((t) => (
                          <li key={traitKey(t)}>
                            {t.trait_category}: {t.trait_value}
                          </li>
                        ))}
                      </ul>
                    </button>
                    {expanded && (
                      <div className="band-section">
                        <TraitDndList
                          traits={band.items}
                          onDragEnd={(e) => handleBandDragEnd(band, e)}
                          onTogglePin={togglePin}
                        />
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          ) : (
            <TraitDndList traits={traits} onDragEnd={handleDragEnd} onTogglePin={togglePin} />
          )}

          <div style={{ marginTop: "1rem", display: "flex", alignItems: "center", gap: "1rem" }}>
            <button onClick={submitApproval} disabled={!isConnected || submitting}>
              {submitting ? "Submitting…" : "Approve ranking"}
            </button>
            {!isConnected && <span className="muted">Connect a wallet to record yourself as approver.</span>}
          </div>

          {result && (
            <div className="card" style={{ marginTop: "1rem", borderColor: "var(--accent)" }}>
              <h2>Approved</h2>
              <ul className="muted" style={{ margin: 0, paddingLeft: "1.2rem" }}>
                <li>
                  Manifest hash: <code>{result.manifest_hash}</code>
                </li>
                <li>
                  Approver: <code>{result.approver_address}</code>
                </li>
                <li>
                  Approved at: <code>{result.approved_at}</code>
                </li>
                <li>{result.trait_count} traits ranked</li>
              </ul>
              <p className="muted" style={{ margin: "0.5rem 0 0" }}>
                This hash will be submitted on-chain via <code>lockManifest</code> together with the atlas
                hash once Set Atlas (Phase 2) is ready.
              </p>
            </div>
          )}
        </section>
      )}
    </main>
  );
}
