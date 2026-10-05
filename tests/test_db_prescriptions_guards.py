"""Предписания: заслоны по ревью #499 — гонки, подпись связей, «сегодня», пределы.

- Закрытие и ответ разом: ответ не ложится на закрытое (advisory-замок 0037).
- Связи черновика правят только с подписью, и правка видна в истории.
- «Сегодня» для срока у базы — по UTC, как у кода, а не по часовому поясу сессии.
- Тема письма — одной строкой; ответов на одно предписание — не больше предела.
- Закрытые читаются по своему частичному индексу.
"""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from conftest import requires_db
from db_harness import set_retraction_env, привязать_страну, точка_справочника
from test_db_prescriptions import (
    _МНОГО_ЗАКРЫТЫХ_SQL,
    _hq,
    _sql,
    _ответить,
    _отправленное,
    _черновик,
)

psycopg = pytest.importorskip("psycopg")

from src.db import prescriptions as rx  # noqa: E402
from src.db import prescriptions_write as rxw  # noqa: E402
from src.db.errors import PrescriptionError  # noqa: E402
from src.db.reach import reach_of  # noqa: E402

pytestmark = requires_db


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


#: Предел ожидания условия, а не пауза: цикл выходит, как только условие наступило.
ЖДАТЬ_ДО = 15.0

_ОТВЕТ_SQL = (
    "insert into prescription_replies (id, prescription_id, comment, replied_by, replied_tenant)"
    " values (gen_random_uuid(), %s, 'гонка', 'partner-ge', 'GE')"
)
_ЖДЁТ_ЗАМКА_SQL = "select count(*) from pg_locks where locktype = 'advisory' and not granted"


def _в_потоке(действие: Any) -> tuple[threading.Thread, threading.Event, list[BaseException]]:
    готово = threading.Event()
    ошибки: list[BaseException] = []

    def бег() -> None:
        try:
            действие()
        except BaseException as exc:  # ошибка потока передаётся в тест
            ошибки.append(exc)
        finally:
            готово.set()

    поток = threading.Thread(target=бег, daemon=True)
    поток.start()
    return поток, готово, ошибки


def _дождаться(готово: threading.Event, pg_dsn: str) -> None:
    """Пока поток не закончил или не встал в очередь за advisory-замком."""
    срок = time.monotonic() + ЖДАТЬ_ДО
    with psycopg.connect(pg_dsn, autocommit=True) as набл:
        while time.monotonic() < срок:
            if готово.wait(0.05):
                return
            строка = набл.execute(_ЖДЁТ_ЗАМКА_SQL).fetchone()
            if строка is not None and int(строка[0]) > 0:
                return
    pytest.fail("поток ответа не закончил и не встал за замок — синхронизация не наступила")


def test_ответ_не_ложится_на_параллельно_закрытое(
    сеть: dict[str, str], admin_env: str, db_env: str, pg_dsn: str
) -> None:
    # Arrange — УК закрывает, но ещё не закоммитил.
    ident = _отправленное()
    закрытие = psycopg.connect(admin_env)
    закрытие.execute(
        "update prescriptions set status = 'closed', closed_by = 'hq-lead',"
        " close_comment = 'выполнено' where id = %s",
        (ident,),
    )

    # Act — партнёр отвечает в это же время, мимо двери (держит база).
    поток, готово, ошибки = _в_потоке(lambda: _sql(db_env, _ОТВЕТ_SQL, (ident,)))
    try:
        _дождаться(готово, pg_dsn)
        закрытие.commit()
    finally:
        закрытие.close()
    поток.join(ЖДАТЬ_ДО)

    # Assert — ответ отвергнут, на закрытом ответов нет.
    assert ошибки, "ответ лёг на предписание, закрытое параллельно"
    assert "отвечают только на действующее" in str(ошибки[0])
    итог = _hq(ident)
    assert итог.status == "closed" and итог.replies == ()


def test_связи_черновика_без_подписи_не_правятся(сеть: dict[str, str], admin_env: str) -> None:
    ident = _черновик(unit_ids=(сеть["Batumi-1"],))
    with pytest.raises(psycopg.errors.CheckViolation, match="с подписью"):
        _sql(
            admin_env,
            "insert into prescription_units (prescription_id, unit_id) values (%s, %s)",
            (ident, сеть["Tbilisi-1"]),
        )
    with pytest.raises(psycopg.errors.CheckViolation, match="с подписью"):
        _sql(admin_env, "delete from prescription_units where prescription_id = %s", (ident,))
    assert [u.name for u in _hq(ident).units] == ["Batumi-1"]


