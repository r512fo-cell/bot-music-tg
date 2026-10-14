"""Все SQL-запросы приложения. Только параметризованные запросы."""
from __future__ import annotations

import re
import secrets
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any

from .db import Database
from .security import TelegramUser
from .userflags import Flags, UserFlags
from .validators import ALBUM_NAME_MAX, album_name_key

VISIBLE = "t.is_deleted = 0 AND t.is_hidden = 0"
POPULAR_WINDOW = 30 * 86400
PLAY_DEDUP_WINDOW = 10 * 60
TAG_RE = re.compile(r"#([\w\d_]{2,32})", re.UNICODE)


def now() -> int:
    return int(time.time())


def extract_tags(text: str) -> list[str]:
    seen: list[str] = []
    for m in TAG_RE.finditer(text or ""):
        tag = m.group(1).casefold()
        if tag not in seen:
            seen.append(tag)
    return seen[:10]


def build_search(title: str, performer: str, file_name: str | None, tags: list[str]) -> str:
    return " ".join(x for x in (performer, title, file_name or "", " ".join(tags)) if x).casefold()


_ARTIST_SPLIT = re.compile(r"\s*(?:,|&|;|/|\bfeat\.?|\bft\.?|\bx\b)\s*")


def rule_matches(field: str, mode: str, key: str, title: str, performer: str) -> bool:
    """Регистронезависимое сравнение. Для «точно» по автору учитываются соавторы (feat., &, ,)."""
    value = (performer if field == "performer" else title).casefold().strip()
    if not value:
        return False
    if mode == "contains":
        return key in value
    if value == key:
        return True
    if field == "performer":
        return key in (p.strip() for p in _ARTIST_SPLIT.split(value))
    return False


def _apply_rules(conn: sqlite3.Connection, track_id: int, title: str, performer: str) -> None:
    """Скрывает/раскрывает трек по правилам. Скрытые вручную треки не трогаем."""
    row = conn.execute("SELECT is_hidden, hidden_rule FROM tracks WHERE id = ?", (track_id,)).fetchone()
    if row is None or (row["is_hidden"] and row["hidden_rule"] is None):
        return
    for rule in conn.execute("SELECT id, field, mode, pattern_key FROM hide_rules ORDER BY id"):
        if rule_matches(rule["field"], rule["mode"], rule["pattern_key"], title, performer):
            conn.execute("UPDATE tracks SET is_hidden = 1, hidden_rule = ? WHERE id = ?", (rule["id"], track_id))
            return
    if row["hidden_rule"] is not None:
        conn.execute("UPDATE tracks SET is_hidden = 0, hidden_rule = NULL WHERE id = ?", (track_id,))


def like_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@dataclass
class TrackData:
    message_id: int
    title: str
    performer: str
    duration: int
    file_size: int
    mime_type: str
    file_name: str | None
    caption: str
    posted_at: int
    tags: list[str] = field(default_factory=list)


def _track_columns(user_id: int | None) -> str:
    liked = (
        "EXISTS(SELECT 1 FROM favorites f WHERE f.user_id = ? AND f.track_id = t.id)"
        if user_id is not None
        else "0"
    )
    return (
        "t.id, t.message_id, t.title, t.performer, t.duration, t.cover, t.color, t.posted_at, "
        "t.plays, t.likes, t.is_hidden, t.mime_type, t.file_size, "
        f"(SELECT group_concat(tag, ' ') FROM track_tags tt WHERE tt.track_id = t.id) AS tags, "
        f"{liked} AS liked"
    )


OWNER_NAME = "COALESCE(NULLIF(u.display_name, ''), u.first_name)"


def _uid_params(user_id: int | None) -> list[Any]:
    return [user_id] if user_id is not None else []


