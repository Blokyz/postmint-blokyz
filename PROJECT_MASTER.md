# Post-Mint Set Collection Engine — Master Reference

> Single source of truth for what this project is, how it works, all decisions made,
> and everything left to build. Updated as sprints progress.
>
> Last updated: 2026-05-23

---

## 1. What This Is

A **plug-and-play set collection engine for existing NFT projects**.

Any project plugs in their contract address → the engine figures out what's rare →
proposes challenges for holders to collect sets → holders race to win physical items.

**It is not a mint platform.** NFTs are not minted here. The project's existing collection
is used as-is. The engine layers a new competitive mechanic on top of it.

### Core Rules
- NFTs are **reusable** — no burn, no lock
- **First N wallets per tier** who hold the qualifying set long enough win
- **No per-wallet cap** — a whale owning many NFTs can theoretically win multiple slots
- Every claim is **recorded on-chain** (immutable, verifiable)

---

## 2. The 8 Tiers

| Tier | Default Cap | Holding Window | Difficulty |
|---|---|---|---|
| Common | 1,000 | Instant | Easiest |
| Uncommon | 750 | 24 hours | |
| Rare | 500 | 72 hours | |
| Super Rare | 250 | 7 days | |
| Ultra Rare | 100 | 7 days | |
| Legendary | 50 | 14 days | |
| Mythic | 12 | 14 days | |
| Secret | 1 | 14 days | Hardest |

Cap and window are **configurable per project per season** — these are defaults only.

---

## 3. How It Works — Full System Flow

```
1. Project provides NFT contract address + chain
         ↓
2. Engine pulls all token + trait data (Moralis NFT API v2.2)
         ↓
3. Computes statistical rarity (−log₂ of trait frequency)
         ↓
4. [Sprint 2] Runs OLS regression on sales → market premium per trait
         ↓
5. Combines both scores → single ranked trait list
         ↓
6. Project reviews ranking in UI, reorders if needed, approves
         ↓
7. Engine proposes set challenges per tier
   ("Hold any 3 NFTs from this pool of 20 traits")
         ↓
8. Project reviews tier cards, adjusts caps, approves atlas
         ↓
9. Atlas hash locked on-chain (ManifestRegistry contract) — immutable
         ↓
10. Claim event goes live — holders race to build their sets
         ↓
11. Engine watches wallets, enforces holding windows
         ↓
12. First N per tier who hold the qualifying set long enough win
         ↓
13. Winners recorded on-chain → Winner manifest exported → Vault partner ships prizes
```

---

## 4. What's Off-Chain vs On-Chain

| What | Where | Why |
|---|---|---|
| Rarity scoring (regression) | Off-chain | EVM can't run OLS regression |
| Set atlas generation | Off-chain | Combinatorial search, too expensive on-chain |
| Atlas hash commitment | **On-chain** | Trustless proof that project agreed to the rules |
| Eligibility checking | Off-chain | Checking 10k traits on-chain costs millions of gas |
| Eligibility proof signing | Off-chain | ~3k gas to verify on-chain vs millions to compute |
| Holding window tracking | Off-chain | Event-driven, free |
| Cap enforcement | **On-chain** | Must be trustless — race conditions impossible |
| Claim recording | **On-chain** | Permanent, immutable winner record |
| Winner export | Off-chain | Reads events → JSON → vault partner |

---

## 5. Tech Stack

| Layer | Technology | Notes |
|---|---|---|
| Data Pipeline | Python 3.11 | |
| API Backend | FastAPI | |
| Database | PostgreSQL 16 | |
| Task Queue | Celery + Redis 7 | Restartable, retryable, monitorable |
| NFT Data | Moralis NFT API v2.2 | |
| Stat Rarity | pandas + numpy | −log₂ frequency scoring |
| Market Premium | statsmodels (OLS) + scikit-learn (Ridge) | Sprint 2 |
| Smart Contracts | Solidity ^0.8.24 | |
| Contract Framework | Foundry | |
| Contract Libraries | OpenZeppelin 5.x | |
| Target Chain | Base L2 | |
| Frontend | Next.js 14 | |
| Wallet Connect | wagmi + RainbowKit | |
| Contract Calls | viem | |

---

