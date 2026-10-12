"""Оценки агрегаторов в базе (#638, D389): справочник точек, оценки, журнал
сбора — под ролью приложения, как их пишет бот, — и блок на странице рейтингов.
"""

from __future__ import annotations

from datetime import date

import pytest
from conftest import requires_db
from web_harness import войти, подменить_двери, собрать

pytest.importorskip("psycopg")

pytestmark = requires_db

ДОДО = "a" * 32
ВЧЕРА, СЕГОДНЯ = date(2026, 10, 10), date(2026, 10, 11)


def _точка(aggregator: str, key: str, dodo_id: str | None = ДОДО) -> object:
    from src.db.agg_store import PointRow

    return PointRow(
        aggregator, key, "RS", "Dodo Pizza", None, 44.8, 20.46, dodo_id, "Beograd-1", 12, {}
    )


def test_сбор_пишется_и_читается_последней_оценкой(db_env: str) -> None:
    from src.db import agg_store
    from src.db.agg_store import RatingRow

    точки = [_точка("wolt", "dodo-1"), _точка("wolt", "dodo-x", dodo_id=None)]
    оценки = [
        RatingRow("wolt", "dodo-1", ВЧЕРА, 9.0, 10, 100, True, True),
        RatingRow("wolt", "dodo-1", СЕГОДНЯ, 9.2, 10, 120, True, True),
        RatingRow("wolt", "dodo-x", СЕГОДНЯ, 5.0, 10, 3, True, True),
    ]
    assert agg_store.save(точки, оценки) == (2, 3)
    agg_store.log_load("wolt", ok=True, points=2, ratings=3)
    agg_store.log_load("glovo", ok=False, points=0, ratings=0, error="HTTP 503")

    # Непривязанная точка в сводку не идёт; срез «на вчера» берёт вчерашнюю.
    (сейчас,) = agg_store.latest(["RS"])
    assert (сейчас.score, сейчас.votes, сейчас.on_date) == (9.2, 120, СЕГОДНЯ)
    (вчера,) = agg_store.latest(["RS"], until=ВЧЕРА)
    assert вчера.score == 9.0
    assert agg_store.last_ok_points("wolt") == 2 and agg_store.last_ok_points("glovo") == 0
    состояния = {s.aggregator: s for s in agg_store.load_states()}
    assert состояния["wolt"].outcome == "ok" and состояния["glovo"].last_ok is None
    assert состояния["glovo"].error == "HTTP 503"
    assert agg_store.last_run() is not None


def test_справочник_сохраняет_координаты_и_дополняет_extra(db_env: str) -> None:
    from src.db import agg_store
    from src.db.agg_store import PointRow

    agg_store.save([_точка("glovo", "306069")], [])
    без_координат = PointRow(
        "glovo", "306069", "RS", "Dodo Pizza", None, None, None, ДОДО, "Beograd-1", 12,
        {"store_id": 1},
    )  # fmt: skip
    agg_store.save([без_координат], [])

    (точка,) = agg_store.known_points("glovo")
    assert (точка.lat, точка.lng, точка.extra) == (44.8, 20.46, {"store_id": 1})


def test_заявка_одна_открытая_и_закрывается_исходом(db_env: str) -> None:
    """Частичный уникальный индекс держит «уже в очереди» на уровне базы (D420)."""
    from src.db import agg_store

    первая, создана = agg_store.request_update(["wolt"], by="mcp:HQ")
    вторая, создана_ещё = agg_store.request_update([], by="anna")

    assert создана and not создана_ещё and вторая.id == первая.id
    assert первая.aggregators == ("wolt",) and первая.requested_by == "mcp:HQ"

    agg_store.finish_request(первая.id, ok=False, error="wolt: HTTP 503")

    assert agg_store.open_request() is None
    новая, создана_после = agg_store.request_update([], by="anna")
    assert создана_после and новая.id != первая.id and новая.aggregators == ()


def test_блок_агрегаторов_на_странице_и_сбой_строкой(
    db_env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import psycopg

    from src.db import agg_store
    from src.db.agg_store import RatingRow

    agg_store.save(
        [_точка("wolt", "dodo-1"), _точка("glovo", "306069")],
        [
            RatingRow("wolt", "dodo-1", date.today(), 9.24, 10, 120, True, True),
            RatingRow("glovo", "306069", date.today(), 98.3, 100, 591, True, True),
        ],
    )
    agg_store.log_load("glovo", ok=False, points=0, ratings=0, error="HTTP 503")
    # Страна охвата появляется в рейтингах с первой загрузкой — здесь как импорт.
    with psycopg.connect(db_env) as conn:
        conn.execute(
            "insert into ratings.countries (code, name_ru, name_en, is_imf) "
            "values ('RS', 'Сербия', 'Serbia', true)"
        )

    подменить_двери(monkeypatch, tenant="HQ", role="control")
    with собрать(tenant="HQ").test_client() as client:
        assert войти(client).status_code == 302
        ответ = client.get("/ratings?group=country&value=RS")
        прошлый = client.get("/ratings?group=country&value=RS&period=2026-01")
    assert ответ.status_code == 200
    блок = ответ.get_data(as_text=True).split('id="rt-maps"')[1].split("</section>")[0]
    assert '9.2<span class="rt-src__scale">/10</span>' in блок and "98.3%" in блок
    assert "Не собралось: Glovo." in блок and "HTTP 503" in блок
    assert "за выбранный период оценок нет" not in блок
    # Истории до первого сбора нет: на прошлый период — последние данные с датой.
    блок = прошлый.get_data(as_text=True).split('id="rt-maps"')[1].split("</section>")[0]
    assert "98.3%" in блок and "за выбранный период оценок нет" in блок
