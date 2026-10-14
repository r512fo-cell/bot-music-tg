"""Админка: правила скрытия треков, очистка базы треков, заявки пользователей."""
from __future__ import annotations

import asyncio
import logging
import shutil
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path as PathParam, Query, Request
from pydantic import BaseModel, Field

from ..validators import ValidationError, clean_text
from .deps import Principal, admin_user, ctx, rate_limit

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin")
Id = Annotated[int, PathParam(ge=1, le=2**53)]


# ================================================================== правила скрытия
class RuleIn(BaseModel):
    field: Literal["performer", "title"]
    mode: Literal["contains", "exact"] = "exact"
    pattern: str = Field(max_length=200)


def _pattern(raw: str) -> tuple[str, str]:
    try:
        value = clean_text(raw, 100, required=True, code="rule_pattern")
    except ValidationError as exc:
        raise HTTPException(422, exc.code) from None
    key = value.casefold()
    if len(key) < 2:
        raise HTTPException(422, "rule_pattern_short")
    return value, key


@router.get("/hide-rules")
async def list_rules(request: Request, p: Principal = Depends(admin_user)) -> dict:
    return {"items": await ctx(request).repo.hide_rules()}


@router.post("/hide-rules/preview")
async def preview_rule(body: RuleIn, request: Request, p: Principal = Depends(admin_user)) -> dict:
    rate_limit(request, f"rule-preview:{p.user_id}", 60)
    _, key = _pattern(body.pattern)
    return await ctx(request).repo.preview_rule(body.field, body.mode, key)


@router.post("/hide-rules", status_code=201)
async def add_rule(body: RuleIn, request: Request, p: Principal = Depends(admin_user)) -> dict:
    rate_limit(request, f"rule-write:{p.user_id}", 30)
    value, key = _pattern(body.pattern)
    try:
        rule_id, hidden = await ctx(request).repo.add_hide_rule(body.field, body.mode, value, key, p.user_id)
    except LookupError as exc:
        raise HTTPException(409, exc.args[0]) from None
    log.info("Админ %s: правило скрытия %s %s %r (скрыто %s)", p.user_id, body.field, body.mode, value, hidden)
    return {"id": rule_id, "hidden": hidden}


@router.delete("/hide-rules/{rule_id}")
async def delete_rule(rule_id: Id, request: Request, p: Principal = Depends(admin_user)) -> dict:
    try:
        shown = await ctx(request).repo.delete_hide_rule(rule_id)
    except KeyError:
        raise HTTPException(404, "rule_not_found") from None
    return {"shown": shown}


# ================================================================== очистка базы треков
class ClearIn(BaseModel):
    confirm: Literal["CLEAR"]
    skip_history: bool = True  # не подтягивать старые посты канала обратно


@router.post("/tracks/clear")
async def clear_tracks(body: ClearIn, request: Request, p: Principal = Depends(admin_user)) -> dict:
    c = ctx(request)
    rate_limit(request, f"tracks-clear:{p.user_id}", 3, 600)
    if c.tg.sync_state.running:
        raise HTTPException(409, "sync_running")
    result = await c.repo.clear_tracks(body.skip_history)
    if body.skip_history and result["min_message_id"]:
        c.tg.history_floor = max(c.tg.history_floor, result["min_message_id"])
    c.tg.clear_cache()
    request.app.state.recommender.invalidate()
    await asyncio.to_thread(_wipe_dir, c.settings.covers_dir)  # превью обложек больше не нужны
    log.warning("Админ %s очистил базу треков: удалено %s (история скрыта: %s)",
                p.user_id, result["deleted"], body.skip_history)
    return result


def _wipe_dir(path) -> None:
    for f in path.glob("*"):
        if f.is_file():
            f.unlink(missing_ok=True)
        elif f.is_dir():
            shutil.rmtree(f, ignore_errors=True)


@router.post("/tracks/history-reset", status_code=204)
async def history_reset(request: Request, p: Principal = Depends(admin_user)) -> None:
    """Снова разрешить импорт старых постов канала (после очистки)."""
    c = ctx(request)
    await c.repo.set_meta("min_message_id", "0")
    c.tg.history_floor = 0


# ================================================================== заявки пользователей
class ApproveIn(BaseModel):
    exclude: list[int] = Field(default_factory=list, max_length=10)


class RejectIn(BaseModel):
    reason: str = Field(default="", max_length=600)


def _subs(request: Request):
    return request.app.state.submissions


def _sub_out(row: dict) -> dict:
    return {
        "id": row["id"], "status": row["status"], "tags": row["tags"].split() if row["tags"] else [],
        "reason": row.get("reason"), "submitted_at": row.get("submitted_at"), "decided_at": row.get("decided_at"),
        "published": row.get("published") or 0, "file_count": row.get("file_count") or 0,
        "user": {"id": row["user_id"], "first_name": row["first_name"], "last_name": row["last_name"],
                 "username": row["username"]},
        "files": [{k: f[k] for k in ("id", "title", "performer", "duration", "file_size")} for f in row.get("files", [])],
    }


@router.get("/submissions")
async def submissions(
    request: Request, p: Principal = Depends(admin_user),
    status: Literal["pending", "approved", "rejected"] = "pending",
    tag: Annotated[str | None, Query(max_length=32, pattern=r"^[\w]+$")] = None,
    q: Annotated[str, Query(max_length=100)] = "",
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
    limit: Annotated[int, Query(ge=1, le=30)] = 15,
) -> dict:
    c = ctx(request)
    rows, counts = await asyncio.gather(
        c.repo.admin_submissions(status, tag.casefold() if tag else None, q.strip(), offset, limit),
        c.repo.submission_counts(),
    )
    return {"items": [_sub_out(r) for r in rows], "counts": counts,
            "next_offset": offset + len(rows) if len(rows) == limit else None}


@router.get("/submissions/count")
async def submissions_count(request: Request, p: Principal = Depends(admin_user)) -> dict:
    return await ctx(request).repo.submission_counts()


@router.post("/submissions/{sid}/approve")
async def approve(sid: Id, body: ApproveIn, request: Request, p: Principal = Depends(admin_user)) -> dict:
    rate_limit(request, f"sub-decide:{p.user_id}", 30)
    try:
        return await _subs(request).approve(sid, p.user_id, body.exclude)
    except KeyError:
        raise HTTPException(404, "sub_not_found") from None
    except LookupError:
        raise HTTPException(409, "sub_busy") from None
    except RuntimeError as exc:
        raise HTTPException(503 if str(exc) == "telegram_offline" else 502, str(exc)) from None


@router.post("/submissions/{sid}/reject", status_code=204)
async def reject(sid: Id, body: RejectIn, request: Request, p: Principal = Depends(admin_user)) -> None:
    rate_limit(request, f"sub-decide:{p.user_id}", 30)
    try:
        reason = clean_text(body.reason, 300, multiline=True, code="reason")
    except ValidationError as exc:
        raise HTTPException(422, exc.code) from None
    try:
        await _subs(request).reject(sid, p.user_id, reason)
    except KeyError:
        raise HTTPException(404, "sub_not_found") from None
    except LookupError:
        raise HTTPException(409, "sub_busy") from None
