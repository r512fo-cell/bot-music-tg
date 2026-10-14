"""Простые, но осмысленные рекомендации «Для вас» (без внешних библиотек и тяжёлых моделей).

Сигналы:
* вкус пользователя — исполнители и теги из его прослушиваний (90 дней) и избранного;
* «слушают вместе» — что слушают люди с пересекающимися прослушиваниями (коллаборативный сигнал);
* популярность и свежесть трека;
* небольшая случайность, стабильная в течение дня (подборка не «скачет» при каждом открытии).
Исключаются: избранное и треки, прослушанные за последние 7 дней. Не больше 2 треков одного автора.
Холодный старт (нет истории): популярное + свежее. Результат кэшируется на 10 минут.

Нагрузка: каталог треков читается один раз на всех (кэш 5 минут), на пользователя — только его
история; ранжирование выполняется в отдельном потоке и не задерживает другие запросы.
"""
from __future__ import annotations

import asyncio
import hashlib
import math
import sqlite3
import time
from collections import OrderedDict, defaultdict
from typing import Any

from .db import Database
from .repo import _ARTIST_SPLIT

CACHE_TTL = 600
CATALOG_TTL = 300
HISTORY_DAYS = 90
RECENT_DAYS = 7
PER_ARTIST = 2


def _artists(performer: str) -> list[str]:
    return [a for a in (p.strip() for p in _ARTIST_SPLIT.split((performer or "").casefold())) if a]


