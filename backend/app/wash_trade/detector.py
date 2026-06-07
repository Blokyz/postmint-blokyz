"""Wash trade detection: 4 SQL rules that set wash_trade_flag = true on suspicious sales."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

WASH_ROUND_TRIP_HOURS = 24
WASH_CLUSTER_MIN_TRADES = 6
WASH_CLUSTER_MAX_WALLETS = 3
WASH_CLUSTER_WINDOW_DAYS = 30
WASH_PRICE_OUTLIER_MULT = 8.0


@dataclass
class WashSummary:
    self_trade: int = 0
    round_trip: int = 0
    cluster: int = 0
    price_outlier: int = 0

    @property
    def total(self) -> int:
        return self.self_trade + self.round_trip + self.cluster + self.price_outlier

    def __str__(self) -> str:
        return (
            f"self={self.self_trade} round_trip={self.round_trip} "
            f"cluster={self.cluster} price_outlier={self.price_outlier} "
            f"total={self.total}"
        )


def flag_wash_trades(
    db: Session,
    contract: str,
    _cluster_ref_time: datetime | None = None,
) -> WashSummary:
    """Run all 4 rules in sequence and return per-rule flagged counts.

    _cluster_ref_time: override "now" for the cluster window (test hook only).
    """
    cluster_window_start = (
        _cluster_ref_time
        if _cluster_ref_time is not None
        else datetime.now(timezone.utc)
    ) - timedelta(days=WASH_CLUSTER_WINDOW_DAYS)

    summary = WashSummary(
        self_trade=_flag_self_trades(db, contract),
        round_trip=_flag_round_trips(db, contract),
        cluster=_flag_clusters(db, contract, cluster_window_start),
        price_outlier=_flag_price_outliers(db, contract),
    )
    db.commit()
    return summary


def _flag_self_trades(db: Session, contract: str) -> int:
    """Rule 1: buyer and seller are the same wallet."""
    result = db.execute(
        text("""
            UPDATE sales
            SET wash_trade_flag = true
            WHERE contract_address = :contract
              AND buyer_address  IS NOT NULL
              AND seller_address IS NOT NULL
              AND lower(buyer_address) = lower(seller_address)
              AND NOT wash_trade_flag
        """),
        {"contract": contract},
    )
    return result.rowcount


def _flag_round_trips(db: Session, contract: str) -> int:
    """Rule 2: same token traded A→B then B→A within the round-trip window."""
    result = db.execute(
        text("""
            UPDATE sales s
            SET wash_trade_flag = true
            WHERE s.contract_address = :contract
              AND NOT s.wash_trade_flag
              AND s.buyer_address  IS NOT NULL
              AND s.seller_address IS NOT NULL
              AND s.sold_at        IS NOT NULL
              AND EXISTS (
                  SELECT 1 FROM sales s2
                  WHERE s2.contract_address = :contract
                    AND s2.token_id = s.token_id
                    AND lower(s2.seller_address) = lower(s.buyer_address)
                    AND lower(s2.buyer_address)  = lower(s.seller_address)
                    AND s2.sold_at IS NOT NULL
                    AND ABS(EXTRACT(EPOCH FROM (s2.sold_at - s.sold_at)))
                        <= :window_seconds
                    AND s2.id != s.id
              )
        """),
        {"contract": contract, "window_seconds": WASH_ROUND_TRIP_HOURS * 3600},
    )
    return result.rowcount


def _flag_clusters(db: Session, contract: str, window_start: datetime) -> int:
    """Rule 3: token traded >= min_trades times among <= max_wallets distinct
    addresses within the rolling detection window.  All sales for a recycled
    token are flagged (not just the windowed ones).
    """
    result = db.execute(
        text("""
            WITH windowed AS (
                SELECT token_id, lower(buyer_address)  AS wallet
                FROM sales
                WHERE contract_address = :contract
                  AND buyer_address IS NOT NULL
                  AND (sold_at IS NULL OR sold_at >= :window_start)
                UNION ALL
                SELECT token_id, lower(seller_address) AS wallet
                FROM sales
                WHERE contract_address = :contract
                  AND seller_address IS NOT NULL
                  AND (sold_at IS NULL OR sold_at >= :window_start)
            ),
            stats AS (
                SELECT
                    token_id,
                    COUNT(*)                    AS trades,
                    COUNT(DISTINCT wallet)       AS wallets
                FROM windowed
                GROUP BY token_id
            ),
            recycled AS (
                SELECT token_id
                FROM stats
                WHERE trades  >= :min_trades
                  AND wallets <= :max_wallets
            )
            UPDATE sales
            SET wash_trade_flag = true
            WHERE contract_address = :contract
              AND NOT wash_trade_flag
              AND token_id IN (SELECT token_id FROM recycled)
        """),
        {
            "contract": contract,
            "window_start": window_start,
            "min_trades": WASH_CLUSTER_MIN_TRADES,
            "max_wallets": WASH_CLUSTER_MAX_WALLETS,
        },
    )
    return result.rowcount


def _flag_price_outliers(db: Session, contract: str) -> int:
    """Rule 4: sale price exceeds the outlier multiplier × the median for the
    token's rarity band (quartile).  Tokens with no trait data fall into band 0
    and are compared against the collection-wide median.

    Rarity proxy: sum of −log₂(trait_frequency) across all traits, computed
    from the traits table at detection time (matches stat_rarity logic).
    """
    result = db.execute(
        text("""
            WITH trait_freqs AS (
                SELECT trait_category,
                       trait_value,
                       COUNT(DISTINCT token_id)::float AS cnt
                FROM traits
                WHERE contract_address = :contract
                GROUP BY trait_category, trait_value
            ),
            supply AS (
                SELECT COUNT(DISTINCT token_id)::float AS n
                FROM traits
                WHERE contract_address = :contract
            ),
            token_rarity AS (
                SELECT t.token_id,
                       SUM(-ln(f.cnt / s.n) / ln(2.0)) AS score
                FROM traits t
                JOIN trait_freqs f
                  ON f.trait_category = t.trait_category
                 AND f.trait_value    = t.trait_value
                CROSS JOIN supply s
                WHERE t.contract_address = :contract
                GROUP BY t.token_id
            ),
            token_bands AS (
                SELECT token_id,
                       NTILE(4) OVER (ORDER BY score ASC) AS band
                FROM token_rarity
            ),
            band_medians AS (
                SELECT
                    COALESCE(tb.band, 0)                                          AS band,
                    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY s.sale_price_eth) AS med
                FROM sales s
                LEFT JOIN token_bands tb ON tb.token_id = s.token_id
                WHERE s.contract_address = :contract
                  AND NOT s.wash_trade_flag
                GROUP BY COALESCE(tb.band, 0)
            ),
            flagged_ids AS (
                SELECT s.id
                FROM sales s
                LEFT JOIN token_bands tb ON tb.token_id = s.token_id
                JOIN  band_medians  bm ON bm.band = COALESCE(tb.band, 0)
                WHERE s.contract_address = :contract
                  AND NOT s.wash_trade_flag
                  AND s.sale_price_eth > bm.med * :multiplier
            )
            UPDATE sales
            SET wash_trade_flag = true
            WHERE id IN (SELECT id FROM flagged_ids)
        """),
        {"contract": contract, "multiplier": WASH_PRICE_OUTLIER_MULT},
    )
    return result.rowcount
