"""
Конвейер картинок государства (Spec 00_core, единица 5; INV-16, INV-18).

Все тестовые картинки генерируются Pillow прямо в тесте — бинарных
фикстур в репозитории нет. Проверяются: точные размеры выхода, WebP без
метаданных, детерминированный sha256, поворот EXIF, белый фон вместо
прозрачности, приём JPEG/PNG/WebP, отказ GIF/BMP/мусору/обрезанному
файлу, отсечка по заголовку до распаковки, правила ориентации, адреса
``image_url``, сериализация разбора семафором и стартовая проверка
кодеков.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import time

import pytest
from PIL import Image, ImageDraw, JpegImagePlugin, features

from modules._00_core import images
from modules._00_core.config_schema import CoreConfig
from modules._00_core.exceptions import (
    ImageOrientationInvalidError,
    ImageTooLargeError,
    ImageUnsupportedError,
)
from modules._00_core.images import (
    check_image_support,
    image_url,
    process_image,
    process_image_async,
)

CONFIG = CoreConfig.from_yaml(CoreConfig.get_default_config_path())
IMAGES = CONFIG.images


def _encoded(fmt: str, size: tuple[int, int], color=(10, 120, 200)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, fmt)
    return buf.getvalue()


def _png(size: tuple[int, int], color=(10, 120, 200)) -> bytes:
    return _encoded("PNG", size, color)


def _decode(payload: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(payload))
    img.load()
    return img


# --- Пережатие ------------------------------------------------------------


@pytest.mark.parametrize(
    "kind,source_size,expected_full,expected_thumb",
    [
        ("flag", (3000, 2000), (600, 400), (96, 64)),
        ("portrait", (1200, 2000), (600, 800), (120, 160)),
    ],
)
def test_exact_output_sizes(kind, source_size, expected_full, expected_thumb):
    """Крупный источник приводится к точному размеру полной картинки и
    миниатюры из конфига."""
    result = process_image(_png(source_size), kind, IMAGES)

    assert _decode(result.full).size == expected_full
    assert _decode(result.thumb).size == expected_thumb
    assert result.byte_size == len(result.full)


def test_output_is_webp_without_exif():
    """Выход — WebP, метаданные не переносятся (INV-18)."""
    result = process_image(_png((1200, 800)), "flag", IMAGES)

    out = _decode(result.full)
    assert out.format == "WEBP"
    assert len(out.getexif()) == 0


def test_same_input_gives_same_sha256():
    """Пережатие детерминированно: один файл — один адрес по содержимому."""
    raw = _png((1500, 1000), color=(50, 160, 90))

    first = process_image(raw, "flag", IMAGES)
    second = process_image(raw, "flag", IMAGES)

    assert first.sha256 == second.sha256
    assert first.sha256 == hashlib.sha256(first.full).hexdigest()


def test_exif_orientation_rotates_before_crop():
    """JPEG с EXIF-ориентацией 6 (хранится 400×600, показывается 600×400)
    принимается как флаг и поворачивается в правильную сторону: левая
    половина сохранённого кадра оказывается верхней половиной выхода."""
    stored = Image.new("RGB", (400, 600))
    draw = ImageDraw.Draw(stored)
    draw.rectangle((0, 0, 199, 599), fill=(220, 30, 30))
    draw.rectangle((200, 0, 399, 599), fill=(30, 30, 220))
    exif = Image.Exif()
    exif[0x0112] = 6
    buf = io.BytesIO()
    stored.save(buf, "JPEG", exif=exif)

    result = process_image(buf.getvalue(), "flag", IMAGES)

    out = _decode(result.full)
    r, g, b = out.getpixel((300, 10))
    assert r > 150 and b < 100, f"top edge should be red, got {(r, g, b)}"


def test_transparency_composited_on_white():
    """Прозрачный PNG уходит на белый фон — чёрных ореолов нет (INV-18)."""
    rgba = Image.new("RGBA", (900, 600), (0, 0, 0, 0))
    buf = io.BytesIO()
    rgba.save(buf, "PNG")

    result = process_image(buf.getvalue(), "flag", IMAGES)

    r, g, b = _decode(result.full).getpixel((10, 10))
    assert r > 240 and g > 240 and b > 240


@pytest.mark.parametrize("fmt", ["JPEG", "PNG", "WEBP"])
def test_supported_formats_accepted(fmt):
    """Тип определяется по содержимому: JPEG, PNG и WebP проходят."""
    result = process_image(_encoded(fmt, (1200, 800)), "flag", IMAGES)

    assert _decode(result.full).size == (600, 400)


# --- Отказы по типу и повреждению ------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        _encoded("GIF", (120, 80)),
        _encoded("BMP", (120, 80)),
        b"\x00\x01\x02\x03 not an image" * 8,
        _encoded("JPEG", (200, 100))[:900],
    ],
    ids=["gif", "bmp", "random-bytes", "truncated-jpeg"],
)
def test_unsupported_or_broken_files_rejected(payload):
    """GIF/BMP/мусор/обрезанный файл — IMAGE_UNSUPPORTED."""
    with pytest.raises(ImageUnsupportedError) as exc_info:
        process_image(payload, "flag", IMAGES)
    assert exc_info.value.code == "IMAGE_UNSUPPORTED"


# --- Отсечка по заголовку до распаковки -------------------------------------


@pytest.mark.parametrize(
    "size,mode",
    [
        ((9000, 10), "RGB"),  # сторона больше max_side
        ((6000, 5000), "RGB"),  # площадь больше max_pixels (30 МП)
        ((12000, 10000), "1"),  # 120 МП: зона DecompressionBombWarning
    ],
)
def test_oversize_rejected_before_decode(monkeypatch, size, mode):
    """Сторона больше max_side или площадь больше max_pixels —
    IMAGE_TOO_LARGE, и пиксели не распаковываются. Однобитный PNG
    12000×10000 — маленький файл с огромным заголовком: зона
    предупреждения Pillow (не ошибка), наш лимит отсекает раньше."""
    buf = io.BytesIO()
    Image.new(mode, size).save(buf, "PNG")
    monkeypatch.setattr(
        Image.Image,
        "load",
        lambda self: pytest.fail("pixels must not be decoded"),
    )
    with pytest.raises(ImageTooLargeError) as exc_info:
        process_image(buf.getvalue(), "flag", IMAGES)
    assert exc_info.value.code == "IMAGE_TOO_LARGE"


def test_decompression_bomb_is_too_large():
    """Заголовок сверх предела распаковщика Pillow (~179 МП) —
    IMAGE_TOO_LARGE (413), а не 500: DecompressionBombError поднимается
    уже на Image.open."""
    buf = io.BytesIO()
    Image.new("1", (20000, 10000)).save(buf, "PNG")

    with pytest.raises(ImageTooLargeError) as exc_info:
        process_image(buf.getvalue(), "flag", IMAGES)
    assert exc_info.value.code == "IMAGE_TOO_LARGE"


def test_jpeg_draft_reduces_decode(monkeypatch):
    """draft запрашивает ЦЕЛЕВОЙ размер: распаковка JPEG реально
    уменьшается (пик памяти не зависит от источника), а выход остаётся
    точным 600×400."""
    recorded: list[tuple[tuple[int, int], tuple[int, int]]] = []
    original = JpegImagePlugin.JpegImageFile.draft

    def _spy(self: Image.Image, mode: str, size: tuple[int, int]):
        result = original(self, mode, size)
        recorded.append((size, self.size))
        return result

    monkeypatch.setattr(JpegImagePlugin.JpegImageFile, "draft", _spy)

    result = process_image(_encoded("JPEG", (6000, 4000)), "flag", IMAGES)

    _request, decoded = recorded.pop()
    assert decoded[0] < 6000 and decoded[1] < 4000
    assert decoded[0] >= 600 and decoded[1] >= 400
    assert _decode(result.full).size == (600, 400)

    # EXIF-ориентация 6: кадр хранится 4000×6000 (показывается 6000×4000)
    # — запрос draft перевёрнут в координаты сохранённого кадра (400×600).
    stored = Image.new("RGB", (4000, 6000), (60, 140, 60))
    exif = Image.Exif()
    exif[0x0112] = 6
    buf = io.BytesIO()
    stored.save(buf, "JPEG", exif=exif)

    result = process_image(buf.getvalue(), "flag", IMAGES)

    _request, decoded = recorded.pop()
    assert decoded[0] < 4000 and decoded[1] < 6000
    assert decoded[0] >= 400 and decoded[1] >= 600
    assert _decode(result.full).size == (600, 400)


# --- Ориентация -------------------------------------------------------------


@pytest.mark.parametrize(
    "kind,size",
    [
        ("flag", (600, 600)),  # квадрат не проходит ни как флаг
        ("flag", (400, 600)),  # ни как вертикаль
        ("portrait", (600, 600)),  # квадрат не проходит ни как портрет
        ("portrait", (600, 400)),  # ни как горизонталь
    ],
)
def test_orientation_rejected(kind, size):
    """Флаг обязан быть строго шире высоты, портрет — строго выше ширины."""
    with pytest.raises(ImageOrientationInvalidError) as exc_info:
        process_image(_png(size), kind, IMAGES)
    assert exc_info.value.code == "IMAGE_ORIENTATION_INVALID"


# --- Адреса -----------------------------------------------------------------


def test_image_url():
    """Адрес строится только здесь (INV-16): None для отсутствующей
    картинки, variant строго full/thumb."""
    sha = "ab" * 32
    assert image_url(None, "full") is None
    assert image_url(sha, "full") == f"/api/v1/images/{sha}/full"
    assert image_url(sha, "thumb") == f"/api/v1/images/{sha}/thumb"
    with pytest.raises(ValueError):
        image_url(sha, "medium")


# --- Асинхронный разбор под семафором ----------------------------------------


async def test_concurrent_processing_is_serialized(monkeypatch):
    """Два параллельных process_image_async выполняются строго по очереди
    — семафор одной картинки не даёт распаковывать две сразу."""
    events: list[str] = []
    sentinel = object()

    def _fake(raw: bytes, kind: str, config) -> object:
        events.append(f"enter-{raw.decode()}")
        time.sleep(0.05)
        events.append(f"exit-{raw.decode()}")
        return sentinel

    monkeypatch.setattr(images, "process_image", _fake)

    first, second = await asyncio.gather(
        process_image_async(b"one", "flag", IMAGES),
        process_image_async(b"two", "flag", IMAGES),
    )

    assert first is sentinel and second is sentinel
    assert events in (
        ["enter-one", "exit-one", "enter-two", "exit-two"],
        ["enter-two", "exit-two", "enter-one", "exit-one"],
    )


# --- Стартовая проверка кодеков ----------------------------------------------


def test_check_image_support_missing_codec(monkeypatch):
    """Pillow без кодека (например webp) — RuntimeError на старте."""
    monkeypatch.setattr(features, "check", lambda codec: codec != "webp")

    with pytest.raises(RuntimeError, match="webp"):
        check_image_support()
