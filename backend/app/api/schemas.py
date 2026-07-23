import re

from pydantic import BaseModel, Field, field_validator, model_validator

_ETH_ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
_SIGNATURE_RE = re.compile(r"^0x[a-fA-F0-9]{130}$")  # 65-byte ECDSA sig (r||s||v)
_TX_HASH_RE = re.compile(r"^0x[a-fA-F0-9]{64}$")  # 32-byte tx hash


def _lower_address(v: str) -> str:
    v = v.strip().lower()
    if not _ETH_ADDRESS_RE.match(v):
        raise ValueError("must be a valid EVM address (0x + 40 hex chars)")
    return v


class IngestRequest(BaseModel):
    contract_address: str
    chain: str = "eth"

    @field_validator("contract_address")
    @classmethod
    def validate_address(cls, v: str) -> str:
        v = v.strip().lower()
        if not _ETH_ADDRESS_RE.match(v):
            raise ValueError("contract_address must be a valid EVM address (0x + 40 hex chars)")
        return v


class IngestResponse(BaseModel):
    job_id: str
    contract_address: str
    status: str
    message: str


class StatusResponse(BaseModel):
    contract_address: str
    job_id: str | None
    status: str | None
    # Coarse pipeline stage: queued | fetching_nfts | fetching_sales | scoring | done | failed.
    phase: str | None
    progress_pct: int | None
    error_message: str | None


class TraitApproval(BaseModel):
    trait_category: str
    trait_value: str
    pinned: bool = False


