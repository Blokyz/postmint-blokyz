from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import audit, health

app = FastAPI(
    title="Post-Mint Set Collection Engine",
    description="Ingestion, rarity audit, atlas, eligibility, and claim signing API",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(audit.router)
