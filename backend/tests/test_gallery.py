"""Tests for the public tier gallery (GET /gallery/{contract}/{tier}) and the
OpenSea listings client parse (app.opensea).

The gallery shows the NFTs qualifying for a tier on the standings Tiers tab:
pool membership honors exclusive bands (`pool_exclude`), OpenSea listings are
intersected when the key + a mainnet chain are present (listed-cheapest first),
and everything degrades to a DB-only gallery otherwise.
"""

import pytest

from app import opensea
from app.api import claims as claims_mod
from app.db.models import Token, Trait
from app.manifests import write_atlas_manifest
from app.opensea import _parse_best_listings, asset_url, opensea_chain

CONTRACT = "0xbc4ca0eda7647a8ab7c2061c2e118a18a936bc46"
TIER = "Common"
RARE_TIER = "Rare"


def _manifest(with_exclude=False):
    common_rule = {
        "archetype": "count_of_pool",
        "pool": [{"trait_category": "Hat", "trait_value": "Gold"}],
        "count_required": 1,
    }
    if with_exclude:
        common_rule["pool_exclude"] = [{"trait_category": "Eyes", "trait_value": "Laser"}]
    return {
        "tier_structure": {},
        "tiers": [
            {
                "tier": RARE_TIER,
                "set_rule": {
                    "archetype": "count_of_pool",
                    "pool": [{"trait_category": "Eyes", "trait_value": "Laser"}],
                    "count_required": 1,
                },
            },
            {"tier": TIER, "set_rule": common_rule},
        ],
    }


def _seed_pool(db, ids=(1, 2, 3), value="Gold", image=True):
    for tid in ids:
        db.add(Token(
            contract_address=CONTRACT, token_id=tid, owner_address="0xabc",
            image_url=f"https://img/{tid}.png" if image else None,
        ))
        db.add(Trait(contract_address=CONTRACT, token_id=tid, trait_category="Hat", trait_value=value))
    db.commit()


@pytest.fixture(autouse=True)
def _fresh_opensea_caches():
    opensea._slug_cache.clear()
    opensea._listings_cache.clear()


def test_gallery_returns_pool_tokens_with_images(client, db):
    write_atlas_manifest(CONTRACT, _manifest())
    _seed_pool(db)
    r = client.get(f"/gallery/{CONTRACT}/{TIER}")
    assert r.status_code == 200
    data = r.json()
    assert data["pool_size"] == 3
    assert data["listings_supported"] is False  # no OPENSEA_API_KEY in tests
    assert data["listed_count"] == 0
    assert [t["token_id"] for t in data["tokens"]] == [1, 2, 3]
    assert data["tokens"][0]["image_url"] == "https://img/1.png"
    assert data["tokens"][0]["price_eth"] is None
    assert data["tokens"][0]["traits"] == [{"trait_category": "Hat", "trait_value": "Gold"}]
    # No collection row -> chain defaults to "eth" -> ethereum asset link.
    assert data["tokens"][0]["opensea_url"] == f"https://opensea.io/assets/ethereum/{CONTRACT}/1"


def test_gallery_honors_pool_exclude(client, db):
    """Exclusive bands: a token carrying a rarer-band trait leaves the Common pool."""
    write_atlas_manifest(CONTRACT, _manifest(with_exclude=True))
    _seed_pool(db, ids=(1, 2))
    # Token 9 carries Hat=Gold AND the rarer Eyes=Laser -> Rare only, never Common.
    db.add(Token(contract_address=CONTRACT, token_id=9, owner_address="0xabc"))
    db.add(Trait(contract_address=CONTRACT, token_id=9, trait_category="Hat", trait_value="Gold"))
    db.add(Trait(contract_address=CONTRACT, token_id=9, trait_category="Eyes", trait_value="Laser"))
    db.commit()
    data = client.get(f"/gallery/{CONTRACT}/{TIER}").json()
    assert data["pool_size"] == 2
    assert [t["token_id"] for t in data["tokens"]] == [1, 2]
    rare = client.get(f"/gallery/{CONTRACT}/{RARE_TIER}").json()
    assert [t["token_id"] for t in rare["tokens"]] == [9]


def test_gallery_limit_caps_tokens(client, db):
    write_atlas_manifest(CONTRACT, _manifest())
    _seed_pool(db, ids=tuple(range(1, 11)))
    r = client.get(f"/gallery/{CONTRACT}/{TIER}?limit=4")
    data = r.json()
    assert data["pool_size"] == 10
    assert len(data["tokens"]) == 4


