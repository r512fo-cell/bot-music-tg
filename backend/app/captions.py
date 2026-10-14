"""Подписи к постам: жанры/теги публикуются как настоящие хэштеги Telegram.

Сущности (entities) задаются явно, поэтому хэштег кликабелен в любом клиенте и
приложение гарантированно распознаёт его как тег трека.
"""
from __future__ import annotations

import re

from telethon import types

TAG_TOKEN = re.compile(r"^#?([\w]{2,32})$", re.UNICODE)
HASHTAG = re.compile(r"#[\w]{2,32}", re.UNICODE)


def _utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def build_caption(text: str | None, max_tags: int = 10) -> tuple[str | None, list[types.TypeMessageEntity]]:
    """'phonk rock' -> '#phonk #rock'; свободный текст сохраняется, слова с # становятся хэштегами."""
    text = (text or "").strip()
    if not text:
        return None, []
    tokens = text.split()
    if all(TAG_TOKEN.match(tok) for tok in tokens):  # только жанры/теги — превращаем в хэштеги
        seen: list[str] = []
        for tok in tokens:
            tag = TAG_TOKEN.match(tok).group(1).casefold()
            if tag not in seen:
                seen.append(tag)
        text = " ".join(f"#{t}" for t in seen[:max_tags])
    entities = [
        types.MessageEntityHashtag(offset=_utf16_len(text[:m.start()]), length=_utf16_len(m.group()))
        for m in HASHTAG.finditer(text)
    ]
    return text, entities
