"""
Solasta Smart Study Scheduler — Core Configuration

Centralised settings management using pydantic-settings.
All environment variables are validated at startup.
"""

from __future__ import annotations

import json
from enum import Enum
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    DEVELOPMENT = "development"
    PRODUCTION = "production"
    TESTING = "testing"


class LLMProvider(str, Enum):
    OLLAMA = "ollama"
    GEMINI = "gemini"
    OPENAI = "openai"


class Settings(BaseSettings):
    """Application-wide configuration loaded from .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ──────────────────────────────────────────
    app_name: str = "SmartStudyScheduler"
    app_env: Environment = Environment.DEVELOPMENT
    debug: bool = True
    log_level: str = "INFO"

    # ── Supabase / Database ──────────────────────────────────
    supabase_url: str = ""
    supabase_key: str = ""
    supabase_service_role_key: str = ""
    database_url: str = "sqlite+aiosqlite:///./local.db"

    # ── LLM — Ollama ─────────────────────────────────────────
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3"

    # ── LLM — Gemini ─────────────────────────────────────────
    google_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"

    # ── LLM — OpenAI ─────────────────────────────────────────
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # ── LLM Routing ──────────────────────────────────────────
    llm_primary_provider: LLMProvider = LLMProvider.OLLAMA
    llm_fallback_provider: LLMProvider = LLMProvider.GEMINI
    llm_tertiary_provider: LLMProvider = LLMProvider.OPENAI
    llm_timeout_seconds: int = 30
    llm_max_retries: int = 3

    # ── Server ───────────────────────────────────────────────
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: List[str] = ["http://localhost:3000"]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors(cls, v):
        if isinstance(v, str):
            return json.loads(v)
        return v

    @property
    def is_production(self) -> bool:
        return self.app_env == Environment.PRODUCTION


# Singleton — import this everywhere
settings = Settings()