## 6. Smart Contracts

Three contracts deployed on **Base L2** (testnet: Base Sepolia, chain id `84532`):

### `ManifestRegistry.sol` ✅ Built
Locks the approved atlas hash on-chain. Immutable proof the project agreed to the rules.

```
lockManifest(nftContract, rankingHash, atlasHash)  → emits ManifestLocked
verifyAtlas(nftContract, atlasHash)                → bool
isLocked(nftContract)                              → bool
```

⚠️ **Known gap:** No access control — any wallet can lock any contract address.
Must add pre-registration or operator whitelist before mainnet.

### `SetClaimManager.sol` ❌ Not built yet (Sprint 5)
One per project per season. Verifies eligibility signatures, enforces caps, records winners.

```
claim(tier, qualifyingTokenIds, windowStartedAt, expiry, nonce, signature)
```

Checks (in order): tier exists → sig not expired → nonce not used → not already claimed
→ cap not full → holding window elapsed → signature valid (ECDSA, backend signer) → award slot.

### `SetClaimFactory.sol` ❌ Not built yet (Sprint 5)
Deploys a new `SetClaimManager` for each project/season. Registry of all seasons.

```
deploySeason(nftContract, atlasHash, backendSigner, tierNames, caps, windows) → address
```

---

## 7. Database Schema

```sql
-- Token ownership snapshot
tokens        (contract_address, token_id) PK
              → owner_address, snapshot_block

-- One row per trait per token
traits        (contract_address, token_id, trait_category) PK
              → trait_value

-- Secondary market sales
sales         (id) PK
              → contract_address, token_id, sale_price_eth,
                seller_address, buyer_address, marketplace,
                tx_hash UNIQUE, sold_at, wash_trade_flag

-- Off-chain claim window tracking
claims        (id) PK | UNIQUE(contract_address, tier, wallet_address)
              → window_started, window_completed, slot_number,
                qualifying_tokens[], on_chain_tx_hash

-- Async ingestion job tracking
ingest_jobs   (id) PK
              → contract_address, chain, status, progress_pct,
                error_message, manifest_path, created_at, updated_at
```

---

## 8. API Routes

### Phase 1 — Audit

| Method | Route | Status | Purpose |
|---|---|---|---|
| POST | `/audit/ingest` | 🔨 Sprint 1 | Trigger ingestion for any contract |
| GET | `/audit/status/{contract}` | 🔨 Sprint 1 | Ingestion progress |
| GET | `/audit/ranking/{contract}` | 🔨 Sprint 1 | Ranked trait list |
| POST | `/audit/approve` | ⏳ Sprint 3 | Write approved manifest |

### Phase 2 — Atlas

| Method | Route | Status | Purpose |
|---|---|---|---|
| POST | `/atlas/generate` | ⏳ Sprint 5 | Generate atlas from manifest |
| GET | `/atlas/preview/{contract}` | ⏳ Sprint 5 | Proposed atlas + ladders |
| POST | `/atlas/approve` | ⏳ Sprint 6 | Lock frozen manifest + call ManifestRegistry |

### Phase 3 — Eligibility + Race

| Method | Route | Status | Purpose |
|---|---|---|---|
| GET | `/eligibility/{wallet}` | ⏳ Sprint 7 | Qualifying sets + progress per tier |
| GET | `/leaderboard/{tier}` | ⏳ Sprint 7 | Aggregate counts (no wallet IDs) |
| POST | `/claim/submit` | ⏳ Sprint 8 | Start holding window |
| POST | `/claim/sign` | ⏳ Sprint 8 | Issue ECDSA proof (after window completes) |
| GET | `/claim/status/{wallet}/{tier}` | ⏳ Sprint 8 | Window + slot status |
| GET | `/winners/{contract}` | ⏳ Sprint 8 | Winner manifest export |

---

## 9. Rarity Algorithm

### Step 1 — Statistical Rarity (Sprint 1)

```
frequency    = token_count / eligible_supply
stat_rarity  = −log₂(frequency)          ← information content
stat_norm    = (x − min) / (max − min)   ← normalised to [0,1]
```

### Step 2 — Market Premium (Sprint 2)

