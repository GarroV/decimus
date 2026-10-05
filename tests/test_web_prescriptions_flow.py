"""Сквозной путь предписания — через настоящую базу, двери и экраны (волна 3).

УК составляет предписание Грузии → письмо ложится черновиком в Gmail
сотрудника (Gmail подменён) → предписание действует, адресаты запомнены →
партнёр Грузии видит его у себя и отвечает комментарием с файлом → УК
закрывает с комментарием → на экране страны видно предписание и «Закрыто».
Партнёр Армении ничего из этого не видит, раздел УК отвечает ему 404.

Подменены только опознание, хранилище файлов и разговор с Google — база с
ролями и триггерами `0037`, маршруты и шаблоны настоящие.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from conftest import requires_db
from db_harness import set_retraction_env, привязать_страну, точка_справочника
from flask.testing import FlaskClient
from web_harness import войти, подменить_двери, собрать

pytest.importorskip("psycopg")

from src.db import prescriptions as rx
from src.db import prescriptions_write as rxw
from src.db.accept import accept_inspection
from src.db.reach import reach_of

pytestmark = requires_db

ORIGIN = {"Origin": "http://localhost"}
СРОК = (datetime.now(UTC).date() + timedelta(days=10)).isoformat()


class Хранилище:
    def __init__(self) -> None:
        self.объекты: dict[str, bytes] = {}

    def put(self, key: str, data: bytes, *, content_type: str) -> str:
        self.объекты[key] = data
        return f"s3://test/{key}"

    def get(self, key: str) -> bytes:
        return self.объекты[key]

    def delete(self, key: str) -> None:
        self.объекты.pop(key, None)


Вход = Callable[[str], FlaskClient]


@pytest.fixture
def почта(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Gmail подменён: черновики пишутся сюда. Реквизиты Google — как на стенде."""
    from src.web import letter_draft
    from src.web import prescriptions as web_rx

    for имя, значение in {
        "GOOGLE_CLIENT_ID": "клиент.apps.googleusercontent.com",
        "GOOGLE_CLIENT_SECRET": "секрет",
        "GOOGLE_REDIRECT_URI": "https://стенд/auth/google/callback",
        "GOOGLE_MAIL_REDIRECT_URI": "https://стенд/auth/google/mail",
    }.items():
        monkeypatch.setenv(имя, значение)
    черновики: list[dict[str, Any]] = []
    monkeypatch.setattr(letter_draft, "exchange_code_for_token", lambda _s, *, code: "токен")

    def положить(token: str, *, to: str, subject: str, body: str, **_: Any) -> str:
        черновики.append({"token": token, "to": to, "subject": subject, "body": body})
        return "черновик-1"

    monkeypatch.setattr(web_rx, "create_draft", положить)
    return черновики


@pytest.fixture
def как(pg_dsn: str, db_env: str, domain_env: Path, monkeypatch: pytest.MonkeyPatch) -> Вход:
    """`как("GE")` — клиент, вошедший человеком этого пространства."""
    set_retraction_env(db_env, monkeypatch)
    точка_справочника("Batumi-1", country="GE", city="Batumi")
    точка_справочника("Yerevan-1", country="AM", city="Yerevan")
    привязать_страну(pg_dsn, tenant="GE", country="GE")
    привязать_страну(pg_dsn, tenant="AM", country="AM")
    склад = Хранилище()
    monkeypatch.setattr(rxw, "S3PhotoStorage", lambda _settings: склад)
    monkeypatch.setattr(rxw, "load_storage_settings", lambda: None)
    monkeypatch.setattr(rx, "S3PhotoStorage", lambda _settings: склад)
    monkeypatch.setattr(rx, "load_storage_settings", lambda: None)

    def войти_как(tenant: str) -> FlaskClient:
        подменить_двери(monkeypatch, tenant=tenant, role="admin")
        monkeypatch.setattr("src.web.auth.reach_of", reach_of)
        client = собрать(tenant=tenant).test_client()
        assert войти(client).status_code == 302
        return client

    return войти_как


def _проверка_уК() -> str:
    from src.db.push import push_inspection
    from src.domain import add_finding, start_inspection

    start_inspection(9_600_001, unit="Batumi-1", kind="planned", report_lang="ru", tenant="HQ")
    add_finding(9_600_001, code="PRD02", level="D2", zone="cold_kitchen", text="партии вместе")
    ident = push_inspection(9_600_001)
    accept_inspection(ident, tenant="HQ", actor="hq-lead")
    return ident


