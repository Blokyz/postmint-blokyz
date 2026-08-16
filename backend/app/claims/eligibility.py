"""Per-wallet, per-tier eligibility evaluation (PROJECT_MASTER §11).

Given an approved atlas manifest tier (its `set_rule`) and the current DB
ownership snapshot, decide whether a wallet holds the qualifying set and by how
much. The pure `tier_progress` math is separated from the DB queries so it can be
unit-tested without Postgres.

Qualification per archetype:
- ``count_of_pool`` / ``apex_combo`` — hold >= `count_required` distinct tokens,
  each carrying at least one trait in `set_rule.pool`.
- ``one_of_each`` — hold >= 1 token for *each* trait in `set_rule.trait_values`
  (no default tier uses this since 2026-06-30, but it's handled defensively).

Set consumption (decided 2026-08-05): a token that backed a WON claim in a tier
is spent for that tier — it can never back another claim there, regardless of
who holds it now (blocks both whale re-claims with the same set and
claim→sell→rebuyer recycling). The same token remains usable in OTHER tiers
(cross-tier reuse is deliberate). Whales may still win multiple slots per tier,
but each win needs a fully disjoint set.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from app.atlas.pools import excluded_token_ids_subq
from app.db.models import Claim, Token, Trait

Pool = list[tuple[str, str]]


@dataclass
class TierEligibility:
    tier: str
    archetype: str
    count_required: int
    held_count: int
    qualifying_token_ids: list[int] = field(default_factory=list)
    qualifies: bool = False
    progress_pct: float = 0.0
    needed: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def tier_progress(held_count: int, count_required: int) -> tuple[bool, float, int]:
    """Pure §11 progress math: ``(qualifies, progress_pct, needed)``.

    A tier with ``count_required <= 0`` (e.g. an empty/`none` band) can never be
    qualified for.
    """
    if count_required <= 0:
        return False, 0.0, 0
    qualifies = held_count >= count_required
    progress_pct = min(100.0, held_count / count_required * 100.0)
    needed = max(0, count_required - held_count)
    return qualifies, round(progress_pct, 2), needed


def _pool_pairs(pool_dicts: list[dict]) -> Pool:
    return [(p["trait_category"], p["trait_value"]) for p in pool_dicts]


def tier_pool_pairs(tier_entry: dict) -> Pool:
    """The qualifying trait pairs for a tier entry (any archetype)."""
    rule = tier_entry.get("set_rule") or {}
    if rule.get("archetype") in ("count_of_pool", "apex_combo"):
        return _pool_pairs(rule.get("pool") or [])
    if rule.get("archetype") == "one_of_each":
        return [(tv["trait_category"], tv["trait_value"]) for tv in rule.get("trait_values") or []]
    return []


def tier_exclude_pairs(tier_entry: dict) -> Pool:
    """Rarer-band trait pairs excluded from a tier (exclusive tier bands,
    Option A 2026-08-13). Tokens carrying any of these belong to a rarer tier.
    Old manifests without `set_rule.pool_exclude` return [] — old behavior."""
    rule = tier_entry.get("set_rule") or {}
    return _pool_pairs(rule.get("pool_exclude") or [])


def consumed_token_ids(db: Session, contract: str, tier: str) -> set[int]:
    """Token ids already spent on a WON claim in this tier — by ANY wallet, so
    consumption follows the token across transfers. Only confirmed wins consume
    (`on_chain_tx_hash` set); an unconfirmed sign-created row does not."""
    rows = db.execute(
        select(Claim.qualifying_tokens)
        .where(Claim.contract_address == contract.lower())
        .where(Claim.tier == tier)
        .where(Claim.on_chain_tx_hash.is_not(None))
    ).all()
    used: set[int] = set()
    for (ids,) in rows:
        used.update(ids or [])
    return used


def matching_token_ids(
    db: Session, contract: str, wallet: str, pool: Pool, exclude_pool: Pool | None = None
) -> list[int]:
    """Token ids currently owned by `wallet` that carry at least one trait in `pool`
    (and, when `exclude_pool` is given, no trait in it — exclusive tier bands).

    Contract + owner are stored lowercased (see ingestion), so inputs are lowered
    to match. Returns a sorted, de-duplicated list.
    """
    if not pool:
        return []
    stmt = (
        select(Trait.token_id)
        .distinct()
        .join(
            Token,
            (Token.contract_address == Trait.contract_address) & (Token.token_id == Trait.token_id),
        )
        .where(Token.contract_address == contract.lower())
        .where(Token.owner_address == wallet.lower())
        .where(tuple_(Trait.trait_category, Trait.trait_value).in_(pool))
    )
    if exclude_pool:
        stmt = stmt.where(
            Trait.token_id.not_in(excluded_token_ids_subq(contract.lower(), exclude_pool))
        )
    rows = db.execute(stmt).all()
    return sorted(r[0] for r in rows)


def evaluate_tier(db: Session, contract: str, wallet: str, tier_entry: dict) -> TierEligibility:
    """Evaluate one atlas tier entry for a wallet."""
    rule = tier_entry.get("set_rule") or {}
    archetype = rule.get("archetype", "none")
    tier = tier_entry.get("tier", "")

    if archetype in ("count_of_pool", "apex_combo"):
        pool = _pool_pairs(rule.get("pool") or [])
        count_required = int(rule.get("count_required") or 0)
        token_ids = matching_token_ids(
            db, contract, wallet, pool, exclude_pool=tier_exclude_pairs(tier_entry)
        )
        used = consumed_token_ids(db, contract, tier)
        if used:
            token_ids = [t for t in token_ids if t not in used]
        held = len(token_ids)
        qualifies, progress, needed = tier_progress(held, count_required)
        return TierEligibility(
            tier, archetype, count_required, held, token_ids, qualifies, progress, needed
        )

    if archetype == "one_of_each":
        trait_values = rule.get("trait_values") or []
        count_required = len(trait_values)
        used = consumed_token_ids(db, contract, tier)
        held = 0
        token_ids: set[int] = set()
        for tv in trait_values:
            ids = [
                t
                for t in matching_token_ids(
                    db, contract, wallet, [(tv["trait_category"], tv["trait_value"])]
                )
                if t not in used
            ]
            if ids:
                held += 1
                token_ids.update(ids)
        qualifies, progress, needed = tier_progress(held, count_required)
        return TierEligibility(
            tier, archetype, count_required, held, sorted(token_ids), qualifies, progress, needed
        )

    # "none" / empty band / unknown archetype — never qualifiable.
    return TierEligibility(tier, archetype, 0, 0, [], False, 0.0, 0)


def evaluate_wallet(db: Session, contract: str, wallet: str, atlas_manifest: dict) -> list[TierEligibility]:
    """Evaluate every tier in the atlas manifest for a wallet (powers /eligibility)."""
    return [evaluate_tier(db, contract, wallet, t) for t in atlas_manifest.get("tiers", [])]


def find_tier_entry(atlas_manifest: dict, tier: str) -> dict | None:
    """Look up a tier entry by name in the atlas manifest."""
    for t in atlas_manifest.get("tiers", []):
        if t.get("tier") == tier:
            return t
    return None
