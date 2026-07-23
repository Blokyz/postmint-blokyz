"""Tests for app.claims.seasons — season registry + nonce allocation (DB-backed)."""

from app.claims.seasons import allocate_nonce, latest_season, record_season
from app.db.models import ClaimNonce, Season

CONTRACT = "0xbc4ca0eda7647a8ab7c2061c2e118a18a936bc46"
MGR_A = "0x1111111111111111111111111111111111111111"
MGR_B = "0x2222222222222222222222222222222222222222"


def test_record_and_latest_season(db):
    s = record_season(db, CONTRACT, MGR_A, chain_id=84532, atlas_hash="0xabc")
    db.commit()
    assert s.contract_address == CONTRACT
    assert s.manager_address == MGR_A
    assert latest_season(db, CONTRACT).manager_address == MGR_A


def test_record_season_idempotent_on_manager(db):
    record_season(db, CONTRACT, MGR_A, chain_id=84532)
    db.commit()
    # Re-register the same manager with a fresh atlas hash — updates, no duplicate.
    again = record_season(db, CONTRACT, MGR_A.upper(), chain_id=84532, atlas_hash="0xnew")
    db.commit()
    assert again.atlas_hash == "0xnew"
    assert db.query(Season).count() == 1


def test_latest_season_picks_newest(db):
    record_season(db, CONTRACT, MGR_A, chain_id=84532)
    record_season(db, CONTRACT, MGR_B, chain_id=84532)
    db.commit()
    assert latest_season(db, CONTRACT).manager_address == MGR_B


def test_latest_season_none_when_unregistered(db):
    assert latest_season(db, CONTRACT) is None


def test_allocate_nonce_unique_and_increasing(db):
    season = record_season(db, CONTRACT, MGR_A, chain_id=84532)
    db.commit()
    n1 = allocate_nonce(db, season, "Rare", "0x00000000000000000000000000000000000000a1", expiry=123)
    n2 = allocate_nonce(db, season, "Rare", "0x00000000000000000000000000000000000000a1", expiry=456)
    db.commit()
    assert n2 > n1
    assert db.query(ClaimNonce).count() == 2
    row = db.get(ClaimNonce, n1)
    assert row.manager_address == MGR_A
    assert row.expiry == 123
