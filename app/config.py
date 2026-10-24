"""Central configuration. All secrets come from environment variables (or a local .env)."""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()  # no-op if there is no .env file (e.g. in production)


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    database_url: str
    seed_demo_data: bool
    api_key: str
    vapi_server_secret: str
    public_base_url: str
    log_level: str


def get_settings() -> Settings:
    return Settings(
        database_url=os.getenv("DATABASE_URL", "sqlite:///./data/patients.db").strip(),
        seed_demo_data=_bool("SEED_DEMO_DATA", False),
        api_key=os.getenv("API_KEY", "").strip(),
        vapi_server_secret=os.getenv("VAPI_SERVER_SECRET", "").strip(),
        public_base_url=os.getenv("PUBLIC_BASE_URL", "https://your-api.example.com").strip().rstrip("/"),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
    )
