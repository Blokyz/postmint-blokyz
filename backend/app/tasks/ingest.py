"""Celery task: ingest all NFTs for a contract → stat rarity → ranking_manifest.json."""

import logging

import pandas as pd
from sqlalchemy import func, select, text

from app.config import get_settings
from app.db.models import IngestJob, Token
from app.db.session import SessionLocal
from app.ingestion.db_writer import upsert_sales, upsert_tokens, upsert_traits
from app.ingestion.errors import EmptyCollectionError, IngestError, MoralisApiError
from app.ingestion.moralis_client import fetch_nft_page, fetch_sales_page
from app.wash_trade import flag_wash_trades
from app.manifests import build_ranking_manifest, write_ranking_manifest
from app.scoring.market_premium import compute_market_premium
from app.scoring.stat_rarity import compute_stat_rarity
from app.worker import celery_app

log = logging.getLogger(__name__)
settings = get_settings()


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30, queue="ingestion")
def run_ingest(self, job_id: str) -> None:
    db = SessionLocal()
    job: IngestJob | None = None
    try:
        job = db.get(IngestJob, job_id)
        if not job:
            log.error("run_ingest: job %s not found", job_id)
            return

        if not settings.moralis_api_key:
            raise IngestError("MORALIS_API_KEY is not configured")

        job.status = "running"
        job.error_message = None
        db.commit()
        log.info("run_ingest started job %s for %s", job_id, job.contract_address)

        contract = job.contract_address
        chain = job.chain
        cursor = job.last_cursor  # None on first run; set if resuming after a crash

        total_fetched = 0
        collection_total: int | None = None

        # ── Page through all NFTs ─────────────────────────────────────────────────
        while True:
            page = fetch_nft_page(contract, chain, settings.moralis_api_key, cursor)

            if collection_total is None:
                collection_total = page.total or None  # keep None if API returned 0

            upsert_tokens(db, page.tokens)
            upsert_traits(db, page.traits)
            total_fetched += len(page.tokens)

            if collection_total:
                job.progress_pct = min(99, int(total_fetched / collection_total * 100))
            elif total_fetched > 0:
                # Moralis didn't return a total — show pages-fetched progress (approximate)
                job.progress_pct = min(50, total_fetched // 200)
            job.last_cursor = page.next_cursor
            db.commit()

            if not page.next_cursor:
                break

            cursor = page.next_cursor

        if total_fetched == 0:
            raise EmptyCollectionError(
                f"Moralis returned 0 NFTs for {contract} on chain {chain}"
            )

        # ── Fetch sales history ───────────────────────────────────────────────────
        sales_cursor: str | None = None
        total_sales = 0
        while True:
            sales_page = fetch_sales_page(contract, chain, settings.moralis_api_key, sales_cursor)
            if sales_page.sales:
                upsert_sales(db, sales_page.sales)
                total_sales += len(sales_page.sales)
            if not sales_page.next_cursor:
                break
            sales_cursor = sales_page.next_cursor
        log.info("Fetched %d sales for %s", total_sales, contract)

        # ── Flag wash trades ──────────────────────────────────────────────────────
        wash = flag_wash_trades(db, contract)
        log.info("Wash trade detection for %s: %s", contract, wash)

        # ── Market premium regression ─────────────────────────────────────────────
        market_result = compute_market_premium(db, contract)
        log.info(
            "Market premium for %s: method=%s r²=%s n_obs=%d",
            contract,
            market_result.method,
            f"{market_result.r_squared:.3f}" if market_result.r_squared is not None else "n/a",
            market_result.n_obs,
        )

        # ── Compute stat rarity ───────────────────────────────────────────────────
        eligible_supply: int = db.scalar(
            select(func.count()).select_from(Token)
            .where(Token.contract_address == contract)
        ) or 0

        if eligible_supply == 0:
            raise EmptyCollectionError(
                f"No tokens persisted for {contract} after fetch (pages had no rows)"
            )

        rows = db.execute(
            text("""
                SELECT trait_category, trait_value, COUNT(*)::int AS token_count
                FROM traits
                WHERE contract_address = :contract
                GROUP BY trait_category, trait_value
            """),
            {"contract": contract},
        ).fetchall()

        df = pd.DataFrame(rows, columns=["trait_category", "trait_value", "token_count"])
        ranked = compute_stat_rarity(df, eligible_supply)

        snapshot_block: int | None = db.scalar(
            select(func.max(Token.snapshot_block))
            .where(Token.contract_address == contract)
        )

        # ── Write manifest ────────────────────────────────────────────────────────
        manifest = build_ranking_manifest(
            contract_address=contract,
            chain=chain,
            total_supply=collection_total or eligible_supply,
            eligible_supply=eligible_supply,
            snapshot_block=snapshot_block,
            ranked_traits=ranked.to_dict("records"),
            market_result=market_result if market_result.method != "none" else None,
        )
        path = write_ranking_manifest(contract, manifest)

        job.status = "complete"
        job.progress_pct = 100
        job.manifest_path = str(path)
        db.commit()
        log.info(
            "Ingestion complete for %s — %d tokens, manifest at %s",
            contract,
            eligible_supply,
            path,
        )

    except (IngestError, MoralisApiError) as exc:
        log.error("run_ingest non-retryable failure for job %s: %s", job_id, exc)
        try:
            db.rollback()
            job = db.get(IngestJob, job_id)
            if job:
                job.status = "failed"
                job.error_message = str(exc)[:500]
                db.commit()
        except Exception:
            pass
    except Exception as exc:
        log.exception("run_ingest failed for job %s (attempt %d)", job_id, self.request.retries + 1)
        try:
            db.rollback()
            job = db.get(IngestJob, job_id)
            if job:
                job.error_message = str(exc)[:500]
                if self.request.retries >= self.max_retries:
                    job.status = "failed"
                db.commit()
        except Exception:
            pass
        raise self.retry(exc=exc)
    finally:
        try:
            if job is not None and job.status == "pending":
                db.rollback()
                refreshed = db.get(IngestJob, job_id)
                if refreshed and refreshed.status == "pending":
                    refreshed.status = "failed"
                    refreshed.error_message = (
                        refreshed.error_message
                        or "Task exited before updating job status (check Celery worker logs)"
                    )[:500]
                    db.commit()
        except Exception:
            pass
        db.close()
