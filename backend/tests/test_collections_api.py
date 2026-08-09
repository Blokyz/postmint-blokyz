"""Tests for the collections registry (app.collections_registry + app.api.collections)."""

import pytest

from app.collections_registry import SlugError, slugify, validate_slug
from app.db.models import Collection, IngestJob
from app.manifests import write_atlas_manifest

CONTRACT = "0xbc4ca0eda7647a8ab7c2061c2e118a18a936bc46"


# --- slugify / validate (pure) ---


def test_slugify_basic():
    assert slugify("Good Vibes Club") == "good-vibes-club"
    assert slugify("  Bored   Apes!! ") == "bored-apes"
    assert slugify("Café Crème ☕") == "cafe-creme"
    assert slugify("A_B__C") == "a-b-c"


def test_validate_slug_rules():
    assert validate_slug("good-vibes") == "good-vibes"
    with pytest.raises(SlugError):
        validate_slug("ab")  # too short
    with pytest.raises(SlugError):
        validate_slug("Bad_Slug")  # uppercase/underscore
    with pytest.raises(SlugError):
        validate_slug("studio")  # reserved
    with pytest.raises(SlugError):
        validate_slug("-lead-hyphen")


# --- API ---


def _publish(client, **over):
    body = {"contract_address": CONTRACT, "display_name": "Good Vibes Club"}
    body.update(over)
    return client.post("/collections", json=body)


def test_publish_derives_slug(client, db):
    r = _publish(client)
    assert r.status_code == 200, r.text
    assert r.json()["slug"] == "good-vibes-club"
    assert r.json()["contract_address"] == CONTRACT
    assert r.json()["published"] is True


def test_publish_uses_ingest_chain(client, db):
    db.add(IngestJob(id="j1", contract_address=CONTRACT, chain="base", status="complete"))
    db.commit()
    r = _publish(client)
    assert r.json()["chain"] == "base"


def test_publish_explicit_slug(client, db):
    r = _publish(client, slug="gvc")
    assert r.status_code == 200
    assert r.json()["slug"] == "gvc"


def test_publish_reserved_slug_rejected(client, db):
    r = _publish(client, slug="studio")
    assert r.status_code == 400


def test_publish_duplicate_slug_conflict(client, db):
    _publish(client, slug="gvc")
    # A different contract trying to grab the same slug.
    r = client.post(
        "/collections",
        json={"contract_address": "0x" + "11" * 20, "display_name": "Other", "slug": "gvc"},
    )
    assert r.status_code == 400


def test_republish_keeps_slug_updates_name(client, db):
    _publish(client, slug="gvc", display_name="Old Name")
    r = client.post(
        "/collections",
        json={"contract_address": CONTRACT, "display_name": "New Name", "slug": "ignored-on-republish"},
    )
    assert r.status_code == 200
    assert r.json()["slug"] == "gvc"  # slug preserved
    assert r.json()["display_name"] == "New Name"
    assert db.query(Collection).count() == 1


def test_resolve_slug_and_404(client, db):
    _publish(client, slug="gvc")
    assert client.get("/collections/gvc").status_code == 200
    assert client.get("/collections/nope").status_code == 404  # doubles as availability check


def test_directory_summary_rollup(client, db):
    # An atlas manifest lets the summary roll up tiers/caps.
    write_atlas_manifest(
        CONTRACT,
        {
            "tier_structure": {"Rare": {"cap": 500, "holding_window_hours": 0}, "Mythic": {"cap": 50, "holding_window_hours": 0}},
            "tiers": [
                {"tier": "Rare", "set_rule": {"archetype": "count_of_pool", "pool": [], "count_required": 2}},
                {"tier": "Mythic", "set_rule": {"archetype": "apex_combo", "pool": [], "count_required": 3}},
            ],
        },
    )
    _publish(client, slug="gvc")
    rows = client.get("/collections").json()
    assert len(rows) == 1
    s = rows[0]
    assert s["slug"] == "gvc"
    assert s["tier_count"] == 2
    assert s["total_cap"] == 550
    assert s["total_filled"] == 0
    assert s["status"] == "live"


