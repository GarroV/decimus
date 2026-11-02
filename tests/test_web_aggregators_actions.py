"""Ручные решения по охвату агрегаторов (D700): «Нет на площадке», «Привязать», «Отвязать».

Права и заслон происхождения — те же, что у привязки Glovo по ссылке; действие
пишет в справочник от имени вошедшего. Страница настоящая, база подменена словарём.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any

import pytest
from flask.testing import FlaskClient
from web_harness import войти, подменить_двери, собрать

from src.db import agg_store, ratings_read
from src.db.errors import RatingsError

TODAY = date(2026, 11, 2)
NOW = datetime(2026, 11, 2, tzinfo=UTC)
ORIGIN = {"Origin": "http://localhost"}
NG = ratings_read.CountryRow("NG", "Нигерия", "Nigeria", None, True)
ABUJA, LAGOS, LAGOS2 = "a" * 32, "b" * 32, "c" * 32
URL = "/ratings/aggregators"


def _unit(key: str, name: str, country: str = "NG", lat: float = 9.0) -> agg_store.UnitRow:
    return agg_store.UnitRow(key, country, name, lat, 7.4, True, None, TODAY)


@pytest.fixture
def base(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Справочник в памяти: что записали действия и что отдаст экран."""
    state: dict[str, Any] = {
        "units": [_unit(ABUJA, "Abuja-1"), _unit(LAGOS, "Lagos-7", lat=6.5), _unit(LAGOS2, "L-9")],
        "absent": set(),
        "links": [],
        "open": [],
        "pinned": [],
        "marked": [],
        "unmarked": [],
        "unpinned": [],
    }

    def mark(aggregator: str, dodo_id: str, *, by: str) -> None:
        state["marked"].append((aggregator, dodo_id, by))
        state["absent"].add((aggregator, dodo_id))

    def unmark(aggregator: str, dodo_id: str) -> None:
        state["unmarked"].append((aggregator, dodo_id))
        state["absent"].discard((aggregator, dodo_id))

    def pin(*args: Any, by: str) -> bool:
        state["pinned"].append((*args, by))
        return True

    monkeypatch.setattr(ratings_read, "countries", lambda: (NG,))
    monkeypatch.setattr(agg_store, "units", lambda codes=None: tuple(state["units"]))
    monkeypatch.setattr(agg_store, "coverage", lambda: ())
    monkeypatch.setattr(agg_store, "load_states", lambda: ())
    monkeypatch.setattr(agg_store, "unmatched_counts", lambda: ())
    # В Нигерии у Glovo и Wolt есть точки; остальные площадки там не ожидаются.
    monkeypatch.setattr(
        agg_store,
        "point_countries",
        lambda key: frozenset({"NG"}) if key in ("glovo", "wolt") else frozenset(),
    )
    monkeypatch.setattr(agg_store, "unit_absent", lambda: frozenset(state["absent"]))
    monkeypatch.setattr(agg_store, "open_points", lambda: tuple(state["open"]))
    monkeypatch.setattr(agg_store, "point_links", lambda aggregator=None: tuple(state["links"]))
    monkeypatch.setattr(agg_store, "mark_absent", mark)
    monkeypatch.setattr(agg_store, "unmark_absent", unmark)
    monkeypatch.setattr(agg_store, "pin_link", pin)
    monkeypatch.setattr(
        agg_store, "unpin_link", lambda aggregator, key: state["unpinned"].append((aggregator, key))
    )
    return state


def clients(monkeypatch: pytest.MonkeyPatch, tenant: str, role: str) -> Iterator[FlaskClient]:
    подменить_двери(monkeypatch, tenant=tenant, role=role)
    with собрать(tenant=tenant).test_client() as client:
        assert войти(client).status_code == 302
        yield client


def page(client: FlaskClient) -> str:
    return client.get("/administration?tab=aggregators&country=NG").get_data(as_text=True)


def platform(html: str, name: str) -> str:
    """Блок одной площадки на экране страны."""
    sections = html.split('<section class="ssec">')[1:]
    return next(block for block in sections if f">{name}</h2>" in block)


