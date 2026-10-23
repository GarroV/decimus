"""Электронный план исправлений в базе: строки, сроки, права, путь, уведомления (#1168, `0092`).

Ядро — то, что партнёр читает как факт: срок строки (дни методики от начала отсчёта, не
больше потолка класса, D3 — немедленно; свой срок только раньше; сдвиг начала пересчитывает
всё, кроме перенесённого с согласием) и «кто что может» (партнёр пишет только строки своей
страны и только в своих статусах, вердикты — УК, уведомление ложится вместе с переходом).
Каждое правило проверяется и дверью (`plan_flow`), и мимо двери — прямым SQL под ролью, чтобы
защита сидела в базе, а не только в коде.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from conftest import TEST_DATA, requires_db
from db_harness import set_retraction_env, привязать_страну, точка_справочника

psycopg = pytest.importorskip("psycopg")

from src.db import action_plans as plans  # noqa: E402
from src.db import notifications as store  # noqa: E402
from src.db import plan_flow as flow  # noqa: E402
from src.db.accept import accept_inspection  # noqa: E402
from src.db.errors import ActionPlanError  # noqa: E402
from src.db.plan_rows import PlanRow  # noqa: E402
from src.db.reach import reach_of  # noqa: E402
from src.domain.config import DATA_FILES  # noqa: E402
from src.domain.plan_due import load_deadlines, plan_due_days  # noqa: E402
from src.domain.version import compose  # noqa: E402

pytestmark = requires_db

ТОЧКА = "Batumi-1"
ЧУЖАЯ_ТОЧКА = "Yerevan-1"
СЕГОДНЯ = datetime.now(UTC).date()
_чаты = iter(range(9_300_000, 9_400_000))

УК_АДМИН = "hq-admin"
УК_ДЕВЕЛОПЕР = "hq-dev"
ГРУЗИЯ_АННА = "ge-anna"
ГРУЗИЯ_БОРИС = "ge-boris"
АРМЕНИЯ_ИВАН = "am-ivan"


@pytest.fixture
def admin_env(db_env: str, monkeypatch: pytest.MonkeyPatch) -> str:
    return set_retraction_env(db_env, monkeypatch)


@pytest.fixture
def сеть(pg_dsn: str, db_env: str, domain_env: Path, admin_env: str) -> dict[str, str]:
    """Грузия и Армения с партнёрами, админ и девелопер УК; ключи учёток — как их знает база."""
    from src.db.web_access import password_hash

    точка_справочника(ТОЧКА, country="GE", city="Batumi")
    точка_справочника(ЧУЖАЯ_ТОЧКА, country="AM", city="Yerevan")
    привязать_страну(pg_dsn, tenant="GE", country="GE")
    привязать_страну(pg_dsn, tenant="AM", country="AM")
    хеш = password_hash("пароль-учётки-теста")
    ключи: dict[str, str] = {}
    with psycopg.connect(pg_dsn) as conn:
        conn.execute("insert into tenants (code) values ('HQ') on conflict do nothing")
        for пространство, логин, роль in (
            ("HQ", УК_АДМИН, "admin"),
            ("HQ", УК_ДЕВЕЛОПЕР, "developer"),
            ("GE", ГРУЗИЯ_АННА, "admin"),
            ("GE", ГРУЗИЯ_БОРИС, "auditor"),
            ("AM", АРМЕНИЯ_ИВАН, "admin"),
        ):
            строка = conn.execute(
                "insert into web_users (tenant_code, login, password_hash, role) "
                "values (%s, %s, %s, %s) returning id::text",
                (пространство, логин, хеш, роль),
            ).fetchone()
            assert строка is not None
            ключи[логин] = строка[0]
        conn.commit()
    return ключи


def _принятая(*уровни: str, unit: str = ТОЧКА) -> str:
    """Принятая проверка УК с записями названных классов; запрос плана завёлся сам."""
    from src.db.push import push_inspection
    from src.domain import add_finding, start_inspection

    чат = next(_чаты)
    start_inspection(чат, unit=unit, kind="planned", report_lang="ru", tenant="HQ")
    коды = {"D1": "PRD01", "D2": "PRD02", "D3": "PRD04"}
    зоны = {"D1": "fridge", "D2": "cold_kitchen", "D3": "dry_storage"}
    for уровень in уровни:
        add_finding(чат, code=коды[уровень], level=уровень, zone=зоны[уровень], text="запись")
    ident = push_inspection(чат)
    accept_inspection(ident, tenant="HQ", actor="garva")
    return ident


def _запрос(ident: str) -> plans.PlanRequest:
    найден = plans.request_of_inspection(ident, reach=reach_of("HQ"))
    assert найден is not None, "запроса по проверке нет"
    return найден


def _заполнить(запрос: plans.PlanRequest, **kw: Any) -> None:
    """Партнёр Грузии заполняет все строки запроса (мера и ответственный у каждой)."""
    for строка in запрос.rows:
        flow.save_row(
            запрос.id,
            строка.id,
            reach=reach_of("GE"),
            tenant="GE",
            actor=ГРУЗИЯ_АННА,
            measure=kw.get("measure", f"Исправим {строка.item_code}"),
            responsible=kw.get("responsible", "Шеф-повар"),
            reason=kw.get("reason"),
            own_due=kw.get("own_due"),
        )


def _на_согласовании(*уровни: str) -> plans.PlanRequest:
    ident = _принятая(*уровни)
    _заполнить(_запрос(ident))
    flow.submit_plan(_запрос(ident).id, reach=reach_of("GE"), tenant="GE", actor=ГРУЗИЯ_АННА)
    return _запрос(ident)


def _в_работе(*уровни: str) -> plans.PlanRequest:
    запрос = _на_согласовании(*уровни)
    flow.accept_plan(запрос.id, actor=УК_АДМИН)
    return _запрос(запрос.inspection_id)


def _сдана(строка: PlanRow, запрос: plans.PlanRequest) -> None:
    for шаг in (flow.start_row, flow.finish_row):
        шаг(
            запрос.id,
            строка.id,
            reach=reach_of("GE"),
            tenant="GE",
            actor=ГРУЗИЯ_АННА,
        )


def _без_умолчания(dsn: str) -> str:
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    return make_conninfo(**{k: v for k, v in conninfo_to_dict(dsn).items() if k != "options"})


@contextmanager
def _роль_приложения(db_env: str, space: str, actor: str = "") -> Iterator[Any]:
    """Соединение роли приложения от имени пространства (оснастка тестов своё не подставляет)."""
    with psycopg.connect(_без_умолчания(db_env)) as conn:
        conn.execute("select set_config('decimus.space', %s, false)", (space,))
        if actor:
            conn.execute("select set_config('decimus.plan_actor', %s, false)", (actor,))
        conn.commit()
        yield conn


@contextmanager
def _админ(admin_env: str, actor: str = "") -> Iterator[Any]:
    with psycopg.connect(admin_env) as conn:
        if actor:
            conn.execute("select set_config('decimus.plan_actor', %s, false)", (actor,))
        yield conn


# --- заведение строк ---------------------------------------------------------


def test_запрос_сам_заводит_строки_по_нарушениям_тяжёлые_сверху(сеть: dict[str, str]) -> None:
    запрос = _запрос(_принятая("D1", "D2", "D3"))

    assert запрос.electronic and запрос.status == "requested"
    assert [(r.level, r.item_code, r.zone) for r in запрос.rows] == [
        ("D3", "PRD04", "dry_storage"),
        ("D2", "PRD02", "cold_kitchen"),
        ("D1", "PRD01", "fridge"),
    ]
    assert [r.position for r in запрос.rows] == [1, 2, 3]
    assert all(r.status == "filling" and not r.measure for r in запрос.rows)
    assert all(r.title_ru for r in запрос.rows), "снимок формулировки не лёг"


def test_одна_строка_на_запись_проверки_без_рекомендаций(сеть: dict[str, str]) -> None:
    from src.db.push import push_inspection
    from src.domain import add_finding, start_inspection

    чат = next(_чаты)
    start_inspection(чат, unit=ТОЧКА, kind="planned", report_lang="ru", tenant="HQ")
    add_finding(чат, code="PRD02", level="D2", zone="cold_kitchen", text="нарушение")
    add_finding(чат, code="PRD02", level="D2", zone="fridge", text="то же в другой зоне")
    add_finding(чат, code="PRD01", level="R", zone="fridge", text="рекомендация")
    ident = push_inspection(чат)
    accept_inspection(ident, tenant="HQ", actor="garva")

    строки = _запрос(ident).rows

    assert [(r.level, r.zone) for r in строки] == [("D2", "cold_kitchen"), ("D2", "fridge")]


def test_срок_строки_это_начало_плюс_дни_методики_не_больше_потолка(
    сеть: dict[str, str],
) -> None:
    запрос = _запрос(_принятая("D1", "D2", "D3"))
    книга = load_deadlines(compose(TEST_DATA, DATA_FILES))

    for строка in запрос.rows:
        дни = книга.days_for(строка.item_code, строка.level)
        assert строка.days == дни
        assert строка.due_on == запрос.count_from + timedelta(days=дни)
    d3 = next(r for r in запрос.rows if r.level == "D3")
    assert d3.days == 0 and d3.due_on == запрос.count_from, "D3 — немедленно"


def test_начало_отсчёта_по_умолчанию_день_подтверждения_а_срок_плана_от_него(
    сеть: dict[str, str],
) -> None:
    запрос = _запрос(_принятая("D2"))

    assert запрос.count_from == СЕГОДНЯ
    assert запрос.due_on == СЕГОДНЯ + timedelta(days=plan_due_days())


def test_уК_называет_начало_отсчёта_при_ручном_запросе(сеть: dict[str, str]) -> None:
    ident = _принятая("D1")
    начало = СЕГОДНЯ - timedelta(days=3)

    # D1 даёт электронный запрос, но авто-запроса нет: D272 только D2/D3.
    request_id = plans.request_plan(ident, actor=УК_АДМИН, count_from=начало)

    запрос = _запрос(ident)
    assert запрос.id == request_id and запрос.electronic and запрос.count_from == начало
    assert запрос.due_on == начало + timedelta(days=plan_due_days())
    assert [r.due_on for r in запрос.rows] == [начало + timedelta(days=r.days) for r in запрос.rows]


def test_ручной_запрос_по_проверке_без_нарушений_остаётся_файловым(сеть: dict[str, str]) -> None:
    from src.db.push import push_inspection
    from src.domain import add_finding, start_inspection

    чат = next(_чаты)
    start_inspection(чат, unit=ТОЧКА, kind="planned", report_lang="ru", tenant="HQ")
    add_finding(чат, code="PRD01", level="R", zone="fridge", text="только рекомендация")
    ident = push_inspection(чат)
    accept_inspection(ident, tenant="HQ", actor="garva")

    plans.request_plan(ident, actor=УК_АДМИН)

    запрос = _запрос(ident)
    assert not запрос.electronic and запрос.rows == ()


# --- сроки: свой срок, сдвиг отсчёта, просрочка ------------------------------


def test_партнёр_ставит_срок_раньше_положенного(сеть: dict[str, str]) -> None:
    запрос = _запрос(_принятая("D2"))
    строка = запрос.rows[0]
    раньше = строка.due_on - timedelta(days=2)

    flow.save_row(
        запрос.id,
        строка.id,
        reach=reach_of("GE"),
        tenant="GE",
        actor=ГРУЗИЯ_АННА,
        measure="Исправим",
        responsible="Шеф",
        reason=None,
        own_due=max(раньше, СЕГОДНЯ),
    )

    итог = _запрос(запрос.inspection_id).rows[0]
    assert итог.own_due == max(раньше, СЕГОДНЯ) and итог.due_on == итог.own_due


def test_позже_положенного_партнёр_срок_не_ставит_ни_дверью_ни_мимо_неё(
    сеть: dict[str, str], db_env: str
) -> None:
    запрос = _запрос(_принятая("D2"))
    строка = запрос.rows[0]
    позже = строка.due_on + timedelta(days=1)

    with pytest.raises(ActionPlanError, match="позже положенного"):
        flow.save_row(
            запрос.id,
            строка.id,
            reach=reach_of("GE"),
            tenant="GE",
            actor=ГРУЗИЯ_АННА,
            measure="м",
            responsible="о",
            reason=None,
            own_due=позже,
        )
    with _роль_приложения(db_env, "GE") as conn, pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("update action_plan_rows set own_due = %s where id = %s", (позже, строка.id))
    assert _запрос(запрос.inspection_id).rows[0].own_due is None


def test_d3_срок_только_день_начала_раньше_нельзя(сеть: dict[str, str]) -> None:
    запрос = _запрос(_принятая("D3"))
    строка = запрос.rows[0]

    with pytest.raises(ActionPlanError):
        flow.save_row(
            запрос.id,
            строка.id,
            reach=reach_of("GE"),
            tenant="GE",
            actor=ГРУЗИЯ_АННА,
            measure="м",
            responsible="о",
            reason=None,
            own_due=запрос.count_from - timedelta(days=1),
        )


def test_сдвиг_начала_пересчитывает_срок_плана_и_строк_кроме_перенесённых(
    сеть: dict[str, str], admin_env: str
) -> None:
    запрос = _запрос(_принятая("D1", "D2"))
    перенесена, обычная = запрос.rows[0], запрос.rows[1]
    перенос = СЕГОДНЯ + timedelta(days=40)
    with _админ(admin_env) as conn:
        conn.execute(
            "update action_plan_rows set extended_due = %s where id = %s", (перенос, перенесена.id)
        )
        conn.commit()
    новое = СЕГОДНЯ + timedelta(days=5)

    flow.set_count_from(запрос.id, actor=УК_АДМИН, count_from=новое)

    итог = _запрос(запрос.inspection_id)
    assert итог.count_from == новое
    assert итог.due_on == новое + timedelta(days=plan_due_days())
    по_id = {r.id: r for r in итог.rows}
    assert по_id[обычная.id].due_on == новое + timedelta(days=обычная.days)
    assert по_id[перенесена.id].due_on == перенос, "перенос с согласием сдвинулся вместе с началом"
    assert ("count_from_changed", УК_АДМИН) in [(e.action, e.actor) for e in итог.events]


def test_сдвиг_начала_не_отодвигает_свой_срок_партнёра_позже_положенного(
    сеть: dict[str, str],
) -> None:
    запрос = _запрос(_принятая("D2"))
    строка = запрос.rows[0]
    свой = max(строка.due_on - timedelta(days=1), СЕГОДНЯ)
    flow.save_row(
        запрос.id,
        строка.id,
        reach=reach_of("GE"),
        tenant="GE",
        actor=ГРУЗИЯ_АННА,
        measure="м",
        responsible="о",
        reason=None,
        own_due=свой,
    )

    # Начало сдвинули назад: положенный срок стал раньше своего срока партнёра.
    flow.set_count_from(запрос.id, actor=УК_АДМИН, count_from=СЕГОДНЯ - timedelta(days=30))

    итог = _запрос(запрос.inspection_id).rows[0]
    assert итог.due_on == СЕГОДНЯ - timedelta(days=30) + timedelta(days=итог.days)


def test_просрочка_строки_считается_на_чтении_а_не_хранится(сеть: dict[str, str]) -> None:
    запрос = _запрос(_принятая("D2"))
    строка = запрос.rows[0]

    assert not строка.overdue(строка.due_on)
    assert строка.overdue(строка.due_on + timedelta(days=1))


def test_отсчёт_нельзя_сдвинуть_у_закрытого_плана(сеть: dict[str, str]) -> None:
    запрос = _в_работе("D3")
    for строка in запрос.rows:
        _сдана(строка, запрос)
        flow.confirm_row(запрос.id, строка.id, actor=УК_АДМИН)

    with pytest.raises(ActionPlanError, match="принят"):
        flow.set_count_from(запрос.id, actor=УК_АДМИН, count_from=СЕГОДНЯ)


def test_партнёр_начало_отсчёта_не_правит_даже_мимо_двери(
    сеть: dict[str, str], db_env: str
) -> None:
    запрос = _запрос(_принятая("D2"))

    with (
        _роль_приложения(db_env, "GE", "x") as conn,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        conn.execute(
            "update action_plan_requests set count_from = current_date - 5 where id = %s",
            (запрос.id,),
        )


# --- права: кто что пишет ----------------------------------------------------


def test_партнёр_чужой_страны_строку_не_правит_и_план_не_отправляет(сеть: dict[str, str]) -> None:
    запрос = _запрос(_принятая("D2"))
    строка = запрос.rows[0]

    with pytest.raises(ActionPlanError, match="нет"):
        flow.save_row(
            запрос.id,
            строка.id,
            reach=reach_of("AM"),
            tenant="AM",
            actor=АРМЕНИЯ_ИВАН,
            measure="чужое",
            responsible="чужой",
            reason=None,
            own_due=None,
        )
    with pytest.raises(ActionPlanError, match="нет"):
        flow.submit_plan(запрос.id, reach=reach_of("AM"), tenant="AM", actor=АРМЕНИЯ_ИВАН)
    assert not _запрос(запрос.inspection_id).rows[0].measure


def test_пространство_чужой_страны_не_видит_и_не_правит_строки_мимо_двери(
    сеть: dict[str, str], db_env: str
) -> None:
    запрос = _запрос(_принятая("D2"))
    строка = запрос.rows[0]

    with _роль_приложения(db_env, "AM") as conn:
        видно = conn.execute("select count(*) from action_plan_rows").fetchone()
        изменено = conn.execute(
            "update action_plan_rows set measure = 'чужое' where id = %s", (строка.id,)
        ).rowcount
    assert видно == (0,), "строки чужой страны видны без охвата"
    assert изменено == 0
    assert not _запрос(запрос.inspection_id).rows[0].measure


def test_пространство_ук_строки_партнёра_не_пишет_мимо_двери(
    сеть: dict[str, str], db_env: str
) -> None:
    запрос = _запрос(_принятая("D2"))

    with (
        _роль_приложения(db_env, "HQ") as conn,
        pytest.raises(psycopg.errors.InsufficientPrivilege, match="партнёр"),
    ):
        conn.execute(
            "update action_plan_rows set measure = 'за партнёра' where id = %s",
            (запрос.rows[0].id,),
        )


def test_администратор_истории_не_заполняет_мера_ответственный_причина(
    сеть: dict[str, str], admin_env: str
) -> None:
    запрос = _запрос(_принятая("D2"))

    for колонка in ("measure", "responsible", "reason", "own_due"):
        значение = "current_date" if колонка == "own_due" else "'за партнёра'"
        with _админ(admin_env) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(
                f"update action_plan_rows set {колонка} = {значение} where id = %s",  # noqa: S608
                (запрос.rows[0].id,),
            )


def test_строки_заводит_только_уК_и_снимок_строки_не_меняется(
    сеть: dict[str, str], db_env: str, admin_env: str
) -> None:
    запрос = _запрос(_принятая("D2"))
    строка = запрос.rows[0]

    with (
        _роль_приложения(db_env, "GE") as conn,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        conn.execute(
            "insert into action_plan_rows (request_id, finding_id, position, item_code, level,"
            " zone, days) values (%s, %s, 99, 'X', 'D1', 'z', 1)",
            (запрос.id, строка.finding_id),
        )
    with _админ(admin_env) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("update action_plan_rows set days = 99 where id = %s", (строка.id,))


def test_на_согласование_нельзя_пока_у_строки_нет_меры_и_ответственного(
    сеть: dict[str, str], db_env: str
) -> None:
    запрос = _запрос(_принятая("D2", "D1"))
    flow.save_row(
        запрос.id,
        запрос.rows[0].id,
        reach=reach_of("GE"),
        tenant="GE",
        actor=ГРУЗИЯ_АННА,
        measure="Исправим",
        responsible="  ",
        reason=None,
        own_due=None,
    )

    with pytest.raises(ActionPlanError, match="не заполнено 2 из 2"):
        flow.submit_plan(запрос.id, reach=reach_of("GE"), tenant="GE", actor=ГРУЗИЯ_АННА)
    with (
        _роль_приложения(db_env, "GE", ГРУЗИЯ_АННА) as conn,
        pytest.raises(psycopg.errors.CheckViolation),
    ):
        conn.execute(
            "update action_plan_requests set status = 'on_review' where id = %s", (запрос.id,)
        )


def test_уК_план_за_партнёра_не_отправляет(сеть: dict[str, str], admin_env: str) -> None:
    запрос = _запрос(_принятая("D2"))
    _заполнить(запрос)

    with _админ(admin_env, УК_АДМИН) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute(
            "update action_plan_requests set status = 'on_review' where id = %s", (запрос.id,)
        )
    with pytest.raises(ActionPlanError, match="партнёр"):
        flow.submit_plan(запрос.id, reach=reach_of("HQ"), tenant="HQ", actor=УК_АДМИН)


def test_на_согласовании_строки_уже_не_правятся(сеть: dict[str, str], db_env: str) -> None:
    запрос = _на_согласовании("D2")
    строка = запрос.rows[0]

    with pytest.raises(ActionPlanError, match="согласование"):
        flow.save_row(
            запрос.id,
            строка.id,
            reach=reach_of("GE"),
            tenant="GE",
            actor=ГРУЗИЯ_АННА,
            measure="правка задним числом",
            responsible="о",
            reason=None,
            own_due=None,
        )
    with _роль_приложения(db_env, "GE") as conn, pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("update action_plan_rows set measure = 'x' where id = %s", (строка.id,))


def test_принять_и_вернуть_план_может_только_уК_и_возврат_с_комментарием(
    сеть: dict[str, str], db_env: str
) -> None:
    запрос = _на_согласовании("D2")

    with (
        _роль_приложения(db_env, "GE", ГРУЗИЯ_АННА) as conn,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        conn.execute(
            "update action_plan_requests set status = 'in_work' where id = %s", (запрос.id,)
        )
    with pytest.raises(ActionPlanError, match="комментарием"):
        flow.return_plan(запрос.id, actor=УК_АДМИН, comment="  ")
    assert _запрос(запрос.inspection_id).status == "on_review"


def test_строки_не_двигаются_пока_план_не_принят(сеть: dict[str, str]) -> None:
    запрос = _на_согласовании("D2")

    with pytest.raises(ActionPlanError, match="не принят"):
        flow.start_row(
            запрос.id, запрос.rows[0].id, reach=reach_of("GE"), tenant="GE", actor=ГРУЗИЯ_АННА
        )


def test_партнёр_не_подтверждает_и_не_возвращает_строку_мимо_двери(
    сеть: dict[str, str], db_env: str
) -> None:
    запрос = _в_работе("D2")
    строка = запрос.rows[0]
    _сдана(строка, запрос)

    for статус in ("confirmed", "returned"):
        with (
            _роль_приложения(db_env, "GE", ГРУЗИЯ_АННА) as conn,
            pytest.raises(psycopg.errors.InsufficientPrivilege),
        ):
            conn.execute(
                "update action_plan_rows set status = %s where id = %s", (статус, строка.id)
            )
    assert _запрос(запрос.inspection_id).rows[0].status == "done"


def test_строку_нельзя_сдать_не_взяв_в_работу_и_двигать_без_подписи(
    сеть: dict[str, str], db_env: str
) -> None:
    запрос = _в_работе("D2")
    строка = запрос.rows[0]

    with pytest.raises(ActionPlanError, match="Сначала"):
        flow.finish_row(запрос.id, строка.id, reach=reach_of("GE"), tenant="GE", actor=ГРУЗИЯ_АННА)
    with (
        _роль_приложения(db_env, "GE") as conn,
        pytest.raises(psycopg.errors.CheckViolation, match="подпис"),
    ):
        conn.execute("update action_plan_rows set status = 'in_work' where id = %s", (строка.id,))


def test_вернуть_строку_можно_только_с_причиной_и_подтверждённая_не_меняется(
    сеть: dict[str, str], admin_env: str
) -> None:
    запрос = _в_работе("D2")
    строка = запрос.rows[0]
    _сдана(строка, запрос)

    with pytest.raises(ActionPlanError, match="причиной"):
        flow.return_row(запрос.id, строка.id, actor=УК_АДМИН, reason=" ")
    flow.confirm_row(запрос.id, строка.id, actor=УК_АДМИН)
    with _админ(admin_env, УК_АДМИН) as conn, pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            "update action_plan_rows set status = 'returned', return_reason = 'x' where id = %s",
            (строка.id,),
        )


def test_закрыть_план_базой_можно_только_когда_подтверждены_все_строки(
    сеть: dict[str, str], admin_env: str
) -> None:
    запрос = _в_работе("D2", "D1")

    with (
        _админ(admin_env, УК_АДМИН) as conn,
        pytest.raises(psycopg.errors.CheckViolation, match="подтверждены"),
    ):
        conn.execute(
            "update action_plan_requests set status = 'closed' where id = %s", (запрос.id,)
        )


# --- путь целиком ------------------------------------------------------------


def test_путь_заполнение_согласование_работа_подтверждение_закрыт(
    сеть: dict[str, str],
) -> None:
    ident = _принятая("D3", "D2")
    запрос = _запрос(ident)
    ревизия = запрос.revision
    _заполнить(запрос)
    assert _запрос(ident).revision > ревизия, "правка строк не подняла ревизию"
    flow.submit_plan(запрос.id, reach=reach_of("GE"), tenant="GE", actor=ГРУЗИЯ_АННА)
    assert _запрос(ident).status == "on_review"

    flow.return_plan(запрос.id, actor=УК_АДМИН, comment="Уточните меры")
    возвращён = _запрос(ident)
    assert возвращён.status == "requested" and возвращён.state == "returned"
    assert возвращён.last_comment == "Уточните меры"
    flow.submit_plan(запрос.id, reach=reach_of("GE"), tenant="GE", actor=ГРУЗИЯ_АННА)
    flow.accept_plan(запрос.id, actor=УК_АДМИН)
    принят = _запрос(ident)
    assert принят.status == "in_work" and принят.state == "in_work"

    первая, вторая = принят.rows
    _сдана(первая, принят)
    flow.return_row(запрос.id, первая.id, actor=УК_АДМИН, reason="Нет фото")
    after_return = {r.id: r for r in _запрос(ident).rows}
    assert after_return[первая.id].status == "returned"
    assert after_return[первая.id].return_reason == "Нет фото"
    flow.finish_row(запрос.id, первая.id, reach=reach_of("GE"), tenant="GE", actor=ГРУЗИЯ_АННА)
    _сдана(вторая, принят)
    flow.confirm_row(запрос.id, первая.id, actor=УК_АДМИН)
    assert _запрос(ident).status == "in_work", "план закрылся, не все строки подтверждены"
    flow.confirm_row(запрос.id, вторая.id, actor=УК_АДМИН)

    итог = _запрос(ident)
    assert итог.status == "closed" and итог.state == "closed"
    assert all(r.status == "confirmed" for r in итог.rows)
    assert [e.action for e in итог.events if e.row_id is None] == [
        "requested",
        "submitted",
        "returned",
        "submitted",
        "accepted",
        "closed",
    ]
    assert [(e.action, e.actor) for e in итог.events if e.row_id == первая.id] == [
        ("row_started", ГРУЗИЯ_АННА),
        ("row_done", ГРУЗИЯ_АННА),
        ("row_returned", УК_АДМИН),
        ("row_done", ГРУЗИЯ_АННА),
        ("row_confirmed", УК_АДМИН),
    ]


def test_закрытый_план_уходит_из_очереди_в_принятые(сеть: dict[str, str]) -> None:
    запрос = _в_работе("D3")
    открытый = {r.id for r in plans.list_requests(reach=reach_of("HQ")).rows}
    assert запрос.id in открытый
    for строка in запрос.rows:
        _сдана(строка, запрос)
        flow.confirm_row(запрос.id, строка.id, actor=УК_АДМИН)

    assert запрос.id not in {r.id for r in plans.list_requests(reach=reach_of("HQ")).rows}
    принятые = plans.list_requests(reach=reach_of("HQ"), accepted=True)
    assert запрос.id in {r.id for r in принятые.rows}


def test_электронный_план_файлом_и_старым_вердиктом_не_ведётся(сеть: dict[str, str]) -> None:
    запрос = _на_согласовании("D2")

    with pytest.raises(ActionPlanError, match="электронный"):
        plans.review(запрос.id, actor=УК_АДМИН, verdict="accepted", comment="")
    with pytest.raises(ActionPlanError, match="электронный"):
        plans.upload_version(
            запрос.id,
            reach=reach_of("GE"),
            tenant="GE",
            actor=ГРУЗИЯ_АННА,
            file_name="план.pdf",
            content_type="application/pdf",
            data=b"%PDF",
            max_bytes=1024,
        )


# --- уведомления внутри приложения -------------------------------------------


def _виды(ключ: str) -> list[str]:
    return sorted(n.kind for n in store.list_for(ключ))


def test_запрос_плана_получают_партнёры_страны_а_не_чужой_страны_и_не_ук(
    сеть: dict[str, str],
) -> None:
    запрос = _запрос(_принятая("D2"))

    for логин in (ГРУЗИЯ_АННА, ГРУЗИЯ_БОРИС):
        строки = store.list_for(сеть[логин])
        assert [(n.kind, n.link) for n in строки] == [
            ("plan_requested", f"/actions?tab=plans&id={запрос.id}")
        ]
        assert строки[0].params["unit"] == ТОЧКА
    assert _виды(сеть[АРМЕНИЯ_ИВАН]) == [], "партнёр чужой страны получил уведомление"
    assert _виды(сеть[УК_АДМИН]) == [] and _виды(сеть[УК_ДЕВЕЛОПЕР]) == []


def test_ход_плана_уведомляет_нужных_и_актёр_себя_не_уведомляет(сеть: dict[str, str]) -> None:
    запрос = _на_согласовании("D3")
    # Отправка на согласование — админам УК (пока девелопер страны не учётка), не партнёру.
    assert "plan_submitted" in _виды(сеть[УК_АДМИН])
    assert "plan_submitted" not in _виды(сеть[ГРУЗИЯ_АННА])
    assert "plan_submitted" not in _виды(сеть[УК_ДЕВЕЛОПЕР])

    flow.accept_plan(запрос.id, actor=УК_АДМИН)
    assert "plan_accepted" in _виды(сеть[ГРУЗИЯ_АННА]) and "plan_accepted" in _виды(
        сеть[ГРУЗИЯ_БОРИС]
    )
    assert "plan_accepted" not in _виды(сеть[УК_АДМИН]), "актёр уведомил сам себя"

    строка = _запрос(запрос.inspection_id).rows[0]
    _сдана(строка, запрос)
    готово = [n for n in store.list_for(сеть[УК_АДМИН]) if n.kind == "plan_row_done"]
    assert [n.link for n in готово] == [f"/actions?tab=plans&id={запрос.id}&row={строка.id}"]
    assert "plan_row_done" not in _виды(сеть[ГРУЗИЯ_АННА])

    flow.return_row(запрос.id, строка.id, actor=УК_АДМИН, reason="Не то")
    assert "plan_row_returned" in _виды(сеть[ГРУЗИЯ_АННА])
    flow.finish_row(запрос.id, строка.id, reach=reach_of("GE"), tenant="GE", actor=ГРУЗИЯ_АННА)
    flow.confirm_row(запрос.id, строка.id, actor=УК_АДМИН)
    assert "plan_row_confirmed" in _виды(сеть[ГРУЗИЯ_БОРИС])
    assert _виды(сеть[АРМЕНИЯ_ИВАН]) == [], "партнёр чужой страны получил уведомление плана"


def test_отказ_перехода_не_оставляет_уведомления(сеть: dict[str, str]) -> None:
    запрос = _на_согласовании("D2")
    было = len(store.list_for(сеть[ГРУЗИЯ_АННА]))

    with pytest.raises(ActionPlanError):
        flow.return_plan(запрос.id, actor=УК_АДМИН, comment="")

    assert len(store.list_for(сеть[ГРУЗИЯ_АННА])) == было


# --- догон строк старым открытым запросам ------------------------------------


def test_старый_открытый_запрос_без_файла_получает_строки_и_сухой_прогон_не_пишет(
    сеть: dict[str, str], pg_dsn: str
) -> None:
    from db_harness import сделать_файловым

    from src.db.plan_backfill import backfill_rows

    ident = _принятая("D1", "D3")
    сделать_файловым(pg_dsn, _запрос(ident).id)

    сухой = backfill_rows()

    assert (сухой.candidates, сухой.converted, сухой.rows, сухой.applied) == (1, 1, 2, False)
    assert not _запрос(ident).electronic, "сухой прогон записал"

    backfill_rows(apply=True)

    запрос = _запрос(ident)
    assert запрос.electronic and [r.level for r in запрос.rows] == ["D3", "D1"]
    assert all(r.due_on == запрос.count_from + timedelta(days=r.days) for r in запрос.rows)

    повтор = backfill_rows(apply=True)
    assert (повтор.candidates, повтор.converted) == (0, 0), "второй прогон взял уже готовый запрос"
