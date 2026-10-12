"""Чтение рейтингов через Claude (D420): охват по токену и те же числа, что у экрана.

Ядро — охват: партнёр не должен увидеть чужие страны ни в сводке, ни в списке
пиццерий, ни в тексте отказа. Данные подменены на уровне базы (`ratings_read`,
`maps_store`, `agg_store`) так, как их отдавал бы SQL: строки только запрошенных
стран. Всё, что выше, — настоящие `report`, `summary` и обработчики.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pytest

from src.db import agg_store, maps_store
from src.db import ratings_read as read
from src.db.agg_store import LatestRating, UpdateRequest
from src.db.ratings_read import CountryRow
from src.db.reach import Reach
from src.mcp import ratings_read as tool
from src.mcp import ratings_tools
from src.mcp.catalogue import KIND_RATINGS, KIND_RATINGS_READ, find
from src.mcp.errors import ToolError
from src.mcp.rpc import RATINGS_CLOSED, handle
from src.ratings import report
from src.ratings.aggregators import queue
from src.ratings.summary import group_average

ПЕРИОД = {"period": "2026-09"}
СТРАНЫ = (
    CountryRow("BG", "Болгария", "Bulgaria", "Dev A", True, "CEE"),
    CountryRow("NG", "Нигерия", "Nigeria", "Dev B", True, "OTHER"),
    CountryRow("RS", "Сербия", "Serbia", "Dev A", True, "CEE"),
)
# (пиццерия, имя, страна, тип, период, начало, балл, конец)
СТРОКИ = (
    ("a1" * 16, "Beograd-1", "RS", "rs", 1, date(2026, 9, 1), 90.0, date(2026, 9, 15)),
    ("a1" * 16, "Beograd-1", "RS", "rs", 2, date(2026, 9, 16), 94.0, date(2026, 9, 30)),
    ("a1" * 16, "Beograd-1", "RS", "rko", 3, date(2026, 9, 7), 80.0, date(2026, 9, 13)),
    ("a2" * 16, "Nis-1", "RS", "rs", 1, date(2026, 9, 1), 70.0, date(2026, 9, 15)),
    ("b1" * 16, "Sofia-1", "BG", "rs", 1, date(2026, 9, 1), 60.0, date(2026, 9, 15)),
    ("c1" * 16, "Lagos-1", "NG", "rs", 1, date(2026, 9, 1), 50.0, date(2026, 9, 15)),
)


@pytest.fixture
def база(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Рейтинги в памяти; `вызовы` — сколько раз спросили оценки (охват «пусто» — ни разу)."""
    состояние: dict[str, Any] = {"вызовы": 0, "охват": None}

    def оценки(*, countries: Any, begin: date, end: date, period_ids: Any = ()) -> list[Any]:
        состояние["вызовы"] += 1
        return [r for r in СТРОКИ if r[2] in countries and r[7] >= begin and r[5] <= end]

    monkeypatch.setattr(read, "countries", lambda: СТРАНЫ)
    monkeypatch.setattr(read, "rs_periods", lambda: ())
    monkeypatch.setattr(read, "score_facts", оценки)
    monkeypatch.setattr(read, "last_loaded", lambda: {"rs": datetime(2026, 10, 1, tzinfo=UTC)})
    monkeypatch.setattr(read, "hard_rules", lambda: ())
    monkeypatch.setattr(
        read, "settings", lambda: {"top_threshold": 85.0, "risk_threshold": 85.0, "risk_periods": 3}
    )
    monkeypatch.setattr(read, "rko_violation_facts", lambda **_: ([], {}))
    monkeypatch.setattr(read, "rs_remark_facts", lambda **_: ([], {}))
    monkeypatch.setattr(read, "last_period_ids", lambda *_a, **_k: ())
    monkeypatch.setattr(
        maps_store,
        "unit_scores",
        lambda provider, *, until: {"a1" * 16: (4.7, 120), "b1" * 16: (4.1, 30)},
    )
    монеты = (
        LatestRating("RS", "wolt", "a1" * 16, 9.4, 10, 300, date(2026, 10, 11)),
        LatestRating("BG", "wolt", "b1" * 16, 8.0, 10, 40, date(2026, 10, 11)),
    )
    monkeypatch.setattr(
        agg_store,
        "latest",
        lambda countries, *, until=None: tuple(r for r in монеты if r.country_code in countries),
    )

    def охват(tenant: str) -> Reach:
        return Reach(tenant, None, состояние["охват"])

    monkeypatch.setattr(tool, "reach_of", охват)
    return состояние


