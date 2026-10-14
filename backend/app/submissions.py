"""Заявки пользователей: свои треки через чат с ботом → модерация в админке → публикация в канал.

* Файлы не скачиваются на хостинг: они остаются в чате пользователя с ботом на серверах Telegram.
  Для прослушивания админом поток отдаётся напрямую из Telegram, при публикации документ
  пересылается в канал по ссылке на файл (без повторной загрузки).
* Лимиты проверяются атомарно в БД: до 5 треков в заявке и 10 в сутки (Premium — 30 и 60), только mp3.
* Администратор может ограничить пользователю отправку треков — бот сообщает об этом.
* Черновик собирается из нескольких сообщений: панель заявки обновляется с задержкой (debounce),
  чтобы альбом из 5 файлов давал одно сообщение бота, а не пять.
"""
from __future__ import annotations

import asyncio
import html
import logging
import re
import time
from collections import defaultdict
from typing import Any

from telethon import Button, events, types
from telethon.errors import RPCError

from .config import Settings
from .repo import Repo, extract_tags
from .texts import guess_lang, t
from .userflags import upload_limits

log = logging.getLogger(__name__)

MAX_PENDING = 3
MAX_SIZE_MB = 50
MAX_MINUTES = 20
DEBOUNCE = 2.5
DRAFT_TTL = 24 * 3600
TAG_RE = re.compile(r"^[\w]{2,32}$", re.UNICODE)


def _is_mp3(doc: types.Document) -> bool:
    name = next((a.file_name for a in doc.attributes if isinstance(a, types.DocumentAttributeFilename)), "") or ""
    voice = any(isinstance(a, types.DocumentAttributeAudio) and a.voice for a in doc.attributes)
    return not voice and (doc.mime_type in ("audio/mpeg", "audio/mp3") or name.lower().endswith(".mp3"))


def parse_tags(text: str, limit: int = 3) -> list[str]:
    tags: list[str] = []
    for token in re.split(r"[\s,;]+", text or ""):
        token = token.strip().lstrip("#").casefold()
        if TAG_RE.match(token) and token not in tags:
            tags.append(token)
        if len(tags) >= limit:
            break
    return tags


