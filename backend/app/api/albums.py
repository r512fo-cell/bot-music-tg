"""Альбомы пользователя: создание, переименование, треки, «поделиться»."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path as PathParam, Query, Request, status
from pydantic import BaseModel, Field

from ..userflags import album_limit
from ..validators import ALBUM_TRACKS_MAX, ValidationError, album_name_key, normalize_album_name, validate_icon
from .deps import Principal, album_out, ctx, current_user, rate_limit, track_out
from .routes import TrackId

router = APIRouter(prefix="/api")
AlbumId = Annotated[int, PathParam(ge=1, le=2**53)]
ShareCode = Annotated[str, PathParam(pattern=r"^[A-Za-z0-9_-]{8,16}$")]


class AlbumIn(BaseModel):
    name: str = Field(max_length=200)
    icon: str = Field(max_length=16)
    track_id: int | None = Field(default=None, ge=1, le=2**53)


class VisibilityIn(BaseModel):
    public: bool


class AlbumPatch(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    icon: str | None = Field(default=None, max_length=16)


def _bad(code: str, http: int = 422) -> HTTPException:
    return HTTPException(http, code)


def _limit(p: Principal) -> int:
    return album_limit(p.flags, p.is_admin)


def _writable(p: Principal) -> None:
    """Администратор может ограничить пользователю создание и изменение альбомов."""
    if p.flags.no_albums and not p.is_admin:
        raise _bad("albums_restricted", status.HTTP_403_FORBIDDEN)


async def _own_album(request: Request, album_id: int, p: Principal) -> dict:
    album = await ctx(request).repo.album(album_id)
    if not album or album["user_id"] != p.user_id:  # чужие альбомы неотличимы от несуществующих
        raise _bad("album_not_found", status.HTTP_404_NOT_FOUND)
    return album


@router.get("/albums")
async def list_albums(
    request: Request,
    p: Principal = Depends(current_user),
    track_id: Annotated[int | None, Query(ge=1, le=2**53)] = None,
) -> dict:
    rows = await ctx(request).repo.albums(p.user_id, track_id)
    return {"items": [album_out(r) for r in rows], "limit": _limit(p)}


@router.post("/albums", status_code=201)
async def create_album(body: AlbumIn, request: Request, p: Principal = Depends(current_user)) -> dict:
    c = ctx(request)
    rate_limit(request, f"album-write:{p.user_id}", 30)
    _writable(p)
    try:
        name = normalize_album_name(body.name)
        icon = validate_icon(body.icon)
    except ValidationError as exc:
        raise _bad(exc.code) from None
    if body.track_id and not await c.repo.get_track(body.track_id, None):
        raise _bad("track_not_found", status.HTTP_404_NOT_FOUND)
    try:
        album_id = await c.repo.create_album(
            p.user_id, name, album_name_key(name), icon, _limit(p),
            [body.track_id] if body.track_id else None,
        )
    except LookupError as exc:
        raise _bad(str(exc.args[0]), status.HTTP_409_CONFLICT) from None
    return album_out(await c.repo.album(album_id))


@router.patch("/albums/{album_id}")
async def update_album(album_id: AlbumId, body: AlbumPatch, request: Request,
                       p: Principal = Depends(current_user)) -> dict:
    c = ctx(request)
    rate_limit(request, f"album-write:{p.user_id}", 30)
    _writable(p)
    await _own_album(request, album_id, p)
    try:
        name = normalize_album_name(body.name) if body.name is not None else None
        icon = validate_icon(body.icon) if body.icon is not None else None
    except ValidationError as exc:
        raise _bad(exc.code) from None
    try:
        await c.repo.update_album(album_id, p.user_id, name, album_name_key(name) if name else None, icon)
    except LookupError as exc:
        raise _bad(str(exc.args[0]), status.HTTP_409_CONFLICT) from None
    return album_out(await c.repo.album(album_id))


@router.delete("/albums/{album_id}", status_code=204)
async def delete_album(album_id: AlbumId, request: Request, p: Principal = Depends(current_user)) -> None:
    rate_limit(request, f"album-write:{p.user_id}", 30)
    if not await ctx(request).repo.delete_album(album_id, p.user_id):
        raise _bad("album_not_found", status.HTTP_404_NOT_FOUND)


@router.get("/albums/{album_id}")
async def get_album(album_id: AlbumId, request: Request, p: Principal = Depends(current_user)) -> dict:
    c = ctx(request)
    album = await _own_album(request, album_id, p)
    rows = await c.repo.album_tracks(album_id, p.user_id)
    return {"album": album_out(album), "tracks": [track_out(r, c.tg) for r in rows], "own": True}


@router.put("/albums/{album_id}/tracks/{track_id}", status_code=204)
async def add_track(album_id: AlbumId, track_id: TrackId, request: Request,
                    p: Principal = Depends(current_user)) -> None:
    rate_limit(request, f"album-tracks:{p.user_id}", 120)
    _writable(p)
    try:
        await ctx(request).repo.album_add_track(album_id, p.user_id, track_id, ALBUM_TRACKS_MAX)
    except KeyError as exc:
        raise _bad(f"{exc.args[0]}_not_found", status.HTTP_404_NOT_FOUND) from None
    except LookupError as exc:
        raise _bad(str(exc.args[0]), status.HTTP_409_CONFLICT) from None


@router.delete("/albums/{album_id}/tracks/{track_id}", status_code=204)
async def remove_track(album_id: AlbumId, track_id: TrackId, request: Request,
                       p: Principal = Depends(current_user)) -> None:
    rate_limit(request, f"album-tracks:{p.user_id}", 120)
    try:
        await ctx(request).repo.album_remove_track(album_id, p.user_id, track_id)
    except KeyError:
        raise _bad("album_not_found", status.HTTP_404_NOT_FOUND) from None


@router.post("/albums/{album_id}/share")
async def share_album(album_id: AlbumId, request: Request, p: Principal = Depends(current_user)) -> dict:
    c = ctx(request)
    rate_limit(request, f"album-share:{p.user_id}", 20)
    _writable(p)
    try:
        code = await c.repo.album_share_code(album_id, p.user_id)
    except KeyError:
        raise _bad("album_not_found", status.HTTP_404_NOT_FOUND) from None
    return {"param": f"a_{code}"}


@router.post("/albums/{album_id}/visibility")
async def album_visibility(album_id: AlbumId, body: VisibilityIn, request: Request,
                           p: Principal = Depends(current_user)) -> dict:
    """Открыть / закрыть доступ. Администратор может закрыть любой публичный альбом (модерация)."""
    c = ctx(request)
    rate_limit(request, f"album-write:{p.user_id}", 30)
    if body.public:
        _writable(p)
    album = await c.repo.album(album_id)
    if not album or (album["user_id"] != p.user_id and not (p.is_admin and not body.public)):
        raise _bad("album_not_found", status.HTTP_404_NOT_FOUND)
    owner = None if album["user_id"] != p.user_id else p.user_id
    row = await c.repo.set_album_public(album_id, owner, body.public)
    return album_out(row)


@router.get("/public/albums")
async def public_albums(
    request: Request, p: Principal = Depends(current_user),
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> dict:
    rows = await ctx(request).repo.public_albums(offset, limit)
    return {"items": [album_out(r) for r in rows], "next_offset": offset + len(rows) if len(rows) == limit else None}


# ------------------------------------------------------------------ чужие (по ссылке)
async def _shared(request: Request, code: str, p: Principal) -> dict:
    album = await ctx(request).repo.album_by_code(code)
    own = bool(album) and album["user_id"] == p.user_id
    # закрытый альбом и альбомы заблокированных пользователей видны только владельцу
    if not album or (not own and (not album["is_public"] or album.get("owner_banned"))):
        raise _bad("album_not_found", status.HTTP_404_NOT_FOUND)
    return album


@router.get("/shared/albums/{code}")
async def shared_album(code: ShareCode, request: Request, p: Principal = Depends(current_user)) -> dict:
    c = ctx(request)
    rate_limit(request, f"shared:{p.user_id}", 60)
    album = await _shared(request, code, p)
    own = album["user_id"] == p.user_id
    if album["is_public"] and not own and await c.repo.count_album_view(album["id"], p.user_id):
        album["views"] = (album.get("views") or 0) + 1
    rows = await c.repo.album_tracks(album["id"], p.user_id)
    out = album_out(album)
    return {"album": out, "tracks": [track_out(r, c.tg) for r in rows], "own": own}


@router.post("/shared/albums/{code}/save", status_code=201)
async def save_shared(code: ShareCode, request: Request, p: Principal = Depends(current_user)) -> dict:
    """Сохранить копию чужого альбома к себе (с учётом лимита и уникальности имени)."""
    c = ctx(request)
    rate_limit(request, f"album-write:{p.user_id}", 30)
    _writable(p)
    album = await _shared(request, code, p)
    if album["user_id"] == p.user_id:
        raise _bad("album_own", status.HTTP_409_CONFLICT)
    ids = await c.repo.album_track_ids(album["id"])
    try:
        new_id = await c.repo.create_album_unique(p.user_id, album["name"], album["icon"], _limit(p), ids)
    except LookupError as exc:
        raise _bad(str(exc.args[0]), status.HTTP_409_CONFLICT) from None
    return album_out(await c.repo.album(new_id))