def _партнёр(база: dict[str, Any], *страны: str) -> None:
    база["охват"] = tuple(страны)


def test_партнёр_видит_в_сводке_только_свою_страну(база: Any) -> None:
    _партнёр(база, "RS")

    ответ = tool.ratings_summary(tenant="RS-SPACE", **ПЕРИОД)

    assert [g["key"] for g in ответ["groups"]] == ["CEE", "OTHER"]
    assert [g["countries"] for g in ответ["groups"]] == [["RS"], []]
    # среднее CEE — по пиццериям Сербии: (92 + 70) / 2, без Болгарии (60)
    assert ответ["groups"][0]["rs"] == 81.0
    текст = str(ответ)
    assert "BG" not in текст and "NG" not in текст


def test_ук_видит_все_страны(база: Any) -> None:
    ответ = tool.ratings_summary(tenant="HQ", **ПЕРИОД)

    assert [g["countries"] for g in ответ["groups"]] == [["BG", "RS"], ["NG"]]
    assert ответ["groups"][0]["rs"] == (92.0 + 70.0 + 60.0) / 3


def test_партнёр_не_выведывает_чужую_страну_отказом(база: Any) -> None:
    _партнёр(база, "RS")

    with pytest.raises(ToolError) as отказ:
        tool.ratings_summary(tenant="X", group_by="country", value="BG", **ПЕРИОД)

    assert (
        "Доступно: RS" in str(отказ.value) and "BG" not in str(отказ.value).split("недоступно")[1]
    )


def test_партнёр_не_видит_чужую_страну_в_списке_пиццерий(база: Any) -> None:
    _партнёр(база, "RS")

    ответ = tool.ratings_units(tenant="X", **ПЕРИОД)

    assert {u["country"] for u in ответ["units"]} == {"RS"}
    assert "Sofia" not in str(ответ) and "Lagos" not in str(ответ)
    assert "wolt" in str(ответ) and 8.0 not in [
        a["score"] for u in ответ["units"] for a in u["aggregators"]
    ]


def test_ук_видит_все_пиццерии_и_у_каждой_свои_карта_и_агрегатор(база: Any) -> None:
    ответ = tool.ratings_units(tenant="HQ", **ПЕРИОД)

    по_имени = {u["name"]: u for u in ответ["units"]}
    assert set(по_имени) == {"Beograd-1", "Nis-1", "Sofia-1", "Lagos-1"}
    белград = по_имени["Beograd-1"]
    assert (белград["rs"], белград["rko"]) == (92.0, 80.0)
    assert белград["maps_google"] == {"score": 4.7, "reviews": 120}
    assert белград["aggregators"][0]["scale"] == 10
    assert по_имени["Nis-1"]["maps_google"] is None and по_имени["Nis-1"]["aggregators"] == []


def test_партнёр_без_стран_ничего_не_видит_и_базу_не_трогает(база: Any) -> None:
    _партнёр(база)

    сводка = tool.ratings_summary(tenant="X", **ПЕРИОД)
    список = tool.ratings_units(tenant="X", **ПЕРИОД)

    assert сводка["status"] == список["status"] == "no_countries"
    assert база["вызовы"] == 0  # охват «ничего» — до базы дело не доходит


