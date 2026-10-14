"""API панели управления. Доступ только для ADMIN_IDS (проверка на сервере)."""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path as PathParam, Query, Request, status
from pydantic import BaseModel, Field
from telethon.extensions import html as tg_html

from ..config import APP_VERSION
from ..texts import guess_lang, t
from ..userflags import ALBUMS_PREMIUM, upload_limits
from ..validators import (
    AD_BUTTON_MAX, AD_TEXT_MAX, AD_TITLE_MAX, BROADCAST_TEXT_MAX, ValidationError, clean_text,
    normalize_display_name, validate_url,
)
from .deps import Principal, admin_track_out, admin_user, ctx, rate_limit
from .routes import Offset, TrackId

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin")


class HiddenIn(BaseModel):
    hidden: bool


class SyncIn(BaseModel):
    full: bool = False


def _dir_size(path: Path) -> int:
    try:
        return sum(f.stat().st_size for f in path.glob("*") if f.is_file())
    except OSError:
        return 0


@router.get("/stats")
async def stats(request: Request, p: Principal = Depends(admin_user)) -> dict:
    c = ctx(request)
    overview, series, top = await asyncio.gather(
        c.repo.admin_overview(), c.repo.daily_series(14), c.repo.admin_top_tracks(10)
    )
    db_size = sum(
        (c.settings.db_path.parent / n).stat().st_size
        for n in (c.settings.db_path.name, c.settings.db_path.name + "-wal")
        if (c.settings.db_path.parent / n).exists()
    )
    covers_size = await asyncio.to_thread(_dir_size, c.settings.covers_dir)
    last_sync = await c.repo.get_meta("last_sync")
    return {
        "overview": overview,
        "series": series,
        "top": [admin_track_out(r, c.tg) for r in top],
        "system": {
            "version": APP_VERSION,
            "telegram_ready": c.tg.ready.is_set(),
            "channel": c.tg.channel.title,
            "bot": c.tg.bot_username,
            "db_size": db_size,
            "covers_size": covers_size,
            "last_sync": int(last_sync) if last_sync else None,
            "history_floor": c.tg.history_floor,
        },
        "sync": c.tg.sync_state.as_dict(),
    }


@router.get("/tracks")
async def tracks(
    request: Request,
    p: Principal = Depends(admin_user),
    q: Annotated[str, Query(max_length=100)] = "",
    offset: Offset = 0,
    limit: Annotated[int, Query(ge=1, le=50)] = 30,
) -> dict:
    c = ctx(request)
    rows = await c.repo.admin_tracks(q.strip(), offset, limit)
    return {"items": [admin_track_out(r, c.tg) for r in rows], "next_offset": offset + len(rows) if len(rows) == limit else None}


@router.post("/tracks/{track_id}/hidden", status_code=204)
async def set_hidden(track_id: TrackId, body: HiddenIn, request: Request, p: Principal = Depends(admin_user)) -> None:
    if not await ctx(request).repo.set_hidden(track_id, body.hidden):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Трек не найден")
    log.info("Админ %s: трек %s hidden=%s", p.user_id, track_id, body.hidden)


@router.post("/sync")
async def sync(body: SyncIn, request: Request, p: Principal = Depends(admin_user)) -> dict:
    c = ctx(request)
    rate_limit(request, f"admin-sync:{p.user_id}", 5)
    started = c.tg.start_sync(full=body.full)
    log.info("Админ %s запустил синхронизацию (full=%s): %s", p.user_id, body.full, started)
    return {"started": started, "sync": c.tg.sync_state.as_dict()}


@router.get("/users")
async def users(
    request: Request, p: Principal = Depends(admin_user), offset: Offset = 0,
    limit: Annotated[int, Query(ge=1, le=50)] = 30,
    q: Annotated[str, Query(max_length=64)] = "",
    filter: Literal["all", "vip", "banned", "restricted"] = "all",
) -> dict:
    c = ctx(request)
    rows = await c.repo.admin_users(q, filter, offset, limit)
    for r in rows:
        r["is_admin"] = c.settings.is_admin(r["id"])
    return {"items": rows, "next_offset": offset + len(rows) if len(rows) == limit else None}


