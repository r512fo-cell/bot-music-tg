"""Публичное API мини-приложения."""
from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path as PathParam, Query, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .. import covers
from ..security import AuthError, issue_token, validate_init_data
from ..texts import guess_lang
from ..userflags import Flags, album_limit, upload_limits
from ..validators import ALBUM_ICONS, ALBUM_NAME_MAX, ALBUM_PUNCT, LANGS
from .deps import Principal, album_out, bearer_user, client_ip, ctx, current_user, media_user, rate_limit, track_out

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

TrackId = Annotated[int, PathParam(ge=1, le=2**53)]
Offset = Annotated[int, Query(ge=0, le=100_000)]

AVATAR_TTL = 24 * 3600
AVATAR_MISS_TTL = 30 * 60
_avatar_locks: dict[int, asyncio.Lock] = {}
_avatar_misses: dict[int, float] = {}


class AuthIn(BaseModel):
    init_data: str = Field(min_length=10, max_length=4096)


class SettingsIn(BaseModel):
    lang: Literal["ru", "en"]


def _profile(user: dict, is_admin: bool, flags: Flags) -> dict:
    return {
        "id": user["id"],
        "first_name": user["first_name"],
        "last_name": user["last_name"],
        "username": user["username"],
        "is_premium": bool(user["is_premium"]),
        "created_at": user["created_at"],
        "is_admin": is_admin,
        "lang": user.get("lang") if user.get("lang") in LANGS else guess_lang(user.get("language_code")),
        "lang_chosen": user.get("lang") in LANGS,
        "display_name": flags.display_name,
        "vip": flags.vip,
        "restrictions": {"albums": flags.no_albums and not is_admin, "uploads": flags.no_uploads and not is_admin},
    }


def _client_config(request: Request, is_admin: bool, flags: Flags) -> dict:
    c = ctx(request)
    return {
        "bot_username": c.tg.bot_username,
        "share_base": c.tg.share_base,
        "album_limit": album_limit(flags, is_admin),
        "upload_limits": upload_limits(flags, is_admin),
        "album_name_max": ALBUM_NAME_MAX,
        "album_punct": "".join(sorted(ALBUM_PUNCT - {" "})),
        "album_icons": list(ALBUM_ICONS),
        "maintenance": c.runtime.maintenance,
        "maintenance_text": c.runtime.maintenance_text,
        "theme": c.runtime.theme,
    }


@router.post("/auth")
async def auth(body: AuthIn, request: Request) -> dict:
    c = ctx(request)
    rate_limit(request, f"auth:{client_ip(request)}", 30, by_ip=True)
    try:
        tg_user = validate_init_data(body.init_data, c.settings.bot_token, c.settings.init_data_ttl)
    except AuthError as exc:
        log.info("Отклонена авторизация с %s: %s", client_ip(request), exc)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Не удалось подтвердить данные Telegram") from None
    is_admin = c.settings.is_admin(tg_user.id)
    flags = c.repo.flags.get(tg_user.id)
    if flags.banned and not is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "banned")
    user = await c.repo.upsert_user(tg_user)
    token, exp = issue_token(tg_user.id, c.settings.secret_key, c.settings.session_ttl)
    return {
        "token": token,
        "expires_at": exp,
        "user": _profile(user, is_admin, flags),
        "config": _client_config(request, is_admin, flags),
    }


@router.put("/me/settings", status_code=204)
async def update_settings(body: SettingsIn, request: Request, p: Principal = Depends(bearer_user)) -> None:
    """Язык интерфейса (доступно и в режиме обслуживания — заглушка тоже переводится)."""
    c = ctx(request)
    rate_limit(request, f"settings:{p.user_id}", 20)
    await c.repo.set_lang(p.user_id, body.lang)
    user = await c.repo.get_user(p.user_id) or {}
    if user.get("started_bot"):
        c.tg.spawn(c.tg.set_user_menu(p.user_id, body.lang, user.get("access_hash")), "user-menu")


@router.get("/home")
async def home(request: Request, p: Principal = Depends(current_user)) -> dict:
    c = ctx(request)
    reco_ids = await request.app.state.recommender.for_user(p.user_id, 10)
    new, popular, albums, recent, tags, recommended = await asyncio.gather(
        c.repo.list_tracks(p.user_id, sort="new", limit=5),
        c.repo.popular(p.user_id, limit=10),
        c.repo.public_albums(0, 5),
        c.repo.history(p.user_id, limit=10),
        c.repo.top_tags(16),
        c.repo.tracks_by_ids(p.user_id, reco_ids),
    )
    return {
        "new": [track_out(r, c.tg) for r in new],
        "recommended": [track_out(r, c.tg) for r in recommended],
        "popular": [track_out(r, c.tg) for r in popular],
        "albums": [album_out(r) for r in albums],
        "recent": [track_out(r, c.tg) for r in recent],
        "tags": tags,
        "channel": {"title": c.tg.channel.title, "url": f"https://t.me/{c.tg.channel.username}" if c.tg.channel.username else None},
    }


@router.get("/tracks")
async def tracks(
    request: Request,
    p: Principal = Depends(current_user),
    sort: Literal["new", "popular", "title"] = "new",
    tag: Annotated[str | None, Query(max_length=32, pattern=r"^[\w]+$")] = None,
    offset: Offset = 0,
    limit: Annotated[int, Query(ge=1, le=50)] = 30,
) -> dict:
    c = ctx(request)
    rows = await c.repo.list_tracks(p.user_id, sort=sort, tag=tag.casefold() if tag else None, offset=offset, limit=limit)
    return {"items": [track_out(r, c.tg) for r in rows], "next_offset": offset + len(rows) if len(rows) == limit else None}


