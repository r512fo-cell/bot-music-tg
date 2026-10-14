"""Тонкая асинхронная обёртка над стандартным sqlite3.

Все обращения к базе выполняются в одном выделенном потоке, поэтому соединение
используется строго последовательно, а event loop не блокируется.
Все запросы — только параметризованные (защита от SQL-инъекций).
"""
from __future__ import annotations

import asyncio
import logging
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from typing import Any, Callable, Iterable, TypeVar

log = logging.getLogger(__name__)
T = TypeVar("T")

SCHEMA_VERSION = 5

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY,
    first_name      TEXT NOT NULL DEFAULT '',
    last_name       TEXT NOT NULL DEFAULT '',
    username        TEXT,
    language_code   TEXT,
    is_premium      INTEGER NOT NULL DEFAULT 0,
    photo_url       TEXT,
    started_bot     INTEGER NOT NULL DEFAULT 0,
    created_at      INTEGER NOT NULL,
    last_seen_at    INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_users_created ON users(created_at);
CREATE INDEX IF NOT EXISTS idx_users_seen ON users(last_seen_at);

CREATE TABLE IF NOT EXISTS tracks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id  INTEGER NOT NULL UNIQUE,
    title       TEXT NOT NULL,
    performer   TEXT NOT NULL DEFAULT '',
    duration    INTEGER NOT NULL DEFAULT 0,
    file_size   INTEGER NOT NULL DEFAULT 0,
    mime_type   TEXT NOT NULL DEFAULT 'audio/mpeg',
    file_name   TEXT,
    caption     TEXT NOT NULL DEFAULT '',
    cover       TEXT,
    color       TEXT,
    search      TEXT NOT NULL DEFAULT '',
    posted_at   INTEGER NOT NULL,
    created_at  INTEGER NOT NULL,
    updated_at  INTEGER NOT NULL,
    is_hidden   INTEGER NOT NULL DEFAULT 0,
    is_deleted  INTEGER NOT NULL DEFAULT 0,
    plays       INTEGER NOT NULL DEFAULT 0,
    likes       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_tracks_posted ON tracks(is_deleted, is_hidden, posted_at DESC);
CREATE INDEX IF NOT EXISTS idx_tracks_plays ON tracks(plays DESC);

CREATE TABLE IF NOT EXISTS track_tags (
    track_id INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    tag      TEXT NOT NULL,
    PRIMARY KEY (track_id, tag)
);
CREATE INDEX IF NOT EXISTS idx_track_tags_tag ON track_tags(tag);

