"""Проверка Telegram initData, подписанные сессионные токены и rate limiting."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from collections import OrderedDict, deque
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl

MAX_INIT_DATA_LEN = 4096


class AuthError(Exception):
    pass


@dataclass(frozen=True)
class TelegramUser:
    id: int
    first_name: str
    last_name: str
    username: str | None
    language_code: str | None
    is_premium: bool
    photo_url: str | None


def _clean_str(value: Any, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()[:limit]


def validate_init_data(init_data: str, bot_token: str, max_age: int) -> TelegramUser:
    """Проверяет подпись initData по алгоритму из документации Telegram Mini Apps.

    secret_key = HMAC_SHA256(key="WebAppData", msg=bot_token)
    hash       = HMAC_SHA256(key=secret_key, msg=data_check_string)
    """
    if not init_data or len(init_data) > MAX_INIT_DATA_LEN:
        raise AuthError("init data missing or too long")

    try:
        pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True)
    except ValueError as exc:
        raise AuthError("malformed init data") from exc

    data: dict[str, str] = {}
    for key, value in pairs:
        if key in data:  # дубликаты ключей — признак подделки
            raise AuthError("duplicate key")
        data[key] = value

    received_hash = data.pop("hash", None)
    if not received_hash or len(received_hash) != 64:
        raise AuthError("hash missing")

    check_string = "\n".join(f"{k}={data[k]}" for k in sorted(data))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received_hash.lower()):
        raise AuthError("bad signature")

    try:
        auth_date = int(data.get("auth_date", "0"))
    except ValueError as exc:
        raise AuthError("bad auth_date") from exc
    now = int(time.time())
    if auth_date <= 0 or now - auth_date > max_age or auth_date - now > 300:
        raise AuthError("init data expired")

    try:
        user = json.loads(data.get("user", ""))
    except json.JSONDecodeError as exc:
        raise AuthError("bad user") from exc
    if not isinstance(user, dict) or not isinstance(user.get("id"), int) or user["id"] <= 0:
        raise AuthError("bad user")
    if user.get("is_bot"):
        raise AuthError("bots are not allowed")

    photo_url = _clean_str(user.get("photo_url"), 512) or None
    if photo_url and not photo_url.startswith("https://t.me/"):
        photo_url = None

    return TelegramUser(
        id=user["id"],
        first_name=_clean_str(user.get("first_name"), 128),
        last_name=_clean_str(user.get("last_name"), 128),
        username=_clean_str(user.get("username"), 64) or None,
        language_code=_clean_str(user.get("language_code"), 16) or None,
        is_premium=bool(user.get("is_premium")),
        photo_url=photo_url,
    )


# ---------------------------------------------------------------------------
# Сессионные токены: base64url(payload).base64url(HMAC-SHA256(payload))
# ---------------------------------------------------------------------------
def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def issue_token(user_id: int, key: bytes, ttl: int) -> tuple[str, int]:
    exp = int(time.time()) + ttl
    payload = json.dumps({"u": user_id, "e": exp}, separators=(",", ":")).encode()
    sig = hmac.new(key, payload, hashlib.sha256).digest()
    return f"{_b64e(payload)}.{_b64e(sig)}", exp


def verify_token(token: str, key: bytes) -> int:
    if not token or len(token) > 256 or token.count(".") != 1:
        raise AuthError("bad token")
    p_part, s_part = token.split(".")
    try:
        payload = _b64d(p_part)
        sig = _b64d(s_part)
    except (ValueError, base64.binascii.Error) as exc:
        raise AuthError("bad token") from exc
    expected = hmac.new(key, payload, hashlib.sha256).digest()
    if not hmac.compare_digest(expected, sig):
        raise AuthError("bad token")
    try:
        data = json.loads(payload)
        user_id, exp = int(data["u"]), int(data["e"])
    except (ValueError, KeyError, TypeError) as exc:
        raise AuthError("bad token") from exc
    if exp < time.time():
        raise AuthError("token expired")
    return user_id


# ---------------------------------------------------------------------------
# Rate limiter: скользящее окно в памяти (одного процесса достаточно).
# ---------------------------------------------------------------------------
class RateLimiter:
    def __init__(self, max_keys: int = 50_000) -> None:
        self._hits: OrderedDict[str, deque[float]] = OrderedDict()
        self._max_keys = max_keys

    def hit(self, key: str, limit: int, window: float) -> bool:
        """True — запрос разрешён, False — лимит превышен."""
        now = time.monotonic()
        bucket = self._hits.get(key)
        if bucket is None:
            bucket = deque()
            self._hits[key] = bucket
            if len(self._hits) > self._max_keys:
                self._hits.popitem(last=False)
        else:
            self._hits.move_to_end(key)
        border = now - window
        while bucket and bucket[0] <= border:
            bucket.popleft()
        if len(bucket) >= limit:
            return False
        bucket.append(now)
        return True
