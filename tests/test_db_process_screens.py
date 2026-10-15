"""D511: экраны показывают направления (процессы), а не цеха — из записанной `by_process`.

Ядро: цифра «где теряем» читается людьми как факт. Процесс без возможных вычетов
(`scored: false`) и с нулевой потерей на экране не стоит, а слабое направление
проверки — наибольшее из записанных чисел, не пересчёт.
"""

from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path

import pytest
from conftest import requires_db

psycopg = pytest.importorskip("psycopg")

from db_harness import accept_pushed, слить_проверку, точка_справочника  # noqa: E402

from src.db import queries  # noqa: E402
from src.db.reach import reach_of  # noqa: E402
from src.domain.models import ProcessScore  # noqa: E402

pytestmark = requires_db


def _процесс(код: str, loss: float, *, scored: bool = True) -> dict[str, object]:
    return {
        "code": код,
        "name_ru": f"{код}-ру",
        "name_en": f"{код}-en",
        "scored": scored,
        "d1": 0,
        "d2": 0,
        "d3": 0,
        "loss": loss,
    }


def _положить(pg_dsn: str, ident: str, by_process: dict[str, object] | None) -> None:
    """Подменяет разбивку проверки на приёмке: сторож 0073 не даёт переписать принятую."""
    with psycopg.connect(pg_dsn) as conn:
        conn.execute("update inspections set by_process = null where id = %s", (ident,))
        if by_process is not None:
            conn.execute(
                "update inspections set by_process = %s::jsonb where id = %s",
                (json.dumps(by_process), ident),
            )
        conn.commit()


@pytest.fixture
def сеть(pg_dsn: str, db_env: str, domain_env: Path) -> dict[str, str]:
    точка_справочника("Batumi-1", country="GE", city="Batumi")
    точка_справочника("Batumi-2", country="GE", city="Batumi")
    точка_справочника("Batumi-3", country="GE", city="Batumi")
    ид = {
        "обычная": слить_проверку(unit="Batumi-1", tenant="HQ", accept=False),
        "без_потерь": слить_проверку(unit="Batumi-2", tenant="HQ", accept=False),
        "без_разбивки": слить_проверку(unit="Batumi-3", tenant="HQ", accept=False),
    }
    _положить(
        pg_dsn,
        ид["обычная"],
        {
            "A": _процесс("A", 5.0),
            "B": _процесс("B", 2.0),
            # Самый «дорогой», но вычетов в нём быть не может — выбираться не должен.
            "INFO": _процесс("INFO", 9.0, scored=False),
            "Z": _процесс("Z", 0.0),
        },
    )
    _положить(pg_dsn, ид["без_потерь"], {"A": _процесс("A", 0.0), "Z": _процесс("Z", 0.0)})
    _положить(pg_dsn, ид["без_разбивки"], None)
    for ident in ид.values():
        accept_pushed(ident)
    return ид


def test_потери_по_направлениям_без_неоцениваемых_и_нулевых(сеть: dict[str, str]) -> None:
    строки = queries.process_losses(reach=reach_of("HQ"))

    assert [(код, потеря) for код, _ru, _en, потеря, _i, _u in строки] == [("A", 5.0), ("B", 2.0)]


def test_слабое_направление_проверки_наибольшее_из_оцениваемых(сеть: dict[str, str]) -> None:
    слабые = queries.worst_processes(reach=reach_of("HQ"))

    assert слабые[сеть["обычная"]][0] == "A"
    # Нет потерь и нет разбивки (историческая) — направления нет, а не выдуманное.
    assert сеть["без_потерь"] not in слабые
    assert сеть["без_разбивки"] not in слабые


def test_карточка_проверки_отдаёт_разбивку_или_none(сеть: dict[str, str]) -> None:
    охват = reach_of("HQ")

    есть = queries.get_inspection(сеть["обычная"], reach=охват)
    нет = queries.get_inspection(сеть["без_разбивки"], reach=охват)

    assert есть is not None and есть.by_process is not None and есть.by_process["A"]["loss"] == 5.0
    assert нет is not None and нет.by_process is None


def test_запросы_читают_поля_снимка_процесса_по_настоящим_именам() -> None:
    """Опечатка в `proc.value ->> '…'` не роняет запрос, а молча обнуляет экран (#354)."""
    поля = {поле.name for поле in dataclasses.fields(ProcessScore)}
    sqls = {
        имя: значение
        for имя, значение in vars(queries).items()
        if имя.endswith("_SQL") and isinstance(значение, str) and "proc.value" in значение
    }
    assert sqls, "не найдено ни одного запроса по by_process — проверка ослепла"

    прочитанные = {
        (имя, ключ)
        for имя, sql in sqls.items()
        for ключ in re.findall(r"proc\.value\s*->>\s*'([a-z_0-9]+)'", sql)
    }

    assert {(имя, ключ) for имя, ключ in прочитанные if ключ not in поля} == set()
