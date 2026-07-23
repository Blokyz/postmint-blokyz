"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { JetBrains_Mono } from "next/font/google";
import { useParams } from "next/navigation";
import { LockPanel } from "@/components/LockPanel";

const mono = JetBrains_Mono({ subsets: ["latin"], weight: ["400", "500", "700"], variable: "--font-mono" });

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ── Types ────────────────────────────────────────────────────────────────

type TraitPair = { trait_category: string; trait_value: string };

type SetRule = {
  archetype: "count_of_pool" | "one_of_each" | "apex_combo" | "none";
  pool?: TraitPair[];
  count_required?: number;
  trait_values?: TraitPair[];
};

type Feasibility = {
  pool_qualifying_nfts: number;
  estimated_qualifiers: number;
  max_sets_formable: number | null;
  race_intensity: number | null;
  fit_score: number | null;
};

type TierEntry = {
  tier: string;
  set_rule: SetRule;
  pool: TraitPair[];
  feasibility: Feasibility | null;
  low_feasibility: boolean;
};

type TierConfig = { cap: number; holding_window_hours: number; count_required: number };

type Ladder = {
  tier_a: string;
  tier_b: string;
  shared_pool_size: number;
  x_a: number | null;
  x_b: number | null;
};

type AtlasManifest = {
  atlas_manifest_id: string;
  ranking_manifest_id: string;
  collection: { contract_address: string; chain: string; total_supply: number; eligible_supply: number };
  generated_at: string;
  tier_structure: Record<string, TierConfig>;
  tiers: TierEntry[];
  ladders: Ladder[];
  approval: unknown;
};

// ── Tuning constants (mirror backend DEFAULT_TIER_STRUCTURE) ──────────────

// Mirrors backend DEFAULT_TIER_STRUCTURE incl. the graduated count_required ramp
// (set size escalates with rarity so no tier is a trivial "hold one token").
const DEFAULT_TIER_STRUCTURE: Record<string, TierConfig> = {
  Common: { cap: 1000, holding_window_hours: 0, count_required: 1 },
  Uncommon: { cap: 750, holding_window_hours: 24, count_required: 2 },
  Rare: { cap: 500, holding_window_hours: 72, count_required: 2 },
  "Super Rare": { cap: 250, holding_window_hours: 168, count_required: 3 },
  Mythic: { cap: 50, holding_window_hours: 336, count_required: 3 },
};

// Set-size slider bounds (tokens a wallet must hold from the band).
const COUNT_MIN = 1;
const COUNT_MAX = 8;

// One accent hue per tier, Common (cold) -> Mythic (hot apex grail).
const TIER_COLOR: Record<string, string> = {
  Common: "#7c8aa3",
  Uncommon: "#4f9bd9",
  Rare: "#2fc7c0",
  "Super Rare": "#8b6df0",
  Mythic: "#ffd23f",
};

const ARCHETYPE_LABEL: Record<SetRule["archetype"], string> = {
  count_of_pool: "Pool count",
  one_of_each: "One of each",
  apex_combo: "Apex combo",
  none: "Empty band",
};

// Healthy fit band (mirrors backend _FIT_RANGE / _FIT_TARGET).
const FIT_MIN = 2;
const FIT_MAX = 5;
const FIT_DISPLAY_MAX = 6;

function capRange(tier: string): [number, number] {
  const d = DEFAULT_TIER_STRUCTURE[tier].cap;
  return [Math.max(1, Math.round(d * 0.25)), d * 4];
}

function windowRange(tier: string): [number, number] {
  const d = DEFAULT_TIER_STRUCTURE[tier].holding_window_hours;
  return [0, Math.max(d * 2, 168)];
}

function ruleSummary(t: TierEntry): string {
  const { set_rule, pool } = t;
  if (set_rule.archetype === "none") return "No traits fall in this rarity band.";
  if (set_rule.archetype === "one_of_each") {
    return `Hold ≥1 token for each of ${set_rule.trait_values?.length ?? 0} specific traits.`;
  }
  return `Hold ≥${set_rule.count_required} token(s) bearing any trait from a pool of ${pool.length}.`;
}

function fmtInt(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString();
}

