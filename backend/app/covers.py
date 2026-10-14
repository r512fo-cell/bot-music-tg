"""Обработка обложек: на хостинге храним только маленькие превью в WebP."""
from __future__ import annotations

import colorsys
import hashlib
import io
import logging
from pathlib import Path

from PIL import Image, ImageOps

log = logging.getLogger(__name__)

SIZES = {"s": 160, "l": 600}
MAX_SOURCE_BYTES = 10 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = 40_000_000  # защита от «декомпрессионных бомб»


def _square(img: Image.Image, size: int) -> Image.Image:
    return ImageOps.fit(img, (size, size), Image.Resampling.LANCZOS, centering=(0.5, 0.5))


def _accent_color(img: Image.Image) -> str:
    """Выбирает яркий «характерный» цвет обложки для фона плеера."""
    small = img.resize((48, 48), Image.Resampling.BILINEAR)
    quant = small.quantize(colors=6, method=Image.Quantize.MEDIANCUT)
    palette = quant.getpalette() or []
    best, best_score = (120, 90, 200), -1.0
    for count, idx in quant.getcolors() or []:
        r, g, b = palette[idx * 3: idx * 3 + 3]
        h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
        if l < 0.12 or l > 0.92:
            continue
        score = count * (0.25 + s) * (1 - abs(l - 0.5))
        if score > best_score:
            best, best_score = (r, g, b), score
    # нормализуем яркость, чтобы цвет хорошо смотрелся на тёмном фоне
    h, l, s = colorsys.rgb_to_hls(*(c / 255 for c in best))
    r, g, b = colorsys.hls_to_rgb(h, min(max(l, 0.42), 0.62), min(max(s, 0.35), 0.85))
    return "#{:02x}{:02x}{:02x}".format(int(r * 255), int(g * 255), int(b * 255))


def process_cover(raw: bytes, track_id: int, out_dir: Path) -> tuple[str, str] | None:
    """Сохраняет превью {name}_s.webp и {name}_l.webp. Возвращает (name, color)."""
    if not raw or len(raw) > MAX_SOURCE_BYTES:
        return None
    try:
        with Image.open(io.BytesIO(raw)) as src:
            src.draft("RGB", (SIZES["l"], SIZES["l"]))
            img = ImageOps.exif_transpose(src).convert("RGB")
    except Exception as exc:  # повреждённое или неподдерживаемое изображение
        log.warning("Не удалось открыть обложку трека %s: %s", track_id, exc)
        return None

    out_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(raw).hexdigest()[:10]
    name = f"{track_id}-{digest}"
    for suffix, size in SIZES.items():
        target = min(size, max(img.size))
        _square(img, target).save(out_dir / f"{name}_{suffix}.webp", "WEBP", quality=80, method=4)
    return name, _accent_color(img)


def remove_cover(name: str | None, out_dir: Path) -> None:
    if not name:
        return
    for suffix in SIZES:
        try:
            (out_dir / f"{name}_{suffix}.webp").unlink(missing_ok=True)
        except OSError:
            pass


def process_avatar(raw: bytes, path: Path) -> bool:
    try:
        with Image.open(io.BytesIO(raw)) as src:
            img = ImageOps.exif_transpose(src).convert("RGB")
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        _square(img, min(256, max(img.size))).save(tmp, "WEBP", quality=82)
        tmp.replace(path)
        return True
    except Exception as exc:
        log.warning("Не удалось обработать аватар: %s", exc)
        return False
