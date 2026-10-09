# ruff: noqa: F811 — фикстуры набора загрузки приходят импортом (как в test_db_imports_limits)
"""Два режима загрузки (D332, D334) — ядро: оценка исторической и границы режимов.

Числа здесь — ядро. Историческая (`history`, `origin = 'legacy'`) хранит оценку
старого отчёта как есть: `pct = reported_pct`, и движок не зовётся НИ на одном
пути — ни при создании, ни на записях, ни на подтверждении, ни на правке на
приёмке, ни при сверке письма. Пересчитанная задним числом, она ушла бы в
историю точки чужой буквой под прежней датой.

Права — тоже ядро: режим задаётся при создании и не меняется; путь с движком не
трогает историческую, путь исторической не трогает текущую; подтверждение
обеих не открывает запрос экшн-плана (D310).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest
from conftest import requires_db
from db_harness import set_retraction_env

psycopg = pytest.importorskip("psycopg")

from test_db_imports import (  # noqa: E402, F401 — фикстуры набора загрузки
    ДЕНЬ,
    КТО,
    ТОЧКА,
    _записано,
    _черновик,
    сеть,
    хранилище,
)

from src.db import action_plans as plans  # noqa: E402
from src.db import imports as db  # noqa: E402
from src.db import imports_legacy as legacy  # noqa: E402
from src.db import revise  # noqa: E402
from src.db.errors import ActionPlanError, HistoryImportError, ReviseError  # noqa: E402
from src.db.queries import (  # noqa: E402
    item_usage,
    list_inspections,
    slice_summary,
    systemic_findings,
)
from src.db.reach import reach_of  # noqa: E402
from src.mcp import imports  # noqa: E402
from src.mcp.checklist import Store  # noqa: E402
from src.mcp.errors import ToolError  # noqa: E402
from src.report import letters, rescore  # noqa: E402
from src.report.letters import LetterError, sources  # noqa: E402

pytestmark = [requires_db, pytest.mark.usefixtures("сеть")]


def _историческая(склад: Store, **поля: Any) -> str:
    аргументы: dict[str, Any] = {
        "mode": "history",
        "unit": ТОЧКА,
        "date": ДЕНЬ,
        "reported_pct": 95.29,
        "reported_status": "Issues (D2)",
        "legacy_method": "Qvalon 133",
        "source_ref": "qvalon.pdf",
        **поля,
    }
    ответ = imports.import_create_inspection(tenant="HQ", store=склад, actor=КТО, **аргументы)
    return str(ответ["id"])


def _запись(склад: Store, ident: str, **поля: Any) -> dict[str, Any]:
    return imports.import_add_finding(
        tenant="HQ",
        store=склад,
        actor=КТО,
        inspection_id=ident,
        text=поля.pop("text", "запись из старого отчёта"),
        **поля,
    )


@pytest.fixture
def движок_запрещён(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Любой вход в движок — падение теста с именем входа.

    Подменяется сам запуск подпроцесса (`letters._run`) — через него идут и
    пересчёт, и команды записей, и сверка письма, — и оба входа пересчёта.
    """
    позвали: list[str] = []

    def запрет(имя: str) -> Any:
        def _(*_a: Any, **_k: Any) -> Any:
            позвали.append(имя)
            raise AssertionError(f"движок позван для исторической: {имя}")

        return _

    monkeypatch.setattr(letters, "_run", запрет("letters._run"))
    monkeypatch.setattr(rescore.letters, "_run", запрет("rescore.letters._run"))
    monkeypatch.setattr(imports, "_rescorer", запрет("imports._rescorer"))
    monkeypatch.setattr(imports, "_engine", запрет("imports._engine"))
    return позвали


# --- историческая: оценка как есть, движок не зовётся -------------------------