// ── Small components ──────────────────────────────────────────────────────

function FitGauge({ fitScore, color }: { fitScore: number | null; color: string }) {
  if (fitScore === null) {
    return (
      <div className="atlas-gauge">
        <div className="atlas-gauge-track">
          <div className="atlas-gauge-target" style={{ left: `${(FIT_MIN / FIT_DISPLAY_MAX) * 100}%`, width: `${((FIT_MAX - FIT_MIN) / FIT_DISPLAY_MAX) * 100}%` }} />
        </div>
        <div className="atlas-gauge-scale">
          <span>0</span>
          <span className="atlas-gauge-sweetspot">2–5</span>
          <span>6+</span>
        </div>
      </div>
    );
  }
  const clamped = Math.min(fitScore, FIT_DISPLAY_MAX);
  const pct = (clamped / FIT_DISPLAY_MAX) * 100;
  return (
    <div className="atlas-gauge">
      <div className="atlas-gauge-track">
        <div
          className="atlas-gauge-target"
          style={{ left: `${(FIT_MIN / FIT_DISPLAY_MAX) * 100}%`, width: `${((FIT_MAX - FIT_MIN) / FIT_DISPLAY_MAX) * 100}%` }}
        />
        <div className="atlas-gauge-marker" style={{ left: `${pct}%`, background: color }} />
      </div>
      <div className="atlas-gauge-scale">
        <span>0</span>
        <span className="atlas-gauge-sweetspot">2–5</span>
        <span>6+</span>
      </div>
    </div>
  );
}