UserId = Annotated[int, PathParam(ge=1, le=2**53)]


class UserPatch(BaseModel):
    display_name: str | None = Field(default=None, max_length=100)  # "" — сбросить на имя из Telegram
    vip: bool | None = None
    banned: bool | None = None
    no_albums: bool | None = None
    no_uploads: bool | None = None
    reason: str | None = Field(default=None, max_length=500)
    notify: bool = True


async def _user_detail(request: Request, user_id: int) -> dict:
    c = ctx(request)
    row = await c.repo.admin_user(user_id)
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user_not_found")
    row["is_admin"] = c.settings.is_admin(user_id)
    return row


@router.get("/users/{user_id}")
async def user_detail(user_id: UserId, request: Request, p: Principal = Depends(admin_user)) -> dict:
    return await _user_detail(request, user_id)


@router.patch("/users/{user_id}")
async def update_user(user_id: UserId, body: UserPatch, request: Request,
                      p: Principal = Depends(admin_user)) -> dict:
    """Premium, блокировка, ограничения и имя в приложении. Пользователь получает уведомление в боте."""
    c = ctx(request)
    rate_limit(request, f"admin-users:{p.user_id}", 60)
    user = await _user_detail(request, user_id)
    changes: dict[str, Any] = {}
    for key in ("vip", "banned", "no_albums", "no_uploads"):
        value = getattr(body, key)
        if value is not None and value != bool(user[key]):
            changes[key] = value
    if user["is_admin"] and any(changes.get(k) for k in ("banned", "no_albums", "no_uploads")):
        raise HTTPException(status.HTTP_409_CONFLICT, "user_is_admin")
    if body.display_name is not None:
        try:
            name = normalize_display_name(body.display_name) if body.display_name.strip() else None
        except ValidationError as exc:
            raise HTTPException(422, exc.code) from None
        if name != user["display_name"]:
            changes["display_name"] = name
    try:
        reason = clean_text(body.reason, 300, code="reason")
    except ValidationError as exc:
        raise HTTPException(422, exc.code) from None
    if changes:
        await c.repo.set_user_flags(user_id, changes)
        log.info("Админ %s изменил пользователя %s: %s", p.user_id, user_id, sorted(changes))
        if body.notify and user["started_bot"]:
            c.tg.spawn(_notify_user(c, user_id, changes, reason), "user-flags-notify")
    return await _user_detail(request, user_id)


async def _notify_user(c, user_id: int, changes: dict[str, Any], reason: str) -> None:
    """Одно сообщение со всеми изменениями. Тексты экранируются (HTML-разметка бота)."""
    user = await c.repo.get_user(user_id) or {}
    lang = user.get("lang") or guess_lang(user.get("language_code"))
    lines = []
    for key in ("banned", "vip", "no_albums", "no_uploads"):
        if key in changes:
            lim = upload_limits(c.repo.flags.get(user_id))
            lines.append(t(lang, f"flag_{key}_{'on' if changes[key] else 'off'}", albums=ALBUMS_PREMIUM, **lim))
    if "display_name" in changes:
        name = changes["display_name"]
        lines.append(t(lang, "flag_name", name=tg_html.escape(name)) if name else t(lang, "flag_name_reset"))
    if not lines:
        return
    text = t(lang, "flags_title") + "\n\n" + "\n".join(lines)
    if reason:
        text += "\n\n" + t(lang, "flags_reason", reason=tg_html.escape(reason))
    # заблокированному не даём кнопку открытия приложения
    markup = None if c.repo.flags.get(user_id).banned else c.tg._webapp_markup(t(lang, "open"))
    await c.tg.send_to_user(user_id, user.get("access_hash"), text, markup)


# ================================================================== реклама
TS_MAX = 4_102_444_800  # 2100-01-01


