"""Импорт собственного контента с YouTube Music в Telegram-канал.

Принципы (хостинг слабый):
* yt-dlp импортируется лениво — модуль не занимает память, пока раздел не используют;
* одно задание и один трек одновременно: скачали → опубликовали → удалили файл;
* скачивается готовая аудиодорожка (m4a/AAC) без перекодирования — ffmpeg не нужен, CPU почти не тратится;
* файл пишется во временный каталог потоково (не в RAM) и удаляется сразу после загрузки в Telegram;
* yt-dlp ограничен экстракторами YouTube — произвольные URL (SSRF) не обрабатываются.
"""
from __future__ import annotations

import asyncio
import io
import logging
import re
import secrets
import shutil
import tempfile
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
from PIL import Image, ImageOps

from .config import Settings
from .repo import Repo
from .userflags import ALBUMS_PREMIUM
from .validators import ValidationError, normalize_album_name

log = logging.getLogger(__name__)

PAGE_SIZE = 10
MAX_ENTRIES = 500
MAX_FILE = 60 * 1024 * 1024
MAX_DURATION = 30 * 60
RESOLVE_TTL = 30 * 60
UPLOAD_PAUSE = 3.0  # пауза между постами — бережём лимиты Telegram для каналов
TMP_PREFIX = "tgmusic-import-"

YT_HOSTS = {"music.youtube.com", "www.youtube.com", "youtube.com", "m.youtube.com", "youtu.be"}
THUMB_HOSTS = ("i.ytimg.com", "lh3.googleusercontent.com", "yt3.ggpht.com", "yt3.googleusercontent.com")
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
LIST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{10,64}$")
BROWSE_ID_RE = re.compile(r"^MPREb_[A-Za-z0-9_-]{6,40}$")
ALLOWED_EXTRACTORS = [r"youtube$", r"youtube:tab$", r"youtube:playlist$"]


