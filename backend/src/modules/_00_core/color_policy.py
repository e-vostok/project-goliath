"""
Чистые функции различимости цветов государств (без БД и без FastAPI).

Расстояние считается в пространстве OKLab как евклидово: чёрный и белый
находятся на расстоянии 1.0. Формула и тестовые векторы — Spec 00_core, Часть 3.
Модуль импортируется схемой конфига, поэтому не должен зависеть от БД.
"""

from __future__ import annotations

import math


def _srgb_to_linear(channel: int) -> float:
    c = channel / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def hex_to_oklab(hex_color: str) -> tuple[float, float, float]:
    """Переводит '#RRGGBB' (регистр любой) в координаты OKLab (L, a, b)."""
    h = hex_color.lstrip("#")
    r, g, b = (_srgb_to_linear(int(h[i : i + 2], 16)) for i in (0, 2, 4))
    lum = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l_, m_, s_ = lum ** (1 / 3), m ** (1 / 3), s ** (1 / 3)
    return (
        0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
        1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
        0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_,
    )


def oklab_distance(first_hex: str, second_hex: str) -> float:
    """Евклидово расстояние между двумя цветами в OKLab."""
    return math.dist(hex_to_oklab(first_hex), hex_to_oklab(second_hex))
