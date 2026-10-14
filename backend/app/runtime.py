"""Настройки, которые администратор меняет «на лету» (хранятся в таблице meta)."""
from __future__ import annotations

from dataclasses import dataclass

from .repo import Repo


THEMES = ("default", "auto", "autumn", "winter", "spring", "summer")


@dataclass
class RuntimeSettings:
    maintenance: bool = False
    maintenance_text: str = ""
    theme: str = "default"

    async def load(self, repo: Repo) -> None:
        self.maintenance = (await repo.get_meta("maintenance")) == "1"
        self.maintenance_text = await repo.get_meta("maintenance_text") or ""
        theme = await repo.get_meta("theme") or "default"
        self.theme = theme if theme in THEMES else "default"

    async def set_theme(self, repo: Repo, theme: str) -> None:
        if theme not in THEMES:
            raise ValueError("theme")
        await repo.set_meta("theme", theme)
        self.theme = theme

    async def save(self, repo: Repo, *, maintenance: bool, maintenance_text: str) -> None:
        await repo.set_meta("maintenance", "1" if maintenance else "0")
        await repo.set_meta("maintenance_text", maintenance_text)
        self.maintenance = maintenance
        self.maintenance_text = maintenance_text
