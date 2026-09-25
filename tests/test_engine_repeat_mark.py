"""#359: пометку повтора можно поставить и снять у уже записанного нарушения.

Аудитор на обходе сначала фиксирует нарушение, и только потом система
подсказывает, что такое же было в прошлый раз. Значит пометка обязана
ставиться ПОСЛЕ записи — иначе подсказка бесполезна, а решение о цене
приходится принимать до того, как есть чем его обосновать.

Снятие так же обязательно, как постановка: ошибиться в пометке — то же самое,
что ошибиться в классе нарушения, и цена ошибки здесь прямая.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from conftest import Run


def оценка(started: Callable[..., Run]) -> dict:
    r = started("score", "--json")
    assert r.code == 0, r.text
    return json.loads(r.text)


def записи(workdir: Path) -> list[dict]:
    return json.loads((workdir / "inspection.json").read_text(encoding="utf-8"))["findings"]


def test_пометка_ставится_после_записи(started: Callable[..., Run], workdir: Path) -> None:
    assert started("add", "--qid", "PRD05", "--level", "D2", "--zone", "hot_kitchen").code == 0
    assert оценка(started)["deductions"] == 2.0

    r = started("edit", "--n", "1", "--repeat")

    assert r.code == 0, r.text
    assert записи(workdir)[0]["repeat"] is True
    assert оценка(started)["deductions"] == 4.0, "цена не пересчитана после пометки"


def test_пометка_снимается(started: Callable[..., Run], workdir: Path) -> None:
    assert started(
        "add", "--qid", "PRD05", "--level", "D2", "--zone", "hot_kitchen", "--repeat"
    ).code == 0

    r = started("edit", "--n", "1", "--no-repeat")

    assert r.code == 0, r.text
    assert записи(workdir)[0]["repeat"] is False
    assert оценка(started)["deductions"] == 2.0, "снятая пометка продолжает удваивать"


def test_правка_одной_пометкой_не_считается_пустой(started: Callable[..., Run]) -> None:
    # `edit` отказывается менять «ничего», и пометка обязана считаться
    # изменением наравне с полями: иначе единственный способ её поставить —
    # заодно переписать что-то ещё.
    assert started("add", "--qid", "PRD05", "--level", "D2", "--zone", "hot_kitchen").code == 0

    r = started("edit", "--n", "1", "--repeat")

    assert r.code == 0, r.text
    assert "Нечего менять" not in r.text


def test_правка_других_полей_пометку_не_трогает(started: Callable[..., Run], workdir: Path) -> None:
    # Пометка — отдельное решение о цене. Правка формулировки её снимать не
    # должна: аудитор поправил слова, а не передумал про повтор.
    assert started(
        "add", "--qid", "PRD05", "--level", "D2", "--zone", "hot_kitchen", "--repeat"
    ).code == 0

    assert started("edit", "--n", "1", "--evidence", "другая формулировка").code == 0

    assert записи(workdir)[0]["repeat"] is True


def test_пометка_несуществующей_записи_это_отказ(started: Callable[..., Run]) -> None:
    r = started("edit", "--n", "77", "--repeat")

    assert r.code != 0
    assert "77" in r.text