def test_directory_summary_with_recorded_wins(client, db):
    """Regression: the rollup crashed ('int' object is not subscriptable) for
    any collection with a WON claim after tier_fill_counts changed shape in
    the derived-window rework — no prior test had a win in the directory."""
    from app.db.models import Claim, Token, Trait

    write_atlas_manifest(
        CONTRACT,
        {
            "tier_structure": {"Rare": {"cap": 500, "holding_window_hours": 24}},
            "tiers": [
                {
                    "tier": "Rare",
                    "set_rule": {
                        "archetype": "count_of_pool",
                        "pool": [{"trait_category": "Hat", "trait_value": "Gold"}],
                        "count_required": 1,
                    },
                }
            ],
        },
    )
    wallet = "0x00000000000000000000000000000000000000a1"
    db.add(Token(contract_address=CONTRACT, token_id=1, owner_address=wallet))
    db.add(Trait(contract_address=CONTRACT, token_id=1, trait_category="Hat", trait_value="Gold"))
    db.add(
        Claim(
            contract_address=CONTRACT,
            tier="Rare",
            wallet_address=wallet,
            on_chain_tx_hash="0x" + "ab" * 32,
            slot_number=1,
        )
    )
    db.commit()
    _publish(client, slug="gvc")

    r = client.get("/collections")
    assert r.status_code == 200, r.text
    s = r.json()[0]
    assert s["total_filled"] == 1
    assert s["racers"] == 1  # the wallet still holds the qualifying set


def test_directory_hides_unpublished_by_default(client, db):
    _publish(client, slug="gvc", published=False)
    assert client.get("/collections").json() == []
    assert len(client.get("/collections?all=true").json()) == 1


# --- operator authorization (enforced only when operator_allowlist configured) ---

from eth_account import Account  # noqa: E402
from eth_account.messages import encode_defunct  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.signing import build_publish_message  # noqa: E402

_OP_KEY = "0x" + "55" * 32
_OP_ADDR = Account.from_key(_OP_KEY).address.lower()
_DISPLAY = "Good Vibes Club"


def _sign_publish(contract, slug, name, key=_OP_KEY):
    sig = Account.sign_message(
        encode_defunct(text=build_publish_message(contract, slug, name)), private_key=key
    ).signature.hex()
    return sig if sig.startswith("0x") else "0x" + sig


def test_publish_open_when_allowlist_unset(client, db):
    """Default (empty allowlist): publish works with no signature — dev behavior."""
    assert _publish(client, slug="gvc").status_code == 200


def test_publish_requires_signature_when_allowlisted(client, db, monkeypatch):
    monkeypatch.setattr(get_settings(), "operator_allowlist", _OP_ADDR)
    assert _publish(client, slug="gvc").status_code == 401  # no signature


def test_publish_accepts_operator_signature(client, db, monkeypatch):
    monkeypatch.setattr(get_settings(), "operator_allowlist", _OP_ADDR)
    sig = _sign_publish(CONTRACT, "gvc", _DISPLAY)
    r = _publish(client, slug="gvc", operator_address=_OP_ADDR, signature=sig)
    assert r.status_code == 200, r.text


def test_publish_rejects_non_operator_signature(client, db, monkeypatch):
    # Allowlist holds a different address than the (valid) signer → 403.
    monkeypatch.setattr(get_settings(), "operator_allowlist", "0x" + "de" * 20)
    sig = _sign_publish(CONTRACT, "gvc", _DISPLAY)
    r = _publish(client, slug="gvc", operator_address=_OP_ADDR, signature=sig)
    assert r.status_code == 403


def test_publish_rejects_mismatched_signature(client, db, monkeypatch):
    # Signature is for a different slug than submitted → recovered signer ≠ operator_address.
    monkeypatch.setattr(get_settings(), "operator_allowlist", _OP_ADDR)
    sig = _sign_publish(CONTRACT, "other-slug", _DISPLAY)
    r = _publish(client, slug="gvc", operator_address=_OP_ADDR, signature=sig)
    assert r.status_code == 401
