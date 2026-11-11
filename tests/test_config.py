from __future__ import annotations

from zoneinfo import ZoneInfo

import pytest
from techo import clock
from techo.config import Settings


def settings_env(monkeypatch, timezone: str | None) -> None:
    monkeypatch.setenv("TECHO_PASSWORD_HASH", "$argon2id$v=19$m=1,t=1,p=1$fake$fake")
    monkeypatch.setenv("TECHO_AGENT_TOKEN", "x" * 32)
    if timezone is None:
        monkeypatch.delenv("TECHO_TIMEZONE", raising=False)
    else:
        monkeypatch.setenv("TECHO_TIMEZONE", timezone)


def test_timezone_defaults_and_reads_env(monkeypatch):
    settings_env(monkeypatch, None)
    assert Settings.from_env().timezone == "Asia/Shanghai"
    settings_env(monkeypatch, "UTC")
    assert Settings.from_env().timezone == "UTC"


def test_invalid_timezone_is_rejected(monkeypatch):
    settings_env(monkeypatch, "Not/AZone")
    with pytest.raises(ValueError, match="TECHO_TIMEZONE"):
        Settings.from_env()


def test_clock_uses_configured_zone():
    original = clock.current_zone()
    try:
        clock.configure(ZoneInfo("UTC"))
        assert clock.stamp().endswith("+00:00")
    finally:
        clock.configure(original)
