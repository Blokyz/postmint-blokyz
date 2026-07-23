// Minimal ManifestRegistry ABI for the on-chain lock flow.
// Mirrors contracts/src/ManifestRegistry.sol — only the functions the frontend
// calls (lockManifest write + isLocked/verifyAtlas reads).

export const MANIFEST_REGISTRY_ABI = [
  {
    type: "function",
    name: "lockManifest",
    stateMutability: "nonpayable",
    inputs: [
      { name: "nftContract", type: "address" },
      { name: "rankingHash", type: "bytes32" },
      { name: "atlasHash", type: "bytes32" },
      { name: "backendSig", type: "bytes" },
    ],
    outputs: [],
  },
  {
    type: "function",
    name: "isLocked",
    stateMutability: "view",
    inputs: [{ name: "nftContract", type: "address" }],
    outputs: [{ name: "", type: "bool" }],
  },
  {
    type: "function",
    name: "verifyAtlas",
    stateMutability: "view",
    inputs: [
      { name: "nftContract", type: "address" },
      { name: "atlasHash", type: "bytes32" },
    ],
    outputs: [{ name: "", type: "bool" }],
  },
] as const;

// Response shape of POST /atlas/lock-attestation (see backend
// app/api/schemas.py::LockAttestationResponse). All hashes/addresses are the
// exact values the backend signed; `registry_address` is the contract the
// signature is bound to, so the lock tx MUST target it.
export type LockAttestation = {
  contract_address: `0x${string}`;
  ranking_hash: `0x${string}`;
  atlas_hash: `0x${string}`;
  signature: `0x${string}`;
  backend_signer: `0x${string}`;
  registry_address: `0x${string}`;
  chain_id: number;
};

// Block-explorer tx URL for the chains we lock on (Base Sepolia / Base mainnet).
export function explorerTxUrl(chainId: number, hash: string): string | null {
  if (chainId === 84532) return `https://sepolia.basescan.org/tx/${hash}`;
  if (chainId === 8453) return `https://basescan.org/tx/${hash}`;
  return null;
}
