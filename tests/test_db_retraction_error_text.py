"""Отказ снятия не выносит наружу текст драйвера.

Путь чтения (`queries.py`) это правило уже держит: наружу уходит тип
исключения, потому что в тексте психкопга оказывается адрес базы. Путь снятия
жил по-другому, и до веб-админки это было полбеды — отказ читал тот, кто и так
знал стенд. Админка печатает его на карточке, а входа у неё нет, поэтому
правило распространено и сюда.

Базы этот файл не требует намеренно: подключение подменяется, и проверяется
ровно текст отказа, а не работа снятия.
"""

from __future__ import annotations

from typing import Any

import pytest

psycopg = pytest.importorskip("psycopg")

from src.db import retract as retract_module  # noqa: E402
from src.db.errors import RetractionError  # noqa: E402

АДРЕС = "host=скрытый-стенд.example port=6543 dbname=audit user=history"


def test_отказ_снятия_называет_тип_а_не_адрес_базы(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange — драйвер падает так, как он это делает на самом деле: адрес
    # стенда лежит прямо в тексте исключения.
    def упасть(*_a: Any, **_k: Any) -> Any:
        raise psycopg.OperationalError(f"connection failed: {АДРЕС}")

    monkeypatch.setattr(retract_module.psycopg, "connect", упасть)
    monkeypatch.setattr(
        retract_module,
        "load_retraction_settings",
        lambda: type("Настройки", (), {"dsn": "postgresql://неважно"})(),
    )

    # Act
    with pytest.raises(RetractionError) as отказ:
        retract_module.retract_inspection("0" * 32, tenant="demo", reason="ошибочный отчёт")

    # Assert — тип назван, адрес не назван.
    текст = str(отказ.value)
    assert "OperationalError" in текст
    for след in ("host=", "port=", "dbname=", "user=", "скрытый-стенд"):
        assert след not in текст, след
