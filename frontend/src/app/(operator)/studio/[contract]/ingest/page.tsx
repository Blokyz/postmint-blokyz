"use client";

import Link from "next/link";
import { Chakra_Petch, JetBrains_Mono } from "next/font/google";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { shortAddr } from "@/lib/api";

const hud = Chakra_Petch({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-hud",
});
const mono = JetBrains_Mono({ subsets: ["latin"], weight: ["400", "500", "700"], variable: "--font-mono" });

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const POLL_MS = 2000;

type Status = {
  contract_address: string;
  job_id: string | null;
  status: string | null;
  phase: string | null;
  progress_pct: number | null;
  error_message: string | null;
};

// Ordered pipeline stages. `base` is where the reactor sits when this phase
// begins; fetching_nfts is special-cased to track the real progress_pct (NFT
// paging is the only phase the backend reports a fine-grained percent for). The
// later phases run with progress_pct pinned at 99, so we step the gauge forward
// by phase instead — this is why the "scoring" hold reads as a real stage, not a
// freeze.
const PHASES = [
  { key: "queued", label: "Queued", code: "QUEUED", base: 3 },
  { key: "fetching_nfts", label: "Fetching NFTs & traits", code: "TOKENS", base: 8 },
  { key: "fetching_sales", label: "Fetching sales history", code: "SALES", base: 74 },
  { key: "scoring", label: "Scoring rarity & market premium", code: "SCORING", base: 88 },
  { key: "done", label: "Complete", code: "DONE", base: 100 },
] as const;

const CHAINS = [
  { id: "eth", label: "ETH" },
  { id: "base", label: "BASE" },
  { id: "polygon", label: "POLY" },
  { id: "arbitrum", label: "ARB" },
] as const;

function phaseIndex(phase: string | null): number {
  const i = PHASES.findIndex((p) => p.key === phase);
  return i === -1 ? 0 : i;
}

// Always-forward display percent. During NFT paging we map progress_pct (0–99)
// into the [8, 70] slice; afterwards the phase's own base drives the gauge.
function displayPct(s: Status | null): number {
  if (!s || !s.status) return 0;
  if (s.status === "complete") return 100;
  if (s.phase === "fetching_nfts") {
    const p = s.progress_pct ?? 0;
    return Math.round(8 + (Math.min(p, 99) / 99) * 62);
  }
  return PHASES[phaseIndex(s.phase)]?.base ?? 5;
}

function isActive(status: string | null | undefined): boolean {
  return status === "pending" || status === "running";
}

function TelemetryRow({ label, value, tone }: { label: string; value: string; tone?: "ok" | "warn" | "live" }) {
  return (
    <div className="tlm-row">
      <span className="tlm-label">{label}</span>
      <span className="tlm-fill" />
      <span className={`tlm-value${tone ? ` is-${tone}` : ""}`}>{value}</span>
    </div>
  );
}

