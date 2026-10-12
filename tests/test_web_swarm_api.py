"""API чтения для Swarm (#567, D387, D388): токен, права, лимит, ввод, ответ — без базы.

Двери базы подменены на границе `src/db/swarm_read`, `src/db/api_access` и
`src/db/web_throttle`: здесь проверяется
поверхность — кто пройдёт, что отбивается 4xx/5xx до похода в базу и как
устроен ответ. Чтение настоящей базы — `tests/test_db_swarm_api.py`.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from flask.testing import FlaskClient

from src.db import api_access, maps_store, queries, ratings_read, swarm_read, web_throttle
from src.db.errors import AccessError, DbError
from src.db.maps_store import LatestRating
from src.db.models import FindingRow, InspectionDetail
from src.db.models import InspectionRow as DetailRow
from src.ratings import pointer
from src.web import inspection_titles, swarm_api
from src.web.app import create_app
from src.web.config import Settings

ТОКЕН = "сервисный-токен-swarm-длиннее-тридцати-двух-знаков"
ТОЛЬКО_РЕЙТИНГИ = "токен-только-с-правом-рейтингов-тоже-длинный"
ВЕРНЫЙ = {"Authorization": f"Bearer {ТОКЕН}"}
ТОКЕНЫ = {
    ТОКЕН: api_access.ApiToken(1, "swarm", api_access.SCOPES),
    ТОЛЬКО_РЕЙТИНГИ: api_access.ApiToken(2, "swarm", (api_access.SCOPE_RATINGS_READ,)),
}
АДРЕСА = (
    f"{swarm_api.SCORES_PATH}?type=rs",
    f"{swarm_api.CHECKUPS_PATH}?type=rko",
    f"{swarm_api.VIOLATIONS_PATH}?type=rs",
    swarm_api.INSPECTIONS_PATH,
    swarm_api.MAPS_PATH,
)
ПЕРИОДЫ = [
    swarm_read.PeriodRow(11, date(2026, 9, 1), date(2026, 9, 15), "Сентябрь 1", "September 1"),
    swarm_read.PeriodRow(12, date(2026, 9, 16), date(2026, 9, 30), "Сентябрь 2", "September 2"),
]


def _клиент() -> FlaskClient:
    app = create_app(
        Settings(
            host="127.0.0.1",
            port=8266,
            tenant="HQ",
            ui_lang="ru",
            secret_key="ключ-подписи-куки-этого-набора-длиннее-тридцати-двух",
        )
    )
    app.config.update(TESTING=True)
    return app.test_client()


@pytest.fixture
def база(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    """Подменённые двери чтения; журнал вызовов — чтобы видеть, что дошло до базы."""
    зовы: dict[str, list[Any]] = {"periods": [], "inspections": [], "maps": []}

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

    def последние(countries: Any, *, until: date) -> tuple[LatestRating, ...]:
        зовы["maps"].append(("latest", list(countries), until))
        оценка = 4.6 if until >= date(2026, 10, 1) else 4.5
        return (
            LatestRating("RS", pointer.GOOGLE, оценка, 100, until),
            LatestRating("RS", pointer.GOOGLE, 4.0, 0, until),
        )

    def пиццерии(*, countries: Any, on: date) -> list[swarm_read.MapUnitRow]:
        зовы["maps"].append(("units", list(countries), on))
        оценка = 4.71 if on >= date(2026, 10, 1) else 4.6
        return [
            swarm_read.MapUnitRow(
                "aa" * 16, "Dodo Beograd", "RS", "Belgrade", pointer.GOOGLE, оценка, 80
            ),
            swarm_read.MapUnitRow(
                "aa" * 16, "Dodo Beograd", "RS", "Belgrade", pointer.YANDEX, 0.0, 0
            ),
        ]

    monkeypatch.setattr(maps_store, "latest", последние)
    monkeypatch.setattr(swarm_read, "map_units", пиццерии)
    monkeypatch.setattr(
        maps_store, "last_ok_load", lambda: datetime(2026, 10, 11, 3, 10, tzinfo=UTC)
    )
    return зовы


@pytest.fixture
def доступ(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Подменённые токены, журнал и счётчик неудач по адресу."""
    состояние: dict[str, Any] = {"журнал": [], "неудачи": 0, "запрет": 0, "недавних": 0}

    def записать(token_id: int | None, path: str, status: int, client: str | None) -> None:
        состояние["журнал"].append((token_id, path, status))

    def неудача(**_: Any) -> web_throttle.Verdict:
        состояние["неудачи"] += 1
        return web_throttle.Verdict()

    monkeypatch.setattr(api_access, "resolve", ТОКЕНЫ.get)
    monkeypatch.setattr(api_access, "recent_requests", lambda *_: состояние["недавних"])
    monkeypatch.setattr(api_access, "log_access", записать)
    monkeypatch.setattr(
        web_throttle,
        "address_verdict",
        lambda **_: web_throttle.Verdict(timedelta(seconds=состояние["запрет"])),
    )
    monkeypatch.setattr(web_throttle, "note_address_failure", неудача)
    return состояние


