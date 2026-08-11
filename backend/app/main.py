from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import atlas, audit, auth, claims, collections, health
from app.config import get_settings

settings = get_settings()

app = FastAPI(
    title="Post-Mint Set Collection Engine v2",
    description="Ingestion, rarity audit, atlas, eligibility, and claim signing API",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(audit.router)
app.include_router(atlas.router)
app.include_router(claims.router)
app.include_router(collections.router)