class Submissions:
    def __init__(self, settings: Settings, repo: Repo, tg: Any) -> None:
        self.s = settings
        self.repo = repo
        self.tg = tg
        self._timers: dict[int, asyncio.Task] = {}
        self._notes: defaultdict[int, defaultdict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._busy: set[int] = set()
        self._upload_mode: dict[int, float] = {}       # кто недавно нажал «Предложить треки»
        self._pending_tags: dict[int, list[str]] = {}  # теги, присланные до первого файла
        self._cleanup: asyncio.Task | None = None
        tg.extra_handlers.append(self.register)

    # ---------------------------------------------------------- регистрация
    def register(self) -> None:
        c = self.tg.client
        private = lambda e: e.is_private and not e.message.out  # noqa: E731
        c.add_event_handler(self._on_upload_cmd, events.NewMessage(pattern=r"^/upload(?:@\w+)?$", func=private))
        c.add_event_handler(self._on_media, events.NewMessage(
            func=lambda e: private(e) and isinstance(e.message.media, types.MessageMediaDocument)))
        c.add_event_handler(self._on_text, events.NewMessage(
            func=lambda e: private(e) and not e.message.media and bool(e.raw_text) and not e.raw_text.startswith("/")))
        c.add_event_handler(self._on_callback, events.CallbackQuery(pattern=rb"^up:"))
        if not self._cleanup:
            self._cleanup = asyncio.create_task(self._cleanup_loop(), name="drafts-cleanup")

    async def _lang(self, user_id: int) -> str:
        user = await self.repo.get_user(user_id) or {}
        return user.get("lang") or guess_lang(user.get("language_code"))

    def _limits(self, user_id: int) -> dict[str, int]:
        lim = upload_limits(self.repo.flags.get(user_id), self.s.is_admin(user_id))
        return {**lim, "size": MAX_SIZE_MB, "minutes": MAX_MINUTES}

    def _restriction(self, user_id: int) -> str | None:
        """Ключ текста-отказа, если отправка треков пользователю недоступна."""
        if self.s.is_admin(user_id):
            return None
        flags = self.repo.flags.get(user_id)
        if flags.banned:
            return "banned"
        return "upload_restricted" if flags.no_uploads else None

    # ---------------------------------------------------------- бот: команды и файлы
    async def _on_upload_cmd(self, event: events.NewMessage.Event) -> None:
        await self._send_intro(event.sender_id, event.chat_id)

    async def _send_intro(self, user_id: int, chat_id: int) -> None:
        lang = await self._lang(user_id)
        if refusal := self._restriction(user_id):
            await self.tg.client.send_message(chat_id, t(lang, refusal))
            return
        self._upload_mode[user_id] = time.monotonic()
        if len(self._upload_mode) > 5000:  # не даём словарю расти бесконечно
            self._upload_mode.pop(next(iter(self._upload_mode)))
        await self.tg.client.send_message(chat_id, t(lang, "upload_intro", **self._limits(user_id)), parse_mode="html")

    async def _ensure_user(self, event: events.NewMessage.Event) -> types.User | None:
        sender = await event.get_sender()
        if not isinstance(sender, types.User) or sender.bot:
            return None
        from .telegram import _tg_user
        await self.repo.upsert_user(_tg_user(sender), started_bot=True, access_hash=sender.access_hash)
        return sender

    async def _on_media(self, event: events.NewMessage.Event) -> None:
        sender = await self._ensure_user(event)
        if sender is None:
            return
        uid = sender.id
        if self._restriction(uid):
            self._notes[uid]["restricted"] = 1
            return self._schedule(uid, event.chat_id)
        doc = event.message.media.document
        if not isinstance(doc, types.Document) or not _is_mp3(doc):
            self._notes[uid]["format"] += 1
            return self._schedule(uid, event.chat_id)
        audio = next((a for a in doc.attributes if isinstance(a, types.DocumentAttributeAudio)), None)
        duration = int(audio.duration) if audio and audio.duration else 0
        if doc.size > MAX_SIZE_MB * 1024 * 1024 or duration > MAX_MINUTES * 60:
            self._notes[uid]["size"] += 1
            return self._schedule(uid, event.chat_id)
        pending = await self.repo.db.fetchval(
            "SELECT COUNT(*) FROM submissions WHERE user_id = ? AND status = 'pending'", (uid,))
        if (pending or 0) >= MAX_PENDING:
            self._notes[uid]["pending"] = pending
            return self._schedule(uid, event.chat_id)

        name = next((a.file_name for a in doc.attributes if isinstance(a, types.DocumentAttributeFilename)), None)
        title = (audio.title if audio and audio.title else "") or (name or "").rsplit(".", 1)[0]
        performer = audio.performer if audio and audio.performer else ""
        lim = self._limits(uid)
        status, sid = await self.repo.add_submission_file(uid, {
            "chat_msg_id": event.message.id, "title": title.strip()[:200] or "—", "performer": performer.strip()[:200],
            "duration": duration, "file_size": int(doc.size), "file_name": (name or "")[:200],
        }, lim["batch"], lim["day"])
        if status == "batch_full":
            self._notes[uid]["batch"] += 1
        elif status == "day_limit":
            self._notes[uid]["day"] += 1
        else:
            early = self._pending_tags.pop(uid, [])
            caption = parse_tags(" ".join(extract_tags(event.message.message or "")))
            if early or caption:  # теги из подписи к файлу или присланные заранее
                await self._merge_tags(sid, early + caption)
        self._schedule(uid, event.chat_id)

    async def _merge_tags(self, sid: int, new: list[str]) -> list[str]:
        sub = await self.repo.submission(sid)
        tags = (sub["tags"].split() if sub and sub["tags"] else [])
        for tg in new:
            if tg not in tags:
                tags.append(tg)
        tags = tags[:3]
        await self.repo.update_submission(sid, tags=" ".join(tags))
        return tags

    async def _on_text(self, event: events.NewMessage.Event) -> None:
        if self._restriction(event.sender_id):
            return
        draft = await self.repo.draft(event.sender_id)
        recent = time.monotonic() - self._upload_mode.get(event.sender_id, 0) < 1800
        if not draft and not recent:
            return  # обычная переписка с ботом — не мешаем
        lang = await self._lang(event.sender_id)
        tags = parse_tags(event.raw_text)
        if not tags:
            await event.respond(t(lang, "upload_tags_bad"))
            return
        if not draft:
            if len(self._pending_tags) > 5000:
                self._pending_tags.clear()
            self._pending_tags[event.sender_id] = tags
            await event.respond(t(lang, "upload_tags_set", tags=" ".join(f"#{x}" for x in tags)))
            return
        await self.repo.update_submission(draft["id"], tags=" ".join(tags))
        self._schedule(event.sender_id, event.chat_id, delay=0.3)

    def _schedule(self, user_id: int, chat_id: int, delay: float | None = None) -> None:
        delay = DEBOUNCE if delay is None else delay
        old = self._timers.get(user_id)
        if old and not old.done():
            old.cancel()
        self._timers[user_id] = asyncio.create_task(self._panel_later(user_id, chat_id, delay))

    async def _panel_later(self, user_id: int, chat_id: int, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
            await self._send_panel(user_id, chat_id)
        except asyncio.CancelledError:
            pass
        except Exception:
            log.exception("Панель заявки не отправлена")
        finally:
            if self._timers.get(user_id) is asyncio.current_task():
                self._timers.pop(user_id, None)

    async def _send_panel(self, user_id: int, chat_id: int) -> None:
        lang = await self._lang(user_id)
        notes = self._notes.pop(user_id, {})
        lim = self._limits(user_id)
        if notes.get("restricted") and (refusal := self._restriction(user_id)):
            await self.tg.client.send_message(chat_id, t(lang, refusal))
            return
        warnings = []
        if notes.get("format"):
            warnings.append(t(lang, "upload_warn_format", n=notes["format"]))
        if notes.get("size"):
            warnings.append(t(lang, "upload_warn_size", n=notes["size"], **lim))
        if notes.get("batch"):
            warnings.append(t(lang, "upload_warn_batch", n=notes["batch"], **lim))
        if notes.get("day"):
            warnings.append(t(lang, "upload_warn_day", n=notes["day"], **lim))
        if notes.get("pending"):
            warnings.append(t(lang, "upload_warn_pending", n=notes["pending"]))

        draft = await self.repo.draft(user_id)
        files = await self.repo.submission_files(draft["id"]) if draft else []
        if not files:
            if warnings:
                await self.tg.client.send_message(chat_id, "\n".join(warnings))
            return
        lines = "\n".join(
            f"{i}. {html.escape(f['performer'] + ' — ' if f['performer'] else '')}{html.escape(f['title'])}"
            for i, f in enumerate(files, 1))
        tags = " ".join(f"#{x}" for x in draft["tags"].split()) if draft["tags"] else t(lang, "upload_no_tags")
        text = t(lang, "upload_summary", n=len(files), files=lines, tags=html.escape(tags), **lim)
        text += "\n\n" + (("\n".join(warnings) + "\n\n") if warnings else "") + t(lang, "upload_hint")
        markup = types.ReplyInlineMarkup(rows=[types.KeyboardInlineButtonRow(buttons=[
            Button.inline(t(lang, "upload_send"), data=f"up:send:{draft['id']}".encode()),
            Button.inline(t(lang, "upload_cancel"), data=f"up:cancel:{draft['id']}".encode()),
        ])])
        # старую панель убираем, новую — вниз, под присланными файлами
        if draft["panel_msg_id"]:
            try:
                await self.tg.client.delete_messages(chat_id, [draft["panel_msg_id"]])
            except RPCError:
                pass
        msg = await self.tg.client.send_message(chat_id, text, buttons=markup, parse_mode="html")
        await self.repo.update_submission(draft["id"], panel_msg_id=msg.id)

    async def _on_callback(self, event: events.CallbackQuery.Event) -> None:
        m = re.fullmatch(rb"up:(start|send|cancel)(?::(\d{1,12}))?", event.data or b"")
        if not m:
            return await event.answer()
        action = m.group(1).decode()
        uid = event.sender_id
        lang = await self._lang(uid)
        if action == "start":
            await event.answer()
            return await self._send_intro(uid, event.chat_id)
        sid = int(m.group(2) or 0)
        sub = await self.repo.submission(sid)
        if not sub or sub["user_id"] != uid or sub["status"] != "draft":  # чужие/старые кнопки
            await event.answer()
            try:
                await event.edit(buttons=None)
            except RPCError:
                pass
            return
        files = await self.repo.submission_files(sid)
        if action == "cancel":
            await self._delete_chat_files(sub, files)
            await self.repo.delete_submission(sid)
            await event.answer()
            return await event.edit(t(lang, "upload_cancelled"), buttons=None)
        if refusal := self._restriction(uid):
            return await event.answer(t(lang, refusal), alert=True)
        if not files:
            return await event.answer(t(lang, "upload_empty"), alert=True)
        if not await self.repo.update_submission(sid, expect="draft", status="pending", submitted_at=int(time.time())):
            return await event.answer()  # повторное нажатие «Отправить»
        await event.answer()
        await event.edit(t(lang, "upload_sent"), buttons=None)
        log.info("Заявка #%s от %s: %s треков", sid, uid, len(files))
        self.tg.spawn(self._notify_admins(sid, len(files)), "notify-admins")

    async def _notify_admins(self, sid: int, n: int) -> None:
        sub = await self.repo.submission(sid)
        if not sub:
            return
        name = sub.get("display_name") or " ".join(x for x in (sub["first_name"], sub["last_name"]) if x) \
            or str(sub["user_id"])
        if sub.get("vip"):
            name = "⭐ " + name
        if sub["username"]:
            name += f" (@{sub['username']})"
        tags = " ".join(f"#{x}" for x in sub["tags"].split()) or "—"
        for admin_id in self.s.admin_ids:
            admin = await self.repo.get_user(admin_id)
            if not admin or not admin.get("started_bot"):
                continue
            lang = admin.get("lang") or guess_lang(admin.get("language_code"))
            text = t(lang, "admin_new_submission", id=sid, name=html.escape(name), n=n, tags=html.escape(tags))
            await self.tg.send_to_user(admin_id, admin.get("access_hash"), text,
                                       self.tg._webapp_markup(t(lang, "admin_panel")))

    async def _delete_chat_files(self, sub: dict, files: list[dict]) -> None:
        """Удаляет предложенные файлы из чата пользователя с ботом (насколько позволяет Telegram)."""
        ids = [f["chat_msg_id"] for f in files]
        if sub.get("panel_msg_id"):
            ids.append(sub["panel_msg_id"])
        if not ids:
            return
        try:
            peer = await self.tg.user_peer(sub["user_id"], sub.get("access_hash"))
            await self.tg.client.delete_messages(peer, ids)
        except (RPCError, ValueError, TypeError) as exc:
            log.debug("Не удалось удалить файлы заявки %s: %s", sub["id"], exc)

    async def _cleanup_loop(self) -> None:
        while True:
            try:
                for d in await self.repo.stale_drafts(DRAFT_TTL):
                    await self.repo.delete_submission(d["id"])
                await self.repo.prune_upload_log()
            except Exception:
                log.exception("Очистка черновиков")
            await asyncio.sleep(3600)

    # ---------------------------------------------------------- модерация (админка)
    async def approve(self, sid: int, admin_id: int, exclude: list[int]) -> dict[str, int]:
        if sid in self._busy:
            raise LookupError("sub_busy")
        self._busy.add(sid)
        try:
            sub = await self.repo.submission(sid)
            if not sub or sub["status"] != "pending":
                raise KeyError("sub_not_found")
            if not self.tg.ready.is_set():
                raise RuntimeError("telegram_offline")
            files = await self.repo.submission_files(sid)
            keep = [f for f in files if f["id"] not in set(exclude)]
            caption = " ".join(f"#{x}" for x in sub["tags"].split()) or None
            published = failed = 0
            for f in keep:
                try:
                    doc = await self.tg.user_audio(sub["user_id"], sub["access_hash"], f["chat_msg_id"], force=True)
                    # документ пересылается по ссылке на файл — без скачивания и повторной загрузки
                    msg = await self.tg.send_to_channel(doc, caption)
                    await self.tg.register_published(msg, None)
                    published += 1
                    await asyncio.sleep(1.5)  # бережём лимиты канала
                except Exception as exc:
                    failed += 1
                    log.warning("Заявка %s: файл %s не опубликован: %s", sid, f["id"], type(exc).__name__)
            if keep and not published:
                raise RuntimeError("sub_publish_failed")  # файлы недоступны — заявка остаётся на проверке
            excluded = [f for f in files if f["id"] in set(exclude)]
            await self._delete_chat_files({**sub, "panel_msg_id": None}, excluded)
            await self.repo.delete_submission_files(sid)
            await self.repo.update_submission(sid, expect="pending", status="approved", decided_at=int(time.time()),
                                              decided_by=admin_id, published=published)
            lang = sub.get("lang") or guess_lang(sub.get("language_code"))
            if published:
                await self.tg.send_to_user(sub["user_id"], sub["access_hash"], t(lang, "upload_approved", n=published),
                                           self.tg._webapp_markup(t(lang, "open")))
            log.info("Админ %s одобрил заявку #%s: опубликовано %s, ошибок %s", admin_id, sid, published, failed)
            return {"published": published, "failed": failed}
        finally:
            self._busy.discard(sid)

    async def reject(self, sid: int, admin_id: int, reason: str) -> None:
        # одна заявка — одно действие: одобрение и отклонение не выполняются одновременно
        if sid in self._busy:
            raise LookupError("sub_busy")
        self._busy.add(sid)
        try:
            sub = await self.repo.submission(sid)
            if not sub or sub["status"] != "pending":
                raise KeyError("sub_not_found")
            if not await self.repo.update_submission(sid, expect="pending", status="rejected", decided_at=int(time.time()),
                                                     decided_by=admin_id, reason=reason or None):
                raise KeyError("sub_not_found")
            files = await self.repo.submission_files(sid)
            await self._delete_chat_files({**sub, "panel_msg_id": None}, files)
            await self.repo.delete_submission_files(sid)
        finally:
            self._busy.discard(sid)
        lang = sub.get("lang") or guess_lang(sub.get("language_code"))
        text = t(lang, "upload_rejected")
        if reason:
            text += "\n" + t(lang, "upload_reason", reason=html.escape(reason))
        await self.tg.send_to_user(sub["user_id"], sub["access_hash"], text, None)
        log.info("Админ %s отклонил заявку #%s", admin_id, sid)
