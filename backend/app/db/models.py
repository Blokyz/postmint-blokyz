from datetime import datetime

from sqlalchemy import ARRAY, BigInteger, Boolean, DateTime, Index, Integer, Numeric, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Token(Base):
    __tablename__ = "tokens"

    contract_address: Mapped[str] = mapped_column(Text, primary_key=True)
    token_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    owner_address: Mapped[str | None] = mapped_column(Text)
    snapshot_block: Mapped[int | None] = mapped_column(BigInteger)
    # When the CURRENT owner received this token (Transfer-event block timestamp).
    # NULL = unknown (pre-existing ingest data) — triggers the lazy per-wallet
    # backfill in claims/acquisitions.py. Must be cleared (not carried over) on
    # any ownership change whose transfer lacks a timestamp.
    acquired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Trait(Base):
    __tablename__ = "traits"
    __table_args__ = (
        Index("ix_traits_contract_category_value", "contract_address", "trait_category", "trait_value"),
    )

    contract_address: Mapped[str] = mapped_column(Text, primary_key=True)
    token_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    trait_category: Mapped[str] = mapped_column(Text, primary_key=True)
    trait_value: Mapped[str] = mapped_column(Text, nullable=False)


class Sale(Base):
    __tablename__ = "sales"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contract_address: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    token_id: Mapped[int] = mapped_column(Integer, nullable=False)
    sale_price_eth: Mapped[float] = mapped_column(Numeric(18, 8), nullable=False)
    seller_address: Mapped[str | None] = mapped_column(Text)
    buyer_address: Mapped[str | None] = mapped_column(Text)
    marketplace: Mapped[str | None] = mapped_column(Text)
    tx_hash: Mapped[str | None] = mapped_column(Text, unique=True)
    sold_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    wash_trade_flag: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class Claim(Base):
    __tablename__ = "claims"
    __table_args__ = (
        # No unique constraint on (wallet, tier) — whales may win multiple slots,
        # but each win needs a DISJOINT set: `qualifying_tokens` on won rows are
        # consumed per tier (eligibility.consumed_token_ids, 2026-08-05).
        # Slot uniqueness prevents double-awarding the same numbered slot.
        Index(
            "uix_claims_contract_tier_slot",
            "contract_address", "tier", "slot_number",
            unique=True,
            postgresql_where="slot_number IS NOT NULL",
        ),
        Index("ix_claims_contract_tier_wallet", "contract_address", "tier", "wallet_address"),
        # At most one active (not-yet-won) claim row per (contract, tier, wallet) —
        # rows are created at /claim/sign time (windows are derived, no submit
        # step); this makes a concurrent first-sign race a clean IntegrityError.
        # A wallet may still record a fresh row for another slot AFTER winning
        # one (its won row has on_chain_tx_hash set, so it's excluded here),
        # preserving the no-whale-cap rule.
        Index(
            "uix_claims_one_active_window",
            "contract_address", "tier", "wallet_address",
            unique=True,
            postgresql_where="on_chain_tx_hash IS NULL",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contract_address: Mapped[str] = mapped_column(Text, nullable=False)
    tier: Mapped[str] = mapped_column(Text, nullable=False)
    wallet_address: Mapped[str] = mapped_column(Text, nullable=False)
    window_started: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    window_completed: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    slot_number: Mapped[int | None] = mapped_column(Integer)
    qualifying_tokens: Mapped[list[int] | None] = mapped_column(ARRAY(Integer))
    on_chain_tx_hash: Mapped[str | None] = mapped_column(Text)


class IngestJob(Base):
    __tablename__ = "ingest_jobs"
    __table_args__ = (
        # At most one active (not failed/complete) job per contract — closes the
        # /ingest check-then-insert race under concurrent requests. The endpoint
        # treats a violation as "someone else just queued it" and resumes.
        Index(
            "uix_ingest_jobs_one_active_per_contract",
            "contract_address",
            unique=True,
            postgresql_where="status NOT IN ('failed', 'complete')",
        ),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    contract_address: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    chain: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    # Coarse pipeline stage for the ingest UI: queued | fetching_nfts |
    # fetching_sales | scoring | done | failed. progress_pct tracks NFT paging only.
    phase: Mapped[str] = mapped_column(Text, nullable=False, default="queued", server_default="queued")
    progress_pct: Mapped[int] = mapped_column(Integer, default=0)
    last_cursor: Mapped[str | None] = mapped_column(Text)  # Moralis pagination cursor — enables mid-collection resume
    manifest_path: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TransferSync(Base):
    """Resumable high-water mark for the holding-window transfer poller — one row
    per contract records the last processed block + Moralis cursor so each poll
    only scans new ownership changes."""

    __tablename__ = "transfer_sync"

    contract_address: Mapped[str] = mapped_column(Text, primary_key=True)
    last_block: Mapped[int | None] = mapped_column(BigInteger)
    cursor: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Season(Base):
    """A deployed `SetClaimManager` (one per project per season). Recorded off-chain
    (from the factory's `SeasonDeployed` event / the deploy script) so the backend
    can bind a claim attestation to the correct season contract. `manager_address`
    is the on-chain `SetClaimManager` address the attestation's digest binds to."""

    __tablename__ = "seasons"
    __table_args__ = (Index("ix_seasons_contract", "contract_address"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contract_address: Mapped[str] = mapped_column(Text, nullable=False)
    manager_address: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    atlas_hash: Mapped[str | None] = mapped_column(Text)
    chain_id: Mapped[int] = mapped_column(Integer, nullable=False)
    deployed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Collection(Base):
    """A published tenant — maps a URL-safe `slug` to a collection contract so the
    holder app can be scoped by `/c/{slug}` instead of a raw address. Created at the
    operator's "Publish" step (after the atlas is generated). One row per contract."""

    __tablename__ = "collections"

    slug: Mapped[str] = mapped_column(Text, primary_key=True)
    contract_address: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    chain: Mapped[str] = mapped_column(Text, nullable=False, default="eth")
    image_url: Mapped[str | None] = mapped_column(Text)
    published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ClaimNonce(Base):
    """A single-use nonce issued by `/claim/sign` to authorize exactly one on-chain
    `SetClaimManager.claim`. The row `id` IS the nonce passed to the contract —
    globally unique, so per-season unique (each season is a separate contract with
    its own `nonceUsed` mapping). Doubles as an audit log of issued attestations.

    A wallet may be issued multiple nonces (it may legitimately win multiple slots —
    the no-whale-cap rule); the contract's cap + per-nonce single-use are the real
    limits, so this table never needs a per-wallet uniqueness constraint."""

    __tablename__ = "claim_nonces"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    season_id: Mapped[int] = mapped_column(Integer, nullable=False)
    contract_address: Mapped[str] = mapped_column(Text, nullable=False)
    tier: Mapped[str] = mapped_column(Text, nullable=False)
    wallet_address: Mapped[str] = mapped_column(Text, nullable=False)
    manager_address: Mapped[str] = mapped_column(Text, nullable=False)
    expiry: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Manifest(Base):
    """Ranking + atlas manifests, stored in the DB instead of on local disk so the
    API and Celery worker share one source of truth and manifests survive a
    deploy (Render/containers have an ephemeral filesystem). One row per
    (contract, kind); `kind` is 'ranking' or 'atlas'. The JSON body is the exact
    manifest dict — the on-chain-locked hash is computed over it unchanged."""

    __tablename__ = "manifests"

    contract_address: Mapped[str] = mapped_column(Text, primary_key=True)
    kind: Mapped[str] = mapped_column(Text, primary_key=True)  # 'ranking' | 'atlas'
    data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
