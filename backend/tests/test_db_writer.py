"""Integration tests for batch upsert helpers — require a live postmint_test DB."""

from sqlalchemy import func, select

from app.db.models import Trait, Token
from app.ingestion.db_writer import upsert_tokens, upsert_traits

_CONTRACT = "0xdeadbeef00000000000000000000000000000001"
_CONTRACT2 = "0xdeadbeef00000000000000000000000000000002"


def _token(token_id: int, owner: str = "0xabc", block: int = 1000, contract: str = _CONTRACT) -> dict:
    return {
        "contract_address": contract,
        "token_id": token_id,
        "owner_address": owner,
        "snapshot_block": block,
    }


def _trait(token_id: int, category: str = "Fur", value: str = "Gold", contract: str = _CONTRACT) -> dict:
    return {
        "contract_address": contract,
        "token_id": token_id,
        "trait_category": category,
        "trait_value": value,
    }


# ── Token upserts ──────────────────────────────────────────────────────────────

def test_upsert_tokens_inserts_row(db):
    upsert_tokens(db, [_token(1)])
    row = db.get(Token, (_CONTRACT, 1))
    assert row is not None
    assert row.owner_address == "0xabc"
    assert row.snapshot_block == 1000


def test_upsert_tokens_updates_owner_on_conflict(db):
    upsert_tokens(db, [_token(2, owner="0xold", block=500)])
    upsert_tokens(db, [_token(2, owner="0xnew", block=501)])
    row = db.get(Token, (_CONTRACT, 2))
    assert row.owner_address == "0xnew"
    assert row.snapshot_block == 501


def test_upsert_tokens_does_not_duplicate(db):
    upsert_tokens(db, [_token(3)])
    upsert_tokens(db, [_token(3)])
    count = db.scalar(
        select(func.count()).select_from(Token)
        .where(Token.contract_address == _CONTRACT, Token.token_id == 3)
    )
    assert count == 1


def test_upsert_tokens_empty_list_is_noop(db):
    upsert_tokens(db, [])
    count = db.scalar(select(func.count()).select_from(Token))
    assert count == 0


def test_upsert_tokens_batch_inserts(db):
    tokens = [_token(i) for i in range(10, 25)]
    upsert_tokens(db, tokens)
    count = db.scalar(
        select(func.count()).select_from(Token)
        .where(Token.contract_address == _CONTRACT)
    )
    assert count == 15


def test_upsert_tokens_multiple_contracts(db):
    upsert_tokens(db, [_token(1, contract=_CONTRACT), _token(1, contract=_CONTRACT2)])
    for contract in [_CONTRACT, _CONTRACT2]:
        assert db.get(Token, (contract, 1)) is not None


def test_upsert_tokens_null_owner_stored(db):
    upsert_tokens(db, [{"contract_address": _CONTRACT, "token_id": 99, "owner_address": None, "snapshot_block": None}])
    row = db.get(Token, (_CONTRACT, 99))
    assert row.owner_address is None


# ── Trait upserts ──────────────────────────────────────────────────────────────

def _seed_token(db, token_id: int, contract: str = _CONTRACT):
    upsert_tokens(db, [_token(token_id, contract=contract)])


def test_upsert_traits_inserts_row(db):
    _seed_token(db, 1)
    upsert_traits(db, [_trait(1)])
    row = db.get(Trait, (_CONTRACT, 1, "Fur"))
    assert row is not None
    assert row.trait_value == "Gold"


def test_upsert_traits_updates_value_on_conflict(db):
    _seed_token(db, 2)
    upsert_traits(db, [_trait(2, value="Old")])
    upsert_traits(db, [_trait(2, value="New")])
    row = db.get(Trait, (_CONTRACT, 2, "Fur"))
    assert row.trait_value == "New"


def test_upsert_traits_does_not_duplicate(db):
    _seed_token(db, 3)
    upsert_traits(db, [_trait(3)])
    upsert_traits(db, [_trait(3)])
    count = db.scalar(
        select(func.count()).select_from(Trait)
        .where(Trait.contract_address == _CONTRACT, Trait.token_id == 3, Trait.trait_category == "Fur")
    )
    assert count == 1


def test_upsert_traits_multiple_categories(db):
    _seed_token(db, 4)
    upsert_traits(db, [
        _trait(4, category="Fur", value="Gold"),
        _trait(4, category="Background", value="Blue"),
        _trait(4, category="Eyes", value="Laser"),
    ])
    count = db.scalar(
        select(func.count()).select_from(Trait)
        .where(Trait.contract_address == _CONTRACT, Trait.token_id == 4)
    )
    assert count == 3


def test_upsert_traits_empty_list_is_noop(db):
    upsert_traits(db, [])
    count = db.scalar(select(func.count()).select_from(Trait))
    assert count == 0
