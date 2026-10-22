"""
Cell constructor shapes of module 03_registry (Spec 3.6, extended by
Spec 04_orders Appendix A): what a constructor emits must satisfy
``cell_matches`` for its column type, and only exactly that shape.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from modules._03_registry.cells import (
    cell_action_text,
    cell_datetime,
    cell_matches,
    cell_nation,
)


def test_new_cell_shapes_match_their_types():
    """``cell_datetime`` / ``cell_action_text`` / ``cell_nation`` emit the
    Spec 1.2 shapes and pass ``cell_matches``; a malformed ``mark`` or a
    nation cell without ``id`` does not."""
    moment = datetime(2026, 10, 15, 18, 21, tzinfo=UTC)
    cell = cell_datetime(moment, "Europe/Moscow")
    assert cell == {
        "date": "15.10.2026",
        "time": "21:21",  # UTC+3
        "key": int(moment.timestamp()),
        "day": (date(2026, 10, 15) - date(1970, 1, 1)).days,
        "mark": None,
    }
    assert cell_matches("datetime", cell)
    # The empty cell keeps the mark — an overdue stage without a moment.
    empty = cell_datetime(None, "Europe/Moscow", mark="overdue")
    assert empty == {
        "date": None,
        "time": None,
        "key": None,
        "day": None,
        "mark": "overdue",
    }
    assert cell_matches("datetime", empty)
    assert not cell_matches("datetime", {**cell, "mark": "bogus"})
    # A half-filled datetime dict is malformed.
    assert not cell_matches("datetime", {**empty, "key": 5})

    action = cell_action_text("Мобилизация", "order:12")
    assert action == {"text": "Мобилизация", "action": "order:12"}
    assert cell_matches("action_text", action)

    nation = cell_nation("Новгород", "#C0392B", nation_id="n-uuid-1")
    assert nation == {
        "id": "n-uuid-1",
        "name": "Новгород",
        "color": "#C0392B",
        "flag_url": None,
    }
    assert cell_matches("nation", nation)
    assert cell_matches("nation", {**nation, "id": None})
    assert cell_matches("nation", {**nation, "flag_url": "https://x.ru/f.png"})
    # No `id`, an extra key, or a non-string `id` — all malformed.
    assert not cell_matches(
        "nation", {"name": "Новгород", "color": "#C0392B", "flag_url": None}
    )
    assert not cell_matches("nation", {**nation, "extra": 1})
    assert not cell_matches("nation", {**nation, "id": 7})