def test_историческая_хранит_оценку_отчёта_и_движок_не_зовётся_ни_на_одном_пути(
    хранилище: Store, движок_запрещён: list[str]
) -> None:
    # Arrange / Act — весь путь коллеги: создать, записи, правка, снятие, чтение,
    # подтверждение.
    ident = _историческая(хранилище, reported_grade="b")
    _запись(хранилище, ident, code="CLN03", level="D2", zone="hot_kitchen")
    _запись(хранилище, ident, text="грязный пол, без пункта и класса")
    _запись(хранилище, ident, code="xyz77", level="D3")
    imports.import_edit_finding(
        tenant="HQ", store=хранилище, actor=КТО, inspection_id=ident, n=2, level="D1"
    )
    imports.import_remove_finding(tenant="HQ", store=хранилище, actor=КТО, inspection_id=ident, n=3)
    вид = imports.import_get_inspection(
        tenant="HQ", store=хранилище, actor=КТО, inspection_id=ident
    )
    imports.import_accept_inspection(
        tenant="HQ",
        store=хранилище,
        actor=КТО,
        inspection_id=ident,
        confirm_unit=ТОЧКА,
        confirm_date=ДЕНЬ,
    )

    # Assert — оценка ровно из отчёта, разбивки нет, счёт записей — по классам.
    detail = _записано(ident)
    строка = detail.inspection
    assert движок_запрещён == []
    assert (строка.origin, строка.pct, строка.grade) == ("legacy", 95.29, "B")
    assert (detail.deductions, detail.by_zone) == (0.0, {})
    assert detail.counts == {"D1": 1, "D2": 1}
    assert строка.checklist_code == "bizdev"
    assert строка.checklist_version == "legacy:Qvalon 133"
    assert (detail.reported_status, detail.legacy_method) == ("Issues (D2)", "Qvalon 133")
    assert вид["mode"] == "history" and вид["pct"] == 95.29
    без_пункта = next(f for f in detail.findings if f.n == 2)
    assert (без_пункта.code, без_пункта.level, без_пункта.zone) == ("LEGACY", "D1", "")


def test_историческая_без_буквы_хранит_пустую_и_видна_в_истории_точки(
    хранилище: Store, движок_запрещён: list[str]
) -> None:
    # Arrange
    ident = _историческая(хранилище, reported_status=None, legacy_method=None)
    _запись(хранилище, ident, text="без класса")

    # Act
    imports.import_accept_inspection(
        tenant="HQ",
        store=хранилище,
        actor=КТО,
        inspection_id=ident,
        confirm_unit=ТОЧКА,
        confirm_date=ДЕНЬ,
    )

    # Assert — в истории точки рядом с обходами (D306), буква пустая, «без класса».
    история = {r.id: r for r in list_inspections(reach=reach_of("HQ"), unit=ТОЧКА)}
    assert (история[ident].pct, история[ident].grade) == (95.29, "")
    assert история[ident].checklist_version == "legacy:unlabelled"
    assert _записано(ident).counts == {"NC": 1}


def test_записи_исторической_не_в_статистике_пунктов_а_оценка_в_средней(
    хранилище: Store,
) -> None:
    """Код пункта старой методики значит другое, чем в нынешнем чек-листе.

    Поэтому записи исторической не идут ни в «системные нарушения сети», ни в
    статистику пункта на экране методики. Оценка же её — истина (D352) и в
    сводке среза остаётся.
    """
    # Arrange — историческая с записью под кодом, который есть и в нынешнем.
    ident = _историческая(хранилище)
    _запись(хранилище, ident, code="CLN03", level="D3", zone="hot_kitchen")
    imports.import_accept_inspection(
        tenant="HQ",
        store=хранилище,
        actor=КТО,
        inspection_id=ident,
        confirm_unit=ТОЧКА,
        confirm_date=ДЕНЬ,
    )
    охват = reach_of("HQ")
    чек_лист = _записано(ident).inspection.checklist_code

    # Act
    системные = systemic_findings(reach=охват)
    пункт = item_usage(reach=охват, code="CLN03", checklist=чек_лист)
    точек, сводка = slice_summary(reach=охват)

    # Assert
    assert "CLN03" not in {код for код, *_ in системные}
    assert (пункт.records, пункт.inspections) == (0, 0)
    assert точек == 1
    assert sum(n for _буква, n, _сумма in сводка) == 1
    assert sum(сумма for _буква, _n, сумма in сводка) == 95.29