```
Model: log(sale_price) = α + Σ βᵢ·trait_i + γ·days_since_first + ε

β coefficient  = how much that trait shifts log-price
e^β            = price multiplier (e.g. β=2.14 → buyers pay ~8.5× more)
market_norm    = (β − β_min) / (β_max − β_min)

Fallback to Ridge when n_traits > n_clean_sales × 0.5
```

### Step 3 — Combined Score

```
combined_score = α × stat_norm + β × market_norm
Default: α = 0.5, β = 0.5 (project adjusts via UI sliders)
Sort descending → rank 1..N
```

### Wash Trade Detection (Sprint 2, before OLS)

| Rule | Logic |
|---|---|
| Self-trade | `seller_address = buyer_address` |
| Pair frequency | Same two wallets traded >3× in 30 days |
| Price outlier | Sale price >10× rolling 7-day floor |
| Quick flip | Token re-sold by buyer within 72 hours |

---

## 10. Set Atlas Generator

### Rarity Band Slicing

| Tier | Rank Band (% of total traits) |
|---|---|
| Common | Bottom 50% |
| Uncommon | 30–50% |
| Rare | 15–30% |
| Super Rare | 7–15% |
| Ultra Rare | 3–7% |
| Legendary | 1–3% |
| Mythic | 0.2–1% |
| Secret | Top 0.2% |

### Three Set Archetypes

| Archetype | Rule | Used For |
|---|---|---|
| Count-of-pool | Hold any X NFTs from a trait pool | Common → Rare |
| One-of-each | Hold one NFT from each specified trait value | Mid tiers |
| Apex combo | Hold X NFTs all from the rarest pool | Mythic / Secret |

### Feasibility Math

```
max_sets_formable = pool_qualifying_nfts / X
race_intensity    = estimated_qualifiers / tier_cap
fit_score         = 1.0 / |log(race_intensity)|   ← target: 1.0–3.0×
```

### Ladder Detection
When adjacent tiers share >70% pool overlap with different X values → detected as ladder.
Example: 3 Yellow apes → Common, 6 Yellow apes → Uncommon.

---

## 11. Eligibility + Claiming

### Eligibility Check (per wallet, per tier)

```
holdings        = current tokens owned by wallet (re-fetched from chain)
matching_tokens = tokens where any trait matches the pool
qualifies       = count(matching_tokens) >= X
progress_pct    = min(100, count / X × 100)
needed          = max(0, X - count)
```

### Holding Window

```
Window starts  → when wallet first qualifies for a tier
Window resets  → if any qualifying token is transferred OUT
Window expires → when block.timestamp >= window_started + holding_window_seconds
Window valid   → backend signs proof → wallet submits claim tx
```

Transfer detection: **Moralis transfer polling** (`GET /api/v2.2/nft/{address}/transfers` every 30s).

### ECDSA Signing (Backend → Contract Bridge)

Backend hot signer holds no funds. Signs:
`wallet + tier + nftContract + tokenIds + windowStartedAt + expiry + nonce`

Encoding must match `abi.encodePacked()` in `SetClaimManager` exactly.
Signature valid for **1 hour** only. Nonce single-use.

---

## 12. Security Model

| Concern | Mitigation |
|---|---|
| Replay attacks | Every signature includes unique `nonce`. Contract stores used nonces. |
| Signature expiry | Valid max 1 hour. Expired sigs revert with clear message. |
| Signer compromise | Signer wallet holds no ETH. Blast radius = signing ability only. |
| Cap race conditions | `claimed < cap` checked atomically in same tx — impossible to exceed on-chain. |
| Cross-chain trust | Claims are on Base; NFT data is on Ethereum. Trust is entirely in backend signature. Scope this explicitly in the security audit. |
| ManifestRegistry griefing | Any wallet can currently lock any contract. ⚠️ Fix before mainnet. |
| Signer key storage | Must use a secrets vault in production — never commit to `.env` in git. |

**Audit required:** `SetClaimManager.sol` must be audited by an external firm before mainnet.

---

## 13. Manifest File Formats

### Ranking Manifest (Phase 1 output)
`output/{contract_address}_ranking_manifest.json`

