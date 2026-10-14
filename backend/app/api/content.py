"""Админ-раздел «Контент»: импорт собственных треков/альбомов с YouTube Music в канал."""
from __future__ import annotations

import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path as PathParam, Query, Request
from pydantic import BaseModel, Field

from ..importer import ImportError_, VIDEO_ID_RE
from ..validators import ValidationError, clean_text
from .deps import Principal, admin_user, ctx, rate_limit

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin/content")
Rid = Annotated[str, PathParam(pattern=r"^[A-Za-z0-9_-]{6,16}$")]


class ResolveIn(BaseModel):
    url: str = Field(min_length=5, max_length=500)


class ImportIn(BaseModel):
    rid: str = Field(pattern=r"^[A-Za-z0-9_-]{6,16}$")
    scope: Literal["track", "page", "all"]
    page: int = Field(default=1, ge=1, le=100)
    video_id: str | None = Field(default=None, max_length=11)
    create_album: bool = False
    album_name: str | None = Field(default=None, max_length=200)
    caption: str = Field(default="", max_length=1000)


def _importer(request: Request):
    return request.app.state.importer


def _err(exc: ImportError_) -> HTTPException:
    code = exc.code
    http = {"yt_url_invalid": 422, "yt_expired": 410, "yt_queue_full": 429, "yt_empty": 404}.get(code, 502)
    if code.startswith("album_"):
        http = 422
    return HTTPException(http, code)


@router.get("/status")
async def status_(request: Request, p: Principal = Depends(admin_user)) -> dict:
    imp = _importer(request)
    return {**imp.available(), "jobs": imp.jobs(), "proxy": bool(ctx(request).settings.ytdlp_proxy),
            "cookies": bool(ctx(request).settings.ytdlp_cookies)}


@router.post("/resolve")
async def resolve(body: ResolveIn, request: Request, p: Principal = Depends(admin_user)) -> dict:
    rate_limit(request, f"yt-resolve:{p.user_id}", 15)
    imp = _importer(request)
    if not imp.available()["available"]:
        raise HTTPException(503, "yt_not_installed")
    try:
        res = await imp.resolve(body.url)
        return await imp.page(res.rid, 1)
    except ImportError_ as exc:
        raise _err(exc) from None


@router.get("/resolve/{rid}")
async def page(rid: Rid, request: Request, p: Principal = Depends(admin_user),
               page: Annotated[int, Query(ge=1, le=100)] = 1) -> dict:
    try:
        return await _importer(request).page(rid, page)
    except ImportError_ as exc:
        raise _err(exc) from None


@router.post("/import", status_code=201)
async def start_import(body: ImportIn, request: Request, p: Principal = Depends(admin_user)) -> dict:
    rate_limit(request, f"yt-import:{p.user_id}", 20)
    if body.scope == "track" and not (body.video_id and VIDEO_ID_RE.match(body.video_id)):
        raise HTTPException(422, "yt_empty")
    c = ctx(request)
    if not c.tg.ready.is_set():
        raise HTTPException(503, "telegram_offline")
    try:
        caption = clean_text(body.caption, 1000, multiline=True, code="bc_text")
    except ValidationError as exc:
        raise HTTPException(422, exc.code) from None
    try:
        job = _importer(request).enqueue(
            body.rid, body.scope, page=body.page, video_id=body.video_id,
            create_album=body.create_album, album_name=body.album_name, caption=caption, admin_id=p.user_id,
        )
    except ImportError_ as exc:
        raise _err(exc) from None
    log.info("Админ %s: импорт %s (%s)", p.user_id, body.scope, body.rid)
    return job.as_dict()


@router.get("/jobs")
async def jobs(request: Request, p: Principal = Depends(admin_user)) -> dict:
    return {"items": _importer(request).jobs()}


@router.post("/jobs/{job_id}/cancel", status_code=204)
async def cancel(job_id: Rid, request: Request, p: Principal = Depends(admin_user)) -> None:
    if not _importer(request).cancel(job_id):
        raise HTTPException(409, "yt_job_not_running")
