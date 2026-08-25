from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any

from fastapi import Request, Response

from .config import Settings


COOKIE_NAME = "research_admin_session"


class AdminAuth:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def enabled(self) -> bool:
        return bool(self.settings.admin_password and self.settings.admin_session_secret)

    def authenticate(self, password: str) -> bool:
        expected = self.settings.admin_password
        return bool(expected) and hmac.compare_digest(password.encode("utf-8"), expected.encode("utf-8"))

    def issue(self, response: Response) -> None:
        if not self.enabled:
            raise RuntimeError("admin authentication is not configured")
        expires = int(time.time()) + self.settings.admin_session_seconds
        payload = {"exp": expires, "nonce": secrets.token_urlsafe(18)}
        encoded = self._encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        signature = self._sign(encoded)
        response.set_cookie(
            COOKIE_NAME,
            f"{encoded}.{signature}",
            max_age=self.settings.admin_session_seconds,
            httponly=True,
            secure=self.settings.admin_cookie_secure,
            samesite="strict",
            path="/api/admin",
        )

    @staticmethod
    def clear(response: Response) -> None:
        response.delete_cookie(COOKIE_NAME, path="/api/admin", samesite="strict")

    def authorized(self, request: Request) -> bool:
        if not self.enabled:
            return False
        token = request.cookies.get(COOKIE_NAME)
        if not token or "." not in token:
            return False
        encoded, signature = token.rsplit(".", 1)
        if not hmac.compare_digest(signature, self._sign(encoded)):
            return False
        try:
            payload: Any = json.loads(self._decode(encoded))
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
            return False
        return (
            isinstance(payload, dict)
            and isinstance(payload.get("exp"), int)
            and payload["exp"] >= int(time.time())
        )

    def _sign(self, value: str) -> str:
        assert self.settings.admin_session_secret is not None
        digest = hmac.new(
            self.settings.admin_session_secret.encode("utf-8"),
            value.encode("ascii"),
            hashlib.sha256,
        ).digest()
        return self._encode(digest)

    @staticmethod
    def _encode(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")

    @staticmethod
    def _decode(value: str) -> str:
        padding = "=" * (-len(value) % 4)
        return base64.urlsafe_b64decode(value + padding).decode("utf-8")
