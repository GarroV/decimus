"""Согласование предписания ОСБ в базе: переходы, возврат, обход мимо двери (0087, D599, D600).

Ядро (доступ и порядок решений — тесты раньше кода): ни одно предписание не уходит
партнёру без согласования. Проверяется то, что держит БАЗА, а не экран:

- путь draft → review → (возврат с комментарием) → review → approved → issued → closed;
- ОСБ согласует свой черновик без шага «на согласовании»;
- отправка не из `approved`, возврат без комментария, вставка не черновиком —
  отказ и у двери, и у прямого SQL администратора истории;
- правка согласованного (текст или связи) снимает согласование;
- автор правит свой черновик, в `review` и `approved` правит только ведущий;
- партнёр не видит ничего, кроме отправленного и закрытого.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import requires_db
from db_harness import set_retraction_env, привязать_страну, точка_справочника
from test_db_prescriptions import (
    СРОК,
    _hq,
    _sql,
    _положено,
    _принятая,
)

psycopg = pytest.importorskip("psycopg")

from src.db import prescriptions as rx  # noqa: E402
from src.db import prescriptions_write as rxw  # noqa: E402
from src.db.errors import PrescriptionError  # noqa: E402
from src.db.reach import reach_of  # noqa: E402

pytestmark = requires_db

АВТОР = "dev-anna"
ОСБ = "osb-vera"


@pytest.fixture
def admin_env(db_env: str, monkeypatch: pytest.MonkeyPatch) -> str:
    return set_retraction_env(db_env, monkeypatch)


@pytest.fixture
def сеть(pg_dsn: str, db_env: str, domain_env: Path, admin_env: str) -> dict[str, str]:
    точки = {
        "Batumi-1": точка_справочника("Batumi-1", country="GE", city="Batumi"),
        "Tbilisi-1": точка_справочника("Tbilisi-1", country="GE", city="Tbilisi"),
    }
    привязать_страну(pg_dsn, tenant="GE", country="GE")
    return точки


def _драфт(**поля: object) -> rx.Draft:
    основа: dict[str, object] = {
        "country": "GE",
        "due_on": СРОК,
        "recipients": "ops@ge.example.com",
        "subject": "Предписание · Грузия",
        "body": "Требуем устранить нарушения в срок.",
    }
    return rx.Draft(**{**основа, **поля})  # type: ignore[arg-type]


def _от_автора(**поля: object) -> str:
    return rxw.create_draft(_драфт(**поля), actor=АВТОР)


def _согласованное(**поля: object) -> str:
    ident = _от_автора(**поля)
    rxw.request_review(ident, actor=АВТОР)
    rxw.approve(ident, actor=ОСБ)
    return ident


def _действия(ident: str) -> list[str]:
    return [e.action for e in _hq(ident).events]


# --- путь ------------------------------------------------------------------


def test_полный_путь_с_возвратом_и_его_история(сеть: dict[str, str]) -> None:
    # Arrange
    основание = _принятая()
    ident = _от_автора(unit_ids=(сеть["Batumi-1"],), inspection_ids=(основание,))
    журнал: list[str] = []

    # Act / Assert по шагам: каждый шаг меняет статус ровно на одно звено цикла.
    rxw.request_review(ident, actor=АВТОР)
    assert _hq(ident).status == "review"
    rxw.return_to_author(ident, actor=ОСБ, comment="Уточните срок по цеху")
    assert _hq(ident).status == "draft"
    rxw.request_review(ident, actor=АВТОР)
    rxw.approve(ident, actor=ОСБ)
    согласованное = _hq(ident)
    assert (согласованное.status, согласованное.approved_by) == ("approved", ОСБ)
    assert согласованное.approved_at is not None
    rxw.issue(ident, actor=ОСБ, put_draft=_положено(журнал))
    rxw.close(ident, actor=ОСБ, comment="выполнено")

    # Assert
    итог = _hq(ident)
    assert итог.status == "closed" and журнал == [ident]
    assert [(e.action, e.actor) for e in итог.events] == [
        ("created", АВТОР),
        ("requested", АВТОР),
        ("returned", ОСБ),
        ("requested", АВТОР),
        ("approved", ОСБ),
        ("issued", ОСБ),
        ("closed", ОСБ),
    ]
    возврат = next(e for e in итог.events if e.action == "returned")
    assert возврат.detail == "Уточните срок по цеху"


def test_осб_согласует_свой_черновик_без_шага_на_согласовании(сеть: dict[str, str]) -> None:
    ident = rxw.create_draft(_драфт(), actor=ОСБ)
    rxw.approve(ident, actor=ОСБ)
    assert _hq(ident).status == "approved"
    rxw.issue(ident, actor=ОСБ, put_draft=_положено([]))
    assert _действия(ident) == ["created", "approved", "issued"]


def test_форма_девелопера_сразу_отправляет_на_согласование(сеть: dict[str, str]) -> None:
    ident = rxw.create_draft(_драфт(), actor=АВТОР, submit=True)
    assert _hq(ident).status == "review"
    assert _действия(ident) == ["created", "requested"]


# --- без согласования предписание не уходит ---------------------------------


@pytest.mark.parametrize("состояние", ["draft", "review"])
def test_отправка_не_из_согласованного_отказ_у_двери(сеть: dict[str, str], состояние: str) -> None:
    ident = _от_автора()
    if состояние == "review":
        rxw.request_review(ident, actor=АВТОР)
    журнал: list[str] = []
    with pytest.raises(PrescriptionError, match="согласован"):
        rxw.issue(ident, actor=ОСБ, put_draft=_положено(журнал))
    assert журнал == [], "письмо легло в почту без согласования"
    assert _hq(ident).status == состояние


@pytest.mark.parametrize("состояние", ["draft", "review"])
def test_отправка_не_из_согласованного_отказ_и_у_прямого_sql(
    сеть: dict[str, str], admin_env: str, состояние: str
) -> None:
    ident = _от_автора()
    if состояние == "review":
        rxw.request_review(ident, actor=АВТОР)
    with pytest.raises(psycopg.errors.CheckViolation, match="только согласованным"):
        _sql(
            admin_env,
            "update prescriptions set status = 'issued', issued_by = 'hq' where id = %s",
            (ident,),
        )
    assert _hq(ident).status == состояние


@pytest.mark.parametrize("статус", ["review", "approved"])
def test_вставка_не_черновиком_отказ_у_любой_роли(
    сеть: dict[str, str], admin_env: str, db_env: str, статус: str
) -> None:
    вставка = (
        "insert into prescriptions (country, due_on, subject, body, created_by, status)"
        " values ('GE', current_date + 7, 's', 'b', 'hq', %s)"
    )
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        _sql(db_env, вставка, (статус,))
    with pytest.raises(psycopg.errors.InsufficientPrivilege, match="только черновиком"):
        _sql(admin_env, вставка, (статус,))


def test_согласование_нельзя_вписать_в_черновик_мимо_перехода(
    сеть: dict[str, str], admin_env: str
) -> None:
    ident = _от_автора()
    with pytest.raises(psycopg.errors.CheckViolation):
        _sql(
            admin_env,
            "update prescriptions set approved_by = 'hq' where id = %s",
            (ident,),
        )


def test_согласовать_без_подписи_нельзя(сеть: dict[str, str], admin_env: str) -> None:
    ident = _от_автора()
    with pytest.raises(psycopg.errors.CheckViolation):
        _sql(admin_env, "update prescriptions set status = 'approved' where id = %s", (ident,))


def test_кто_согласовал_не_переписывают(сеть: dict[str, str], admin_env: str) -> None:
    ident = _согласованное()
    with pytest.raises(psycopg.errors.CheckViolation, match="не переписывают"):
        _sql(admin_env, "update prescriptions set approved_by = 'другой' where id = %s", (ident,))
    assert _hq(ident).approved_by == ОСБ


def test_согласованное_не_закрывают_и_не_откатывают_в_черновик(
    сеть: dict[str, str], admin_env: str
) -> None:
    ident = _согласованное()
    with pytest.raises(psycopg.errors.CheckViolation, match="не закрывают"):
        _sql(
            admin_env,
            "update prescriptions set status = 'closed', closed_by = 'hq', close_comment = 'x'"
            " where id = %s",
            (ident,),
        )
    with psycopg.connect(admin_env) as conn:
        conn.execute("select set_config('decimus.prescription_actor', 'hq', true)")
        with pytest.raises(
            psycopg.errors.CheckViolation, match=r"не предусмотрен|нет согласования"
        ):
            conn.execute(
                "update prescriptions set status = 'draft', approved_by = null where id = %s",
                (ident,),
            )


# --- возврат только с комментарием ------------------------------------------


@pytest.mark.parametrize("комментарий", ["", "   "])
def test_возврат_без_комментария_отказ_у_двери(сеть: dict[str, str], комментарий: str) -> None:
    ident = _от_автора()
    rxw.request_review(ident, actor=АВТОР)
    with pytest.raises(PrescriptionError, match="комментарием"):
        rxw.return_to_author(ident, actor=ОСБ, comment=комментарий)
    assert _hq(ident).status == "review"


def test_возврат_без_комментария_отказ_и_у_прямого_sql(
    сеть: dict[str, str], admin_env: str
) -> None:
    ident = _от_автора()
    rxw.request_review(ident, actor=АВТОР)
    with psycopg.connect(admin_env) as conn:
        conn.execute("select set_config('decimus.prescription_actor', 'osb', true)")
        with pytest.raises(psycopg.errors.CheckViolation, match="с комментарием"):
            conn.execute("update prescriptions set status = 'draft' where id = %s", (ident,))
    assert _hq(ident).status == "review"


def test_возвращать_можно_только_то_что_на_согласовании(сеть: dict[str, str]) -> None:
    ident = _от_автора()
    with pytest.raises(PrescriptionError, match="на согласовании"):
        rxw.return_to_author(ident, actor=ОСБ, comment="зачем")


# --- правка согласованного снимает согласование ------------------------------


def test_правка_текста_согласованного_снимает_согласование(сеть: dict[str, str]) -> None:
    ident = _согласованное()

    rxw.update_draft(ident, _драфт(body="Новый текст"), actor=ОСБ, manager=True)

    итог = _hq(ident)
    assert (итог.status, итог.approved_by, итог.approved_at) == ("review", None, None)
    assert итог.body == "Новый текст"
    assert (итог.events[-1].action, итог.events[-1].detail) == ("edited", "approval_dropped")


def test_правка_пиццерий_согласованного_снимает_согласование(сеть: dict[str, str]) -> None:
    ident = _согласованное(unit_ids=(сеть["Batumi-1"],))

    rxw.update_draft(ident, _драфт(unit_ids=(сеть["Tbilisi-1"],)), actor=ОСБ, manager=True)

    итог = _hq(ident)
    assert итог.status == "review"
    assert [u.name for u in итог.units] == ["Tbilisi-1"]


def test_после_снятия_согласования_отправка_закрыта_пока_не_согласуют_снова(
    сеть: dict[str, str],
) -> None:
    ident = _согласованное()
    rxw.update_draft(ident, _драфт(body="Другое"), actor=ОСБ, manager=True)
    with pytest.raises(PrescriptionError, match="согласован"):
        rxw.issue(ident, actor=ОСБ, put_draft=_положено([]))
    rxw.approve(ident, actor=ОСБ)
    rxw.issue(ident, actor=ОСБ, put_draft=_положено([]))
    assert _hq(ident).status == "issued"


def test_согласуют_тем_что_лежит_без_правки_в_том_же_шаге(
    сеть: dict[str, str], admin_env: str
) -> None:
    ident = _от_автора()
    with psycopg.connect(admin_env) as conn:
        conn.execute("select set_config('decimus.prescription_actor', 'osb', true)")
        with pytest.raises(psycopg.errors.CheckViolation, match="без правки"):
            conn.execute(
                "update prescriptions set status = 'approved', approved_by = 'osb',"
                " body = 'подмена при согласовании' where id = %s",
                (ident,),
            )


# --- кто что правит ---------------------------------------------------------


def test_автор_правит_свой_черновик_чужой_нет(сеть: dict[str, str]) -> None:
    ident = _от_автора()
    rxw.update_draft(ident, _драфт(body="Поправил автор"), actor=АВТОР)
    assert _hq(ident).body == "Поправил автор"
    with pytest.raises(PrescriptionError, match="автор"):
        rxw.update_draft(ident, _драфт(body="Чужая правка"), actor="dev-boris")
    assert _hq(ident).body == "Поправил автор"


@pytest.mark.parametrize("состояние", ["review", "approved"])
def test_на_согласовании_и_после_автор_не_правит_ведущий_правит(
    сеть: dict[str, str], состояние: str
) -> None:
    ident = _от_автора()
    rxw.request_review(ident, actor=АВТОР)
    if состояние == "approved":
        rxw.approve(ident, actor=ОСБ)
    with pytest.raises(PrescriptionError, match="ОСБ"):
        rxw.update_draft(ident, _драфт(body="Автор лезет"), actor=АВТОР)
    rxw.update_draft(ident, _драфт(body="Правит ОСБ"), actor=ОСБ, manager=True)
    assert _hq(ident).body == "Правит ОСБ"


def test_запросить_согласование_чужого_черновика_нельзя(сеть: dict[str, str]) -> None:
    ident = _от_автора()
    with pytest.raises(PrescriptionError, match="автор"):
        rxw.request_review(ident, actor="dev-boris")
    rxw.request_review(ident, actor=ОСБ, manager=True)
    assert _hq(ident).status == "review"


def test_отправленное_не_правится_ни_автором_ни_ведущим(сеть: dict[str, str]) -> None:
    ident = _согласованное()
    rxw.issue(ident, actor=ОСБ, put_draft=_положено([]))
    with pytest.raises(PrescriptionError, match="не правится"):
        rxw.update_draft(ident, _драфт(body="поздно"), actor=ОСБ, manager=True)


# --- прежние выданные и закрытые остаются как есть --------------------------


def test_выданное_до_согласования_живёт_и_закрывается(сеть: dict[str, str], pg_dsn: str) -> None:
    """Предписание, выданное до 0087, без полей согласования: схема его допускает."""
    ident = _от_автора()
    with psycopg.connect(pg_dsn) as conn:
        conn.execute("alter table prescriptions disable trigger prescriptions_guarded")
        conn.execute("alter table prescriptions disable trigger prescriptions_logged")
        conn.execute(
            "update prescriptions set status = 'issued', issued_by = 'old-lead', issued_at = now()"
            " where id = %s",
            (ident,),
        )
        conn.execute("alter table prescriptions enable trigger prescriptions_guarded")
        conn.execute("alter table prescriptions enable trigger prescriptions_logged")
        conn.commit()

    rxw.close(ident, actor=ОСБ, comment="закрыто прежнее")

    итог = _hq(ident)
    assert (итог.status, итог.approved_by) == ("closed", None)


# --- партнёр -----------------------------------------------------------------


def test_партнёр_не_видит_ничего_до_отправки_и_не_отвечает_на_неотправленное(
    сеть: dict[str, str],
) -> None:
    черновик = _от_автора(subject="черновик")
    на_согласовании = _от_автора(subject="на согласовании")
    rxw.request_review(на_согласовании, actor=АВТОР)
    согласованное = _согласованное(subject="согласованное")
    отправленное = _согласованное(subject="отправленное")
    rxw.issue(отправленное, actor=ОСБ, put_draft=_положено([]))

    партнёр = reach_of("GE")
    видно = rx.list_prescriptions(reach=партнёр).rows
    assert [p.subject for p in видно] == ["отправленное"]
    for скрытое in (черновик, на_согласовании, согласованное):
        assert rx.get_prescription(скрытое, reach=партнёр) is None
        with pytest.raises(PrescriptionError):
            rxw.reply(
                скрытое,
                reach=партнёр,
                tenant="GE",
                actor="partner-ge",
                comment="рано",
                attachment=None,
                max_bytes=1024,
            )
    assert rx.country_prescriptions("GE", reach=reach_of("HQ")).rows[0].subject == "отправленное"
    assert len(rx.country_prescriptions("GE", reach=reach_of("HQ")).rows) == 1