def test_незнакомый_код_исторической_предупреждение_а_не_отказ(хранилище: Store) -> None:
    ident = _историческая(хранилище)
    ответ = _запись(хранилище, ident, code="ZZZ999", text="пункт старого чек-листа")
    assert any("ZZZ999" in w for w in ответ["warnings"])
    assert _записано(ident).findings[0].code == "ZZZ999"


def test_подтверждение_исторической_с_d3_не_открывает_запрос_плана(
    хранилище: Store, pg_dsn: str
) -> None:
    # Arrange
    ident = _историческая(хранилище)
    _запись(хранилище, ident, code="CLN03", level="D3", zone="hot_kitchen")

    # Act
    imports.import_accept_inspection(
        tenant="HQ",
        store=хранилище,
        actor=КТО,
        inspection_id=ident,
        confirm_unit=ТОЧКА,
        confirm_date=ДЕНЬ,
    )

    # Assert
    with psycopg.connect(pg_dsn) as conn:
        запросов = conn.execute(
            "select count(*) from action_plan_requests where inspection_id = %s", (ident,)
        ).fetchone()
    assert запросов == (0,)


@pytest.mark.parametrize("режим", ["history", "current"])
def test_по_загруженной_план_руками_не_запрашивают(
    хранилище: Store, db_env: str, monkeypatch: pytest.MonkeyPatch, режим: str
) -> None:
    """D310: кнопка «Запросить план» (POST `/request`) по загруженной — отказ словами.

    Автозапрос при подтверждении закрыт `accept.py`; ручной запрос шёл мимо
    него и до правки заводил план по загруженной проверке.
    """
    # Arrange — принятая загруженная проверка УК.
    set_retraction_env(db_env, monkeypatch)
    ident = _историческая(хранилище) if режим == "history" else _черновик(хранилище)
    imports.import_accept_inspection(
        tenant="HQ",
        store=хранилище,
        actor=КТО,
        inspection_id=ident,
        confirm_unit=ТОЧКА,
        confirm_date=ДЕНЬ,
    )

    # Act / Assert
    with pytest.raises(ActionPlanError, match="загружена задним числом"):
        plans.request_plan(ident, actor="hq", due_on=date.today() + timedelta(days=3))
    assert plans.request_of_inspection(ident, reach=reach_of("HQ")) is None


def test_правка_на_приёмке_исторической_отказ_до_движка(хранилище: Store) -> None:
    # Arrange
    ident = _историческая(хранилище)
    _запись(хранилище, ident, code="CLN03", level="D1", zone="hot_kitchen")
    запись = _записано(ident).findings[0]

    def движок(_detail: Any) -> Any:
        raise AssertionError("до движка дойти не должно")

    # Act / Assert
    with pytest.raises(ReviseError, match="историческая"):
        revise.revise_finding(
            ident,
            запись.id,
            tenant="HQ",
            revision=revise.Revision(
                code="CLN03", level="D2", zone="hot_kitchen", zone_unusual=False, text="x"
            ),
            score_of=движок,
        )
    assert _записано(ident).inspection.pct == 95.29


def test_пересчёт_и_письмо_исторической_отказывают_словами(хранилище: Store) -> None:
    ident = _историческая(хранилище)
    detail = _записано(ident)
    with pytest.raises(LetterError, match="историческая"):
        rescore.rescore(detail, papers=sources())
    with pytest.raises(LetterError, match="историческая"):
        rescore.apply_command(detail, papers=sources(), args=["drop", "1"])
    with pytest.raises(LetterError, match="письма партнёру"):
        letters.build(detail, lang=None, papers=sources())


# --- границы режимов ---------------------------------------------------------


