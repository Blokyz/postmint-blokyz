"""End-to-end Phase-3 claim round-trip against a local anvil node.

Proves the full live loop — including the derived holding window (2026-08-04):
the holder's tokens are seeded as acquired 48h ago against a 24h season window,
so the wallet is `ready` on first status read with NO opt-in/submit step, and
the backend attests the acquisition-derived `windowStartedAt` which the
on-chain elapsed check accepts.

  deploy SetClaimFactory + a season (the real forge scripts, 24h window)
  -> POST /claims/season   (register the manager with the backend)
  -> seed a qualifying wallet (tokens/traits, acquired_at 48h ago) + atlas
  -> GET  /claim/status    (derived: ready — long holder, no clock started)
  -> POST /claim/sign      (backend attestation, windowStartedAt = 48h ago)
  -> SetClaimManager.claim tx from the wallet (cast send)
  -> POST /claim/confirm   (backend verifies the Claimed event on anvil)
  -> GET /winners + /leaderboard asserts (slot 1 recorded, on-chain slot number)

Run from backend/ with the venv active, Docker (Postgres) up, and foundry
(anvil/forge/cast) on PATH:

    python scripts/claim_e2e.py

Starts its own anvil on :8545 with chain-id 84532 (same as Base Sepolia, so
attestations bind identically); reuses an already-running node if one is up.
The API is driven in-process (FastAPI TestClient) against the dev DB with
BASE_SEPOLIA_RPC_URL overridden to anvil. Prior E2E rows for the fake contract
are cleaned at start, so reruns are idempotent.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

BACKEND_DIR = Path(__file__).resolve().parents[1]
CONTRACTS_DIR = BACKEND_DIR.parent / "contracts"
sys.path.insert(0, str(BACKEND_DIR))

RPC = "http://127.0.0.1:8545"
CHAIN_ID = 84532

# Point the app at anvil BEFORE any app import (module-level get_settings()).
os.environ["BASE_SEPOLIA_RPC_URL"] = RPC
os.environ["CHAIN_ID"] = str(CHAIN_ID)

# Well-known anvil dev keys.
DEPLOYER_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"  # account 0
HOLDER_KEY = "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"  # account 1
HOLDER = "0x70997970c51812dc3a010c7d01b50e0d17dc79c8"

# Synthetic collection raced in this E2E (never a real ingest).
CONTRACT = "0x0000000000000000000000000000000000e2e001"
ATLAS_HASH = "0x" + "e2" * 32
TIER = "Rare"
CAP = 3
COUNT_REQUIRED = 2
WINDOW_HOURS = 24  # the flat non-Common window; holder seeded as a 48h holder


def sh(args: list[str], cwd: Path | None = None, extra_env: dict | None = None) -> str:
    env = {**os.environ, **(extra_env or {})}
    proc = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True)
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr, file=sys.stderr)
        raise SystemExit(f"command failed ({proc.returncode}): {' '.join(args[:3])}…")
    return proc.stdout


def rpc_alive() -> bool:
    try:
        r = httpx.post(RPC, json={"jsonrpc": "2.0", "id": 1, "method": "eth_chainId", "params": []}, timeout=2)
        return int(r.json()["result"], 16) == CHAIN_ID
    except Exception:
        return False


def start_anvil() -> subprocess.Popen | None:
    if rpc_alive():
        print(f"· reusing running anvil at {RPC}")
        return None
    proc = subprocess.Popen(
        ["anvil", "--chain-id", str(CHAIN_ID), "--port", "8545", "--silent"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(50):
        if rpc_alive():
            print(f"· anvil up at {RPC} (chain-id {CHAIN_ID})")
            return proc
        time.sleep(0.2)
    proc.terminate()
    raise SystemExit("anvil did not come up on :8545")


def parse_deployed(stdout: str, marker: str) -> str:
    for line in stdout.splitlines():
        if marker in line:
            return line.rsplit(" ", 1)[-1].strip()
    print(stdout)
    raise SystemExit(f"could not find {marker!r} in forge output")


def main() -> None:
    anvil = start_anvil()
    try:
        # --- 1. Deploy factory + season via the real forge scripts ---
        out = sh(
            ["forge", "script", "script/DeploySetClaimFactory.s.sol:DeploySetClaimFactory",
             "--rpc-url", RPC, "--broadcast"],
            cwd=CONTRACTS_DIR,
            extra_env={"DEPLOYER_PRIVATE_KEY": DEPLOYER_KEY},
        )
        factory = parse_deployed(out, "SetClaimFactory deployed at:")
        print(f"· factory  {factory}")

        # Backend signer resolved from the configured key so the season accepts
        # the attestations /claim/sign will produce.
        from app.claim_signing import backend_signer_address
        from app.config import get_settings

        settings = get_settings()
        assert settings.base_sepolia_rpc_url == RPC, "env override did not take"
        if not settings.backend_signer_private_key:
            raise SystemExit("BACKEND_SIGNER_PRIVATE_KEY missing from .env")
        signer_addr = backend_signer_address(settings.backend_signer_private_key)

        out = sh(
            ["forge", "script", "script/DeploySeason.s.sol:DeploySeason",
             "--rpc-url", RPC, "--broadcast"],
            cwd=CONTRACTS_DIR,
            extra_env={
                "DEPLOYER_PRIVATE_KEY": DEPLOYER_KEY,
                "CLAIM_FACTORY_ADDRESS": factory,
                "SEASON_NFT_CONTRACT": CONTRACT,
                "SEASON_ATLAS_HASH": ATLAS_HASH,
                "BACKEND_SIGNER_ADDRESS": signer_addr,
                "SEASON_TIER_NAMES": TIER,
                "SEASON_TIER_CAPS": str(CAP),
                "SEASON_TIER_WINDOWS": str(WINDOW_HOURS * 3600),
            },
        )
        manager = parse_deployed(out, "Season (SetClaimManager) deployed at:")
        print(f"· season   {manager} (backendSigner {signer_addr})")

        # --- 2. Seed the dev DB + atlas manifest for the synthetic collection ---
        from sqlalchemy import delete
        from app.db.models import Claim, ClaimNonce, Season, Token, Trait
        from app.db.session import SessionLocal
        from app.manifests import OUTPUT_DIR, write_atlas_manifest

        from datetime import datetime, timedelta, timezone

        acquired = datetime.now(timezone.utc) - timedelta(hours=48)

        db = SessionLocal()
        db.execute(delete(Claim).where(Claim.contract_address == CONTRACT))
        db.execute(delete(ClaimNonce).where(ClaimNonce.contract_address == CONTRACT))
        db.execute(delete(Season).where(Season.contract_address == CONTRACT))
        db.execute(delete(Trait).where(Trait.contract_address == CONTRACT))
        db.execute(delete(Token).where(Token.contract_address == CONTRACT))
        for tid in (1, 2):
            db.add(
                Token(
                    contract_address=CONTRACT, token_id=tid, owner_address=HOLDER, acquired_at=acquired
                )
            )
            db.add(Trait(contract_address=CONTRACT, token_id=tid, trait_category="Hat", trait_value="Gold"))
        db.commit()
        db.close()

        write_atlas_manifest(
            CONTRACT,
            {
                "tier_structure": {TIER: {"cap": CAP, "holding_window_hours": WINDOW_HOURS}},
                "tiers": [
                    {
                        "tier": TIER,
                        "set_rule": {
                            "archetype": "count_of_pool",
                            "pool": [{"trait_category": "Hat", "trait_value": "Gold"}],
                            "count_required": COUNT_REQUIRED,
                        },
                    }
                ],
            },
        )
        print(f"· seeded {COUNT_REQUIRED} qualifying tokens (acquired 48h ago) for {HOLDER[:10]}… + atlas manifest")

        # --- 3. Drive the claim API in-process ---
        from fastapi.testclient import TestClient
        from app.main import app

        with TestClient(app) as client:
            r = client.post(
                "/claims/season",
                json={"contract_address": CONTRACT, "manager_address": manager, "atlas_hash": ATLAS_HASH},
            )
            assert r.status_code == 200, f"/claims/season -> {r.status_code}: {r.text}"

            # Derived window: a 48h holder against a 24h window is ready on
            # first read — no submit/opt-in exists anymore.
            r = client.get(f"/claim/status/{CONTRACT}/{TIER}/{HOLDER}")
            assert r.status_code == 200, f"/claim/status -> {r.status_code}: {r.text}"
            assert r.json()["status"] == "ready", f"derived window not ready: {r.json()}"
            print("· status derived from acquisitions -> ready (48h held vs 24h window)")

            r = client.post(
                "/claim/sign",
                json={"contract_address": CONTRACT, "tier": TIER, "wallet_address": HOLDER},
            )
            assert r.status_code == 200, f"/claim/sign -> {r.status_code}: {r.text}"
            att = r.json()
            assert att["manager_address"].lower() == manager.lower()
            # The attested window start is the acquisition-derived completion time.
            assert att["window_started_at"] == int(acquired.timestamp()), att
            print(f"· attestation signed (windowStartedAt = acquisition time, nonce {att['nonce']})")

            # --- 4. The real on-chain claim from the holder wallet ---
            token_ids = json.dumps(att["token_ids"], separators=(",", ":"))
            receipt = json.loads(
                sh(
                    ["cast", "send", manager,
                     "claim(string,uint256[],uint256,uint256,uint256,bytes)",
                     TIER, token_ids, str(att["window_started_at"]), str(att["expiry"]),
                     str(att["nonce"]), att["signature"],
                     "--private-key", HOLDER_KEY, "--rpc-url", RPC, "--json"],
                )
            )
            tx_hash = receipt["transactionHash"]
            assert receipt["status"] in ("0x1", 1), f"claim tx reverted: {receipt}"
            print(f"· claim tx mined {tx_hash} (gas {int(receipt['gasUsed'], 16)})")

            # --- 5. Confirm: backend verifies the Claimed event on anvil ---
            r = client.post(
                "/claim/confirm",
                json={"contract_address": CONTRACT, "tier": TIER, "wallet_address": HOLDER, "tx_hash": tx_hash},
            )
            assert r.status_code == 200, f"/claim/confirm -> {r.status_code}: {r.text}"
            body = r.json()
            assert body["status"] == "won" and body["slot_number"] == 1, body
            print(f"· confirm verified on-chain -> won slot {body['slot_number']}")

            # --- 6. The win is visible everywhere ---
            w = client.get(f"/winners/{CONTRACT}").json()
            assert w["total"] == 1 and w["winners_by_tier"][TIER][0]["wallet_address"] == HOLDER, w
            lb = client.get(f"/leaderboard/{CONTRACT}/{TIER}").json()
            assert lb["slots_filled"] == 1 and lb["slots_remaining"] == CAP - 1, lb

        # On-chain cross-check: slotsRemaining reflects the award.
        remaining = int(
            sh(["cast", "call", manager, "slotsRemaining(string)(uint256)", TIER, "--rpc-url", RPC]).split()[0]
        )
        assert remaining == CAP - 1, f"on-chain slotsRemaining {remaining} != {CAP - 1}"

        print()
        print("PASS — full claim loop verified live:")
        print(f"  factory {factory}")
        print(f"  season  {manager}")
        print(f"  winner  {HOLDER} slot 1 in {TIER!r} (tx {tx_hash})")
        print(f"  artifacts left for inspection: DB rows for {CONTRACT} + "
              f"{(OUTPUT_DIR / (CONTRACT + '_atlas_manifest.json')).name}")
    finally:
        if anvil is not None:
            anvil.terminate()


if __name__ == "__main__":
    main()
