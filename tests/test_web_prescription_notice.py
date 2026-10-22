"""Предписание по проверке в вебе, насквозь: форма с галочками → документ PDF → письмо с вложением.

Настоящие база, движок (синтетическая методика `tests/methodology`), маршруты и
шаблоны; подменены опознание и разговор с Google. Проверяется то, что видит и
получает человек: какие записи отмечены, что попало в документ, что лежит в
письме. Сам отбор — `test_notice_core.py`.
"""

from __future__ import annotations

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

from src.db import country_contracts as contracts
from src.db import prescriptions as rx
from src.db.accept import accept_inspection
from src.db.reach import reach_of
from src.report import notice_pdf
from src.web.google_mail import MailGrant

pytestmark = requires_db

ORIGIN = {"Origin": "http://localhost"}
ПОЧТА = "osb@example.com"
СЕГОДНЯ = datetime.now(UTC).date()
СРОК = (СЕГОДНЯ + timedelta(days=30)).isoformat()


@pytest.fixture
def письма(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Gmail подменён: черновики с вложениями пишутся сюда."""
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
    monkeypatch.setattr(
        letter_draft, "exchange_code_for_grant", lambda _s, *, code: MailGrant("токен", ПОЧТА)
    )

    def положить(token: str, **письмо: Any) -> str:
        черновики.append(письмо)
        return "черновик-1"

    monkeypatch.setattr(web_rx, "create_draft", положить)
    return черновики


@pytest.fixture
def осб(
    pg_dsn: str, db_env: str, domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> Callable[[], FlaskClient]:
    set_retraction_env(db_env, monkeypatch)
    точка_справочника("Batumi-1", country="GE", city="Batumi")
    привязать_страну(pg_dsn, tenant="GE", country="GE")

    def войти_осб() -> FlaskClient:
        подменить_двери(monkeypatch, tenant="HQ", role="osb")
        monkeypatch.setattr("src.web.auth.reach_of", reach_of)
        client = собрать(tenant="HQ").test_client()
        assert войти(client).status_code == 302
        подменить_двери(monkeypatch, tenant="HQ", role="osb", email=ПОЧТА)
        monkeypatch.setattr("src.web.auth.reach_of", reach_of)
        return client

    return войти_осб


@pytest.fixture
def осб_партнёром(monkeypatch: pytest.MonkeyPatch) -> Callable[[], FlaskClient]:
    """Вошедший партнёр Грузии: документ предписания ему не открывается."""

    def войти_партнёром() -> FlaskClient:
        подменить_двери(monkeypatch, tenant="GE", role="admin")
        monkeypatch.setattr("src.web.auth.reach_of", reach_of)
        client = собрать(tenant="GE").test_client()
        assert войти(client).status_code == 302
        return client

    return войти_партнёром


def _проверка() -> str:
    """Проверка УК: D3 и D1 в одной зоне (обе по правилу) и D1 в другой (не по правилу)."""
    from src.db.push import push_inspection
    from src.domain import add_finding, start_inspection

    start_inspection(9_610_001, unit="Batumi-1", kind="planned", report_lang="ru", tenant="HQ")
    add_finding(9_610_001, code="PRD04", level="D3", zone="fridge", text="кадр холодильника")
    add_finding(9_610_001, code="PRD07", level="D1", zone="fridge", text="ярлык")
    add_finding(9_610_001, code="PRD06", level="D1", zone="hot_kitchen", text="плита")
    ident = push_inspection(9_610_001)
    accept_inspection(ident, tenant="HQ", actor="hq-lead")
    return ident


def _записи(ident: str) -> dict[str, str]:
    """Код пункта → идентификатор записи."""
    import psycopg

    from src.db.config import load_retraction_settings

    with psycopg.connect(load_retraction_settings().dsn) as conn:
        rows = conn.execute(
            "select code, id from findings where inspection_id = %s", (ident,)
        ).fetchall()
    return {str(r[0]): str(r[1]) for r in rows}


def test_форма_отмечает_по_правилу_документ_берёт_отмеченное_письмо_с_pdf(
    осб: Callable[[], FlaskClient],
    осб_партнёром: Callable[[], FlaskClient],
    письма: list[dict[str, Any]],
) -> None:
    # Arrange
    основание = _проверка()
    записи = _записи(основание)
    contracts.save(
        "GE",
        contracts.ContractFields(
            legal_name="Test Franchisee LLC",
            agreement="Franchise Agreement No. T-1 dated 01.01.2020",
            dkk_emails="ops@ge.example.com",
        ),
        actor="osb",
    )
    клиент = осб()

    # Act — форма с карточки: отмечены D3 и D1 обнулённой зоны, D1 другой зоны — нет.
    форма = клиент.get(f"/actions/prescriptions/new?inspection={основание}&lang=en")
    html = форма.get_data(as_text=True)
    assert форма.status_code == 200
    for код in ("PRD04", "PRD07", "PRD06"):
        assert f'value="{записи[код]}"' in html
    отмечено = {
        код for код, ident in записи.items() if f'name="finding" value="{ident}" checked' in html
    }
    assert отмечено == {"PRD04", "PRD07"}
    assert f'value="{СРОК}"' in html, "срок по умолчанию — 30 дней"

    # Act — сохранить как есть и согласовать.
    данные = {
        "country": "GE",
        "inspection": [основание],
        "due": СРОК,
        "recipients": "ops@ge.example.com",
        "subject": "Notice",
        "body": "Please see the attached notice.",
        "finding_shown": list(записи.values()),
        "finding": [записи["PRD04"], записи["PRD07"]],
        "then": "approve",
    }
    сохранено = клиент.post("/actions/prescriptions?lang=en", data=данные, headers=ORIGIN)
    assert сохранено.status_code == 303, сохранено.get_data(as_text=True)[:400]
    (п,) = rx.list_prescriptions(reach=reach_of("HQ")).rows
    assert (п.status, п.kind, п.has_document) == ("approved", "inspection", True)
    assert {f.finding_id: f.included for f in п.findings} == {
        записи["PRD04"]: True,
        записи["PRD07"]: True,
        записи["PRD06"]: False,
    }

    # Assert — документ: только включённые записи, пункт по-английски, сведения договора.
    документ = notice_pdf.render_html(notice_pdf.document_of(п, reach=reach_of("HQ"), on=СЕГОДНЯ))
    assert "Test Franchisee LLC" in документ and "{{" not in документ
    assert документ.count("<tr><td>Batumi-1</td>") >= 3  # визит и две записи
    ответ = клиент.get(f"/actions/prescriptions/{п.id}/document.pdf")
    assert ответ.status_code == 200, ответ.get_data(as_text=True)[-300:]
    assert ответ.mimetype == "application/pdf"
    assert ответ.data.startswith(b"%PDF-")

    # Act — в почту: письмо с PDF во вложении, «Кому» — контакты по ДКК.
    уход = клиент.post(f"/actions/prescriptions/{п.id}/send?lang=en", headers=ORIGIN)
    метка = parse_qs(urlsplit(уход.headers["Location"]).query)["state"][0]
    возврат = клиент.get(f"/auth/google/mail?state={метка}&code=код")
    assert возврат.status_code == 303 and "gmail=ok" in возврат.headers["Location"]
    (письмо,) = письма
    assert письмо["to"] == "ops@ge.example.com"
    (вложение,) = письмо["attachments"]
    assert вложение.content_type == "application/pdf" and вложение.data.startswith(b"%PDF-")
    assert вложение.filename.startswith("Notice GE ") and вложение.filename.endswith(".pdf")

    # Assert — партнёру документ не открывается.
    партнёр = осб_партнёром()
    assert партнёр.get(f"/actions/prescriptions/{п.id}/document.pdf").status_code == 404


def test_без_отмеченных_записей_предписание_не_сохраняется(
    осб: Callable[[], FlaskClient],
) -> None:
    основание = _проверка()
    записи = _записи(основание)
    клиент = осб()
    ответ = клиент.post(
        "/actions/prescriptions?lang=en",
        data={
            "country": "GE",
            "inspection": [основание],
            "due": СРОК,
            "recipients": "ops@ge.example.com",
            "subject": "Notice",
            "body": "text",
            "finding_shown": list(записи.values()),
            "then": "save",
        },
        headers=ORIGIN,
    )
    assert ответ.status_code == 400
    assert "хотя бы одно нарушение" in ответ.get_data(as_text=True)
    assert rx.list_prescriptions(reach=reach_of("HQ")).rows == ()
