from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str  # ty: ignore[missing-argument]  # populated from env / .env


@lru_cache
def get_settings() -> Settings:
    return Settings()  # ty: ignore[missing-argument]  # env-populated
