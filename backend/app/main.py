"""Точка входа: FastAPI + Telegram-бот в одном процессе."""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .api import admin, albums, content, moderation, routes, stream
from .api.deps import Ctx
from .config import APP_VERSION, load_settings
from .db import Database
from .importer import Importer
from .submissions import Submissions
from .recommend import Recommender
from .repo import Repo
from .runtime import RuntimeSettings
from .security import RateLimiter
from .telegram import TelegramService

settings = load_settings()

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
# Сторонние логгеры могут писать URL с токеном бота — оставляем только предупреждения
for noisy in ("httpx", "httpcore", "telethon", "uvicorn.access", "yt_dlp"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
log = logging.getLogger("app")

CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self' https://telegram.org",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob: https://t.me https://*.telesco.pe https://i.ytimg.com https://*.googleusercontent.com https://*.ggpht.com",
    "media-src 'self' blob:",
    "connect-src 'self'",
    "font-src 'self' data:",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'none'",
    "frame-ancestors https://web.telegram.org https://*.telegram.org https://telegram.org https://t.me",
])

SECURITY_HEADERS = [
    (b"content-security-policy", CSP.encode()),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), payment=(), usb=()"),
    (b"strict-transport-security", b"max-age=31536000; includeSubDomains"),
    (b"cross-origin-resource-policy", b"same-origin"),
]
MAX_BODY = 32 * 1024


class SecurityMiddleware:
    """Чистый ASGI-middleware: заголовки безопасности, лимит тела, лог ошибок без query-строк."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        length = headers.get(b"content-length")
        if length is not None and (not length.isdigit() or int(length) > MAX_BODY):
            await JSONResponse({"detail": "Слишком большой запрос"}, status_code=413)(scope, receive, send)
            return
        if scope["method"] in ("POST", "PUT", "PATCH") and b"transfer-encoding" in headers:
            await JSONResponse({"detail": "Chunked-запросы не поддерживаются"}, status_code=411)(scope, receive, send)
            return

        started = time.monotonic()

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                message.setdefault("headers", [])
                existing = {k.lower() for k, _ in message["headers"]}
                message["headers"].extend(h for h in SECURITY_HEADERS if h[0] not in existing)
                code = message["status"]
                if code >= 500:
                    # путь без query: в query может быть токен сессии
                    log.warning("%s %s -> %s (%.0f мс)", scope["method"], scope["path"], code,
                                (time.monotonic() - started) * 1000)
            await send(message)

        await self.app(scope, receive, send_wrapper)


@asynccontextmanager
async def lifespan(app: FastAPI):
    for d in (settings.data_dir, settings.covers_dir, settings.avatars_dir):
        d.mkdir(parents=True, exist_ok=True)
    db = Database(settings.db_path)
    await db.connect()
    repo = Repo(db)
    await repo.load_flags()
    # рассылки, прерванные перезапуском, не «зависают» в статусе running
    await db.execute("UPDATE broadcasts SET status = 'interrupted' WHERE status IN ('queued', 'running')")
    runtime = RuntimeSettings()
    await runtime.load(repo)
    tg = TelegramService(settings, repo)
    app.state.ctx = Ctx(settings=settings, repo=repo, tg=tg, limiter=RateLimiter(), runtime=runtime,
                        ip_limiter=RateLimiter(max_keys=20_000))
    app.state.importer = Importer(settings, repo, tg)
    app.state.submissions = Submissions(settings, repo, tg)
    app.state.recommender = Recommender(db)
    tg.start()
    app.state.importer.start()
    log.info("Приложение v%s запущено", APP_VERSION)
    try:
        yield
    finally:
        await app.state.importer.stop()
        await tg.stop()
        await db.close()


app = FastAPI(
    title="TG Music App",
    version=APP_VERSION,
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.add_middleware(SecurityMiddleware)
app.include_router(routes.router)
app.include_router(albums.router)
app.include_router(content.router)
app.include_router(moderation.router)
app.include_router(stream.router)
app.include_router(admin.router)


@app.exception_handler(RequestValidationError)
async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Не возвращаем клиенту детали валидации с исходными данными
    return JSONResponse({"detail": "Некорректный запрос"}, status_code=422)


@app.exception_handler(StarletteHTTPException)
async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=getattr(exc, "headers", None))


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    log.exception("Необработанная ошибка: %s %s", request.method, request.url.path)
    return JSONResponse({"detail": "Внутренняя ошибка сервера"}, status_code=500)


@app.get("/health", include_in_schema=False)
async def health(request: Request) -> dict:
    return {"status": "ok", "telegram": request.app.state.ctx.tg.ready.is_set(), "version": APP_VERSION}


# ------------------------------------------------------------------ медиа (превью)
class CachedStatic(StaticFiles):
    def __init__(self, *args, cache_control: str, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.cache_control = cache_control

    def file_response(self, *args, **kwargs) -> Response:
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = self.cache_control
        return resp


settings.covers_dir.mkdir(parents=True, exist_ok=True)
app.mount(
    "/media/covers",
    CachedStatic(directory=settings.covers_dir, cache_control="public, max-age=31536000, immutable"),
    name="covers",
)


@app.get("/media/channel.webp", include_in_schema=False)
async def channel_photo() -> FileResponse:
    path = settings.data_dir / "channel.webp"
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path, media_type="image/webp", headers={"Cache-Control": "public, max-age=3600"})


# ------------------------------------------------------------------ фронтенд (SPA)
STATIC = settings.static_dir
INDEX = STATIC / "index.html"

if (STATIC / "assets").is_dir():
    app.mount(
        "/assets",
        CachedStatic(directory=STATIC / "assets", cache_control="public, max-age=31536000, immutable"),
        name="assets",
    )


def _index() -> Response:
    if not INDEX.exists():
        return JSONResponse({"detail": "Фронтенд не собран"}, status_code=503)
    return FileResponse(INDEX, media_type="text/html", headers={"Cache-Control": "no-cache"})


@app.get("/", include_in_schema=False)
async def index() -> Response:
    return _index()


@app.get("/{path:path}", include_in_schema=False)
async def spa(path: str) -> Response:
    if path.startswith(("api/", "media/")):
        raise HTTPException(404)
    # Корневые файлы сборки (favicon и т.п.) — с защитой от path traversal
    candidate = (STATIC / path).resolve()
    if candidate.is_file() and candidate.is_relative_to(STATIC.resolve()) and "/" not in path:
        return FileResponse(candidate, headers={"Cache-Control": "public, max-age=86400"})
    return _index()
