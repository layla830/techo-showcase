from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import timedelta

from fastapi import Request
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from pwdlib.hashers.bcrypt import BcryptHasher
from sqlalchemy import delete, func, select

from .clock import now, stamp
from .config import Settings
from .database import Database
from .errors import APIError
from .models import BrowserSession, LoginAttempt


@dataclass(frozen=True)
class Actor:
    name: str
    source: str


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def check_origin(request: Request, settings: Settings) -> None:
    origin = request.headers.get("origin")
    if (origin is not None and origin != settings.public_origin) or request.headers.get(
        "sec-fetch-site"
    ) == "cross-site":
        raise APIError(403, "forbidden", "写入请求必须来自手帐本站")


class AuthService:
    def __init__(self, database: Database, settings: Settings):
        self.database = database
        self.settings = settings
        self.passwords = PasswordHash((Argon2Hasher(), BcryptHasher()))

    def authenticate(self, request: Request) -> Actor:
        token = request.headers.get("x-techo-token")
        if token is not None:
            if not hmac.compare_digest(token.encode(), self.settings.agent_token.encode()):
                raise APIError(401, "unauthorized", "Agent token 无效")
            return Actor("agent", "token")
        cookie = request.cookies.get(self.settings.cookie_name)
        if cookie:
            with self.database.transaction() as session:
                row = session.get(BrowserSession, digest(cookie))
                valid = row is not None and row.expires_at > stamp()
            if valid:
                if request.method not in {"GET", "HEAD", "OPTIONS"}:
                    check_origin(request, self.settings)
                return Actor("human", "session")
        raise APIError(401, "unauthorized", "请先登录")

    def login(self, password: str, ip: str) -> str:
        current = now()
        cutoff = stamp(current - timedelta(minutes=1))
        ip_hash = digest(ip)
        with self.database.transaction(write=True) as session:
            session.execute(delete(LoginAttempt).where(LoginAttempt.at <= cutoff))
            attempts = session.scalar(
                select(func.count()).select_from(LoginAttempt).where(LoginAttempt.ip_hash == ip_hash)
            )
            if attempts >= 5:
                raise APIError(429, "rate_limited", "登录过于频繁，请一分钟后重试")
            session.add(LoginAttempt(ip_hash=ip_hash, at=stamp(current)))
        try:
            valid = self.passwords.verify(password, self.settings.password_hash)
        except Exception:
            valid = False
        if not valid:
            raise APIError(401, "unauthorized", "密码不正确")
        token = secrets.token_urlsafe(32)
        with self.database.transaction(write=True) as session:
            session.execute(delete(BrowserSession).where(BrowserSession.expires_at <= stamp(current)))
            session.add(
                BrowserSession(
                    token_hash=digest(token),
                    created_at=stamp(current),
                    expires_at=stamp(current + timedelta(days=self.settings.session_days)),
                )
            )
        return token

    def logout(self, token: str | None) -> None:
        if token:
            with self.database.transaction(write=True) as session:
                session.execute(delete(BrowserSession).where(BrowserSession.token_hash == digest(token)))
