"""Konfigurasjon lest fra miljovariabler (.env lokalt, secrets i skyen)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent

load_dotenv(REPO_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    database_url: str
    entry_id: int
    throttle_seconds: float
    user_agent: str

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


def _default_database_url() -> str:
    (REPO_ROOT / "data").mkdir(exist_ok=True)
    return f"sqlite:///{REPO_ROOT / 'data' / 'fpl.sqlite'}"


def get_settings() -> Settings:
    url = os.getenv("DATABASE_URL") or _default_database_url()
    # Streamlit Cloud og Supabase gir av og til 'postgres://', som SQLAlchemy 2 ikke tar.
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg2://", 1)
    return Settings(
        database_url=url,
        entry_id=int(os.getenv("FPL_ENTRY_ID", "3486140")),
        throttle_seconds=float(os.getenv("FPL_THROTTLE_SECONDS", "0.25")),
        user_agent=os.getenv(
            "FPL_USER_AGENT",
            "fpl-planner/0.1 (personal project; contact: jonas.ilje@gmail.com)",
        ),
    )