def test_правка_связей_видна_в_истории_одной_записью(сеть: dict[str, str], admin_env: str) -> None:
    ident = _черновик()
    assert [e.action for e in _hq(ident).events] == ["created"]

    # Только пиццерии, поля письма те же — правка всё равно в истории.
    with psycopg.connect(admin_env) as conn:
        conn.execute("select set_config('decimus.prescription_actor', 'hq-lead', true)")
        conn.execute(
            "insert into prescription_units (prescription_id, unit_id) values (%s, %s)",
            (ident, сеть["Batumi-1"]),
        )
        conn.execute(
            "insert into prescription_units (prescription_id, unit_id) values (%s, %s)",
            (ident, сеть["Tbilisi-1"]),
        )
        conn.commit()

    события = _hq(ident).events
    assert [e.action for e in события] == ["created", "edited"]
    assert события[-1].actor == "hq-lead"


def test_сегодня_для_срока_у_базы_по_utc(сеть: dict[str, str], admin_env: str, pg_dsn: str) -> None:
    """Пояс сессии не сдвигает «сегодня»: и код, и база считают его по UTC."""
    сегодня = datetime.now(UTC).date()
    вечер = datetime.now(UTC).hour >= 12
    # Вечером по UTC у пояса +14 уже завтра: срок «сегодня» по current_date
    # отверг бы отправку. Утром у пояса −12 ещё вчера: вчерашний срок
    # по current_date прошёл бы.
    пояс, срок = ("Etc/GMT-14", сегодня) if вечер else ("Etc/GMT+12", сегодня - timedelta(days=1))
    ident = _черновик()
    with psycopg.connect(pg_dsn) as conn:
        conn.execute("alter table prescriptions disable trigger user")
        conn.execute("update prescriptions set due_on = %s where id = %s", (срок, ident))
        conn.execute("alter table prescriptions enable trigger user")
        conn.commit()

    def отправить() -> None:
        with psycopg.connect(admin_env) as conn:
            conn.execute(f"set timezone = '{пояс}'")
            conn.execute(
                "update prescriptions set status = 'issued', issued_by = 'hq-lead' where id = %s",
                (ident,),
            )
            conn.commit()

    if вечер:
        отправить()
        assert _hq(ident).status == "issued"
    else:
        with pytest.raises(psycopg.errors.CheckViolation, match="срок предписания"):
            отправить()


def test_тема_письма_одной_строкой(сеть: dict[str, str], admin_env: str) -> None:
    with pytest.raises(PrescriptionError, match="одной строкой"):
        _черновик(subject="Предписание\r\nBcc: all@example.com")
    ident = _черновик()
    with psycopg.connect(admin_env) as conn:
        conn.execute("select set_config('decimus.prescription_actor', 'hq-lead', true)")
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(
                "update prescriptions set subject = %s where id = %s",
                ("Тема\nBcc: all@example.com", ident),
            )


def test_ответов_не_больше_предела(сеть: dict[str, str]) -> None:
    ident = _отправленное()
    for _ in range(2):
        rxw.reply(
            ident,
            reach=reach_of("GE"),
            tenant="GE",
            actor="partner-ge",
            comment="ещё",
            attachment=None,
            max_bytes=1024,
            max_replies=2,
        )
    with pytest.raises(PrescriptionError, match="уже 2 ответов"):
        rxw.reply(
            ident,
            reach=reach_of("GE"),
            tenant="GE",
            actor="partner-ge",
            comment="третий",
            attachment=None,
            max_bytes=1024,
            max_replies=2,
        )
    assert len(_hq(ident).replies) == 2
    # Предел по умолчанию — из настройки, обычный ответ проходит.
    _ответить(ident)


def test_закрытые_читаются_по_частичному_индексу(pg_dsn: str, сеть: dict[str, str]) -> None:
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute("alter table prescriptions disable trigger user")
        cur.execute(_МНОГО_ЗАКРЫТЫХ_SQL, {"сколько": 8000})
        cur.execute("alter table prescriptions enable trigger user")
        conn.commit()
    with psycopg.connect(pg_dsn, autocommit=True) as conn:
        conn.execute("analyze prescriptions")

    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "explain " + rx._CLOSED_SQL,
            {**rx.reach_params(reach_of("HQ")), "country": None, "limit": rx.LIST_LIMIT + 1},
        )
        план = "\n".join(строка[0] for строка in cur.fetchall())

    assert "prescriptions_closed_idx" in план, f"закрытые не берут свой индекс:\n{план}"
