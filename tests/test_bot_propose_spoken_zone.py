"""#1267, D646: быстрый путь берёт зону из слов, когда на экране зона не названа.

Зона записи — место, где найден продукт (D206), и первым источником у мини-аппа
стоят слова аудитора (`walk_zone.resolve_item_zone`: сказанное — раньше экрана).
Быстрый путь обязан читать зону в том же порядке: иначе «грязный пол в горячем
цехе» уходил к модели из-за того, что вкладка на экране была не выбрана, хотя
зона названа вслух. Спор слов и экрана решают слова — как у записи.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from conftest import live_data_env, requires_data  # noqa: F401 -- фикстура

from src.bot import propose as ядро
from src.web.walk_zone import resolve_item_zone

ЧАТ = 4242


@pytest.fixture
def без_модели(monkeypatch: pytest.MonkeyPatch) -> None:
    def нельзя(*a: Any, **k: Any) -> None:
        raise AssertionError("быстрый путь должен был закрыть поиск без модели")

    monkeypatch.setattr(ядро, "classify", нельзя)
    monkeypatch.setattr(ядро, "recall", lambda *a, **k: None)


def _найти(note: str, zone: str | None) -> ядро.Offer:
    return ядро.propose(
        note, [], zone=zone, chat_id=ЧАТ, ui_lang="ru", speech_lang="ru", report_lang="ru"
    )


def test_зона_в_словах_заменяет_пустую_зону_экрана(domain_env: Path, без_модели: None) -> None:
    итог = _найти("печь в нагаре на тепловом участке", None)

    assert итог.via == "fast" and итог.candidates[0].code == "CLN05"
    assert итог.candidates[0].zone == "hot_kitchen"


def test_зона_в_словах_побеждает_зону_экрана(domain_env: Path, без_модели: None) -> None:
    """Слова — тепловой участок, экран — холодный: выигрывают слова, как у `resolve_item_zone`."""
    итог = _найти("печь в нагаре на тепловом участке", "cold_kitchen")

    assert итог.via == "fast" and итог.candidates[0].zone == "hot_kitchen"
    # Тот же исход, что даёт вывод зоны записи для найденного пункта.
    вывод = resolve_item_zone(
        ("hot_kitchen",), spoken="hot_kitchen", model=None, hint="cold_kitchen"
    )
    assert (вывод.zone, вывод.source) == ("hot_kitchen", "words")


def test_без_зоны_в_словах_остаётся_зона_экрана(domain_env: Path, без_модели: None) -> None:
    итог = _найти("печь в нагаре", "hot_kitchen")

    assert итог.via == "fast" and итог.candidates[0].zone == "hot_kitchen"


def test_нет_зоны_нигде_быстрого_пути_нет(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    вызвана: list[str] = []
    monkeypatch.setattr(ядро, "recall", lambda *a, **k: None)

    class _S:
        candidates: tuple[Any, ...] = ()
        also_seen: tuple[Any, ...] = ()
        question = ""

    monkeypatch.setattr(ядро, "classify", lambda *a, **k: вызвана.append("модель") or _S())

    итог = _найти("печь в нагаре", None)

    assert итог.via == "model" and вызвана == ["модель"]


@requires_data
def test_боевая_методика_грязный_пол_в_горячем_цехе_без_модели(
    live_data_env: Path,  # noqa: F811
    без_модели: None,
) -> None:
    """Образец владельца (#1267): зона только в словах — и пункт найден мгновенно."""
    итог = _найти("грязный пол в горячем цехе", None)

    assert итог.via == "fast", итог
    assert итог.candidates[0].code == "CLN03" and итог.candidates[0].zone == "hot_kitchen"
