"""Суточный сбор данных Dodo IS для «Качества» (D671): порядок, окна, отказ по доступу, журнал.

Сеть (`client.api_get`, `client.working_pizzerias`) и база (`dodois_metrics_store`, входы) подменены
двойниками: настоящих запросов и записей нет. Живой формат ответов продаж и заказов не сверен —
это проверка порядка и сумм, а не формата.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from src.db import dodois_logins as logins
from src.db import dodois_metrics_store as store
from src.dodois import client, metrics
from src.dodois.client import DodoisError, Response
from src.domain import dodois as rules
from src.domain import dodois_metrics as parse

А = "000d3a240c719a8711e68aba13f7f862"
Б = "000d3a240c719a8711e68aba13f7fc8a"
СЕГОДНЯ = date(2026, 10, 28)
СЕЙЧАС = datetime(2026, 10, 28, 3, 0, tzinfo=UTC)
ДОСТУП = "access-ZZZZ-secret"


def _вход(state: str = rules.OK) -> rules.Login:
    return rules.Login(
        country="BG",
        contour="intl",
        source="invite",
        issued_by="o",
        account_name=None,
        account_email=None,
        linked_at=СЕЙЧАС,
        scope="shared sales",
        units_total=2,
        units_open=2,
        refreshed_at=None,
        access_expires_at=None,
        checked_at=None,
        state=state,
        reason=None,
    )


class Мир:
    """Двойник Dodo IS и базы: что запрошено, что записано."""

    def __init__(self) -> None:
        self.запросы: list[tuple[str, dict[str, str]]] = []
        self.ответ: Any = None  # функция (path, query) -> Response
        self.продажи: list[tuple[date, list[str], list[parse.SalesRow]]] = []
        self.агрегаторы: list[tuple[date, list[str], list[parse.AggregatorMonth]]] = []
        self.оценки: list[tuple[date, list[str], list[parse.KrRow]]] = []
        self.журнал: list[tuple[int | None, bool, int, str | None]] = []
        self.удачных: dict[str, bool] = {}
        self.последняя: dict[str, datetime | None] = {}


@pytest.fixture
def мир(monkeypatch: pytest.MonkeyPatch) -> Мир:
    w = Мир()

    def api_get(contour: str, path: str, query: Any, token: str, **_: Any) -> Response:
        assert token == ДОСТУП
        w.запросы.append((path, dict(query)))
        return w.ответ(path, dict(query))

    monkeypatch.setattr(client, "api_get", api_get)
    monkeypatch.setattr(client, "working_pizzerias", lambda country: [А, Б])
    monkeypatch.setattr(logins, "read_tokens", lambda country: logins.Tokens(ДОСТУП, "r"))
    monkeypatch.setattr(store, "country_units", lambda country: [А])
    monkeypatch.setattr(store, "start_load", lambda country, kind: 1)
    monkeypatch.setattr(
        store,
        "finish_load",
        lambda i, *, ok, rows=0, error=None: w.журнал.append((i, ok, rows, error)),
    )
    monkeypatch.setattr(store, "has_ok_load", lambda country, kind: w.удачных.get(kind, False))
    monkeypatch.setattr(store, "last_ok_at", lambda country, kind: w.последняя.get(kind))
    monkeypatch.setattr(
        store,
        "replace_sales",
        lambda month, units, rows: w.продажи.append((month, list(units), list(rows))) or len(rows),
    )
    monkeypatch.setattr(
        store,
        "replace_aggregators",
        lambda month, units, rows: (
            w.агрегаторы.append((month, list(units), list(rows))) or len(rows)
        ),
    )
    monkeypatch.setattr(
        store,
        "replace_kr",
        lambda month, units, rows: w.оценки.append((month, list(units), list(rows))) or len(rows),
    )
    return w


def _ок(тело: Any) -> Response:
    return Response(200, {}, тело)


def _нет_доступа() -> Response:
    return Response(403, {}, {"code": "NoAccessToUnit"})


def _без_сна(_: float) -> None:
    return None


def test_продажи_месяца_складываются_по_окнам_и_заменяют_месяц_целиком(мир: Мир) -> None:
    мир.удачных[parse.KIND_SALES] = True  # не первая загрузка: прошлый и текущий месяцы

    def ответ(path: str, query: dict[str, str]) -> Response:
        строка = {
            "unitId": А,
            "orderSource": "Website",
            "salesChannel": "Delivery",
            "ordersCount": 2,
            "sales": 10,
        }
        return _ок({"result": [строка]})

    мир.ответ = ответ

    исходы = metrics.collect_country(_вход(), [parse.KIND_SALES], today=СЕГОДНЯ, sleep=_без_сна)

    assert [o.ok for o in исходы] == [True]
    сентябрь = next(p for p in мир.продажи if p[0] == date(2026, 9, 1))
    # Сентябрь — 30 дней, окна по 7: 5 окон; каждое дало 2 заказа на 10.
    assert сентябрь[2][0].orders == 10
    assert str(сентябрь[2][0].revenue) == "50"
    assert сентябрь[1] == [А, Б]  # заменяется месяц обеих пиццерий, ответивших в заход
    assert мир.журнал[-1][1:] == (True, 2, None)


def test_пиццерия_без_доступа_выделяется_делением_пачки_и_её_месяц_не_стирается(мир: Мир) -> None:
    мир.удачных[parse.KIND_KR] = True

    def ответ(path: str, query: dict[str, str]) -> Response:
        if Б in query["units"]:
            return _нет_доступа()
        return _ок(
            {
                "customerRatings": [
                    {
                        "unitId": А,
                        "avgDineInOrderRate": 4.5,
                        "avgDeliveryOrderRate": 4,
                        "dineInRateCount": 3,
                        "deliveryRateCount": 2,
                    }
                ]
            }
        )

    мир.ответ = ответ

    исходы = metrics.collect_country(_вход(), [parse.KIND_KR], today=СЕГОДНЯ, sleep=_без_сна)

    assert исходы[0].ok
    месяц, заменены, _ = мир.оценки[0]
    assert заменены == [А]  # Б без доступа: его прежние строки остаются
    assert месяц == date(2026, 10, 1)


def test_заказы_агрегаторов_листаются_постранично_до_конца_выдачи(мир: Мир) -> None:
    мир.удачных[parse.KIND_AGGREGATORS] = True
    страницы = iter(
        [
            {
                "sales": [{"unitId": А, "aggregatorName": "Glovo", }],
                "isEndOfListReached": False,
            },
            {
                "sales": [{"unitId": А, "aggregatorName": "Glovo", }],
                "isEndOfListReached": True,
            },
        ]
    )

    def ответ(path: str, query: dict[str, str]) -> Response:
        assert query["orderSource"] == "Aggregator"
        if int(query["skip"]) == 0 and query["from"].startswith("2026-09"):
            return _ок({"sales": [], "isEndOfListReached": True})
        return _ок(next(страницы, {"sales": [], "isEndOfListReached": True}))

    мир.ответ = ответ

    metrics.collect_country(_вход(), [parse.KIND_AGGREGATORS], today=СЕГОДНЯ, sleep=_без_сна)

    октябрь = next(p for p in мир.агрегаторы if p[0] == date(2026, 10, 1))
    assert [(r.aggregator, r.orders, r.revenue) for r in октябрь[2]] == [("Glovo", 2, None)]


def test_неизвестная_форма_ответа_пишется_неудачей_с_именами_ключей(мир: Мир) -> None:
    мир.ответ = lambda path, query: _ок({"result": [{"unitId": А, "итого": 5}]})

    исходы = metrics.collect_country(_вход(), [parse.KIND_SALES], today=СЕГОДНЯ, sleep=_без_сна)

    assert not исходы[0].ok
    assert исходы[0].error is not None
    assert исходы[0].error.startswith("unknown_shape")
    assert "итого" in исходы[0].error
    assert мир.продажи == []  # ничего не записано
    assert мир.журнал[-1][1] is False


def test_отказ_dodo_is_пишется_видом_отказа(мир: Мир) -> None:
    def ответ(path: str, query: dict[str, str]) -> Response:
        raise DodoisError("rate_limited")

    мир.ответ = ответ

    исходы = metrics.collect_country(_вход(), [parse.KIND_KR], today=СЕГОДНЯ, sleep=_без_сна)

    assert (исходы[0].ok, исходы[0].error) == (False, "rate_limited")


def test_первая_загрузка_берёт_историю_а_повторная_нет(мир: Мир) -> None:
    мир.ответ = lambda path, query: _ок({"customerRatings": []})

    metrics.collect_country(_вход(), [parse.KIND_KR], today=СЕГОДНЯ, sleep=_без_сна)
    первая = len(мир.оценки)
    мир.оценки.clear()
    мир.удачных[parse.KIND_KR] = True
    metrics.collect_country(_вход(), [parse.KIND_KR], today=СЕГОДНЯ, sleep=_без_сна)

    assert первая == 13
    assert len(мир.оценки) == 2


def test_вид_данных_свеж_сутки_и_после_них_снова_в_работе(мир: Мир) -> None:
    мир.последняя[parse.KIND_SALES] = СЕЙЧАС - timedelta(hours=5)
    мир.последняя[parse.KIND_KR] = СЕЙЧАС - timedelta(hours=21)

    assert metrics.due_kinds("BG", СЕЙЧАС) == [
        parse.KIND_AGGREGATORS,
        parse.KIND_KR,
        parse.KIND_RATINGS,
    ]


def test_страна_с_истёкшим_входом_пропускается(monkeypatch: pytest.MonkeyPatch, мир: Мир) -> None:
    monkeypatch.setattr(logins, "list_logins", lambda: (_вход(rules.EXPIRED),))

    assert metrics.run_pass(now=СЕЙЧАС, sleep=_без_сна) == []
    assert мир.запросы == []


def test_нет_ключей_входа_это_неудача_без_хождения_в_сеть(
    monkeypatch: pytest.MonkeyPatch, мир: Мир
) -> None:
    monkeypatch.setattr(logins, "read_tokens", lambda country: None)

    исходы = metrics.collect_country(_вход(), list(parse.KINDS), today=СЕГОДНЯ, sleep=_без_сна)

    assert {(o.ok, o.error) for o in исходы} == {(False, "no_tokens")}
    assert мир.запросы == []


def test_оценки_контроля_и_проверки_идут_без_префикса_страны_и_делят_пачку_по_доступу(
    мир: Мир, monkeypatch: pytest.MonkeyPatch
) -> None:
    мир.удачных[parse.KIND_RATINGS] = True
    записано: dict[str, Any] = {}

    def заменить_оценки(начало: date, конец: date, units: Any, rows: Any) -> int:
        записано["оценки"] = (начало, конец, list(units), list(rows))
        return len(rows)

    def заменить_проверки(начало: date, конец: date, units: Any, rows: Any) -> int:
        записано["проверки"] = list(rows)
        return len(rows)

    monkeypatch.setattr(store, "replace_rating_periods", заменить_оценки)
    monkeypatch.setattr(store, "replace_checkup_periods", заменить_проверки)

    def ответ(path: str, query: dict[str, str]) -> Response:
        assert path.startswith("/controlling/")  # без /dodopizza/<cc>
        if Б in query["units"]:
            return _нет_доступа()
        if path.endswith("/checkups"):
            проверка = {
                "id": "1",
                "unitId": А,
                "periodFrom": "2026-10-05",
                "periodTo": "2026-10-11",
                "ratingKind": "Standards",
                "status": "Completed",
            }
            return _ок({"checkups": [проверка], "isEndOfListReached": True})
        строка = {
            "unitId": А,
            "periodFrom": "2026-10-05",
            "periodTo": "2026-10-11",
            "rate": 90,
            "publishStatus": "Published",
        }
        return _ок({"unitRates": [строка], "isEndOfListReached": True})

    мир.ответ = ответ

    исходы = metrics.collect_country(_вход(), [parse.KIND_RATINGS], today=СЕГОДНЯ, sleep=_без_сна)

    assert исходы[0].ok
    начало, конец, заменены, рейтинги = записано["оценки"]
    assert (начало, конец) == (date(2026, 9, 1), СЕГОДНЯ)
    assert заменены == [А]  # пиццерия без доступа не стирается
    assert {r.kind for r in рейтинги} == {"rko", "rs"}
    assert [c.checkups for c in записано["проверки"]] == [1]  # из двух окон — одна проверка
