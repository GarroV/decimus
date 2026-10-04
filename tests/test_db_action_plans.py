"""Экшн-планы в базе: автозапрос, заслоны ролей и стран, история (D272, D274, урок #490).

Проверяется то, что держит БАЗА и двери блока `db`, а не экран: роль
приложения (бот, партнёр в вебе) не заводит запрос, не выносит вердикт и не
переводит план в «принят» ни вставкой, ни правкой; партнёр чужой страны не
видит, не загружает и не скачивает; угаданный id запроса или файла отвечает
тем же «нет», что несуществующий.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from conftest import requires_db
from db_harness import admin_role_dsn, set_retraction_env, привязать_страну, точка_справочника

psycopg = pytest.importorskip("psycopg")

from src.db import action_plans as plans  # noqa: E402
from src.db.accept import accept_inspection  # noqa: E402
from src.db.errors import ActionPlanError  # noqa: E402
from src.db.reach import reach_of  # noqa: E402

pytestmark = requires_db

ТОЧКА = "Batumi-1"
ЧУЖАЯ_ТОЧКА = "Yerevan-1"
СЕГОДНЯ = datetime.now(UTC).date()
МБ = 1024 * 1024
_чаты = iter(range(9_100_000, 9_200_000))


class Хранилище:
    """Хранилище в памяти: ключ → байты."""

    def __init__(self) -> None:
        self.объекты: dict[str, bytes] = {}

    def put(self, key: str, data: bytes, *, content_type: str) -> str:
        self.объекты[key] = data
        return f"s3://test/{key}"

    def get(self, key: str) -> bytes:
        return self.объекты[key]

    def delete(self, key: str) -> None:
        self.объекты.pop(key, None)


@pytest.fixture
def admin_env(db_env: str, monkeypatch: pytest.MonkeyPatch) -> str:
    return set_retraction_env(db_env, monkeypatch)


@pytest.fixture
def сеть(pg_dsn: str, db_env: str, domain_env: Path, admin_env: str) -> None:
    """Batumi-1 в Грузии (партнёр GE), Yerevan-1 в Армении (партнёр AM)."""
    точка_справочника(ТОЧКА, country="GE", city="Batumi")
    точка_справочника(ЧУЖАЯ_ТОЧКА, country="AM", city="Yerevan")
    привязать_страну(pg_dsn, tenant="GE", country="GE")
    привязать_страну(pg_dsn, tenant="AM", country="AM")


@pytest.fixture
def склад() -> Хранилище:
    return Хранилище()


def _проверка(*уровни: str, unit: str = ТОЧКА, tenant: str = "HQ") -> str:
    """Слитая и ждущая приёмки проверка с записями названных классов."""
    from src.db.push import push_inspection
    from src.domain import add_finding, start_inspection

    чат = next(_чаты)
    start_inspection(чат, unit=unit, kind="planned", report_lang="ru", tenant=tenant)
    коды = {"D1": "PRD01", "D2": "PRD02", "D3": "PRD04"}
    зоны = {"D1": "fridge", "D2": "cold_kitchen", "D3": "dry_storage"}
    for уровень in уровни:
        add_finding(чат, code=коды[уровень], level=уровень, zone=зоны[уровень], text="запись")
    return push_inspection(чат)


def _принятая(*уровни: str, unit: str = ТОЧКА, tenant: str = "HQ") -> str:
    ident = _проверка(*уровни, unit=unit, tenant=tenant)
    accept_inspection(ident, tenant=tenant, actor="garva")
    return ident


def _запрос(ident: str) -> plans.PlanRequest:
    найден = plans.request_of_inspection(ident, reach=reach_of("HQ"))
    assert найден is not None, "запроса по проверке нет"
    return найден


def _загрузить(
    склад: Хранилище, request_id: str, *, tenant: str = "GE", data: bytes = b"%PDF plan"
) -> int:
    return plans.upload_version(
        request_id,
        reach=reach_of(tenant),
        tenant=tenant,
        actor=f"partner-{tenant.lower()}",
        file_name="план.pdf",
        content_type="application/pdf",
        data=data,
        max_bytes=25 * МБ,
        storage=склад,
    )


def _sql(dsn: str, текст: str, параметры: tuple[Any, ...] = ()) -> None:
    with psycopg.connect(dsn) as conn:
        conn.execute(текст, параметры)
        conn.commit()


# --- автозапрос при подтверждении (D272, D274) -------------------------------


def test_подтверждение_с_d2_само_заводит_запрос_на_семь_дней(сеть: None) -> None:
    # Act
    ident = _принятая("D1", "D2")

    # Assert
    запрос = _запрос(ident)
    assert (запрос.country, запрос.status, запрос.origin) == ("GE", "requested", "auto")
    assert запрос.due_on == СЕГОДНЯ + timedelta(days=7)
    assert запрос.requested_by == "garva"
    assert [(e.action, e.actor) for e in запрос.events] == [("requested", "garva")]


def test_подтверждение_с_d3_заводит_запрос(сеть: None) -> None:
    assert _запрос(_принятая("D3")).status == "requested"


def test_срок_по_умолчанию_берётся_из_настройки(
    сеть: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ACTION_PLAN_DUE_DAYS", "10")
    assert _запрос(_принятая("D2")).due_on == СЕГОДНЯ + timedelta(days=10)


def test_подтверждение_без_d2_d3_запроса_не_заводит(сеть: None) -> None:
    ident = _принятая("D1")
    assert plans.request_of_inspection(ident, reach=reach_of("HQ")) is None


def test_своя_проверка_партнёра_запроса_не_заводит(сеть: None) -> None:
    """Экшн-план — ответ партнёра на проверку УК (D289)."""
    ident = _принятая("D2", tenant="GE")
    assert plans.request_of_inspection(ident, reach=reach_of("HQ")) is None


# --- заслоны базы: роль приложения не выносит вердикт (урок #490) -------------


def test_роль_приложения_не_заводит_запрос(сеть: None, db_env: str) -> None:
    ident = _принятая("D1")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        _sql(
            db_env,
            "insert into action_plan_requests (inspection_id, country, due_on, origin,"
            " requested_by, due_set_by) values (%s, 'GE', current_date, 'manual', 'bot', 'bot')",
            (ident,),
        )


def test_принятым_запрос_не_вставляет_никто(сеть: None, admin_env: str) -> None:
    ident = _принятая("D1")
    with pytest.raises(psycopg.errors.InsufficientPrivilege, match="только запрошенным"):
        _sql(
            admin_env,
            "insert into action_plan_requests (inspection_id, country, due_on, status, origin,"
            " requested_by, due_set_by) values (%s, 'GE', current_date, 'accepted', 'manual',"
            " 'hq', 'hq')",
            (ident,),
        )


def test_роль_приложения_не_выносит_вердикт(сеть: None, склад: Хранилище, db_env: str) -> None:
    запрос = _запрос(_принятая("D2"))
    _загрузить(склад, запрос.id)
    файл = _запрос(запрос.inspection_id).files[-1].id
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        _sql(
            db_env,
            "insert into action_plan_reviews (file_id, verdict, reviewed_by)"
            " values (%s, 'accepted', 'bot')",
            (файл,),
        )


def test_роль_приложения_не_переводит_в_принят(сеть: None, склад: Хранилище, db_env: str) -> None:
    запрос = _запрос(_принятая("D2"))
    _загрузить(склад, запрос.id)
    with pytest.raises(psycopg.errors.InsufficientPrivilege, match="только УК"):
        _sql(
            db_env,
            "update action_plan_requests set status = 'accepted' where id = %s",
            (запрос.id,),
        )
    assert _запрос(запрос.inspection_id).status == "on_review"


def test_роль_приложения_не_правит_срок(сеть: None, db_env: str) -> None:
    запрос = _запрос(_принятая("D2"))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        _sql(
            db_env,
            "update action_plan_requests set due_on = due_on + 30 where id = %s",
            (запрос.id,),
        )


def test_принятым_без_вердикта_не_делает_и_уК(сеть: None, склад: Хранилище, admin_env: str) -> None:
    запрос = _запрос(_принятая("D2"))
    _загрузить(склад, запрос.id)
    with pytest.raises(psycopg.errors.CheckViolation, match="нет вердикта"):
        _sql(
            admin_env,
            "update action_plan_requests set status = 'accepted' where id = %s",
            (запрос.id,),
        )


def test_историю_не_пишет_напрямую_никто(сеть: None, db_env: str, admin_env: str) -> None:
    запрос = _запрос(_принятая("D2"))
    for dsn in (db_env, admin_env):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            _sql(
                dsn,
                "insert into action_plan_events (request_id, action, actor)"
                " values (%s, 'accepted', 'подлог')",
                (запрос.id,),
            )


def test_чужое_пространство_версию_не_кладёт_даже_мимо_двери(сеть: None, db_env: str) -> None:
    """Триггер держит страну и без кода веба: AM не кладёт файл в запрос Грузии."""
    запрос = _запрос(_принятая("D2"))
    with pytest.raises(psycopg.errors.InsufficientPrivilege, match="не отвечает за страну"):
        _sql(
            db_env,
            "insert into action_plan_files (id, request_id, version, storage_path, file_name,"
            " size_bytes, content_type, uploaded_by, uploaded_tenant) values"
            " (gen_random_uuid(), %s, 1, 's3://x/y', 'p.pdf', 3, 'application/pdf', 'am', 'AM')",
            (запрос.id,),
        )


# --- путь из критерия приёмки --------------------------------------------------


def test_запрос_загрузка_возврат_вторая_версия_приём(сеть: None, склад: Хранилище) -> None:
    # Arrange
    запрос = _запрос(_принятая("D2"))

    # Act
    assert _загрузить(склад, запрос.id, data=b"v1") == 1
    plans.review(запрос.id, actor="hq-lead", verdict="returned", comment="нет сроков")
    после_возврата = _запрос(запрос.inspection_id)
    assert _загрузить(склад, запрос.id, data=b"v2") == 2
    plans.review(запрос.id, actor="hq-lead", verdict="accepted", comment="")

    # Assert
    итог = _запрос(запрос.inspection_id)
    assert после_возврата.state == plans.STATE_RETURNED
    assert итог.state == plans.STATE_ACCEPTED
    assert [(f.version, f.verdict, f.comment) for f in итог.files] == [
        (1, "returned", "нет сроков"),
        (2, "accepted", None),
    ]
    assert [(e.action, e.actor) for e in итог.events] == [
        ("requested", "garva"),
        ("uploaded", "partner-ge"),
        ("returned", "hq-lead"),
        ("uploaded", "partner-ge"),
        ("accepted", "hq-lead"),
    ]
    assert sorted(склад.объекты.values()) == [b"v1", b"v2"]
    assert all(ключ.startswith("action-plans/") for ключ in склад.объекты)


def test_возврат_без_комментария_это_отказ(сеть: None, склад: Хранилище) -> None:
    запрос = _запрос(_принятая("D2"))
    _загрузить(склад, запрос.id)
    with pytest.raises(ActionPlanError, match="комментар"):
        plans.review(запрос.id, actor="hq", verdict="returned", comment="  ")
    assert _запрос(запрос.inspection_id).status == "on_review"


def test_пока_план_на_приёмке_новую_версию_не_кладут(сеть: None, склад: Хранилище) -> None:
    запрос = _запрос(_принятая("D2"))
    _загрузить(склад, запрос.id)
    with pytest.raises(ActionPlanError):
        _загрузить(склад, запрос.id)


def test_принятый_план_не_меняется(сеть: None, склад: Хранилище) -> None:
    запрос = _запрос(_принятая("D2"))
    _загрузить(склад, запрос.id)
    plans.review(запрос.id, actor="hq", verdict="accepted", comment="")
    with pytest.raises(ActionPlanError):
        _загрузить(склад, запрос.id)
    with pytest.raises(ActionPlanError):
        plans.set_due(запрос.id, actor="hq", due_on=СЕГОДНЯ + timedelta(days=30))
    with pytest.raises(ActionPlanError):
        plans.review(запрос.id, actor="hq", verdict="returned", comment="ещё")


def test_вердикт_без_версии_это_отказ(сеть: None) -> None:
    запрос = _запрос(_принятая("D2"))
    with pytest.raises(ActionPlanError):
        plans.review(запрос.id, actor="hq", verdict="accepted", comment="")


@pytest.mark.parametrize("размер", [0, 25 * МБ + 1])
def test_пустой_и_больше_предела_файл_не_принимается(
    сеть: None, склад: Хранилище, размер: int
) -> None:
    запрос = _запрос(_принятая("D2"))
    with pytest.raises(ActionPlanError):
        _загрузить(склад, запрос.id, data=b"x" * размер)
    assert склад.объекты == {}


# --- охват: чужая страна и IDOR ----------------------------------------------


def test_партнёр_видит_только_запросы_своих_стран(сеть: None) -> None:
    # Arrange
    грузия = _запрос(_принятая("D2"))
    армения = _запрос(_принятая("D2", unit=ЧУЖАЯ_ТОЧКА))

    # Act
    у_ge = {r.id for r in plans.list_requests(reach=reach_of("GE"))}
    у_am = {r.id for r in plans.list_requests(reach=reach_of("AM"))}
    у_уК = {r.id for r in plans.list_requests(reach=reach_of("HQ"))}

    # Assert
    assert (у_ge, у_am, у_уК) == ({грузия.id}, {армения.id}, {грузия.id, армения.id})


def test_чужой_запрос_по_id_неотличим_от_несуществующего(сеть: None) -> None:
    запрос = _запрос(_принятая("D2"))
    assert plans.get_request(запрос.id, reach=reach_of("AM")) is None
    assert plans.get_request(запрос.id, reach=reach_of("GE")) is not None
    assert plans.get_request("00000000-0000-0000-0000-000000000000", reach=reach_of("GE")) is None


def test_партнёр_чужой_страны_не_загружает(сеть: None, склад: Хранилище) -> None:
    запрос = _запрос(_принятая("D2"))
    with pytest.raises(ActionPlanError, match="нет"):
        _загрузить(склад, запрос.id, tenant="AM")
    assert склад.объекты == {}
    assert _запрос(запрос.inspection_id).status == "requested"


def test_уК_версию_за_партнёра_не_кладёт(сеть: None, склад: Хранилище) -> None:
    запрос = _запрос(_принятая("D2"))
    with pytest.raises(ActionPlanError):
        _загрузить(склад, запрос.id, tenant="HQ")
    assert _запрос(запрос.inspection_id).files == ()


def test_файл_скачивают_своя_страна_и_уК_а_чужая_нет(сеть: None, склад: Хранилище) -> None:
    # Arrange
    запрос = _запрос(_принятая("D2"))
    _загрузить(склад, запрос.id, data=b"plan-bytes")
    файл = _запрос(запрос.inspection_id).files[0].id

    # Act
    у_ge = plans.file_for_download(файл, reach=reach_of("GE"))
    у_уК = plans.file_for_download(файл, reach=reach_of("HQ"))
    у_am = plans.file_for_download(файл, reach=reach_of("AM"))

    # Assert
    assert у_am is None
    assert у_ge is not None and у_уК is not None
    assert у_ge.file_name == "план.pdf"
    assert plans.fetch_file(у_ge, storage=склад) == b"plan-bytes"


# --- ручной запрос и срок ---------------------------------------------------------


def test_уК_запрашивает_план_по_проверке_без_d2_со_сроком(сеть: None) -> None:
    # Arrange
    ident = _принятая("D1")
    срок = СЕГОДНЯ + timedelta(days=14)

    # Act
    plans.request_plan(ident, actor="hq-lead", due_on=срок)

    # Assert
    запрос = _запрос(ident)
    assert (запрос.origin, запрос.due_on, запрос.requested_by) == ("manual", срок, "hq-lead")


def test_второй_запрос_по_той_же_проверке_это_отказ(сеть: None) -> None:
    ident = _принятая("D2")
    with pytest.raises(ActionPlanError, match="уже"):
        plans.request_plan(ident, actor="hq", due_on=СЕГОДНЯ + timedelta(days=3))


@pytest.mark.parametrize("какая", ["ждущая", "партнёра"])
def test_запросить_можно_только_по_принятой_проверке_уК(сеть: None, какая: str) -> None:
    ident = _проверка("D1") if какая == "ждущая" else _принятая("D1", tenant="GE")
    with pytest.raises(ActionPlanError):
        plans.request_plan(ident, actor="hq", due_on=СЕГОДНЯ + timedelta(days=3))


def test_срок_в_прошлом_это_отказ(сеть: None) -> None:
    ident = _принятая("D1")
    with pytest.raises(ActionPlanError, match="прошёл"):
        plans.request_plan(ident, actor="hq", due_on=СЕГОДНЯ - timedelta(days=1))


def test_уК_правит_срок_и_это_в_истории(сеть: None) -> None:
    запрос = _запрос(_принятая("D2"))
    новый = СЕГОДНЯ + timedelta(days=20)

    plans.set_due(запрос.id, actor="hq-lead", due_on=новый)

    итог = _запрос(запрос.inspection_id)
    assert итог.due_on == новый
    assert [(e.action, e.actor) for e in итог.events][-1] == ("due_changed", "hq-lead")


def test_просрочка_считается_на_чтении(сеть: None, admin_env: str) -> None:
    запрос = _запрос(_принятая("D2"))
    _sql(
        admin_env,
        "update action_plan_requests set due_on = %s where id = %s",
        (СЕГОДНЯ - timedelta(days=1), запрос.id),
    )
    итог = _запрос(запрос.inspection_id)
    assert итог.overdue(СЕГОДНЯ) is True
    assert итог.overdue(date(2000, 1, 1)) is False


def test_админская_связь_не_та_что_у_приложения(db_env: str) -> None:
    """Санитарная: тесты выше действительно ходят двумя разными ролями."""
    assert admin_role_dsn(db_env) != db_env
