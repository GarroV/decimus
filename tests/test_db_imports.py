"""Загрузка исторических проверок через MCP (D305–D310) — ядро: оценка и права.

Числа здесь — ядро: загруженная проверка после подтверждения входит в историю
точки и аналитику наравне с обойдёнными (D306), и буква, посчитанная не по тем
записям или не по той версии, ушла бы туда как факт. Права — тоже ядро:
инструменты загрузки пишут в базу, и запись мимо загруженного черновика своего
пространства (обойдённая проверка, принятая, чужая) была бы правкой истории.

Инструменты вызываются так, как их зовёт сервер (`src.mcp.imports`), на
настоящей базе под ролью приложения и с настоящим движком.
"""

from __future__ import annotations

import base64
import io
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from conftest import TEST_DATA, requires_db
from db_harness import (
    set_retraction_env,
    привязать_страну,
    слить_проверку,
    точка_справочника,
)
from mcp_checklist_harness import build_edition

psycopg = pytest.importorskip("psycopg")

from src.db import action_plans as plans  # noqa: E402
from src.db.accept import accept_inspection  # noqa: E402
from src.db.queries import get_inspection, list_inspections  # noqa: E402
from src.db.reach import own_reach, reach_of  # noqa: E402
from src.mcp import imports  # noqa: E402
from src.mcp.checklist import Store, current_version  # noqa: E402
from src.mcp.errors import ToolError  # noqa: E402
from src.report.letters import sources  # noqa: E402
from src.report.rescore import rescore  # noqa: E402

pytestmark = requires_db

ТОЧКА = "Batumi-1"
ДЕНЬ = "2024-03-15"
КТО = "mcp:tg:4242"


class Склад:
    """Хранилище кадров в памяти: ключ → байты."""

    def __init__(self) -> None:
        self.объекты: dict[str, bytes] = {}

    def put(self, key: str, data: bytes, *, content_type: str) -> str:
        self.объекты[key] = data
        return f"s3://test/{key}"

    def delete(self, key: str) -> None:
        self.объекты.pop(key, None)


