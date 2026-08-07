"use client";

import { useEffect, useState } from "react";
import {
  useAccount,
  useChainId,
  useReadContract,
  useSwitchChain,
  useWaitForTransactionReceipt,
  useWriteContract,
} from "wagmi";
import { ApiError, apiPost } from "@/lib/api";
import { LockAttestation, MANIFEST_REGISTRY_ABI, explorerTxUrl } from "@/lib/manifestRegistry";
import { manifestRegistryAddress } from "@/lib/wagmi";

// Turn a wagmi/viem error into one human line. The contract's revert strings
// ("Already locked", "Unauthorized: bad backend signature") surface verbatim
// inside the verbose viem message, so we match on them.
function humanizeError(e: unknown): string {
  const msg = e instanceof Error ? e.message : String(e);
  if (/User rejected|User denied|rejected the request/i.test(msg)) return "Transaction rejected in your wallet.";
  if (/Already locked/.test(msg)) return "This collection is already locked on-chain.";
  if (/Unauthorized|bad backend signature/.test(msg)) return "Contract rejected the backend signature.";
  if (/Already locked|Invalid contract|Bad sig/.test(msg)) return msg.split("\n")[0];
  return msg.split("\n")[0].slice(0, 200);
}

type Phase = "idle" | "attesting" | "submitting";

export function LockPanel({ contract, dirty }: { contract: string; dirty: boolean }) {
  const { isConnected } = useAccount();
  const chainId = useChainId();
  const { switchChainAsync } = useSwitchChain();
  const { writeContractAsync } = useWriteContract();

  const [phase, setPhase] = useState<Phase>("idle");
  const [att, setAtt] = useState<LockAttestation | null>(null);
  const [txHash, setTxHash] = useState<`0x${string}` | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);

  const { isLoading: mining, isSuccess: mined } = useWaitForTransactionReceipt({ hash: txHash });

  // Pre-check on-chain lock state (best-effort: needs the env-configured
  // registry address; the write itself targets the attestation's registry).
  const { data: alreadyLocked, refetch: refetchLocked } = useReadContract({
    abi: MANIFEST_REGISTRY_ABI,
    address: manifestRegistryAddress,
    functionName: "isLocked",
    args: [contract as `0x${string}`],
    query: { enabled: Boolean(manifestRegistryAddress) },
  });

  // Reset transient state when the target contract changes.
  useEffect(() => {
    setPhase("idle");
    setAtt(null);
    setTxHash(undefined);
    setError(null);
  }, [contract]);

  // Refresh the lock badge once the tx confirms.
  useEffect(() => {
    if (mined) refetchLocked();
  }, [mined, refetchLocked]);

  const busy = phase !== "idle" || mining;

  async function handleLock() {
    setError(null);
    setTxHash(undefined);
    setPhase("attesting");
    try {
      const attestation = await apiPost<LockAttestation>("/atlas/lock-attestation", { contract_address: contract });
      setAtt(attestation);

      // The attestation is bound to a specific chain; make sure the wallet is on it.
      if (chainId !== attestation.chain_id) {
        await switchChainAsync({ chainId: attestation.chain_id });
      }

      setPhase("submitting");
      const hash = await writeContractAsync({
        abi: MANIFEST_REGISTRY_ABI,
        address: attestation.registry_address,
        functionName: "lockManifest",
        args: [
          attestation.contract_address,
          attestation.ranking_hash,
          attestation.atlas_hash,
          attestation.signature,
        ],
        chainId: attestation.chain_id,
      });
      setTxHash(hash);
    } catch (e) {
      setError(humanizeError(e));
    } finally {
      setPhase("idle");
    }
  }

  const txUrl = att && txHash ? explorerTxUrl(att.chain_id, txHash) : null;
  const locked = alreadyLocked === true || mined;

  return (
    <section className="lock-panel">
      <div className="lock-head">
        <span className="lock-kicker">On-chain // commit</span>
        <h2 className="lock-title">Lock manifests</h2>
        <p className="lock-lede">
          Write the approved ranking hash and generated atlas hash to <code>ManifestRegistry</code>. The
          backend signs the lock tuple; your wallet submits the transaction and is recorded as the approver.
        </p>
      </div>

      {locked ? (
        <div className="lock-state is-locked">
          <span className="lock-badge">● Locked</span>
          <p>
            This collection&apos;s manifests are locked on-chain and immutable.
            {txUrl && (
              <>
                {" "}
                <a href={txUrl} target="_blank" rel="noopener noreferrer">
                  View transaction ↗
                </a>
              </>
            )}
          </p>
        </div>
      ) : (
        <>
          {att && (
            <dl className="lock-tuple">
              <div>
                <dt>Ranking hash</dt>
                <dd>
                  <code>{att.ranking_hash}</code>
                </dd>
              </div>
              <div>
                <dt>Atlas hash</dt>
                <dd>
                  <code>{att.atlas_hash}</code>
                </dd>
              </div>
              <div>
                <dt>Registry</dt>
                <dd>
                  <code>{att.registry_address}</code> · chain {att.chain_id}
                </dd>
              </div>
            </dl>
          )}

          <div className="lock-actions">
            <button type="button" className="lock-btn" onClick={handleLock} disabled={!isConnected || busy || dirty}>
              {phase === "attesting"
                ? "Requesting attestation…"
                : phase === "submitting"
                  ? "Confirm in wallet…"
                  : mining
                    ? "Locking on-chain…"
                    : "Lock on-chain"}
            </button>

            {!isConnected && <span className="lock-note">Connect a wallet (top-right) to submit the lock.</span>}
            {isConnected && dirty && (
              <span className="lock-note">
                Unsaved tier changes — hit “Regenerate” first so the locked atlas matches what you see.
              </span>
            )}
            {mining && txUrl && (
              <a className="lock-note" href={txUrl} target="_blank" rel="noopener noreferrer">
                Pending transaction ↗
              </a>
            )}
          </div>

          {error && <p className="lock-error">{error}</p>}
        </>
      )}
    </section>
  );
}
