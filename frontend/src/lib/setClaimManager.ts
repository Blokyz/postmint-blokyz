// Minimal SetClaimManager ABI for the on-chain claim flow.
// Mirrors contracts/src/SetClaimManager.sol — only what the /race page calls
// (the claim write + slotsRemaining read).

export const SET_CLAIM_MANAGER_ABI = [
  {
    type: "function",
    name: "claim",
    stateMutability: "nonpayable",
    inputs: [
      { name: "tier", type: "string" },
      { name: "tokenIds", type: "uint256[]" },
      { name: "windowStartedAt", type: "uint256" },
      { name: "expiry", type: "uint256" },
      { name: "nonce", type: "uint256" },
      { name: "signature", type: "bytes" },
    ],
    outputs: [],
  },
  {
    type: "function",
    name: "slotsRemaining",
    stateMutability: "view",
    inputs: [{ name: "tier", type: "string" }],
    outputs: [{ name: "", type: "uint256" }],
  },
] as const;

// Response shape of POST /claim/sign (see backend app/api/schemas.py
// ::ClaimSignResponse). These are the exact values the backend signed; the claim
// tx MUST target `manager_address` on `chain_id`, and pass the tuple verbatim.
export type ClaimAttestation = {
  contract_address: `0x${string}`;
  tier: string;
  wallet_address: `0x${string}`;
  manager_address: `0x${string}`;
  chain_id: number;
  token_ids: number[];
  window_started_at: number;
  expiry: number;
  nonce: number;
  signature: `0x${string}`;
  backend_signer: `0x${string}`;
};

// Build the positional args for SetClaimManager.claim from a sign attestation.
// uint256 fields must be bigint; token ids come back as JSON numbers.
export function claimArgs(att: ClaimAttestation) {
  return [
    att.tier,
    att.token_ids.map((t) => BigInt(t)),
    BigInt(att.window_started_at),
    BigInt(att.expiry),
    BigInt(att.nonce),
    att.signature,
  ] as const;
}
