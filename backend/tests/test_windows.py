"""Tests for app.claims.windows.

`test_derive_*` / `test_window_seconds*` are pure (no DB) and always run. The
`db`-fixtured tests exercise submit/status/reset against the claims table.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.claims.windows import (
    NotQualified,
    UnknownTier,
    derive_status,
    reset_if_unqualified,
    submit_window,
    tier_window_seconds,
    window_status,
)
from app.db.models import Claim, Token, Trait

CONTRACT = "0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
WALLET = "0x00000000000000000000000000000000000000a1"
NOW = datetime(2026, 7, 13, 12, 0, 0, tzinfo=timezone.utc)


def _manifest(window_hours=72, count_required=2, pool=(("Hat", "Gold"),), tier="Rare"):
    return {
        "tier_structure": {tier: {"cap": 500, "holding_window_hours": window_hours}},
        "tiers": [
            {
                "tier": tier,
                "set_rule": {
                    "archetype": "count_of_pool",
                    "pool": [{"trait_category": c, "trait_value": v} for c, v in pool],
                    "count_required": count_required,
                },
            }
        ],
    }


# --- pure window-state math ---


def test_window_seconds_from_manifest():
    assert tier_window_seconds(_manifest(window_hours=72), "Rare") == 72 * 3600
    assert tier_window_seconds(_manifest(window_hours=0), "Rare") == 0
    assert tier_window_seconds(_manifest(), "Missing") == 0


def test_derive_not_started():
    assert derive_status(NOW, None, 3600, True, False)["status"] == "not_started"


def test_derive_won_short_circuits():
    # won even if window_started is None / not qualifying
    assert derive_status(NOW, None, 3600, False, True)["status"] == "won"


def test_derive_reset_when_not_qualifying():
    started = NOW - timedelta(hours=1)
    out = derive_status(NOW, started, 3600, False, False)
    assert out["status"] == "reset"
    assert out["seconds_remaining"] is None


def test_derive_racing():
    started = NOW - timedelta(minutes=30)
    out = derive_status(NOW, started, 3600, True, False)  # 1h window, 30m elapsed
    assert out["status"] == "racing"
    assert out["seconds_remaining"] == 1800


def test_derive_ready_at_exact_boundary():
    started = NOW - timedelta(seconds=3600)
    out = derive_status(NOW, started, 3600, True, False)
    assert out["status"] == "ready"
    assert out["seconds_remaining"] == 0


def test_derive_ready_past_boundary():
    started = NOW - timedelta(hours=5)
    out = derive_status(NOW, started, 3600, True, False)
    assert out["status"] == "ready"


def test_derive_naive_started_treated_as_utc():
    started = (NOW - timedelta(minutes=30)).replace(tzinfo=None)
    out = derive_status(NOW, started, 3600, True, False)
    assert out["status"] == "racing"


# --- DB-backed ---


def _seed_holdings(db, count, pool_value="Gold"):
    for token_id in range(1, count + 1):
        db.add(Token(contract_address=CONTRACT, token_id=token_id, owner_address=WALLET))
        db.add(Trait(contract_address=CONTRACT, token_id=token_id, trait_category="Hat", trait_value=pool_value))
    db.commit()


def test_submit_window_starts_clock(db):
    _seed_holdings(db, 2)
    out = submit_window(db, CONTRACT, "Rare", WALLET, _manifest(), now=NOW)
    db.commit()
    assert out["status"] == "racing"
    assert out["window_seconds"] == 72 * 3600
    row = db.query(Claim).one()
    assert row.window_started is not None
    assert sorted(row.qualifying_tokens) == [1, 2]


def test_submit_window_rejects_unqualified(db):
    _seed_holdings(db, 1)  # need 2
    with pytest.raises(NotQualified):
        submit_window(db, CONTRACT, "Rare", WALLET, _manifest(), now=NOW)


def test_submit_window_unknown_tier(db):
    _seed_holdings(db, 2)
    with pytest.raises(UnknownTier):
        submit_window(db, CONTRACT, "Nope", WALLET, _manifest(), now=NOW)


def test_submit_window_idempotent_does_not_restart(db):
    _seed_holdings(db, 2)
    submit_window(db, CONTRACT, "Rare", WALLET, _manifest(), now=NOW)
    db.commit()
    first = db.query(Claim).one().window_started

    later = NOW + timedelta(hours=1)
    submit_window(db, CONTRACT, "Rare", WALLET, _manifest(), now=later)
    db.commit()
    assert db.query(Claim).one().window_started == first  # clock not restarted
    assert db.query(Claim).count() == 1


def test_window_status_ready_after_elapsed(db):
    _seed_holdings(db, 2)
    submit_window(db, CONTRACT, "Rare", WALLET, _manifest(window_hours=72), now=NOW)
    db.commit()
    later = NOW + timedelta(hours=72)
    out = window_status(db, CONTRACT, "Rare", WALLET, _manifest(window_hours=72), now=later)
    assert out["status"] == "ready"
    assert out["seconds_remaining"] == 0


def test_window_status_none_when_not_submitted(db):
    _seed_holdings(db, 2)
    out = window_status(db, CONTRACT, "Rare", WALLET, _manifest(), now=NOW)
    assert out["status"] == "not_started"


def test_reset_if_unqualified_clears_dropped_window(db):
    _seed_holdings(db, 2)
    submit_window(db, CONTRACT, "Rare", WALLET, _manifest(), now=NOW)
    db.commit()

    # Simulate an out-transfer: wallet now holds only 1 (below X=2).
    db.query(Token).filter(Token.token_id == 2).update({"owner_address": "0x00000000000000000000000000000000000000ff"})
    db.commit()

    reset = reset_if_unqualified(db, CONTRACT, WALLET, _manifest())
    db.commit()
    assert reset == ["Rare"]
    row = db.query(Claim).one()
    assert row.window_started is None  # window cleared, opt-in row kept
    assert row.qualifying_tokens is None


def test_reset_if_unqualified_keeps_window_above_x(db):
    _seed_holdings(db, 3)  # X=2, holds 3
    submit_window(db, CONTRACT, "Rare", WALLET, _manifest(count_required=2), now=NOW)
    db.commit()

    # Transfer one out — still holds 2 >= X, window must survive (reset rule).
    db.query(Token).filter(Token.token_id == 3).update({"owner_address": "0x00000000000000000000000000000000000000ff"})
    db.commit()

    reset = reset_if_unqualified(db, CONTRACT, WALLET, _manifest(count_required=2))
    db.commit()
    assert reset == []
    assert db.query(Claim).one().window_started is not None


def test_resubmit_after_reset_restarts(db):
    _seed_holdings(db, 2)
    submit_window(db, CONTRACT, "Rare", WALLET, _manifest(), now=NOW)
    db.commit()
    # Drop below X and reset.
    db.query(Token).filter(Token.token_id == 2).update({"owner_address": "0x00000000000000000000000000000000000000ff"})
    db.commit()
    reset_if_unqualified(db, CONTRACT, WALLET, _manifest())
    db.commit()

    # Re-acquire and re-submit — a new window starts, reusing the same row.
    db.query(Token).filter(Token.token_id == 2).update({"owner_address": WALLET})
    db.commit()
    restart = NOW + timedelta(days=1)
    out = submit_window(db, CONTRACT, "Rare", WALLET, _manifest(), now=restart)
    db.commit()
    assert out["status"] == "racing"
    row = db.query(Claim).one()
    assert row.window_started.replace(tzinfo=timezone.utc) == restart
    assert db.query(Claim).count() == 1
