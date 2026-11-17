from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class ConfiguredModel(BaseModel):
    model_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    provider: Literal["google", "anthropic", "xai"] = "google"
    endpoint_type: Literal["vertex_gemini", "vertex_anthropic", "xai_responses"] = (
        "vertex_gemini"
    )
    location: str = Field(default="us-central1", min_length=1)
    supports_temperature: bool = False
    supports_top_p: bool = False
    supports_seed: bool = False
    supports_reasoning: bool = False
    supports_structured_output: bool = False
    max_context: int = Field(gt=0)
    enabled: bool = False

    @model_validator(mode="after")
    def validate_provider_endpoint(self) -> ConfiguredModel:
        expected_provider = {
            "vertex_gemini": "google",
            "vertex_anthropic": "anthropic",
            "xai_responses": "xai",
        }[self.endpoint_type]
        if self.provider != expected_provider:
            raise ValueError(
                f"endpoint_type {self.endpoint_type!r} requires provider {expected_provider!r}"
            )
        return self


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPOSITORY_ROOT / ".env",
        env_prefix="APP_",
        extra="ignore",
    )

    app_name: str = "LLM Source Manipulation Benchmark"
    environment: Literal["development", "test", "production"] = Field(
        default="development",
        validation_alias="APP_ENV",
    )
    host: str = "127.0.0.1"
    port: int = 8000
    database_url: str = "sqlite+aiosqlite:///./data/seo_eval.db"
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    log_level: str = "INFO"
    auto_create_schema: bool = False
    max_source_bytes: int = 5 * 1024 * 1024
    model_timeout_seconds: int = Field(default=180, ge=1, le=900)
    analysis_model_id: str = "gemini-3.5-flash-lite"
    gcp_project: str | None = None
    xai_api_key: SecretStr | None = Field(default=None, validation_alias="APP_XAI_API_KEY")
    model_registry: list[ConfiguredModel] = Field(default_factory=list)


@lru_cache
def get_settings() -> Settings:
    return Settings()
