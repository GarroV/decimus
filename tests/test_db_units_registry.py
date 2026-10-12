"""Реестр пиццерий (`agg.units`, 0051) и экран «Пиццерии на площадках» (D424).

Реестр пишет роль приложения, как бот; экран открывается через настоящее
приложение с базой: охват, значок устаревших данных, привязка Glovo по ссылке.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest
from conftest import requires_db
from web_harness import войти, подменить_двери, собрать

pytest.importorskip("psycopg")

pytestmark = requires_db

СЕГОДНЯ = date.today()
ПЕРВЫЙ, ВТОРОЙ, ТРЕТИЙ = "a" * 32, "b" * 32, "c" * 32
ORIGIN = {"Origin": "http://localhost"}


def _unit(dodo_id: str, country: str = "RO", name: str = "Dodo", working: bool = True) -> Any:
    from src.ratings.maps_link import DodoUnit

    return DodoUnit(dodo_id, name, 44.4, 26.1, country, working)


def _first_seen(dsn: str) -> dict[str, date | None]:
    import psycopg

    with psycopg.connect(dsn) as conn:
        rows = conn.execute("select dodo_id, first_seen from agg.units").fetchall()
    return {r[0]: r[1] for r in rows}


def test_первое_заполнение_без_даты_новая_пиццерия_с_сегодняшней(db_env: str) -> None:
    from src.db import agg_store

    agg_store.save_units([_unit(ПЕРВЫЙ), _unit(ВТОРОЙ)], СЕГОДНЯ - timedelta(days=3))
    agg_store.save_units([_unit(ПЕРВЫЙ), _unit(ВТОРОЙ), _unit(ТРЕТИЙ)], СЕГОДНЯ)

    # Были при первом заполнении — «новыми» не числятся; пришедшая позже — с датой.
    assert _first_seen(db_env) == {ПЕРВЫЙ: None, ВТОРОЙ: None, ТРЕТИЙ: СЕГОДНЯ}


def test_известная_пиццерия_обновляется_а_first_seen_остаётся(db_env: str) -> None:
    from src.db import agg_store

    agg_store.save_units([_unit(ПЕРВЫЙ)], СЕГОДНЯ - timedelta(days=9))
    agg_store.save_units([_unit(ВТОРОЙ)], СЕГОДНЯ - timedelta(days=5))
    agg_store.save_units([_unit(ВТОРОЙ, name="Переименована", working=False)], СЕГОДНЯ)

    by_id = {u.dodo_id: u for u in agg_store.units()}
    assert by_id[ВТОРОЙ].first_seen == СЕГОДНЯ - timedelta(days=5)
    assert (by_id[ВТОРОЙ].name, by_id[ВТОРОЙ].working) == ("Переименована", False)
    assert by_id[ВТОРОЙ].last_seen == СЕГОДНЯ and by_id[ПЕРВЫЙ].last_seen == СЕГОДНЯ - timedelta(
        days=9
    )
    assert [u.dodo_id for u in agg_store.units(["RO"])] == [ПЕРВЫЙ, ВТОРОЙ]
    assert agg_store.units(["PL"]) == ()


def test_страны_imf_берутся_из_справочника_рейтингов(db_env: str) -> None:
    import psycopg

    from src.db import agg_store

    with psycopg.connect(db_env) as conn:
        conn.execute(
            "insert into ratings.countries (code, name_ru, name_en, is_imf) values "
            "('RS', 'Сербия', 'Serbia', true), ('XX', 'Не IMF', 'Not IMF', false)"
        )

    assert agg_store.imf_countries() == ("RS",)


def _наполнить() -> None:
    """Румыния: новая и старая пиццерии, у старой Glovo устарел; Wolt свежий."""
    from src.db import agg_store, maps_store
    from src.db.agg_store import PointRow, RatingRow
    from src.ratings import pointer

    agg_store.save_units([_unit(ВТОРОЙ, name="Старая")], СЕГОДНЯ - timedelta(days=40))
    agg_store.save_units([_unit(ПЕРВЫЙ, name="Новая")], СЕГОДНЯ - timedelta(days=2))

    def точка(agg: str, key: str, dodo: str, extra: dict[str, object]) -> PointRow:
        return PointRow(agg, key, "RO", "Dodo", None, 44.4, 26.1, dodo, "x", 10, extra)

    agg_store.save(
        [
            точка("wolt", "w-1", ВТОРОЙ, {}),
            точка("glovo", "306069", ВТОРОЙ, {"store_id": 1}),
            точка("wolt", "w-2", ПЕРВЫЙ, {}),
        ],
        [
            RatingRow("wolt", "w-1", СЕГОДНЯ, 9.24, 10, 120, True, True),
            RatingRow("glovo", "306069", СЕГОДНЯ - timedelta(days=9), 98.3, 100, 591, True, True),
            RatingRow("wolt", "w-2", СЕГОДНЯ, 8.5, 10, 4, True, True),
        ],
    )
    карта = "11111111-1111-1111-1111-111111111111"
    maps_store.save(
        [(карта, None, "Dodo", "Dodo Old", "RO", "City", "addr", 44.4, 26.1, 1, None)],
        [(карта, pointer.GOOGLE, СЕГОДНЯ - timedelta(days=1), 4.6, 80)],
    )
    maps_store.save_links([(карта, ВТОРОЙ, "Старая", 10)])


def test_охват_читается_с_последней_оценкой_каждой_точки(db_env: str) -> None:
    from src.db import agg_store

    _наполнить()

    rows = {(r.aggregator, r.dodo_id): r for r in agg_store.coverage()}
    glovo = rows[("glovo", ВТОРОЙ)]
    assert (glovo.score, glovo.scale, glovo.on_date) == (98.3, 100, СЕГОДНЯ - timedelta(days=9))
    assert rows[("wolt", ПЕРВЫЙ)].score == 8.5
    assert agg_store.point_countries("glovo") == {"RO"}
    assert agg_store.point_keys("glovo") == {"306069"}


def _страница(client: Any, path: str = "/ratings/coverage") -> str:
    ответ = client.get(path)
    assert ответ.status_code == 200
    return ответ.get_data(as_text=True)


def test_экран_охвата_значок_устаревших_прочерк_и_счётчики(
    db_env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _наполнить()

    подменить_двери(monkeypatch, tenant="HQ", role="auditor")
    with собрать(tenant="HQ").test_client() as client:
        assert войти(client).status_code == 302
        html = _страница(client)
        польша = _страница(client, "/ratings/coverage?country=PL")

    assert "пиццерий 2 · новых за 30 дней 1 · без точки на площадках 2" in html
    # Обе без Bolt Food (он в Румынии ожидается); у «Новой» ещё нет Glovo.
    assert html.count("rt-chip") >= 1  # «новая» — у Новая, не у Старая
    # Glovo у «Старой» старше недели: значок с датой. Свежий Wolt — без значка.
    устарел = (СЕГОДНЯ - timedelta(days=9)).strftime("%d.%m.%Y")
    assert f"Данные от {устарел}, новые не приходят" in html
    assert html.count('class="rt-stale"') == 1
    assert "Нет на площадке" in html  # у «Новой» нет Glovo
    assert "98.3%" in html and "9.2<span" in html
    # Гость-не-управляющий формы привязки не видит.
    assert "привязать" not in html
    assert "В этой стране нет работающих пиццерий." in польша


def test_привязка_glovo_по_ссылке_только_управляющим_и_пишет_точку(
    db_env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.db import agg_store
    from src.ratings.aggregators import glovo_link
    from src.web import ratings as screen

    _наполнить()
    настоящая = glovo_link.link_by_url
    страница = (
        '<script>"cityCode":"BUC" https://api.glovoapp.com/v4/stores/555/addresses/777/x</script>'
    )

    class Glovo:
        def get(self, url: str, headers: Any = None) -> object:
            return {"addressId": 777, "name": "Dodo", "ratingInfo": {"ratingValue": 0.9}}

    def без_сети(unit: Any, url: str, taken: Any, today: date, **kw: Any) -> Any:
        return настоящая(unit, url, taken, today, http=Glovo(), page=lambda _: страница)

    monkeypatch.setattr(screen.glovo_link, "link_by_url", без_сети)
    форма = {"dodo_id": ПЕРВЫЙ, "url": "https://glovoapp.com/en/ro/bucharest/stores/dodo"}

    подменить_двери(monkeypatch, tenant="HQ", role="auditor")
    with собрать(tenant="HQ").test_client() as client:
        assert войти(client).status_code == 302
        assert client.post("/ratings/coverage/link", data=форма, headers=ORIGIN).status_code == 403

    подменить_двери(monkeypatch, tenant="HQ", role="control")
    with собрать(tenant="HQ").test_client() as client:
        assert войти(client).status_code == 302
        assert "привязать" in _страница(client)  # у «Новой» нет Glovo — форма есть
        чужая = client.post(
            "/ratings/coverage/link", data=форма, headers={"Origin": "http://evil.example"}
        )
        плохая = client.post(
            "/ratings/coverage/link",
            data={**форма, "url": "https://evil.example/x"},
            headers=ORIGIN,
        )
        хорошая = client.post("/ratings/coverage/link", data=форма, headers=ORIGIN)
        повтор = client.post("/ratings/coverage/link", data=форма, headers=ORIGIN)

    assert чужая.status_code in (400, 403)
    assert плохая.status_code == 400 and "нужна ссылка вида" in плохая.get_data(as_text=True)
    assert хорошая.status_code == 200 and "Привязано к Glovo: Новая." in хорошая.get_data(
        as_text=True
    )
    assert повтор.status_code == 400 and "уже привязана к другой" in повтор.get_data(as_text=True)
    rows = {(r.aggregator, r.dodo_id): r for r in agg_store.coverage()}
    assert rows[("glovo", ПЕРВЫЙ)].score == 90.0
    (точка,) = [p for p in agg_store.known_points("glovo") if p.point_key == "777"]
    assert (точка.extra["store_id"], точка.extra["city_code"]) == ("555", "BUC")