def test_у_площадки_без_поиска_пробел_с_кнопкой_а_у_поисковой_нет_на_площадке_без_кнопки(
    monkeypatch: pytest.MonkeyPatch, base: dict[str, Any]
) -> None:
    for client in clients(monkeypatch, "HQ", "control"):
        html = page(client)

    glovo, wolt = platform(html, "Glovo"), platform(html, "Wolt")
    assert "Abuja-1 — нет привязки" in glovo
    assert glovo.count('action="/ratings/aggregators/absent"') == 3  # по пиццерии
    assert "Abuja-1 — нет на площадке" in wolt and "К сведению" in wolt
    assert "нет привязки" not in wolt and "/absent" not in wolt


def test_отмеченная_строка_в_сведениях_со_снятием_а_не_в_пробелах(
    monkeypatch: pytest.MonkeyPatch, base: dict[str, Any]
) -> None:
    base["absent"].add(("glovo", ABUJA))
    for client in clients(monkeypatch, "HQ", "control"):
        html = page(client)

    glovo = platform(html, "Glovo")
    assert "Abuja-1 — нет на площадке (отмечено вручную)" in glovo
    assert 'action="/ratings/aggregators/present"' in glovo and "Снять отметку" in glovo
    assert "Abuja-1 — нет привязки" not in glovo


def test_кандидат_рядом_показан_с_названием_расстоянием_и_кнопкой_привязать(
    monkeypatch: pytest.MonkeyPatch, base: dict[str, Any]
) -> None:
    base["open"] = [
        agg_store.OpenPoint("wolt", "374489", "NG", "Dodo Abuja", "https://t/374489", 9.01, 7.4)
    ]
    for client in clients(monkeypatch, "HQ", "control"):
        html = page(client)

    wolt = platform(html, "Wolt")
    assert "Abuja-1 — кандидат рядом не привязан" in wolt
    assert "Dodo Abuja" in wolt and "https://t/374489" in wolt
    assert 'name="point_key" value="374489"' in wolt and "Привязать" in wolt


def test_закреплённая_привязка_видна_с_кнопкой_отвязать(
    monkeypatch: pytest.MonkeyPatch, base: dict[str, Any]
) -> None:
    base["links"] = [agg_store.PointLink("wolt", "374489", ABUJA)]
    for client in clients(monkeypatch, "HQ", "control"):
        html = page(client)

    wolt = platform(html, "Wolt")
    assert "Закреплённые привязки" in wolt and "374489" in wolt and "Отвязать" in wolt
    assert 'action="/ratings/aggregators/unpin"' in wolt


def post(client: FlaskClient, action: str, **form: str) -> Any:
    return client.post(f"{URL}/{action}", data=form, headers=ORIGIN)


def test_нет_на_площадке_пишет_отметку_от_имени_учётки_и_возвращает_на_страну(
    monkeypatch: pytest.MonkeyPatch, base: dict[str, Any]
) -> None:
    for client in clients(monkeypatch, "HQ", "admin"):
        reply = post(client, "absent", aggregator="glovo", dodo_id=ABUJA, country="NG")

    assert reply.status_code == 303
    assert reply.headers["Location"] == "/administration?tab=aggregators&country=NG"
    ((aggregator, dodo_id, by),) = base["marked"]
    assert (aggregator, dodo_id) == ("glovo", ABUJA) and by


def test_отметку_можно_снять(monkeypatch: pytest.MonkeyPatch, base: dict[str, Any]) -> None:
    for client in clients(monkeypatch, "HQ", "admin"):
        reply = post(client, "present", aggregator="glovo", dodo_id=ABUJA, country="NG")

    assert reply.status_code == 303 and base["unmarked"] == [("glovo", ABUJA)]


@pytest.mark.parametrize(
    "form",
    [
        {"aggregator": "wolt", "dodo_id": ABUJA},  # поисковую площадку отмечать нельзя
        {"aggregator": "nope", "dodo_id": ABUJA},
        {"aggregator": "glovo", "dodo_id": "d" * 32},  # нет такой пиццерии
        {"aggregator": "glovo", "dodo_id": "not-an-id"},
    ],
)
def test_отметка_не_по_адресу_отказ_без_записи(
    monkeypatch: pytest.MonkeyPatch, base: dict[str, Any], form: dict[str, str]
) -> None:
    for client in clients(monkeypatch, "HQ", "admin"):
        reply = post(client, "absent", country="NG", **form)

    assert reply.status_code == 303 and "result=failed" in reply.headers["Location"]
    assert base["marked"] == []