class ImportError_(Exception):
    """Ошибка с кодом для интерфейса."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


# ------------------------------------------------------------------ ссылки
def normalize_url(raw: str) -> str:
    """Принимает только ссылки YouTube / YouTube Music и приводит их к канонической форме."""
    url = (raw or "").strip()
    if len(url) > 500 or any(c in url for c in " \n\r\t\"'<>"):
        raise ImportError_("yt_url_invalid")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    p = urlparse(url)
    host = (p.hostname or "").lower()
    try:
        port = p.port
    except ValueError:  # «youtube.com:abc»
        raise ImportError_("yt_url_invalid") from None
    if host not in YT_HOSTS or p.username or p.password or (port not in (None, 443)):
        raise ImportError_("yt_url_invalid")
    q = parse_qs(p.query)
    if host == "youtu.be":
        vid = p.path.strip("/")
        if VIDEO_ID_RE.match(vid):
            return f"https://music.youtube.com/watch?v={vid}"
        raise ImportError_("yt_url_invalid")
    if p.path.startswith("/browse/"):
        bid = p.path.split("/")[2] if len(p.path.split("/")) > 2 else ""
        if BROWSE_ID_RE.match(bid):
            return f"https://music.youtube.com/browse/{bid}"
        raise ImportError_("yt_url_invalid")
    if "list" in q and LIST_ID_RE.match(q["list"][0]) and p.path in ("/playlist", "/watch"):
        if p.path == "/playlist" or "v" not in q:
            return f"https://music.youtube.com/playlist?list={q['list'][0]}"
    if p.path == "/watch" and "v" in q and VIDEO_ID_RE.match(q["v"][0]):
        return f"https://music.youtube.com/watch?v={q['v'][0]}"
    if p.path.startswith("/shorts/") and VIDEO_ID_RE.match(p.path.split("/")[2] if len(p.path.split("/")) > 2 else ""):
        return f"https://music.youtube.com/watch?v={p.path.split('/')[2]}"
    raise ImportError_("yt_url_invalid")


def _clean_artist(value: str | None) -> str:
    value = (value or "").strip()
    return value[:-8] if value.endswith(" - Topic") else value


def _best_thumb(thumbs: list[dict] | None, min_w: int = 300) -> str | None:
    """Квадратная обложка YouTube Music, иначе самая подходящая по размеру."""
    best, best_score = None, -1.0
    for t in thumbs or []:
        url = t.get("url") or ""
        host = (urlparse(url).hostname or "").lower()
        if not url.startswith("https://") or not host.endswith(THUMB_HOSTS):
            continue
        w, h = t.get("width") or 0, t.get("height") or 0
        square = 1.0 if w and h and abs(w - h) < 8 else 0.0
        size = min(w or 480, 1200) / 1200
        score = square * 2 + size + (0.5 if (w or 480) >= min_w else 0)
        if score > best_score:
            best, best_score = url, score
    return best


# ------------------------------------------------------------------ данные
@dataclass
class Entry:
    video_id: str
    title: str
    artist: str
    duration: int
    thumbnail: str | None


@dataclass
class Resolved:
    rid: str
    kind: str  # track | playlist
    url: str
    title: str
    artist: str
    thumbnail: str | None
    entries: list[Entry]
    created_at: float = field(default_factory=time.time)


@dataclass
class JobItem:
    video_id: str
    title: str
    artist: str
    status: str = "queued"  # queued | downloading | uploading | done | skipped | error | cancelled
    error: str | None = None
    track_id: int | None = None


@dataclass
class Job:
    id: str
    title: str
    items: list[JobItem]
    created_by: int
    create_album: bool
    album_name: str | None
    caption: str
    status: str = "queued"  # queued | running | done | cancelled | error
    album_id: int | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    cancel: bool = False

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("cancel")
        counts: dict[str, int] = {}
        for it in self.items:
            counts[it.status] = counts.get(it.status, 0) + 1
        d["counts"] = counts
        d["total"] = len(self.items)
        d["processed"] = sum(counts.get(k, 0) for k in ("done", "skipped", "error", "cancelled"))
        return d


# ------------------------------------------------------------------ сервис
class Importer:
    def __init__(self, settings: Settings, repo: Repo, tg: Any) -> None:
        self.s = settings
        self.repo = repo
        self.tg = tg
        self._resolved: OrderedDict[str, Resolved] = OrderedDict()
        self._jobs: OrderedDict[str, Job] = OrderedDict()
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._worker: asyncio.Task | None = None
        # yt-dlp нельзя прервать по таймауту: поток доработает сам. Свои однопоточные пулы не дают
        # «зависшим» загрузкам накапливаться и занимать общий пул (обложки, аватары)
        self._dl_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ytdlp-dl")
        self._info_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ytdlp-info")
        # редиректы проверяем вручную на каждом шаге (защита от SSRF через перенаправление)
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(15.0), follow_redirects=False,
                                       proxy=settings.ytdlp_proxy if settings.ytdlp_proxy and not settings.ytdlp_proxy.startswith("socks") else None)
        self._resolve_lock = asyncio.Semaphore(1)
        self._cleanup_stale_tmp()

    # ---------------------------------------------------------- жизненный цикл
    def start(self) -> None:
        self._worker = asyncio.create_task(self._run(), name="importer")

    async def stop(self) -> None:
        if self._worker:
            self._worker.cancel()
        await self._http.aclose()
        for pool in (self._dl_pool, self._info_pool):
            pool.shutdown(wait=False, cancel_futures=True)

    @staticmethod
    def _cleanup_stale_tmp() -> None:
        for d in Path(tempfile.gettempdir()).glob(TMP_PREFIX + "*"):
            shutil.rmtree(d, ignore_errors=True)

    @staticmethod
    def available() -> dict[str, Any]:
        # без импорта самого yt-dlp — проверка не должна занимать память
        try:
            from importlib.metadata import version
            __version__ = version("yt-dlp")
        except Exception:
            return {"available": False, "version": None, "js_runtime": None}
        deno = shutil.which("deno")
        return {"available": True, "version": __version__, "js_runtime": "deno" if deno else None}

    # ---------------------------------------------------------- yt-dlp
    def _ydl_opts(self, **extra: Any) -> dict[str, Any]:
        opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "skip_download": False,
            "allowed_extractors": ALLOWED_EXTRACTORS,
            "socket_timeout": 20,
            "retries": 3,
            "extractor_retries": 2,
            "concurrent_fragment_downloads": 1,
            "noplaylist": True,
            "cachedir": str(self.s.data_dir / "yt-cache"),
            "logger": _QuietLogger(),
        }
        if self.s.ytdlp_proxy:
            opts["proxy"] = self.s.ytdlp_proxy
        if self.s.ytdlp_cookies:
            opts["cookiefile"] = str(self.s.ytdlp_cookies)
        opts.update(extra)
        return opts

    def _extract_sync(self, url: str, flat: bool) -> dict[str, Any]:
        import yt_dlp  # ленивый импорт: ~30 МБ RAM только при использовании

        opts = self._ydl_opts(skip_download=True, extract_flat="in_playlist" if flat else False,
                              noplaylist=False, playlist_items=f"1:{MAX_ENTRIES}")
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.sanitize_info(ydl.extract_info(url, download=False))

    def _download_sync(self, video_id: str, workdir: Path) -> dict[str, Any]:
        import yt_dlp

        opts = self._ydl_opts(
            # готовый AAC/m4a — без перекодирования; иначе лучшая доступная аудиодорожка
            format="bestaudio[ext=m4a]/bestaudio[acodec^=mp4a]/bestaudio",
            outtmpl={"default": str(workdir / "%(id)s.%(ext)s")},
            max_filesize=MAX_FILE,
            match_filter=lambda info, *args, **kwargs: (
                "too long" if (info.get("duration") or 0) > MAX_DURATION else None),
            writethumbnail=False,
            overwrites=True,
        )
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"https://music.youtube.com/watch?v={video_id}", download=True)
            info = ydl.sanitize_info(info)
        files = [d.get("filepath") for d in info.get("requested_downloads") or [] if d.get("filepath")]
        if not files or not Path(files[0]).is_file():
            if (info.get("duration") or 0) > MAX_DURATION:
                raise ImportError_("yt_too_long")
            if (info.get("filesize") or info.get("filesize_approx") or 0) > MAX_FILE:
                raise ImportError_("yt_too_large")
            raise ImportError_("yt_download_failed")
        info["_filepath"] = files[0]
        return info

    # ---------------------------------------------------------- поиск/предпросмотр
    async def resolve(self, raw_url: str) -> Resolved:
        url = normalize_url(raw_url)
        for r in self._resolved.values():
            if r.url == url and time.time() - r.created_at < RESOLVE_TTL:
                return r
        async with self._resolve_lock:
            try:
                info = await asyncio.wait_for(asyncio.get_running_loop().run_in_executor(
                    self._info_pool, self._extract_sync, url, "watch?v=" not in url), timeout=90)
            except ImportError_:
                raise
            except asyncio.TimeoutError:
                raise ImportError_("yt_timeout") from None
            except Exception as exc:
                log.warning("YouTube: не удалось получить %s: %s", url, _short(exc))
                raise ImportError_(_classify(exc)) from None

        if info.get("_type") in ("playlist", "multi_video"):
            entries = []
            for e in info.get("entries") or []:
                vid = e.get("id") or ""
                if not VIDEO_ID_RE.match(vid):
                    continue
                entries.append(Entry(
                    video_id=vid,
                    title=(e.get("track") or e.get("title") or "")[:200] or vid,
                    artist=_clean_artist(e.get("artist") or e.get("channel") or e.get("uploader"))[:200],
                    duration=int(e.get("duration") or 0),
                    thumbnail=_best_thumb(e.get("thumbnails"), 120),
                ))
            if not entries:
                raise ImportError_("yt_empty")
            res = Resolved(
                rid=secrets.token_urlsafe(8), kind="playlist", url=url,
                title=(info.get("title") or "Playlist")[:200].removeprefix("Album - "),
                artist=_clean_artist(info.get("channel") or info.get("uploader"))[:200],
                thumbnail=_best_thumb(info.get("thumbnails")) or entries[0].thumbnail,
                entries=entries,
            )
        else:
            vid = info.get("id") or ""
            if not VIDEO_ID_RE.match(vid):
                raise ImportError_("yt_empty")
            entry = Entry(vid, (info.get("track") or info.get("title") or vid)[:200],
                          _clean_artist(info.get("artist") or info.get("channel") or info.get("uploader"))[:200],
                          int(info.get("duration") or 0), _best_thumb(info.get("thumbnails")))
            res = Resolved(secrets.token_urlsafe(8), "track", url, entry.title, entry.artist, entry.thumbnail, [entry])

        self._resolved[res.rid] = res
        while len(self._resolved) > 20:
            self._resolved.popitem(last=False)
        return res

    def get_resolved(self, rid: str) -> Resolved:
        res = self._resolved.get(rid)
        if not res or time.time() - res.created_at > RESOLVE_TTL:
            raise ImportError_("yt_expired")
        return res

    async def page(self, rid: str, page: int) -> dict[str, Any]:
        res = self.get_resolved(rid)
        pages = max(1, -(-len(res.entries) // PAGE_SIZE))
        page = min(max(page, 1), pages)
        chunk = res.entries[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]
        imported = await self.repo.imported_map([e.video_id for e in chunk])
        queued = {it.video_id for j in self._jobs.values() if j.status in ("queued", "running")
                  for it in j.items if it.status in ("queued", "downloading", "uploading")}
        return {
            "rid": res.rid, "kind": res.kind, "title": res.title, "artist": res.artist,
            "thumbnail": res.thumbnail, "total": len(res.entries), "page": page, "pages": pages,
            "items": [{**asdict(e), "imported": e.video_id in imported, "queued": e.video_id in queued}
                      for e in chunk],
        }

    # ---------------------------------------------------------- задания
    def enqueue(self, rid: str, scope: str, *, page: int = 1, video_id: str | None = None,
                create_album: bool = False, album_name: str | None = None, caption: str = "",
                admin_id: int) -> Job:
        res = self.get_resolved(rid)
        if scope == "track":
            entries = [e for e in res.entries if e.video_id == video_id]
        elif scope == "page":
            entries = res.entries[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]
        else:
            entries = list(res.entries)
        if not entries:
            raise ImportError_("yt_empty")
        if sum(1 for j in self._jobs.values() if j.status in ("queued", "running")) >= 5:
            raise ImportError_("yt_queue_full")
        name = None
        if create_album:
            try:
                name = normalize_album_name(album_name or res.title)
            except ValidationError as exc:
                raise ImportError_(exc.code) from None
        job = Job(
            id=secrets.token_urlsafe(6), title=res.title if scope != "track" else entries[0].title,
            items=[JobItem(e.video_id, e.title, e.artist) for e in entries],
            created_by=admin_id, create_album=create_album, album_name=name, caption=caption,
        )
        self._jobs[job.id] = job
        while len(self._jobs) > 15:
            oldest = next(iter(self._jobs.values()))
            if oldest.status in ("queued", "running"):
                break
            self._jobs.popitem(last=False)
        self._queue.put_nowait(job.id)
        log.info("Импорт: задание %s (%s треков) от админа %s", job.id, len(job.items), admin_id)
        return job

    def jobs(self) -> list[dict[str, Any]]:
        return [j.as_dict() for j in reversed(self._jobs.values())]

    def cancel(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if not job or job.status not in ("queued", "running"):
            return False
        job.cancel = True
        return True

    async def _run(self) -> None:
        while True:
            job_id = await self._queue.get()
            job = self._jobs.get(job_id)
            if not job or job.cancel:
                if job:
                    job.status = "cancelled"
                    job.finished_at = time.time()
                continue
            try:
                await self._process(job)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # задание не должно ронять воркер
                log.exception("Импорт: задание %s упало", job.id)
                job.status, job.error = "error", _short(exc)
            finally:
                job.finished_at = time.time()

    async def _process(self, job: Job) -> None:
        job.status = "running"
        workdir = Path(tempfile.mkdtemp(prefix=TMP_PREFIX))
        track_ids: list[int] = []
        try:
            already = await self.repo.imported_map([it.video_id for it in job.items])
            for it in job.items:
                if job.cancel:
                    it.status = "cancelled"
                    continue
                if it.video_id in already:
                    it.status, it.track_id = "skipped", already[it.video_id]
                    track_ids.append(already[it.video_id])
                    continue
                try:
                    it.track_id = await self._import_one(it, job, workdir)
                    it.status = "done"
                    track_ids.append(it.track_id)
                    await asyncio.sleep(UPLOAD_PAUSE)
                except ImportError_ as exc:
                    it.status, it.error = "error", exc.code
                except Exception as exc:
                    log.warning("Импорт %s: %s", it.video_id, _short(exc))
                    it.status, it.error = "error", _classify(exc)
                finally:
                    for f in workdir.iterdir():  # файлы не задерживаются ни на секунду дольше нужного
                        f.unlink(missing_ok=True)
            if job.create_album and track_ids:
                job.album_id = await self._make_album(job, track_ids)
            job.status = "cancelled" if job.cancel else "done"
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    async def _import_one(self, it: JobItem, job: Job, workdir: Path) -> int:
        if not self.tg.ready.is_set():
            raise ImportError_("telegram_offline")
        it.status = "downloading"
        try:
            info = await asyncio.wait_for(asyncio.get_running_loop().run_in_executor(
                self._dl_pool, self._download_sync, it.video_id, workdir), timeout=600)
        except ImportError_:
            raise
        except asyncio.TimeoutError:
            raise ImportError_("yt_timeout") from None
        path = Path(info["_filepath"])
        if (info.get("duration") or 0) > MAX_DURATION:
            raise ImportError_("yt_too_long")
        title = (info.get("track") or it.title or info.get("title") or it.video_id)[:200]
        artist = _clean_artist(info.get("artist") or info.get("creator") or it.artist or info.get("uploader"))[:200]
        artist = artist.split(",")[0].strip() if len(artist) > 60 else artist
        it.title, it.artist = title, artist

        cover_raw = await self._fetch_thumb(_best_thumb(info.get("thumbnails"), 500))
        tg_thumb = _telegram_thumb(cover_raw) if cover_raw else None

        it.status = "uploading"
        ext = path.suffix.lower()
        mime = {".m4a": "audio/mp4", ".mp4": "audio/mp4", ".webm": "audio/webm", ".opus": "audio/ogg",
                ".ogg": "audio/ogg", ".mp3": "audio/mpeg"}.get(ext, "audio/mp4")
        msg = await self.tg.publish_audio(
            path, title=title, performer=artist, duration=int(info.get("duration") or 0),
            thumb=tg_thumb, caption=job.caption, mime_type=mime,
            file_name=_safe_filename(f"{artist} - {title}" if artist else title) + (ext or ".m4a"),
        )
        path.unlink(missing_ok=True)
        await self.repo.add_import(it.video_id, msg.id, job.created_by)
        track_id = await self.tg.register_published(msg, cover_raw)
        if not track_id:
            raise ImportError_("yt_publish_failed")
        return track_id

    @staticmethod
    def _thumb_host_ok(url: httpx.URL) -> bool:
        host = (url.host or "").lower()
        return url.scheme == "https" and any(host == h or host.endswith("." + h) for h in THUMB_HOSTS)

    async def _fetch_thumb(self, url: str | None) -> bytes | None:
        if not url:
            return None
        try:
            target = httpx.URL(url)
            for _ in range(4):  # каждый шаг перенаправления проверяется заново
                if not self._thumb_host_ok(target):
                    return None
                async with self._http.stream("GET", target) as r:
                    if r.is_redirect and r.headers.get("location"):
                        target = target.join(r.headers["location"])
                        continue
                    if r.status_code != 200:
                        return None
                    data = bytearray()
                    async for chunk in r.aiter_bytes():
                        data += chunk
                        if len(data) > 5 * 1024 * 1024:
                            return None
                    return bytes(data)
            return None
        except (httpx.HTTPError, httpx.InvalidURL, ValueError):
            return None

    async def _make_album(self, job: Job, track_ids: list[int]) -> int | None:
        user = await self.repo.get_user(job.created_by)
        if not user:
            return None
        ids = list(dict.fromkeys(track_ids))[:500]
        try:
            # порядок как в плейлисте: первый трек — первым
            return await self.repo.create_album_unique(job.created_by, job.album_name or "Import", "🎧",
                                                       ALBUMS_PREMIUM, ids)
        except LookupError as exc:
            job.error = exc.args[0]
            return None


# ------------------------------------------------------------------ helpers
class _QuietLogger:
    def debug(self, msg: str) -> None: ...
    def info(self, msg: str) -> None: ...
    def warning(self, msg: str) -> None: ...

    def error(self, msg: str) -> None:
        log.debug("yt-dlp: %s", msg[:300])


def _short(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {str(exc)[:200]}"


def _classify(exc: BaseException) -> str:
    text = str(exc).lower()
    if "sign in" in text or "confirm you" in text or "bot" in text:
        return "yt_bot_check"
    if "private" in text or "unavailable" in text or "removed" in text:
        return "yt_unavailable"
    if "too long" in text or "max_filesize" in text or "larger than" in text:
        return "yt_too_long"
    if "javascript" in text or "js runtime" in text or "challenge" in text:
        return "yt_js_runtime"
    if "timed out" in text or "timeout" in text or "connection" in text:
        return "yt_network"
    return "yt_failed"


def _safe_filename(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", name).strip()
    return name[:120] or "track"


def _telegram_thumb(raw: bytes) -> bytes | None:
    """Миниатюра для Telegram: JPEG ≤ 320px, ≤ 200 КБ."""
    try:
        with Image.open(io.BytesIO(raw)) as src:
            img = ImageOps.fit(src.convert("RGB"), (320, 320), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        img.save(out, "JPEG", quality=85, optimize=True)
        data = out.getvalue()
        return data if len(data) <= 200 * 1024 else None
    except Exception:
        return None

