"""#837: «Ещё не смотрели» — пункты зоны без записи, подсказка аудитору на ходу.

Блок отвечает на «что ещё посмотреть в ЭТОЙ зоне»: только пункты её, только без
записи в ней, замеры отдельным списком, оба языка. Ничего не блокирует.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.domain import add_finding, get_state, list_items, list_zones, start_inspection
from src.web import walk
from src.web.texts_walk import WALK_TEXTS

ЦЕХ = "hot_kitchen"


def _экран(lang: str = "ru") -> dict[str, Any]:
    проверка = get_state(1)
    assert проверка is not None
    return walk.build_walk(
        проверка,
        list_zones(chat_id=1),
        walk.PreviousOutcome(None),
        lang=lang,
        question=lambda code: None,
        items=list_items(chat_id=1),
    )


def _зона(данные: dict[str, Any], код: str) -> dict[str, Any]:
    return next(z for z in данные["zones"] if z["code"] == код)


def _коды(список: list[dict[str, Any]]) -> list[str]:
    return [i["code"] for i in список]


def _начать() -> None:
    start_inspection(1, unit="Белград-1", kind="planned", report_lang="ru", ui_lang="ru")


def test_в_блоке_только_пункты_этой_зоны(domain_env: Path) -> None:
    _начать()

    цех = _зона(_экран(), ЦЕХ)
    зал = _зона(_экран(), "dining")

    assert "PRD01" in _коды(цех["unseen"]), "пункт горячего цеха виден в горячем цехе"
    assert "PRD01" not in _коды(зал["unseen"]), "пункт чужой зоны здесь не предлагается"
    assert "CLN06" in _коды(зал["unseen"]), "пункт зала — в зале"
    assert not {"INF01", "PRD16"} & set(_коды(цех["unseen"])), "служебные пункты не предлагаются"


def test_пункт_пропадает_после_записи_с_этим_кодом(domain_env: Path) -> None:
    _начать()
    до = _коды(_зона(_экран(), ЦЕХ)["unseen"])

    add_finding(1, code="PRD01", level="D1", zone=ЦЕХ, text="нет маркировки")
    после = _зона(_экран(), ЦЕХ)

    assert "PRD01" in до
    assert "PRD01" not in _коды(после["unseen"])
    assert _коды(после["unseen"]) == [c for c in до if c != "PRD01"], "остальные на месте"


def test_запись_в_другой_зоне_пункт_не_убирает(domain_env: Path) -> None:
    _начать()

    add_finding(1, code="PRD02", level="D2", zone="cold_kitchen", text="не то")

    assert "PRD02" in _коды(_зона(_экран(), ЦЕХ)["unseen"]), "в цехе по нему ещё не смотрели"
    assert "PRD02" not in _коды(_зона(_экран(), "cold_kitchen")["unseen"])


def test_замеры_отдельно_и_только_явной_зоны(domain_env: Path) -> None:
    _начать()

    цех = _зона(_экран(), ЦЕХ)

    assert _коды(цех["unseen_info"]) == ["INF09"], "замер с зоной цеха — отдельным списком"
    assert not {"INF09", "INF10", "INF11", "INF20"} & set(_коды(цех["unseen"])), "не в нарушениях"
    assert "INF10" not in _коды(цех["unseen_info"]), "замер «везде» не шумит в каждой зоне"

    add_finding(1, code="INF09", level="D0", zone=ЦЕХ, text="63")
    assert _зона(_экран(), ЦЕХ)["unseen_info"] == [], "снятый замер уходит из строки"


def test_формулировки_на_языке_проверки_без_классов(domain_env: Path) -> None:
    _начать()

    ру = next(i for i in _зона(_экран("ru"), ЦЕХ)["unseen"] if i["code"] == "PRD01")
    en = next(i for i in _зона(_экран("en"), ЦЕХ)["unseen"] if i["code"] == "PRD01")

    assert ру["q"] != en["q"]
    assert en["q"].startswith("Prep item"), "английская формулировка"
    assert not ру["q"].startswith("(D"), "класс из начала формулировки убран"
    assert ру["levels"] == ["D1", "D2"], "уровни нужны, чтобы открыть форму с пунктом"


def test_тексты_блока_заведены_на_обоих_языках() -> None:
    for ключ in ("walk.unseen.title", "walk.unseen.info"):
        assert WALK_TEXTS[ключ]["ru"] and WALK_TEXTS[ключ]["en"], ключ
    assert walk.texts_for("en")["walk.unseen.title"] == "Not looked at yet"
    assert walk.texts_for("ru")["walk.unseen.title"] == "Ещё не смотрели"