def test_сводка_совпадает_с_экраном(база: Any) -> None:
    """Те же средние и те же дельты, что строит `report.build` для страницы."""
    for группа, значение in (("imf", None), ("developer", "Dev A"), ("country", "RS")):
        аргументы = {"group": группа, **({"value": значение} if значение else {}), **ПЕРИОД}
        выбор, _ = report.select(аргументы, today=date(2026, 10, 12))
        экран = report.build(выбор)

        ответ = tool.ratings_summary(tenant="HQ", group_by=группа, value=значение, period="2026-09")

        assert len(ответ["groups"]) == len(экран.groups)
        for строка, g in zip(ответ["groups"], экран.groups, strict=True):
            assert строка["rs"] == (None if g.rs is None else round(g.rs, 1))
            assert строка["rko"] == (None if g.rko is None else round(g.rko, 1))
            assert (строка["rs_delta"], строка["rko_delta"]) == (g.rs_delta, g.rko_delta)
            assert tuple(строка["countries"]) == g.countries


def test_среднее_группы_по_пиццериям_а_не_по_периодам(база: Any) -> None:
    """D353: пиццерия — среднее своих периодов, группа — среднее пиццерий."""
    факты = report.period_scores(report.select(ПЕРИОД, today=date(2026, 10, 12))[0], ("RS",))
    ответ = tool.ratings_summary(tenant="HQ", group_by="country", value="RS", **ПЕРИОД)

    assert ответ["groups"][0]["rs"] == round(group_average(факты, "rs", ["RS"]) or 0, 1) == 81.0


@pytest.mark.parametrize(
    "аргументы",
    [
        {"period": "сентябрь"},
        {"date_from": "2026-09-01"},
        {"date_from": "вчера", "date_to": "2026-09-30"},
        {"period": "2026-09", "date_from": "2026-09-01", "date_to": "2026-09-30"},
        {"group_by": "planet"},
        {"group_by": "developer"},
        {"group_by": "developer", "value": "Dev Z"},
        {"group_by": "country", "value": "ZZ"},
    ],
)
def test_неверный_отбор_отказ_а_не_молчаливая_замена(база: Any, аргументы: dict[str, str]) -> None:
    with pytest.raises(ToolError):
        tool.ratings_summary(tenant="HQ", **аргументы)


def test_в_ответе_стоит_выбранный_период_и_прошлый(база: Any) -> None:
    ответ = tool.ratings_summary(tenant="HQ", date_from="2026-09-01", date_to="2026-09-30")

    assert ответ["period"]["key"] == "2026-09" and ответ["period"]["end"] == "2026-09-30"
    assert ответ["previous_period"]["key"] == "2026-08"


def test_отбор_пиццерий_по_городу_имени_и_пределу(база: Any) -> None:
    assert [u["name"] for u in tool.ratings_units(tenant="HQ", city="grad", **ПЕРИОД)["units"]] == [
        "Beograd-1"
    ]
    assert tool.ratings_units(tenant="HQ", unit="a2" * 16, **ПЕРИОД)["units"][0]["name"] == "Nis-1"
    страница = tool.ratings_units(tenant="HQ", limit=2, **ПЕРИОД)
    assert (страница["total"], страница["returned"], страница["truncated"]) == (4, 2, True)
    with pytest.raises(ToolError):
        tool.ratings_units(tenant="HQ", limit=500, **ПЕРИОД)


# --- агрегаторы -------------------------------------------------------------


def _состояние(error: str | None) -> agg_store.LoadState:
    момент = datetime(2026, 10, 12, 3, 0, tzinfo=UTC)
    return agg_store.LoadState(
        "glovo", момент, "failed", 0, error, datetime(2026, 10, 11, tzinfo=UTC)
    )


