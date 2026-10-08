"""API чтения для Swarm (#567, D335): токен, отказы ввода, форма ответа — без базы.

Двери базы подменены на границе `src/db/swarm_read`: здесь проверяется
поверхность — кто пройдёт, что отбивается 4xx/5xx до похода в базу и как
устроен ответ. Чтение настоящей базы — `tests/test_db_swarm_api.py`.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any

import pytest
from flask.testing import FlaskClient

from src.db import ratings_read, swarm_read
from src.db.errors import DbError
from src.web import swarm_api
from src.web.app import create_app
from src.web.config import Settings, load_settings
from src.web.errors import WebConfigError

ТОКЕН = "сервисный-токен-swarm-длиннее-тридцати-двух-знаков"
ВЕРНЫЙ = {"Authorization": f"Bearer {ТОКЕН}"}
АДРЕСА = (
    f"{swarm_api.SCORES_PATH}?type=rs",
    f"{swarm_api.CHECKUPS_PATH}?type=rko",
    f"{swarm_api.VIOLATIONS_PATH}?type=rs",
    swarm_api.INSPECTIONS_PATH,
)
ПЕРИОДЫ = [
    swarm_read.PeriodRow(11, date(2026, 9, 1), date(2026, 9, 15), "Сентябрь 1", "September 1"),
    swarm_read.PeriodRow(12, date(2026, 9, 16), date(2026, 9, 30), "Сентябрь 2", "September 2"),
]


def _клиент(token: str | None) -> FlaskClient:
    app = create_app(
        Settings(
            host="127.0.0.1",
            port=8266,
            tenant="HQ",
            ui_lang="ru",
            secret_key="ключ-подписи-куки-этого-набора-длиннее-тридцати-двух",
            swarm_api_token=token,
        )
    )
    app.config.update(TESTING=True)
    return app.test_client()


@pytest.fixture
def база(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    """Подменённые двери чтения; журнал вызовов — чтобы видеть, что дошло до базы."""
    зовы: dict[str, list[Any]] = {"periods": [], "inspections": []}

    def периоды(rating_type: str, **kw: Any) -> list[swarm_read.PeriodRow]:
        зовы["periods"].append((rating_type, kw))
        return ПЕРИОДЫ

    def проверки(**kw: Any) -> list[swarm_read.InspectionRow]:
        зовы["inspections"].append(kw)
        return [
            swarm_read.InspectionRow(
                "11111111-1111-1111-1111-111111111111",
                "22222222-2222-2222-2222-222222222222",
                None,
                "Batumi-1",
                "GE",
                date(2026, 10, 2),
                "planned",
                97.5,
                "A",
            )
        ]

    monkeypatch.setattr(swarm_read, "periods", периоды)
    monkeypatch.setattr(swarm_read, "inspections", проверки)
    monkeypatch.setattr(
        swarm_read,
        "scores",
        lambda *a, **k: [("aa" * 16, "Testville-1", "RS", "Dev One", 12, 96.0)],
    )
    monkeypatch.setattr(
        swarm_read,
        "checkup_counts",
        lambda *a, **k: ([("aa" * 16, "Testville-1", "RS", 11, "inspection", 2)], []),
    )
    monkeypatch.setattr(swarm_read, "violation_facts", lambda *a, **k: ([], [("RS", 12, 3)]))
    monkeypatch.setattr(
        swarm_read, "loaded_at", lambda formats: datetime(2026, 10, 8, 19, 40, 1, 5, tzinfo=UTC)
    )
    monkeypatch.setattr(
        ratings_read,
        "countries",
        lambda: (
            ratings_read.CountryRow("RS", "Сербия", "Serbia", None, True),
            ratings_read.CountryRow("RU", "Россия", "Russia", None, False),
        ),
    )
    return зовы


@pytest.fixture
def клиент(база: dict[str, list[Any]]) -> Iterator[FlaskClient]:
    with _клиент(ТОКЕН) as client:
        yield client


# --- опознание ---------------------------------------------------------------


@pytest.mark.parametrize("адрес", АДРЕСА)
@pytest.mark.parametrize(
    "заголовки",
    [
        {},
        {"Authorization": "Bearer не-тот-токен-совсем-другой-и-тоже-длинный"},
        {"Authorization": f"Basic {ТОКЕН}"},
        {"Authorization": "Bearer "},
        {"Authorization": f"Bearer {ТОКЕН}x"},
    ],
)
def test_без_верного_токена_401(
    клиент: FlaskClient, база: dict[str, list[Any]], адрес: str, заголовки: dict[str, str]
) -> None:
    ответ = клиент.get(адрес, headers=заголовки)
    assert ответ.status_code == 401
    assert ответ.get_json()["error"] == "unauthorized"
    assert ответ.headers["WWW-Authenticate"].startswith("Bearer")
    assert база == {"periods": [], "inspections": []}, "до базы дошёл неопознанный"


@pytest.mark.parametrize("адрес", АДРЕСА)
def test_токен_не_задан_503_а_не_открыто(база: dict[str, list[Any]], адрес: str) -> None:
    with _клиент(None) as client:
        ответ = client.get(адрес, headers=ВЕРНЫЙ)
    assert ответ.status_code == 503
    assert ответ.get_json() == {
        "error": "not_configured",
        "message": "SWARM_API_TOKEN is not set on this server",
    }


@pytest.mark.parametrize("адрес", АДРЕСА)
def test_верный_токен_пускает(клиент: FlaskClient, адрес: str) -> None:
    ответ = клиент.get(адрес, headers=ВЕРНЫЙ)
    assert ответ.status_code == 200, ответ.get_data(as_text=True)
    assert ответ.headers["Cache-Control"] == "private, max-age=300"


def test_схема_bearer_без_учёта_регистра(клиент: FlaskClient) -> None:
    ответ = клиент.get(АДРЕСА[0], headers={"Authorization": f"bearer {ТОКЕН}"})
    assert ответ.status_code == 200


def test_токен_не_открывает_остальную_админку(клиент: FlaskClient) -> None:
    """Токен — только эти четыре адреса: страница админки с ним уводит на вход."""
    for путь in ("/ratings", "/inspections", "/ratings/imports"):
        ответ = клиент.get(путь, headers=ВЕРНЫЙ)
        assert ответ.status_code == 302 and "/login" in ответ.headers["Location"], путь


def test_только_чтение(клиент: FlaskClient) -> None:
    ответ = клиент.post(swarm_api.SCORES_PATH, headers=ВЕРНЫЙ)
    assert ответ.status_code in (302, 405)


def test_короткий_токен_в_окружении_отказ_запуска() -> None:
    with pytest.raises(WebConfigError, match="SWARM_API_TOKEN"):
        load_settings({"WEB_TENANT": "HQ", "SWARM_API_TOKEN": "short"})
    assert load_settings({"WEB_TENANT": "HQ"}).swarm_api_token is None
    assert load_settings({"WEB_TENANT": "HQ", "SWARM_API_TOKEN": ТОКЕН}).swarm_api_token == ТОКЕН


# --- отказы ввода ------------------------------------------------------------


@pytest.mark.parametrize(
    ("адрес", "код"),
    [
        (f"{swarm_api.SCORES_PATH}", "bad_type"),
        (f"{swarm_api.SCORES_PATH}?type=xx", "bad_type"),
        (f"{swarm_api.CHECKUPS_PATH}?type=rs&countries=RS,SRB", "bad_countries"),
        (f"{swarm_api.CHECKUPS_PATH}?type=rs&countries=RS,,HR", "bad_countries"),
        (f"{swarm_api.VIOLATIONS_PATH}?type=rs&countries=R1", "bad_countries"),
        (f"{swarm_api.SCORES_PATH}?type=rs&from=2026-13-01", "bad_date"),
        (f"{swarm_api.SCORES_PATH}?type=rs&from=20261001", "bad_date"),
        (f"{swarm_api.SCORES_PATH}?type=rs&to=yesterday", "bad_date"),
        (f"{swarm_api.SCORES_PATH}?type=rs&from=2026-10-02&to=2026-10-01", "bad_range"),
        (f"{swarm_api.VIOLATIONS_PATH}?type=rko&top=0", "bad_top"),
        (f"{swarm_api.VIOLATIONS_PATH}?type=rko&top=21", "bad_top"),
        (f"{swarm_api.VIOLATIONS_PATH}?type=rko&top=-1", "bad_top"),
        (f"{swarm_api.INSPECTIONS_PATH}?limit=1001", "bad_limit"),
        (f"{swarm_api.INSPECTIONS_PATH}?countries=ge;am", "bad_countries"),
        (f"{swarm_api.INSPECTIONS_PATH}?from=2026-02-30", "bad_date"),
    ],
)
def test_кривой_ввод_400(
    клиент: FlaskClient, база: dict[str, list[Any]], адрес: str, код: str
) -> None:
    ответ = клиент.get(адрес, headers=ВЕРНЫЙ)
    assert ответ.status_code == 400
    тело = ответ.get_json()
    assert тело["error"] == код and тело["message"]
    assert база["inspections"] == []


def test_слишком_много_периодов_400(клиент: FlaskClient, monkeypatch: pytest.MonkeyPatch) -> None:
    много = [ПЕРИОДЫ[0]] * (swarm_api.MAX_PERIODS + 1)
    monkeypatch.setattr(swarm_read, "periods", lambda *a, **k: много)
    ответ = клиент.get(АДРЕСА[0], headers=ВЕРНЫЙ)
    assert ответ.status_code == 400 and ответ.get_json()["error"] == "range_too_large"


def test_база_не_ответила_503(клиент: FlaskClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def отказ(*_: Any, **__: Any) -> None:
        raise DbError("нет связи")

    monkeypatch.setattr(swarm_read, "periods", отказ)
    ответ = клиент.get(АДРЕСА[0], headers=ВЕРНЫЙ)
    assert ответ.status_code == 503 and ответ.get_json()["error"] == "db_unavailable"
    assert "нет связи" not in ответ.get_data(as_text=True)


# --- форма ответа ------------------------------------------------------------


def test_баллы_выровнены_по_периодам(клиент: FlaskClient, база: dict[str, list[Any]]) -> None:
    тело = клиент.get(
        f"{swarm_api.SCORES_PATH}?type=RS&from=2026-09-01&to=2026-09-30", headers=ВЕРНЫЙ
    ).get_json()
    assert тело == {
        "type": "rs",
        "periods": [
            {
                "id": 11,
                "start": "2026-09-01",
                "end": "2026-09-15",
                "title_ru": "Сентябрь 1",
                "title_en": "September 1",
            },
            {
                "id": 12,
                "start": "2026-09-16",
                "end": "2026-09-30",
                "title_ru": "Сентябрь 2",
                "title_en": "September 2",
            },
        ],
        "units": [
            {
                "id": "aa" * 16,
                "name": "Testville-1",
                "cc": "RS",
                "developer": "Dev One",
                "scores": [None, 96.0],
            }
        ],
        "loaded_at": "2026-10-08T19:40:01Z",
    }
    assert база["periods"] == [
        ("rs", {"date_from": date(2026, 9, 1), "date_to": date(2026, 9, 30)})
    ]


def test_страны_по_умолчанию_только_imf(
    клиент: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    спросили: list[Any] = []
    monkeypatch.setattr(swarm_read, "scores", lambda *a, **k: спросили.append(k) or [])
    клиент.get(АДРЕСА[0], headers=ВЕРНЫЙ)
    клиент.get(f"{АДРЕСА[0]}&countries=hr, rs,HR", headers=ВЕРНЫЙ)
    assert [k["countries"] for k in спросили] == [["RS"], ["HR", "RS"]]


def test_собираемость_по_каналам(клиент: FlaskClient) -> None:
    тело = клиент.get(f"{swarm_api.CHECKUPS_PATH}?type=rs", headers=ВЕРНЫЙ).get_json()
    assert тело["units"] == [
        {
            "id": "aa" * 16,
            "name": "Testville-1",
            "cc": "RS",
            "counts": [
                {"restaurant": 0, "delivery": 0, "inspection": 2, "online": 0, "rated": None},
                None,
            ],
        }
    ]


def test_нарушения_проверки_были_нарушений_нет(клиент: FlaskClient) -> None:
    тело = клиент.get(f"{swarm_api.VIOLATIONS_PATH}?type=rs", headers=ВЕРНЫЙ).get_json()
    assert тело["countries"] == [
        {
            "cc": "RS",
            "periods": [None, {"total": 0, "checkups": 3, "per_checkup": 0.0, "top": []}],
        }
    ]


def test_проверки_форма_и_обрезка(клиент: FlaskClient, база: dict[str, list[Any]]) -> None:
    тело = клиент.get(
        f"{swarm_api.INSPECTIONS_PATH}?countries=ge&from=2026-10-01&limit=1", headers=ВЕРНЫЙ
    ).get_json()
    assert тело == {
        "inspections": [
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "unit": {
                    "id": "22222222-2222-2222-2222-222222222222",
                    "dodo_id": None,
                    "name": "Batumi-1",
                    "cc": "GE",
                },
                "date": "2026-10-02",
                "kind": "planned",
                "score_pct": 97.5,
                "grade": "A",
                "path": "/inspections/11111111-1111-1111-1111-111111111111",
            }
        ],
        "truncated": False,
    }
    (зов,) = база["inspections"]
    assert зов["limit"] == 2, "читается на одну больше предела — так видна обрезка"
    assert зов["reach"].countries == ("GE",) and зов["reach"].tenants is None
    assert зов["date_from"] == date(2026, 10, 1) and зов["date_to"] is None