def test_путь_с_движком_не_трогает_историческую(хранилище: Store) -> None:
    """Заслон в замке базы: `apply` на исторической не зовётся вовсе."""
    ident = _историческая(хранилище)
    _запись(хранилище, ident, code="CLN03", level="D1", zone="hot_kitchen")

    def движок(_detail: Any) -> Any:
        raise AssertionError("до движка дойти не должно")

    with pytest.raises(HistoryImportError, match="историческая"):
        db.add_finding(ident, tenant="HQ", wording=db.Wording("x", None), apply=движок)
    with pytest.raises(HistoryImportError, match="историческая"):
        db.edit_finding(ident, 1, tenant="HQ", wording=db.Wording("x", None), apply=движок)
    with pytest.raises(HistoryImportError, match="историческая"):
        db.remove_finding(ident, 1, tenant="HQ", apply=движок)
    assert _записано(ident).inspection.pct == 95.29


def test_путь_исторической_не_трогает_текущую(хранилище: Store) -> None:
    ident = _черновик(хранилище)
    запись = legacy.LegacyFinding(code=None, level=None, zone=None)
    with pytest.raises(HistoryImportError, match="текущая"):
        legacy.add_legacy_finding(ident, tenant="HQ", finding=запись, wording=db.Wording("x", None))
    assert _записано(ident).findings == ()


def test_историческую_слой_базы_движком_не_заводит() -> None:
    def посчитать(_detail: Any) -> Any:
        raise AssertionError("до движка дойти не должно")

    шапка = db.NewDraft(
        tenant="HQ",
        unit=ТОЧКА,
        inspection_date=date(2024, 3, 15),
        kind="planned",
        checklist_code="bizdev",
        checklist_version="legacy:x",
        auditor="",
        report_lang="ru",
        speech_lang="ru",
        origin="legacy",
        reported_pct=90.0,
    )
    with pytest.raises(HistoryImportError, match="не считает"):
        db.create_draft(шапка, apply_score=посчитать)


@pytest.mark.parametrize(
    ("поля", "причина"),
    [
        ({"mode": None}, "mode"),
        ({"mode": "old"}, "mode"),
        ({"reported_pct": None}, "обязательна"),
        ({"checklist_version": "bizdev-2023"}, "history"),
        ({"checklist_code": "bizdev"}, "history"),
    ],
)
def test_режим_и_обязательные_поля_исторической(
    хранилище: Store, поля: dict[str, Any], причина: str
) -> None:
    with pytest.raises(ToolError, match=причина):
        _историческая(хранилище, **поля)


def test_у_текущей_нет_статуса_старого_отчёта(хранилище: Store) -> None:
    with pytest.raises(ToolError, match="только для режима history"):
        _черновик(хранилище, reported_status="Passed")


def test_текущей_записи_код_класс_и_зона_обязательны(хранилище: Store) -> None:
    ident = _черновик(хранилище)
    with pytest.raises(ToolError, match="обязательны code, level и zone"):
        _запись(хранилище, ident, code="CLN03")


@pytest.mark.parametrize(
    ("было", "стало"),
    [("legacy", "import"), ("legacy", "field"), ("import", "legacy")],
)
def test_режим_не_меняется(хранилище: Store, db_env: str, было: str, стало: str) -> None:
    ident = _историческая(хранилище) if было == "legacy" else _черновик(хранилище)
    with (
        psycopg.connect(db_env) as conn,
        pytest.raises(psycopg.errors.CheckViolation, match="происхождение"),
    ):
        conn.execute("update inspections set origin = %s where id = %s", (стало, ident))


def test_база_не_даёт_исторической_оценку_не_из_отчёта(хранилище: Store, db_env: str) -> None:
    """Третий заслон (0042): даже мимо кода оценку исторической не переписать."""
    ident = _историческая(хранилище)
    with (
        psycopg.connect(db_env) as conn,
        pytest.raises(psycopg.errors.CheckViolation, match="legacy_score_as_is"),
    ):
        conn.execute("update inspections set pct = 99.5 where id = %s", (ident,))
