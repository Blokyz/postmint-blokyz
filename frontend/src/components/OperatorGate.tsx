"use client";

// Studio access gate. Blocks every /studio page behind a connected wallet on
// the backend operator allowlist (GET /auth/operator/{wallet}). UX ONLY — the
// writes stay signature-gated server-side; an empty backend allowlist = open,
// so local dev is unaffected until OPERATOR_ALLOWLIST is set.

import { useEffect, useState } from "react";
import Link from "next/link";
import { useAccount } from "wagmi";
import { ConnectButton } from "@rainbow-me/rainbowkit";
import { apiGet } from "@/lib/api";

type GateState = "checking" | "allowed" | "denied" | "error";

export function OperatorGate({ children }: { children: React.ReactNode }) {
  const { address, status } = useAccount();
  const [gate, setGate] = useState<GateState>("checking");
  // Wallet state differs between SSR and the reconnecting client — render the
  // neutral "checking" card until mounted to avoid a hydration mismatch.
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  useEffect(() => {
    if (!address) return;
    let cancelled = false;
    setGate("checking");
    apiGet<{ allowed: boolean }>(`/auth/operator/${address}`)
      .then((r) => {
        if (!cancelled) setGate(r.allowed ? "allowed" : "denied");
      })
      .catch(() => {
        if (!cancelled) setGate("error");
      });
    return () => {
      cancelled = true;
    };
  }, [address]);

  if (mounted && status === "connected" && gate === "allowed") return <>{children}</>;

  const disconnected = mounted && status === "disconnected";

  return (
    <div className="op-gate">
      <div className="op-gate-card" role="dialog" aria-modal="true">
        {disconnected ? (
          <>
            <span className="op-gate-kicker">STUDIO ACCESS</span>
            <h1 className="op-gate-title">Project owners &amp; admins only</h1>
            <p className="op-gate-desc">
              The Studio is where projects run their ingest → approve → atlas → publish
              pipeline. Connect an operator wallet to continue.
            </p>
            <div className="op-gate-actions">
              <ConnectButton accountStatus="address" chainStatus="none" showBalance={false} />
              <Link className="op-gate-back" href="/paddock">
                ← Back to The Paddock
              </Link>
            </div>
          </>
        ) : mounted && status === "connected" && gate === "denied" ? (
          <>
            <span className="op-gate-kicker">ACCESS DENIED</span>
            <h1 className="op-gate-title">This area is only for project owners and admins</h1>
            <p className="op-gate-desc">
              The connected wallet is not on the operator allowlist. If you run a project
              on PostMint, contact the platform to get your wallet added — or switch to
              your operator wallet.
            </p>
            <div className="op-gate-actions">
              <ConnectButton accountStatus="address" chainStatus="none" showBalance={false} />
              <Link className="op-gate-back" href="/paddock">
                ← Back to The Paddock
              </Link>
            </div>
          </>
        ) : mounted && status === "connected" && gate === "error" ? (
          <>
            <span className="op-gate-kicker">STUDIO ACCESS</span>
            <h1 className="op-gate-title">Couldn&apos;t verify access</h1>
            <p className="op-gate-desc">
              The API is unreachable, so operator access can&apos;t be checked. Make sure
              the backend is running, then reload.
            </p>
          </>
        ) : (
          <span className="op-gate-checking">Checking access…</span>
        )}
      </div>
    </div>
  );
}
