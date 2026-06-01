from datetime import datetime

from sqlalchemy import ARRAY, BigInteger, Boolean, DateTime, Index, Integer, Numeric, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Token(Base):
    __tablename__ = "tokens"

    contract_address: Mapped[str] = mapped_column(Text, primary_key=True)
    token_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    owner_address: Mapped[str | None] = mapped_column(Text)
    snapshot_block: Mapped[int | None] = mapped_column(BigInteger)


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
        # No unique constraint on (wallet, tier) — whales may win multiple slots.
        # Slot uniqueness prevents double-awarding the same numbered slot.
        Index(
            "uix_claims_contract_tier_slot",
            "contract_address", "tier", "slot_number",
            unique=True,
            postgresql_where="slot_number IS NOT NULL",
        ),
        Index("ix_claims_contract_tier_wallet", "contract_address", "tier", "wallet_address"),
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

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    contract_address: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    chain: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    progress_pct: Mapped[int] = mapped_column(Integer, default=0)
    last_cursor: Mapped[str | None] = mapped_column(Text)  # Moralis pagination cursor — enables mid-collection resume
    manifest_path: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
