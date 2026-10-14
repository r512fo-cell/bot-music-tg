"""Статусы пользователей, которые выставляет администратор: Premium, блокировка, ограничения
и отображаемое имя.

Флаги нужны почти на каждом запросе (проверка блокировки, лимиты), поэтому держим их в памяти:
в словаре только пользователи, у которых хоть что-то отличается от значений по умолчанию.
Источник истины — таблица users; кэш обновляется в момент изменения из админки.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

# ---------------------------------------------------------------- лимиты
ALBUMS_USER = 50
ALBUMS_PREMIUM = 150
UPLOAD_USER = {"batch": 5, "day": 10}
UPLOAD_PREMIUM = {"batch": 30, "day": 60}


@dataclass(frozen=True)
class Flags:
    vip: bool = False           # Premium ⭐ в приложении (не путать с Telegram Premium)
    banned: bool = False        # доступ к приложению и боту закрыт
    no_albums: bool = False     # нельзя создавать и изменять альбомы
    no_uploads: bool = False    # нельзя предлагать треки
    display_name: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"vip": self.vip, "banned": self.banned, "no_albums": self.no_albums,
                "no_uploads": self.no_uploads, "display_name": self.display_name}


EMPTY = Flags()
_COLUMNS = ("vip", "banned", "no_albums", "no_uploads", "display_name")


def album_limit(flags: Flags, is_admin: bool) -> int:
    return ALBUMS_PREMIUM if (flags.vip or is_admin) else ALBUMS_USER


def upload_limits(flags: Flags, is_admin: bool = False) -> dict[str, int]:
    return dict(UPLOAD_PREMIUM if (flags.vip or is_admin) else UPLOAD_USER)


def from_row(row: dict[str, Any]) -> Flags:
    return Flags(vip=bool(row.get("vip")), banned=bool(row.get("banned")), no_albums=bool(row.get("no_albums")),
                 no_uploads=bool(row.get("no_uploads")), display_name=row.get("display_name") or None)


class UserFlags:
    def __init__(self) -> None:
        self._map: dict[int, Flags] = {}

    def get(self, user_id: int) -> Flags:
        return self._map.get(user_id, EMPTY)

    def put(self, user_id: int, flags: Flags) -> None:
        if flags == EMPTY:
            self._map.pop(user_id, None)
        else:
            self._map[user_id] = flags

    def update(self, user_id: int, **changes: Any) -> Flags:
        flags = replace(self.get(user_id), **changes)
        self.put(user_id, flags)
        return flags

    def load(self, rows: list[dict[str, Any]]) -> None:
        self._map = {}
        for row in rows:
            self.put(int(row["id"]), from_row(row))

    @staticmethod
    def select_sql() -> str:
        cols = ", ".join(_COLUMNS)
        return (f"SELECT id, {cols} FROM users WHERE vip = 1 OR banned = 1 OR no_albums = 1 "
                "OR no_uploads = 1 OR display_name IS NOT NULL")

    def __len__(self) -> int:
        return len(self._map)
