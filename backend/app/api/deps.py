"""Зависимости FastAPI: авторизация, rate limit, сериализация."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Request, status

from ..config import Settings
from ..repo import Repo
from ..runtime import RuntimeSettings
from ..security import AuthError, RateLimiter, verify_token
from ..telegram import TelegramService
from ..userflags import EMPTY, Flags


@dataclass
class Ctx:
    settings: Settings
    repo: Repo
    tg: TelegramService
    limiter: RateLimiter
    runtime: RuntimeSettings
    # отдельный лимитер для ключей по IP: поток запросов с подменёнными адресами
    # не может вытеснить персональные лимиты пользователей
    ip_limiter: RateLimiter


@dataclass(frozen=True)
class Principal:
    user_id: int
    is_admin: bool
    flags: Flags = EMPTY


def ctx(request: Request) -> Ctx:
    return request.app.state.ctx


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def rate_limit(request: Request, key: str, limit: int, window: float = 60.0, *, by_ip: bool = False) -> None:
    c = ctx(request)
    if not (c.ip_limiter if by_ip else c.limiter).hit(key, limit, window):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Слишком много запросов, попробуйте позже")


def _principal_from_token(request: Request, token: str | None) -> Principal:
    c = ctx(request)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Требуется авторизация")
    try:
        uid = verify_token(token, c.settings.secret_key)
    except AuthError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Сессия недействительна") from None
    is_admin = c.settings.is_admin(uid)
    flags = c.repo.flags.get(uid)
    # заблокированный пользователь теряет доступ сразу, не дожидаясь истечения токена
    if flags.banned and not is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "banned")
    return Principal(uid, is_admin, flags)


def _check_maintenance(request: Request, p: Principal) -> None:
    if ctx(request).runtime.maintenance and not p.is_admin:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "maintenance")


def bearer_user(request: Request) -> Principal:
    """Проверка токена без учёта режима обслуживания (для /auth-зависимых настроек)."""
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer":
        token = ""
    p = _principal_from_token(request, token.strip())
    rate_limit(request, f"api:{p.user_id}", 240)
    return p


def current_user(request: Request) -> Principal:
    p = bearer_user(request)
    _check_maintenance(request, p)
    return p


def media_user(request: Request) -> Principal:
    """Для <audio>/<img>, которые не умеют слать заголовки: токен в query-параметре."""
    p = _principal_from_token(request, request.query_params.get("t"))
    _check_maintenance(request, p)
    return p


def admin_user(request: Request) -> Principal:
    p = bearer_user(request)
    if not p.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Недостаточно прав")
    return p


def track_out(row: dict[str, Any], tg: TelegramService) -> dict[str, Any]:
    cover = row.get("cover")
    return {
        "id": row["id"],
        "title": row["title"],
        "performer": row["performer"],
        "duration": row["duration"],
        "cover": {"s": f"/media/covers/{cover}_s.webp", "l": f"/media/covers/{cover}_l.webp"} if cover else None,
        "color": row.get("color"),
        "posted_at": row["posted_at"],
        "plays": row["plays"],
        "likes": row["likes"],
        "liked": bool(row.get("liked")),
        "tags": (row.get("tags") or "").split() if row.get("tags") else [],
        "post_url": tg.post_url(row["message_id"]),
    }


def album_out(row: dict[str, Any], tg: TelegramService | None = None) -> dict[str, Any]:
    covers = (row.get("covers") or "").split()
    return {
        "id": row["id"],
        "name": row["name"],
        "icon": row["icon"],
        "track_count": row.get("track_count") or 0,
        "duration": row.get("duration") or 0,
        "covers": [f"/media/covers/{c}_s.webp" for c in covers[:4]],
        "shared": bool(row.get("share_code")),
        "public": bool(row.get("is_public")),
        "share_param": f"a_{row['share_code']}" if row.get("share_code") and row.get("is_public") else None,
        "owner_name": row.get("owner_name") or None,
        "has_track": bool(row.get("has_track")),
        # счётчик просмотров виден только у открытых альбомов
        "views": int(row.get("views") or 0) if row.get("is_public") else None,
        "owner_vip": bool(row.get("owner_vip")),
        "created_at": row["created_at"],
    }


def admin_track_out(row: dict[str, Any], tg: TelegramService) -> dict[str, Any]:
    out = track_out(row, tg)
    out.update(hidden=bool(row.get("is_hidden")), file_size=row.get("file_size"), mime_type=row.get("mime_type"))
    return out
