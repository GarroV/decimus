"""T349: разрыв ряда виден в ответе инструмента, а не только внутри (#337).

Признак сравнимости может быть каким угодно верным — если читатель его не
видит, ряд по-прежнему смешивает проверки молча. Поэтому здесь проверяется не
расчёт (он в `test_mcp_comparability.py`), а видимость: поле в ответе и фраза
в строке состояния, которую читают всегда.

База здесь не нужна и не используется: подменяется слой чтения строк. Так
проверка работает у всех, а не только там, где поднят Postgres, — и красит
прогон по делу, а не по отсутствию окружения.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from src.db.models import InspectionRow
from src.mcp import comparability, tools

ЦЕНА_ПЕРВАЯ = "aaaaaaaaaaaa"
ЦЕНА_ВТОРАЯ = "bbbbbbbbbbbb"


def _проверка(*, version: str, code: str = "bizdev", pct: float = 97.0) -> InspectionRow:
    return InspectionRow(
        id=f"{int(pct * 100):032d}",
        tenant_code="укашка",
        unit_name="Белград-1",
        chat_id=100500,
        kind="planned",
        inspection_date=date(2026, 9, 23),
        report_lang="ru",
        checklist_version=version,
        pct=pct,
        grade="A",
        findings_count=1,
        pushed_at="2026-09-23T18:00:00+02:00",
        checklist_code=code,
    )


@pytest.fixture
def ряд_из_двух_цен(monkeypatch: pytest.MonkeyPatch) -> list[InspectionRow]:
    """Две проверки одного чек-листа, посчитанные по разным ставкам."""
    строки = [
        _проверка(version="набор-2026-09-01-111111111111", pct=97.0),
        _проверка(version="набор-2026-09-10-222222222222", pct=91.0),
    ]
    цены = {
        "набор-2026-09-01-111111111111": ЦЕНА_ПЕРВАЯ,
        "набор-2026-09-10-222222222222": ЦЕНА_ВТОРАЯ,
    }
    monkeypatch.setattr(comparability, "shape_of", lambda version, code, papers: цены.get(version))
    monkeypatch.setattr(
        tools, "_read", lambda **_: tools._Page(rows=tuple(строки), limit=50, truncated=False)
    )
    monkeypatch.setattr(
        tools,
        "_read_everything",
        lambda **_: tools._Page(rows=tuple(строки), limit=50, truncated=False),
    )
    return строки


def _признак(ответ: dict[str, Any]) -> dict[str, Any]:
    значение = ответ[comparability.FIELD]
    assert isinstance(значение, dict)
    return значение


def test_история_точки_называет_разрыв_ряда(ряд_из_двух_цен: list[InspectionRow]) -> None:
    """Ряд одной точки — то место, где разницу цен и принимают за динамику."""
    ответ = tools.unit_history(tenant="укашка", unit="Белград-1")

    assert _признак(ответ)["comparable"] is False
    assert _признак(ответ)["note"] in str(ответ["status"]), (
        "разрыв назван только вложенным полем: строку состояния читают всегда, поле — когда знают"
    )


def test_сводка_по_сети_называет_разрыв_ряда(ряд_из_двух_цен: list[InspectionRow]) -> None:
    """Распределение букв по сети — ровно тот ряд, из-за которого задача заведена."""
    ответ = tools.network_summary(tenant="укашка")

    assert _признак(ответ)["comparable"] is False
    assert _признак(ответ)["note"] in str(ответ["status"])


def test_список_проверок_называет_разрыв_ряда(ряд_из_двух_цен: list[InspectionRow]) -> None:
    ответ = tools.list_inspections(tenant="укашка")

    assert _признак(ответ)["comparable"] is False


def test_целый_ряд_ничего_лишнего_не_говорит(monkeypatch: pytest.MonkeyPatch) -> None:
    """Предупреждение на каждом ответе обесценивает предупреждение по делу.

    Ряд, посчитанный по одной цене, обязан выглядеть как прежде: признак есть
    полем, а строка состояния остаётся чистой.
    """
    строки = [
        _проверка(version="набор-2026-09-01-111111111111", pct=97.0),
        _проверка(version="набор-2026-09-10-222222222222", pct=91.0),
    ]
    monkeypatch.setattr(comparability, "shape_of", lambda version, code, papers: ЦЕНА_ПЕРВАЯ)
    monkeypatch.setattr(
        tools, "_read", lambda **_: tools._Page(rows=tuple(строки), limit=50, truncated=False)
    )

    ответ = tools.unit_history(tenant="укашка", unit="Белград-1")

    assert _признак(ответ)["comparable"] is True
    assert _признак(ответ)["note"] == ""
    assert "not scored the same way" not in str(ответ["status"])
