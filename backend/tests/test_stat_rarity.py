import math

import pandas as pd
import pytest

from app.scoring.stat_rarity import compute_stat_rarity


def _df(*rows):
    return pd.DataFrame(rows, columns=["trait_category", "trait_value", "token_count"])


def test_rarest_trait_gets_norm_1():
    df = _df(("Fur", "Gold", 1), ("Fur", "Brown", 9))
    result = compute_stat_rarity(df, eligible_supply=10)
    gold = result[result.trait_value == "Gold"].iloc[0]
    assert gold["stat_norm"] == pytest.approx(1.0)


def test_most_common_trait_gets_norm_0():
    df = _df(("Fur", "Gold", 1), ("Fur", "Brown", 9))
    result = compute_stat_rarity(df, eligible_supply=10)
    brown = result[result.trait_value == "Brown"].iloc[0]
    assert brown["stat_norm"] == pytest.approx(0.0)


def test_stat_rarity_formula():
    df = _df(("Fur", "Gold", 1))
    result = compute_stat_rarity(df, eligible_supply=10)
    expected = -math.log2(1 / 10)
    assert result.iloc[0]["stat_rarity"] == pytest.approx(expected)


def test_frequency_computed_correctly():
    df = _df(("Background", "Blue", 100))
    result = compute_stat_rarity(df, eligible_supply=1000)
    assert result.iloc[0]["frequency"] == pytest.approx(0.1)


def test_uniform_traits_all_get_norm_0():
    """When every trait has the same count, normalisation collapses to 0."""
    df = _df(("Fur", "Gold", 5), ("Fur", "Brown", 5))
    result = compute_stat_rarity(df, eligible_supply=10)
    assert (result["stat_norm"] == 0.0).all()


def test_output_sorted_descending_by_stat_norm():
    df = _df(("Fur", "A", 1), ("Fur", "B", 5), ("Fur", "C", 50))
    result = compute_stat_rarity(df, eligible_supply=56)
    norms = result["stat_norm"].tolist()
    assert norms == sorted(norms, reverse=True)


def test_stat_norm_bounded_between_0_and_1():
    df = _df(("Fur", "A", 1), ("Fur", "B", 10), ("Fur", "C", 100))
    result = compute_stat_rarity(df, eligible_supply=111)
    assert result["stat_norm"].between(0.0, 1.0).all()


def test_output_preserves_all_rows():
    df = _df(("Fur", "A", 1), ("Background", "Blue", 200), ("Eyes", "Laser", 3))
    result = compute_stat_rarity(df, eligible_supply=204)
    assert len(result) == 3


def test_output_columns():
    df = _df(("Fur", "Gold", 1))
    result = compute_stat_rarity(df, eligible_supply=10)
    for col in ["trait_category", "trait_value", "token_count", "frequency", "stat_rarity", "stat_norm"]:
        assert col in result.columns
