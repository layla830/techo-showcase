from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    project_root: Path
    password_hash: str
    agent_token: str
    public_origin: str = "https://techo.example.com"
    base_path: str = "/techo"
    session_days: int = 90
    cookie_name: str = "techo_session"
    timezone: str = "Asia/Shanghai"

    @property
    def database_path(self) -> Path:
        return self.project_root / "data" / "techo.db"

    @property
    def photos_path(self) -> Path:
        # Production systemd only allows writes under data/; photos live beside the DB.
        return self.database_path.parent / "photos"

    @property
    def api_prefix(self) -> str:
        return self.base_path + "/api/v1"

    @classmethod
    def from_env(cls) -> Settings:
        values = {**dotenv_values(PROJECT_ROOT / ".env"), **os.environ}
        password_hash = values.get("TECHO_PASSWORD_HASH", "")
        token = values.get("TECHO_AGENT_TOKEN", "")
        origin = values.get("TECHO_PUBLIC_ORIGIN", "https://techo.example.com").rstrip("/")
        timezone = values.get("TECHO_TIMEZONE") or "Asia/Shanghai"
        try:
            ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("TECHO_TIMEZONE must be a valid IANA timezone name") from None
        if not password_hash.startswith(("$argon2", "$2a$", "$2b$", "$2y$")):
            raise ValueError("TECHO_PASSWORD_HASH must contain an Argon2 or bcrypt hash")
        if len(token) < 32:
            raise ValueError("TECHO_AGENT_TOKEN must contain at least 32 characters")
        parsed = urlsplit(origin)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.path
            or parsed.query
            or parsed.fragment
            or parsed.username
            or parsed.password
        ):
            raise ValueError("TECHO_PUBLIC_ORIGIN must be an HTTPS origin without a path")
        return cls(
            project_root=PROJECT_ROOT,
            password_hash=password_hash,
            agent_token=token,
            public_origin=origin,
            timezone=timezone,
        )
