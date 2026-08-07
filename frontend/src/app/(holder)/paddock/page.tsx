"use client";

import { ConnectButton } from "@rainbow-me/rainbowkit";
import { displayFont, bodyFont } from "@/lib/fonts";
import Link from "next/link";
import { useEffect, useState } from "react";
import { ContestCard } from "@/components/ContestCard";
import { SiteHeader } from "@/components/SiteHeader";
import { CollectionSummary, listCollections } from "@/lib/collections";

const display = displayFont;
const mono = bodyFont;

export default function DirectoryPage() {
  const [cols, setCols] = useState<CollectionSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const running = (cols ?? []).filter((c) => c.status !== "full");
  const finished = (cols ?? []).filter((c) => c.status === "full");

  useEffect(() => {
    listCollections()
      .then(setCols)
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load contests"));
  }, []);

  return (
    <>
      <SiteHeader
        actions={<ConnectButton accountStatus="address" chainStatus="icon" showBalance={false} />}
      >
        <Link href="/paddock" className="site-nav__section">
          The Paddock
        </Link>
      </SiteHeader>
      <main className={`race-control ${display.variable} ${mono.variable}`}>
      <div className="rc-grain" aria-hidden />
      <div className="rc-flag" aria-hidden />

      <header className="rc-header">
        <div className="rc-id">
          <span className="rc-kicker">POSTMINT // live contests</span>
          <h1 className="rc-title">The&nbsp;Paddock</h1>
        </div>
      </header>

      {error && <p className="rc-alert">⨯ {error}</p>}

      {cols && running.length === 0 && (
        <section className="rc-empty">
          <p>No live contests yet. Once a project publishes its set atlas, it shows up here.</p>
        </section>
      )}

      {running.length > 0 && (
        <section className="dir-grid">
          {running.map((c) => (
            <ContestCard key={c.slug} c={c} />
          ))}
        </section>
      )}

      {finished.length > 0 && (
        <>
          <h2 className="dir-finished-head">FINISHED — grids full</h2>
          <section className="dir-grid dir-grid--finished">
            {finished.map((c) => (
              <ContestCard key={c.slug} c={c} />
            ))}
          </section>
        </>
      )}
      </main>
    </>
  );
}
