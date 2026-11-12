"""D759 п.5 (#1670): лимиты пространства и потолок расхода модели — на настоящей базе.

Настройка пространства вместо константы (слив и черновик загрузки), «без лимита»
пустым значением, правка лимитов администратором истории, сумма расхода за месяц
только своего пространства и закрытый потолком вызов. Роль приложения читает
`space_limits`, но не пишет в неё (`test_db_migrate_roles.py` держит права).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from conftest import requires_db

psycopg = pytest.importorskip("psycopg")

from db_harness import привязать_страну, слить_проверку, точка_справочника  # noqa: E402

from src.db import model_usage, space_limits  # noqa: E402
from src.db.errors import AccessError, InspectionLimitError  # noqa: E402
from src.domain.model_usage import ModelCall, usage_scope  # noqa: E402
from src.domain.space_limits import month_start  # noqa: E402
from src.recognize import spend_cap  # noqa: E402
from src.recognize.errors import ModelLimitReached  # noqa: E402

pytestmark = requires_db

ТОЧКА = "Batumi-1"
_REAL_RECORD = model_usage.record


@pytest.fixture
def сеть(pg_dsn: str, db_env: str, domain_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_ADMIN_URL", pg_dsn)
    точка_справочника(ТОЧКА, country="GE", city="Batumi")
    привязать_страну(pg_dsn, tenant="GE", country="GE")
    spend_cap.forget()


def _день(n: int) -> str:
    return f"2026-10-{n:02d}"


def _вызов(tenant: str, *, когда: datetime | None = None, **kw: object) -> None:
    """Строка расхода; дорогой вызов gpt-5.6-sol: 1 млн входа = 4 $ (model_prices.json)."""
    _REAL_RECORD(
        ModelCall(
            kind="recognize",
            model="gpt-5.6-sol",
            ok=True,
            input_tokens=int(kw.get("input", 1_000_000)),  # type: ignore[call-overload]
            output_tokens=0,
            tenant=tenant,
        )
    )
    if когда is not None:
        with psycopg.connect(_dsn()) as conn:
            conn.execute(
                "update model_usage set occurred_at = %s "
                "where id = (select max(id) from model_usage)",
                (когда,),
            )


def _dsn() -> str:
    import os

    return os.environ["DATABASE_ADMIN_URL"]


# --- проверки на пиццерию из настройки -------------------------------------------


def test_лимит_проверок_берётся_из_настройки_пространства(сеть: None) -> None:
    space_limits.set_limits("GE", inspections_per_unit=2, monthly_spend_usd=None, by="boss")

    слить_проверку(unit=ТОЧКА, tenant="GE", date=_день(1))
    слить_проверку(unit=ТОЧКА, tenant="GE", date=_день(2))
    with pytest.raises(InspectionLimitError, match="лимит тестового периода: 2"):
        слить_проверку(unit=ТОЧКА, tenant="GE", date=_день(3))


def test_пустое_значение_снимает_лимит_проверок(сеть: None) -> None:
    space_limits.set_limits("GE", inspections_per_unit=None, monthly_spend_usd=None, by="boss")

    for n in range(1, 8):
        слить_проверку(unit=ТОЧКА, tenant="GE", date=_день(n))


def test_настройка_одного_пространства_не_трогает_другое(сеть: None, pg_dsn: str) -> None:
    space_limits.set_limits("GE", inspections_per_unit=1, monthly_spend_usd=None, by="boss")

    assert space_limits.stored("AM") is None
    assert space_limits.stored("GE") is not None


def test_правка_пишет_кто_менял_и_перезаписывает_строку(сеть: None) -> None:
    space_limits.set_limits("GE", inspections_per_unit=3, monthly_spend_usd=Decimal("10"), by="a")
    space_limits.set_limits("GE", inspections_per_unit=4, monthly_spend_usd=None, by="kostya")

    строка = space_limits.stored_all()["GE"]
    assert строка.limits.inspections_per_unit == 4
    assert строка.limits.monthly_spend_usd is None
    assert строка.updated_by == "kostya" and строка.updated_at is not None


def test_ук_и_незаведённое_и_негодное_значение_отказ(сеть: None) -> None:
    with pytest.raises(AccessError, match="УК лимитов нет"):
        space_limits.set_limits("HQ", inspections_per_unit=1, monthly_spend_usd=None, by="x")
    with pytest.raises(AccessError, match="не заведено"):
        space_limits.set_limits("ZZ", inspections_per_unit=1, monthly_spend_usd=None, by="x")
    with pytest.raises(AccessError):
        space_limits.set_limits("GE", inspections_per_unit=0, monthly_spend_usd=None, by="x")
    with pytest.raises(AccessError):
        space_limits.set_limits(
            "GE", inspections_per_unit=1, monthly_spend_usd=Decimal("-1"), by="x"
        )


def test_роль_приложения_лимиты_не_пишет(сеть: None, db_env: str) -> None:
    with psycopg.connect(db_env) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute(
            "insert into space_limits (tenant_code, inspections_per_unit) values ('GE', 99)"
        )


# --- расход за месяц и потолок -----------------------------------------------------


def test_сумма_расхода_только_своего_пространства_и_только_за_этот_месяц(сеть: None) -> None:
    now = datetime.now(UTC)
    _вызов("GE")
    _вызов("GE", когда=month_start(now) - timedelta(days=1))  # прошлый месяц
    _вызов("AM")

    строки = space_limits.month_spend("GE", month_start(now))

    assert [(r.model, r.input_tokens) for r in строки] == [("gpt-5.6-sol", 1_000_000)]
    assert spend_cap.month_spend("GE").spent == Decimal("4.00")


def test_достигнутый_потолок_закрывает_вызов_а_выше_потолка_и_ук_пускает(сеть: None) -> None:
    space_limits.set_limits("GE", inspections_per_unit=None, monthly_spend_usd=Decimal("5"), by="b")
    _вызов("GE")  # 4 $
    with usage_scope(tenant="GE"):
        spend_cap.ensure_within_cap()  # 4 из 5 — ещё можно

    _вызов("GE")  # 8 $
    spend_cap.forget()
    with usage_scope(tenant="GE"), pytest.raises(ModelLimitReached):
        spend_cap.ensure_within_cap()
    spend_cap.forget()
    with usage_scope(tenant="HQ"):
        spend_cap.ensure_within_cap()


def test_без_строки_настроек_потолок_пятьдесят_долларов(сеть: None) -> None:
    for _ in range(12):
        _вызов("GE")  # 48 $
    spend_cap.forget()
    with usage_scope(tenant="GE"):
        spend_cap.ensure_within_cap()

    _вызов("GE")  # 52 $
    spend_cap.forget()
    with usage_scope(tenant="GE"), pytest.raises(ModelLimitReached):
        spend_cap.ensure_within_cap()


def test_пустой_потолок_значит_без_потолка(сеть: None) -> None:
    space_limits.set_limits("GE", inspections_per_unit=None, monthly_spend_usd=None, by="b")
    for _ in range(14):
        _вызов("GE")
    spend_cap.forget()
    with usage_scope(tenant="GE"):
        spend_cap.ensure_within_cap()