def test_gallery_offset_pages_through_pool(client, db):
    write_atlas_manifest(CONTRACT, _manifest())
    _seed_pool(db, ids=tuple(range(1, 11)))
    page2 = client.get(f"/gallery/{CONTRACT}/{TIER}?limit=4&offset=4").json()
    assert [t["token_id"] for t in page2["tokens"]] == [5, 6, 7, 8]
    tail = client.get(f"/gallery/{CONTRACT}/{TIER}?limit=4&offset=8").json()
    assert [t["token_id"] for t in tail["tokens"]] == [9, 10]


def test_gallery_unknown_tier_404(client, db):
    write_atlas_manifest(CONTRACT, _manifest())
    assert client.get(f"/gallery/{CONTRACT}/Nope").status_code == 404


def test_gallery_accepts_slug_style_tier_names(client, db):
    """URLs use hyphenated lowercase tiers ('super-rare'); exact names still work."""
    manifest = _manifest()
    manifest["tiers"].append({
        "tier": "Super Rare",
        "set_rule": {
            "archetype": "count_of_pool",
            "pool": [{"trait_category": "Fur", "trait_value": "Gold"}],
            "count_required": 1,
        },
    })
    write_atlas_manifest(CONTRACT, manifest)
    r = client.get(f"/gallery/{CONTRACT}/super-rare")
    assert r.status_code == 200
    assert r.json()["tier"] == "Super Rare"  # canonical name echoed back
    assert client.get(f"/gallery/{CONTRACT}/Super Rare").status_code == 200
    assert client.get(f"/gallery/{CONTRACT}/common").status_code == 200


def test_gallery_404_without_manifest(client):
    assert client.get(f"/gallery/{CONTRACT}/{TIER}").status_code == 404


def test_gallery_listed_tokens_first_cheapest_sorted(client, db, monkeypatch):
    write_atlas_manifest(CONTRACT, _manifest())
    _seed_pool(db, ids=(1, 2, 3, 4))
    monkeypatch.setattr(claims_mod.settings, "opensea_api_key", "test-key")
    # Token 99 is listed but not in the pool — must not appear.
    monkeypatch.setattr(
        claims_mod.opensea, "listed_prices", lambda c, ch: {3: 0.5, 1: 0.2, 99: 0.01}
    )
    data = client.get(f"/gallery/{CONTRACT}/{TIER}").json()
    assert data["listings_supported"] is True
    assert data["listed_count"] == 2
    ids = [t["token_id"] for t in data["tokens"]]
    assert ids[:2] == [1, 3]  # cheapest listed first
    assert set(ids[2:]) == {2, 4}  # unlisted fill
    assert data["tokens"][0]["price_eth"] == 0.2
    assert data["tokens"][2]["price_eth"] is None


# ── OpenSea client ────────────────────────────────────────────────────────────

def test_parse_best_listings_extracts_cheapest_per_token():
    def listing(tid, wei):
        return {
            "protocol_data": {"parameters": {"offer": [{"identifierOrCriteria": str(tid)}]}},
            "price": {"current": {"currency": "ETH", "decimals": 18, "value": str(wei)}},
        }
    data = {"listings": [
        listing(7, 500_000_000_000_000_000),   # 0.5
        listing(7, 400_000_000_000_000_000),   # cheaper duplicate wins
        listing(8, 1_000_000_000_000_000_000),
        {"malformed": True},                    # skipped, not fatal
    ]}
    assert _parse_best_listings(data) == {7: 0.4, 8: 1.0}


def test_listed_prices_empty_without_key():
    # Test env has no OPENSEA_API_KEY -> every fetch degrades to {}.
    assert opensea.listed_prices(CONTRACT, "eth") == {}


@pytest.mark.parametrize("chain,expected", [
    ("eth", "ethereum"),
    ("base", "base"),
    ("base-sepolia", None),  # OpenSea dropped testnets (OS2, 2025)
    ("", None),
])
def test_opensea_chain_map(chain, expected):
    assert opensea_chain(chain) == expected


def test_asset_url_none_off_opensea():
    assert asset_url("base-sepolia", CONTRACT, 1) is None
    assert asset_url("base", CONTRACT, 1) == f"https://opensea.io/assets/base/{CONTRACT}/1"
