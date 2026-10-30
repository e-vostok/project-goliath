"""
Картинки государства: адресация и обработка (Spec 00_core, единица 5).

Единственное место, которое знает, как картинка превращается в адрес
(INV-16) и как загруженный файл проверяется и пережимается (INV-18):
тип определяется по содержимому (JPEG, PNG, WebP), пределы пикселей и
стороны проверяются по заголовку до распаковки, ориентация — по размеру
после поворота EXIF, дальше обрезка по центру до пропорции, приведение к
точному размеру, WebP без метаданных, миниатюра, sha256 полного файла.

Разбор — процессорная работа (170–360 мс на источнике 10–25 МП по
замерам docs/05_RESEARCH/images_0.12.0.md), поэтому ``process_image``
синхронна, а ``process_image_async`` выполняет её в пуле потоков под
общим семафором на одну картинку (сервер — один воркер на 4 ГБ).
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import threading
import weakref
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError, features

from modules._00_core.config_schema import ImagesSettings
from modules._00_core.exceptions import (
    ImageOrientationInvalidError,
    ImageTooLargeError,
    ImageUnsupportedError,
)

# Тип картинки — только по содержимому файла (INV-18).
_ALLOWED_FORMATS = ("JPEG", "PNG", "WEBP")

_KINDS = ("flag", "portrait")
_VARIANTS = ("full", "thumb")

# Тег EXIF «Orientation»; значения 5–8 меняют ширину и высоту местами.
_EXIF_ORIENTATION_TAG = 0x0112
_TRANSPOSE_ORIENTATIONS = (5, 6, 7, 8)

# Кодеки, без которых приём картинок невозможен (проверяются на старте).
_REQUIRED_CODECS = ("webp", "jpg", "zlib")  # zlib — кодек PNG

# Семафоры разбора — по одному на цикл событий, создаются лениво:
# модульный семафор, привязанный к одному циклу, упал бы с «attached to
# a different loop» в тестах, где циклов много.
_process_semaphores: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
_process_semaphores_guard = threading.Lock()


def image_url(sha256: str | None, variant: str) -> str | None:
    """Адрес картинки по содержимому; ``None`` для отсутствующей (INV-16)."""
    if sha256 is None:
        return None
    if variant not in _VARIANTS:
        raise ValueError(f"unknown image variant: {variant!r}")
    return f"/api/v1/images/{sha256}/{variant}"


@dataclass(frozen=True)
class ProcessedImage:
    """Результат пережатия загрузки: оба WebP и ключ содержимого."""

    full: bytes
    thumb: bytes
    sha256: str
    byte_size: int


def _cover_crop_size(
    src_w: int, src_h: int, aspect_w: int, aspect_h: int
) -> tuple[int, int]:
    """Наибольший вписанный прямоугольник пропорции aspect_w:aspect_h."""
    if src_w * aspect_h > src_h * aspect_w:
        # Источник шире целевой пропорции — обрезаем по ширине.
        return (src_h * aspect_w // aspect_h, src_h)
    return (src_w, src_w * aspect_h // aspect_w)


def _cover_crop_box(
    src_w: int, src_h: int, aspect_w: int, aspect_h: int
) -> tuple[int, int, int, int]:
    """Центральная обрезка до пропорции aspect_w:aspect_h."""
    crop_w, crop_h = _cover_crop_size(src_w, src_h, aspect_w, aspect_h)
    x0 = (src_w - crop_w) // 2
    y0 = (src_h - crop_h) // 2
    return (x0, y0, x0 + crop_w, y0 + crop_h)


def _flatten_to_rgb(img: Image.Image) -> Image.Image:
    """Прозрачность и палитра — на белый фон, дальше RGB (INV-18)."""
    if img.mode in ("RGBA", "LA", "PA", "RGBa") or "transparency" in img.info:
        rgba = img.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        return Image.alpha_composite(background, rgba).convert("RGB")
    if img.mode != "RGB":
        return img.convert("RGB")
    return img


def _encode_webp(img: Image.Image, quality: int) -> bytes:
    """WebP заданного качества; метаданные (EXIF, ICC) не переносятся."""
    out = io.BytesIO()
    img.save(out, "WEBP", quality=quality)
    return out.getvalue()


def process_image(
    raw: bytes, kind: str, config: ImagesSettings
) -> ProcessedImage:
    """Проверка и пережатие загруженного файла (синхронно, CPU-bound).

    Порядок проверок — Spec, абзац «Загрузка»: тип по содержимому →
    число пикселей и сторона по заголовку, до распаковки → ориентация по
    размеру после поворота EXIF → разбор.
    """
    if kind == "flag":
        target_w, target_h = config.flag_width, config.flag_height
        thumb_w, thumb_h = config.flag_thumb_width, config.flag_thumb_height
        need_horizontal = True
    elif kind == "portrait":
        target_w, target_h = config.portrait_width, config.portrait_height
        thumb_w, thumb_h = config.portrait_thumb_width, config.portrait_thumb_height
        need_horizontal = False
    else:
        raise ValueError(f"unknown image kind: {kind!r}")

    # (a) Тип — по сигнатуре файла; имя файла и Content-Type не участвуют.
    # DecompressionBombError Pillow выбрасывает уже на open по размеру из
    # заголовка — это переполнение лимита, а не «непонятный файл» (413).
    try:
        probe = Image.open(io.BytesIO(raw), formats=_ALLOWED_FORMATS)
    except Image.DecompressionBombError as exc:
        raise ImageTooLargeError(
            "declared pixel count is beyond the decoder safety limit"
        ) from exc
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as exc:
        raise ImageUnsupportedError("not a JPEG, PNG or WebP file") from exc

    try:
        # (b) Пределы по заголовку: probe.size известен без распаковки
        # пикселей — «бомба» маленького файла с огромным кадром отсекается
        # здесь, до того как память выделена.
        src_w, src_h = probe.size
        if src_w * src_h > config.max_pixels or max(src_w, src_h) > config.max_side:
            raise ImageTooLargeError(
                f"source {src_w}x{src_h} exceeds max_pixels="
                f"{config.max_pixels} or max_side={config.max_side}"
            )

        # (c) Ориентация — по размеру ПОСЛЕ поворота EXIF: ориентации 5–8
        # меняют ширину и высоту местами. Битый EXIF считается отсутствием
        # поворота — метаданным не доверяем (INV-18).
        try:
            exif_orientation = probe.getexif().get(_EXIF_ORIENTATION_TAG, 1)
        except Exception:
            exif_orientation = 1
        disp_w, disp_h = (
            (src_h, src_w)
            if exif_orientation in _TRANSPOSE_ORIENTATIONS
            else (src_w, src_h)
        )
        if need_horizontal and disp_w <= disp_h:
            raise ImageOrientationInvalidError(
                "flag must be wider than tall after EXIF rotation"
            )
        if not need_horizontal and disp_h <= disp_w:
            raise ImageOrientationInvalidError(
                "portrait must be taller than wide after EXIF rotation"
            )

        # (d) Распаковка: JPEG читается в режиме draft — уменьшенной
        # распаковки. Запрашивается ЦЕЛЕВОЙ размер (для повёрнутых по EXIF
        # — перевернутый: сохранённый кадр повёрнут относительно показа):
        # результат не меньше целевого в обеих сторонах, значит
        # центральная обрезка пропорции цели в него точно помещается, а
        # пик памяти перестаёт зависеть от размера источника (исследование
        # docs/05_RESEARCH/images_0.12.0.md). У анимированных PNG/WebP
        # берётся только первый кадр.
        try:
            draft_size = (
                (target_h, target_w)
                if exif_orientation in _TRANSPOSE_ORIENTATIONS
                else (target_w, target_h)
            )
            if getattr(probe, "is_animated", False):
                probe.seek(0)
            probe.draft("RGB", draft_size)
            img = ImageOps.exif_transpose(probe)
            if img is None:
                img = probe
            img.load()
        except Image.DecompressionBombError as exc:
            raise ImageTooLargeError(
                "declared pixel count is beyond the decoder safety limit"
            ) from exc
        except Exception as exc:
            raise ImageUnsupportedError("file cannot be decoded") from exc

        # (e) Центральная обрезка до пропорции и приведение к точному
        # размеру; источник меньше целевого увеличивается (это разрешено).
        img = _flatten_to_rgb(img)
        img = img.crop(_cover_crop_box(img.width, img.height, target_w, target_h))
        img = img.resize((target_w, target_h), Image.Resampling.LANCZOS)

        # (f)+(g) Полный размер и миниатюра из финальной картинки — WebP
        # без метаданных; sha256 считается по полному файлу.
        full = _encode_webp(img, config.webp_quality)
        thumb = _encode_webp(
            img.resize((thumb_w, thumb_h), Image.Resampling.LANCZOS),
            config.webp_quality,
        )
    finally:
        probe.close()

    return ProcessedImage(
        full=full,
        thumb=thumb,
        sha256=hashlib.sha256(full).hexdigest(),
        byte_size=len(full),
    )


def _process_semaphore() -> asyncio.Semaphore:
    """Общий семафор разбора для текущего цикла событий (лениво, один на цикл)."""
    loop = asyncio.get_running_loop()
    with _process_semaphores_guard:
        semaphore = _process_semaphores.get(loop)
        if semaphore is None:
            semaphore = asyncio.Semaphore(1)
            _process_semaphores[loop] = semaphore
    return semaphore


async def process_image_async(
    raw: bytes, kind: str, config: ImagesSettings
) -> ProcessedImage:
    """``process_image`` в пуле потоков под семафором одной картинки."""
    async with _process_semaphore():
        return await asyncio.to_thread(process_image, raw, kind, config)


def check_image_support() -> None:
    """Проверка кодеков Pillow на старте: без webp/jpg/zlib приём невозможен."""
    missing = [codec for codec in _REQUIRED_CODECS if not features.check(codec)]
    if missing:
        raise RuntimeError(
            "Pillow was built without required image codecs: "
            + ", ".join(missing)
        )
