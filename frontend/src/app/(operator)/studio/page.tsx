"use client";

// Operator console home. The ONE place a contract address is typed — everything
// downstream (`/studio/{contract}/…`) reads it from the route. Also lists the
// collections already in the registry so an operator can jump back into a pipeline.

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ConnectButton } from "@rainbow-me/rainbowkit";
import { ADDRESS_RE, shortAddr } from "@/lib/api";
import { CollectionSummary, listAllCollections } from "@/lib/collections";

export default function StudioHome() {
  const router = useRouter();
  const [input, setInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [collections, setCollections] = useState<CollectionSummary[] | null>(null);

  useEffect(() => {
    let live = true;
    listAllCollections()
      .then((c) => live && setCollections(c))
      .catch(() => live && setCollections([]));
    return () => {
      live = false;
    };
  }, []);

  function open(e: React.FormEvent) {
    e.preventDefault();
    const addr = input.trim().toLowerCase();
    if (!ADDRESS_RE.test(addr)) {
      setError("Enter a valid contract address (0x + 40 hex characters).");
      return;
    }
    router.push(`/studio/${addr}`);
  }

  return (
    <main className="studio">
      <header className="studio-top">
        <div>
          <span className="studio-kicker">PostMint // operator console</span>
          <h1 className="studio-h1">Studio</h1>
        </div>
        <ConnectButton accountStatus="address" chainStatus="icon" showBalance={false} />
      </header>

      <section className="studio-enter">
        <p className="studio-lede">
          Run a collection through the pipeline — ingest &amp; rarity, ranking approval, Set Atlas tuning,
          then publish it live. Enter the collection&apos;s contract to begin.
        </p>
        <form onSubmit={open} className="studio-enterbar">
          <input
            type="text"
            spellCheck={false}
            autoComplete="off"
            placeholder="0x… collection contract address"
            value={input}
            onChange={(e) => {
              setInput(e.target.value);
              setError(null);
            }}
          />
          <button type="submit">Open console ▸</button>
        </form>
        {error && <p className="studio-error">{error}</p>}
      </section>

      <section className="studio-recent">
        <div className="studio-section-label">// your collections</div>
        {collections === null && <p className="studio-note">Loading…</p>}
        {collections && collections.length === 0 && (
          <p className="studio-note">
            No collections yet. Enter a contract above to run the first one through the pipeline.
          </p>
        )}
        {collections && collections.length > 0 && (
          <ul className="studio-list">
            {collections.map((c) => (
              <li key={c.contract_address}>
                <Link href={`/studio/${c.contract_address}`} className="studio-row">
                  <span className="studio-row-name">{c.display_name}</span>
                  <span className="studio-row-meta">
                    {c.tier_count} tiers · {c.total_filled}/{c.total_cap} secured
                  </span>
                  <span className="studio-row-addr">{shortAddr(c.contract_address)}</span>
                  <span className={`studio-badge${c.published ? " is-live" : ""}`}>
                    {c.published ? "● Published" : "○ Draft"}
                  </span>
                  <span className="studio-row-go">▸</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>

      <footer className="studio-foot">
        <Link href="/">← The Paddock (holder view)</Link>
      </footer>
    </main>
  );
}