CREATE TABLE IF NOT EXISTS plays (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    track_id  INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    user_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    played_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_plays_time ON plays(played_at);
CREATE INDEX IF NOT EXISTS idx_plays_track_time ON plays(track_id, played_at);
CREATE INDEX IF NOT EXISTS idx_plays_user_time ON plays(user_id, played_at DESC);

CREATE TABLE IF NOT EXISTS favorites (
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    track_id   INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    created_at INTEGER NOT NULL,
    PRIMARY KEY (user_id, track_id)
);
CREATE INDEX IF NOT EXISTS idx_fav_user ON favorites(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


# Миграции применяются последовательно: ключ — версия, до которой обновляется схема.
MIGRATIONS: dict[int, list[str]] = {
    2: [
        "ALTER TABLE users ADD COLUMN lang TEXT",
        "ALTER TABLE users ADD COLUMN access_hash INTEGER",
        "ALTER TABLE users ADD COLUMN blocked INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE tracks ADD COLUMN cover_checked_at INTEGER",
        """CREATE TABLE IF NOT EXISTS albums (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name        TEXT NOT NULL,
            name_key    TEXT NOT NULL,
            icon        TEXT NOT NULL,
            share_code  TEXT UNIQUE,
            created_at  INTEGER NOT NULL,
            updated_at  INTEGER NOT NULL,
            UNIQUE (user_id, name_key)
        )""",
        "CREATE INDEX IF NOT EXISTS idx_albums_user ON albums(user_id, created_at)",
        """CREATE TABLE IF NOT EXISTS album_tracks (
            album_id  INTEGER NOT NULL REFERENCES albums(id) ON DELETE CASCADE,
            track_id  INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
            added_at  INTEGER NOT NULL,
            PRIMARY KEY (album_id, track_id)
        )""",
        "CREATE INDEX IF NOT EXISTS idx_album_tracks_order ON album_tracks(album_id, added_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_album_tracks_track ON album_tracks(track_id)",
        """CREATE TABLE IF NOT EXISTS ads (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            placement    TEXT NOT NULL CHECK (placement IN ('home', 'library')),
            title        TEXT NOT NULL,
            text         TEXT NOT NULL DEFAULT '',
            button_text  TEXT,
            button_url   TEXT,
            is_active    INTEGER NOT NULL DEFAULT 1,
            show_from    INTEGER,
            show_until   INTEGER,
            impressions  INTEGER NOT NULL DEFAULT 0,
            clicks       INTEGER NOT NULL DEFAULT 0,
            created_by   INTEGER NOT NULL,
            created_at   INTEGER NOT NULL,
            updated_at   INTEGER NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS idx_ads_place ON ads(placement, is_active)",
        """CREATE TABLE IF NOT EXISTS broadcasts (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            text             TEXT NOT NULL,
            button_text      TEXT,
            button_url       TEXT,
            with_app_button  INTEGER NOT NULL DEFAULT 1,
            audience         TEXT NOT NULL DEFAULT 'all',
            status           TEXT NOT NULL DEFAULT 'queued',
            total            INTEGER NOT NULL DEFAULT 0,
            sent             INTEGER NOT NULL DEFAULT 0,
            failed           INTEGER NOT NULL DEFAULT 0,
            created_by       INTEGER NOT NULL,
            created_at       INTEGER NOT NULL,
            finished_at      INTEGER
        )""",
    ],
    3: [
        "ALTER TABLE albums ADD COLUMN is_public INTEGER NOT NULL DEFAULT 0",
        # альбомы, которыми уже делились по ссылке, остаются доступными
        "UPDATE albums SET is_public = 1 WHERE share_code IS NOT NULL",
        "CREATE INDEX IF NOT EXISTS idx_albums_public ON albums(is_public, updated_at DESC)",
        """CREATE TABLE IF NOT EXISTS yt_imports (
            video_id    TEXT PRIMARY KEY,
            message_id  INTEGER NOT NULL,
            created_by  INTEGER NOT NULL,
            created_at  INTEGER NOT NULL
        )""",
    ],
    4: [
        "ALTER TABLE tracks ADD COLUMN hidden_rule INTEGER",
        """CREATE TABLE IF NOT EXISTS hide_rules (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            field       TEXT NOT NULL CHECK (field IN ('performer', 'title')),
            mode        TEXT NOT NULL CHECK (mode IN ('contains', 'exact')),
            pattern     TEXT NOT NULL,
            pattern_key TEXT NOT NULL,
            created_by  INTEGER NOT NULL,
            created_at  INTEGER NOT NULL,
            UNIQUE (field, mode, pattern_key)
        )""",
        """CREATE TABLE IF NOT EXISTS submissions (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            status       TEXT NOT NULL DEFAULT 'draft'
                         CHECK (status IN ('draft', 'pending', 'approved', 'rejected')),
            tags         TEXT NOT NULL DEFAULT '',
            reason       TEXT,
            panel_msg_id INTEGER,
            created_at   INTEGER NOT NULL,
            submitted_at INTEGER,
            decided_at   INTEGER,
            decided_by   INTEGER,
            published    INTEGER NOT NULL DEFAULT 0
        )""",
        "CREATE INDEX IF NOT EXISTS idx_sub_status ON submissions(status, submitted_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_sub_user ON submissions(user_id, created_at DESC)",
        """CREATE TABLE IF NOT EXISTS submission_files (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            submission_id INTEGER NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
            chat_msg_id   INTEGER NOT NULL,
            title         TEXT NOT NULL DEFAULT '',
            performer     TEXT NOT NULL DEFAULT '',
            duration      INTEGER NOT NULL DEFAULT 0,
            file_size     INTEGER NOT NULL DEFAULT 0,
            file_name     TEXT,
            created_at    INTEGER NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS idx_subfiles_sub ON submission_files(submission_id)",
    ],
    5: [
        # статусы, которые выставляет администратор (см. userflags.py)
        "ALTER TABLE users ADD COLUMN vip INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN banned INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN no_albums INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN no_uploads INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN display_name TEXT",
        "ALTER TABLE users ADD COLUMN flags_updated_at INTEGER",
        # просмотры открытых альбомов: один зритель засчитывается не чаще раза в 12 часов
        "ALTER TABLE albums ADD COLUMN views INTEGER NOT NULL DEFAULT 0",
        """CREATE TABLE IF NOT EXISTS album_views (
            album_id INTEGER NOT NULL REFERENCES albums(id) ON DELETE CASCADE,
            user_id  INTEGER NOT NULL,
            seen_at  INTEGER NOT NULL,
            PRIMARY KEY (album_id, user_id)
        ) WITHOUT ROWID""",
        "CREATE INDEX IF NOT EXISTS idx_album_views_seen ON album_views(seen_at)",
        # журнал загрузок для суточного лимита: отмена/решение по заявке не «обнуляют» лимит
        """CREATE TABLE IF NOT EXISTS upload_log (
            user_id    INTEGER NOT NULL,
            created_at INTEGER NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS idx_upload_log ON upload_log(user_id, created_at)",
        """INSERT INTO upload_log (user_id, created_at)
           SELECT s.user_id, f.created_at FROM submission_files f JOIN submissions s ON s.id = f.submission_id
           WHERE f.created_at > strftime('%s', 'now') - 86400""",
    ],
}


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sqlite")
        self._conn: sqlite3.Connection | None = None

    # ---------- жизненный цикл ----------
    async def connect(self) -> None:
        await self._run(self._open)

    def _open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA cache_size=-8000")  # ~8 МБ кэша страниц
        # встроенный lower() в SQLite понимает только ASCII — для поиска по кириллице нужен casefold
        conn.create_function("casefold", 1, lambda v: v.casefold() if isinstance(v, str) else v,
                             deterministic=True)
        conn.executescript(SCHEMA)
        self._migrate(conn)
        self._conn = conn
        log.info("SQLite открыта: %s", self.path)

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        # 0 = новая база (базовая схема уже создана выше), 1 = база версии 1.0
        current = conn.execute("PRAGMA user_version").fetchone()[0] or 1
        for version in sorted(v for v in MIGRATIONS if v > current):
            log.info("Миграция базы данных до версии %s", version)
            conn.execute("BEGIN IMMEDIATE")
            try:
                for stmt in MIGRATIONS[version]:
                    try:
                        conn.execute(stmt)
                    except sqlite3.OperationalError as exc:
                        # повторный запуск после частично применённой миграции
                        if "duplicate column" not in str(exc):
                            raise
                conn.execute(f"PRAGMA user_version={version}")
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise

    async def close(self) -> None:
        def _close() -> None:
            if self._conn is not None:
                try:
                    self._conn.execute("PRAGMA optimize")
                finally:
                    self._conn.close()
                    self._conn = None

        await self._run(_close)
        self._executor.shutdown(wait=True)

    # ---------- выполнение ----------
    async def _run(self, fn: Callable[..., T], *args: Any) -> T:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, partial(fn, *args))

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("База данных не подключена")
        return self._conn

    async def run(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        """Произвольное чтение в потоке БД (без транзакции)."""
        return await self._run(lambda: fn(self.conn))

    async def fetchall(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        def _q() -> list[dict[str, Any]]:
            return [dict(r) for r in self.conn.execute(sql, tuple(params)).fetchall()]

        return await self._run(_q)

    async def fetchone(self, sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
        def _q() -> dict[str, Any] | None:
            row = self.conn.execute(sql, tuple(params)).fetchone()
            return dict(row) if row else None

        return await self._run(_q)

    async def fetchval(self, sql: str, params: Iterable[Any] = ()) -> Any:
        def _q() -> Any:
            row = self.conn.execute(sql, tuple(params)).fetchone()
            return row[0] if row else None

        return await self._run(_q)

    async def execute(self, sql: str, params: Iterable[Any] = ()) -> int:
        """Возвращает lastrowid (для INSERT) либо rowcount."""

        def _q() -> int:
            cur = self.conn.execute(sql, tuple(params))
            return cur.lastrowid if sql.lstrip().upper().startswith("INSERT") else cur.rowcount

        return await self._run(_q)

    async def transaction(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        """Выполняет fn(conn) атомарно."""

        def _tx() -> T:
            conn = self.conn
            conn.execute("BEGIN IMMEDIATE")
            try:
                result = fn(conn)
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")
            return result

        return await self._run(_tx)