@pytest.fixture
def клиент(база: dict[str, list[Any]], доступ: dict[str, Any]) -> Iterator[FlaskClient]:
    with _клиент() as client:
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
    клиент: FlaskClient,
    база: dict[str, list[Any]],
    доступ: dict[str, Any],
    адрес: str,
    заголовки: dict[str, str],
) -> None:
    ответ = клиент.get(адрес, headers=заголовки)
    assert ответ.status_code == 401
    assert ответ.get_json()["error"] == "unauthorized"
    assert ответ.headers["WWW-Authenticate"].startswith("Bearer")
    assert база == {"periods": [], "inspections": [], "maps": []}, "до базы дошёл неопознанный"
    assert доступ["неудачи"] == 1, "неудача не записана в счётчик адреса"
    assert доступ["журнал"] == [(None, адрес.split("?")[0], 401)]


@pytest.mark.parametrize("адрес", АДРЕСА)
def test_верный_токен_пускает_и_пишется_в_журнал(
    клиент: FlaskClient, доступ: dict[str, Any], адрес: str
) -> None:
    ответ = клиент.get(адрес, headers=ВЕРНЫЙ)
    assert ответ.status_code == 200, ответ.get_data(as_text=True)
    assert ответ.headers["Cache-Control"] == "private, max-age=300"
    assert доступ["журнал"] == [(1, адрес.split("?")[0], 200)]
    assert доступ["неудачи"] == 0


def test_нет_права_маршрута_403(
    клиент: FlaskClient, база: dict[str, list[Any]], доступ: dict[str, Any]
) -> None:
    заголовки = {"Authorization": f"Bearer {ТОЛЬКО_РЕЙТИНГИ}"}
    assert клиент.get(АДРЕСА[0], headers=заголовки).status_code == 200
    ответ = клиент.get(swarm_api.INSPECTIONS_PATH, headers=заголовки)
    assert ответ.status_code == 403
    assert ответ.get_json()["error"] == "forbidden"
    assert база["inspections"] == [], "до базы дошёл токен без права"
    assert доступ["журнал"][-1] == (2, swarm_api.INSPECTIONS_PATH, 403)


def test_запертый_адрес_отбивает_неверный_токен_без_журнала(
    клиент: FlaskClient, база: dict[str, list[Any]], доступ: dict[str, Any]
) -> None:
    доступ["запрет"] = 90
    ответ = клиент.get(АДРЕСА[0], headers={"Authorization": "Bearer подбор-подбор-подбор-подбор-1"})
    assert ответ.status_code == 429
    assert ответ.get_json()["error"] == "locked"
    assert ответ.headers["Retry-After"] == "90"
    assert база["periods"] == []
    assert доступ["неудачи"] == 0, "запертый адрес копит отметки — перебор не дешевеет"
    assert доступ["журнал"] == [], "отказ запертому адресу раздувает журнал"


def test_верный_токен_проходит_с_запертого_адреса(
    клиент: FlaskClient, база: dict[str, list[Any]], доступ: dict[str, Any]
) -> None:
    """Исходящие адреса Edge Functions общие: чужой перебор не запирает Swarm."""
    доступ["запрет"] = 90
    ответ = клиент.get(АДРЕСА[0], headers=ВЕРНЫЙ)
    assert ответ.status_code == 200
    assert доступ["журнал"][-1][2] == 200