class AdIn(BaseModel):
    placement: Literal["home", "library"]
    title: str = Field(max_length=200)
    text: str = Field(default="", max_length=1000)
    button_text: str | None = Field(default=None, max_length=100)
    button_url: str | None = Field(default=None, max_length=600)
    is_active: bool = True
    show_from: int | None = Field(default=None, ge=0, le=TS_MAX)
    show_until: int | None = Field(default=None, ge=0, le=TS_MAX)


def _validated_ad(body: AdIn) -> dict[str, Any]:
    try:
        title = clean_text(body.title, AD_TITLE_MAX, required=True, code="ad_title")
        text = clean_text(body.text, AD_TEXT_MAX, code="ad_text")
        button_text = clean_text(body.button_text, AD_BUTTON_MAX, code="ad_button") or None
        button_url = validate_url(body.button_url) if (body.button_url or "").strip() else None
    except ValidationError as exc:
        raise HTTPException(422, exc.code) from None
    if bool(button_text) != bool(button_url):
        raise HTTPException(422, "ad_button_pair")
    if body.show_from and body.show_until and body.show_until <= body.show_from:
        raise HTTPException(422, "ad_period")
    return {
        "placement": body.placement, "title": title, "text": text, "button_text": button_text,
        "button_url": button_url, "is_active": body.is_active,
        "show_from": body.show_from or None, "show_until": body.show_until or None,
    }


def _ad_out(row: dict[str, Any]) -> dict[str, Any]:
    ts = time.time()
    if not row["is_active"]:
        state = "hidden"
    elif row["show_until"] and row["show_until"] <= ts:
        state = "expired"
    elif row["show_from"] and row["show_from"] > ts:
        state = "scheduled"
    else:
        state = "active"
    return {**row, "is_active": bool(row["is_active"]), "state": state}


@router.get("/ads")
async def list_ads(request: Request, p: Principal = Depends(admin_user)) -> dict:
    return {"items": [_ad_out(r) for r in await ctx(request).repo.admin_ads()]}


@router.post("/ads", status_code=201)
async def create_ad(body: AdIn, request: Request, p: Principal = Depends(admin_user)) -> dict:
    rate_limit(request, f"admin-ads:{p.user_id}", 30)
    ad_id = await ctx(request).repo.create_ad(_validated_ad(body), p.user_id)
    log.info("Админ %s создал рекламный блок %s", p.user_id, ad_id)
    return {"id": ad_id}


@router.put("/ads/{ad_id}", status_code=204)
async def update_ad(ad_id: TrackId, body: AdIn, request: Request, p: Principal = Depends(admin_user)) -> None:
    rate_limit(request, f"admin-ads:{p.user_id}", 60)
    if not await ctx(request).repo.update_ad(ad_id, _validated_ad(body)):
        raise HTTPException(404, "ad_not_found")


@router.delete("/ads/{ad_id}", status_code=204)
async def delete_ad(ad_id: TrackId, request: Request, p: Principal = Depends(admin_user)) -> None:
    if not await ctx(request).repo.delete_ad(ad_id):
        raise HTTPException(404, "ad_not_found")
    log.info("Админ %s удалил рекламный блок %s", p.user_id, ad_id)


# ================================================================== рассылка
class BroadcastIn(BaseModel):
    text: str = Field(max_length=5000)
    button_text: str | None = Field(default=None, max_length=100)
    button_url: str | None = Field(default=None, max_length=600)
    with_app_button: bool = True
    audience: Literal["all", "ru", "en"] = "all"


