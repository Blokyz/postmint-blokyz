"use client";

import { ConnectButton } from "@rainbow-me/rainbowkit";
import { useAccount, useChainId } from "wagmi";
import { BAYC_ADDRESS, manifestRegistryAddress } from "@/lib/wagmi";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default function HomePage() {
  const { address, isConnected } = useAccount();
  const chainId = useChainId();

  return (
    <main>
      <header>
        <div>
          <h1 style={{ margin: 0, fontSize: "1.35rem" }}>Post-Mint Set Collection</h1>
          <p className="muted" style={{ margin: "0.25rem 0 0" }}>
            Base Sepolia · BAYC validation
          </p>
        </div>
        <ConnectButton />
      </header>

      <section className="card">
        <h2>MVP config</h2>
        <ul className="muted" style={{ margin: 0, paddingLeft: "1.2rem" }}>
          <li>
            Claim chain: Base Sepolia (<code>{chainId}</code>)
          </li>
          <li>
            Validation collection: BAYC <code>{BAYC_ADDRESS}</code>
          </li>
          <li>
            Manifest registry:{" "}
            {manifestRegistryAddress ? (
              <code>{manifestRegistryAddress}</code>
            ) : (
              <span>not deployed — set NEXT_PUBLIC_MANIFEST_REGISTRY_ADDRESS</span>
            )}
          </li>
          <li>
            API: <code>{API_URL}</code>
          </li>
        </ul>
      </section>

      <section className="card">
        <h2>Connected wallet (on-chain approver)</h2>
        {isConnected && address ? (
          <p style={{ margin: 0 }}>
            <code>{address}</code> — will sign <code>lockManifest</code> on Base Sepolia after atlas
            approval (Sprint 6).
          </p>
        ) : (
          <p className="muted" style={{ margin: 0 }}>
            Connect a wallet to continue. Project approval uses your wallet on-chain, not an admin key.
          </p>
        )}
      </section>

      <section className="card">
        <h2>Sprint 0</h2>
        <p className="muted" style={{ margin: 0 }}>
          Backend audit routes and ingestion land in Sprint 1. This shell wires wallet + chain for
          upcoming audit / atlas / claim flows.
        </p>
      </section>
    </main>
  );
}