Key fields:
- `manifest_id` — UUID
- `collection.contract_address`, `collection.chain`, `collection.eligible_supply`
- `weights.alpha`, `weights.beta` — scoring weights (project-adjustable)
- `trait_rankings[]` — ranked list with rank, stat_norm, market_norm, combined_score
- `approval` — null until project approves

### Set Atlas Manifest (Phase 2 output)
`output/{contract_address}_atlas_manifest.json`

Key fields:
- `atlas_manifest_id`, `ranking_manifest_id`
- `tier_structure` — caps + holding_window_hours per tier
- `tiers[]` — set rules, pool, feasibility math, alternatives
- `ladders[]` — detected natural ladders between adjacent tiers

### Winner Manifest (Phase 3 output)
`output/{contract_address}_winner_manifest.json`

Key fields:
- `tiers[].winners[]` — slot number, wallet, qualifying tokens, on-chain tx, shipping status

---

## 14. Full Sprint Plan

| Sprint | Weeks | Deliverable | Status |
|---|---|---|---|
| 0 | Done | Monorepo skeleton, DB schema, health APIs, ManifestRegistry.sol + tests | ✅ Done |
| 1 | Current | Moralis ingest (any collection) → Postgres → stat rarity → ranking_manifest.json | 🔨 In Progress |
| 2 | Next | Sales ingestion + wash trade detection + OLS/Ridge regression → combined ranking | ⏳ |
| 3 | | Manifest builder + FastAPI audit approval routes | ⏳ |
| 4 | | Audit UI: drag-and-drop ranking review + validate 5 collections | ⏳ |
| 5 | | Atlas candidate generator + slotter + atlas manifest + SetClaimFactory + SetClaimManager + Foundry tests | ⏳ |
| 6 | | Atlas UI + approval flow + on-chain lockManifest | ⏳ |
| 7 | | Eligibility evaluator + holding window (Moralis transfer polling) + Base Sepolia deploy | ⏳ |
| 8 | | Signing service + claim routes + winner manifest export | ⏳ |
| 9 | | Holder dashboard + leaderboard + full claim flow on testnet | ⏳ |
| 10+ | | External security audit (smart contracts) | ⏳ |
| 11+ | | Mainnet deploy on Base (after audit sign-off) | ⏳ |

---

## 15. Validation Pass Criteria

The rarity engine passes validation when **7 of the top 10 traits match documented collector
consensus** for at least one collection:

| Collection | Chain | Why Included |
|---|---|---|
| BAYC | Ethereum | Large, well-documented — Solid Gold Fur = rank 1 easily verifiable |
| Good Vibes Club | Ethereum | Intentionally engineered rarity tiers |
| Quirkies | Ethereum | "Diamond" rare class easily verifiable |
| Chimpers | Ethereum | Documented Type tier (Divine → Common) |
| Claynosaurz | Ethereum (bridged) | Cross-chain validation |

---

## 16. Open Questions

| # | Question | Status |
|---|---|---|
| 1 | **Whale multi-claim** — can one wallet claim multiple slots in the same tier? If yes, remove `UNIQUE(contract_address, tier, wallet_address)` from claims table. | ⚠️ Needs product decision |
| 2 | **ManifestRegistry access control** — pre-register pattern or platform operator whitelist? | ⚠️ Needs decision before mainnet |
| 3 | **Holding windows** — are the default durations (24h → 14 days) confirmed, or should projects set their own? | Open |
| 4 | **Paid claims** — does the atlas UI need price-per-tier fields (claim fee)? | Open |
| 5 | **Hosting** — Railway + Supabase before or after Sprint 2 validation? | Open |
| 6 | **Security audit firm** — budget and timeline needed before Sprint 3 contracts go to mainnet | Open |

---

## 17. Known Bugs / Risks

| Issue | Severity | Sprint |
|---|---|---|
| `ManifestRegistry` has no access control — griefing attack possible | HIGH | Fix in Sprint 5 |
| Moralis API key required — ingestion silently fails without it | Medium | Sprint 1 startup check |
| `IngestJob` missing `manifest_path` column — will be added in migration 002 | Medium | Sprint 1 |
| CORS hardcoded to `localhost:3000` — staging/prod will fail | Low | Sprint 1 config update |
| Transfer detection has no implementation yet — holding window engine blocked | Low | Sprint 7 |