def test_привязать_записывает_пару_с_расстоянием(
    monkeypatch: pytest.MonkeyPatch, base: dict[str, Any]
) -> None:
    base["open"] = [agg_store.OpenPoint("trendyol_go", "374489", "NG", "D", None, 9.01, 7.4)]
    for client in clients(monkeypatch, "HQ", "control"):
        reply = post(client, "pin", aggregator="trendyol_go", dodo_id=ABUJA, point_key="374489")

    assert reply.status_code == 303 and "result" not in reply.headers["Location"]
    ((aggregator, key, dodo_id, name, metres, by),) = base["pinned"]
    assert (aggregator, key, dodo_id, name) == ("trendyol_go", "374489", ABUJA, "Abuja-1")
    assert 1000 < metres < 1200 and by  # 0,01° широты ≈ 1,1 км


def test_привязать_можно_только_непривязанную_точку_той_же_страны(
    monkeypatch: pytest.MonkeyPatch, base: dict[str, Any]
) -> None:
    base["open"] = [agg_store.OpenPoint("trendyol_go", "ge", "GE", "D", None, 9.0, 7.4)]
    for client in clients(monkeypatch, "HQ", "control"):
        foreign = post(client, "pin", aggregator="trendyol_go", dodo_id=ABUJA, point_key="ge")
        absent = post(client, "pin", aggregator="trendyol_go", dodo_id=ABUJA, point_key="zzz")

    assert "result=failed" in foreign.headers["Location"]
    assert "result=failed" in absent.headers["Location"]
    assert base["pinned"] == []


def test_отвязать_снимает_закрепление(
    monkeypatch: pytest.MonkeyPatch, base: dict[str, Any]
) -> None:
    for client in clients(monkeypatch, "HQ", "control"):
        reply = post(client, "unpin", aggregator="trendyol_go", point_key="374489", country="NG")

    assert reply.status_code == 303 and base["unpinned"] == [("trendyol_go", "374489")]


@pytest.mark.parametrize("action", ["absent", "present", "pin", "unpin"])
@pytest.mark.parametrize(
    ("tenant", "role"), [("GE", "admin"), ("HQ", "auditor"), ("HQ", "developer")]
)
def test_без_права_управлять_рейтингами_403_и_ничего_не_пишется(
    monkeypatch: pytest.MonkeyPatch, base: dict[str, Any], action: str, tenant: str, role: str
) -> None:
    for client in clients(monkeypatch, tenant, role):
        reply = post(client, action, aggregator="glovo", dodo_id=ABUJA, point_key="k")

    assert reply.status_code in (403, 404)
    assert not any(base[k] for k in ("marked", "unmarked", "pinned", "unpinned"))


@pytest.mark.parametrize("action", ["absent", "present", "pin", "unpin"])
def test_чужой_origin_отказ_и_ничего_не_пишется(
    monkeypatch: pytest.MonkeyPatch, base: dict[str, Any], action: str
) -> None:
    for client in clients(monkeypatch, "HQ", "admin"):
        reply = client.post(
            f"{URL}/{action}",
            data={"aggregator": "glovo", "dodo_id": ABUJA, "point_key": "k"},
            headers={"Origin": "https://evil.example"},
        )

    assert reply.status_code == 403
    assert not any(base[k] for k in ("marked", "unmarked", "pinned", "unpinned"))


def test_база_не_приняла_экран_говорит_об_этом(
    monkeypatch: pytest.MonkeyPatch, base: dict[str, Any]
) -> None:
    def refuse(*_a: Any, **_k: Any) -> None:
        raise RatingsError("база отказала")

    monkeypatch.setattr(agg_store, "mark_absent", refuse)
    for client in clients(monkeypatch, "HQ", "admin"):
        reply = post(client, "absent", aggregator="glovo", dodo_id=ABUJA, country="NG")
        html = client.get(reply.headers["Location"]).get_data(as_text=True)

    assert reply.status_code == 303 and "result=failed" in reply.headers["Location"]
    assert "Не получилось" in html