def test_лимит_частоты_на_токен_429(
    клиент: FlaskClient, база: dict[str, list[Any]], доступ: dict[str, Any]
) -> None:
    доступ["недавних"] = swarm_api.RATE_LIMIT_PER_MINUTE - 1
    assert клиент.get(АДРЕСА[0], headers=ВЕРНЫЙ).status_code == 200
    доступ["недавних"] = swarm_api.RATE_LIMIT_PER_MINUTE
    база["periods"].clear()
    ответ = клиент.get(АДРЕСА[0], headers=ВЕРНЫЙ)
    assert ответ.status_code == 429
    assert ответ.get_json()["error"] == "rate_limited"
    assert ответ.headers["Retry-After"] == "60"
    assert база["periods"] == []
    assert доступ["журнал"][-1] == (1, swarm_api.SCORES_PATH, 429)


def test_база_опознания_не_ответила_503_а_не_открыто(
    клиент: FlaskClient, база: dict[str, list[Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    def отказ(_: str) -> None:
        raise AccessError("Не удалось сверить токен API (OperationalError)")

    monkeypatch.setattr(api_access, "resolve", отказ)
    ответ = клиент.get(АДРЕСА[0], headers=ВЕРНЫЙ)
    assert ответ.status_code == 503 and ответ.get_json()["error"] == "db_unavailable"
    assert база["periods"] == []


def test_журнал_не_записался_503(клиент: FlaskClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def отказ(*_: Any) -> None:
        raise AccessError("Не удалось записать обращение к API (OperationalError)")

    monkeypatch.setattr(api_access, "log_access", отказ)
    ответ = клиент.get(АДРЕСА[0], headers=ВЕРНЫЙ)
    assert ответ.status_code == 503 and ответ.get_json()["error"] == "db_unavailable"
    assert "periods" not in ответ.get_data(as_text=True)


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
        (f"{swarm_api.MAPS_PATH}?on=2026-10-32", "bad_date"),
        (f"{swarm_api.MAPS_PATH}?on=2026-10-11&compare=2026-10-11", "bad_range"),
        (f"{swarm_api.MAPS_PATH}?on=2026-10-11&compare=2026-10-12", "bad_range"),
        (f"{swarm_api.MAPS_PATH}?countries=R", "bad_countries"),
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
                "previous": None,
            }
        ],
        "truncated": False,
    }
    (зов,) = база["inspections"]
    assert зов["limit"] == 2, "читается на одну больше предела — так видна обрезка"
    assert зов["reach"].countries == ("GE",) and зов["reach"].tenants is None
    assert зов["date_from"] == date(2026, 10, 1) and зов["date_to"] is None


# --- детали проверки (D391) ------------------------------------------------------

ПРОВЕРКА = "11111111-1111-1111-1111-111111111111"
ПД = {"auditor", "partner", "contact", "chat_id", "city", "comment", "words", "photos"}


def _деталь() -> InspectionDetail:
    шапка = DetailRow(
        id=ПРОВЕРКА,
        tenant_code="HQ",
        unit_name="Batumi-1",
        chat_id=777,
        kind="planned",
        inspection_date=date(2026, 10, 2),
        report_lang="ru",
        checklist_version="1.4",
        pct=97.5,
        grade="A",
        findings_count=2,
        pushed_at="2026-10-02T10:00:00",
        auditor="Аудитор Аудиторович",
        city="Батуми",
        partner="Партнёр",
        contact="+995 000",
    )

    def запись(n: int, code: str, repeat: bool) -> FindingRow:
        return FindingRow(
            id=f"f{n}",
            inspection_id=ПРОВЕРКА,
            unit_name="Batumi-1",
            inspection_date=date(2026, 10, 2),
            n=n,
            code=code,
            level="D1",
            zone="KIT",
            zone_unusual=False,
            source="voice",
            lang="ru",
            text=f"факт {n}",
            comment="комментарий аудитора с именем",
            words="сырые слова",
            repeat=repeat,
        )

    return InspectionDetail(
        inspection=шапка,
        deductions=2.5,
        counts={"D1": 2},
        by_zone={
            "KIT": {
                "code": "KIT",
                "name_ru": "Кухня",
                "name_en": "Kitchen",
                "share": 40,
                "loss": 2.5,
                "left": 37.5,
                "zeroed": False,
            }
        },
        findings=(запись(2, "B2", True), запись(1, "A1", False)),
    )


@pytest.fixture
def деталь(monkeypatch: pytest.MonkeyPatch, база: dict[str, list[Any]]) -> dict[str, Any]:
    зовы: dict[str, Any] = {"one": [], "card": [], "есть": True}
    строка = swarm_read.InspectionRow(
        ПРОВЕРКА,
        "22222222-2222-2222-2222-222222222222",
        None,
        "Batumi-1",
        "GE",
        date(2026, 10, 2),
        "planned",
        97.5,
        "A",
        previous=swarm_read.PreviousInspection(
            "33333333-3333-3333-3333-333333333333", date(2026, 7, 1), 94.0, "B"
        ),
    )

    def одна(**kw: Any) -> swarm_read.InspectionRow | None:
        зовы["one"].append(kw)
        return строка if зовы["есть"] else None

    def карточка(ident: str, **kw: Any) -> InspectionDetail | None:
        зовы["card"].append((ident, kw))
        return _деталь()

    monkeypatch.setattr(swarm_read, "inspection", одна)
    monkeypatch.setattr(queries, "get_inspection", карточка)
    monkeypatch.setattr(
        inspection_titles, "item_titles", lambda v: {"A1": ("Пол чистый", "Floor clean")}
    )
    return зовы


def _ключи(значение: Any) -> set[str]:
    if isinstance(значение, dict):
        return set(значение) | {k for v in значение.values() for k in _ключи(v)}
    if isinstance(значение, list):
        return {k for v in значение for k in _ключи(v)}
    return set()


def test_деталь_проверки_форма(клиент: FlaskClient, деталь: dict[str, Any]) -> None:
    ответ = клиент.get(f"{swarm_api.INSPECTIONS_PATH}/{ПРОВЕРКА.upper()}", headers=ВЕРНЫЙ)
    assert ответ.status_code == 200
    тело = ответ.get_json()
    проверка = тело["inspection"]
    assert проверка["previous"] == {
        "id": "33333333-3333-3333-3333-333333333333",
        "date": "2026-07-01",
        "score_pct": 94.0,
        "grade": "B",
    }
    assert проверка["deductions"] == 2.5 and проверка["counts"] == {"D1": 2}
    assert проверка["zones"] == [
        {
            "zone": "KIT",
            "title_ru": "Кухня",
            "title_en": "Kitchen",
            "share": 40,
            "loss": 2.5,
            "left": 37.5,
            "zeroed": False,
        }
    ]
    assert [f["n"] for f in тело["findings"]] == [1, 2], "записи по номеру"
    assert тело["findings"][0] == {
        "n": 1,
        "code": "A1",
        "title_ru": "Пол чистый",
        "title_en": "Floor clean",
        "level": "D1",
        "zone": "KIT",
        "text": "факт 1",
        "repeat": False,
    }
    assert тело["findings"][1]["title_ru"] is None and тело["findings"][1]["repeat"] is True
    ((ident, kw),) = деталь["card"]
    assert ident == ПРОВЕРКА, "идентификатор приведён к нижнему регистру"
    assert kw["reach"].tenants is None and kw["reach"].countries is None
    assert "include_on_review" not in kw and "include_retracted" not in kw, (
        "деталь читает только принятые — без приёмки и снятых"
    )


def test_деталь_проверки_без_персональных_данных(
    клиент: FlaskClient, деталь: dict[str, Any]
) -> None:
    тело = клиент.get(f"{swarm_api.INSPECTIONS_PATH}/{ПРОВЕРКА}", headers=ВЕРНЫЙ).get_json()
    утекло = _ключи(тело) & ПД
    assert not утекло, f"в ответ попали персональные поля: {утекло}"
    текст = str(тело)
    for значение in ("Аудитор Аудиторович", "Партнёр", "+995 000", "777", "с именем", "сырые"):
        assert значение not in текст, f"в ответ попало «{значение}»"


def test_деталь_проверки_нет_такой_404(клиент: FlaskClient, деталь: dict[str, Any]) -> None:
    деталь["есть"] = False
    ответ = клиент.get(f"{swarm_api.INSPECTIONS_PATH}/{ПРОВЕРКА}", headers=ВЕРНЫЙ)
    assert ответ.status_code == 404
    assert ответ.get_json()["error"] == "not_found"
    assert деталь["card"] == [], "без принятой строки карточка не читается"


@pytest.mark.parametrize("ident", ["не-uuid", "1111", f"{ПРОВЕРКА}x", "' or 1=1 --"])
def test_деталь_проверки_кривой_id_400(
    клиент: FlaskClient, деталь: dict[str, Any], ident: str
) -> None:
    ответ = клиент.get(f"{swarm_api.INSPECTIONS_PATH}/{ident}", headers=ВЕРНЫЙ)
    assert ответ.status_code == 400
    assert ответ.get_json()["error"] == "bad_id"
    assert деталь["one"] == [] and деталь["card"] == []


def test_деталь_проверки_без_права_403(
    клиент: FlaskClient, деталь: dict[str, Any], доступ: dict[str, Any]
) -> None:
    ответ = клиент.get(
        f"{swarm_api.INSPECTIONS_PATH}/{ПРОВЕРКА}",
        headers={"Authorization": f"Bearer {ТОЛЬКО_РЕЙТИНГИ}"},
    )
    assert ответ.status_code == 403
    assert деталь["one"] == []
    assert доступ["журнал"][-1] == (2, f"{swarm_api.INSPECTIONS_PATH}/{ПРОВЕРКА}", 403)


def test_деталь_проверки_без_токена_401(клиент: FlaskClient, деталь: dict[str, Any]) -> None:
    assert клиент.get(f"{swarm_api.INSPECTIONS_PATH}/{ПРОВЕРКА}").status_code == 401
    assert деталь["one"] == []


# --- оценки на картах (D390) ---------------------------------------------------


def test_карты_страны_и_пиццерии_со_сравнением(
    клиент: FlaskClient, база: dict[str, list[Any]]
) -> None:
    ответ = клиент.get(f"{swarm_api.MAPS_PATH}?on=2026-10-11&compare=2026-09-11", headers=ВЕРНЫЙ)
    assert ответ.status_code == 200, ответ.get_data(as_text=True)
    тело = ответ.get_json()
    assert тело["on"] == "2026-10-11" and тело["compare"] == "2026-09-11"
    assert тело["providers"] == ["google", "yandex"]
    assert тело["loaded_at"] == "2026-10-11T03:10:00Z"
    [страна] = тело["countries"]
    assert страна["cc"] == "RS" and страна["as_of"] == "2026-10-11"
    # Филиал без отзывов в среднюю не входит, но в счёт филиалов — да (maps.summarize).
    assert страна["maps"]["google"] == {"avg": 4.6, "reviews": 100, "branches": 2, "delta": 0.1}
    assert страна["maps"]["yandex"] == {"avg": None, "reviews": 0, "branches": 0, "delta": None}
    assert тело["units"] == [
        {
            "id": "aa" * 16,
            "name": "Dodo Beograd",
            "cc": "RS",
            "city": "Belgrade",
            "maps": {"google": {"avg": 4.71, "reviews": 80, "prev_avg": 4.6}, "yandex": None},
        }
    ]
    assert ("units", ["RS"], date(2026, 9, 11)) in база["maps"], "страны по умолчанию — не IMF"


def test_карты_без_сравнения_и_дата_по_умолчанию(
    клиент: FlaskClient, база: dict[str, list[Any]]
) -> None:
    тело = клиент.get(f"{swarm_api.MAPS_PATH}?countries=rs", headers=ВЕРНЫЙ).get_json()
    сегодня = datetime.now(UTC).date()
    assert тело["on"] == сегодня.isoformat() and тело["compare"] is None
    assert тело["countries"][0]["maps"]["google"]["delta"] is None
    assert тело["units"][0]["maps"]["google"]["prev_avg"] is None
    assert база["maps"] == [("latest", ["RS"], сегодня), ("units", ["RS"], сегодня)]


def test_карты_с_токеном_без_права_рейтингов_403(
    клиент: FlaskClient, база: dict[str, list[Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    без_рейтингов = "токен-только-с-правом-проверок-тоже-очень-длинный"
    monkeypatch.setattr(
        api_access,
        "resolve",
        lambda t: (
            api_access.ApiToken(3, "x", (api_access.SCOPE_INSPECTIONS_READ,))
            if t == без_рейтингов
            else None
        ),
    )
    ответ = клиент.get(swarm_api.MAPS_PATH, headers={"Authorization": f"Bearer {без_рейтингов}"})
    assert ответ.status_code == 403
    assert база["maps"] == []
