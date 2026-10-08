"""API чтения `/api/v1` (#567, D336): доступ по токену и формы ответов контракта.

Ядро — доступ: без токена, с отозванным, с чужим правом, с кукой админки
вместо токена ответ один из 401/403 без подробностей. Данные рейтингов кладёт
настоящий импортёр, проверки — настоящий слив; токены выпускаются в тесте.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from conftest import requires_db
from db_harness import set_retraction_env, слить_проверку, точка_справочника
from flask.testing import FlaskClient
from ratings_samples import P_RS_PREV, U1, rko_evaluations, rko_violations, rs_checkups, snapshot
from web_harness import ПАРОЛЬ, СЕКРЕТ, войти, подменить_двери

pytest.importorskip("psycopg")

from src.db import api_tokens
from src.ratings.importer import CHANNEL_WEB, import_file
from src.web import api_limits
from src.web.app import create_app
from src.web.config import Settings

pytestmark = requires_db

РЕЙТИНГИ = "ratings:read"
ПРОВЕРКИ = "inspections:read"


def _приложение(*, api: bool = True) -> Any:
    app = create_app(
        Settings(
            host="127.0.0.1",
            port=8266,
            tenant="HQ",
            ui_lang="ru",
            secret_key=СЕКРЕТ,
            api_enabled=api,
        )
    )
    app.config.update(TESTING=True)
    return app


@pytest.fixture
def admin_env(db_env: str, monkeypatch: pytest.MonkeyPatch) -> str:
    return set_retraction_env(db_env, monkeypatch)


@pytest.fixture
def клиент(admin_env: str) -> Iterator[FlaskClient]:
    with _приложение().test_client() as client:
        yield client


def _токен(*scopes: str) -> str:
    return api_tokens.issue("swarm", scopes=list(scopes), by="tester").value


def _с(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


#: Проверка РКО Testville-1 внутри недели РКО снимка (29.09–05.10).
В_НЕДЕЛЕ = {"Дата заказа": "2026-10-03 10:14:19", "CreatedAtUtc": "2026-10-03 10:24:19"}


def _загрузить_рейтинги() -> None:
    for data in (snapshot(), rko_violations(**В_НЕДЕЛЕ), rko_evaluations(), rs_checkups()):
        import_file(
            data,
            kind=None,
            channel=CHANNEL_WEB,
            actor="ctl",
            file_name=None,
            today=date(2026, 10, 8),
        )


# --- доступ ----------------------------------------------------------------------


def test_без_заголовка_401(клиент: FlaskClient) -> None:
    ответ = клиент.get("/api/v1/ratings/scores?type=rs")

    assert ответ.status_code == 401
    assert ответ.get_json() == {
        "error": "unauthorized",
        "message": "A valid bearer token is required",
    }
    assert ответ.headers["Cache-Control"] == "no-store"


def test_незнакомый_и_отозванный_неразличимы(клиент: FlaskClient) -> None:
    выпущен = api_tokens.issue("swarm", scopes=[РЕЙТИНГИ], by="tester")
    api_tokens.revoke(выпущен.id, by="tester")

    отозванный = клиент.get("/api/v1/ratings/scores?type=rs", headers=_с(выпущен.value))
    незнакомый = клиент.get("/api/v1/ratings/scores?type=rs", headers=_с(api_tokens.new_token()))

    assert отозванный.status_code == незнакомый.status_code == 401
    assert отозванный.get_data() == незнакомый.get_data()


def test_право_рейтингов_не_открывает_проверки(клиент: FlaskClient) -> None:
    токен = _токен(РЕЙТИНГИ)

    assert клиент.get("/api/v1/ratings/scores?type=rs", headers=_с(токен)).status_code == 200
    ответ = клиент.get("/api/v1/inspections", headers=_с(токен))

    assert ответ.status_code == 403
    assert ответ.get_json()["error"] == "forbidden"


def test_право_проверок_не_открывает_рейтинги(клиент: FlaskClient) -> None:
    токен = _токен(ПРОВЕРКИ)

    assert клиент.get("/api/v1/inspections", headers=_с(токен)).status_code == 200
    assert клиент.get("/api/v1/ratings/checkups?type=rs", headers=_с(токен)).status_code == 403


def test_кука_админки_не_открывает_api(
    admin_env: str, domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    подменить_двери(monkeypatch, tenant="HQ", role="admin")
    with _приложение().test_client() as client:
        assert войти(client).status_code == 302
        assert client.get("/ratings").status_code == 200

        ответ = client.get("/api/v1/ratings/scores?type=rs")

    assert ответ.status_code == 401


def test_токен_не_открывает_админку(клиент: FlaskClient) -> None:
    токен = _токен(РЕЙТИНГИ, ПРОВЕРКИ)

    ответ = клиент.get("/ratings", headers=_с(токен))

    assert ответ.status_code == 302
    assert "/login" in ответ.headers["Location"]


def test_выключенный_api_не_отвечает(admin_env: str) -> None:
    токен = _токен(РЕЙТИНГИ)
    with _приложение(api=False).test_client() as client:
        ответ = client.get("/api/v1/ratings/scores?type=rs", headers=_с(токен))

    assert ответ.status_code != 200
    assert ответ.headers.get("Content-Type", "").startswith("application/json") is False


def test_прочие_адреса_api_без_токена_401_с_токеном_404(клиент: FlaskClient) -> None:
    assert клиент.get("/api/v1/ratings/import").status_code == 401
    assert клиент.post("/api/v1/ratings/scores").status_code == 401

    токен = _токен(РЕЙТИНГИ)
    assert клиент.post("/api/v1/ratings/scores", headers=_с(токен)).status_code == 404
    assert клиент.get("/api/v1/whatever", headers=_с(токен)).get_json()["error"] == "not_found"


def test_лимит_на_токен_429(admin_env: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api_limits, "PER_TOKEN_PER_MINUTE", 2)
    токен = _токен(ПРОВЕРКИ)
    with _приложение().test_client() as client:
        коды = [client.get("/api/v1/inspections", headers=_с(токен)).status_code for _ in range(3)]
        последний = client.get("/api/v1/inspections", headers=_с(токен))

    assert коды == [200, 200, 429]
    assert последний.get_json()["error"] == "rate_limited"
    assert int(последний.headers["Retry-After"]) >= 1


def test_неудачи_с_адреса_запираются_429(admin_env: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api_limits, "FAILURES_PER_MINUTE", 2)
    токен = _токен(ПРОВЕРКИ)
    with _приложение().test_client() as client:
        коды = [
            client.get("/api/v1/inspections", headers=_с("dcm_" + "x" * 43)).status_code
            for _ in range(2)
        ]
        запертый = client.get("/api/v1/inspections", headers=_с(токен))

    assert коды == [401, 401]
    assert запертый.status_code == 429


def test_журнал_без_токена(клиент: FlaskClient, caplog: pytest.LogCaptureFixture) -> None:
    токен = _токен(РЕЙТИНГИ)
    caplog.set_level(logging.INFO, logger="src.web.api")

    клиент.get("/api/v1/ratings/scores?type=rs&countries=RS", headers=_с(токен))
    клиент.get("/api/v1/ratings/scores?type=rs", headers=_с("dcm_" + "y" * 43))

    записи = [json.loads(r.getMessage()) for r in caplog.records if r.name == "src.web.api"]
    assert [z["status"] for z in записи] == [200, 401]
    assert записи[0]["consumer"] == "swarm" and записи[0]["params"] == {
        "countries": "RS",
        "type": "rs",
    }
    assert записи[1]["consumer"] is None
    весь_журнал = caplog.text
    assert токен not in весь_журнал and "y" * 43 not in весь_журнал
    assert "Bearer" not in весь_журнал and ПАРОЛЬ not in весь_журнал


# --- валидация -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("query", "code"),
    [
        ("", "bad_type"),
        ("type=xx", "bad_type"),
        ("type=rs&countries=RU", "bad_countries"),
        ("type=rs&countries=rs;drop", "bad_countries"),
        ("type=rs&from=2026-13-01", "bad_date"),
        ("type=rs&from=yesterday", "bad_date"),
        ("type=rs&from=2026-10-01&to=2026-09-01", "bad_range"),
        ("type=rs&top=0", "bad_top"),
        ("type=rs&top=21", "bad_top"),
        ("type=rs&country=RS", "unknown_parameter"),
        ("type=rs&type=rko", "bad_parameter"),
    ],
)
def test_параметры_400(клиент: FlaskClient, query: str, code: str) -> None:
    токен = _токен(РЕЙТИНГИ)

    ответ = клиент.get(f"/api/v1/ratings/violations?{query}", headers=_с(токен))

    assert ответ.status_code == 400
    assert ответ.get_json()["error"] == code
    assert set(ответ.get_json()) == {"error", "message"}


def test_слишком_широкий_диапазон_400(клиент: FlaskClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.ratings import api_payload

    _загрузить_рейтинги()
    monkeypatch.setattr(api_payload, "MAX_PERIODS", 0)
    токен = _токен(РЕЙТИНГИ)

    ответ = клиент.get("/api/v1/ratings/scores?type=rs", headers=_с(токен))

    assert ответ.status_code == 400 and ответ.get_json()["error"] == "range_too_large"


def test_база_недоступна_503_без_подробностей(
    клиент: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    токен = _токен(ПРОВЕРКИ)
    # Сверка токена прошла, а чтение данных упало: подключение данных испорчено.
    from src.db import api_inspections

    def упала(**_: object) -> None:
        from src.db.errors import DbError

        raise DbError("dsn=postgresql://secret@host/db")

    monkeypatch.setattr(api_inspections, "inspection_results", упала)

    ответ = клиент.get("/api/v1/inspections", headers=_с(токен))

    assert ответ.status_code == 503
    assert ответ.get_json() == {
        "error": "unavailable",
        "message": "Data source is temporarily unavailable",
    }


# --- формы ответов ---------------------------------------------------------------


#: Вторая пиццерия Сербии с баллом только в прошлом периоде РС.
U9 = "aa0000000000000000000000000000a9"
ПРОШЛЫЙ_РС = {
    "id": P_RS_PREV,
    "rating_type": 2,
    "begin": "2026-09-01",
    "end": "2026-09-15",
    "alias": "Сентябрь 1 часть 2026",
    "alias_en": "September part 1 2026",
}


def test_баллы_по_контракту(клиент: FlaskClient) -> None:
    _загрузить_рейтинги()
    прошлый = snapshot(
        dodo_id=U9,
        name="Testville-9",
        history=[{"score": 80, "status": "1", "period": ПРОШЛЫЙ_РС}],
        remarks=[],
    )
    import_file(
        прошлый,
        kind=None,
        channel=CHANNEL_WEB,
        actor="ctl",
        file_name=None,
        today=date(2026, 10, 8),
    )
    токен = _токен(РЕЙТИНГИ)

    ответ = клиент.get("/api/v1/ratings/scores?type=rs&countries=RS", headers=_с(токен))

    assert ответ.status_code == 200
    assert ответ.headers["Cache-Control"] == "private, max-age=300"
    тело = ответ.get_json()
    assert set(тело) == {"type", "periods", "units", "loaded_at"}
    assert тело["type"] == "rs"
    starts = [p["start"] for p in тело["periods"]]
    assert starts == ["2026-09-01", "2026-09-16"]
    assert set(тело["periods"][1]) == {"id", "start", "end", "title_ru", "title_en"}
    assert тело["periods"][0]["title_en"] == "September part 1 2026"
    assert тело["units"] == [
        {
            "id": U1,
            "name": "Testville-1",
            "cc": "RS",
            "developer": None,
            "scores": [None, 97.5],
        },
        {
            "id": U9,
            "name": "Testville-9",
            "cc": "RS",
            "developer": None,
            "scores": [80.0, None],
        },
    ]
    assert тело["loaded_at"].endswith("Z")


def test_баллы_с_датами(клиент: FlaskClient) -> None:
    _загрузить_рейтинги()
    токен = _токен(РЕЙТИНГИ)

    тело = клиент.get(
        "/api/v1/ratings/scores?type=rs&from=2026-09-10&to=2026-09-30", headers=_с(токен)
    ).get_json()

    assert [p["start"] for p in тело["periods"]] == ["2026-09-16"]
    assert тело["units"][0]["scores"] == [97.5]


def test_собираемость_по_контракту(клиент: FlaskClient) -> None:
    _загрузить_рейтинги()
    токен = _токен(РЕЙТИНГИ)

    тело = клиент.get(
        "/api/v1/ratings/checkups?type=rko&countries=RS", headers=_с(токен)
    ).get_json()

    assert set(тело) == {"type", "periods", "units"}
    assert [p["start"] for p in тело["periods"]] == ["2026-09-29"]
    assert тело["units"] == [
        {
            "id": U1,
            "cc": "RS",
            "counts": [{"restaurant": 0, "delivery": 1, "inspection": 0, "online": 0}],
        }
    ]

    тело = клиент.get("/api/v1/ratings/checkups?type=rs", headers=_с(токен)).get_json()
    # Проверки РС 06–07.10 позже последнего периода РС (16–30.09).
    assert тело["units"] == []


def test_нарушения_по_контракту(клиент: FlaskClient) -> None:
    _загрузить_рейтинги()
    токен = _токен(РЕЙТИНГИ)

    тело = клиент.get(
        "/api/v1/ratings/violations?type=rs&countries=RS,SI&top=1", headers=_с(токен)
    ).get_json()

    assert set(тело) == {"type", "periods", "countries"}
    assert [c["cc"] for c in тело["countries"]] == ["RS", "SI"]
    rs = тело["countries"][0]["top"]
    assert len(rs) == len(тело["periods"])
    индекс = [p["start"] for p in тело["periods"]].index("2026-09-16")
    assert rs[индекс] == [{"text": "Грязный пол", "criterion_id": "17", "count": 2}]
    assert тело["countries"][1]["top"] == [[] for _ in тело["periods"]]


def test_проверки_по_контракту(клиент: FlaskClient, domain_env: Path, admin_env: str) -> None:
    _загрузить_рейтинги()
    точка = точка_справочника("Batumi-1", country="GE", city="Batumi")
    принятая = слить_проверку(unit="Batumi-1", tenant="HQ", date="2026-10-02")
    слить_проверку(unit="Batumi-1", tenant="HQ", accept=False)
    токен = _токен(ПРОВЕРКИ)

    тело = клиент.get(
        "/api/v1/inspections?countries=GE&from=2026-10-01", headers=_с(токен)
    ).get_json()

    (проверка,) = тело["inspections"]
    assert set(проверка) == {"id", "unit", "date", "status", "score_pct", "grade", "url"}
    assert проверка["id"] == принятая
    assert проверка["unit"] == {"id": точка, "dodo_id": None, "name": "Batumi-1", "cc": "GE"}
    assert проверка["date"] == "2026-10-02"
    assert проверка["status"] == "finalized"
    assert isinstance(проверка["score_pct"], float) and проверка["grade"]
    assert проверка["url"].endswith(f"/inspections/{принятая}")
    пусто = клиент.get("/api/v1/inspections?countries=RS", headers=_с(токен)).get_json()
    assert пусто == {"inspections": []}
