"""D710: журнал обхода на карточке — шаги словами, без кодов пунктов и без «D1» вместо класса."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.db.walk_log import StepRow
from src.web import walk_log_view
from src.web.texts import TEXTS

ПУНКТ = "Порядок 14 — повреждённая мусорка"


def _row(**kw: object) -> StepRow:
    base: dict[str, object] = dict(
        id=1,
        at=datetime(2026, 11, 5, 15, 33, 7, tzinfo=UTC),
        run_id="run-1",
        unit="Brasov-1",
        step="class",
        outcome="ok",
        words="повреждённая мусорка на улице",
        photos=1,
        item_code="TEH14",
        zone="outside",
        level=None,
        verdict="not_established",
        reason="Повреждение не мешает работе",
        via=None,
        detail={},
        duration_ms=2310,
        error="",
        login="pavel",
    )
    return StepRow(**{**base, **kw})  # type: ignore[arg-type]


def _build(*rows: StepRow, lang: str = "ru") -> tuple[walk_log_view.Run, ...]:
    return walk_log_view.build(
        rows,
        lang=lang,
        full=lambda code: ПУНКТ if code == "TEH14" else code,
        zone_names={"outside": "Территория"},
    )


def test_the_disputed_step_reads_in_words_without_item_codes() -> None:
    (run,) = _build(_row())

    text = "\n".join(line for step in run.steps for line in step.lines)
    assert run.heading == "Обход: Brasov-1" and run.who == "аудитор pavel"
    assert "Нарушение по этим фактам не установлено" in text
    assert f"Пункт: {ПУНКТ}" in text and "Зона: Территория" in text
    assert "Причина: Повреждение не мешает работе" in text
    assert "TEH14" not in text and "outside" not in text
    assert run.steps[0].duration == "2310 мс" and run.steps[0].at == "2026-11-05 15:33:07"


def test_classes_are_named_and_offers_use_item_wording() -> None:
    row = _row(
        step="suggest",
        verdict=None,
        item_code="TEH14",
        via="model",
        detail={"candidates": [{"code": "TEH14", "level": "D2", "zone": "outside"}]},
    )

    (run,) = _build(row)

    lines = run.steps[0].lines
    assert any(ПУНКТ in line and "значительное (D2)" in line for line in lines)
    assert "Путь: модель" in lines


def test_fallback_and_refusal_are_explained() -> None:
    row = _row(
        step="suggest",
        outcome="error",
        verdict=None,
        via="fallback",
        error="ModelUnavailable",
        detail={"reason_code": "walk.err.recognize"},
    )

    (run,) = _build(row)

    lines = run.steps[0].lines
    assert "Модель недоступна — пункт выбирается вручную" in lines
    assert any(line.startswith("Отказ: ") for line in lines)
    assert "Сбой: ModelUnavailable" in lines and run.steps[0].tone == "tag--err"


def test_english_and_grouping_by_run() -> None:
    rows = (_row(), _row(id=2, run_id="run-2", unit="Brasov-2", login=None))

    first, second = _build(*rows, lang="en")

    assert first.heading == "Walk: Brasov-1" and second.who == ""
    assert "No violation established from these facts" in first.steps[0].lines


@pytest.mark.parametrize("key", [k for k in TEXTS if k.startswith("walklog.")])
def test_every_walk_log_text_has_both_languages(key: str) -> None:
    assert TEXTS[key]["ru"].strip() and TEXTS[key]["en"].strip()