def _validated_broadcast(body: BroadcastIn) -> dict[str, Any]:
    try:
        text = clean_text(body.text, BROADCAST_TEXT_MAX, multiline=True, required=True, code="bc_text")
        button_text = clean_text(body.button_text, AD_BUTTON_MAX, code="ad_button") or None
        button_url = validate_url(body.button_url) if (body.button_url or "").strip() else None
    except ValidationError as exc:
        raise HTTPException(422, exc.code) from None
    if bool(button_text) != bool(button_url):
        raise HTTPException(422, "ad_button_pair")
    try:
        plain, _ = tg_html.parse(text)
    except Exception:
        raise HTTPException(422, "bc_html") from None
    if not plain.strip():
        raise HTTPException(422, "bc_text_empty")
    return {"text": text, "button_text": button_text, "button_url": button_url,
            "with_app_button": body.with_app_button, "audience": body.audience}


@router.get("/broadcasts")
async def broadcasts(request: Request, p: Principal = Depends(admin_user)) -> dict:
    c = ctx(request)
    items, sizes = await asyncio.gather(c.repo.broadcasts(20), c.repo.audience_sizes())
    return {"items": items, "running": c.tg.broadcast_running, "audience": sizes}


@router.post("/broadcasts/test")
async def broadcast_test(body: BroadcastIn, request: Request, p: Principal = Depends(admin_user)) -> dict:
    c = ctx(request)
    rate_limit(request, f"admin-bc-test:{p.user_id}", 10)
    if not c.tg.ready.is_set():
        raise HTTPException(503, "telegram_offline")
    result = await c.tg.send_broadcast_test(p.user_id, _validated_broadcast(body))
    return {"result": result}


@router.post("/broadcasts", status_code=201)
async def start_broadcast(body: BroadcastIn, request: Request, p: Principal = Depends(admin_user)) -> dict:
    c = ctx(request)
    rate_limit(request, f"admin-bc:{p.user_id}", 5, 600)
    data = _validated_broadcast(body)
    if c.tg.broadcast_running:
        raise HTTPException(409, "bc_running")
    if not c.tg.ready.is_set():
        raise HTTPException(503, "telegram_offline")
    bid = await c.repo.create_broadcast(data, p.user_id)
    c.tg.start_broadcast(bid)
    log.info("Админ %s запустил рассылку #%s (%s)", p.user_id, bid, data["audience"])
    return {"id": bid}


@router.post("/broadcasts/cancel", status_code=204)
async def cancel_broadcast(request: Request, p: Principal = Depends(admin_user)) -> None:
    if not ctx(request).tg.cancel_broadcast():
        raise HTTPException(409, "bc_not_running")


# ================================================================== настройки
class SettingsIn(BaseModel):
    maintenance: bool
    maintenance_text: str = Field(default="", max_length=600)


@router.get("/settings")
async def get_settings(request: Request, p: Principal = Depends(admin_user)) -> dict:
    rt = ctx(request).runtime
    return {"maintenance": rt.maintenance, "maintenance_text": rt.maintenance_text, "theme": rt.theme}


class ThemeIn(BaseModel):
    theme: Literal["default", "auto", "autumn", "winter", "spring", "summer"]


@router.put("/settings/theme")
async def put_theme(body: ThemeIn, request: Request, p: Principal = Depends(admin_user)) -> dict:
    c = ctx(request)
    rate_limit(request, f"admin-settings:{p.user_id}", 30)
    await c.runtime.set_theme(c.repo, body.theme)
    log.info("Админ %s: тема оформления = %s", p.user_id, body.theme)
    return {"theme": c.runtime.theme}


@router.put("/settings")
async def put_settings(body: SettingsIn, request: Request, p: Principal = Depends(admin_user)) -> dict:
    c = ctx(request)
    rate_limit(request, f"admin-settings:{p.user_id}", 30)
    try:
        text = clean_text(body.maintenance_text, 300, multiline=True, code="maint_text")
    except ValidationError as exc:
        raise HTTPException(422, exc.code) from None
    await c.runtime.save(c.repo, maintenance=body.maintenance, maintenance_text=text)
    log.warning("Админ %s: режим обслуживания = %s", p.user_id, body.maintenance)
    return {"maintenance": c.runtime.maintenance, "maintenance_text": c.runtime.maintenance_text,
            "theme": c.runtime.theme}
