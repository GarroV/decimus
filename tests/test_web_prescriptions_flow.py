"""Сквозной путь предписания — через настоящую базу, двери и экраны (волна 3).

ОСБ составляет и согласует предписание Грузии, отправляет → письмо ложится
черновиком в Gmail сотрудника (Gmail подменён) → предписание действует,
адресаты запомнены →
партнёр Грузии видит его у себя и отвечает комментарием с файлом → УК
закрывает с комментарием → на экране страны видно предписание и «Закрыто».
Партнёр Армении ничего из этого не видит, раздел УК отвечает ему 404.
Девелопер и админ УК формируют предписание только из проверки и запрашивают
согласование; согласовать, вернуть, отправить и закрыть им нельзя (D599, D600).

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
from src.web.google_mail import MailGrant

pytestmark = requires_db

ORIGIN = {"Origin": "http://localhost"}
СРОК = (datetime.now(UTC).date() + timedelta(days=10)).isoformat()
#: Почта входа через Google у вошедшего: черновик ложится только в неё (D176).
ПОЧТА = "lead@example.com"
ГРАНТ = MailGrant("токен", ПОЧТА)


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


Вход = Callable[..., FlaskClient]
#: Роль сотрудника УК по умолчанию — ОСБ: ведёт предписание целиком (D599, D600).
#: У партнёра пространства роль админа — как было.
РОЛЬ_УК = "osb"


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
    monkeypatch.setattr(letter_draft, "exchange_code_for_grant", lambda _s, *, code: ГРАНТ)

    def положить(token: str, *, to: str, subject: str, body: str, **_: Any) -> str:
        черновики.append({"token": token, "to": to, "subject": subject, "body": body})
        return "черновик-1"

    monkeypatch.setattr(web_rx, "create_draft", положить)
    return черновики


@pytest.fixture
def как(pg_dsn: str, db_env: str, domain_env: Path, monkeypatch: pytest.MonkeyPatch) -> Вход:
    """`как("GE")` — клиент, вошедший человеком этого пространства.

    В HQ без роли входит ОСБ; `как("HQ", role="developer")` — девелопер или админ УК.
    """
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

    def войти_как(tenant: str, role: str | None = None) -> FlaskClient:
        роль = role or (РОЛЬ_УК if tenant == "HQ" else "admin")
        # Входит оснастка паролем, а учётке с почтой Google пароль закрыт:
        # почта появляется у сессии после входа — как у вошедшего через Google.
        подменить_двери(monkeypatch, tenant=tenant, role=роль)
        monkeypatch.setattr("src.web.auth.reach_of", reach_of)
        client = собрать(tenant=tenant).test_client()
        assert войти(client).status_code == 302
        подменить_двери(monkeypatch, tenant=tenant, role=роль, email=ПОЧТА)
        monkeypatch.setattr("src.web.auth.reach_of", reach_of)
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


def _отбор(основание: str) -> dict[str, list[str]]:
    """Поля формы шага 3: отмечена единственная запись проверки (её добавил ОСБ сам)."""
    import psycopg

    from src.db.config import load_retraction_settings

    with psycopg.connect(load_retraction_settings().dsn) as conn:
        записи = [
            str(r[0])
            for r in conn.execute(
                "select id from findings where inspection_id = %s", (основание,)
            ).fetchall()
        ]
    return {"finding_shown": записи, "finding": записи}


def test_путь_предписания(как: Вход, почта: list[dict[str, Any]]) -> None:
    # Arrange
    основание = _проверка_уК()
    уК = как("HQ")
    форма = уК.get("/actions/prescriptions/new?country=GE&lang=ru").get_data(as_text=True)
    assert "Batumi-1" in форма and основание in форма, "в форме нет пиццерии или проверки"

    # Act — составить и согласовать, затем отправить: ответ ведёт в Google.
    составлено = уК.post(
        "/actions/prescriptions?lang=ru",
        data={
            "country": "GE",
            "unit": [],
            "inspection": [основание],
            **_отбор(основание),
            "due": СРОК,
            "recipients": "ops@ge.example.com",
            "subject": "Предписание · Грузия",
            "body": "Устраните нарушения хранения.\nСрок — десять дней.",
            "then": "approve",
        },
        headers=ORIGIN,
    )
    assert составлено.status_code == 303, составлено.get_data(as_text=True)[:400]
    (согласовано,) = rx.list_prescriptions(reach=reach_of("HQ")).rows
    assert согласовано.status == "approved"
    уход = уК.post(f"/actions/prescriptions/{согласовано.id}/send?lang=ru", headers=ORIGIN)
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
    assert "Предписание · Грузия" in грузия.get(
        "/prescriptions?lang=ru", follow_redirects=True
    ).get_data(as_text=True)
    ответ = грузия.post(
        f"/actions/prescriptions/{п.id}/reply?lang=ru",
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
    assert "Предписание · Грузия" not in армения.get(
        "/prescriptions?lang=ru", follow_redirects=True
    ).get_data(as_text=True)
    assert "Предписание · Грузия" not in армения.get(
        f"/prescriptions/{п.id}", follow_redirects=True
    ).get_data(as_text=True)
    assert (
        армения.get(f"/prescriptions/files/{файл.replies[0].id}", follow_redirects=True).status_code
        == 404
    )
    # Составление и правка — раздел УК: партнёру 404 (старый адрес списка лишь переадресует).
    assert армения.get("/actions/prescriptions/new?country=AM").status_code == 404
    assert армения.get(f"/actions/prescriptions/{п.id}/edit").status_code == 404
    assert армения.get(f"/actions/prescriptions/{п.id}").status_code in (303, 404)
    assert "Предписание · Грузия" not in армения.get(
        f"/actions/prescriptions/{п.id}", follow_redirects=True
    ).get_data(as_text=True)
    # «Пиццерии» партнёр видит в пределах своих стран (D512): своя — да, чужая — 404.
    assert армения.get("/country/AM?lang=ru").status_code == 200
    assert армения.get("/country/GE?lang=ru").status_code == 404

    # УК видит ответ, скачивает файл и закрывает с комментарием.
    уК = как("HQ")
    карточка = уК.get(f"/osb?id={п.id}&lang=ru").get_data(as_text=True)
    assert "Разделили партии" in карточка
    закрыто = уК.post(
        f"/actions/prescriptions/{п.id}/close?lang=ru",
        data={"comment": "Выполнено, проверили на месте"},
        headers=ORIGIN,
    )
    assert "Предписание закрыто." in закрыто.get_data(as_text=True)
    скачано = уК.get(f"/actions/prescription-files/{файл.replies[0].id}")
    assert скачано.status_code == 200 and скачано.data == b"%PDF fix"

    # На карточке УК в «Действиях» — предписание и «Закрыто» («Пиццерии» его
    # не показывают, D512). Партнёр видит «Закрыто» на карточке в своём разделе.
    список = уК.get(f"/osb?id={п.id}&lang=ru").get_data(as_text=True)
    assert "Предписание · Грузия" in список and "Закрыто" in список
    грузия = как("GE")
    своё = грузия.get(f"/prescriptions/{п.id}?lang=ru", follow_redirects=True).get_data(
        as_text=True
    )
    assert "Закрыто" in своё
    итог = rx.get_prescription(п.id, reach=reach_of("HQ"))
    assert итог is not None
    assert [e.action for e in итог.events] == ["created", "approved", "issued", "replied", "closed"]


def test_черновик_партнёр_не_видит_нигде(как: Вход) -> None:
    основание = _проверка_уК()
    уК = как("HQ")
    ответ = уК.post(
        "/actions/prescriptions?lang=ru",
        data={
            "country": "GE",
            "due": СРОК,
            "recipients": "ops@ge.example.com",
            "subject": "Черновая тема",
            "body": "текст",
            "inspection": [основание],
            **_отбор(основание),
            "then": "save",
        },
        headers=ORIGIN,
    )
    assert ответ.status_code == 303
    ident = _ident(ответ)
    грузия = как("GE")
    assert "Черновая тема" not in грузия.get(
        "/prescriptions?lang=ru", follow_redirects=True
    ).get_data(as_text=True)
    assert "Черновая тема" not in грузия.get(
        f"/prescriptions/{ident}", follow_redirects=True
    ).get_data(as_text=True)


def _составить(клиент: FlaskClient, основание: str, *, then: str) -> Any:
    return клиент.post(
        "/actions/prescriptions?lang=ru",
        data={
            "country": "GE",
            "inspection": [основание],
            **_отбор(основание),
            "due": СРОК,
            "recipients": "ops@ge.example.com",
            "subject": "Предписание от девелопера",
            "body": "Устраните нарушения.",
            "then": then,
        },
        headers=ORIGIN,
    )


def _ident(ответ: Any) -> str:
    return parse_qs(urlsplit(ответ.headers["Location"]).query)["id"][0]


def test_путь_девелопера_запрос_согласование_отправка(
    как: Вход, почта: list[dict[str, Any]]
) -> None:
    # Arrange
    основание = _проверка_уК()
    девелопер = как("HQ", role="developer")

    # Act — девелопер формирует с основанием и запрашивает согласование.
    составлено = _составить(девелопер, основание, then="request")
    assert составлено.status_code == 303, составлено.get_data(as_text=True)[:400]
    ident = _ident(составлено)
    (запрошено,) = rx.list_prescriptions(reach=reach_of("HQ")).rows
    assert запрошено.status == "review"

    # Партнёр на согласовании ничего не видит.
    assert "Предписание от девелопера" not in как("GE").get(
        f"/prescriptions/{ident}", follow_redirects=True
    ).get_data(as_text=True)

    # ОСБ согласует и отправляет: письмо ложится в Gmail того, кто нажал.
    осб = как("HQ")
    assert (
        осб.post(f"/actions/prescriptions/{ident}/approve?lang=ru", headers=ORIGIN).status_code
        == 200
    )
    (согласовано,) = rx.list_prescriptions(reach=reach_of("HQ")).rows
    assert согласовано.status == "approved"
    уход = осб.post(f"/actions/prescriptions/{ident}/send?lang=ru", headers=ORIGIN)
    assert уход.status_code == 302, уход.get_data(as_text=True)[:400]
    метка = parse_qs(urlsplit(уход.headers["Location"]).query)["state"][0]
    возврат = осб.get(f"/auth/google/mail?state={метка}&code=код")

    # Assert
    assert возврат.status_code == 303 and "gmail=ok" in возврат.headers["Location"]
    assert [ч["to"] for ч in почта] == ["ops@ge.example.com"]
    (итог,) = rx.list_prescriptions(reach=reach_of("HQ")).rows
    assert итог.status == "issued"
    assert "Предписание от девелопера" in как("GE").get(
        "/prescriptions?lang=ru", follow_redirects=True
    ).get_data(as_text=True)


@pytest.mark.parametrize("роль", ["developer", "admin"])
def test_девелопер_и_админ_не_согласуют_и_не_отправляют(
    как: Вход, почта: list[dict[str, Any]], роль: str
) -> None:
    # Arrange — запрос на согласование уже лежит у ОСБ.
    основание = _проверка_уК()
    клиент = как("HQ", role=роль)
    ident = _ident(_составить(клиент, основание, then="request"))

    def статус() -> str:
        (п,) = rx.list_prescriptions(reach=reach_of("HQ")).rows
        return п.status

    # Act / Assert — каждое действие ведущего отвечает отказом, статус не сдвигается.
    for действие, данные in (
        ("approve", {}),
        ("return", {"comment": "верните"}),
        ("send", {}),
        ("close", {"comment": "закрыто"}),
    ):
        ответ = клиент.post(
            f"/actions/prescriptions/{ident}/{действие}?lang=ru", data=данные, headers=ORIGIN
        )
        assert ответ.status_code == 403, (действие, ответ.status_code)
        assert статус() == "review", действие
    assert почта == []

    # «Составить и согласовать» одним шагом тоже закрыто — после отказа нового нет.
    сразу = _составить(клиент, основание, then="approve")
    assert сразу.status_code == 403
    assert len(rx.list_prescriptions(reach=reach_of("HQ")).rows) == 1


@pytest.mark.parametrize("роль", ["developer", "admin"])
def test_без_проверки_основания_девелопер_и_админ_получают_отказ(как: Вход, роль: str) -> None:
    ответ = как("HQ", role=роль).post(
        "/actions/prescriptions?lang=ru",
        data={
            "country": "GE",
            "due": СРОК,
            "recipients": "ops@ge.example.com",
            "subject": "Без основания",
            "body": "текст",
            "then": "request",
        },
        headers=ORIGIN,
    )
    assert ответ.status_code == 400
    assert rx.list_prescriptions(reach=reach_of("HQ")).rows == ()