export default function IngestPage() {
  const params = useParams();
  const contract = String(params.contract ?? "").toLowerCase();

  const [chain, setChain] = useState("eth");
  const [status, setStatus] = useState<Status | null>(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearTimeout(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const poll = useCallback(async (addr: string) => {
    try {
      const res = await fetch(`${API_URL}/audit/status/${addr}`);
      if (res.status === 404) {
        setStatus(null);
        return;
      }
      if (!res.ok) throw new Error(`Status check failed (${res.status})`);
      const data: Status = await res.json();
      setStatus(data);
      if (isActive(data.status)) {
        pollRef.current = setTimeout(() => poll(addr), POLL_MS);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Status check failed");
    }
  }, []);

  // Load any existing job state for this contract on mount, and keep polling if
  // it's live. Clean up any in-flight poll on unmount.
  useEffect(() => {
    poll(contract);
    return stopPolling;
  }, [contract, poll, stopPolling]);

  async function startIngestion() {
    stopPolling();
    setError(null);
    setStarting(true);
    try {
      const res = await fetch(`${API_URL}/audit/ingest`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ contract_address: contract, chain }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail ?? `Failed to start ingestion (${res.status})`);
      }
      poll(contract);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to start ingestion");
    } finally {
      setStarting(false);
    }
  }

  const active = isActive(status?.status);
  const complete = status?.status === "complete";
  const failed = status?.status === "failed";
  const pct = displayPct(status);
  const currentPhase = phaseIndex(status?.phase ?? null);

  const statusChip = failed
    ? { code: "FAULT", tone: "fault" }
    : complete
      ? { code: "COMPLETE", tone: "done" }
      : active
        ? { code: "LIVE", tone: "live" }
        : { code: "IDLE", tone: "idle" };

  const reactorState = failed ? "is-fault" : complete ? "is-done" : active ? "is-live" : "is-idle";

  return (
    <main className={`ingest-console ${hud.variable} ${mono.variable}`}>
      <div className="ingest-grain" aria-hidden />

      <header className="ic-header">
        <div className="ic-id">
          <span className="ic-kicker">INGEST.SYS // {shortAddr(contract)}</span>
          <h1 className="ic-title">Acquire&nbsp;Target</h1>
        </div>
        <div className={`ic-chip is-${statusChip.tone}`}>
          <span className="ic-chip-dot" />
          {statusChip.code}
        </div>
      </header>

      <section className="ic-panel ic-acquire">
        <div className="ic-panel-label">// target acquisition</div>
        <div className="ic-form">
          <div className="ic-input-wrap">
            <span className="ic-input-prefix">CONTRACT</span>
            <span className="ic-input ic-input-static">{contract}</span>
          </div>
          <div className="ic-chainset" role="group" aria-label="Source chain">
            {CHAINS.map((c) => (
              <button
                type="button"
                key={c.id}
                className={`ic-chain${chain === c.id ? " is-on" : ""}`}
                onClick={() => setChain(c.id)}
                disabled={active}
              >
                {c.label}
              </button>
            ))}
          </div>
          <button type="button" onClick={startIngestion} className="ic-initiate" disabled={starting || active}>
            <span>{starting ? "ARMING…" : active ? "RUNNING" : complete ? "RE-RUN" : "INITIATE"}</span>
            <span className="ic-initiate-arrow">▸</span>
          </button>
        </div>
        <p className="ic-hint">
          Source chain is where the collection lives — BAYC → ETH. Re-running an active target resumes it
          from the last cursor.
        </p>
        {error && <p className="ic-alert-line">⨯ {error}</p>}
      </section>

      {status && (
        <section className="ic-readout">
          <div
            className={`ic-reactor ${reactorState}`}
            style={{ "--pct": failed ? 100 : pct } as React.CSSProperties}
          >
            <div className="ic-reactor-ticks" aria-hidden />
            <div className="ic-reactor-ring" aria-hidden />
            {active && <div className="ic-reactor-sweep" aria-hidden />}
            <div className="ic-reactor-core">
              <div className="ic-reactor-pct">
                {failed ? "⨯" : complete ? "100" : pct}
                {!failed && <span className="ic-reactor-unit">%</span>}
              </div>
              <div className="ic-reactor-phase">
                {failed ? "FAULT" : complete ? "MANIFEST READY" : PHASES[currentPhase]?.code ?? "—"}
              </div>
            </div>
          </div>

          <div className="ic-readout-right">
            <div className="ic-pipeline">
              {PHASES.filter((p) => p.key !== "done").map((p, i) => {
                const state = failed
                  ? i < currentPhase
                    ? "done"
                    : i === currentPhase
                      ? "fault"
                      : "todo"
                  : complete || i < currentPhase
                    ? "done"
                    : i === currentPhase
                      ? "active"
                      : "todo";
                return (
                  <div key={p.key} className={`ic-stage is-${state}`}>
                    <span className="ic-stage-node">
                      <span className="ic-stage-idx">{String(i + 1).padStart(2, "0")}</span>
                    </span>
                    <span className="ic-stage-label">{p.label}</span>
                  </div>
                );
              })}
            </div>

            <div className="ic-telemetry">
              <div className="ic-panel-label">// telemetry</div>
              <TelemetryRow label="JOB" value={status.job_id ? status.job_id.slice(0, 8) : "—"} />
              <TelemetryRow
                label="PHASE"
                value={(status.phase ?? "—").toUpperCase()}
                tone={active ? "live" : undefined}
              />
              <TelemetryRow label="RAW PROGRESS" value={`${status.progress_pct ?? 0}%`} />
              <TelemetryRow
                label="STATUS"
                value={(status.status ?? "—").toUpperCase()}
                tone={failed ? "warn" : complete ? "ok" : active ? "live" : undefined}
              />
            </div>
          </div>
        </section>
      )}

      {failed && status?.error_message && (
        <section className="ic-panel ic-fault">
          <div className="ic-panel-label">// fault trace</div>
          <p className="ic-fault-msg">{status.error_message}</p>
        </section>
      )}

      {complete && (
        <section className="ic-panel ic-complete">
          <div>
            <div className="ic-panel-label">// manifest ready</div>
            <p className="ic-complete-msg">Rarity manifest written. Ready to review &amp; lock.</p>
          </div>
          <Link href={`/studio/${contract}/approve`} className="ic-cta">
            REVIEW &amp; APPROVE <span className="ic-initiate-arrow">▸</span>
          </Link>
        </section>
      )}
    </main>
  );
}
