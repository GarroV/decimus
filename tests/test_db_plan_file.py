"""Файл «туда и обратно» электронного плана в базе (#1168, шаг 3; миграция `0093`).

Ядро — запись строк файла той же дверью, что правка на экране, и ревизия: план на экране
поменяли после выгрузки файла — ничего не пишется, пока человек не выберет. Права и сторожа
базы те же, что у `save_row` (`tests/test_db_plan_rows.py`): здесь — что дверь файла их не
обходит (чужая страна, УК, план на согласовании) и что срок позже положенного не ложится.
"""

# ruff: noqa: F811 — фикстуры набора подтягиваются импортом и подставляются по имени

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from conftest import requires_db
from test_db_plan_rows import (  # noqa: F401 — фикстуры набора подтягиваются импортом
    ГРУЗИЯ_АННА,
    СЕГОДНЯ,
    _заполнить,
    _запрос,
    _на_согласовании,
    _принятая,
    _Склад,
    admin_env,
    сеть,
)

psycopg = pytest.importorskip("psycopg")

from src.db import action_plans as plans  # noqa: E402
from src.db import plan_flow as flow  # noqa: E402
from src.db.errors import ActionPlanError  # noqa: E402
from src.db.plan_file import DUE_NOT_DATE, SKIP_UNKNOWN, FileRow  # noqa: E402
from src.db.reach import reach_of  # noqa: E402
from src.domain.plan_due import OWN_DUE_LATE  # noqa: E402

pytestmark = requires_db


def _из_файла(row_id: str, line: int, **kw: Any) -> FileRow:
    данные: dict[str, Any] = {
        "line": line,
        "row_id": row_id,
        "measure": "Из файла",
        "responsible": "Шеф из файла",
        "reason": "",
        "due": None,
    }
    данные.update(kw)
    return FileRow(**данные)


def _применить(
    запрос: plans.PlanRequest, строки: list[FileRow], *, revision: int | None = None, **kw: Any
) -> Any:
    return flow.apply_file_rows(
        запрос.id,
        reach=kw.pop("reach", reach_of("GE")),
        tenant=kw.pop("tenant", "GE"),
        actor=ГРУЗИЯ_АННА,
        file_rows=строки,
        expected_revision=запрос.revision if revision is None else revision,
        **kw,
    )


def test_строки_файла_ложатся_в_план_и_ревизия_растёт(сеть: dict[str, str]) -> None:
    запрос = _запрос(_принятая("D2", "D1"))
    первая, вторая = запрос.rows

    итог = _применить(
        запрос, [_из_файла(первая.id, 11), _из_файла(вторая.id, 12, reason="Не успели")]
    )

    после = _запрос(запрос.inspection_id)
    assert итог.conflict is False and итог.written == 2
    assert [(r.measure, r.responsible) for r in после.rows] == [("Из файла", "Шеф из файла")] * 2
    assert после.rows[1].reason == "Не успели"
    assert после.revision == запрос.revision + 2


def test_строка_совпавшая_с_экраном_не_пишется_и_ревизию_не_трогает(
    сеть: dict[str, str],
) -> None:
    запрос = _запрос(_принятая("D2"))
    строка = запрос.rows[0]
    _заполнить(запрос, measure="Из файла", responsible="Шеф из файла")
    экран = _запрос(запрос.inspection_id)

    итог = _применить(экран, [_из_файла(строка.id, 11)])

    assert итог.written == 0 and итог.reconciled.unchanged == 1
    assert _запрос(запрос.inspection_id).revision == экран.revision


def test_ревизия_разошлась_конфликт_и_ничего_не_записано(сеть: dict[str, str]) -> None:
    запрос = _запрос(_принятая("D2"))
    строка = запрос.rows[0]
    flow.save_row(
        запрос.id, строка.id, reach=reach_of("GE"), tenant="GE", actor=ГРУЗИЯ_АННА,
        measure="С экрана", responsible="Шеф", reason=None, own_due=None,
    )  # fmt: skip
    экран = _запрос(запрос.inspection_id)
    assert экран.revision > запрос.revision

    итог = _применить(экран, [_из_файла(строка.id, 11)], revision=запрос.revision)

    assert итог.conflict is True and итог.written == 0
    assert [c.row.id for c in итог.reconciled.changes] == [строка.id]
    после = _запрос(запрос.inspection_id)
    assert (после.rows[0].measure, после.revision) == ("С экрана", экран.revision)


