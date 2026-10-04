"""Предписания в базе: заслоны ролей и стран, неизменяемость отправленного, история (0037).

Проверяется то, что держит БАЗА и двери блока `db`, а не экран: роль
приложения (бот, партнёр в вебе) не заводит, не правит и не закрывает
предписание; вставить сразу «отправленным» не может никто; отправленное и
закрытое не правятся; ответ кладёт только партнёр страны и только в
действующее; партнёр не видит черновиков и чужих стран, угаданный id
предписания или файла отвечает тем же «нет», что несуществующий.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from conftest import requires_db
from db_harness import set_retraction_env, привязать_страну, точка_справочника

psycopg = pytest.importorskip("psycopg")

from src.db import prescriptions as rx  # noqa: E402
from src.db import prescriptions_write as rxw  # noqa: E402
from src.db.accept import accept_inspection  # noqa: E402
from src.db.errors import IssuedDraftLostError, PrescriptionError  # noqa: E402
from src.db.move import move_inspection  # noqa: E402
from src.db.reach import reach_of  # noqa: E402
from src.db.retract import retract_inspection  # noqa: E402

pytestmark = requires_db

СЕГОДНЯ = datetime.now(UTC).date()
СРОК = СЕГОДНЯ + timedelta(days=14)
МБ = 1024 * 1024
_чаты = iter(range(9_400_000, 9_500_000))


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
def сеть(pg_dsn: str, db_env: str, domain_env: Path, admin_env: str) -> dict[str, str]:
    """Batumi-1 и Tbilisi-1 в Грузии (партнёр GE), Yerevan-1 в Армении (партнёр AM)."""
    точки = {
        "Batumi-1": точка_справочника("Batumi-1", country="GE", city="Batumi"),
        "Tbilisi-1": точка_справочника("Tbilisi-1", country="GE", city="Tbilisi"),
        "Yerevan-1": точка_справочника("Yerevan-1", country="AM", city="Yerevan"),
    }
    привязать_страну(pg_dsn, tenant="GE", country="GE")
    привязать_страну(pg_dsn, tenant="AM", country="AM")
    return точки


@pytest.fixture
def склад() -> Хранилище:
    return Хранилище()


def _принятая(unit: str = "Batumi-1", tenant: str = "HQ") -> str:
    from src.db.push import push_inspection
    from src.domain import add_finding, start_inspection

    чат = next(_чаты)
    start_inspection(чат, unit=unit, kind="planned", report_lang="ru", tenant=tenant)
    add_finding(чат, code="PRD02", level="D2", zone="cold_kitchen", text="запись")
    ident = push_inspection(чат)
    accept_inspection(ident, tenant=tenant, actor="garva")
    return ident


def _черновик(**поля: Any) -> str:
    основа: dict[str, Any] = {
        "country": "GE",
        "due_on": СРОК,
        "recipients": "ops@ge.example.com",
        "subject": "Предписание · Грузия",
        "body": "Требуем устранить нарушения в срок.",
    }
    return rxw.create_draft(rx.Draft(**{**основа, **поля}), actor="hq-lead")


def _положено(журнал: list[str]) -> rx.PutDraft:
    def положить(предписание: rx.Prescription) -> None:
        журнал.append(предписание.id)

    return положить


def _отправленное(**поля: Any) -> str:
    ident = _черновик(**поля)
    rxw.issue(ident, actor="hq-lead", put_draft=_положено([]))
    return ident


def _hq(ident: str) -> rx.Prescription:
    найдено = rx.get_prescription(ident, reach=reach_of("HQ"))
    assert найдено is not None, "предписания нет и у УК"
    return найдено


def _sql(dsn: str, текст: str, параметры: tuple[Any, ...] = ()) -> None:
    with psycopg.connect(dsn) as conn:
        conn.execute(текст, параметры)
        conn.commit()


def _ответить(ident: str, *, tenant: str = "GE", склад: Хранилище | None = None, **kw: Any) -> str:
    return rxw.reply(
        ident,
        reach=reach_of(tenant),
        tenant=tenant,
        actor=f"partner-{tenant.lower()}",
        comment=kw.pop("comment", "исправили"),
        attachment=kw.pop("attachment", None),
        max_bytes=25 * МБ,
        storage=склад,
    )


# --- путь: черновик → отправка → ответ → закрытие ---------------------------


def test_путь_предписания_и_его_история(сеть: dict[str, str], склад: Хранилище) -> None:
    # Arrange
    основание = _принятая()
    журнал: list[str] = []
    ident = _черновик(unit_ids=(сеть["Batumi-1"],), inspection_ids=(основание,))

    # Act
    rxw.issue(ident, actor="hq-lead", put_draft=_положено(журнал))
    _ответить(
        ident,
        склад=склад,
        comment="план приложен",
        attachment=rxw.Attachment(name="ответ.pdf", content_type="application/pdf", data=b"%PDF"),
    )
    rxw.close(ident, actor="hq-lead", comment="выполнено")

    # Assert
    итог = _hq(ident)
    assert журнал == [ident], "черновик в почту не клали или клали не то"
    assert итог.status == "closed" and итог.close_comment == "выполнено"
    assert [u.name for u in итог.units] == ["Batumi-1"]
    assert [b.inspection_id for b in итог.bases] == [основание] and итог.bases[0].known
    assert итог.replies[0].comment == "план приложен"
    assert [(e.action, e.actor) for e in итог.events] == [
        ("created", "hq-lead"),
        ("issued", "hq-lead"),
        ("replied", "partner-ge"),
        ("closed", "hq-lead"),
    ]


def test_отправка_запоминает_адресатов_страны(сеть: dict[str, str]) -> None:
    assert rx.remembered_recipients("GE") == ""
    _отправленное(recipients="a@ge.example.com; b@ge.example.com")
    assert rx.remembered_recipients("GE") == "a@ge.example.com, b@ge.example.com"


def test_не_легло_в_почту_остаётся_черновиком(сеть: dict[str, str]) -> None:
    ident = _черновик()

    def отказ(_: rx.Prescription) -> None:
        raise RuntimeError("Gmail недоступен")

    with pytest.raises(RuntimeError):
        rxw.issue(ident, actor="hq-lead", put_draft=отказ)
    assert _hq(ident).status == "draft"
    assert rx.remembered_recipients("GE") == ""


def test_правка_черновика_в_истории_с_подписью(сеть: dict[str, str]) -> None:
    ident = _черновик()
    rxw.update_draft(
        ident,
        rx.Draft(
            country="AM",  # страну правка не меняет — берётся из базы
            due_on=СРОК,
            recipients="new@ge.example.com",
            subject="Новая тема",
            body="Новый текст",
            unit_ids=(сеть["Tbilisi-1"],),
        ),
        actor="hq-two",
    )
    итог = _hq(ident)
    assert (итог.country, итог.subject, итог.recipients) == (
        "GE",
        "Новая тема",
        "new@ge.example.com",
    )
    assert [u.name for u in итог.units] == ["Tbilisi-1"]
    assert [(e.action, e.actor) for e in итог.events] == [
        ("created", "hq-lead"),
        ("edited", "hq-two"),
    ]


# --- неизменяемость отправленного ------------------------------------------


def test_отправленное_не_правится_дверью(сеть: dict[str, str]) -> None:
    ident = _отправленное()
    with pytest.raises(PrescriptionError, match="не правится"):
        rxw.update_draft(
            ident,
            rx.Draft(
                country="GE", due_on=СРОК, recipients="x@ge.example.com", subject="s", body="b"
            ),
            actor="hq-lead",
        )


@pytest.mark.parametrize(
    "правка",
    [
        "update prescriptions set body = 'подмена' where id = %s",
        "update prescriptions set due_on = due_on + 30 where id = %s",
        "update prescriptions set recipients = 'evil@x.example.com' where id = %s",
        "update prescriptions set status = 'draft' where id = %s",
    ],
)
def test_отправленное_не_правит_и_уК_мимо_двери(
    сеть: dict[str, str], admin_env: str, правка: str
) -> None:
    ident = _отправленное()
    with pytest.raises(psycopg.errors.CheckViolation, match="не правится"):
        _sql(admin_env, правка, (ident,))
    assert _hq(ident).body == "Требуем устранить нарушения в срок."


def test_пиццерии_отправленного_не_меняются(сеть: dict[str, str], admin_env: str) -> None:
    ident = _отправленное(unit_ids=(сеть["Batumi-1"],))
    with pytest.raises(psycopg.errors.CheckViolation, match="только у черновика"):
        _sql(admin_env, "delete from prescription_units where prescription_id = %s", (ident,))
    with pytest.raises(psycopg.errors.CheckViolation, match="только у черновика"):
        _sql(
            admin_env,
            "insert into prescription_units (prescription_id, unit_id) values (%s, %s)",
            (ident, сеть["Tbilisi-1"]),
        )


def test_закрытое_не_меняется(сеть: dict[str, str], admin_env: str) -> None:
    ident = _отправленное()
    rxw.close(ident, actor="hq-lead", comment="снято")
    with pytest.raises(psycopg.errors.CheckViolation, match="закрытое"):
        _sql(admin_env, "update prescriptions set status = 'issued' where id = %s", (ident,))


def test_закрыть_без_комментария_нельзя(сеть: dict[str, str], admin_env: str) -> None:
    ident = _отправленное()
    with pytest.raises(PrescriptionError, match="с комментарием"):
        rxw.close(ident, actor="hq-lead", comment="  ")
    with pytest.raises(psycopg.errors.CheckViolation, match="комментарием"):
        _sql(
            admin_env,
            "update prescriptions set status = 'closed', closed_by = 'hq' where id = %s",
            (ident,),
        )


def test_черновик_не_закрывают(сеть: dict[str, str]) -> None:
    ident = _черновик()
    with pytest.raises(PrescriptionError, match="только действующее"):
        rxw.close(ident, actor="hq-lead", comment="зря")


# --- заслоны ролей (урок #490) ---------------------------------------------


def test_роль_приложения_не_заводит_предписание(сеть: dict[str, str], db_env: str) -> None:
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        _sql(
            db_env,
            "insert into prescriptions (country, due_on, subject, body, created_by)"
            " values ('GE', current_date + 7, 's', 'b', 'bot')",
        )


def test_роль_приложения_не_правит_и_не_закрывает(сеть: dict[str, str], db_env: str) -> None:
    ident = _отправленное()
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        _sql(
            db_env,
            "update prescriptions set status = 'closed', closed_by = 'bot',"
            " close_comment = 'сам закрыл' where id = %s",
            (ident,),
        )


def test_отправленным_не_вставляет_никто(сеть: dict[str, str], admin_env: str) -> None:
    with pytest.raises(psycopg.errors.InsufficientPrivilege, match="только черновиком"):
        _sql(
            admin_env,
            "insert into prescriptions (country, due_on, subject, body, created_by, status,"
            " issued_by, issued_at) values ('GE', current_date + 7, 's', 'b', 'hq', 'issued',"
            " 'hq', now())",
        )


def test_историю_не_пишет_напрямую_никто(сеть: dict[str, str], db_env: str, admin_env: str) -> None:
    ident = _черновик()
    for dsn in (db_env, admin_env):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            _sql(
                dsn,
                "insert into prescription_events (prescription_id, action, actor)"
                " values (%s, 'closed', 'кто-то')",
                (ident,),
            )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            _sql(dsn, "insert into country_recipients values ('GE', 'evil@x.example.com', 'x')")


def test_правка_черновика_без_подписи_это_отказ(сеть: dict[str, str], admin_env: str) -> None:
    ident = _черновик()
    with pytest.raises(psycopg.errors.CheckViolation, match="с подписью"):
        _sql(admin_env, "update prescriptions set body = 'тихо' where id = %s", (ident,))


# --- основания и пиццерии: страна из источника -----------------------------


def test_пиццерия_чужой_страны_не_привязывается(сеть: dict[str, str]) -> None:
    with pytest.raises(PrescriptionError, match="не из страны"):
        _черновик(unit_ids=(сеть["Yerevan-1"],))


@pytest.mark.parametrize("какая", ["чужой страны", "партнёра"])
def test_основание_только_принятая_проверка_уК_страны(сеть: dict[str, str], какая: str) -> None:
    проверка = _принятая("Yerevan-1") if какая == "чужой страны" else _принятая(tenant="GE")
    with pytest.raises(PrescriptionError, match="основанием служит"):
        _черновик(inspection_ids=(проверка,))


def test_отклонённое_основание_не_даёт_отправить_и_видно_пометкой(
    сеть: dict[str, str], admin_env: str
) -> None:
    # Arrange — черновик на проверке, которую потом отклонили.
    основание = _принятая()
    ident = _черновик(inspection_ids=(основание,))
    retract_inspection(основание, tenant="HQ", reason="ошибка точки", storage=Хранилище())

    # Act / Assert
    with pytest.raises(PrescriptionError, match="отклонена"):
        rxw.issue(ident, actor="hq-lead", put_draft=_положено([]))
    база = _hq(ident).bases
    assert [(b.inspection_id, b.known) for b in база] == [(основание, False)]


def test_перенос_основания_в_другую_страну_не_даёт_отправить(
    сеть: dict[str, str],
) -> None:
    основание = _принятая()
    ident = _черновик(inspection_ids=(основание,))
    move_inspection(
        основание,
        tenant="HQ",
        new_date=СЕГОДНЯ,
        new_unit_id=сеть["Yerevan-1"],
        reason="не та точка",
        actor="garva",
    )
    with pytest.raises(PrescriptionError, match="уже не в стране"):
        rxw.issue(ident, actor="hq-lead", put_draft=_положено([]))


def test_без_адресатов_не_отправляют(сеть: dict[str, str]) -> None:
    ident = _черновик(recipients="")
    журнал: list[str] = []
    with pytest.raises(PrescriptionError, match="Нет адресатов"):
        rxw.issue(ident, actor="hq-lead", put_draft=_положено(журнал))
    assert журнал == [], "черновик в почту положен без адресатов"


def test_отметка_не_легла_после_черновика_говорит_об_этом(
    сеть: dict[str, str], admin_env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    ident = _черновик()
    monkeypatch.setattr(
        rxw,
        "_ISSUE_SQL",
        "update prescriptions set status = 'closed' where id = %(id)s and %(actor)s is not null",
    )
    with pytest.raises(IssuedDraftLostError, match="Удалите этот черновик"):
        rxw.issue(ident, actor="hq-lead", put_draft=_положено([]))
    assert _hq(ident).status == "draft"


# --- охват: партнёр, чужая страна, IDOR -------------------------------------


def test_партнёр_видит_только_отправленное_своей_страны(сеть: dict[str, str]) -> None:
    черновик = _черновик(subject="черновик")
    своё = _отправленное(subject="своё")
    rxw.close(_отправленное(subject="закрытое"), actor="hq-lead", comment="ок")
    with_closed = rx.list_prescriptions(reach=reach_of("GE"), closed=True)

    открытые = rx.list_prescriptions(reach=reach_of("GE"))
    assert [p.subject for p in открытые.rows] == ["своё"]
    assert [p.subject for p in with_closed.rows] == ["закрытое"]
    assert rx.get_prescription(черновик, reach=reach_of("GE")) is None
    assert rx.get_prescription(своё, reach=reach_of("GE")) is not None
    assert rx.list_prescriptions(reach=reach_of("AM")).rows == ()
    assert rx.get_prescription(своё, reach=reach_of("AM")) is None
    уК = rx.list_prescriptions(reach=reach_of("HQ"))
    assert {p.subject for p in уК.rows} == {"черновик", "своё"}


def test_партнёр_без_охвата_стран_не_видит_ничего(сеть: dict[str, str]) -> None:
    from src.db.reach import own_reach

    ident = _отправленное()
    assert rx.get_prescription(ident, reach=own_reach("GE")) is None
    assert rx.list_prescriptions(reach=own_reach("GE")).rows == ()


def test_чужой_id_неотличим_от_несуществующего(сеть: dict[str, str]) -> None:
    ident = _отправленное()
    assert rx.get_prescription(ident, reach=reach_of("AM")) is None
    assert rx.get_prescription("00000000-0000-0000-0000-000000000000", reach=reach_of("AM")) is None
    assert rx.get_prescription("не-uuid", reach=reach_of("HQ")) is None


def test_ответ_только_партнёр_своей_страны(сеть: dict[str, str], db_env: str) -> None:
    ident = _отправленное()
    with pytest.raises(PrescriptionError, match="Предписания нет"):
        _ответить(ident, tenant="AM")
    with pytest.raises(PrescriptionError, match="партнёр страны"):
        _ответить(ident, tenant="HQ")
    # Мимо двери — тоже отказ: держит триггер, а не охват кода.
    with pytest.raises(psycopg.errors.InsufficientPrivilege, match="не отвечает за страну"):
        _sql(
            db_env,
            "insert into prescription_replies (id, prescription_id, comment, replied_by,"
            " replied_tenant) values (gen_random_uuid(), %s, 'чужой', 'am', 'AM')",
            (ident,),
        )


def test_на_черновик_и_закрытое_не_отвечают(сеть: dict[str, str], db_env: str) -> None:
    черновик = _черновик()
    закрытое = _отправленное()
    rxw.close(закрытое, actor="hq-lead", comment="ок")
    with pytest.raises(PrescriptionError):
        _ответить(черновик)
    with pytest.raises(PrescriptionError, match="закрыто"):
        _ответить(закрытое)
    for ident in (черновик, закрытое):
        with pytest.raises(psycopg.errors.CheckViolation, match="только на действующее"):
            _sql(
                db_env,
                "insert into prescription_replies (id, prescription_id, comment, replied_by,"
                " replied_tenant) values (gen_random_uuid(), %s, 'мимо', 'ge', 'GE')",
                (ident,),
            )


def test_файл_ответа_скачивают_своя_страна_и_уК_а_чужая_нет(
    сеть: dict[str, str], склад: Хранилище
) -> None:
    ident = _отправленное()
    ответ = _ответить(
        ident,
        склад=склад,
        attachment=rxw.Attachment(name="../../ответ.pdf", content_type="", data=b"%PDF"),
    )
    assert rx.file_for_download(ответ, reach=reach_of("AM")) is None
    своя = rx.file_for_download(ответ, reach=reach_of("GE"))
    уК = rx.file_for_download(ответ, reach=reach_of("HQ"))
    assert своя is not None and уК is not None
    assert своя.file_name == "ответ.pdf"
    assert rx.fetch_file(уК, storage=склад) == b"%PDF"
    assert своя.storage_path.startswith("s3://test/prescriptions/")


def test_не_легла_строка_ответа_объект_убран(сеть: dict[str, str], склад: Хранилище) -> None:
    ident = _отправленное()
    with pytest.raises(PrescriptionError):
        _ответить(
            ident,
            tenant="AM",
            склад=склад,
            attachment=rxw.Attachment(name="x.pdf", content_type="", data=b"x"),
        )
    assert склад.объекты == {}


def test_файл_больше_предела_не_принимается(сеть: dict[str, str], склад: Хранилище) -> None:
    ident = _отправленное()
    with pytest.raises(PrescriptionError, match="ATTACHMENT_MAX_MB"):
        rxw.reply(
            ident,
            reach=reach_of("GE"),
            tenant="GE",
            actor="p",
            comment="к",
            attachment=rxw.Attachment(name="x", content_type="", data=b"12345"),
            max_bytes=4,
            storage=склад,
        )


# --- просрочка и очередь ----------------------------------------------------


def test_просрочка_считается_на_чтении(сеть: dict[str, str], pg_dsn: str) -> None:
    ident = _отправленное()
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute("alter table prescriptions disable trigger user")
        cur.execute("update prescriptions set due_on = current_date - 1 where id = %s", (ident,))
        cur.execute("alter table prescriptions enable trigger user")
        conn.commit()
    assert _hq(ident).state(СЕГОДНЯ) == rx.STATE_OVERDUE


def test_упёршийся_в_предел_список_говорит_об_этом(
    сеть: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _черновик()
    _черновик()
    monkeypatch.setattr(rx, "LIST_LIMIT", 1)
    список = rx.list_prescriptions(reach=reach_of("HQ"))
    assert список.truncated is True and len(список.rows) == 1


_МНОГО_ЗАКРЫТЫХ_SQL = """
insert into prescriptions (country, due_on, subject, body, created_by, status, issued_by,
                           issued_at, closed_by, closed_at, close_comment)
select 'GE', current_date - (g %% 900), 's', 'b', 'hq', 'closed', 'hq', now(), 'hq', now(), 'ok'
from generate_series(1, %(сколько)s) g
"""


def test_очередь_всех_стран_идёт_по_частичному_индексу(pg_dsn: str, сеть: dict[str, str]) -> None:
    """Закрытые копятся годами — очередь УК по всем странам их не читает."""
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute("alter table prescriptions disable trigger user")
        cur.execute(_МНОГО_ЗАКРЫТЫХ_SQL, {"сколько": 8000})
        cur.execute("alter table prescriptions enable trigger user")
        conn.commit()
    for _ in range(5):
        _черновик()
    with psycopg.connect(pg_dsn, autocommit=True) as conn:
        conn.execute("analyze prescriptions")

    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "explain " + rx._OPEN_SQL,
            {**rx.reach_params(reach_of("HQ")), "country": None, "limit": rx.LIST_LIMIT + 1},
        )
        план = "\n".join(строка[0] for строка in cur.fetchall())

    assert "prescriptions_open_idx" in план, f"очередь не берёт свой индекс:\n{план}"
