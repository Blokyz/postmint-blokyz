from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql://postmint:postmint@localhost:15432/postmint"
    redis_url: str = "redis://localhost:6379/0"
    moralis_api_key: str = ""
    base_sepolia_rpc_url: str = "https://sepolia.base.org"


@lru_cache
def get_settings() -> Settings:
    return Settings()