def _jitter(user_id: int, track_id: int) -> float:
    day = int(time.time() // 86400)
    h = hashlib.blake2b(f"{user_id}:{track_id}:{day}".encode(), digest_size=4).digest()
    return int.from_bytes(h, "big") / 0xFFFFFFFF


def _catalog(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Все видимые треки с тегами — одним проходом (без подзапроса на каждую строку)."""
    tags: defaultdict[int, list[str]] = defaultdict(list)
    for tid, tag in conn.execute(
            "SELECT g.track_id, g.tag FROM track_tags g JOIN tracks t ON t.id = g.track_id "
            "WHERE t.is_deleted = 0 AND t.is_hidden = 0"):
        tags[tid].append(tag)
    return [
        {"id": r[0], "performer": r[1], "posted_at": r[2], "plays": r[3], "tags": " ".join(tags.get(r[0], ()))}
        for r in conn.execute("SELECT id, performer, posted_at, plays FROM tracks WHERE is_deleted = 0 AND is_hidden = 0")
    ]


def _collect(conn: sqlite3.Connection, user_id: int) -> dict[str, Any]:
    now = int(time.time())
    mine = conn.execute(
        """SELECT track_id, COUNT(*) AS c, MAX(played_at) AS last FROM plays
           WHERE user_id = ? AND played_at > ? GROUP BY track_id""",
        (user_id, now - HISTORY_DAYS * 86400)).fetchall()
    favs = {r[0] for r in conn.execute("SELECT track_id FROM favorites WHERE user_id = ?", (user_id,))}
    co: dict[int, int] = {}
    seed = list({r["track_id"] for r in mine} | favs)[:200]
    if seed:
        marks = ",".join("?" * len(seed))
        neighbours = [r[0] for r in conn.execute(
            f"""SELECT user_id FROM plays WHERE track_id IN ({marks}) AND user_id != ? AND played_at > ?
                GROUP BY user_id ORDER BY MAX(played_at) DESC LIMIT 300""",
            (*seed, user_id, now - HISTORY_DAYS * 86400))]
        if neighbours:
            marks = ",".join("?" * len(neighbours))
            co = {r[0]: r[1] for r in conn.execute(
                f"""SELECT track_id, COUNT(DISTINCT user_id) FROM plays
                    WHERE user_id IN ({marks}) AND played_at > ? GROUP BY track_id""",
                (*neighbours, now - HISTORY_DAYS * 86400))}
    return {"mine": mine, "favs": favs, "co": co, "now": now}


class Recommender:
    def __init__(self, db: Database) -> None:
        self.db = db
        self._cache: OrderedDict[int, tuple[float, list[int]]] = OrderedDict()
        self._catalog: tuple[float, list[dict[str, Any]]] | None = None
        self._catalog_lock = asyncio.Lock()

    async def catalog(self) -> list[dict[str, Any]]:
        async with self._catalog_lock:  # при пустом кэше каталог читает только один запрос
            if not self._catalog or time.monotonic() - self._catalog[0] > CATALOG_TTL:
                tracks = await self.db.run(_catalog)
                # пустой каталог не кэшируем: треки могут появиться в любую минуту
                self._catalog = (time.monotonic(), tracks) if tracks else None
                return tracks
            return self._catalog[1]

    async def for_user(self, user_id: int, limit: int = 10) -> list[int]:
        hit = self._cache.get(user_id)
        if hit and time.monotonic() - hit[0] < CACHE_TTL:
            return hit[1]
        tracks = await self.catalog()
        data = await self.db.run(lambda conn: _collect(conn, user_id))
        data["tracks"] = tracks
        ids = await asyncio.to_thread(rank, user_id, data, limit)
        if not ids:
            return ids
        self._cache[user_id] = (time.monotonic(), ids)
        self._cache.move_to_end(user_id)
        while len(self._cache) > 2000:
            self._cache.popitem(last=False)
        return ids

    def invalidate(self, user_id: int | None = None) -> None:
        if user_id is None:
            self._cache.clear()
            self._catalog = None
        else:
            self._cache.pop(user_id, None)


def rank(user_id: int, data: dict[str, Any], limit: int) -> list[int]:
    tracks, favs, co, now = data["tracks"], data["favs"], data["co"], data["now"]
    if not tracks:
        return []
    by_id = {t["id"]: t for t in tracks}

    # --- профиль вкуса
    artist_w: defaultdict[str, float] = defaultdict(float)
    tag_w: defaultdict[str, float] = defaultdict(float)
    recent = set()
    def feed(track: Any, weight: float) -> None:
        for a in _artists(track["performer"]):
            artist_w[a] += weight
        for g in (track["tags"] or "").split():
            tag_w[g] += weight
    for r in data["mine"]:
        t = by_id.get(r["track_id"])
        if t:
            age_days = (now - r["last"]) / 86400
            feed(t, min(r["c"], 5) * (1.0 if age_days < 30 else 0.5))
            if age_days < RECENT_DAYS:
                recent.add(r["track_id"])
    for tid in favs:
        if tid in by_id:
            feed(by_id[tid], 3.0)
    has_profile = bool(artist_w or tag_w)

    max_a = max(artist_w.values(), default=1.0)
    max_t = max(tag_w.values(), default=1.0)
    max_co = max(co.values(), default=1)
    max_plays = max((t["plays"] for t in tracks), default=0)

    def score(t: Any) -> float:
        s = 0.0
        if has_profile:
            s += 2.0 * max((artist_w.get(a, 0.0) for a in _artists(t["performer"])), default=0.0) / max_a
            s += 1.5 * min(1.0, sum(tag_w.get(g, 0.0) for g in (t["tags"] or "").split()) / max_t)
            s += 1.2 * co.get(t["id"], 0) / max_co
        s += (0.6 if has_profile else 1.4) * (math.log1p(t["plays"]) / math.log1p(max_plays) if max_plays else 0)
        age = (now - t["posted_at"]) / 86400
        s += (0.5 if has_profile else 1.0) * max(0.0, 1 - age / 14)
        return s + 0.35 * _jitter(user_id, t["id"])

    # кандидаты: сначала «новое для пользователя», при нехватке — всё, кроме избранного
    ranked = sorted(tracks, key=score, reverse=True)  # оценка считается один раз на трек
    pools = [
        [t for t in ranked if t["id"] not in favs and t["id"] not in recent],
        [t for t in ranked if t["id"] not in favs],
        ranked,
    ]
    result: list[int] = []
    per_artist: defaultdict[str, int] = defaultdict(int)
    for pool in pools:
        for t in pool:
            if len(result) >= limit:
                return result
            if t["id"] in result:
                continue
            main = (_artists(t["performer"]) or [""])[0]
            if main and per_artist[main] >= PER_ARTIST and pool is pools[0]:
                continue  # разнообразие: не больше 2 треков одного автора
            per_artist[main] += 1
            result.append(t["id"])
    return result
