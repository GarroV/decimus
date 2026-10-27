"""Компоновка «Рейтингов» в базе: блок «Сравнение» (D551, миграция 0080)."""

from __future__ import annotations

import pytest
from conftest import requires_db

pytest.importorskip("psycopg")

from src.db import ratings_read as read
from src.ratings import layout as rl

pytestmark = requires_db


def test_сравнение_встаёт_под_средними_и_прячется_контролингом(db_env: str) -> None:
    порядок = [b.key for b in rl.arrange(read.layout_rows())]
    assert "compare" in порядок and "clients" in порядок  # строки есть у всех блоков (0080, 0101)

    было = [(b.key, b.visible) for b in rl.arrange(read.layout_rows())]
    try:
        read.save_layout([(k, k != "compare") for k, _ in было], actor="test")
        # Галочка легла: строка блока есть, `save_layout` её правит, а не теряет.
        assert dict((b.key, b.visible) for b in rl.arrange(read.layout_rows()))["compare"] is False
    finally:
        read.save_layout(было, actor="test")