def test_статус_агрегаторов_текст_ошибки_только_уК(
    база: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(agg_store, "load_states", lambda: (_состояние("HTTP 503"),))
    очередь = UpdateRequest(
        7, datetime(2026, 10, 12, 9, tzinfo=UTC), "anna", ("wolt",), None, None, None
    )
    monkeypatch.setattr(agg_store, "open_request", lambda: очередь)

    ук = tool.aggregators_status(tenant="HQ")
    партнёр = tool.aggregators_status(tenant="GE")

    glovo = next(a for a in ук["aggregators"] if a["aggregator"] == "glovo")
    assert glovo["outcome"] == "failed" and glovo["error"] == "HTTP 503" and glovo["scale"] == 100
    чужой = next(a for a in партнёр["aggregators"] if a["aggregator"] == "glovo")
    assert чужой["outcome"] == "failed" and чужой["error"] is None
    assert "HTTP 503" not in str(партнёр) and "anna" not in str(партнёр)
    assert ук["update_request"]["aggregators"] == ["wolt"]
    wolt = next(a for a in ук["aggregators"] if a["aggregator"] == "wolt")
    assert wolt["outcome"] == "never_run"


# --- вход: вид, заслон, заявка ----------------------------------------------


def _звать(имя: str, tenant: str, arguments: dict[str, Any], actor: str = "") -> dict[str, Any]:
    ответ = handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": имя, "arguments": arguments},
        },
        tenant=tenant,
        checklist=None,
        source=None,
        may_retract=False,
        actor=actor,
    )
    assert ответ is not None
    return ответ


def test_виды_инструментов() -> None:
    for имя in ("ratings_summary", "ratings_units", "aggregators_status"):
        spec = find(имя)
        assert spec is not None and spec.kind == KIND_RATINGS_READ
        assert spec.handler.__module__ == "src.mcp.ratings_read"
    spec = find("request_aggregators_update")
    assert spec is not None and spec.kind == KIND_RATINGS
    assert KIND_RATINGS_READ == "ratings_read"


def test_чтение_открыто_токену_партнёра_а_заявка_закрыта(
    база: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _партнёр(база, "RS")
    ответ = _звать("ratings_summary", "GE", dict(ПЕРИОД))
    assert "isError" not in ответ["result"] or not ответ["result"]["isError"]
    assert "Сербия" not in str(ответ) and '"RS"' in str(ответ)

    запросы: list[Any] = []
    monkeypatch.setattr(queue, "ask", lambda *a, **k: запросы.append((a, k)))
    закрыто = _звать("request_aggregators_update", "GE", {})
    assert RATINGS_CLOSED in str(закрыто) and запросы == []


class _Очередь:
    def __init__(self) -> None:
        self.открытая: UpdateRequest | None = None

    def поставить(self, names: Any, *, by: str) -> tuple[UpdateRequest, bool]:
        if self.открытая:
            return self.открытая, False
        self.открытая = UpdateRequest(
            1, datetime(2026, 10, 12, 9, tzinfo=UTC), by, tuple(names), None, None, None
        )
        return self.открытая, True


def test_заявка_пишет_автора_вызова_и_повтор_не_плодит(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    q = _Очередь()
    monkeypatch.setattr(agg_store, "request_update", q.поставить)

    первая = _звать(
        "request_aggregators_update", "HQ", {"aggregators": ["wolt"]}, actor="mcp:tg:42"
    )
    вторая = _звать("request_aggregators_update", "HQ", {}, actor="mcp:tg:99")

    assert "queued" in str(первая) and "mcp:tg:42" in str(первая)
    assert "already_queued" in str(вторая) and "уже в очереди" in str(вторая)
    assert q.открытая is not None and q.открытая.requested_by == "mcp:tg:42"


def test_заявка_с_незнакомым_агрегатором_отказ(monkeypatch: pytest.MonkeyPatch) -> None:
    q = _Очередь()
    monkeypatch.setattr(agg_store, "request_update", q.поставить)

    ответ = _звать("request_aggregators_update", "HQ", {"aggregators": ["foody"]})

    assert ответ["result"]["isError"] is True and "foody" in str(ответ) and q.открытая is None


def test_импорт_csv_по_прежнему_только_уК() -> None:
    with pytest.raises(ToolError):
        ratings_tools.import_ratings(tenant="GE", kind="snapshot", content="{}")
