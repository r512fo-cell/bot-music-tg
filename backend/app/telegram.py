"""Работа с Telegram через MTProto (Telethon) от имени бота.

* принимает новые/изменённые/удалённые посты канала и синхронизирует базу;
* импортирует историю канала (боту недоступен getHistory, поэтому сообщения
  запрашиваются пакетами по id);
* стримит аудио напрямую из Telegram к пользователю (Range-запросы), не сохраняя
  файлы на диск — на хостинге лежат только превью обложек;
* обрабатывает команды бота (/start, /stats, /sync).
"""
from __future__ import annotations

import asyncio
import html
import logging
import re
import time
from collections import OrderedDict
from urllib.parse import urlparse
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

import httpx
from telethon import Button, TelegramClient, events, functions, types, utils
from telethon.errors import (
    ChannelPrivateError,
    FileReferenceExpiredError,
    FloodWaitError,
    InputUserDeactivatedError,
    PeerIdInvalidError,
    RPCError,
    UserDeactivatedBanError,
    UserDeactivatedError,
    UserIsBlockedError,
)
from telethon.tl.custom import Message

from . import covers
from .captions import build_caption
from .config import APP_VERSION, Settings
from .repo import Repo, TrackData, extract_tags
from .security import TelegramUser
from .texts import guess_lang, t
from .validators import START_PARAM_RE

log = logging.getLogger(__name__)

STREAM_REQUEST_SIZE = 256 * 1024          # делитель 1 МБ и кратен 4 КБ (требование upload.getFile)
MESSAGE_CACHE_TTL = 20 * 60
MESSAGE_CACHE_SIZE = 512
SYNC_BATCH = 100
COVER_NEIGHBOR_WINDOW = 5 * 60           # фото-пост перед аудио в пределах 5 минут = обложка


@dataclass
class SyncState:
    running: bool = False
    full: bool = False
    started_at: int = 0
    finished_at: int = 0
    scanned: int = 0
    found: int = 0
    deleted: int = 0
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class ChannelInfo:
    id: int = 0
    title: str = ""
    username: str | None = None
    has_photo: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


class TrackUnavailable(Exception):
    pass


def _tg_user(sender: types.User) -> TelegramUser:
    return TelegramUser(
        id=sender.id,
        first_name=(sender.first_name or "")[:128],
        last_name=(sender.last_name or "")[:128],
        username=sender.username,
        language_code=getattr(sender, "lang_code", None),
        is_premium=bool(getattr(sender, "premium", False)),
        photo_url=None,
    )


def _audio_document(msg: Message | None) -> types.Document | None:
    """Возвращает документ, если сообщение — аудиотрек (голосовые исключаются)."""
    if msg is None or not isinstance(msg.media, types.MessageMediaDocument):
        return None
    doc = msg.media.document
    if not isinstance(doc, types.Document):
        return None
    audio_attr = next((a for a in doc.attributes if isinstance(a, types.DocumentAttributeAudio)), None)
    if audio_attr is not None:
        return None if audio_attr.voice else doc
    if (doc.mime_type or "").startswith("audio/"):
        return doc
    return None


def _track_from_message(msg: Message, doc: types.Document) -> TrackData:
    audio = next((a for a in doc.attributes if isinstance(a, types.DocumentAttributeAudio)), None)
    fname_attr = next((a for a in doc.attributes if isinstance(a, types.DocumentAttributeFilename)), None)
    file_name = fname_attr.file_name[:255] if fname_attr and fname_attr.file_name else None

    title = (audio.title if audio and audio.title else "").strip()
    performer = (audio.performer if audio and audio.performer else "").strip()
    if not title and file_name:
        stem = file_name.rsplit(".", 1)[0].replace("_", " ").strip()
        if " - " in stem and not performer:
            performer, title = (s.strip() for s in stem.split(" - ", 1))
        else:
            title = stem
    caption = (msg.message or "").strip()
    if not title:
        first_line = caption.splitlines()[0] if caption else ""
        title = first_line.lstrip("#").strip() or "Без названия"

    return TrackData(
        message_id=msg.id,
        title=title[:200],
        performer=performer[:200],
        duration=int(audio.duration) if audio and audio.duration else 0,
        file_size=int(doc.size or 0),
        mime_type=(doc.mime_type or "audio/mpeg")[:64],
        file_name=file_name,
        caption=caption[:2000],
        posted_at=int(msg.date.timestamp()) if msg.date else int(time.time()),
        tags=extract_tags(caption),
    )


