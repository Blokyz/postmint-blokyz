// Operator authorization for starting an ingestion.
//
// Byte-for-byte mirror of backend app/signing.py:build_ingest_message. Keep in
// lockstep — the backend recovers the signer from these exact bytes. `issuedAt`
// is unix seconds; the backend rejects signatures older than its
// INGEST_SIG_TTL_SECONDS (default 5 min), so sign immediately before POSTing.
export function buildIngestMessage(contract: string, chain: string, issuedAt: number): string {
  return `PostMint collection ingest\ncontract:${contract.toLowerCase()}\nchain:${chain}\nissued_at:${issuedAt}`;
}