function TierCard({
  tier,
  override,
  onChangeCap,
  onChangeWindow,
  onChangeCount,
  onReset,
}: {
  tier: TierEntry;
  override: TierConfig;
  onChangeCap: (v: number) => void;
  onChangeWindow: (v: number) => void;
  onChangeCount: (v: number) => void;
  onReset: () => void;
}) {
  const color = TIER_COLOR[tier.tier] ?? "#7c8aa3";
  const [capMin, capMax] = capRange(tier.tier);
  const [winMin, winMax] = windowRange(tier.tier);
  const feas = tier.feasibility;
  const defaults = DEFAULT_TIER_STRUCTURE[tier.tier];
  const isDefault =
    override.cap === defaults.cap &&
    override.holding_window_hours === defaults.holding_window_hours &&
    override.count_required === defaults.count_required;
  const fit = feas?.fit_score ?? null;
  const healthy = !tier.low_feasibility;

  return (
    <article className="atlas-tier" style={{ "--tier-color": color } as React.CSSProperties}>
      <header className="atlas-tier-head">
        <div className="atlas-tier-name">
          <span className="atlas-dot" />
          <h2>{tier.tier}</h2>
        </div>
        <span className="atlas-archetype">{ARCHETYPE_LABEL[tier.set_rule.archetype]}</span>
      </header>

      <div className="atlas-fit">
        <div className="atlas-fit-readout">
          <span className="atlas-fit-value">{fit === null ? "—" : fit.toFixed(2)}</span>
          <span className="atlas-fit-label">fit score</span>
        </div>
        <span className={`atlas-status ${healthy ? "is-healthy" : "is-low"}`}>
          {healthy ? "Healthy race" : "Low feasibility"}
        </span>
      </div>

      <FitGauge fitScore={fit} color={color} />

      <p className="atlas-rule">{ruleSummary(tier)}</p>

      {tier.set_rule.archetype === "one_of_each" && tier.set_rule.trait_values && (
        <div className="atlas-chips">
          {tier.set_rule.trait_values.map((tv) => (
            <span key={`${tv.trait_category}::${tv.trait_value}`} className="atlas-chip" title={tv.trait_category}>
              {tv.trait_value}
            </span>
          ))}
        </div>
      )}

      {feas && (
        <dl className="atlas-stats">
          <div>
            <dt>Qualifiers</dt>
            <dd>{fmtInt(feas.estimated_qualifiers)}</dd>
          </div>
          <div>
            <dt>Slots (cap)</dt>
            <dd>{fmtInt(override.cap)}</dd>
          </div>
          <div>
            <dt>Pool NFTs</dt>
            <dd>{fmtInt(feas.pool_qualifying_nfts)}</dd>
          </div>
          <div>
            <dt>Max sets</dt>
            <dd>{fmtInt(feas.max_sets_formable)}</dd>
          </div>
        </dl>
      )}

      <div className="atlas-controls">
        <label className="atlas-control">
          <span className="atlas-control-label">
            Set size <b>hold {override.count_required} token{override.count_required === 1 ? "" : "s"}</b>
          </span>
          <input
            type="range"
            className="atlas-slider"
            min={COUNT_MIN}
            max={COUNT_MAX}
            step={1}
            value={override.count_required}
            onChange={(e) => onChangeCount(Number(e.target.value))}
          />
        </label>
        <label className="atlas-control">
          <span className="atlas-control-label">
            Cap <b>{override.cap.toLocaleString()}</b>
          </span>
          <input
            type="range"
            className="atlas-slider"
            min={capMin}
            max={capMax}
            step={1}
            value={override.cap}
            onChange={(e) => onChangeCap(Number(e.target.value))}
          />
        </label>
        <label className="atlas-control">
          <span className="atlas-control-label">
            Holding window <b>{override.holding_window_hours}h</b>
          </span>
          <input
            type="range"
            className="atlas-slider"
            min={winMin}
            max={winMax}
            step={1}
            value={override.holding_window_hours}
            onChange={(e) => onChangeWindow(Number(e.target.value))}
          />
        </label>
        <button type="button" className="atlas-reset" onClick={onReset} disabled={isDefault}>
          Reset to defaults
        </button>
      </div>
    </article>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────

export default function AtlasPage() {
  const params = useParams();
  const contract = String(params.contract ?? "").toLowerCase();

  const [manifest, setManifest] = useState<AtlasManifest | null>(null);
  const [overrides, setOverrides] = useState<Record<string, TierConfig>>({});
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const applyManifest = (data: AtlasManifest) => {
    setManifest(data);
    setOverrides(data.tier_structure);
  };

  // Load an already-generated atlas (GET, no regeneration) so revisiting the
  // step doesn't overwrite a tuned manifest. 404 = not generated yet.
  useEffect(() => {
    let live = true;
    setLoading(true);
    setError(null);
    setManifest(null);
    fetch(`${API_URL}/atlas/preview/${contract}`)
      .then((res) => {
        if (res.status === 404) return null;
        if (!res.ok) throw new Error(`Failed to load atlas (${res.status})`);
        return res.json();
      })
      .then((data) => {
        if (live && data) applyManifest(data as AtlasManifest);
      })
      .catch((e) => live && setError(e instanceof Error ? e.message : "Failed to load atlas"))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [contract]);

  const generate = useCallback(async (addr: string, tierStructure?: Record<string, TierConfig>) => {
    const res = await fetch(`${API_URL}/atlas/generate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        contract_address: addr,
        ...(tierStructure ? { tier_structure: tierStructure } : {}),
      }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => null);
      if (res.status === 404) {
        throw new Error(body?.detail ?? "No completed ingestion found for this contract — run an audit first.");
      }
      if (res.status === 400) {
        throw new Error(body?.detail ?? "Ranking manifest must be approved before generating an atlas.");
      }
      throw new Error(body?.detail ?? `Atlas generation failed (${res.status})`);
    }
    return (await res.json()) as AtlasManifest;
  }, []);

  async function handleGenerate() {
    setGenerating(true);
    setError(null);
    try {
      const data = await generate(contract);
      applyManifest(data);
    } catch (e2) {
      setError(e2 instanceof Error ? e2.message : "Failed to generate atlas");
    } finally {
      setGenerating(false);
    }
  }

  async function handleRegenerate() {
    setRegenerating(true);
    setError(null);
    try {
      const data = await generate(contract, overrides);
      applyManifest(data);
    } catch (e2) {
      setError(e2 instanceof Error ? e2.message : "Failed to regenerate atlas");
    } finally {
      setRegenerating(false);
    }
  }

  function setCap(tier: string, cap: number) {
    setOverrides((prev) => ({ ...prev, [tier]: { ...prev[tier], cap } }));
  }

  function setWindow(tier: string, holding_window_hours: number) {
    setOverrides((prev) => ({ ...prev, [tier]: { ...prev[tier], holding_window_hours } }));
  }

  function setCount(tier: string, count_required: number) {
    setOverrides((prev) => ({ ...prev, [tier]: { ...prev[tier], count_required } }));
  }

  function resetTier(tier: string) {
    setOverrides((prev) => ({ ...prev, [tier]: { ...DEFAULT_TIER_STRUCTURE[tier] } }));
  }

  const dirty =
    manifest !== null &&
    Object.entries(overrides).some(
      ([tier, cfg]) =>
        cfg.cap !== manifest.tier_structure[tier]?.cap ||
        cfg.holding_window_hours !== manifest.tier_structure[tier]?.holding_window_hours ||
        cfg.count_required !== manifest.tier_structure[tier]?.count_required,
    );

  const healthyCount = manifest ? manifest.tiers.filter((t) => !t.low_feasibility).length : 0;

  return (
    <main className={`atlas-main ${mono.variable}`}>
      <header className="atlas-header">
        <div>
          <span className="atlas-kicker">Set Atlas · Rarity console</span>
          <h1 className="atlas-title">Tier Tuning</h1>
        </div>
      </header>

      {loading && <p className="atlas-note">Loading atlas…</p>}

      {!loading && !manifest && (
        <section className="atlas-empty">
          <p className="atlas-note">
            No atlas generated yet. Slice this collection&apos;s approved ranking into rarity tiers to begin
            tuning.
          </p>
          <button type="button" onClick={handleGenerate} disabled={generating} className="atlas-regenerate">
            {generating ? "Generating…" : "Generate atlas"}
          </button>
          {error && (
            <p className="atlas-error">
              {error} <Link href={`/studio/${contract}/approve`}>← Go to Approve</Link>
            </p>
          )}
        </section>
      )}

      {manifest && (
        <>
          {error && <p className="atlas-error">{error}</p>}
          <section className="atlas-summary">
            <div>
              <span>Contract</span>
              <code>{manifest.collection.contract_address.slice(0, 10)}…{manifest.collection.contract_address.slice(-4)}</code>
            </div>
            <div>
              <span>Eligible supply</span>
              <code>{manifest.collection.eligible_supply.toLocaleString()}</code>
            </div>
            <div>
              <span>Healthy tiers</span>
              <code>
                {healthyCount} / {manifest.tiers.length}
              </code>
            </div>
            <div>
              <span>Atlas ID</span>
              <code>{manifest.atlas_manifest_id.slice(0, 8)}</code>
            </div>
          </section>

          {manifest.ladders.length > 0 && (
            <div className="atlas-ladder-banner">
              <strong>Ladder{manifest.ladders.length > 1 ? "s" : ""} detected</strong>
              <ul>
                {manifest.ladders.map((l, i) => (
                  <li key={i}>
                    {l.tier_a} ↔ {l.tier_b}: share {l.shared_pool_size} traits but require {fmtInt(l.x_a)} vs {fmtInt(l.x_b)}.
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="atlas-grid">
            {manifest.tiers.map((tier) => (
              <TierCard
                key={tier.tier}
                tier={tier}
                override={overrides[tier.tier] ?? DEFAULT_TIER_STRUCTURE[tier.tier]}
                onChangeCap={(v) => setCap(tier.tier, v)}
                onChangeWindow={(v) => setWindow(tier.tier, v)}
                onChangeCount={(v) => setCount(tier.tier, v)}
                onReset={() => resetTier(tier.tier)}
              />
            ))}
          </div>

          <div className="atlas-actions">
            <button type="button" onClick={handleRegenerate} disabled={regenerating || !dirty} className="atlas-regenerate">
              {regenerating ? "Regenerating…" : dirty ? "Regenerate with new tiers" : "No changes to apply"}
            </button>
            <Link href={`/studio/${contract}/publish`} className="atlas-publish-link">
              Continue to Publish ▸
            </Link>
          </div>

          <LockPanel contract={contract} dirty={dirty} />
        </>
      )}
    </main>
  );
}
