"""Glovo: точки новым пиццериям находятся сами, привязка по ссылке (D424, #648).

Чистые решения — какую известную точку брать, принять ли ответ, пустить ли
адрес, как читается страница магазина, свежи ли данные — без сети и базы.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from src.db.agg_store import CoverageRow, PointRow, UnitRow
from src.ratings import coverage
from src.ratings.aggregators import glovo_link
from src.ratings.aggregators.base import AggregatorError
from src.ratings.maps_link import DodoUnit

ДЕНЬ = date(2026, 10, 12)
БУХАРЕСТ = (44.4268, 26.1025)
СЕЛО_БЛИЗКО = (44.45, 26.10)  # ~3 км от Бухареста
ПЛОЕШТИ = (44.94, 26.03)  # ~57 км


def _glovo(key: str, lat: float, lng: float, country: str = "RO", **extra: object) -> PointRow:
    base: dict[str, object] = {
        "store_id": 111, "city_code": "BUC", "country": country, "lat": lat, "lng": lng,
    }  # fmt: skip
    return PointRow(
        "glovo", key, country, "Dodo", None, None, None, "a" * 32, "B-1", None, base | extra
    )


def _unit(lat: float, lng: float, country: str = "RO", dodo_id: str = "b" * 32) -> DodoUnit:
    return DodoUnit(dodo_id, "Новая", lat, lng, country)


class _Http:
    """Подставной Glovo: на каждый запрос отдаёт заготовленный ответ."""

    def __init__(self, *answers: object) -> None:
        self.answers = list(answers)
        self.headers_seen: list[dict[str, str]] = []

    def get(self, url: str, headers: dict[str, str] | None = None) -> object:
        self.headers_seen.append(headers or {})
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def _ответ(address: int, value: float = 0.95) -> dict[str, object]:
    return {
        "addressId": address,
        "name": "Dodo Pizza",
        "ratingInfo": {"ratingValue": value, "ratingCount": 40},
    }


# --- какую известную точку брать -------------------------------------------


def test_берётся_ближайшая_точка_той_же_страны_в_пределах_40_км() -> None:
    далёкая = _glovo("1", *ПЛОЕШТИ)
    ближняя = _glovo("2", *СЕЛО_БЛИЗКО)
    чужая_страна = _glovo("3", *БУХАРЕСТ, country="BG")

    donor = glovo_link.choose_donor(_unit(*БУХАРЕСТ), [далёкая, чужая_страна, ближняя])

    assert donor is ближняя


def test_дальше_40_км_или_без_store_id_донора_нет() -> None:
    assert glovo_link.choose_donor(_unit(*БУХАРЕСТ), [_glovo("1", *ПЛОЕШТИ)]) is None
    без_магазина = _glovo("2", *СЕЛО_БЛИЗКО, store_id=None)
    без_города = _glovo("3", *СЕЛО_БЛИЗКО, city_code="")
    assert glovo_link.choose_donor(_unit(*БУХАРЕСТ), [без_магазина, без_города]) is None


def test_новая_точка_только_если_адреса_ещё_нет() -> None:
    assert glovo_link.accepts(306070, {"306069"})
    assert not glovo_link.accepts(306069, {"306069"})
    assert not glovo_link.accepts(None, set())


# --- автопоиск целиком ------------------------------------------------------


def test_автопоиск_записывает_новую_точку_и_пропускает_занятую() -> None:
    известная = _glovo("306069", *БУХАРЕСТ)
    новая, покрытая = _unit(44.43, 26.11, dodo_id="c" * 32), _unit(44.42, 26.09, dodo_id="d" * 32)
    http: Any = _Http(_ответ(500001), _ответ(306069))

    points, ratings = glovo_link.discover(http, [новая, покрытая], [известная], {"306069"}, ДЕНЬ)

    assert [(p.point_key, p.dodo_id, p.link_distance_m) for p in points] == [
        ("500001", "c" * 32, None)
    ]
    assert (ratings[0].score, ratings[0].scale, ratings[0].on_date) == (95.0, 100, ДЕНЬ)
    # Запрос ушёл с координатами самой пиццерии, а не донора.
    assert http.headers_seen[0]["Glovo-Delivery-Location-Latitude"] == "44.43"
    assert http.headers_seen[0]["Glovo-Location-City-Code"] == "BUC"


def test_автопоиск_ошибка_одной_пиццерии_не_валит_остальные() -> None:
    известная = _glovo("306069", *БУХАРЕСТ)
    первая, вторая = _unit(44.43, 26.11, dodo_id="c" * 32), _unit(44.42, 26.09, dodo_id="d" * 32)
    http: Any = _Http(AggregatorError("HTTP 404"), _ответ(500002))

    points, _ = glovo_link.discover(http, [первая, вторая], [известная], set(), ДЕНЬ)

    assert [p.dodo_id for p in points] == ["d" * 32]


def test_автопоиск_не_трогает_закрытых_привязанных_и_чужие_страны() -> None:
    известная = _glovo("306069", *БУХАРЕСТ)
    закрытая = DodoUnit("c" * 32, "Закрыта", 44.43, 26.11, "RO", working=False)
    привязанная = _unit(44.43, 26.11, dodo_id="a" * 32)  # её код уже у известной точки
    в_болгарии = _unit(42.7, 23.3, country="BG", dodo_id="e" * 32)
    http: Any = _Http()

    result = glovo_link.discover(
        http, [закрытая, привязанная, в_болгарии], [известная], set(), ДЕНЬ
    )

    assert result == ([], [])


# --- адрес страницы: Glovo и только Glovo -----------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://glovoapp.com/en/ro/bucharest/stores/dodo-pizza-buc",
        "https://glovoapp.com/ro/ro/bucharest/stores/dodo-pizza-buc/",
        "https://glovoapp.com/pt-br/ng/lagos/stores/dodo-pizza-lag?utm=x#top",
        "  https://glovoapp.com/en/ge/tbilisi/stores/dodo-pizza  ",
    ],
)
def test_ссылка_на_магазин_принимается_и_страна_берётся_из_пути(url: str) -> None:
    parsed = glovo_link.parse_store_url(url)

    assert parsed is not None
    assert parsed[0] in {"RO", "NG", "GE"}
    assert parsed[1].startswith("https://glovoapp.com/")
    assert "?" not in parsed[1] and "#" not in parsed[1]


@pytest.mark.parametrize(
    "url",
    [
        "http://glovoapp.com/en/ro/bucharest/stores/dodo",  # не https
        "https://evil.example/en/ro/bucharest/stores/dodo",  # чужой хост
        "https://glovoapp.com.evil.example/en/ro/bucharest/stores/dodo",  # хост-двойник
        "https://evilglovoapp.com/en/ro/bucharest/stores/dodo",
        "https://www.glovoapp.com/en/ro/bucharest/stores/dodo",  # поддомен — не наш хост
        "https://glovoapp.com@evil.example/en/ro/bucharest/stores/dodo",  # логин вместо хоста
        "https://user:pw@glovoapp.com/en/ro/bucharest/stores/dodo",
        "https://glovoapp.com:8443/en/ro/bucharest/stores/dodo",
        "https://glovoapp.com/en/ro/bucharest/dodo",  # нет /stores/
        "https://glovoapp.com/en/ro/stores/dodo",  # нет города
        "https://glovoapp.com/en/ro/bucharest/stores/",  # нет магазина
        "https://glovoapp.com/en/ro/bucharest/stores/../../admin",  # обход пути
        "https://glovoapp.com//evil.example/en/ro/bucharest/stores/dodo",
        "ftp://glovoapp.com/en/ro/bucharest/stores/dodo",
        "glovoapp.com/en/ro/bucharest/stores/dodo",
        "",
    ],
)
def test_чужой_адрес_и_кривой_путь_отвергаются(url: str) -> None:
    assert glovo_link.parse_store_url(url) is None


# --- страница магазина ------------------------------------------------------

_СТРАНИЦА = (
    '<html><script id="__NEXT_DATA__">{"props":{"city":{"cityCode":"SZR","name":"Stara Zagora"},'
    '"api":"https://api.glovoapp.com/v4/stores/776055/addresses/1020934/rating"}}</script></html>'
)


def test_со_страницы_читаются_id_магазина_и_код_города() -> None:
    assert glovo_link.store_from_page(_СТРАНИЦА) == ("776055", "SZR")
    # Тот же код внутри строки JSON, с экранированными кавычками.
    экранировано = _СТРАНИЦА.replace('"cityCode":"SZR"', '\\"cityCode\\":\\"SZR\\"')
    assert glovo_link.store_from_page(экранировано) == ("776055", "SZR")


def test_страница_без_данных_магазина_это_ошибка() -> None:
    with pytest.raises(AggregatorError):
        glovo_link.store_from_page("<html>Access denied</html>")
    with pytest.raises(AggregatorError):
        glovo_link.store_from_page('<html>"cityCode":"SZR"</html>')


# --- привязка по ссылке целиком ---------------------------------------------

_URL = "https://glovoapp.com/en/bg/stara-zagora/stores/dodo-pizza-szr"


def test_привязка_по_ссылке_пишет_точку_и_не_ходит_на_чужие_адреса() -> None:
    unit = _unit(42.43, 25.64, country="BG")
    открыто: list[str] = []

    def страница(url: str) -> str:
        открыто.append(url)
        return _СТРАНИЦА

    http: Any = _Http(_ответ(1020934, 0.9))
    итог, point, rating = glovo_link.link_by_url(unit, _URL, set(), ДЕНЬ, http=http, page=страница)

    assert (итог.code, итог.point_key) == ("ok", "1020934")
    assert point is not None
    assert (point.extra["store_id"], point.extra["city_code"]) == ("776055", "SZR")
    assert rating is not None and rating.score == 90.0
    assert открыто == [_URL]

    чужой = "https://evil.example/en/bg/x/stores/y"
    итог, point, _ = glovo_link.link_by_url(unit, чужой, set(), ДЕНЬ, page=страница)
    assert (итог.code, point) == ("bad_url", None)
    assert len(открыто) == 1  # на чужой адрес сервер не ходил


def test_привязка_отказывает_словами_кода() -> None:
    unit = _unit(42.43, 25.64, country="BG")

    def ok_page(_: str) -> str:
        return _СТРАНИЦА

    def упала(_: str) -> str:
        raise AggregatorError("нет сети")

    def code(
        u: Any, *, taken: set[str] | None = None, http: Any = None, page: Any = ok_page
    ) -> str:
        return glovo_link.link_by_url(u, _URL, taken or set(), ДЕНЬ, http=http, page=page)[0].code

    assert code(None) == "unknown_unit"
    assert code(_unit(44.4, 26.1)) == "country_mismatch"  # страна в ссылке не та
    assert code(unit, taken={"1020934"}, http=_Http(_ответ(1020934))) == "taken"
    assert code(unit, page=упала) == "page_failed"
    assert code(unit, page=lambda _: "<html/>") == "no_store"
    assert code(unit, http=_Http(AggregatorError("HTTP 404"))) == "glovo_failed"


# --- свежесть и охват -------------------------------------------------------


def test_данные_старше_недели_устарели_неделя_ровно_ещё_свежа() -> None:
    assert not coverage.is_stale(date(2026, 10, 5), ДЕНЬ)  # 7 дней
    assert coverage.is_stale(date(2026, 10, 4), ДЕНЬ)  # 8 дней
    assert not coverage.is_stale(None, ДЕНЬ)


def _юнит(
    dodo_id: str, country: str, first_seen: date | None = None, working: bool = True
) -> UnitRow:
    return UnitRow(dodo_id, country, f"Пиццерия {dodo_id[0]}", 1.0, 1.0, working, first_seen, ДЕНЬ)


def test_охват_ячейки_счётчики_и_колонки_по_странам() -> None:
    а, б, в = "a" * 32, "b" * 32, "c" * 32
    units = [
        _юнит(а, "RO", first_seen=date(2026, 10, 1)),  # новая
        _юнит(б, "RO", first_seen=None),  # была с самого начала
        _юнит(в, "PL"),
        _юнит("d" * 32, "RO", working=False),  # закрыта — в таблицу не идёт
    ]
    linked = [
        CoverageRow("glovo", а, "RO", 95.0, 100, date(2026, 10, 1)),  # старше недели
        CoverageRow("wolt", а, "RO", 9.2, 10, ДЕНЬ),
        CoverageRow("wolt", в, "PL", None, None, None),  # точка есть, оценок нет
    ]
    agg = {"wolt": {"RO", "PL"}, "glovo": {"RO"}, "pyszne_pl": {"PL"}}

    result = coverage.build(units, [("2", {а: (4.6, ДЕНЬ)})], linked, agg, ДЕНЬ)

    assert [p.key for p in result.platforms] == ["2", "wolt", "glovo", "pyszne_pl"]
    assert len(result.rows) == 3 and result.new == 1
    ячейки = {r.unit.dodo_id: r.cells for r in result.rows}
    assert ячейки[а]["glovo"].stale
    assert not ячейки[а]["wolt"].stale and not ячейки[а]["2"].stale
    assert ячейки[б]["glovo"].state == coverage.MISSING
    assert ячейки[б]["wolt"].state == coverage.MISSING
    assert ячейки[в]["glovo"].state == coverage.ABSENT  # Glovo в Польше не ожидается
    assert ячейки[в]["wolt"].state == coverage.UNRATED
    # Без точки на агрегаторе: б (нет Wolt и Glovo) и в (нет Pyszne); а — везде.
    assert result.unlinked == 2

    только_польша = coverage.build(units, [], linked, agg, ДЕНЬ, country="PL")
    assert [p.key for p in только_польша.platforms] == ["wolt", "pyszne_pl"]
    assert len(только_польша.rows) == 1