class Repo:
    def __init__(self, db: Database) -> None:
        self.db = db
        self.flags = UserFlags()
        self._view_writes = 0

    async def load_flags(self) -> None:
        self.flags.load(await self.db.fetchall(UserFlags.select_sql()))

    # ------------------------------------------------------------------ users
    async def upsert_user(self, u: TelegramUser, started_bot: bool = False,
                          access_hash: int | None = None) -> dict[str, Any]:
        ts = now()
        await self.db.execute(
            """
            INSERT INTO users (id, first_name, last_name, username, language_code, is_premium,
                               photo_url, started_bot, created_at, last_seen_at, access_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                first_name = excluded.first_name,
                last_name = excluded.last_name,
                username = excluded.username,
                language_code = COALESCE(excluded.language_code, users.language_code),
                is_premium = excluded.is_premium,
                photo_url = COALESCE(excluded.photo_url, users.photo_url),
                started_bot = MAX(users.started_bot, excluded.started_bot),
                blocked = CASE WHEN excluded.started_bot = 1 THEN 0 ELSE users.blocked END,
                access_hash = COALESCE(excluded.access_hash, users.access_hash),
                last_seen_at = excluded.last_seen_at
            """,
            (u.id, u.first_name, u.last_name, u.username, u.language_code, int(u.is_premium),
             u.photo_url, int(started_bot), ts, ts, access_hash),
        )
        return await self.get_user(u.id)  # type: ignore[return-value]

    async def get_user(self, user_id: int) -> dict[str, Any] | None:
        return await self.db.fetchone("SELECT * FROM users WHERE id = ?", (user_id,))

    async def set_lang(self, user_id: int, lang: str) -> None:
        await self.db.execute("UPDATE users SET lang = ? WHERE id = ?", (lang, user_id))

    async def mark_blocked(self, user_id: int) -> None:
        await self.db.execute("UPDATE users SET blocked = 1 WHERE id = ?", (user_id,))

    async def touch_user(self, user_id: int) -> None:
        await self.db.execute(
            "UPDATE users SET last_seen_at = ? WHERE id = ? AND last_seen_at < ?",
            (now(), user_id, now() - 60),
        )

    async def user_stats(self, user_id: int) -> dict[str, Any]:
        row = await self.db.fetchone(
            """
            SELECT
              (SELECT COUNT(*) FROM plays WHERE user_id = ?) AS plays,
              (SELECT COUNT(DISTINCT track_id) FROM plays WHERE user_id = ?) AS unique_tracks,
              (SELECT COUNT(*) FROM favorites WHERE user_id = ?) AS favorites,
              (SELECT COALESCE(SUM(t.duration), 0) FROM plays p JOIN tracks t ON t.id = p.track_id
                 WHERE p.user_id = ?) AS seconds
            """,
            (user_id, user_id, user_id, user_id),
        )
        return row or {}

    # ----------------------------------------------------------------- tracks
    async def upsert_track(self, d: TrackData) -> tuple[int, bool]:
        """Возвращает (track_id, created)."""
        search = build_search(d.title, d.performer, d.file_name, d.tags)

        def _tx(conn: sqlite3.Connection) -> tuple[int, bool]:
            ts = now()
            row = conn.execute("SELECT id FROM tracks WHERE message_id = ?", (d.message_id,)).fetchone()
            if row:
                track_id = row["id"]
                conn.execute(
                    """UPDATE tracks SET title=?, performer=?, duration=?, file_size=?, mime_type=?,
                       file_name=?, caption=?, search=?, updated_at=?, is_deleted=0 WHERE id=?""",
                    (d.title, d.performer, d.duration, d.file_size, d.mime_type, d.file_name,
                     d.caption, search, ts, track_id),
                )
                created = False
            else:
                cur = conn.execute(
                    """INSERT INTO tracks (message_id, title, performer, duration, file_size, mime_type,
                       file_name, caption, search, posted_at, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (d.message_id, d.title, d.performer, d.duration, d.file_size, d.mime_type,
                     d.file_name, d.caption, search, d.posted_at, ts, ts),
                )
                track_id = int(cur.lastrowid)
                created = True
            conn.execute("DELETE FROM track_tags WHERE track_id = ?", (track_id,))
            conn.executemany(
                "INSERT OR IGNORE INTO track_tags (track_id, tag) VALUES (?, ?)",
                [(track_id, tag) for tag in d.tags],
            )
            _apply_rules(conn, track_id, d.title, d.performer)
            return track_id, created

        return await self.db.transaction(_tx)

    async def set_cover(self, track_id: int, cover: str | None, color: str | None) -> None:
        await self.db.execute(
            "UPDATE tracks SET cover = ?, color = ?, cover_checked_at = ? WHERE id = ?",
            (cover, color, now(), track_id),
        )

    async def mark_deleted(self, message_ids: list[int]) -> int:
        if not message_ids:
            return 0
        marks = ",".join("?" * len(message_ids))
        return await self.db.execute(
            f"UPDATE tracks SET is_deleted = 1, updated_at = ? WHERE message_id IN ({marks})",
            [now(), *message_ids],
        )

    async def set_hidden(self, track_id: int, hidden: bool) -> bool:
        # ручное действие админа отменяет привязку к правилу
        return await self.db.execute(
            "UPDATE tracks SET is_hidden = ?, hidden_rule = NULL, updated_at = ? WHERE id = ?",
            (int(hidden), now(), track_id),
        ) > 0

    async def get_track_by_message(self, message_id: int) -> dict[str, Any] | None:
        return await self.db.fetchone("SELECT * FROM tracks WHERE message_id = ?", (message_id,))

    async def get_track_raw(self, track_id: int) -> dict[str, Any] | None:
        return await self.db.fetchone("SELECT * FROM tracks WHERE id = ?", (track_id,))

    async def max_message_id(self) -> int:
        return int(await self.db.fetchval("SELECT COALESCE(MAX(message_id), 0) FROM tracks") or 0)

    async def message_ids_in_range(self, lo: int, hi: int) -> list[int]:
        rows = await self.db.fetchall(
            "SELECT message_id FROM tracks WHERE message_id BETWEEN ? AND ? AND is_deleted = 0",
            (lo, hi),
        )
        return [r["message_id"] for r in rows]

    async def tracks_without_cover(self, limit: int = 500, recheck_after: int = 7 * 86400) -> list[dict[str, Any]]:
        return await self.db.fetchall(
            "SELECT id, message_id, cover FROM tracks WHERE cover IS NULL AND is_deleted = 0 "
            "AND (cover_checked_at IS NULL OR cover_checked_at < ?) ORDER BY posted_at DESC LIMIT ?",
            (now() - recheck_after, limit),
        )

    async def mark_cover_checked(self, track_id: int) -> None:
        await self.db.execute("UPDATE tracks SET cover_checked_at = ? WHERE id = ?", (now(), track_id))

    # -------------------------------------------------------------- listings
    async def get_track(self, track_id: int, user_id: int | None) -> dict[str, Any] | None:
        return await self.db.fetchone(
            f"SELECT {_track_columns(user_id)} FROM tracks t WHERE t.id = ? AND {VISIBLE}",
            [*_uid_params(user_id), track_id],
        )

    async def tracks_by_ids(self, user_id: int | None, ids: list[int]) -> list[dict[str, Any]]:
        if not ids:
            return []
        marks = ",".join("?" * len(ids))
        rows = await self.db.fetchall(
            f"SELECT {_track_columns(user_id)} FROM tracks t WHERE t.id IN ({marks}) AND {VISIBLE}",
            [*_uid_params(user_id), *ids])
        order = {tid: i for i, tid in enumerate(ids)}
        return sorted(rows, key=lambda r: order.get(r["id"], 0))

    async def list_tracks(
        self, user_id: int | None, *, sort: str = "new", tag: str | None = None,
        offset: int = 0, limit: int = 30,
    ) -> list[dict[str, Any]]:
        where = [VISIBLE]
        params: list[Any] = _uid_params(user_id)
        if tag:
            where.append("EXISTS(SELECT 1 FROM track_tags g WHERE g.track_id = t.id AND g.tag = ?)")
            params.append(tag)
        order = {
            "new": "t.posted_at DESC, t.id DESC",
            "popular": "t.plays DESC, t.likes DESC, t.posted_at DESC",
            "title": "t.title COLLATE NOCASE ASC, t.id ASC",
        }[sort]
        params += [limit, offset]
        return await self.db.fetchall(
            f"SELECT {_track_columns(user_id)} FROM tracks t WHERE {' AND '.join(where)} "
            f"ORDER BY {order} LIMIT ? OFFSET ?",
            params,
        )

    async def popular(self, user_id: int | None, limit: int = 10, window: int = POPULAR_WINDOW) -> list[dict[str, Any]]:
        """Популярное: прослушивания за последние 30 дней, при равенстве — за всё время."""
        return await self.db.fetchall(
            f"""
            SELECT {_track_columns(user_id)},
                   (SELECT COUNT(*) FROM plays p WHERE p.track_id = t.id AND p.played_at >= ?) AS recent
            FROM tracks t
            WHERE {VISIBLE} AND t.plays > 0
            ORDER BY recent DESC, t.plays DESC, t.likes DESC
            LIMIT ?
            """,
            [*_uid_params(user_id), now() - window, limit],
        )

    async def search(self, user_id: int | None, query: str, offset: int = 0, limit: int = 30) -> list[dict[str, Any]]:
        words = [w for w in query.casefold().split() if w][:6]
        if not words:
            return []
        where = [VISIBLE] + ["t.search LIKE ? ESCAPE '\\'"] * len(words)
        params: list[Any] = [*_uid_params(user_id), *[f"%{like_escape(w)}%" for w in words], limit, offset]
        return await self.db.fetchall(
            f"SELECT {_track_columns(user_id)} FROM tracks t WHERE {' AND '.join(where)} "
            "ORDER BY t.plays DESC, t.posted_at DESC LIMIT ? OFFSET ?",
            params,
        )

    async def top_tags(self, limit: int = 16) -> list[dict[str, Any]]:
        return await self.db.fetchall(
            f"""SELECT tt.tag, COUNT(*) AS count FROM track_tags tt
                JOIN tracks t ON t.id = tt.track_id WHERE {VISIBLE}
                GROUP BY tt.tag ORDER BY count DESC, tt.tag LIMIT ?""",
            (limit,),
        )

    async def count_visible(self) -> int:
        return int(await self.db.fetchval(f"SELECT COUNT(*) FROM tracks t WHERE {VISIBLE}") or 0)

    # ---------------------------------------------------------- favorites
    async def add_favorite(self, user_id: int, track_id: int) -> bool:
        def _tx(conn: sqlite3.Connection) -> bool:
            if not conn.execute(f"SELECT 1 FROM tracks t WHERE t.id = ? AND {VISIBLE}", (track_id,)).fetchone():
                return False
            cur = conn.execute(
                "INSERT OR IGNORE INTO favorites (user_id, track_id, created_at) VALUES (?, ?, ?)",
                (user_id, track_id, now()),
            )
            if cur.rowcount:
                conn.execute("UPDATE tracks SET likes = likes + 1 WHERE id = ?", (track_id,))
            return True

        return await self.db.transaction(_tx)

    async def remove_favorite(self, user_id: int, track_id: int) -> None:
        def _tx(conn: sqlite3.Connection) -> None:
            cur = conn.execute("DELETE FROM favorites WHERE user_id = ? AND track_id = ?", (user_id, track_id))
            if cur.rowcount:
                conn.execute("UPDATE tracks SET likes = MAX(likes - 1, 0) WHERE id = ?", (track_id,))

        await self.db.transaction(_tx)

    async def favorites(self, user_id: int, offset: int = 0, limit: int = 50) -> list[dict[str, Any]]:
        return await self.db.fetchall(
            f"""SELECT {_track_columns(user_id)} FROM favorites fv
                JOIN tracks t ON t.id = fv.track_id
                WHERE fv.user_id = ? AND {VISIBLE}
                ORDER BY fv.created_at DESC LIMIT ? OFFSET ?""",
            [user_id, user_id, limit, offset],
        )

    async def history(self, user_id: int, limit: int = 30) -> list[dict[str, Any]]:
        return await self.db.fetchall(
            f"""SELECT {_track_columns(user_id)}, h.last_played FROM
                  (SELECT track_id, MAX(played_at) AS last_played FROM plays
                   WHERE user_id = ? GROUP BY track_id ORDER BY last_played DESC LIMIT ?) h
                JOIN tracks t ON t.id = h.track_id
                WHERE {VISIBLE}
                ORDER BY h.last_played DESC""",
            [user_id, user_id, limit],
        )

    # -------------------------------------------------------------- plays
    async def register_play(self, user_id: int, track_id: int) -> bool:
        """Засчитывает прослушивание. Повтор того же трека в течение 10 минут не считается."""

        def _tx(conn: sqlite3.Connection) -> bool:
            ts = now()
            if not conn.execute(f"SELECT 1 FROM tracks t WHERE t.id = ? AND {VISIBLE}", (track_id,)).fetchone():
                return False
            recent = conn.execute(
                "SELECT 1 FROM plays WHERE user_id = ? AND track_id = ? AND played_at > ? LIMIT 1",
                (user_id, track_id, ts - PLAY_DEDUP_WINDOW),
            ).fetchone()
            if recent:
                return False
            conn.execute("INSERT INTO plays (track_id, user_id, played_at) VALUES (?, ?, ?)", (track_id, user_id, ts))
            conn.execute("UPDATE tracks SET plays = plays + 1 WHERE id = ?", (track_id,))
            return True

        return await self.db.transaction(_tx)

    # -------------------------------------------------------------- meta
    async def get_meta(self, key: str) -> str | None:
        return await self.db.fetchval("SELECT value FROM meta WHERE key = ?", (key,))

    async def set_meta(self, key: str, value: str) -> None:
        await self.db.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    # -------------------------------------------------------------- admin
    async def admin_overview(self) -> dict[str, Any]:
        ts = now()
        day_start = ts - ts % 86400
        row = await self.db.fetchone(
            """
            SELECT
              (SELECT COUNT(*) FROM users) AS users_total,
              (SELECT COUNT(*) FROM users WHERE created_at >= ?) AS users_today,
              (SELECT COUNT(*) FROM users WHERE created_at >= ?) AS users_week,
              (SELECT COUNT(*) FROM users WHERE last_seen_at >= ?) AS dau,
              (SELECT COUNT(*) FROM users WHERE last_seen_at >= ?) AS wau,
              (SELECT COUNT(*) FROM users WHERE last_seen_at >= ?) AS mau,
              (SELECT COUNT(*) FROM users WHERE started_bot = 1) AS users_started,
              (SELECT COUNT(*) FROM tracks WHERE is_deleted = 0) AS tracks_total,
              (SELECT COUNT(*) FROM tracks WHERE is_deleted = 0 AND is_hidden = 1) AS tracks_hidden,
              (SELECT COUNT(*) FROM tracks WHERE is_deleted = 0 AND created_at >= ?) AS tracks_week,
              (SELECT COALESCE(SUM(duration), 0) FROM tracks WHERE is_deleted = 0) AS library_seconds,
              (SELECT COUNT(*) FROM plays) AS plays_total,
              (SELECT COUNT(*) FROM plays WHERE played_at >= ?) AS plays_today,
              (SELECT COUNT(*) FROM favorites) AS favorites_total
            """,
            (day_start, ts - 7 * 86400, ts - 86400, ts - 7 * 86400, ts - 30 * 86400,
             ts - 7 * 86400, day_start),
        )
        return row or {}

    async def daily_series(self, days: int = 14) -> list[dict[str, Any]]:
        ts = now()
        start = ts - ts % 86400 - (days - 1) * 86400
        plays = await self.db.fetchall(
            "SELECT (played_at - ?) / 86400 AS d, COUNT(*) AS c, COUNT(DISTINCT user_id) AS u "
            "FROM plays WHERE played_at >= ? GROUP BY d",
            (start, start),
        )
        users = await self.db.fetchall(
            "SELECT (created_at - ?) / 86400 AS d, COUNT(*) AS c FROM users WHERE created_at >= ? GROUP BY d",
            (start, start),
        )
        p = {r["d"]: r for r in plays}
        u = {r["d"]: r["c"] for r in users}
        return [
            {
                "date": start + i * 86400,
                "plays": p.get(i, {}).get("c", 0),
                "listeners": p.get(i, {}).get("u", 0),
                "new_users": u.get(i, 0),
            }
            for i in range(days)
        ]

    async def admin_top_tracks(self, limit: int = 10) -> list[dict[str, Any]]:
        return await self.popular(None, limit=limit, window=7 * 86400)

    async def admin_tracks(self, query: str, offset: int, limit: int) -> list[dict[str, Any]]:
        params: list[Any] = []
        where = ["t.is_deleted = 0"]
        for w in [w for w in query.casefold().split() if w][:6]:
            where.append("t.search LIKE ? ESCAPE '\\'")
            params.append(f"%{like_escape(w)}%")
        params += [limit, offset]
        return await self.db.fetchall(
            f"SELECT {_track_columns(None)} FROM tracks t WHERE {' AND '.join(where)} "
            "ORDER BY t.posted_at DESC LIMIT ? OFFSET ?",
            params,
        )

    _USER_FILTERS = {
        "all": "1",
        "vip": "u.vip = 1",
        "banned": "u.banned = 1",
        "restricted": "(u.no_albums = 1 OR u.no_uploads = 1)",
    }

    async def admin_users(self, q: str, flt: str, offset: int, limit: int) -> list[dict[str, Any]]:
        where, params = [self._USER_FILTERS.get(flt, "1")], []
        q = q.strip().lstrip("@")
        if q.isdigit():
            where.append("u.id = ?")
            params.append(int(q))
        else:
            for w in [w for w in q.casefold().split() if w][:4]:
                where.append("""casefold(u.first_name || ' ' || u.last_name || ' ' || COALESCE(u.username, '')
                                 || ' ' || COALESCE(u.display_name, '')) LIKE ? ESCAPE '\\'""")
                params.append(f"%{like_escape(w)}%")
        return await self.db.fetchall(
            f"""SELECT u.id, u.first_name, u.last_name, u.username, u.display_name, u.is_premium, u.created_at,
                       u.last_seen_at, u.lang, u.blocked, u.started_bot, u.vip, u.banned, u.no_albums, u.no_uploads,
                       (SELECT COUNT(*) FROM plays p WHERE p.user_id = u.id) AS plays
                FROM users u WHERE {' AND '.join(where)}
                ORDER BY u.created_at DESC, u.id DESC LIMIT ? OFFSET ?""",
            [*params, limit, offset],
        )

    async def admin_user(self, user_id: int) -> dict[str, Any] | None:
        return await self.db.fetchone(
            """SELECT u.id, u.first_name, u.last_name, u.username, u.display_name, u.is_premium, u.created_at,
                      u.last_seen_at, u.lang, u.blocked, u.started_bot, u.vip, u.banned, u.no_albums, u.no_uploads,
                      u.flags_updated_at,
                      (SELECT COUNT(*) FROM plays p WHERE p.user_id = u.id) AS plays,
                      (SELECT COUNT(*) FROM favorites f WHERE f.user_id = u.id) AS favorites,
                      (SELECT COUNT(*) FROM albums a WHERE a.user_id = u.id) AS albums,
                      (SELECT COUNT(*) FROM submissions s WHERE s.user_id = u.id AND s.status != 'draft') AS submissions,
                      (SELECT COALESCE(SUM(s.published), 0) FROM submissions s WHERE s.user_id = u.id) AS published
               FROM users u WHERE u.id = ?""",
            (user_id,),
        )

    async def set_user_flags(self, user_id: int, changes: dict[str, Any]) -> Flags:
        """Меняет статусы пользователя в БД и в кэше. Ключи — поля Flags."""
        allowed = {"vip", "banned", "no_albums", "no_uploads", "display_name"}
        changes = {k: v for k, v in changes.items() if k in allowed}
        if changes:
            cols = ", ".join(f"{k} = ?" for k in changes)
            vals = [int(v) if isinstance(v, bool) else v for v in changes.values()]
            await self.db.execute(f"UPDATE users SET {cols}, flags_updated_at = ? WHERE id = ?",
                                  [*vals, now(), user_id])
        return self.flags.update(user_id, **changes) if changes else self.flags.get(user_id)

    # ================================================================ albums
    _ALBUM_COLS = """
        a.id, a.name, a.icon, a.share_code, a.is_public, a.views, a.created_at, a.updated_at, a.user_id,
        (SELECT COUNT(*) FROM album_tracks x JOIN tracks t ON t.id = x.track_id
           WHERE x.album_id = a.id AND t.is_deleted = 0 AND t.is_hidden = 0) AS track_count,
        (SELECT COALESCE(SUM(t.duration), 0) FROM album_tracks x JOIN tracks t ON t.id = x.track_id
           WHERE x.album_id = a.id AND t.is_deleted = 0 AND t.is_hidden = 0) AS duration,
        (SELECT group_concat(cover, ' ') FROM (
            SELECT t.cover FROM album_tracks x JOIN tracks t ON t.id = x.track_id
            WHERE x.album_id = a.id AND t.cover IS NOT NULL AND t.is_deleted = 0 AND t.is_hidden = 0
            ORDER BY x.added_at DESC, x.rowid DESC LIMIT 4)) AS covers
    """

    async def albums(self, user_id: int, track_id: int | None = None) -> list[dict[str, Any]]:
        has = ("EXISTS(SELECT 1 FROM album_tracks h WHERE h.album_id = a.id AND h.track_id = ?)"
               if track_id else "0")
        params: list[Any] = [track_id] if track_id else []
        return await self.db.fetchall(
            f"SELECT {self._ALBUM_COLS}, {has} AS has_track FROM albums a WHERE a.user_id = ? "
            "ORDER BY a.created_at DESC, a.id DESC",
            [*params, user_id],
        )

    async def album(self, album_id: int) -> dict[str, Any] | None:
        return await self.db.fetchone(f"SELECT {self._ALBUM_COLS} FROM albums a WHERE a.id = ?", (album_id,))

    async def album_by_code(self, code: str) -> dict[str, Any] | None:
        return await self.db.fetchone(
            f"SELECT {self._ALBUM_COLS}, {OWNER_NAME} AS owner_name, u.vip AS owner_vip, u.banned AS owner_banned "
            "FROM albums a JOIN users u ON u.id = a.user_id WHERE a.share_code = ?",
            (code,),
        )

    async def set_album_public(self, album_id: int, user_id: int | None, public: bool) -> dict[str, Any] | None:
        """user_id=None — действие администратора над любым альбомом. Код ссылки создаётся при открытии."""

        def _tx(conn: sqlite3.Connection) -> bool:
            if user_id is None:
                row = conn.execute("SELECT share_code FROM albums WHERE id = ?", (album_id,)).fetchone()
            else:
                row = conn.execute("SELECT share_code FROM albums WHERE id = ? AND user_id = ?",
                                   (album_id, user_id)).fetchone()
            if not row:
                return False
            code = row["share_code"] or (secrets.token_urlsafe(9)[:12] if public else None)
            conn.execute("UPDATE albums SET is_public = ?, share_code = ?, updated_at = ? WHERE id = ?",
                         (int(public), code, now(), album_id))
            return True

        if not await self.db.transaction(_tx):
            return None
        return await self.album(album_id)

    async def public_albums(self, offset: int = 0, limit: int = 20) -> list[dict[str, Any]]:
        return await self.db.fetchall(
            f"""SELECT * FROM (
                  SELECT {self._ALBUM_COLS}, {OWNER_NAME} AS owner_name, u.vip AS owner_vip FROM albums a
                  JOIN users u ON u.id = a.user_id WHERE a.is_public = 1 AND u.banned = 0
                ) WHERE track_count > 0
                ORDER BY updated_at DESC, id DESC LIMIT ? OFFSET ?""",
            (limit, offset),
        )

    VIEW_WINDOW = 12 * 3600

    async def count_album_view(self, album_id: int, user_id: int) -> bool:
        """Засчитывает просмотр открытого альбома: один зритель — не чаще раза в 12 часов."""
        ts = now()
        self._view_writes += 1
        cleanup = self._view_writes % 500 == 0

        def _tx(conn: sqlite3.Connection) -> bool:
            if cleanup:  # старые отметки больше ни на что не влияют
                conn.execute("DELETE FROM album_views WHERE seen_at < ?", (ts - self.VIEW_WINDOW,))
            row = conn.execute("SELECT seen_at FROM album_views WHERE album_id = ? AND user_id = ?",
                               (album_id, user_id)).fetchone()
            if row and row[0] > ts - self.VIEW_WINDOW:
                return False
            conn.execute(
                "INSERT INTO album_views (album_id, user_id, seen_at) VALUES (?, ?, ?) "
                "ON CONFLICT(album_id, user_id) DO UPDATE SET seen_at = excluded.seen_at",
                (album_id, user_id, ts))
            conn.execute("UPDATE albums SET views = views + 1 WHERE id = ? AND is_public = 1", (album_id,))
            return True

        return await self.db.transaction(_tx)

    async def create_album_unique(self, user_id: int, base: str, icon: str, limit: int,
                                  track_ids: list[int] | None = None) -> int:
        """Как create_album, но при совпадении имени добавляет « (2)», « (3)»…"""
        for i in range(1, 6):
            name = base if i == 1 else f"{base[:ALBUM_NAME_MAX - 4]} ({i})"
            try:
                return await self.create_album(user_id, name, album_name_key(name), icon, limit, track_ids)
            except LookupError as exc:
                if exc.args[0] != "album_exists":
                    raise
        raise LookupError("album_exists")

    async def album_count(self, user_id: int) -> int:
        return int(await self.db.fetchval("SELECT COUNT(*) FROM albums WHERE user_id = ?", (user_id,)) or 0)

    async def create_album(self, user_id: int, name: str, key: str, icon: str, limit: int,
                           track_ids: list[int] | None = None) -> int:
        """Атомарно проверяет лимит и уникальность имени. Ошибки: LookupError('limit'|'exists')."""

        def _tx(conn: sqlite3.Connection) -> int:
            count = conn.execute("SELECT COUNT(*) FROM albums WHERE user_id = ?", (user_id,)).fetchone()[0]
            if count >= limit:
                raise LookupError("album_limit")
            if conn.execute("SELECT 1 FROM albums WHERE user_id = ? AND name_key = ?", (user_id, key)).fetchone():
                raise LookupError("album_exists")
            ts = now()
            cur = conn.execute(
                "INSERT INTO albums (user_id, name, name_key, icon, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, name, key, icon, ts, ts),
            )
            album_id = int(cur.lastrowid)
            if track_ids:
                conn.executemany(
                    "INSERT OR IGNORE INTO album_tracks (album_id, track_id, added_at) VALUES (?, ?, ?)",
                    [(album_id, tid, ts - i) for i, tid in enumerate(track_ids)],
                )
            return album_id

        return await self.db.transaction(_tx)

    async def update_album(self, album_id: int, user_id: int, name: str | None, key: str | None,
                           icon: str | None) -> None:
        def _tx(conn: sqlite3.Connection) -> None:
            row = conn.execute("SELECT 1 FROM albums WHERE id = ? AND user_id = ?", (album_id, user_id)).fetchone()
            if not row:
                raise KeyError("album")
            if key and conn.execute(
                "SELECT 1 FROM albums WHERE user_id = ? AND name_key = ? AND id != ?", (user_id, key, album_id)
            ).fetchone():
                raise LookupError("album_exists")
            conn.execute(
                "UPDATE albums SET name = COALESCE(?, name), name_key = COALESCE(?, name_key), "
                "icon = COALESCE(?, icon), updated_at = ? WHERE id = ?",
                (name, key, icon, now(), album_id),
            )

        await self.db.transaction(_tx)

    async def delete_album(self, album_id: int, user_id: int) -> bool:
        return await self.db.execute("DELETE FROM albums WHERE id = ? AND user_id = ?", (album_id, user_id)) > 0

    async def album_tracks(self, album_id: int, user_id: int | None) -> list[dict[str, Any]]:
        return await self.db.fetchall(
            f"""SELECT {_track_columns(user_id)} FROM album_tracks x
                JOIN tracks t ON t.id = x.track_id
                WHERE x.album_id = ? AND {VISIBLE}
                ORDER BY x.added_at DESC, x.rowid DESC LIMIT ?""",
            [*_uid_params(user_id), album_id, 500],
        )

    async def album_add_track(self, album_id: int, user_id: int, track_id: int, max_tracks: int) -> None:
        def _tx(conn: sqlite3.Connection) -> None:
            if not conn.execute("SELECT 1 FROM albums WHERE id = ? AND user_id = ?", (album_id, user_id)).fetchone():
                raise KeyError("album")
            if not conn.execute(f"SELECT 1 FROM tracks t WHERE t.id = ? AND {VISIBLE}", (track_id,)).fetchone():
                raise KeyError("track")
            n = conn.execute("SELECT COUNT(*) FROM album_tracks WHERE album_id = ?", (album_id,)).fetchone()[0]
            if n >= max_tracks:
                raise LookupError("album_full")
            ts = now()
            conn.execute(
                "INSERT OR IGNORE INTO album_tracks (album_id, track_id, added_at) VALUES (?, ?, ?)",
                (album_id, track_id, ts),
            )
            conn.execute("UPDATE albums SET updated_at = ? WHERE id = ?", (ts, album_id))

        await self.db.transaction(_tx)

    async def album_remove_track(self, album_id: int, user_id: int, track_id: int) -> None:
        def _tx(conn: sqlite3.Connection) -> None:
            if not conn.execute("SELECT 1 FROM albums WHERE id = ? AND user_id = ?", (album_id, user_id)).fetchone():
                raise KeyError("album")
            conn.execute("DELETE FROM album_tracks WHERE album_id = ? AND track_id = ?", (album_id, track_id))
            conn.execute("UPDATE albums SET updated_at = ? WHERE id = ?", (now(), album_id))

        await self.db.transaction(_tx)

    async def album_share_code(self, album_id: int, user_id: int) -> str:
        def _tx(conn: sqlite3.Connection) -> str:
            row = conn.execute("SELECT share_code FROM albums WHERE id = ? AND user_id = ?",
                               (album_id, user_id)).fetchone()
            if not row:
                raise KeyError("album")
            code = row["share_code"] or secrets.token_urlsafe(9)[:12]
            # поделиться = открыть доступ по ссылке
            conn.execute("UPDATE albums SET share_code = ?, is_public = 1 WHERE id = ?", (code, album_id))
            return code

        return await self.db.transaction(_tx)

    async def album_track_ids(self, album_id: int) -> list[int]:
        rows = await self.db.fetchall(
            f"""SELECT x.track_id FROM album_tracks x JOIN tracks t ON t.id = x.track_id
                WHERE x.album_id = ? AND {VISIBLE} ORDER BY x.added_at DESC, x.rowid DESC""",
            (album_id,),
        )
        return [r["track_id"] for r in rows]

    # ================================================================ ads
    async def active_ads(self, placement: str) -> list[dict[str, Any]]:
        ts = now()
        return await self.db.fetchall(
            """SELECT id, placement, title, text, button_text, button_url FROM ads
               WHERE placement = ? AND is_active = 1
                 AND (show_from IS NULL OR show_from <= ?) AND (show_until IS NULL OR show_until > ?)""",
            (placement, ts, ts),
        )

    async def ad_is_active(self, ad_id: int) -> bool:
        return bool(await self.db.fetchval("SELECT 1 FROM ads WHERE id = ? AND is_active = 1", (ad_id,)))

    async def ad_hit(self, ad_id: int, field_name: str) -> None:
        column = {"impressions": "impressions", "clicks": "clicks"}[field_name]
        await self.db.execute(f"UPDATE ads SET {column} = {column} + 1 WHERE id = ?", (ad_id,))

    async def admin_ads(self) -> list[dict[str, Any]]:
        return await self.db.fetchall("SELECT * FROM ads ORDER BY created_at DESC")

    async def create_ad(self, data: dict[str, Any], admin_id: int) -> int:
        ts = now()
        return await self.db.execute(
            """INSERT INTO ads (placement, title, text, button_text, button_url, is_active, show_from,
                                show_until, created_by, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (data["placement"], data["title"], data["text"], data["button_text"], data["button_url"],
             int(data["is_active"]), data["show_from"], data["show_until"], admin_id, ts, ts),
        )

    async def update_ad(self, ad_id: int, data: dict[str, Any]) -> bool:
        return await self.db.execute(
            """UPDATE ads SET placement = ?, title = ?, text = ?, button_text = ?, button_url = ?,
                   is_active = ?, show_from = ?, show_until = ?, updated_at = ? WHERE id = ?""",
            (data["placement"], data["title"], data["text"], data["button_text"], data["button_url"],
             int(data["is_active"]), data["show_from"], data["show_until"], now(), ad_id),
        ) > 0

    async def delete_ad(self, ad_id: int) -> bool:
        return await self.db.execute("DELETE FROM ads WHERE id = ?", (ad_id,)) > 0

    # ================================================================ broadcasts
    async def create_broadcast(self, data: dict[str, Any], admin_id: int) -> int:
        return await self.db.execute(
            """INSERT INTO broadcasts (text, button_text, button_url, with_app_button, audience, status,
                                       created_by, created_at) VALUES (?, ?, ?, ?, ?, 'queued', ?, ?)""",
            (data["text"], data["button_text"], data["button_url"], int(data["with_app_button"]),
             data["audience"], admin_id, now()),
        )

    async def broadcast(self, bid: int) -> dict[str, Any] | None:
        return await self.db.fetchone("SELECT * FROM broadcasts WHERE id = ?", (bid,))

    async def broadcasts(self, limit: int = 20) -> list[dict[str, Any]]:
        return await self.db.fetchall("SELECT * FROM broadcasts ORDER BY id DESC LIMIT ?", (limit,))

    async def broadcast_update(self, bid: int, **fields: Any) -> None:
        allowed = {"status", "total", "sent", "failed", "finished_at"}
        keys = [k for k in fields if k in allowed]
        if not keys:
            return
        sets = ", ".join(f"{k} = ?" for k in keys)
        await self.db.execute(f"UPDATE broadcasts SET {sets} WHERE id = ?", [*(fields[k] for k in keys), bid])

    async def broadcast_recipients(self, audience: str) -> list[dict[str, Any]]:
        eff = "COALESCE(lang, CASE WHEN language_code IN ('ru','uk','be','kk') THEN 'ru' ELSE 'en' END)"
        where = "started_bot = 1 AND blocked = 0 AND banned = 0"
        params: list[Any] = []
        if audience in ("ru", "en"):
            where += f" AND {eff} = ?"
            params.append(audience)
        return await self.db.fetchall(
            f"SELECT id, access_hash, {eff} AS lang FROM users WHERE {where} ORDER BY id", params)

    async def audience_sizes(self) -> dict[str, int]:
        row = await self.db.fetchone(
            """SELECT COUNT(*) AS all_,
                 SUM(CASE WHEN COALESCE(lang, CASE WHEN language_code IN ('ru','uk','be','kk') THEN 'ru' ELSE 'en' END) = 'ru' THEN 1 ELSE 0 END) AS ru,
                 SUM(CASE WHEN COALESCE(lang, CASE WHEN language_code IN ('ru','uk','be','kk') THEN 'ru' ELSE 'en' END) = 'en' THEN 1 ELSE 0 END) AS en
               FROM users WHERE started_bot = 1 AND blocked = 0 AND banned = 0"""
        ) or {}
        return {"all": row.get("all_") or 0, "ru": row.get("ru") or 0, "en": row.get("en") or 0}

    # ================================================================ импорт с YouTube Music
    async def imported_map(self, video_ids: list[str]) -> dict[str, int]:
        """video_id -> track_id для уже опубликованных (и не удалённых) треков."""
        if not video_ids:
            return {}
        marks = ",".join("?" * len(video_ids))
        rows = await self.db.fetchall(
            f"""SELECT y.video_id, t.id AS track_id FROM yt_imports y
                JOIN tracks t ON t.message_id = y.message_id AND t.is_deleted = 0
                WHERE y.video_id IN ({marks})""",
            video_ids,
        )
        return {r["video_id"]: r["track_id"] for r in rows}

    async def add_import(self, video_id: str, message_id: int, admin_id: int) -> None:
        await self.db.execute(
            "INSERT OR REPLACE INTO yt_imports (video_id, message_id, created_by, created_at) VALUES (?, ?, ?, ?)",
            (video_id, message_id, admin_id, now()),
        )

    # ================================================================ правила скрытия
    async def hide_rules(self) -> list[dict[str, Any]]:
        return await self.db.fetchall(
            """SELECT r.*, (SELECT COUNT(*) FROM tracks t WHERE t.hidden_rule = r.id AND t.is_deleted = 0) AS hidden_count
               FROM hide_rules r ORDER BY r.created_at DESC"""
        )

    async def preview_rule(self, field: str, mode: str, key: str, limit: int = 5) -> dict[str, Any]:
        rows = await self.db.fetchall("SELECT id, title, performer FROM tracks WHERE is_deleted = 0")
        hits = [r for r in rows if rule_matches(field, mode, key, r["title"], r["performer"])]
        return {"count": len(hits), "sample": [{"title": r["title"], "performer": r["performer"]} for r in hits[:limit]]}

    async def add_hide_rule(self, field: str, mode: str, pattern: str, key: str, admin_id: int) -> tuple[int, int]:
        """Возвращает (rule_id, сколько треков скрыто). LookupError('rule_exists')."""

        def _tx(conn: sqlite3.Connection) -> tuple[int, int]:
            if conn.execute("SELECT 1 FROM hide_rules WHERE field = ? AND mode = ? AND pattern_key = ?",
                            (field, mode, key)).fetchone():
                raise LookupError("rule_exists")
            cur = conn.execute(
                "INSERT INTO hide_rules (field, mode, pattern, pattern_key, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (field, mode, pattern, key, admin_id, now()))
            rule_id = int(cur.lastrowid)
            ids = [r["id"] for r in conn.execute(
                "SELECT id, title, performer FROM tracks WHERE is_deleted = 0 AND is_hidden = 0")
                if rule_matches(field, mode, key, r["title"], r["performer"])]
            conn.executemany("UPDATE tracks SET is_hidden = 1, hidden_rule = ? WHERE id = ?",
                             [(rule_id, i) for i in ids])
            return rule_id, len(ids)

        return await self.db.transaction(_tx)

    async def delete_hide_rule(self, rule_id: int) -> int:
        """Удаляет правило, раскрывает его треки (если их не скрывает другое правило). Возвращает число раскрытых."""

        def _tx(conn: sqlite3.Connection) -> int:
            rows = conn.execute("SELECT id, title, performer FROM tracks WHERE hidden_rule = ?", (rule_id,)).fetchall()
            conn.execute("UPDATE tracks SET is_hidden = 0, hidden_rule = NULL WHERE hidden_rule = ?", (rule_id,))
            if not conn.execute("DELETE FROM hide_rules WHERE id = ?", (rule_id,)).rowcount:
                raise KeyError("rule")
            for r in rows:
                _apply_rules(conn, r["id"], r["title"], r["performer"])
            return conn.execute(
                f"SELECT COUNT(*) FROM tracks WHERE id IN ({','.join('?' * len(rows)) or 'NULL'}) AND is_hidden = 0",
                [r["id"] for r in rows]).fetchone()[0]

        return await self.db.transaction(_tx)

    # ================================================================ очистка базы треков
    async def clear_tracks(self, keep_history_out: bool) -> dict[str, int]:
        """Удаляет все треки и связанные с ними данные (теги, прослушивания, лайки, треки в альбомах).
        Пользователи, альбомы, реклама и настройки сохраняются."""

        def _tx(conn: sqlite3.Connection) -> dict[str, int]:
            count = conn.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
            max_id = conn.execute("SELECT COALESCE(MAX(message_id), 0) FROM tracks").fetchone()[0]
            conn.execute("DELETE FROM tracks")
            conn.execute("DELETE FROM yt_imports")
            if keep_history_out and max_id:
                prev = conn.execute("SELECT value FROM meta WHERE key = 'min_message_id'").fetchone()
                floor = max(max_id, int(prev["value"]) if prev else 0)
                conn.execute("INSERT INTO meta (key, value) VALUES ('min_message_id', ?) "
                             "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (str(floor),))
            return {"deleted": count, "min_message_id": max_id if keep_history_out else 0}

        result = await self.db.transaction(_tx)
        await self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return result

    # ================================================================ заявки пользователей
    async def draft(self, user_id: int) -> dict[str, Any] | None:
        return await self.db.fetchone(
            "SELECT * FROM submissions WHERE user_id = ? AND status = 'draft' ORDER BY id DESC LIMIT 1", (user_id,))

    async def submission(self, sid: int) -> dict[str, Any] | None:
        return await self.db.fetchone(
            """SELECT s.*, u.first_name, u.last_name, u.username, u.display_name, u.vip, u.access_hash, u.lang,
                      u.language_code
               FROM submissions s JOIN users u ON u.id = s.user_id WHERE s.id = ?""", (sid,))

    async def submission_files(self, sid: int) -> list[dict[str, Any]]:
        return await self.db.fetchall("SELECT * FROM submission_files WHERE submission_id = ? ORDER BY id", (sid,))

    async def submission_file(self, fid: int) -> dict[str, Any] | None:
        return await self.db.fetchone(
            """SELECT f.*, s.user_id, s.status, u.access_hash FROM submission_files f
               JOIN submissions s ON s.id = f.submission_id JOIN users u ON u.id = s.user_id
               WHERE f.id = ?""", (fid,))

    async def files_last_day(self, user_id: int) -> int:
        return int(await self.db.fetchval(
            "SELECT COUNT(*) FROM upload_log WHERE user_id = ? AND created_at > ?", (user_id, now() - 86400)) or 0)

    async def prune_upload_log(self) -> None:
        await self.db.execute("DELETE FROM upload_log WHERE created_at < ?", (now() - 2 * 86400,))

    async def add_submission_file(self, user_id: int, f: dict[str, Any], per_batch: int, per_day: int) -> tuple[str, int]:
        """Атомарно проверяет лимиты и добавляет файл в черновик. Возвращает (статус, sid):
        'ok' | 'batch_full' | 'day_limit'."""

        def _tx(conn: sqlite3.Connection) -> tuple[str, int]:
            ts = now()
            used = conn.execute("SELECT COUNT(*) FROM upload_log WHERE user_id = ? AND created_at > ?",
                                (user_id, ts - 86400)).fetchone()[0]
            row = conn.execute("SELECT id FROM submissions WHERE user_id = ? AND status = 'draft' ORDER BY id DESC LIMIT 1",
                               (user_id,)).fetchone()
            sid = row["id"] if row else 0
            if used >= per_day:
                return "day_limit", sid
            if sid:
                n = conn.execute("SELECT COUNT(*) FROM submission_files WHERE submission_id = ?", (sid,)).fetchone()[0]
                if n >= per_batch:
                    return "batch_full", sid
            else:
                sid = int(conn.execute("INSERT INTO submissions (user_id, status, created_at) VALUES (?, 'draft', ?)",
                                       (user_id, ts)).lastrowid)
            conn.execute(
                """INSERT INTO submission_files (submission_id, chat_msg_id, title, performer, duration, file_size,
                   file_name, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (sid, f["chat_msg_id"], f["title"], f["performer"], f["duration"], f["file_size"], f["file_name"], ts))
            conn.execute("INSERT INTO upload_log (user_id, created_at) VALUES (?, ?)", (user_id, ts))
            return "ok", sid

        return await self.db.transaction(_tx)

    async def update_submission(self, sid: int, expect: str | None = None, **fields: Any) -> bool:
        """expect — менять только если текущий статус совпадает (защита от двойных нажатий и гонок).
        Возвращает True, если строка обновлена."""
        allowed = {"status", "tags", "reason", "panel_msg_id", "submitted_at", "decided_at", "decided_by", "published"}
        keys = [k for k in fields if k in allowed]
        if not keys:
            return False
        sql = f"UPDATE submissions SET {', '.join(k + ' = ?' for k in keys)} WHERE id = ?"
        params = [*(fields[k] for k in keys), sid]
        if expect is not None:
            sql += " AND status = ?"
            params.append(expect)
        return await self.db.execute(sql, params) > 0

    async def delete_submission_files(self, sid: int, file_ids: list[int] | None = None) -> None:
        if file_ids is None:
            await self.db.execute("DELETE FROM submission_files WHERE submission_id = ?", (sid,))
        elif file_ids:
            marks = ",".join("?" * len(file_ids))
            await self.db.execute(f"DELETE FROM submission_files WHERE submission_id = ? AND id IN ({marks})",
                                  [sid, *file_ids])

    async def delete_submission(self, sid: int) -> None:
        await self.db.execute("DELETE FROM submissions WHERE id = ?", (sid,))

    async def stale_drafts(self, older_than: int) -> list[dict[str, Any]]:
        return await self.db.fetchall(
            "SELECT id, user_id FROM submissions WHERE status = 'draft' AND created_at < ?", (now() - older_than,))

    async def admin_submissions(self, status: str, tag: str | None, q: str, offset: int, limit: int) -> list[dict[str, Any]]:
        where, params = ["s.status = ?"], [status]
        if tag:
            where.append("(' ' || s.tags || ' ') LIKE ? ESCAPE '\\'")
            params.append(f"% {like_escape(tag)} %")
        for w in [w for w in q.casefold().split() if w][:4]:
            where.append("""(casefold(u.first_name || ' ' || u.last_name || ' ' || COALESCE(u.username, '')
                         || ' ' || COALESCE(u.display_name, '')) LIKE ? ESCAPE '\\'
                OR EXISTS(SELECT 1 FROM submission_files f WHERE f.submission_id = s.id
                          AND casefold(f.title || ' ' || f.performer) LIKE ? ESCAPE '\\'))""")
            params += [f"%{like_escape(w)}%"] * 2
        order = "s.submitted_at ASC" if status == "pending" else "s.decided_at DESC"
        rows = await self.db.fetchall(
            f"""SELECT s.*, u.first_name, u.last_name, u.username, u.display_name, u.vip,
                   (SELECT COUNT(*) FROM submission_files f WHERE f.submission_id = s.id) AS file_count
                FROM submissions s JOIN users u ON u.id = s.user_id
                WHERE {' AND '.join(where)} ORDER BY {order} LIMIT ? OFFSET ?""",
            [*params, limit, offset])
        if rows:
            marks = ",".join("?" * len(rows))
            files = await self.db.fetchall(
                f"SELECT * FROM submission_files WHERE submission_id IN ({marks}) ORDER BY id", [r["id"] for r in rows])
            by_sub: dict[int, list] = {}
            for f in files:
                by_sub.setdefault(f["submission_id"], []).append(f)
            for r in rows:
                r["files"] = by_sub.get(r["id"], [])
        return rows

    async def submission_counts(self) -> dict[str, Any]:
        row = await self.db.fetchone(
            """SELECT SUM(status = 'pending') AS pending, SUM(status = 'approved') AS approved,
                      SUM(status = 'rejected') AS rejected FROM submissions""") or {}
        tags = await self.db.fetchall("SELECT tags FROM submissions WHERE status = 'pending' AND tags != ''")
        counter: dict[str, int] = {}
        for r in tags:
            for tg in r["tags"].split():
                counter[tg] = counter.get(tg, 0) + 1
        return {
            "pending": row.get("pending") or 0, "approved": row.get("approved") or 0, "rejected": row.get("rejected") or 0,
            "tags": sorted(counter, key=lambda k: (-counter[k], k))[:20],
        }