@pytest.fixture
def хранилище(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Store:
    """Хранилище версий с действующей методикой набора и старым изданием рядом (D307)."""
    корень = tmp_path / "store"
    monkeypatch.setenv("MCP_CHECKLIST_STORE", str(корень))
    склад = Store(root=корень, live=TEST_DATA)
    current_version(склад)  # заводит хранилище снимком действующей методики
    черновик = tmp_path / "old-edition"
    издание = build_edition(черновик, name="old", day="2023-01-01")
    черновик.rename(склад.home / "versions" / издание)
    return склад


@pytest.fixture
def сеть(pg_dsn: str, db_env: str, domain_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    точка_справочника(ТОЧКА, country="GE", city="Batumi")
    привязать_страну(pg_dsn, tenant="GE", country="GE")
    set_retraction_env(db_env, monkeypatch)


def _старое_издание(склад: Store) -> str:
    живое = current_version(склад)
    return next(p.name for p in (склад.home / "versions").iterdir() if p.name != живое)


def _черновик(склад: Store, *, tenant: str = "HQ", **поля: Any) -> str:
    аргументы: dict[str, Any] = {
        # Текущая (D334): этот набор — путь с движком. Историческая — в
        # `test_db_import_modes.py`.
        "mode": "current",
        "unit": ТОЧКА,
        "date": ДЕНЬ,
        "checklist_code": "bizdev",
        "auditor": "Ivan Petrov",
        "reported_pct": 98.0,
        "reported_grade": "B",
        "source_ref": "bitrix://reports/123",
        **поля,
    }
    ответ = imports.import_create_inspection(tenant=tenant, store=склад, actor=КТО, **аргументы)
    return str(ответ["id"])


def _добавить(склад: Store, ident: str, code: str, level: str, zone: str, **поля: Any) -> Any:
    return imports.import_add_finding(
        tenant="HQ",
        store=склад,
        actor=КТО,
        inspection_id=ident,
        code=code,
        level=level,
        zone=zone,
        text=поля.pop("text", "запись из старого отчёта"),
        **поля,
    )


def _записано(ident: str, tenant: str = "HQ") -> Any:
    detail = get_inspection(ident, reach=own_reach(tenant), include_on_review=True)
    assert detail is not None
    return detail


def _движок_согласен(ident: str) -> tuple[float, str]:
    """Записанная оценка = то, что движок считает по записанным записям её версии."""
    detail = _записано(ident)
    посчитано = rescore(detail, papers=sources())
    assert (detail.inspection.pct, detail.inspection.grade) == (посчитано.pct, посчитано.grade)
    assert detail.counts == dict(посчитано.counts)
    return detail.inspection.pct, detail.inspection.grade


# --- оценка: только движок, по версии проверки --------------------------------


def test_черновик_без_записей_посчитан_движком_по_действующей_версии(
    сеть: None, хранилище: Store
) -> None:
    # Act
    ident = _черновик(хранилище)

    # Assert
    строка = _записано(ident).inspection
    assert строка.on_review and строка.chat_id == 0
    assert строка.checklist_version == current_version(хранилище)
    assert _движок_согласен(ident) == (100.0, "A")


def test_добавление_правка_снятие_пересчитывают_оценку_движком(
    сеть: None, хранилище: Store
) -> None:
    # Arrange
    ident = _черновик(хранилище)

    # Act / Assert — D1 стоит 0,5; D2 — 2; повтор удваивает (D191).
    _добавить(хранилище, ident, "CLN03", "D1", "hot_kitchen")
    assert _движок_согласен(ident) == (99.5, "A")

    _добавить(хранилище, ident, "PRD02", "D2", "cold_kitchen", comment="переставить")
    assert _движок_согласен(ident) == (97.5, "B")

    imports.import_edit_finding(
        tenant="HQ", store=хранилище, actor=КТО, inspection_id=ident, n=1, repeat=True
    )
    assert _движок_согласен(ident) == (97.0, "B")

    ответ = imports.import_remove_finding(
        tenant="HQ", store=хранилище, actor=КТО, inspection_id=ident, n=2
    )
    assert _движок_согласен(ident) == (99.0, "A")
    assert [f["n"] for f in ответ["findings"]] == [1]
    запись = _записано(ident).findings[0]
    assert (запись.code, запись.level, запись.repeat) == ("CLN03", "D1", True)


def test_формулировка_и_комментарий_лежат_на_языке_слов_проверки(
    сеть: None, хранилище: Store
) -> None:
    # Arrange
    ident = _черновик(хранилище, text_lang="en")

    # Act
    _добавить(хранилище, ident, "CLN03", "D1", "hot_kitchen", text="streaks", comment="wash")
    imports.import_edit_finding(
        tenant="HQ", store=хранилище, actor=КТО, inspection_id=ident, n=1, comment=""
    )

    # Assert
    запись = _записано(ident).findings[0]
    assert (запись.lang, запись.text, запись.comment) == ("en", "streaks", None)


def test_текущая_не_заводится_по_старой_версии_даже_существующей(
    сеть: None, хранилище: Store
) -> None:
    """D334: в режиме current только действующая версия — старую выбрать нельзя."""
    # Arrange — старое издание в хранилище есть (D307).
    старое = _старое_издание(хранилище)

    # Act / Assert
    with pytest.raises(ToolError, match="выбрать версию нельзя"):
        _черновик(хранилище, checklist_version=старое)
    assert imports.import_list_drafts(tenant="HQ", store=хранилище, actor=КТО)["count"] == 0


def test_текущая_заводится_по_названной_действующей_версии(сеть: None, хранилище: Store) -> None:
    ident = _черновик(хранилище, checklist_version=current_version(хранилище))
    assert _записано(ident).inspection.checklist_version == current_version(хранилище)


def test_текущая_не_заводится_по_другому_чек_листу(сеть: None, хранилище: Store) -> None:
    with pytest.raises(ToolError, match="действующему эталону"):
        _черновик(хранилище, checklist_code="old-checklist")


def test_сверка_со_старым_отчётом_показывает_расхождение(сеть: None, хранилище: Store) -> None:
    # Arrange — в старом отчёте 98% B, а записана одна D1.
    ident = _черновик(хранилище)
    _добавить(хранилище, ident, "CLN03", "D1", "hot_kitchen")

    # Act
    вид = imports.import_get_inspection(
        tenant="HQ", store=хранилище, actor=КТО, inspection_id=ident
    )

    # Assert
    assert вид["matches_reported"] is False
    assert вид["pct_diff"] == 1.5
    _добавить(хранилище, ident, "PRD01", "D1", "fridge")
    _добавить(хранилище, ident, "CLN05", "D1", "hot_kitchen")
    _добавить(хранилище, ident, "PRD02", "D2", "cold_kitchen")
    вид = imports.import_get_inspection(
        tenant="HQ", store=хранилище, actor=КТО, inspection_id=ident
    )
    assert (вид["pct"], вид["grade"], вид["matches_reported"]) == (96.5, "B", False)


# --- отказы проверки записи и шапки ------------------------------------------


@pytest.mark.parametrize(
    ("code", "level", "zone", "причина"),
    [
        ("XXX99", "D1", "hot_kitchen", "XXX99"),
        ("CLN03", "D3", "hot_kitchen", "D3"),
        ("CLN03", "D1", "nowhere", "nowhere"),
    ],
)
def test_запись_вне_методики_версии_отклоняется_и_ничего_не_пишет(
    сеть: None, хранилище: Store, code: str, level: str, zone: str, причина: str
) -> None:
    # Arrange
    ident = _черновик(хранилище)

    # Act / Assert
    with pytest.raises(ToolError, match=причина):
        _добавить(хранилище, ident, code, level, zone)
    assert _записано(ident).findings == ()
    assert _движок_согласен(ident) == (100.0, "A")


def test_пара_пункт_плюс_зона_занята_второй_записью_не_берётся(
    сеть: None, хранилище: Store
) -> None:
    # Arrange
    ident = _черновик(хранилище)
    _добавить(хранилище, ident, "CLN03", "D1", "hot_kitchen")

    # Act / Assert
    with pytest.raises(ToolError, match="уже зафиксировано"):
        _добавить(хранилище, ident, "CLN03", "D1", "hot_kitchen", text="ещё раз")
    assert len(_записано(ident).findings) == 1
    assert _движок_согласен(ident) == (99.5, "A")


def test_зона_вне_списка_пункта_принимается_с_пометкой(сеть: None, хранилище: Store) -> None:
    # Arrange
    ident = _черновик(хранилище)

    # Act — CLN05 бывает только в hot_kitchen; человек назвал зал (D206).
    _добавить(хранилище, ident, "CLN05", "D1", "dining")

    # Assert
    assert _записано(ident).findings[0].zone_unusual is True


def test_дата_в_будущем_не_принимается(сеть: None, хранилище: Store) -> None:
    завтра = (date.today() + timedelta(days=1)).isoformat()
    with pytest.raises(ToolError, match="будущем"):
        _черновик(хранилище, date=завтра)


def test_неизвестная_версия_не_принимается(сеть: None, хранилище: Store) -> None:
    with pytest.raises(ToolError, match="выбрать версию нельзя"):
        _черновик(хранилище, checklist_version="bizdev-2020-01-01-000000000000")


def test_точка_вне_справочника_не_заводится(сеть: None, хранилище: Store) -> None:
    with pytest.raises(ToolError, match="справочнике"):
        _черновик(хранилище, unit="Nowhere-77")


# --- права: только загруженный черновик своего пространства -------------------


def test_чужое_пространство_черновика_не_видит_и_не_правит(сеть: None, хранилище: Store) -> None:
    # Arrange
    ident = _черновик(хранилище)

    # Act / Assert
    with pytest.raises(ToolError, match="нет"):
        imports.import_add_finding(
            tenant="GE",
            store=хранилище,
            actor=КТО,
            inspection_id=ident,
            code="CLN03",
            level="D1",
            zone="hot_kitchen",
            text="чужое",
        )
    assert _записано(ident).findings == ()


def test_проверку_обхода_инструменты_загрузки_не_трогают(сеть: None, хранилище: Store) -> None:
    # Arrange — ждущая приёмки проверка из бота.
    обход = слить_проверку(unit=ТОЧКА, tenant="HQ", accept=False)
    было = _записано(обход)

    # Act / Assert
    with pytest.raises(ToolError, match="обхода"):
        _добавить(хранилище, обход, "PRD01", "D1", "fridge")
    with pytest.raises(ToolError, match="обхода"):
        imports.import_discard_draft(
            tenant="HQ",
            store=хранилище,
            actor=КТО,
            inspection_id=обход,
            confirm_unit=ТОЧКА,
            confirm_date=было.inspection.inspection_date.isoformat(),
        )
    with pytest.raises(ToolError, match="обхода"):
        imports.import_accept_inspection(
            tenant="HQ",
            store=хранилище,
            actor=КТО,
            inspection_id=обход,
            confirm_unit=ТОЧКА,
            confirm_date=было.inspection.inspection_date.isoformat(),
        )
    with pytest.raises(ToolError, match="обхода"):
        imports.import_edit_finding(
            tenant="HQ", store=хранилище, actor=КТО, inspection_id=обход, n=1, level="D1"
        )
    with pytest.raises(ToolError, match="обхода"):
        imports.import_remove_finding(
            tenant="HQ", store=хранилище, actor=КТО, inspection_id=обход, n=1
        )
    assert _записано(обход).findings == было.findings


def test_кадр_к_проверке_обхода_не_прикладывается(
    сеть: None, хранилище: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    склад = Склад()
    monkeypatch.setattr(imports, "_photo_storage", lambda: склад)
    обход = слить_проверку(unit=ТОЧКА, tenant="HQ", accept=False)
    with pytest.raises(ToolError, match="обхода"):
        imports.import_add_photo(
            tenant="HQ",
            store=хранилище,
            actor=КТО,
            inspection_id=обход,
            n=1,
            image_base64=base64.b64encode(_png()).decode(),
            mime="image/png",
        )
    assert склад.объекты == {}


def test_правка_обхода_мимо_инструмента_тоже_отказ(сеть: None, db_env: str) -> None:
    """Заслон стоит в замке базы, а не только в обработчике MCP."""
    from src.db import imports as db

    обход = слить_проверку(unit=ТОЧКА, tenant="HQ", accept=False)

    def движок(_detail: Any) -> Any:
        raise AssertionError("до движка дойти не должно")

    with pytest.raises(db.HistoryImportError, match="обхода"):
        db.remove_finding(обход, 1, tenant="HQ", apply=движок)


def test_принятую_загрузку_не_правят_и_не_удаляют(сеть: None, хранилище: Store) -> None:
    # Arrange
    ident = _черновик(хранилище)
    _добавить(хранилище, ident, "CLN03", "D1", "hot_kitchen")
    imports.import_accept_inspection(
        tenant="HQ",
        store=хранилище,
        actor=КТО,
        inspection_id=ident,
        confirm_unit=ТОЧКА,
        confirm_date=ДЕНЬ,
    )

    # Act / Assert
    with pytest.raises(ToolError, match="подтверждена"):
        _добавить(хранилище, ident, "PRD01", "D1", "fridge")
    with pytest.raises(ToolError, match="подтверждена"):
        imports.import_discard_draft(
            tenant="HQ",
            store=хранилище,
            actor=КТО,
            inspection_id=ident,
            confirm_unit=ТОЧКА,
            confirm_date=ДЕНЬ,
        )
    assert len(_записано(ident).findings) == 1


def test_происхождение_не_переписывается(сеть: None, pg_dsn: str, db_env: str) -> None:
    """Обойдённую с D2 нельзя выдать за загруженную, чтобы уйти от запроса плана (D272)."""
    обход = слить_проверку(unit=ТОЧКА, tenant="HQ", accept=False)
    with psycopg.connect(db_env) as conn, pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("update inspections set origin = 'import' where id = %s", (обход,))


def test_загруженную_не_выдать_за_обход(сеть: None, хранилище: Store, db_env: str) -> None:
    """Обратный ход держит ТОЛЬКО триггер 0038: ограничение `chat_id = 0` его не ловит.

    Прямой ход (обход → загрузка) ловит ещё и `inspections_import_has_no_chat`,
    поэтому тест выше триггер в одиночку не проверяет — проверяет этот.
    """
    ident = _черновик(хранилище)
    with (
        psycopg.connect(db_env) as conn,
        pytest.raises(psycopg.errors.CheckViolation, match="происхождение"),
    ):
        conn.execute("update inspections set origin = 'field' where id = %s", (ident,))


# --- подтверждение: без запроса плана, с подписью ------------------------------


def _запрос(ident: str) -> Any:
    return plans.request_of_inspection(ident, reach=reach_of("HQ"))


def test_подтверждение_загрузки_с_d2_не_открывает_запрос_плана(
    сеть: None, хранилище: Store, pg_dsn: str
) -> None:
    # Arrange
    ident = _черновик(хранилище)
    _добавить(хранилище, ident, "PRD02", "D2", "cold_kitchen")

    # Act
    ответ = imports.import_accept_inspection(
        tenant="HQ",
        store=хранилище,
        actor=КТО,
        inspection_id=ident,
        confirm_unit=ТОЧКА,
        confirm_date=ДЕНЬ,
    )

    # Assert
    assert ответ["accepted_by"] == КТО
    assert _запрос(ident) is None
    with psycopg.connect(pg_dsn) as conn:
        строка = conn.execute(
            "select status, accepted_by, (select count(*) from action_plan_requests r "
            "where r.inspection_id = i.id) from inspections i where id = %s",
            (ident,),
        ).fetchone()
    assert строка == ("finalized", КТО, 0)


def test_подтверждение_обхода_с_d2_по_прежнему_открывает_запрос(сеть: None) -> None:
    from src.db.push import push_inspection
    from src.domain import add_finding, start_inspection

    # Arrange — проверка обхода с D2, как в test_db_action_plans.
    чат = 9_300_001
    start_inspection(чат, unit=ТОЧКА, kind="planned", report_lang="ru", tenant="HQ")
    add_finding(чат, code="PRD02", level="D2", zone="cold_kitchen", text="запись")
    ident = push_inspection(чат)

    # Act
    accept_inspection(ident, tenant="HQ", actor="garva")

    # Assert
    assert _запрос(ident) is not None


def test_принятая_загрузка_входит_в_историю_как_обычная(сеть: None, хранилище: Store) -> None:
    # Arrange
    ident = _черновик(хранилище)
    _добавить(хранилище, ident, "CLN03", "D1", "hot_kitchen")
    assert ident not in {r.id for r in list_inspections(reach=reach_of("HQ"))}

    # Act
    imports.import_accept_inspection(
        tenant="HQ",
        store=хранилище,
        actor=КТО,
        inspection_id=ident,
        confirm_unit=ТОЧКА.lower(),
        confirm_date=ДЕНЬ,
    )

    # Assert — обычное чтение истории (D306).
    история = {r.id: r for r in list_inspections(reach=reach_of("HQ"), unit=ТОЧКА)}
    assert (история[ident].pct, история[ident].grade) == (99.5, "A")


def test_несошедшееся_подтверждение_ничего_не_принимает(сеть: None, хранилище: Store) -> None:
    # Arrange
    ident = _черновик(хранилище)

    # Act / Assert
    with pytest.raises(ToolError, match="не сошлось"):
        imports.import_accept_inspection(
            tenant="HQ",
            store=хранилище,
            actor=КТО,
            inspection_id=ident,
            confirm_unit=ТОЧКА,
            confirm_date="2024-03-16",
        )
    with pytest.raises(ToolError, match="не сошлось"):
        imports.import_accept_inspection(
            tenant="HQ",
            store=хранилище,
            actor=КТО,
            inspection_id=ident,
            confirm_unit="Batumi-2",
            confirm_date=ДЕНЬ,
        )
    assert _записано(ident).inspection.on_review


# --- удаление черновика и кадры ---------------------------------------------


def _png() -> bytes:
    from PIL import Image

    буфер = io.BytesIO()
    Image.new("RGB", (32, 24), (200, 30, 30)).save(буфер, format="PNG")
    return буфер.getvalue()


def test_кадр_ложится_в_хранилище_и_уходит_со_снятой_записью(
    сеть: None, хранилище: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    склад = Склад()
    monkeypatch.setattr(imports, "_photo_storage", lambda: склад)
    ident = _черновик(хранилище)
    _добавить(хранилище, ident, "CLN03", "D1", "hot_kitchen")
    кадр = base64.b64encode(_png()).decode()

    # Act
    imports.import_add_photo(
        tenant="HQ",
        store=хранилище,
        actor=КТО,
        inspection_id=ident,
        n=1,
        image_base64=кадр,
        mime="image/png",
    )

    # Assert
    assert len(склад.объекты) == 1
    with pytest.raises(ToolError, match="уже приложен"):
        imports.import_add_photo(
            tenant="HQ",
            store=хранилище,
            actor=КТО,
            inspection_id=ident,
            n=1,
            image_base64=кадр,
            mime="image/png",
        )
    imports.import_remove_finding(tenant="HQ", store=хранилище, actor=КТО, inspection_id=ident, n=1)
    assert склад.объекты == {}


def test_большой_кадр_отклоняется_до_хранилища(
    сеть: None, хранилище: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    склад = Склад()
    monkeypatch.setattr(imports, "_photo_storage", lambda: склад)
    ident = _черновик(хранилище)
    _добавить(хранилище, ident, "CLN03", "D1", "hot_kitchen")
    with pytest.raises(ToolError, match="КБ"):
        imports.import_add_photo(
            tenant="HQ",
            store=хранилище,
            actor=КТО,
            inspection_id=ident,
            n=1,
            image_base64=base64.b64encode(b"\xff" * (imports.MAX_PHOTO_BYTES + 1)).decode(),
            mime="image/jpeg",
        )
    assert склад.объекты == {}


def test_удаление_черновика_убирает_его_целиком(
    сеть: None, хранилище: Store, pg_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    склад = Склад()
    monkeypatch.setattr(imports, "_photo_storage", lambda: склад)
    ident = _черновик(хранилище)
    _добавить(хранилище, ident, "CLN03", "D1", "hot_kitchen")
    imports.import_add_photo(
        tenant="HQ",
        store=хранилище,
        actor=КТО,
        inspection_id=ident,
        n=1,
        image_base64=base64.b64encode(_png()).decode(),
        mime="image/png",
    )

    # Act
    imports.import_discard_draft(
        tenant="HQ",
        store=хранилище,
        actor=КТО,
        inspection_id=ident,
        confirm_unit=ТОЧКА,
        confirm_date=ДЕНЬ,
    )

    # Assert
    with psycopg.connect(pg_dsn) as conn:
        осталось = conn.execute(
            "select (select count(*) from inspections where id = %(id)s),"
            " (select count(*) from translations where entity_id = %(id)s)",
            {"id": ident},
        ).fetchone()
        переводов = conn.execute(
            "select count(*) from translations t where t.entity_type = 'finding'"
            " and not exists (select 1 from findings f where f.id = t.entity_id)"
        ).fetchone()
    assert осталось == (0, 0)
    assert переводов == (0,)
    assert склад.объекты == {}
    assert imports.import_list_drafts(tenant="HQ", store=хранилище, actor=КТО)["count"] == 0
