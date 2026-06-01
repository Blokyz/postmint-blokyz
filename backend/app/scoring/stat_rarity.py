"""Statistical rarity scoring: −log₂(frequency), normalised to [0, 1]."""

import math

import pandas as pd


def compute_stat_rarity(df: pd.DataFrame, eligible_supply: int) -> pd.DataFrame:
    """
    Args:
        df: columns [trait_category, trait_value, token_count]
        eligible_supply: total number of tokens ingested

    Returns:
        Same rows + [frequency, stat_rarity, stat_norm], sorted by stat_norm desc.
    """
    out = df.copy()
    out["token_count"] = out["token_count"].astype(int)
    out["frequency"] = out["token_count"] / eligible_supply
    out["stat_rarity"] = out["frequency"].apply(
        lambda f: -math.log2(f) if f > 0 else 0.0
    )

    r_min = out["stat_rarity"].min()
    r_max = out["stat_rarity"].max()
    if r_max > r_min:
        out["stat_norm"] = (out["stat_rarity"] - r_min) / (r_max - r_min)
    else:
        out["stat_norm"] = 0.0

    return out.sort_values("stat_norm", ascending=False).reset_index(drop=True)
