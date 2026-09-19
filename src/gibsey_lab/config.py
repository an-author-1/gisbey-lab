from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = REPO_ROOT / ".env"

DEFAULT_MODEL = "jev-latest"


@dataclass(frozen=True)
class Config:
    model: str
    api_key: str | None = field(default=None, repr=False)  # never shown in repr/str/logs

    @property
    def has_live_credentials(self) -> bool:
        return bool(self.api_key)


def load_config() -> Config:
    """Load .env from the repo root without discarding already-exported env vars.

    TYPESAFE_API_KEY / TYPESAFE_MODEL are canonical: the typesafe-sdk client reads
    TYPESAFE_API_KEY from the environment itself. JEV_API_KEY / JEV_MODEL / JEV_MODEL_ID
    are accommodated as an existing equivalent setting, not discarded, and are mirrored
    into the canonical name (only in-process; the .env file on disk is never rewritten).
    """
    load_dotenv(ENV_PATH, override=False)

    api_key = os.environ.get("TYPESAFE_API_KEY") or os.environ.get("JEV_API_KEY") or None
    if api_key:
        os.environ.setdefault("TYPESAFE_API_KEY", api_key)  # SDK reads this name directly

    model = (
        os.environ.get("TYPESAFE_MODEL")
        or os.environ.get("JEV_MODEL")
        or os.environ.get("JEV_MODEL_ID")
        or DEFAULT_MODEL
    )
    return Config(model=model, api_key=api_key)
