"""Tests for app.claims.windows — derived holding windows (no opt-in clock).

Status is arithmetic over `tokens.acquired_at`: the window runs from the moment
the wallet acquired its X-th qualifying token. DB-backed tests seed
`acquired_at` directly so the lazy Moralis backfill never fires (no NULLs).
"""

import datetime as dt

import pytest

from app.claims.windows import (
    STATUS_NOT_STARTED,
    STATUS_RACING,
    STATUS_READY,
    STATUS_WON,
    UnknownTier,
    derive_status,
    tier_window_seconds,
    window_status,
)
from app.db.models import Token, Trait

CONTRACT = "0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
WALLET = "0x00000000000000000000000000000000000000a1"

NOW = dt.datetime(2026, 8, 4, 12, 0, tzinfo=dt.timezone.utc)
DAY = 24 * 3600


def _manifest(window_hours=24, count_required=2, tier="Rare"):
    return {
        "tier_structure": {tier: {"cap": 500, "holding_window_hours": window_hours}},
        "tiers": [
            {
                "tier": tier,
                "set_rule": {
                    "archetype": "count_of_pool",
                    "pool": [{"trait_category": "Hat", "trait_value": "Gold"}],
                    "count_required": count_required,
                },
            }
        ],
    }


def _seed_holdings(db, acquired_ats, owner=WALLET):
    """One qualifying token per acquired_at entry (token ids 1..n)."""
    for i, ts in enumerate(acquired_ats, start=1):
        db.add(Token(contract_address=CONTRACT, token_id=i, owner_address=owner, acquired_at=ts))
        db.add(Trait(contract_address=CONTRACT, token_id=i, trait_category="Hat", trait_value="Gold"))
    db.commit()


def _ago(hours):
    return NOW - dt.timedelta(hours=hours)


# --- pure derive_status ---


def test_derive_won():
    out = derive_status(NOW, None, DAY, qualifies=True, won=True)
    assert out["status"] == STATUS_WON


def test_derive_not_qualified():
    out = derive_status(NOW, _ago(100), DAY, qualifies=False, won=False)
    assert out["status"] == STATUS_NOT_STARTED
    assert out["seconds_remaining"] is None


def test_derive_ready_long_holder():
    out = derive_status(NOW, _ago(25), DAY, qualifies=True, won=False)
    assert out["status"] == STATUS_READY
    assert out["seconds_remaining"] == 0


def test_derive_racing_fresh_buyer():
    out = derive_status(NOW, _ago(1), DAY, qualifies=True, won=False)
    assert out["status"] == STATUS_RACING
    assert out["seconds_remaining"] == 23 * 3600
    assert out["ready_at"] == (_ago(1) + dt.timedelta(seconds=DAY)).isoformat()


def test_derive_exact_boundary_is_ready():
    out = derive_status(NOW, _ago(24), DAY, qualifies=True, won=False)
    assert out["status"] == STATUS_READY


def test_derive_zero_window_instant_ready():
    """Common: qualification alone is enough — no completion time needed."""
    out = derive_status(NOW, None, 0, qualifies=True, won=False)
    assert out["status"] == STATUS_READY
    assert out["seconds_remaining"] == 0


def test_derive_unknown_completion_counts_as_now():
    """Conservative: unknown history starts the clock now, never shortens it."""
    out = derive_status(NOW, None, DAY, qualifies=True, won=False)
    assert out["status"] == STATUS_RACING
    assert out["seconds_remaining"] == DAY


def test_derive_naive_timestamp_treated_as_utc():
    naive = _ago(25).replace(tzinfo=None)
    out = derive_status(NOW, naive, DAY, qualifies=True, won=False)
    assert out["status"] == STATUS_READY


def test_tier_window_seconds():
    assert tier_window_seconds(_manifest(window_hours=24), "Rare") == DAY
    assert tier_window_seconds(_manifest(window_hours=24), "Nope") == 0
    assert tier_window_seconds(_manifest(window_hours=0), "Rare") == 0


def test_tier_window_seconds_clamps_stale_manifests():
    """Pre-change manifests carry 72-336h values — the flat rule wins in code."""
    for stale_hours in (72, 168, 336):
        assert tier_window_seconds(_manifest(window_hours=stale_hours), "Rare") == DAY


