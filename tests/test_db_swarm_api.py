"""API чтения для Swarm через настоящую базу (#567, D335): синтетика загружена — API её отдал.

Данные кладутся теми же дверями, что у продукта: рейтинги — загрузкой
синтетических выгрузок (`ratings_samples`), проверки — сливом и подтверждением
(`db_harness`). Процент и буква проверки сверяются с тем, что записал движок, —
API ничего не пересчитывает.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from conftest import requires_db
from ratings_samples import U1, rko_evaluations, rko_violations, rs_checkups, snapshot

psycopg = pytest.importorskip("psycopg")

from db_harness import слить_проверку, точка_справочника  # noqa: E402
from flask.testing import FlaskClient  # noqa: E402

from src.db import queries  # noqa: E402
from src.db.reach import reach_of  # noqa: E402
from src.ratings.importer import CHANNEL_WEB, import_file  # noqa: E402
from src.web import swarm_api  # noqa: E402
from src.web.app import create_app  # noqa: E402
from src.web.config import Settings  # noqa: E402

pytestmark = requires_db

ТОКЕН = "сервисный-токен-swarm-длиннее-тридцати-двух-знаков"
ВЕРНЫЙ = {"Authorization": f"Bearer {ТОКЕН}"}


def _грузить(data: bytes) -> None:
    import_file(
        data, kind=None, channel=CHANNEL_WEB, actor="ctl", file_name=None, today=date(2026, 10, 8)
    )


@pytest.fixture
def клиент() -> Iterator[FlaskClient]:
    app = create_app(
        Settings(
            host="127.0.0.1",
            port=8266,
            tenant="HQ",
            ui_lang="ru",
            secret_key="ключ-подписи-куки-этого-набора-длиннее-тридцати-двух",
            swarm_api_token=ТОКЕН,
        )
    )
    app.config.update(TESTING=True)
    with app.test_client() as client:
        yield client


@pytest.fixture
def рейтинги(db_env: str) -> None:
    """U1 (Сербия): РС 97.5 за 16–30.09, РКО 91 за 29.09–05.10, замечания периода РС.

    Даты проверок из выгрузок сдвинуты внутрь периодов снимка: так видно, что
    проверка попадает в свой период по дате, а не по ссылке.
    """
    _грузить(snapshot())
    _грузить(rs_checkups().replace(b"2026-10-06 15:15:00", b"2026-09-20 15:15:00"))
    _грузить(rko_violations(**{"Дата заказа": "2026-10-03 10:14:19"}))
    _грузить(rko_evaluations())


def _get(клиент: FlaskClient, путь: str) -> dict[str, Any]:
    ответ = клиент.get(путь, headers=ВЕРНЫЙ)
    assert ответ.status_code == 200, ответ.get_data(as_text=True)
    тело: dict[str, Any] = ответ.get_json()
    return тело


def _ячейка(тело: dict[str, Any], начало: str) -> int:
    """Индекс периода по дате начала: id периодов в базе — свои, не из снимка."""
    return [p["start"] for p in тело["periods"]].index(начало)


@pytest.mark.usefixtures("рейтинги")
def test_баллы_рс_из_снимка(клиент: FlaskClient) -> None:
    тело = _get(клиент, f"{swarm_api.SCORES_PATH}?type=rs&countries=RS")
    assert [p["start"] for p in тело["periods"]] == sorted(p["start"] for p in тело["periods"])
    i = _ячейка(тело, "2026-09-16")
    assert тело["periods"][i]["title_en"] == "September part 2 2026"
    (unit,) = тело["units"]
    assert unit["id"] == U1 and unit["cc"] == "RS" and unit["name"] == "Testville-1"
    assert len(unit["scores"]) == len(тело["periods"])
    assert unit["scores"][i] == pytest.approx(97.5)
    assert all(s is None for j, s in enumerate(unit["scores"]) if j != i)
    assert тело["loaded_at"] is not None and тело["loaded_at"].endswith("Z")


@pytest.mark.usefixtures("рейтинги")
def test_баллы_за_чужие_даты_и_страны_пусты(клиент: FlaskClient) -> None:
    тело = _get(клиент, f"{swarm_api.SCORES_PATH}?type=rs&from=2027-01-01")
    assert тело["periods"] == [] and тело["units"] == []
    тело = _get(клиент, f"{swarm_api.SCORES_PATH}?type=rko&countries=HR")
    assert тело["periods"] and тело["units"] == []


@pytest.mark.usefixtures("рейтинги")
def test_собираемость_по_каналам_и_числу_снимка(клиент: FlaskClient) -> None:
    рс = _get(клиент, f"{swarm_api.CHECKUPS_PATH}?type=rs&countries=RS")
    i = _ячейка(рс, "2026-09-16")
    (unit,) = рс["units"]
    assert unit["counts"][i] == {
        "restaurant": 0,
        "delivery": 0,
        "inspection": 1,
        "online": 0,
        "rated": 4,
    }
    ркo = _get(клиент, f"{swarm_api.CHECKUPS_PATH}?type=rko&countries=RS")
    j = _ячейка(ркo, "2026-09-29")
    (unit,) = ркo["units"]
    assert unit["counts"][j]["delivery"] == 1 and unit["counts"][j]["restaurant"] == 0


@pytest.mark.usefixtures("рейтинги")
def test_топ_нарушений_по_стране(клиент: FlaskClient) -> None:
    рс = _get(клиент, f"{swarm_api.VIOLATIONS_PATH}?type=rs&countries=RS&top=5")
    i = _ячейка(рс, "2026-09-16")
    (страна,) = рс["countries"]
    ячейка = страна["periods"][i]
    assert ячейка["checkups"] == 4
    assert ячейка["top"][0] == {"text": "Грязный пол", "count": 2}
    ркo = _get(клиент, f"{swarm_api.VIOLATIONS_PATH}?type=rko&countries=RS&top=1")
    j = _ячейка(ркo, "2026-09-29")
    (страна,) = ркo["countries"]
    ячейка = страна["periods"][j]
    assert ячейка["checkups"] == 1
    assert ячейка["top"] == [{"text": "Ингредиенты на бортах", "count": 2}], "top=1 — одна строка"
    assert ячейка["total"] == 3, "(ML) у второго нарушения не мешает счёту"


@pytest.fixture
def проверки(pg_dsn: str, db_env: str, domain_env: Path) -> dict[str, str]:
    точка_справочника("Batumi-1", country="GE", city="Batumi")
    точка_справочника("Yerevan-1", country="AM", city="Yerevan")
    return {
        "батуми": слить_проверку(unit="Batumi-1", tenant="HQ", date="2026-10-02"),
        "ереван": слить_проверку(unit="Yerevan-1", tenant="HQ", date="2026-10-03"),
        "ждёт": слить_проверку(unit="Batumi-1", tenant="HQ", date="2026-10-04", accept=False),
    }


def test_проверки_принятые_по_всей_сети(клиент: FlaskClient, проверки: dict[str, str]) -> None:
    тело = _get(клиент, swarm_api.INSPECTIONS_PATH)
    ids = [x["id"] for x in тело["inspections"]]
    assert ids == [проверки["ереван"], проверки["батуми"]], "свежие первыми, ждущая — вне"
    assert тело["truncated"] is False
    записано = {r.id: r for r in queries.list_inspections(reach=reach_of("HQ"), limit=10)}
    for x in тело["inspections"]:
        assert x["score_pct"] == pytest.approx(записано[x["id"]].pct)
        assert x["grade"] == записано[x["id"]].grade
        assert x["kind"] == "planned" and x["path"] == f"/inspections/{x['id']}"
        assert set(x) == {"id", "unit", "date", "kind", "score_pct", "grade", "path"}
        assert set(x["unit"]) == {"id", "dodo_id", "name", "cc"}


def test_проверки_по_стране_датам_и_пределу(клиент: FlaskClient, проверки: dict[str, str]) -> None:
    (x,) = _get(клиент, f"{swarm_api.INSPECTIONS_PATH}?countries=GE")["inspections"]
    assert x["id"] == проверки["батуми"] and x["unit"]["cc"] == "GE"
    assert x["unit"]["name"] == "Batumi-1" and x["date"] == "2026-10-02"
    assert _get(клиент, f"{swarm_api.INSPECTIONS_PATH}?to=2026-10-01")["inspections"] == []
    тело = _get(клиент, f"{swarm_api.INSPECTIONS_PATH}?limit=1")
    assert [x["id"] for x in тело["inspections"]] == [проверки["ереван"]]
    assert тело["truncated"] is True
