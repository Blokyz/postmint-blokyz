# Post-Mint Set Collection Engine

Plug-and-play set collection races for NFT projects. See [PLAN.md](./PLAN.md) and [TECHNICAL_DESIGN.md](./TECHNICAL_DESIGN.md).

**MVP defaults:** Base Sepolia claims · BAYC validation · wallet-based on-chain approval · monorepo.

## Prerequisites

- **Docker Desktop** (for Postgres) — start Docker before `docker compose up`
- **Foundry** (`forge`) — [install](https://book.getfoundry.sh/getting-started/installation) for contract tests and Base Sepolia deploy
- **Python 3.11+** and **Node 18+**
- **WalletConnect project id** — [cloud.walletconnect.com](https://cloud.walletconnect.com) for RainbowKit (set in `frontend/.env.local`)

## Quick start

### 1. Database

```bash
docker compose up -d
```

### 2. Backend

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example ../.env
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

In a second terminal (Celery worker for ingestion):

```bash
cd backend
# Windows (recommended): stops duplicate workers, uses solo pool
./scripts/run_celery_worker.ps1
# macOS/Linux
celery -A app.worker:celery_app worker -Q ingestion --loglevel=info
```

If jobs stay `pending` after a Redis/Docker restart, repair and re-queue:

```bash
cd backend
python -m app.maintenance.repair_ingest_queue --stop-workers --requeue
```

- Health: http://localhost:8000/health  
- DB health: http://localhost:8000/health/db  

Trigger ingestion (PowerShell — `curl` is an alias and needs different syntax):

```powershell
$body = @{ contract_address = "0xBC4CA0EdA7647A8aB7C2061c2E118A18a936bC46"; chain = "eth" } | ConvertTo-Json
Invoke-RestMethod -Uri "http://localhost:8000/audit/ingest" -Method POST -ContentType "application/json" -Body $body
Invoke-RestMethod -Uri "http://localhost:8000/audit/status/0xBC4CA0EdA7647A8aB7C2061c2E118A18a936bC46"
```

### 3. Contracts (Foundry)

```bash
cd contracts
forge install foundry-rs/forge-std
forge install OpenZeppelin/openzeppelin-contracts@v5.1.0
forge test
```

Deploy `ManifestRegistry` to Base Sepolia:

```bash
export DEPLOYER_PRIVATE_KEY=0x...
export BASE_SEPOLIA_RPC_URL=https://sepolia.base.org
forge script script/DeployManifestRegistry.s.sol:DeployManifestRegistry \
  --rpc-url base_sepolia --broadcast
```

Set `NEXT_PUBLIC_MANIFEST_REGISTRY_ADDRESS` in `frontend/.env.local`.

### 4. Frontend

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev
```

Open http://localhost:3000 — connect wallet on Base Sepolia.

## Layout

| Path | Role |
|------|------|
| `backend/` | FastAPI, Postgres, Moralis ingestion (Sprint 1+) |
| `contracts/` | `ManifestRegistry`, later `SetClaimFactory` / `SetClaimManager` |
| `frontend/` | Next.js 14 + wagmi + RainbowKit |
| `schemas/` | JSON Schema for ranking + atlas manifests |

## Docs

- [IMPLEMENTATION.md](./IMPLEMENTATION.md) — locked decisions and sprint tracker