# --- DB-backed window_status ---


def test_status_long_holder_ready(db):
    _seed_holdings(db, [_ago(30), _ago(26)])
    out = window_status(db, CONTRACT, "Rare", WALLET, _manifest(), now=NOW)
    assert out["status"] == STATUS_READY
    assert out["qualifies"] is True
    # Set completed at the 2nd-oldest acquisition (26h ago).
    assert out["window_started"] == _ago(26).isoformat()


def test_status_fresh_buyer_racing(db):
    """Held one token for a month; bought the 2nd an hour ago -> 23h left."""
    _seed_holdings(db, [_ago(30 * 24), _ago(1)])
    out = window_status(db, CONTRACT, "Rare", WALLET, _manifest(), now=NOW)
    assert out["status"] == STATUS_RACING
    assert out["seconds_remaining"] == 23 * 3600
    assert out["window_started"] == _ago(1).isoformat()


def test_status_not_qualified(db):
    _seed_holdings(db, [_ago(100)])  # holds 1, needs 2
    out = window_status(db, CONTRACT, "Rare", WALLET, _manifest(), now=NOW)
    assert out["status"] == STATUS_NOT_STARTED
    assert out["qualifies"] is False
    assert out["window_started"] is None


def test_status_zero_window_instant(db):
    """Common-style tier: ready immediately on qualification, acquisition data
    never consulted (window_started stays None)."""
    _seed_holdings(db, [None])  # acquired_at NULL — must not matter
    manifest = _manifest(window_hours=0, count_required=1, tier="Common")
    out = window_status(db, CONTRACT, "Common", WALLET, manifest, now=NOW)
    assert out["status"] == STATUS_READY
    assert out["window_started"] is None


def test_status_sell_and_rebuy_restamps(db):
    """After a rebuy the clock runs from the new acquired_at (poller restamped)."""
    _seed_holdings(db, [_ago(26), _ago(25)])
    out = window_status(db, CONTRACT, "Rare", WALLET, _manifest(), now=NOW)
    assert out["status"] == STATUS_READY

    # Token 2 "sold and rebought" 2h ago — poller rewrote acquired_at.
    db.get(Token, (CONTRACT, 2)).acquired_at = _ago(2)
    db.commit()
    out = window_status(db, CONTRACT, "Rare", WALLET, _manifest(), now=NOW)
    assert out["status"] == STATUS_RACING
    assert out["seconds_remaining"] == 22 * 3600


def test_status_extra_tokens_use_xth_oldest(db):
    """Holding 3 when 2 are needed: the 2nd-oldest acquisition starts the clock
    (the newest token doesn't delay an already-complete set)."""
    _seed_holdings(db, [_ago(50), _ago(40), _ago(1)])
    out = window_status(db, CONTRACT, "Rare", WALLET, _manifest(), now=NOW)
    assert out["status"] == STATUS_READY
    assert out["window_started"] == _ago(40).isoformat()


def test_status_unknown_tier_raises(db):
    with pytest.raises(UnknownTier):
        window_status(db, CONTRACT, "Nope", WALLET, _manifest(), now=NOW)


def test_status_backfill_triggered_for_null_acquired_at(db, monkeypatch):
    """A qualifying wallet with unstamped tokens triggers the lazy backfill."""
    from app.claims import acquisitions as amod
    from app.ingestion.moralis_client import TransfersPage

    _seed_holdings(db, [None, None])

    def fake(wallet, contract, chain, api_key, cursor=None):
        return TransfersPage(
            transfers=[
                {
                    "token_id": tid,
                    "from_address": "0x00000000000000000000000000000000000000ff",
                    "to_address": WALLET,
                    "block_number": 100,
                    "log_index": 0,
                    "tx_hash": "0x" + "aa" * 32,
                    "acquired_at": _ago(30),
                }
                for tid in (1, 2)
            ],
            next_cursor=None,
        )

    monkeypatch.setattr(amod, "fetch_wallet_transfers_page", fake)
    out = window_status(db, CONTRACT, "Rare", WALLET, _manifest(), now=NOW)
    db.commit()
    assert out["status"] == STATUS_READY
    assert db.get(Token, (CONTRACT, 1)).acquired_at == _ago(30)
