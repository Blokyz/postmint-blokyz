from unittest.mock import MagicMock, patch

import pytest

from app.ingestion.moralis_client import (
    NftPage,
    _normalize_chain,
    _normalize_value,
    fetch_nft_page,
)

_CONTRACT = "0xBC4CA0EdA7647A8aB7C2061c2E118A18a936f13D"
_API_KEY = "fake-api-key"


def _mock_resp(data: dict) -> MagicMock:
    m = MagicMock()
    m.json.return_value = data
    m.raise_for_status.return_value = None
    return m


_PAGE_ONE = {
    "total": 3,
    "cursor": "cursor-abc",
    "result": [
        {
            "token_id": "1",
            "owner_of": "0xOwnerA",
            "block_number": "21000000",
            "normalized_metadata": {
                "attributes": [
                    {"trait_type": "Fur", "value": "Solid Gold"},
                    {"trait_type": "Background", "value": "Blue"},
                ]
            },
        },
        {
            "token_id": "2",
            "owner_of": "0xOwnerB",
            "block_number": "21000001",
            "normalized_metadata": {"attributes": []},
        },
    ],
}

_LAST_PAGE = {
    "total": 3,
    "cursor": None,
    "result": [
        {
            "token_id": "3",
            "owner_of": None,
            "block_number": None,
            "normalized_metadata": None,
        }
    ],
}


# ── Token parsing ──────────────────────────────────────────────────────────────

def test_tokens_parsed_count():
    with patch("httpx.get", return_value=_mock_resp(_PAGE_ONE)):
        page = fetch_nft_page(_CONTRACT, "eth", _API_KEY)
    assert len(page.tokens) == 2


def test_token_id_cast_to_int():
    with patch("httpx.get", return_value=_mock_resp(_PAGE_ONE)):
        page = fetch_nft_page(_CONTRACT, "eth", _API_KEY)
    assert page.tokens[0]["token_id"] == 1


def test_owner_address_lowercased():
    with patch("httpx.get", return_value=_mock_resp(_PAGE_ONE)):
        page = fetch_nft_page(_CONTRACT, "eth", _API_KEY)
    assert page.tokens[0]["owner_address"] == "0xownera"


def test_snapshot_block_cast_to_int():
    with patch("httpx.get", return_value=_mock_resp(_PAGE_ONE)):
        page = fetch_nft_page(_CONTRACT, "eth", _API_KEY)
    assert page.tokens[0]["snapshot_block"] == 21_000_000


def test_missing_owner_becomes_none():
    with patch("httpx.get", return_value=_mock_resp(_LAST_PAGE)):
        page = fetch_nft_page(_CONTRACT, "eth", _API_KEY)
    assert page.tokens[0]["owner_address"] is None


def test_missing_block_becomes_none():
    with patch("httpx.get", return_value=_mock_resp(_LAST_PAGE)):
        page = fetch_nft_page(_CONTRACT, "eth", _API_KEY)
    assert page.tokens[0]["snapshot_block"] is None


def test_contract_address_lowercased_in_token():
    with patch("httpx.get", return_value=_mock_resp(_PAGE_ONE)):
        page = fetch_nft_page(_CONTRACT, "eth", _API_KEY)
    assert page.tokens[0]["contract_address"] == _CONTRACT.lower()


# ── Trait parsing ──────────────────────────────────────────────────────────────

def test_traits_parsed_count():
    with patch("httpx.get", return_value=_mock_resp(_PAGE_ONE)):
        page = fetch_nft_page(_CONTRACT, "eth", _API_KEY)
    # Token 1 has 2 traits; token 2 has 0
    assert len(page.traits) == 2


def test_trait_category_title_cased():
    data = {
        "total": 1, "cursor": None,
        "result": [{
            "token_id": "1", "owner_of": "0xA", "block_number": "1",
            "normalized_metadata": {
                "attributes": [{"trait_type": "background color", "value": "blue"}]
            },
        }],
    }
    with patch("httpx.get", return_value=_mock_resp(data)):
        page = fetch_nft_page(_CONTRACT, "eth", _API_KEY)
    assert page.traits[0]["trait_category"] == "Background Color"


def test_trait_category_blank_is_skipped():
    data = {
        "total": 1, "cursor": None,
        "result": [{
            "token_id": "1", "owner_of": "0xA", "block_number": "1",
            "normalized_metadata": {
                "attributes": [{"trait_type": "  ", "value": "blue"}]
            },
        }],
    }
    with patch("httpx.get", return_value=_mock_resp(data)):
        page = fetch_nft_page(_CONTRACT, "eth", _API_KEY)
    assert page.traits == []


def test_no_normalized_metadata_yields_no_traits():
    with patch("httpx.get", return_value=_mock_resp(_LAST_PAGE)):
        page = fetch_nft_page(_CONTRACT, "eth", _API_KEY)
    assert page.traits == []


# ── Pagination ─────────────────────────────────────────────────────────────────

def test_next_cursor_returned():
    with patch("httpx.get", return_value=_mock_resp(_PAGE_ONE)):
        page = fetch_nft_page(_CONTRACT, "eth", _API_KEY)
    assert page.next_cursor == "cursor-abc"


def test_no_cursor_on_last_page():
    with patch("httpx.get", return_value=_mock_resp(_LAST_PAGE)):
        page = fetch_nft_page(_CONTRACT, "eth", _API_KEY)
    assert page.next_cursor is None


def test_total_returned():
    with patch("httpx.get", return_value=_mock_resp(_PAGE_ONE)):
        page = fetch_nft_page(_CONTRACT, "eth", _API_KEY)
    assert page.total == 3


def test_cursor_passed_to_api():
    with patch("httpx.get", return_value=_mock_resp(_LAST_PAGE)) as mock_get:
        fetch_nft_page(_CONTRACT, "eth", _API_KEY, cursor="my-cursor")
    _, kwargs = mock_get.call_args
    assert kwargs["params"]["cursor"] == "my-cursor"


def test_no_cursor_param_on_first_page():
    with patch("httpx.get", return_value=_mock_resp(_PAGE_ONE)) as mock_get:
        fetch_nft_page(_CONTRACT, "eth", _API_KEY)
    _, kwargs = mock_get.call_args
    assert "cursor" not in kwargs["params"]


# ── Chain normalisation ────────────────────────────────────────────────────────

@pytest.mark.parametrize("alias,expected", [
    ("ethereum", "eth"),
    ("Ethereum", "eth"),
    ("ETH", "eth"),
    ("base", "base"),
    ("polygon", "polygon"),
    ("arbitrum", "arbitrum"),
    ("optimism", "optimism"),
])
def test_normalize_chain(alias, expected):
    assert _normalize_chain(alias) == expected


def test_normalize_chain_unknown_passthrough():
    assert _normalize_chain("avalanche") == "avalanche"


# ── Value normalisation ────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw", ["none", "null", "n/a", "N/A", "NULL", "", None])
def test_normalize_value_null_variants(raw):
    assert _normalize_value(raw) == "None"


def test_normalize_value_real_value():
    assert _normalize_value("Solid Gold") == "Solid Gold"


def test_normalize_value_strips_whitespace():
    assert _normalize_value("  Blue  ") == "Blue"
