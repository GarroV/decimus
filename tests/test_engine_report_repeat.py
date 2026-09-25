"""#359: отчёт объясняет удвоенный вычет, а не оставляет его без объяснения.

Партнёр читает отчёт как счёт: по нему он платит и по нему спорит. Запись,
стоившая вдвое, без пометки выглядит ошибкой расчёта — и оспаривается именно
как ошибка, потому что проверить её по тексту отчёта нечем.

Раздел «Методика расчёта» — второе место: правило, по которому цена выросла,
обязано быть напечатано там же, где остальные правила.
"""

from __future__ import annotations

from collections.abc import Callable

from conftest import Run


def test_повторная_запись_помечена_в_отчёте(
    started: Callable[..., Run], report: Callable[..., Run]
) -> None:
    assert started(
        "add", "--qid", "PRD05", "--level", "D2", "--zone", "hot_kitchen", "--repeat"
    ).code == 0

    r = report("html")

    assert r.code == 0, r.text
    assert "повтор — вычет удвоен" in r.out, (
        "у записи нет пометки, объясняющей удвоенный вычет"
    )


def test_обычная_запись_пометки_не_получает(
    started: Callable[..., Run], report: Callable[..., Run]
) -> None:
    # Обратная сторона: пометка у всех подряд обесценивает её и делает отчёт
    # неверным ровно там, где он должен быть точным. Правило в разделе
    # методики при этом печатается всегда — оно описывает расчёт, а не запись.
    assert started("add", "--qid", "PRD05", "--level", "D2", "--zone", "hot_kitchen").code == 0

    r = report("html")

    assert r.code == 0, r.text
    assert "повтор — вычет удвоен" not in r.out


def test_методика_в_отчёте_называет_правило_удвоения(
    started: Callable[..., Run], report: Callable[..., Run]
) -> None:
    assert started("add", "--qid", "PRD05", "--level", "D2", "--zone", "hot_kitchen").code == 0

    r = report("html")

    assert r.code == 0, r.text
    assert "двое" in r.out or "двойн" in r.out, (
        "раздел методики не объясняет, почему повтор стоит дороже"
    )


def test_правило_названо_и_по_английски(
    started: Callable[..., Run], report: Callable[..., Run]
) -> None:
    # Язык отчёта — параметр продукта, а не константа: партнёр читает на своём.
    assert started("add", "--qid", "PRD05", "--level", "D2", "--zone", "hot_kitchen").code == 0

    r = report("html", "--lang", "en")

    assert r.code == 0, r.text
    assert "twice" in r.out.lower() or "double" in r.out.lower()