class ApproveRequest(BaseModel):
    contract_address: str
    approver_address: str
    trait_rankings: list[TraitApproval]
    # Stat-vs-market blend chosen by the approver; must sum to 1.0. Recorded in
    # the manifest and covered by the signature.
    w_stat: float = 0.5
    w_market: float = 0.5
    # EIP-191 personal_sign over the canonical approval message (see app.signing).
    signature: str

    @field_validator("contract_address", "approver_address")
    @classmethod
    def validate_addresses(cls, v: str) -> str:
        v = v.strip().lower()
        if not _ETH_ADDRESS_RE.match(v):
            raise ValueError("must be a valid EVM address (0x + 40 hex chars)")
        return v

    @field_validator("w_stat", "w_market")
    @classmethod
    def validate_weight(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError("weight must be in [0, 1]")
        return round(v, 2)  # 2-dp grid keeps the signed message byte-stable across JS/Python

    @model_validator(mode="after")
    def validate_weights_sum(self) -> "ApproveRequest":
        if abs((self.w_stat + self.w_market) - 1.0) > 1e-6:
            raise ValueError("w_stat + w_market must sum to 1.0")
        return self

    @field_validator("signature")
    @classmethod
    def validate_signature(cls, v: str) -> str:
        v = v.strip()
        if not _SIGNATURE_RE.match(v):
            raise ValueError("signature must be a 65-byte hex ECDSA signature (0x + 130 hex chars)")
        return v


class ApproveResponse(BaseModel):
    contract_address: str
    manifest_hash: str
    approved_at: str
    approver_address: str
    trait_count: int
    w_stat: float
    w_market: float


class LockAttestationRequest(BaseModel):
    contract_address: str

    @field_validator("contract_address")
    @classmethod
    def validate_address(cls, v: str) -> str:
        v = v.strip().lower()
        if not _ETH_ADDRESS_RE.match(v):
            raise ValueError("contract_address must be a valid EVM address (0x + 40 hex chars)")
        return v


class LockAttestationResponse(BaseModel):
    contract_address: str
    ranking_hash: str
    atlas_hash: str
    # Backend-signer attestation the project owner passes to lockManifest().
    signature: str
    backend_signer: str
    registry_address: str
    chain_id: int


class TierOverride(BaseModel):
    cap: int = Field(ge=1)
    holding_window_hours: float = Field(ge=0)
    # Set size (tokens a wallet must hold from the tier's band). Optional so a
    # partial override keeps the graduated default; clamped to the pool downstream.
    count_required: int | None = Field(default=None, ge=1, le=20)


class AtlasGenerateRequest(BaseModel):
    contract_address: str
    tier_structure: dict[str, TierOverride] | None = None

    @field_validator("contract_address")
    @classmethod
    def validate_address(cls, v: str) -> str:
        v = v.strip().lower()
        if not _ETH_ADDRESS_RE.match(v):
            raise ValueError("contract_address must be a valid EVM address (0x + 40 hex chars)")
        return v

    @field_validator("tier_structure")
    @classmethod
    def validate_tier_structure(cls, v: dict[str, TierOverride] | None) -> dict[str, TierOverride] | None:
        if v is None:
            return v
        from app.atlas.generator import DEFAULT_TIER_STRUCTURE

        unknown = set(v) - set(DEFAULT_TIER_STRUCTURE)
        if unknown:
            raise ValueError(f"Unknown tier(s) in tier_structure: {sorted(unknown)}")
        return v


# --- Phase 3: claims / race ---


class SeasonRegisterRequest(BaseModel):
    """Register a deployed `SetClaimManager` so the backend can attest claims for it."""

    contract_address: str
    manager_address: str
    atlas_hash: str | None = None

    @field_validator("contract_address", "manager_address")
    @classmethod
    def validate_addresses(cls, v: str) -> str:
        return _lower_address(v)


class SeasonResponse(BaseModel):
    contract_address: str
    manager_address: str
    atlas_hash: str | None
    chain_id: int


class ClaimSubmitRequest(BaseModel):
    """Opt in to (start/resume) a holding window for a qualifying wallet+tier."""

    contract_address: str
    tier: str
    wallet_address: str

    @field_validator("contract_address", "wallet_address")
    @classmethod
    def validate_addresses(cls, v: str) -> str:
        return _lower_address(v)


class ClaimSignRequest(BaseModel):
    """Request a backend attestation to submit `SetClaimManager.claim` on-chain.
    Only issued when the wallet's window is `ready` (elapsed + still qualifying)."""

    contract_address: str
    tier: str
    wallet_address: str

    @field_validator("contract_address", "wallet_address")
    @classmethod
    def validate_addresses(cls, v: str) -> str:
        return _lower_address(v)


class ClaimSignResponse(BaseModel):
    contract_address: str
    tier: str
    wallet_address: str
    manager_address: str
    chain_id: int
    token_ids: list[int]
    window_started_at: int
    expiry: int
    nonce: int
    signature: str
    backend_signer: str


class ClaimConfirmRequest(BaseModel):
    """Report a landed on-chain claim tx so the backend records the win."""

    contract_address: str
    tier: str
    wallet_address: str
    tx_hash: str
    slot_number: int | None = None

    @field_validator("contract_address", "wallet_address")
    @classmethod
    def validate_addresses(cls, v: str) -> str:
        return _lower_address(v)

    @field_validator("tx_hash")
    @classmethod
    def validate_tx_hash(cls, v: str) -> str:
        v = v.strip().lower()
        if not _TX_HASH_RE.match(v):
            raise ValueError("tx_hash must be a 32-byte hex hash (0x + 64 hex chars)")
        return v


# --- Phase 1: collections registry (slug -> contract tenancy) ---


class CollectionCreateRequest(BaseModel):
    """Publish a collection under a slug. `slug` optional — derived from
    `display_name` when omitted."""

    contract_address: str
    display_name: str
    slug: str | None = None
    image_url: str | None = None
    published: bool = True
    # Operator authorization (enforced only when `operator_allowlist` is set).
    # EIP-191 personal_sign over app.signing.build_publish_message, plus the signer.
    operator_address: str | None = None
    signature: str | None = None

    @field_validator("contract_address")
    @classmethod
    def validate_address(cls, v: str) -> str:
        return _lower_address(v)


class CollectionResponse(BaseModel):
    slug: str
    contract_address: str
    display_name: str
    chain: str
    image_url: str | None
    published: bool


class CollectionSummary(BaseModel):
    """Directory-card shape for the holder-side collections grid."""

    slug: str
    display_name: str
    contract_address: str
    chain: str
    image_url: str | None
    published: bool
    tier_count: int
    total_cap: int
    total_filled: int
    racers: int
    status: str
