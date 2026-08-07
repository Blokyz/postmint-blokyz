"use client";

import { Crest } from "@/components/Crest";

interface ClaimConfirmModalProps {
  tier: string;
  collectionName: string;
  chain: string;
  onConfirm: () => void;
  onCancel: () => void;
  loading: boolean;
}

export function ClaimConfirmModal({
  tier,
  collectionName,
  chain,
  onConfirm,
  onCancel,
  loading,
}: ClaimConfirmModalProps) {
  return (
    <div className="rc-modal-backdrop" role="dialog" aria-modal="true">
      <div className="rc-modal-card">
        <div className="rc-modal-head">
          <Crest tier={tier} state="ready" size={56} />
          <div>
            <span className="rc-modal-kicker">CONFIRM ON-CHAIN CLAIM</span>
            <h2 className="rc-modal-title">Claim {tier} Slot</h2>
          </div>
        </div>

        <div className="rc-modal-body">
          <p className="rc-modal-desc">
            You have completed your holding window for <strong>{collectionName}</strong> on the <strong>{tier}</strong> tier.
          </p>

          <div className="rc-modal-details">
            <div className="rc-modal-row">
              <span className="rc-modal-label">Network:</span>
              <span className="rc-modal-val">{chain.toUpperCase()}</span>
            </div>
            <div className="rc-modal-row">
              <span className="rc-modal-label">Transaction type:</span>
              <span className="rc-modal-val">SetClaimManager.claim()</span>
            </div>
            <div className="rc-modal-row">
              <span className="rc-modal-label">Attestation signature:</span>
              <span className="rc-modal-val">Single-use cryptographically signed ticket</span>
            </div>
          </div>

          <div className="rc-modal-notice">
            <span className="rc-modal-notice-icon">💡</span>
            <p>
              Submitting this transaction requires wallet gas. Once confirmed on-chain, your win will be permanently recorded and your Championship Points updated.
            </p>
          </div>
        </div>

        <div className="rc-modal-foot">
          <button
            type="button"
            className="rc-btn is-ghost"
            onClick={onCancel}
            disabled={loading}
          >
            Cancel
          </button>
          <button
            type="button"
            className="rc-btn is-green"
            onClick={onConfirm}
            disabled={loading}
          >
            {loading ? "Requesting Signature…" : "Confirm & Sign in Wallet ⚡"}
          </button>
        </div>
      </div>
    </div>
  );
}
