from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql://postmint:postmint@localhost:15432/postmint"
    redis_url: str = "redis://localhost:6379/0"
    moralis_api_key: str = ""
    # Pause between Moralis requests. Default matches the free tier (40 req/s);
    # lower it (or set 0) on paid plans via MORALIS_RATE_SLEEP in .env.
    moralis_rate_sleep: float = 0.025
    base_sepolia_rpc_url: str = "https://sepolia.base.org"
    # Browser origins allowed to call the API (comma-separated). Defaults cover the
    # Next.js dev server reached via either hostname — hitting it on 127.0.0.1 when
    # only localhost is allowed makes the CORS preflight fail as a "Failed to fetch".
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # On-chain lock attestation (Wave 2). The backend signer key authorizes
    # `ManifestRegistry.lockManifest`; the registry address + chain id bind each
    # attestation to a specific deployment so it can't be replayed elsewhere.
    # Populate `manifest_registry_address` after deploying the contract.
    backend_signer_private_key: str = ""
    manifest_registry_address: str = ""
    chain_id: int = 84532  # Base Sepolia

    # Phase 3 claim attestation. How long a `/claim/sign` signature stays valid
    # (the `expiry` bound into the digest); the contract rejects a claim tx that
    # lands after it. Keep short so a leaked/stale sig can't be replayed later.
    claim_sig_ttl_seconds: int = 3600

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
