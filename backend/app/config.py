"""Конфигурация приложения. Все секреты читаются только из переменных окружения."""
from __future__ import annotations

import hashlib
import hmac
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

APP_VERSION = "1.5.0"


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Переменная окружения {name} не задана")
    return value


def _parse_ids(raw: str) -> frozenset[int]:
    ids: set[int] = set()
    for part in re.split(r"[\s,;]+", raw.strip()):
        if part:
            try:
                ids.add(int(part))
            except ValueError as exc:
                raise RuntimeError(f"ADMIN_IDS содержит некорректный id: {part!r}") from exc
    return frozenset(ids)


def _normalize_channel(raw: str) -> str | int:
    value = raw.strip()
    # Числовой id приватного канала: -100xxxxxxxxxx
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    for prefix in ("https://t.me/", "http://t.me/", "t.me/", "@"):
        if value.lower().startswith(prefix):
            value = value[len(prefix):]
    value = value.strip("/")
    if not re.fullmatch(r"[A-Za-z0-9_]{4,32}", value):
        raise RuntimeError(f"CHANNEL_USERNAME некорректен: {raw!r}")
    return value


@dataclass(frozen=True)
class Settings:
    bot_token: str
    api_id: int
    api_hash: str
    channel: str | int
    admin_ids: frozenset[int]
    webapp_url: str
    webapp_short_name: str | None
    data_dir: Path
    static_dir: Path
    secret_key: bytes = field(repr=False)
    ytdlp_proxy: str | None = field(default=None, repr=False)   # http(s)/socks5 прокси для YouTube
    ytdlp_cookies: Path | None = None                          # cookies.txt (Netscape) для YouTube
    session_ttl: int = 12 * 3600          # время жизни сессионного токена
    init_data_ttl: int = 24 * 3600        # максимальный возраст initData
    stream_concurrency: int = 24          # одновременных стримов на весь сервер
    stream_per_user: int = 3              # одновременных стримов на пользователя
    log_level: str = "INFO"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def covers_dir(self) -> Path:
        return self.data_dir / "covers"

    @property
    def avatars_dir(self) -> Path:
        return self.data_dir / "avatars"

    @property
    def session_path(self) -> Path:
        # Сессия привязана к id бота: при смене BOT_TOKEN на другого бота создаётся новая
        return self.data_dir / f"telegram-{self.bot_token.split(':', 1)[0]}"

    @property
    def webapp_origin(self) -> str:
        p = urlparse(self.webapp_url)
        return f"{p.scheme}://{p.netloc}"

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.admin_ids


def _proxy(raw: str) -> str | None:
    value = raw.strip()
    if not value:
        return None
    if urlparse(value).scheme not in ("http", "https", "socks5", "socks5h"):
        raise RuntimeError("YTDLP_PROXY: поддерживаются http://, https://, socks5://")
    return value


def _cookies(raw: str) -> Path | None:
    value = raw.strip()
    if not value:
        return None
    path = Path(value)
    if not path.is_file():
        raise RuntimeError(f"YTDLP_COOKIES: файл не найден: {value}")
    return path


def load_settings() -> Settings:
    bot_token = _required("BOT_TOKEN")
    if not re.fullmatch(r"\d+:[A-Za-z0-9_-]{30,}", bot_token):
        raise RuntimeError("BOT_TOKEN имеет неверный формат")

    api_id_raw = _required("TELEGRAM_API_ID")
    if not api_id_raw.isdigit():
        raise RuntimeError("TELEGRAM_API_ID должен быть числом")

    webapp_url = _required("WEBAPP_URL").rstrip("/")
    short_name = os.getenv("WEBAPP_SHORT_NAME", "").strip() or None
    if short_name and not re.fullmatch(r"[A-Za-z0-9_]{3,30}", short_name):
        raise RuntimeError("WEBAPP_SHORT_NAME некорректен (латиница, цифры, _; 3–30 символов)")
    if urlparse(webapp_url).scheme != "https":
        raise RuntimeError("WEBAPP_URL должен начинаться с https:// (требование Telegram)")

    # Отдельный ключ для подписи сессий. Если SECRET_KEY не задан — выводится из токена бота
    # через HMAC, поэтому сам токен никогда не используется напрямую как ключ сессий.
    secret_raw = os.getenv("SECRET_KEY", "").strip()
    secret_key = hmac.new(
        (secret_raw or bot_token).encode(), b"tg-music-app/session/v1", hashlib.sha256
    ).digest()

    base = Path(__file__).resolve().parent.parent
    return Settings(
        bot_token=bot_token,
        api_id=int(api_id_raw),
        api_hash=_required("TELEGRAM_API_HASH"),
        channel=_normalize_channel(_required("CHANNEL_USERNAME")),
        admin_ids=_parse_ids(os.getenv("ADMIN_IDS", "")),
        webapp_url=webapp_url,
        webapp_short_name=short_name,
        data_dir=Path(os.getenv("DATA_DIR", "/data")),
        static_dir=Path(os.getenv("STATIC_DIR", str(base / "static"))),
        secret_key=secret_key,
        ytdlp_proxy=_proxy(os.getenv("YTDLP_PROXY", "")),
        ytdlp_cookies=_cookies(os.getenv("YTDLP_COOKIES", "")),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
    )