def test_после_выбора_пишутся_только_взятые_из_файла_строки(сеть: dict[str, str]) -> None:
    запрос = _запрос(_принятая("D2", "D1"))
    первая, вторая = запрос.rows

    итог = _применить(
        запрос,
        [_из_файла(первая.id, 11), _из_файла(вторая.id, 12)],
        take=frozenset({вторая.id}),
    )

    после = _запрос(запрос.inspection_id)
    assert итог.written == 1
    assert (после.rows[0].measure, после.rows[1].measure) == ("", "Из файла")


def test_выбор_по_ревизии_которой_уже_нет_снова_конфликт(сеть: dict[str, str]) -> None:
    запрос = _запрос(_принятая("D2"))
    строка = запрос.rows[0]
    итог = _применить(запрос, [_из_файла(строка.id, 11)])
    assert итог.written == 1

    снова = _применить(запрос, [_из_файла(строка.id, 11, measure="Ещё раз")])

    assert снова.conflict is True
    assert _запрос(запрос.inspection_id).rows[0].measure == "Из файла"


def test_срок_позже_положенного_не_ложится_а_текст_строки_ложится(сеть: dict[str, str]) -> None:
    запрос = _запрос(_принятая("D2"))
    строка = запрос.rows[0]

    итог = _применить(запрос, [_из_файла(строка.id, 11, due=строка.due_on + timedelta(days=1))])

    после = _запрос(запрос.inspection_id).rows[0]
    assert [(d.code, d.bound) for d in итог.reconciled.due_refused] == [
        (OWN_DUE_LATE, строка.due_on)
    ]
    assert (после.measure, после.own_due, после.due_on) == ("Из файла", None, строка.due_on)


def test_срок_раньше_положенного_ложится_как_с_экрана(сеть: dict[str, str]) -> None:
    запрос = _запрос(_принятая("D2"))
    строка = запрос.rows[0]
    раньше = max(строка.due_on - timedelta(days=2), СЕГОДНЯ)

    _применить(запрос, [_из_файла(строка.id, 11, due=раньше)])

    после = _запрос(запрос.inspection_id).rows[0]
    assert (после.own_due, после.due_on) == (раньше, раньше)


def test_срок_не_дата_отвергается_прежний_остаётся(сеть: dict[str, str]) -> None:
    запрос = _запрос(_принятая("D2"))
    строка = запрос.rows[0]

    итог = _применить(запрос, [_из_файла(строка.id, 11, due_unreadable=True)])

    assert [d.code for d in итог.reconciled.due_refused] == [DUE_NOT_DATE]
    assert _запрос(запрос.inspection_id).rows[0].own_due is None


def test_строка_чужого_плана_без_пары_и_в_этот_план_не_попадает(сеть: dict[str, str]) -> None:
    запрос = _запрос(_принятая("D2"))
    другой = _запрос(_принятая("D2"))

    итог = _применить(запрос, [_из_файла(другой.rows[0].id, 11)])

    assert [s.code for s in итог.reconciled.skipped] == [SKIP_UNKNOWN] and итог.written == 0
    assert _запрос(другой.inspection_id).rows[0].measure == ""


def test_партнёр_чужой_страны_файл_в_план_не_кладёт(сеть: dict[str, str]) -> None:
    запрос = _запрос(_принятая("D2"))

    with pytest.raises(ActionPlanError, match="Запроса нет"):
        _применить(запрос, [_из_файла(запрос.rows[0].id, 11)], reach=reach_of("AM"), tenant="AM")

    assert _запрос(запрос.inspection_id).rows[0].measure == ""


def test_уК_файл_за_партнёра_не_кладёт(сеть: dict[str, str]) -> None:
    запрос = _запрос(_принятая("D2"))

    with pytest.raises(ActionPlanError, match="партнёр"):
        _применить(запрос, [_из_файла(запрос.rows[0].id, 11)], reach=reach_of("HQ"), tenant="HQ")


def test_на_согласовании_файл_строки_не_правит(сеть: dict[str, str]) -> None:
    запрос = _на_согласовании("D2")

    with pytest.raises(ActionPlanError, match="согласование"):
        _применить(запрос, [_из_файла(запрос.rows[0].id, 11)])

    assert _запрос(запрос.inspection_id).rows[0].measure != "Из файла"


def test_версия_помнит_разобран_ли_файл(сеть: dict[str, str]) -> None:
    запрос = _запрос(_принятая("D2"))
    склад = _Склад()

    for разобран in (True, False):
        plans.upload_version(
            запрос.id,
            reach=reach_of("GE"),
            tenant="GE",
            actor=ГРУЗИЯ_АННА,
            file_name="план.xlsx",
            content_type="application/octet-stream",
            data=b"PK",
            max_bytes=1024,
            parsed=разобран,
            storage=склад,  # type: ignore[arg-type]
        )

    assert [f.parsed for f in _запрос(запрос.inspection_id).files] == [True, False]