def test_путь_предписания(как: Вход, почта: list[dict[str, Any]]) -> None:
    # Arrange
    основание = _проверка_уК()
    уК = как("HQ")
    форма = уК.get("/actions/prescriptions/new?country=GE&lang=ru").get_data(as_text=True)
    assert "Batumi-1" in форма and основание in форма, "в форме нет пиццерии или проверки"

    # Act — составить и сразу положить в Gmail.
    уход = уК.post(
        "/actions/prescriptions?lang=ru",
        data={
            "country": "GE",
            "unit": [],
            "inspection": [основание],
            "due": СРОК,
            "recipients": "ops@ge.example.com",
            "subject": "Предписание · Грузия",
            "body": "Устраните нарушения хранения.\nСрок — десять дней.",
            "then": "send",
        },
        headers=ORIGIN,
    )
    assert уход.status_code == 302, уход.get_data(as_text=True)[:400]
    метка = parse_qs(urlsplit(уход.headers["Location"]).query)["state"][0]
    возврат = уК.get(f"/auth/google/mail?state={метка}&code=код")

    # Assert — черновик лёг, предписание действует, адресаты запомнены.
    assert возврат.status_code == 303 and "gmail=ok" in возврат.headers["Location"]
    assert [ч["to"] for ч in почта] == ["ops@ge.example.com"]
    assert "Срок — десять дней." in почта[0]["body"]
    список = rx.list_prescriptions(reach=reach_of("HQ"))
    (п,) = список.rows
    assert п.status == "issued" and п.whole_country
    assert rx.remembered_recipients("GE") == "ops@ge.example.com"
    assert 'value="ops@ge.example.com"' in уК.get(
        "/actions/prescriptions/new?country=GE&lang=ru"
    ).get_data(as_text=True)

    # Партнёр Грузии видит предписание и отвечает файлом с комментарием.
    грузия = как("GE")
    assert "Предписание · Грузия" in грузия.get("/prescriptions?lang=ru").get_data(as_text=True)
    ответ = грузия.post(
        f"/prescriptions/{п.id}/reply?lang=ru",
        data={"comment": "Разделили партии", "file": (io.BytesIO(b"%PDF fix"), "акт.pdf")},
        headers=ORIGIN,
        content_type="multipart/form-data",
    )
    assert ответ.status_code == 200, ответ.get_data(as_text=True)[:400]
    assert "Ответ сохранён" in ответ.get_data(as_text=True)

    # Партнёр Армении не видит ничего, раздел УК ему закрыт.
    армения = как("AM")
    файл = rx.get_prescription(п.id, reach=reach_of("HQ"))
    assert файл is not None and файл.replies[0].file_name == "акт.pdf"
    assert "Предписание · Грузия" not in армения.get("/prescriptions?lang=ru").get_data(
        as_text=True
    )
    assert армения.get(f"/prescriptions/{п.id}").status_code == 404
    assert армения.get(f"/prescriptions/files/{файл.replies[0].id}").status_code == 404
    assert армения.get("/actions/prescriptions").status_code == 404
    assert армения.get(f"/actions/prescriptions/{п.id}").status_code == 404
    assert "Предписание · Грузия" not in армения.get("/country/AM?lang=ru").get_data(as_text=True)

    # УК видит ответ, скачивает файл и закрывает с комментарием.
    уК = как("HQ")
    карточка = уК.get(f"/actions/prescriptions/{п.id}?lang=ru").get_data(as_text=True)
    assert "Разделили партии" in карточка
    скачано = уК.get(f"/prescriptions/files/{файл.replies[0].id}")
    assert скачано.status_code == 200 and скачано.data == b"%PDF fix"
    закрыто = уК.post(
        f"/actions/prescriptions/{п.id}/close?lang=ru",
        data={"comment": "Выполнено, проверили на месте"},
        headers=ORIGIN,
    )
    assert "Предписание закрыто." in закрыто.get_data(as_text=True)

    # На экране страны — предписание и «Закрыто»; партнёру тоже.
    страна = уК.get("/country/GE?lang=ru").get_data(as_text=True)
    assert "Предписание · Грузия" in страна and "Закрыто" in страна
    грузия = как("GE")
    assert "Предписание · Грузия" in грузия.get("/country/GE?lang=ru").get_data(as_text=True)
    итог = rx.get_prescription(п.id, reach=reach_of("HQ"))
    assert итог is not None
    assert [e.action for e in итог.events] == ["created", "issued", "replied", "closed"]


def test_черновик_партнёр_не_видит_нигде(как: Вход) -> None:
    уК = как("HQ")
    ответ = уК.post(
        "/actions/prescriptions?lang=ru",
        data={
            "country": "GE",
            "due": СРОК,
            "recipients": "ops@ge.example.com",
            "subject": "Черновая тема",
            "body": "текст",
            "then": "save",
        },
        headers=ORIGIN,
    )
    assert ответ.status_code == 303
    ident = ответ.headers["Location"].split("/actions/prescriptions/")[1].split("?")[0]
    грузия = как("GE")
    assert "Черновая тема" not in грузия.get("/prescriptions?lang=ru").get_data(as_text=True)
    assert грузия.get(f"/prescriptions/{ident}").status_code == 404
    assert "Черновая тема" not in грузия.get("/country/GE?lang=ru").get_data(as_text=True)