@router.get("/tracks/{track_id}")
async def track(track_id: TrackId, request: Request, p: Principal = Depends(current_user)) -> dict:
    c = ctx(request)
    row = await c.repo.get_track(track_id, p.user_id)
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Трек не найден")
    return track_out(row, c.tg)


@router.get("/search")
async def search(
    request: Request,
    q: Annotated[str, Query(min_length=1, max_length=100)],
    p: Principal = Depends(current_user),
    offset: Offset = 0,
    limit: Annotated[int, Query(ge=1, le=50)] = 30,
) -> dict:
    c = ctx(request)
    rate_limit(request, f"search:{p.user_id}", 60)
    rows = await c.repo.search(p.user_id, q.strip(), offset=offset, limit=limit)
    return {"items": [track_out(r, c.tg) for r in rows], "next_offset": offset + len(rows) if len(rows) == limit else None}


@router.post("/tracks/{track_id}/play", status_code=204)
async def play(track_id: TrackId, request: Request, p: Principal = Depends(current_user)) -> None:
    rate_limit(request, f"play:{p.user_id}", 30)
    await ctx(request).repo.register_play(p.user_id, track_id)


@router.put("/tracks/{track_id}/like", status_code=204)
async def like(track_id: TrackId, request: Request, p: Principal = Depends(current_user)) -> None:
    rate_limit(request, f"like:{p.user_id}", 60)
    if not await ctx(request).repo.add_favorite(p.user_id, track_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Трек не найден")


@router.delete("/tracks/{track_id}/like", status_code=204)
async def unlike(track_id: TrackId, request: Request, p: Principal = Depends(current_user)) -> None:
    rate_limit(request, f"like:{p.user_id}", 60)
    await ctx(request).repo.remove_favorite(p.user_id, track_id)


@router.get("/me")
async def me(request: Request, p: Principal = Depends(current_user)) -> dict:
    c = ctx(request)
    user = await c.repo.get_user(p.user_id)
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Пользователь не найден")
    await c.repo.touch_user(p.user_id)
    stats = await c.repo.user_stats(p.user_id)
    return {**_profile(user, p.is_admin, p.flags), "stats": stats,
            "config": {"album_limit": album_limit(p.flags, p.is_admin),
                       "upload_limits": upload_limits(p.flags, p.is_admin)}}


@router.get("/me/favorites")
async def my_favorites(
    request: Request, p: Principal = Depends(current_user), offset: Offset = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict:
    c = ctx(request)
    rows = await c.repo.favorites(p.user_id, offset=offset, limit=limit)
    return {"items": [track_out(r, c.tg) for r in rows], "next_offset": offset + len(rows) if len(rows) == limit else None}


@router.get("/me/history")
async def my_history(request: Request, p: Principal = Depends(current_user)) -> dict:
    c = ctx(request)
    rows = await c.repo.history(p.user_id, limit=30)
    return {"items": [track_out(r, c.tg) for r in rows]}


@router.get("/me/avatar")
async def my_avatar(request: Request, p: Principal = Depends(media_user)) -> FileResponse:
    c = ctx(request)
    rate_limit(request, f"avatar:{p.user_id}", 20)
    path = c.settings.avatars_dir / f"{p.user_id}.webp"
    fresh = path.exists() and time.time() - path.stat().st_mtime < AVATAR_TTL
    if not fresh and time.time() - _avatar_misses.get(p.user_id, 0) > AVATAR_MISS_TTL:
        lock = _avatar_locks.setdefault(p.user_id, asyncio.Lock())
        try:
            async with lock:
                if not (path.exists() and time.time() - path.stat().st_mtime < AVATAR_TTL):
                    user = await c.repo.get_user(p.user_id) or {}
                    raw = None
                    try:
                        raw = await c.tg.fetch_avatar(p.user_id, user.get("access_hash"))
                    except Exception as exc:  # аватар — не повод отдавать 500
                        log.debug("Аватар %s не получен: %s", p.user_id, type(exc).__name__)
                    if raw and await asyncio.to_thread(covers.process_avatar, raw, path):
                        _avatar_misses.pop(p.user_id, None)
                    else:
                        _avatar_misses[p.user_id] = time.time()
        finally:
            _avatar_locks.pop(p.user_id, None)
            if len(_avatar_misses) > 10_000:
                _avatar_misses.clear()
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Нет аватара")
    return FileResponse(path, media_type="image/webp", headers={"Cache-Control": "private, max-age=3600"})


# ------------------------------------------------------------------ реклама
@router.get("/ads")
async def ads(
    request: Request,
    placement: Literal["home", "library"],
    p: Principal = Depends(current_user),
) -> dict:
    c = ctx(request)
    rows = await c.repo.active_ads(placement)
    if not rows:
        return {"ad": None}
    ad = random.choice(rows)
    if c.limiter.hit(f"ad-imp:{p.user_id}:{ad['id']}", 1, 60):  # не накручиваем показы
        await c.repo.ad_hit(ad["id"], "impressions")
    return {"ad": {k: ad[k] for k in ("id", "placement", "title", "text", "button_text", "button_url")}}


@router.post("/ads/{ad_id}/click", status_code=204)
async def ad_click(ad_id: TrackId, request: Request, p: Principal = Depends(current_user)) -> None:
    c = ctx(request)
    # ключ лимитера создаём только для реально существующей рекламы
    if await c.repo.ad_is_active(ad_id) and c.limiter.hit(f"ad-click:{p.user_id}:{ad_id}", 1, 60):
        await c.repo.ad_hit(ad_id, "clicks")
