"use client";

// Pipeline overview for one contract. Derives each stage's state from whether its
// ARTIFACT exists (ranking manifest → approval → atlas manifest → published
// collection) rather than the latest ingest-job status, because a failed re-ingest
// must not hide manifests produced by an earlier successful run.

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { apiGet, ApiError } from "@/lib/api";
import { CollectionSummary, listAllCollections } from "@/lib/collections";

type Ranking = { approval: { manifest_hash: string; approver_address: string } | null };
type Status = { status: string | null; phase: string | null; progress_pct: number | null };

type StageState = "done" | "active" | "ready" | "locked" | "failed";

type Stage = {
  key: string;
  n: number;
  title: string;
  state: StageState;
  detail: string;
};

const STATE_LABEL: Record<StageState, string> = {
  done: "● Done",
  active: "◍ Running",
  ready: "○ Ready",
  locked: "· Locked",
  failed: "⨯ Failed",
};

async function tryGet<T>(path: string): Promise<T | null> {
  try {
    return await apiGet<T>(path);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return null;
    throw e;
  }
}

export default function PipelineOverview() {
  const params = useParams();
  const contract = String(params.contract ?? "").toLowerCase();

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [ranking, setRanking] = useState<Ranking | null>(null);
  const [status, setStatus] = useState<Status | null>(null);
  const [atlas, setAtlas] = useState<boolean>(false);
  const [collection, setCollection] = useState<CollectionSummary | null>(null);

  useEffect(() => {
    let live = true;
    setLoading(true);
    setError(null);
    Promise.all([
      tryGet<Ranking>(`/audit/ranking/${contract}`),
      tryGet<Status>(`/audit/status/${contract}`),
      tryGet<unknown>(`/atlas/preview/${contract}`),
      listAllCollections().catch(() => [] as CollectionSummary[]),
    ])
      .then(([rk, st, at, cols]) => {
        if (!live) return;
        setRanking(rk);
        setStatus(st);
        setAtlas(at !== null);
        setCollection(cols.find((c) => c.contract_address.toLowerCase() === contract) ?? null);
      })
      .catch((e) => live && setError(e instanceof Error ? e.message : "Failed to load pipeline"))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [contract]);

  const ingested = ranking !== null;
  const approved = ranking?.approval != null;
  const published = collection?.published ?? false;
  const ingestActive = status?.status === "pending" || status?.status === "running";
  const ingestFailed = status?.status === "failed";

  const stages: Stage[] = [
    {
      key: "ingest",
      n: 1,
      title: "Ingest & rarity",
      state: ingested ? "done" : ingestActive ? "active" : ingestFailed ? "failed" : "ready",
      detail: ingested
        ? "Tokens, traits, sales fetched; rarity manifest written."
        : ingestActive
          ? `Running — ${status?.phase ?? "queued"} (${status?.progress_pct ?? 0}%).`
          : ingestFailed
            ? "Last run failed — open Ingest to retry."
            : "Fetch tokens, traits & sales, then score rarity.",
    },
    {
      key: "approve",
      n: 2,
      title: "Approve ranking",
      state: approved ? "done" : ingested ? "ready" : "locked",
      detail: approved
        ? "Ranking wallet-signed and hashed — ready for Atlas."
        : ingested
          ? "Reorder / pin traits, set the blend, wallet-sign."
          : "Complete ingestion first.",
    },
    {
      key: "atlas",
      n: 3,
      title: "Set Atlas",
      state: atlas ? "done" : approved ? "ready" : "locked",
      detail: atlas
        ? "Tiers generated & tuned — ready to publish / lock."
        : approved
          ? "Slice tiers, tune caps & set sizes, lock on-chain."
          : "Approve the ranking first.",
    },
    {
      key: "publish",
      n: 4,
      title: "Publish",
      state: published ? "done" : atlas ? "ready" : "locked",
      detail: published
        ? `Live at /c/${collection?.slug} — holders can race.`
        : atlas
          ? "Give it a name & slug to put the contest live for holders."
          : "Generate the Atlas first.",
    },
  ];

  return (
    <main className="studio">
      <header className="studio-top">
        <div>
          <span className="studio-kicker">Pipeline · {contract.slice(0, 10)}…{contract.slice(-4)}</span>
          <h1 className="studio-h1">
            {collection?.display_name ?? "Collection console"}
          </h1>
        </div>
        {published && collection && (
          <Link href={`/c/${collection.slug}`} className="studio-viewlive">
            View live ▸
          </Link>
        )}
      </header>

      {error && <p className="studio-error">{error}</p>}
      {loading && <p className="studio-note">Reading pipeline state…</p>}

      {!loading && (
        <ol className="studio-pipeline">
          {stages.map((s) => (
            <li key={s.key} className={`studio-stage is-${s.state}`}>
              <div className="studio-stage-n">{s.n}</div>
              <div className="studio-stage-body">
                <div className="studio-stage-head">
                  <h2>{s.title}</h2>
                  <span className={`studio-stage-chip is-${s.state}`}>{STATE_LABEL[s.state]}</span>
                </div>
                <p className="studio-stage-detail">{s.detail}</p>
              </div>
              <div className="studio-stage-cta">
                {s.state === "locked" ? (
                  <span className="studio-stage-lock">Locked</span>
                ) : (
                  <Link href={`/studio/${contract}/${s.key}`} className="studio-stage-btn">
                    {s.state === "done" ? "Review" : "Open"} ▸
                  </Link>
                )}
              </div>
            </li>
          ))}
        </ol>
      )}
    </main>
  );
}