class TelegramService:
    def __init__(self, settings: Settings, repo: Repo) -> None:
        self.s = settings
        self.repo = repo
        self.client = TelegramClient(
            str(settings.session_path),
            settings.api_id,
            settings.api_hash,
            flood_sleep_threshold=120,
            catch_up=True,
            device_model="tg-music-app",
            app_version=APP_VERSION,
            connection_retries=None,
            retry_delay=3,
            auto_reconnect=True,
        )
        self.channel = ChannelInfo()
        self._channel_entity: Any = None
        self.ready = asyncio.Event()
        self.sync_state = SyncState()
        self._sync_lock = asyncio.Lock()
        self._msg_cache: OrderedDict[int, tuple[float, Message]] = OrderedDict()
        self._tasks: set[asyncio.Task] = set()
        self._supervisor: asyncio.Task | None = None
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(15.0), follow_redirects=False)
        self._bot_username = ""
        self._has_main_app = False
        self._webfile_dc_id = 0
        self._broadcast_task: asyncio.Task | None = None
        self._broadcast_cancel = False
        self.history_floor = 0  # посты с id <= floor игнорируются (после очистки базы треков)
        self.extra_handlers: list[Any] = []  # регистраторы обработчиков других модулей (заявки)

    # ================================================================ lifecycle
    def start(self) -> None:
        self._supervisor = asyncio.create_task(self._run(), name="telegram-supervisor")

    async def stop(self) -> None:
        for task in [*self._tasks, self._supervisor]:
            if task and not task.done():
                task.cancel()
        try:
            await self.client.disconnect()
        except Exception:
            pass
        await self._http.aclose()

    def spawn(self, coro, name: str) -> asyncio.Task:
        task = asyncio.create_task(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        task.add_done_callback(self._log_task_error)
        return task

    @staticmethod
    def _log_task_error(task: asyncio.Task) -> None:
        if not task.cancelled() and task.exception():
            log.error("Фоновая задача %s упала", task.get_name(), exc_info=task.exception())

    async def _run(self) -> None:
        delay = 5
        while True:
            try:
                await self._connect()
                delay = 5
                await self.client.run_until_disconnected()
                log.warning("Telegram-клиент отключился, переподключение…")
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Ошибка подключения к Telegram, повтор через %s с", delay)
            self.ready.clear()
            await asyncio.sleep(delay)
            delay = min(delay * 2, 300)

    async def _connect(self) -> None:
        self.s.data_dir.mkdir(parents=True, exist_ok=True)
        if not self.client.is_connected():
            await self.client.start(bot_token=self.s.bot_token)
        me = await self.client.get_me()
        self._bot_username = me.username or ""
        self._has_main_app = bool(getattr(me, "bot_has_main_app", False))
        log.info("Бот авторизован: @%s", self._bot_username)

        try:
            self._channel_entity = await self.client.get_entity(self.s.channel)
        except (ValueError, ChannelPrivateError) as exc:
            raise RuntimeError(
                f"Канал {self.s.channel!r} недоступен. Добавьте бота в администраторы канала."
            ) from exc
        ch = self._channel_entity
        self.channel = ChannelInfo(
            id=utils.get_peer_id(ch),
            title=getattr(ch, "title", ""),
            username=getattr(ch, "username", None),
            has_photo=False,
        )
        log.info("Канал: %s (%s)", self.channel.title, self.channel.id)

        self.history_floor = int(await self.repo.get_meta("min_message_id") or 0)
        if not getattr(self, "_handlers_registered", False):
            self._register_handlers()
            for register in self.extra_handlers:
                register()
            self._handlers_registered = True

        self.ready.set()
        self.spawn(self._post_connect(), "post-connect")

    async def _post_connect(self) -> None:
        await self._setup_bot_ui()
        await self._download_channel_photo()
        has_tracks = await self.repo.max_message_id() > 0
        await self.sync(full=not has_tracks)
        await self._backfill_covers()

    async def _setup_bot_ui(self) -> None:
        try:
            await self.client(functions.bots.SetBotMenuButtonRequest(
                user_id=types.InputUserEmpty(),
                button=types.BotMenuButton(text=t("ru", "menu"), url=self.s.webapp_url),
            ))
            for lang_code, lang in (("", "en"), ("ru", "ru"), ("en", "en")):
                await self.client(functions.bots.SetBotCommandsRequest(
                    scope=types.BotCommandScopeDefault(),
                    lang_code=lang_code,
                    commands=[
                        types.BotCommand(command="start", description=t(lang, "cmd_start")),
                        types.BotCommand(command="upload", description=t(lang, "cmd_upload")),
                        types.BotCommand(command="language", description=t(lang, "cmd_language")),
                    ],
                ))
        except RPCError as exc:
            log.warning("Не удалось настроить меню бота: %s", exc)

    async def _download_channel_photo(self) -> None:
        try:
            raw = await self.client.download_profile_photo(self._channel_entity, file=bytes, download_big=False)
            if raw and await asyncio.to_thread(covers.process_avatar, raw, self.s.data_dir / "channel.webp"):
                self.channel.has_photo = True
        except Exception as exc:
            log.warning("Не удалось загрузить фото канала: %s", exc)

    # ================================================================ handlers
    def _register_handlers(self) -> None:
        chat = self._channel_entity
        c = self.client
        c.add_event_handler(self._on_channel_post, events.NewMessage(chats=chat))
        c.add_event_handler(self._on_channel_post, events.MessageEdited(chats=chat))
        c.add_event_handler(self._on_channel_delete, events.MessageDeleted(chats=chat))
        c.add_event_handler(self._on_start, events.NewMessage(
            pattern=r"^/start(?:@\w+)?(?:\s+(\S{1,64}))?\s*$", func=lambda e: e.is_private))
        c.add_event_handler(self._on_language, events.NewMessage(
            pattern=r"^/(?:language|lang)(?:@\w+)?$", func=lambda e: e.is_private))
        c.add_event_handler(self._on_lang_callback, events.CallbackQuery(pattern=rb"^lang:"))
        c.add_event_handler(self._on_stats, events.NewMessage(pattern=r"^/stats(?:@\w+)?$", func=lambda e: e.is_private))
        c.add_event_handler(self._on_sync, events.NewMessage(pattern=r"^/sync(?:@\w+)?$", func=lambda e: e.is_private))

    async def _on_channel_post(self, event: events.NewMessage.Event) -> None:
        msg: Message = event.message
        self._msg_cache.pop(msg.id, None)
        if msg.id <= self.history_floor:
            return
        doc = _audio_document(msg)
        if doc is None:
            # Пост отредактировали и аудио больше нет — скрываем трек
            if isinstance(event, events.MessageEdited.Event) and await self.repo.get_track_by_message(msg.id):
                await self.repo.mark_deleted([msg.id])
            return
        # Посты, опубликованные самим ботом (импорт), получают обложку в register_published
        await self._save_message(msg, doc, fetch_cover=not msg.out)

    async def _on_channel_delete(self, event: events.MessageDeleted.Event) -> None:
        ids = list(event.deleted_ids or [])
        for mid in ids:
            self._msg_cache.pop(mid, None)
        n = await self.repo.mark_deleted(ids)
        if n:
            log.info("Удалено треков: %s", n)

    async def _save_message(self, msg: Message, doc: types.Document, fetch_cover: bool = True) -> None:
        data = _track_from_message(msg, doc)
        track_id, created = await self.repo.upsert_track(data)
        row = await self.repo.get_track_raw(track_id)
        if fetch_cover and (created or (row and not row["cover"])):
            await self._fetch_cover(track_id, msg, doc, old=row["cover"] if row else None)
        if created:
            log.info("Новый трек #%s: %s — %s", track_id, data.performer, data.title)

    async def _fetch_cover(self, track_id: int, msg: Message, doc: types.Document, old: str | None = None) -> bool:
        """Источники обложки по порядку:
        1) миниатюра внутри аудиофайла;
        2) обложка альбома, которую Telegram подбирает сам (её показывают официальные клиенты);
        3) фото-пост, опубликованный прямо перед треком.
        """
        raw: bytes | None = None
        for source in (self._cover_from_thumb, self._cover_from_web, self._neighbor_photo):
            try:
                raw = await source(msg, doc)
            except Exception as exc:  # источник недоступен — пробуем следующий
                log.debug("Обложка трека %s (%s): %s", track_id, source.__name__, exc)
                raw = None
            if raw:
                break
        if not raw:
            await self.repo.mark_cover_checked(track_id)
            return False
        result = await asyncio.to_thread(covers.process_cover, raw, track_id, self.s.covers_dir)
        if not result:
            await self.repo.mark_cover_checked(track_id)
            return False
        name, color = result
        await self.repo.set_cover(track_id, name, color)
        if old and old != name:
            covers.remove_cover(old, self.s.covers_dir)
        return True

    async def _cover_from_thumb(self, msg: Message, doc: types.Document) -> bytes | None:
        thumbs = [t for t in (doc.thumbs or []) if not isinstance(t, (types.PhotoStrippedSize, types.PhotoPathSize))]
        if not thumbs:
            return None
        return await self.client.download_media(msg, file=bytes, thumb=-1)

    async def _webfile_dc(self) -> int:
        if not self._webfile_dc_id:
            cfg = await self.client(functions.help.GetConfigRequest())
            self._webfile_dc_id = cfg.webfile_dc_id
        return self._webfile_dc_id

    async def _get_web_file(self, location: types.TypeInputWebFileLocation) -> bytes | None:
        """upload.getWebFile выполняется в специальном DC (config.webfile_dc_id)."""
        dc_id = await self._webfile_dc()
        exported = dc_id != self.client.session.dc_id
        sender = await self.client._borrow_exported_sender(dc_id) if exported else self.client._sender
        try:
            data = bytearray()
            for _ in range(16):  # не больше 2 МБ
                res = await self.client._call(sender, functions.upload.GetWebFileRequest(
                    location=location, offset=len(data), limit=128 * 1024))
                chunk = bytes(res.bytes or b"")
                data += chunk
                if len(chunk) < 128 * 1024 or (res.size and len(data) >= res.size):
                    break
            return bytes(data) if len(data) > 512 else None
        finally:
            if exported:
                await self.client._return_exported_sender(sender)

    async def _cover_from_web(self, msg: Message, doc: types.Document) -> bytes | None:
        raw = await self._get_web_file(types.InputWebFileAudioAlbumThumbLocation(
            small=False, document=utils.get_input_document(doc)))
        if raw:
            return raw
        audio = next((a for a in doc.attributes if isinstance(a, types.DocumentAttributeAudio)), None)
        if audio and audio.title and audio.performer:
            return await self._get_web_file(types.InputWebFileAudioAlbumThumbLocation(
                small=False, title=audio.title, performer=audio.performer))
        return None

    async def _neighbor_photo(self, msg: Message, doc: types.Document | None = None) -> bytes | None:
        """Частый формат каналов: сначала пост с обложкой, следом аудио."""
        if msg.id <= 1:
            return None
        prev = await self.client.get_messages(self._channel_entity, ids=msg.id - 1)
        if not prev or not isinstance(prev.media, types.MessageMediaPhoto) or not prev.date or not msg.date:
            return None
        if abs((msg.date - prev.date).total_seconds()) > COVER_NEIGHBOR_WINDOW:
            return None
        sizes = sorted(
            (s for s in getattr(prev.media.photo, "sizes", [])
             if isinstance(s, (types.PhotoSize, types.PhotoSizeProgressive))),
            key=lambda s: s.w,
        )
        if not sizes:
            return None
        # берём размер около 800px, а не оригинал — экономим трафик и место
        size = next((s for s in sizes if s.w >= 600), sizes[-1])
        return await self.client.download_media(prev, file=bytes, thumb=size)

    async def _backfill_covers(self) -> None:
        """Догружает обложки трекам, у которых их нет (повторная попытка — раз в неделю)."""
        rows = await self.repo.tracks_without_cover(limit=400)
        found = 0
        for row in rows:
            msg = await self._get_message(row["message_id"], force=True)
            doc = _audio_document(msg)
            if msg and doc:
                found += await self._fetch_cover(row["id"], msg, doc)
                await asyncio.sleep(0.3)
        if rows:
            log.info("Обложки: проверено %s, найдено %s", len(rows), found)

    # ------------------------------------------------------------ bot commands
    def _webapp_button(self, text: str, param: str | None = None) -> types.KeyboardInlineButton:
        return types.KeyboardInlineButton(
            text=text,
            type=types.InlineButtonTypeWebView(url=self.webapp_link(param)),
            style=types.KeyboardButtonStyle(bg_primary=True),
        )

    def _webapp_markup(self, text: str, param: str | None = None) -> types.ReplyInlineMarkup:
        return types.ReplyInlineMarkup(rows=[types.KeyboardInlineButtonRow(buttons=[self._webapp_button(text, param)])])

    @staticmethod
    def _lang_markup(param: str | None) -> types.ReplyInlineMarkup:
        suffix = param or ""
        return types.ReplyInlineMarkup(rows=[types.KeyboardInlineButtonRow(buttons=[
            Button.inline("🇷🇺 Русский", data=f"lang:ru:{suffix}".encode()),
            Button.inline("🇬🇧 English", data=f"lang:en:{suffix}".encode()),
        ])])

    async def _on_start(self, event: events.NewMessage.Event) -> None:
        sender = await event.get_sender()
        if not isinstance(sender, types.User) or sender.bot:
            return
        raw_param = (event.pattern_match.group(1) or "") if event.pattern_match else ""
        param = raw_param if START_PARAM_RE.match(raw_param) else None
        user = await self.repo.upsert_user(_tg_user(sender), started_bot=True, access_hash=sender.access_hash)
        if self.is_banned(sender.id):
            await event.respond(t(user.get("lang") or guess_lang(sender.lang_code), "banned"))
            return
        self.spawn(self._cache_avatar(sender), "avatar")
        if not user.get("lang"):
            await event.respond(t(guess_lang(sender.lang_code), "choose_lang"), buttons=self._lang_markup(param))
            return
        await self._send_welcome(event.chat_id, sender, user["lang"], param)

    async def _on_language(self, event: events.NewMessage.Event) -> None:
        sender = await event.get_sender()
        lang = (await self.repo.get_user(event.sender_id) or {}).get("lang") or guess_lang(getattr(sender, "lang_code", None))
        await event.respond(t(lang, "choose_lang"), buttons=self._lang_markup(None))

    async def _on_lang_callback(self, event: events.CallbackQuery.Event) -> None:
        m = re.fullmatch(rb"lang:(ru|en):([A-Za-z0-9_-]{0,20})", event.data or b"")
        if not m:
            await event.answer()
            return
        lang = m.group(1).decode()
        raw_param = m.group(2).decode()
        param = raw_param if START_PARAM_RE.match(raw_param) else None
        sender = await event.get_sender()
        if not isinstance(sender, types.User):
            return
        await self.repo.upsert_user(_tg_user(sender), started_bot=True, access_hash=sender.access_hash)
        await self.repo.set_lang(sender.id, lang)
        await event.answer(t(lang, "lang_set"))
        if self.is_banned(sender.id):
            return
        try:
            await event.edit(t(lang, "lang_set"))
        except RPCError:
            pass
        await self.set_user_menu(sender.id, lang, sender.access_hash)
        await self._send_welcome(sender.id, sender, lang, param)

    async def set_user_menu(self, user_id: int, lang: str, access_hash: int | None = None) -> None:
        """Подпись кнопки меню на языке пользователя."""
        try:
            peer = types.InputUser(user_id, access_hash) if access_hash else await self.client.get_input_entity(user_id)
            await self.client(functions.bots.SetBotMenuButtonRequest(
                user_id=peer, button=types.BotMenuButton(text=t(lang, "menu"), url=self.s.webapp_url)))
        except (RPCError, ValueError, TypeError) as exc:
            log.debug("Меню пользователя не обновлено: %s", exc)

    async def _send_welcome(self, chat_id: int, sender: types.User, lang: str, param: str | None) -> None:
        if param and param.startswith("t_"):
            track = await self.repo.get_track(int(param[2:]), None)
            if track:
                title = f"{track['performer']} — {track['title']}" if track["performer"] else track["title"]
                await self.client.send_message(
                    chat_id, t(lang, "shared_track", title=html.escape(title)),
                    buttons=self._webapp_markup(t(lang, "listen"), param), parse_mode="html")
                return
            await self.client.send_message(chat_id, t(lang, "not_found"))
        elif param and param.startswith("a_"):
            album = await self.repo.album_by_code(param[2:])
            # закрытый альбом (или альбом заблокированного) по старой ссылке не раскрываем
            if album and album["is_public"] and not album.get("owner_banned"):
                await self.client.send_message(
                    chat_id, t(lang, "shared_album", title=html.escape(f"{album['icon']} {album['name']}")),
                    buttons=self._webapp_markup(t(lang, "open_album"), param), parse_mode="html")
                return
            await self.client.send_message(chat_id, t(lang, "not_found"))
        name = (self.repo.flags.get(sender.id).display_name or utils.get_display_name(sender)
                or ("друг" if lang == "ru" else "friend"))
        await self.client.send_message(
            chat_id,
            t(lang, "welcome", name=html.escape(name), channel=html.escape(self.channel.title or "—")),
            buttons=types.ReplyInlineMarkup(rows=[
                types.KeyboardInlineButtonRow(buttons=[self._webapp_button(t(lang, "open"))]),
                types.KeyboardInlineButtonRow(buttons=[Button.inline(t(lang, "upload_button"), data=b"up:start")]),
            ]),
            parse_mode="html", link_preview=False)

    def is_banned(self, user_id: int) -> bool:
        return self.repo.flags.get(user_id).banned and not self.s.is_admin(user_id)

    async def _user_lang(self, user_id: int) -> str:
        user = await self.repo.get_user(user_id) or {}
        return user.get("lang") or guess_lang(user.get("language_code"))

    async def _on_stats(self, event: events.NewMessage.Event) -> None:
        if not self.s.is_admin(event.sender_id):
            return
        lang = await self._user_lang(event.sender_id)
        o = await self.repo.admin_overview()
        await event.respond(t(lang, "stats", **o), buttons=self._webapp_markup(t(lang, "admin_panel")),
                            parse_mode="html")

    async def _on_sync(self, event: events.NewMessage.Event) -> None:
        if not self.s.is_admin(event.sender_id):
            return
        lang = await self._user_lang(event.sender_id)
        if self.sync_state.running:
            await event.respond(t(lang, "sync_running"))
            return
        await event.respond(t(lang, "sync_start"))
        self.spawn(self._sync_and_report(event.chat_id, lang), "sync-command")

    async def _sync_and_report(self, chat_id: int, lang: str) -> None:
        st = await self.sync(full=True)
        text = t(lang, "sync_error", error=st["error"]) if st.get("error") else t(lang, "sync_done", **st)
        await self.client.send_message(chat_id, text)

    async def _cache_avatar(self, user: types.User) -> None:
        if not isinstance(getattr(user, "photo", None), types.UserProfilePhoto):
            return
        raw = await self.client.download_profile_photo(user, file=bytes, download_big=True)
        if raw:
            await asyncio.to_thread(covers.process_avatar, raw, self.s.avatars_dir / f"{user.id}.webp")

    # ------------------------------------------------------------ рассылка
    def _broadcast_markup(self, data: dict[str, Any], lang: str) -> types.ReplyInlineMarkup | None:
        rows = []
        if data.get("button_text") and data.get("button_url"):
            rows.append(types.KeyboardInlineButtonRow(buttons=[types.KeyboardInlineButton(
                text=data["button_text"], type=types.InlineButtonTypeUrl(url=data["button_url"]))]))
        if data.get("with_app_button"):
            rows.append(types.KeyboardInlineButtonRow(buttons=[self._webapp_button(t(lang, "open"))]))
        return types.ReplyInlineMarkup(rows=rows) if rows else None

    async def send_to_user(self, user_id: int, access_hash: int | None, text: str,
                           markup: types.ReplyInlineMarkup | None) -> str:
        """'ok' | 'blocked' | 'fail'"""
        try:
            peer = types.InputPeerUser(user_id, access_hash) if access_hash else await self.client.get_input_entity(user_id)
        except (ValueError, TypeError):
            return "fail"
        for _ in range(3):
            try:
                await self.client.send_message(peer, text, parse_mode="html", buttons=markup, link_preview=False)
                return "ok"
            except FloodWaitError as exc:
                await asyncio.sleep(exc.seconds + 1)
            except (UserIsBlockedError, InputUserDeactivatedError, UserDeactivatedError,
                    UserDeactivatedBanError, PeerIdInvalidError):
                return "blocked"
            except RPCError as exc:
                log.debug("Сообщение пользователю не отправлено: %s", exc)
                return "fail"
            except (ConnectionError, OSError, asyncio.TimeoutError):
                await asyncio.sleep(5)  # переподключение клиента — пробуем ещё раз
        return "fail"

    async def send_broadcast_test(self, admin_id: int, data: dict[str, Any]) -> str:
        user = await self.repo.get_user(admin_id) or {}
        lang = user.get("lang") or guess_lang(user.get("language_code"))
        return await self.send_to_user(admin_id, user.get("access_hash"), data["text"],
                                       self._broadcast_markup(data, lang))

    @property
    def broadcast_running(self) -> bool:
        return self._broadcast_task is not None and not self._broadcast_task.done()

    def start_broadcast(self, bid: int) -> bool:
        if self.broadcast_running or not self.ready.is_set():
            return False
        self._broadcast_cancel = False
        self._broadcast_task = self.spawn(self._run_broadcast(bid), "broadcast")
        return True

    def cancel_broadcast(self) -> bool:
        if not self.broadcast_running:
            return False
        self._broadcast_cancel = True
        return True

    async def _run_broadcast(self, bid: int) -> None:
        b = await self.repo.broadcast(bid)
        if not b:
            return
        recipients = await self.repo.broadcast_recipients(b["audience"])
        await self.repo.broadcast_update(bid, status="running", total=len(recipients))
        markups = {lang: self._broadcast_markup(b, lang) for lang in ("ru", "en")}
        sent = failed = 0
        status = "done"
        try:
            for i, r in enumerate(recipients, 1):
                if self._broadcast_cancel:
                    status = "cancelled"
                    break
                res = await self.send_to_user(r["id"], r["access_hash"], b["text"], markups.get(r["lang"], markups["en"]))
                if res == "ok":
                    sent += 1
                else:
                    failed += 1
                    if res == "blocked":
                        await self.repo.mark_blocked(r["id"])
                if i % 20 == 0:
                    await self.repo.broadcast_update(bid, sent=sent, failed=failed)
                await asyncio.sleep(0.05)  # ~20 сообщений/с — ниже лимитов Telegram
        except asyncio.CancelledError:
            status = "interrupted"
            raise
        except Exception:  # обрыв связи и т.п. — не выдаём частичную рассылку за завершённую
            status = "error"
            log.exception("Рассылка #%s прервана ошибкой", bid)
        finally:
            await self.repo.broadcast_update(bid, status=status, sent=sent, failed=failed,
                                             finished_at=int(time.time()))
            log.info("Рассылка #%s: %s, отправлено %s, ошибок %s", bid, status, sent, failed)

    # ================================================================ sync
    def start_sync(self, full: bool) -> bool:
        if self.sync_state.running or not self.ready.is_set():
            return False
        self.spawn(self.sync(full=full), "sync")
        return True

    async def _top_message_hint(self) -> int:
        try:
            full = await self.client(functions.channels.GetFullChannelRequest(self._channel_entity))
            fc = full.full_chat
            return max(getattr(fc, "read_inbox_max_id", 0) or 0, getattr(fc, "read_outbox_max_id", 0) or 0)
        except RPCError as exc:
            log.debug("GetFullChannel недоступен: %s", exc)
            return 0

    async def sync(self, full: bool = False) -> dict[str, Any]:
        if self._sync_lock.locked():
            return self.sync_state.as_dict()
        async with self._sync_lock:
            st = self.sync_state = SyncState(running=True, full=full, started_at=int(time.time()))
            try:
                await self.ready.wait()
                known_max = await self.repo.max_message_id()
                hint = await self._top_message_hint()
                start = max(1 if full else max(1, known_max - 20), self.history_floor + 1)
                cursor = start
                empty_streak = 0
                while True:
                    ids = list(range(cursor, cursor + SYNC_BATCH))
                    try:
                        messages = await self.client.get_messages(self._channel_entity, ids=ids)
                    except FloodWaitError as exc:
                        await asyncio.sleep(exc.seconds + 1)
                        continue
                    st.scanned += len(ids)
                    alive = [m for m in messages if m is not None]
                    found_ids: set[int] = set()
                    for msg in alive:
                        doc = _audio_document(msg)
                        if doc is not None:
                            await self._save_message(msg, doc)
                            found_ids.add(msg.id)
                            st.found += 1
                    if full:
                        existing = await self.repo.message_ids_in_range(ids[0], ids[-1])
                        gone = [mid for mid in existing if mid not in found_ids]
                        st.deleted += await self.repo.mark_deleted(gone)

                    empty_streak = 0 if alive else empty_streak + 1
                    cursor += SYNC_BATCH
                    top = max(hint, known_max)
                    if cursor > top and empty_streak >= (2 if top else 5):
                        break
                    if cursor > 5_000_000:  # предохранитель
                        break
                    await asyncio.sleep(0.35)
                log.info("Синхронизация завершена: %s", st.as_dict())
            except asyncio.CancelledError:
                st.error = "cancelled"
                raise
            except Exception as exc:
                log.exception("Ошибка синхронизации")
                st.error = type(exc).__name__
            finally:
                st.running = False
                st.finished_at = int(time.time())
                await self.repo.set_meta("last_sync", str(st.finished_at))
            return st.as_dict()

    # ================================================================ streaming
    async def _get_message(self, message_id: int, force: bool = False) -> Message | None:
        now = time.monotonic()
        cached = self._msg_cache.get(message_id)
        if cached and not force and now - cached[0] < MESSAGE_CACHE_TTL:
            self._msg_cache.move_to_end(message_id)
            return cached[1]
        if not self.ready.is_set():
            await asyncio.wait_for(self.ready.wait(), timeout=5)
        msg = await self.client.get_messages(self._channel_entity, ids=message_id)
        if msg is None:
            self._msg_cache.pop(message_id, None)
            return None
        self._msg_cache[message_id] = (now, msg)
        self._msg_cache.move_to_end(message_id)
        while len(self._msg_cache) > MESSAGE_CACHE_SIZE:
            self._msg_cache.popitem(last=False)
        return msg

    async def resolve_document(self, message_id: int) -> types.Document:
        msg = await self._get_message(message_id)
        doc = _audio_document(msg)
        if doc is None:
            await self.repo.mark_deleted([message_id])
            raise TrackUnavailable()
        return doc

    async def stream(self, message_id: int, start: int, end: int, resolve: Any = None) -> AsyncIterator[bytes]:
        """Отдаёт байты [start, end] файла, запрашивая у Telegram выровненные блоки.
        resolve(force) — откуда брать документ (по умолчанию пост канала)."""
        if resolve is None:
            async def resolve(force: bool = False) -> types.Document:
                if force:
                    self._msg_cache.pop(message_id, None)
                return await self.resolve_document(message_id)
        pos = start
        retries = 0
        doc = await resolve(False)
        while pos <= end:
            aligned = pos - pos % STREAM_REQUEST_SIZE
            skip = pos - aligned
            limit = (end + 1 - aligned + STREAM_REQUEST_SIZE - 1) // STREAM_REQUEST_SIZE
            it = self.client.iter_download(
                doc, offset=aligned, request_size=STREAM_REQUEST_SIZE,
                chunk_size=STREAM_REQUEST_SIZE, limit=limit, file_size=doc.size,
            )
            try:
                async for chunk in it:
                    data = bytes(chunk)
                    if skip:
                        data, skip = data[skip:], 0
                    need = end + 1 - pos
                    if len(data) > need:
                        data = data[:need]
                    if not data:
                        return
                    pos += len(data)
                    yield data
                    if pos > end:
                        break
                else:
                    if pos <= end:  # файл оказался короче заявленного
                        return
            except FileReferenceExpiredError:
                retries += 1
                if retries > 2:
                    raise
                doc = await resolve(True)
                continue
            finally:
                await it.close()

    # ================================================================ avatars
    async def fetch_avatar(self, user_id: int, access_hash: int | None = None) -> bytes | None:
        """Аватар пользователя: сначала MTProto (надёжно), затем Bot API как запасной путь."""
        if self.ready.is_set():
            try:
                peer = (types.InputPeerUser(user_id, access_hash) if access_hash
                        else await self.client.get_input_entity(user_id))
                raw = await self.client.download_profile_photo(peer, file=bytes, download_big=True)
                if raw:
                    return raw
            except (RPCError, ValueError, TypeError, ConnectionError, OSError, asyncio.TimeoutError) as exc:
                log.debug("Аватар через MTProto не получен: %s", type(exc).__name__)
        return await self._fetch_avatar_botapi(user_id)

    async def _fetch_avatar_botapi(self, user_id: int) -> bytes | None:
        """Bot API (не требует access_hash). Токен никогда не логируется."""
        base = f"https://api.telegram.org/bot{self.s.bot_token}"
        try:
            r = await self._http.get(f"{base}/getUserProfilePhotos", params={"user_id": user_id, "limit": 1})
            data = r.json()
            photos = data.get("result", {}).get("photos") or []
            if not data.get("ok") or not photos:
                return None
            sizes = sorted(photos[0], key=lambda p: p.get("width", 0))
            if not sizes:
                return None
            size = next((p for p in sizes if p.get("width", 0) >= 320), sizes[-1])
            r = await self._http.get(f"{base}/getFile", params={"file_id": size["file_id"]})
            file_path = r.json().get("result", {}).get("file_path")
            if not file_path or ".." in file_path:
                return None
            r = await self._http.get(f"https://api.telegram.org/file/bot{self.s.bot_token}/{file_path}")
            if r.status_code != 200 or len(r.content) > 5 * 1024 * 1024:
                return None
            return r.content
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            log.warning("Аватар пользователя не получен: %s", type(exc).__name__)
            return None

    # ================================================================ публикация в канал
    async def publish_audio(self, path: Any, *, title: str, performer: str, duration: int,
                            thumb: bytes | None, caption: str, mime_type: str, file_name: str) -> Message:
        """Загружает аудио в канал потоково с диска (файл не читается в память целиком)."""
        if not self.ready.is_set():
            raise RuntimeError("telegram_offline")
        attributes = [
            types.DocumentAttributeAudio(duration=max(0, int(duration)), title=title, performer=performer or None),
            types.DocumentAttributeFilename(file_name=file_name),
        ]
        return await self.send_to_channel(str(path), caption, attributes=attributes, thumb=thumb,
                                          mime_type=mime_type, force_document=False)

    async def send_to_channel(self, file: Any, caption: str | None, **kwargs: Any) -> Message:
        """Публикация файла в канал с подписью-хэштегами; FloodWait переживаем (до 5 минут)."""
        text, entities = build_caption(caption)
        for attempt in range(3):
            try:
                return await self.client.send_file(self._channel_entity, file, caption=text,
                                                   formatting_entities=entities or None, parse_mode=None, **kwargs)
            except FloodWaitError as exc:
                if attempt == 2 or exc.seconds > 300:
                    raise
                await asyncio.sleep(exc.seconds + 1)
        raise RuntimeError("unreachable")

    async def register_published(self, msg: Message, cover_raw: bytes | None) -> int | None:
        """Сразу добавляет опубликованный трек в базу (не дожидаясь события) с качественной обложкой."""
        doc = _audio_document(msg)
        if doc is None:
            return None
        track_id, _ = await self.repo.upsert_track(_track_from_message(msg, doc))
        result = await asyncio.to_thread(covers.process_cover, cover_raw, track_id, self.s.covers_dir) if cover_raw else None
        if result:
            await self.repo.set_cover(track_id, *result)
        else:
            await self._fetch_cover(track_id, msg, doc)
        return track_id

    def clear_cache(self) -> None:
        self._msg_cache.clear()

    # ================================================================ личные чаты
    async def user_peer(self, user_id: int, access_hash: int | None) -> Any:
        return types.InputPeerUser(user_id, access_hash) if access_hash else await self.client.get_input_entity(user_id)

    async def user_audio(self, user_id: int, access_hash: int | None, msg_id: int, force: bool = False) -> types.Document:
        """Аудио из чата пользователя с ботом (файл остаётся на серверах Telegram)."""
        key = -(user_id * 10_000_000 + msg_id)  # отрицательные ключи не пересекаются с постами канала
        cached = self._msg_cache.get(key)
        if cached and not force and time.monotonic() - cached[0] < MESSAGE_CACHE_TTL:
            msg = cached[1]
        else:
            msg = await self.client.get_messages(await self.user_peer(user_id, access_hash), ids=msg_id)
            if msg is not None:
                self._msg_cache[key] = (time.monotonic(), msg)
                while len(self._msg_cache) > MESSAGE_CACHE_SIZE:
                    self._msg_cache.popitem(last=False)
        doc = _audio_document(msg)
        if doc is None:
            raise TrackUnavailable()
        return doc

    # ================================================================ helpers
    def webapp_link(self, param: str | None = None) -> str:
        if not param:
            return self.s.webapp_url
        base = self.s.webapp_url if urlparse(self.s.webapp_url).path else self.s.webapp_url + "/"
        return f"{base}{'&' if '?' in base else '?'}startapp={param}"

    @property
    def share_base(self) -> str | None:
        """Префикс ссылки «поделиться»: дописывается параметр t_<id> или a_<code>.

        * основной Mini App бота (BotFather → Configure Mini App) — приложение открывается сразу;
        * WEBAPP_SHORT_NAME (BotFather → /newapp) — то же самое через короткое имя;
        * иначе — ссылка на бота, который пришлёт кнопку открытия приложения.
        """
        if not self._bot_username:
            return None
        if self.s.webapp_short_name:
            return f"https://t.me/{self._bot_username}/{self.s.webapp_short_name}?startapp="
        if self._has_main_app:
            return f"https://t.me/{self._bot_username}?startapp="
        return f"https://t.me/{self._bot_username}?start="

    def post_url(self, message_id: int) -> str | None:
        if self.channel.username:
            return f"https://t.me/{self.channel.username}/{message_id}"
        if self.channel.id:
            internal = str(self.channel.id).removeprefix("-100")
            return f"https://t.me/c/{internal}/{message_id}"
        return None

    @property
    def bot_username(self) -> str:
        return self._bot_username

