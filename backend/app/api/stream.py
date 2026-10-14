"""Проксирование аудио из Telegram с поддержкой HTTP Range (перемотка).

Файл не сохраняется на диск: байты читаются из Telegram блоками и сразу
отдаются клиенту. Ограничено число одновременных потоков на пользователя
и на сервер, чтобы слабый хостинг не перегружался.
"""
from __future__ import annotations

import asyncio
import logging
import re
import weakref
from collections import defaultdict
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response, StreamingResponse

from ..telegram import TrackUnavailable
from .deps import Principal, ctx, media_user, rate_limit
from .routes import TrackId

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")
MIME_RE = re.compile(r"^audio/[a-z0-9.+-]{1,40}$")

_active_per_user: defaultdict[int, int] = defaultdict(int)
_active_total = 0


def _parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    """Возвращает (start, end) включительно, None — весь файл. ValueError — некорректный диапазон."""
    if not header:
        return None
    m = RANGE_RE.match(header.strip().split(",")[0].strip())
    if not m:
        raise ValueError("bad range")
    a, b = m.groups()
    if a == "" and b == "":
        raise ValueError("bad range")
    if a == "":  # суффикс: последние N байт
        n = int(b)
        if n == 0:
            raise ValueError("bad range")
        return max(size - n, 0), size - 1
    start = int(a)
    end = int(b) if b else size - 1
    if start >= size or end < start:
        raise ValueError("unsatisfiable")
    return start, min(end, size - 1)


class _Slot:
    """Место в лимите одновременных потоков. Занимается сразу при проверке (до любых await),
    иначе параллельные запросы успевают пройти проверку раньше, чем кто-то увеличит счётчик."""

    def __init__(self, user_id: int) -> None:
        global _active_total
        self.user_id = user_id
        self.held = True
        _active_per_user[user_id] += 1
        _active_total += 1

    def release(self) -> None:
        global _active_total
        if not self.held:
            return
        self.held = False
        _active_total -= 1
        _active_per_user[self.user_id] -= 1
        if _active_per_user[self.user_id] <= 0:
            _active_per_user.pop(self.user_id, None)


def _acquire(c, user_id: int) -> _Slot:
    if _active_per_user.get(user_id, 0) >= c.settings.stream_per_user:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Слишком много одновременных потоков")
    if _active_total >= c.settings.stream_concurrency:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Сервер перегружен, попробуйте позже",
                            headers={"Retry-After": "5"})
    return _Slot(user_id)
    if not c.tg.ready.is_set():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Telegram временно недоступен",
                            headers={"Retry-After": "5"})


def _range_response(request: Request, slot: _Slot, size: int, mime: str, chunks, label: str) -> Response:
    """Ответ с поддержкой Range: chunks(start, end) -> async-итератор байтов."""
    if size <= 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Файл недоступен")
    try:
        rng = _parse_range(request.headers.get("range"), size)
    except ValueError:
        slot.release()
        return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
    start, end = rng if rng else (0, size - 1)
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(end - start + 1),
        "Cache-Control": "private, max-age=3600",
        "Content-Disposition": "inline",
    }
    if rng:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"

    async def body() -> AsyncIterator[bytes]:
        try:
            async for chunk in chunks(start, end):
                yield chunk
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # обрыв посреди потока: заголовки уже отправлены
            log.warning("Стрим %s прерван: %s", label, type(exc).__name__)
        finally:
            slot.release()

    gen = body()
    # клиент может отключиться до первого байта: тогда генератор не запустится и finally не сработает
    weakref.finalize(gen, slot.release)
    return StreamingResponse(gen, status_code=206 if rng else 200,
                             media_type=mime if MIME_RE.match(mime or "") else "audio/mpeg", headers=headers)


async def _resolved(coro):
    """Документ запрашиваем ДО отправки заголовков, чтобы корректно вернуть ошибку."""
    try:
        return await asyncio.wait_for(coro, timeout=15)
    except TrackUnavailable:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Файл удалён") from None
    except (asyncio.TimeoutError, ConnectionError):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Telegram временно недоступен",
                            headers={"Retry-After": "5"}) from None


@router.get("/stream/{track_id}")
async def stream(track_id: TrackId, request: Request, p: Principal = Depends(media_user)) -> Response:
    c = ctx(request)
    rate_limit(request, f"stream:{p.user_id}", 120)
    track = await c.repo.get_track_raw(track_id)
    if not track or track["is_deleted"] or (track["is_hidden"] and not p.is_admin):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Трек не найден")
    slot = _acquire(c, p.user_id)
    try:
        doc = await _resolved(c.tg.resolve_document(track["message_id"]))
        size = int(doc.size or track["file_size"] or 0)
        return _range_response(request, slot, size, track["mime_type"],
                               lambda a, b: c.tg.stream(track["message_id"], a, b), f"трека {track_id}")
    except BaseException:
        slot.release()
        raise


@router.get("/admin/submissions/files/{file_id}/stream")
async def submission_stream(file_id: TrackId, request: Request, p: Principal = Depends(media_user)) -> Response:
    """Прослушивание предложенного трека администратором — прямо из чата пользователя с ботом."""
    if not p.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Недостаточно прав")
    c = ctx(request)
    rate_limit(request, f"stream:{p.user_id}", 120)
    f = await c.repo.submission_file(file_id)
    if not f:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Файл не найден")

    async def resolve(force: bool = False):
        return await c.tg.user_audio(f["user_id"], f["access_hash"], f["chat_msg_id"], force=force)

    slot = _acquire(c, p.user_id)
    try:
        doc = await _resolved(resolve())
        return _range_response(request, slot, int(doc.size or f["file_size"] or 0), doc.mime_type or "audio/mpeg",
                               lambda a, b: c.tg.stream(0, a, b, resolve=resolve), f"заявки {file_id}")
    except BaseException:
        slot.release()
        raise
