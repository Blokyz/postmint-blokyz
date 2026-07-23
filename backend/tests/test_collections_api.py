"""Tests for the collections registry (app.collections_registry + app.api.collections)."""

import pytest

from app.collections_registry import SlugError, slugify, validate_slug
from app.db.models import Collection, IngestJob
from app.manifests import OUTPUT_DIR, write_atlas_manifest

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
    path = OUTPUT_DIR / f"{CONTRACT}_atlas_manifest.json"
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
    try:
        _publish(client, slug="gvc")
        rows = client.get("/collections").json()
        assert len(rows) == 1
        s = rows[0]
        assert s["slug"] == "gvc"
        assert s["tier_count"] == 2
        assert s["total_cap"] == 550
        assert s["total_filled"] == 0
        assert s["status"] == "live"
    finally:
        if path.exists():
            path.unlink()


def test_directory_hides_unpublished_by_default(client, db):
    _publish(client, slug="gvc", published=False)
    assert client.get("/collections").json() == []
    assert len(client.get("/collections?all=true").json()) == 1
