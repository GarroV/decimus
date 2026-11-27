"""`sales_summary` (MCP): суммы, средний чек, доли, дельты и охват.

Ядро — числа и охват: выручка разных валют не складывается, идущий месяц не сравнивается
с полным, партнёр не видит и не выведывает чужие страны. База подменена на уровне
`dodois_metrics` и `agg_store` так, как её отдавал бы SQL: строки только запрошенной страны
и месяца. Классификация источника и канала — настоящая `domain.sales_view`, та же, что у экрана.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest

from src.db import agg_store, dodois_metrics
from src.db.dodois_metrics import KindLoad, UnitAggregatorOrders, UnitSales
from src.db.reach import Reach
from src.mcp import sales_read as tool
from src.mcp.catalogue import KIND_RATINGS_READ, find
from src.mcp.errors import ToolError
from src.mcp.rpc import handle

A, B, C = "a1" * 16, "a2" * 16, "c1" * 16
МЕСЯЦ = date(2026, 9, 1)
ПРОШЛЫЙ = date(2026, 8, 1)
ГОД_НАЗАД = date(2025, 9, 1)


def _р(uid: str, источник: str, канал: str, заказы: int, выручка: str, валюта: str) -> UnitSales:
    return UnitSales(uid, источник, канал, заказы, Decimal(выручка), валюта)


# (страна, месяц) -> строки продаж
ПРОДАЖИ = {
    ("RS", МЕСЯЦ): [
        _р(A, "Dine-in", "Dine-in", 10, "1000", "RSD"),
        _р(A, "Mobile app", "Delivery", 20, "3000", "RSD"),
        _р(A, "Aggregator", "Delivery", 30, "6000", "RSD"),
        _р(B, "Website", "Takeaway", 40, "2000", "RSD"),
        _р(B, "Phone", "Delivery", 0, "0", "RSD"),
    ],
    ("RS", ПРОШЛЫЙ): [_р(A, "Dine-in", "Dine-in", 50, "4000", "RSD")],
    ("RS", ГОД_НАЗАД): [_р(A, "Dine-in", "Dine-in", 200, "8000", "RSD")],
    ("TR", МЕСЯЦ): [_р(C, "Aggregator", "Delivery", 5, "500", "TRY")],
}
РЕЕСТР = (
    agg_store.UnitRow(A, "RS", "Beograd-1", 0, 0, True, None, date(2026, 9, 1)),
    agg_store.UnitRow(B, "RS", "Nis-1", 0, 0, True, None, date(2026, 9, 1)),
    agg_store.UnitRow(C, "TR", "Izmir-1", 0, 0, True, None, date(2026, 9, 1)),
)
ЗАГРУЗКА = datetime(2026, 10, 1, 12, tzinfo=UTC)


@pytest.fixture
def база(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    состояние: dict[str, Any] = {"охват": None, "сегодня": date(2026, 10, 15)}

    def реестр(countries: Any = None) -> tuple[Any, ...]:
        return tuple(u for u in РЕЕСТР if countries is None or u.country in countries)

    class _Дата(date):
        @classmethod
        def today(cls) -> date:
            return состояние["сегодня"]

    monkeypatch.setattr(tool, "date", _Дата)
    monkeypatch.setattr(agg_store, "units", реестр)
    monkeypatch.setattr(dodois_metrics, "unit_sales", lambda c, m: ПРОДАЖИ.get((c, m), []))
    monkeypatch.setattr(
        dodois_metrics,
        "unit_aggregator_orders",
        lambda c, m: [UnitAggregatorOrders(C, "Wolt", 7, None)] if (c, m) == ("TR", МЕСЯЦ) else [],
    )
    monkeypatch.setattr(
        dodois_metrics,
        "kind_loads",
        lambda: [
            KindLoad("RS", "sales", ЗАГРУЗКА, 5, ЗАГРУЗКА, True, None),
            KindLoad("RS", "kr", None, None, None, None, None),
        ],
    )
    monkeypatch.setattr(tool, "reach_of", lambda tenant: Reach(tenant, None, состояние["охват"]))
    return состояние


def _страна(ответ: dict[str, Any], код: str) -> dict[str, Any]:
    return next(c for c in ответ["countries"] if c["country"] == код)


def test_суммы_средний_чек_доли_и_каналы_страны(база: Any) -> None:
    ответ = tool.sales_summary(tenant="HQ", country="RS", month="2026-09")

    сербия = _страна(ответ, "RS")
    assert сербия["currency"] == "RSD"
    assert сербия["units_with_data"] == 2
    assert сербия["revenue"] == 12000.0
    assert сербия["orders"] == 100
    assert сербия["avg_check"] == 120.0  # 12000 / 100
    assert сербия["revenue_dine_in"] == 1000.0
    assert сербия["revenue_delivery"] == 9000.0  # 3000 + 6000 + 0; самовывоз 2000 не в доставке
    # агрегаторы 30, приложение и сайт 20 + 40, прочее (Dine-in, Phone) 10 + 0 — из 100
    assert сербия["orders_share"] == {"aggregators": 30.0, "app_site": 60.0, "other": 10.0}
    assert сербия["loaded_at"] == ЗАГРУЗКА.isoformat()
    assert ответ["month"] == "2026-09" and ответ["month_open"] is False


def test_дельты_к_прошлому_месяцу_и_году(база: Any) -> None:
    сербия = _страна(tool.sales_summary(tenant="HQ", country="RS", month="2026-09"), "RS")

    assert сербия["prev_month"] == {
        "month": "2026-08-01", "revenue": 4000.0, "orders": 50, "avg_check": 80.0,
        "revenue_delta_pct": 200.0, "orders_delta_pct": 100.0,
    }  # fmt: skip
    год = сербия["same_month_last_year"]
    assert год["revenue"] == 8000.0 and год["revenue_delta_pct"] == 50.0
    assert год["orders_delta_pct"] == -50.0  # 100 против 200


def test_нет_сравниваемого_месяца_в_базе_даёт_null(база: Any) -> None:
    турция = _страна(tool.sales_summary(tenant="HQ", month="2026-09"), "TR")

    assert турция["prev_month"] is None and турция["same_month_last_year"] is None


def test_идущий_месяц_не_сравнивается_с_полным(база: Any) -> None:
    база["сегодня"] = date(2026, 9, 20)

    ответ = tool.sales_summary(tenant="HQ", country="RS", by_unit=True)  # месяц не задан

    assert ответ["month"] == "2026-09" and ответ["month_open"] is True
    сербия = _страна(ответ, "RS")
    assert сербия["prev_month"] is None and сербия["same_month_last_year"] is None
    assert сербия["revenue"] == 12000.0  # сами числа месяца отдаются
    assert all(u["revenue_delta_pct"] is None and u["prev_month_revenue"] is None
               for u in ответ["units"])  # fmt: skip
    assert "неполные" in ответ["note"]


def test_валюты_не_складываются_заказы_по_сети_складываются(база: Any) -> None:
    ответ = tool.sales_summary(tenant="HQ", month="2026-09")

    assert {c["country"]: c["currency"] for c in ответ["countries"]} == {"RS": "RSD", "TR": "TRY"}
    assert "revenue" not in ответ and "network_revenue" not in ответ
    # RS 100 заказов + TR: заказов агрегаторов в продажах 5 (свой счёт 7 не нужен)
    assert ответ["network_orders"] == 105
    assert "не складывается" in ответ["note"]


def test_счёт_агрегаторов_берётся_отдельно_если_в_продажах_их_нет(база: Any) -> None:
    ПРОДАЖИ[("TR", МЕСЯЦ)] = [_р(C, "Website", "Delivery", 5, "500", "TRY")]
    try:
        турция = _страна(tool.sales_summary(tenant="HQ", country="TR", month="2026-09"), "TR")
    finally:
        ПРОДАЖИ[("TR", МЕСЯЦ)] = [_р(C, "Aggregator", "Delivery", 5, "500", "TRY")]

    assert турция["orders"] == 12  # 5 сайта + 7 агрегаторов по их счёту, как на экране
    assert турция["orders_share"]["aggregators"] == round(7 / 12 * 100, 2)


def test_пиццерии_по_выручке_убыв_и_обрезка(база: Any) -> None:
    ответ = tool.sales_summary(tenant="HQ", country="RS", month="2026-09", by_unit=True)

    assert [u["name"] for u in ответ["units"]] == ["Beograd-1", "Nis-1"]
    первая = ответ["units"][0]
    assert первая["revenue"] == 10000.0 and первая["orders"] == 60
    assert первая["avg_check"] == round(10000 / 60, 2)
    assert первая["prev_month_revenue"] == 4000.0 and первая["revenue_delta_pct"] == 150.0
    assert ответ["units"][1]["prev_month_revenue"] is None  # в прошлом месяце не было строк

    страница = tool.sales_summary(tenant="HQ", month="2026-09", by_unit=True, limit=2)
    assert страница["returned"] == 2 and страница["total_units"] == 3
    assert страница["truncated"] is True
    assert [u["country"] for u in страница["units"]] == ["RS", "RS"]


def test_без_by_unit_списка_пиццерий_нет(база: Any) -> None:
    assert "units" not in tool.sales_summary(tenant="HQ", month="2026-09")


def test_партнёр_видит_только_свою_страну(база: Any) -> None:
    база["охват"] = ("RS",)

    ответ = tool.sales_summary(tenant="RS-SPACE", month="2026-09", by_unit=True)

    assert [c["country"] for c in ответ["countries"]] == ["RS"]
    assert ответ["network_orders"] == 100
    assert "TR" not in str(ответ) and "Izmir" not in str(ответ)


def test_чужая_страна_отказ_тот_же_что_у_неизвестной(база: Any) -> None:
    база["охват"] = ("RS",)

    with pytest.raises(ToolError) as чужая:
        tool.sales_summary(tenant="X", country="TR")
    with pytest.raises(ToolError) as неизвестная:
        tool.sales_summary(tenant="X", country="ZZ")

    assert str(чужая.value).replace("TR", "ZZ") == str(неизвестная.value)
    assert "Доступно: RS" in str(чужая.value) and "TR," not in str(чужая.value)


def test_партнёр_без_стран_получает_отказ_без_чтения_продаж(
    база: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    база["охват"] = ()
    monkeypatch.setattr(
        dodois_metrics, "unit_sales", lambda *_: pytest.fail("продажи читались без охвата")
    )

    assert tool.sales_summary(tenant="X")["status"] == "no_countries"


@pytest.mark.parametrize("плохой", ["сентябрь", "2026-9", "2026-13", "2026-00", "09-2026", ""])
def test_кривой_месяц_отказ_с_примером(база: Any, плохой: str) -> None:
    with pytest.raises(ToolError, match=r"ГГГГ-ММ, например 2026-09"):
        tool.sales_summary(tenant="HQ", month=плохой)


@pytest.mark.parametrize("плохая", ["rs", "SRB", "R", "1S"])
def test_кривой_код_страны_отказ(база: Any, плохая: str) -> None:
    with pytest.raises(ToolError, match="две заглавные"):
        tool.sales_summary(tenant="HQ", country=плохая)


@pytest.mark.parametrize("предел", [0, 201, -1])
def test_предел_вне_границ_отказ(база: Any, предел: int) -> None:
    with pytest.raises(ToolError, match="от 1 до 200"):
        tool.sales_summary(tenant="HQ", limit=предел)


def test_месяц_без_продаж_отвечает_no_data_а_не_нулями(база: Any) -> None:
    ответ = tool.sales_summary(tenant="HQ", month="2024-01")

    assert ответ["status"] == "no_data" and "message" in ответ
    assert all(c["revenue"] is None and c["avg_check"] is None for c in ответ["countries"])


def test_инструмент_в_каталоге_и_вызов_через_rpc(база: Any) -> None:
    spec = find("sales_summary")
    assert spec is not None and spec.kind == KIND_RATINGS_READ
    assert spec.input_schema["additionalProperties"] is False

    ответ = handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "sales_summary",
                "arguments": {"country": "RS", "month": "2026-09"},
            },
        },
        tenant="HQ",
        checklist=None,
        source=None,
        may_retract=False,
        actor="x",
        role="admin",
    )

    assert ответ is not None and not ответ["result"].get("isError")
    assert '"revenue": 12000.0' in str(ответ["result"]["content"][0]["text"])
