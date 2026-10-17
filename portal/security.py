"""Passwords, tokens and a tiny in-memory rate limiter (stdlib only)."""
import hashlib
import hmac
import os
import secrets
import time
from collections import defaultdict, deque

_N, _R, _P = 2 ** 14, 8, 1
DUMMY_HASH = "scrypt$" + "00" * 16 + "$" + "00" * 32


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt, dk = stored.split("$")
        if scheme != "scrypt":
            return False
        calc = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt),
                              n=_N, r=_R, p=_P, dklen=32)
        return hmac.compare_digest(calc.hex(), dk)
    except (ValueError, TypeError):
        return False


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_api_token() -> tuple[str, str]:
    """Returns (token to show once, hash to store)."""
    token = "wsp_" + secrets.token_urlsafe(32)
    return token, token_hash(token)


def new_link_token() -> str:
    """Capability token embedded in a student's private link (128 bits)."""
    return secrets.token_urlsafe(16)


class RateLimiter:
    """Sliding window, per process. Good enough for one small server; not a substitute
    for a proxy-level limit if the portal is ever exposed to heavy traffic."""

    def __init__(self, limit: int, window_seconds: int):
        self.limit, self.window = limit, window_seconds
        self._hits: dict[str, deque] = defaultdict(deque)

    def _trim(self, key: str, now: float):
        q = self._hits[key]
        while q and now - q[0] > self.window:
            q.popleft()
        return q

    def ok(self, key: str) -> bool:
        return len(self._trim(key, time.monotonic())) < self.limit

    def record(self, key: str):
        now = time.monotonic()
        self._trim(key, now).append(now)
