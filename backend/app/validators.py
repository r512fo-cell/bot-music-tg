"""Серверная валидация пользовательского ввода. Ошибки возвращаются кодами,
которые фронтенд переводит на язык интерфейса."""
from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlparse

LANGS = ("ru", "en")

# ------------------------------------------------------------------ альбомы
ALBUM_NAME_MIN = 1
ALBUM_NAME_MAX = 32
ALBUM_TRACKS_MAX = 500
# Разрешены: буквы любых алфавитов, цифры, пробел и этот набор знаков
ALBUM_PUNCT = frozenset(" -_.,!?&'()#+:")
ALBUM_ICONS = ("🎧", "🔥", "💜", "🌙", "🚗", "🏋️", "🎸", "🎹", "☕", "🌊", "⭐", "🎉")


class ValidationError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def normalize_album_name(raw: str) -> str:
    """NFKC + схлопывание пробелов. Проверка набора символов, длины и «мусорных» повторов."""
    if not isinstance(raw, str):
        raise ValidationError("album_name_empty")
    name = unicodedata.normalize("NFKC", raw)
    name = re.sub(r"\s+", " ", name).strip()
    if len(name) < ALBUM_NAME_MIN:
        raise ValidationError("album_name_empty")
    if len(name) > ALBUM_NAME_MAX:
        raise ValidationError("album_name_long")
    for ch in name:
        cat = unicodedata.category(ch)
        if cat[0] == "L" or cat in ("Nd", "Mn", "Mc") or ch in ALBUM_PUNCT:
            continue
        raise ValidationError("album_name_chars")
    if not any(ch.isalnum() for ch in name):
        raise ValidationError("album_name_alnum")
    if re.search(r"(.)\1{4,}", name):  # «аааааа», «!!!!!!»
        raise ValidationError("album_name_repeat")
    if re.search(r"[" + re.escape("".join(ALBUM_PUNCT - {" "})) + r"]{3,}", name):
        raise ValidationError("album_name_punct")
    return name


def album_name_key(name: str) -> str:
    """Ключ уникальности: регистр и пробелы не делают имя «новым»."""
    return name.casefold().replace(" ", "")


def validate_icon(icon: str) -> str:
    if icon not in ALBUM_ICONS:
        raise ValidationError("album_icon")
    return icon


# ------------------------------------------------------------------ имя в приложении
DISPLAY_NAME_MAX = 24
DISPLAY_NAME_PUNCT = frozenset(" -_.'")


def normalize_display_name(raw: str) -> str:
    """Имя, которое администратор задаёт пользователю: буквы, цифры, пробел и « -_.' »."""
    name = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", raw or "")).strip()
    if len(name) < 2:
        raise ValidationError("name_short")
    if len(name) > DISPLAY_NAME_MAX:
        raise ValidationError("name_long")
    for ch in name:
        cat = unicodedata.category(ch)
        if not (cat[0] == "L" or cat in ("Nd", "Mn", "Mc") or ch in DISPLAY_NAME_PUNCT):
            raise ValidationError("name_chars")
    if not any(ch.isalnum() for ch in name) or re.search(r"(.)\1{4,}", name):
        raise ValidationError("name_chars")
    return name


# ------------------------------------------------------------------ ссылки / тексты
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f​-‏‪-‮⁦-⁩]")


def clean_text(raw: str | None, max_len: int, *, multiline: bool = False, required: bool = False,
               code: str = "text") -> str:
    value = unicodedata.normalize("NFC", raw or "")
    value = _CTRL.sub("", value)
    if not multiline:
        value = re.sub(r"\s+", " ", value)
    value = value.strip()
    if required and not value:
        raise ValidationError(f"{code}_empty")
    if len(value) > max_len:
        raise ValidationError(f"{code}_long")
    return value


def validate_url(raw: str | None) -> str:
    """Только https:// (в т.ч. t.me). Никаких javascript:, data:, http:// и логинов в URL."""
    url = (raw or "").strip()
    if len(url) > 512:
        raise ValidationError("url_long")
    p = urlparse(url)
    if p.scheme != "https" or not p.hostname or p.username or p.password:
        raise ValidationError("url_invalid")
    if not re.fullmatch(r"[a-z0-9.-]+", p.hostname) or "." not in p.hostname:
        raise ValidationError("url_invalid")
    if _CTRL.search(url) or any(ch in url for ch in ' "<>\\`'):
        raise ValidationError("url_invalid")
    return url


# ------------------------------------------------------------------ реклама
AD_PLACEMENTS = ("home", "library")
AD_TITLE_MAX = 40
AD_TEXT_MAX = 140
AD_BUTTON_MAX = 24

# ------------------------------------------------------------------ рассылка
BROADCAST_TEXT_MAX = 3500
BROADCAST_AUDIENCES = ("all", "ru", "en")

# ------------------------------------------------------------------ deep links
START_PARAM_RE = re.compile(r"^(t_\d{1,12}|a_[A-Za-z0-9_-]{8,16})$")
