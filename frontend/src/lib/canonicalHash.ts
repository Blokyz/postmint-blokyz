import { keccak256, toBytes } from "viem";

/**
 * PostMint Canonical Hash (PMCH v1) — JS reference implementation.
 *
 * MUST stay byte-for-byte in lockstep with `canonical_serialize` /
 * `compute_manifest_hash` in backend/app/manifests.py. This lets anyone verify a
 * manifest hash (the value locked on-chain via ManifestRegistry.lockManifest)
 * directly from the published manifest JSON.
 *
 * Spec: objects emit keys sorted by code point as {"k":v,...} with no whitespace;
 * arrays preserve order; strings use JSON escaping with non-ASCII left literal
 * (JSON.stringify); numbers are integer-valued → plain integer string, else a
 * fixed 6-fraction-digit decimal (inputs are pre-rounded to ≤6 dp). true/false/
 * null as-is. Result hashed as UTF-8 keccak256.
 */

type JsonValue = null | boolean | number | string | JsonValue[] | { [k: string]: JsonValue };

function canonicalNumber(value: number): string {
  if (!Number.isFinite(value)) {
    throw new Error(`non-finite number is not canonicalizable: ${value}`);
  }
  // String(-0) === "0" and Number.isInteger(-0) === true, so integers (incl.
  // 1.0 / -0.0) collapse to a plain decimal with no sign-of-zero quirk.
  if (Number.isInteger(value)) return String(value);
  const s = value.toFixed(6);
  return s === "-0.000000" ? "0.000000" : s;
}

export function canonicalSerialize(value: JsonValue): string {
  if (value === null) return "null";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") return canonicalNumber(value);
  if (typeof value === "string") return JSON.stringify(value);
  if (Array.isArray(value)) return "[" + value.map(canonicalSerialize).join(",") + "]";
  // object — sort keys by code point (matches Python's default string sort)
  const keys = Object.keys(value).sort();
  return "{" + keys.map((k) => JSON.stringify(k) + ":" + canonicalSerialize(value[k])).join(",") + "}";
}

/**
 * keccak256 over the PMCH-v1 canonical form with `approval` nulled — the exact
 * hash the backend computes and the project owner locks on-chain.
 */
export function computeManifestHash(manifest: { [k: string]: JsonValue }): string {
  const canonical = { ...manifest, approval: null };
  return keccak256(toBytes(canonicalSerialize(canonical)));
}
