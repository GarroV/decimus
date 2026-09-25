"""Уход письма в черновики Gmail: что происходит на маршрутах (T352, #332).

Живого Google здесь нет и не нужно: наружу ходят ровно две двери
(`exchange_code_for_token`, `create_draft`), они подменяются, и проверяется то,
чья ошибка молчит:

* письмо **фиксируется до** ухода за согласием — иначе правки человека умирают
  вместе со страницей;
* черновик собирается из **зафиксированного** текста, а не из заготовки;
* подделанный возврат не доходит до почты;
* отказ человека в окне согласия — не поломка и не «черновик создан».
"""

from __future__ import annotations

import urllib.parse
from collections.abc import Iterator
from datetime import date, datetime
from typing import Any

import pytest
from flask.testing import FlaskClient
from web_harness import СВОЙ, войти, подменить_двери, собрать

from src.db.letters import SavedLetter
from src.db.models import InspectionDetail, InspectionRow
from src.web import inspections as data
from src.web import letter_draft
from src.web.google_mail import DRAFT_SCOPE

ТЕНАНТ = "default"
ПРОВЕРКА = "11111111-1111-1111-1111-111111111111"
ЗАФИКСИРОВАННОЕ = "Здравствуйте! Это письмо человек подтвердил."


def карточка() -> InspectionDetail:
    шапка = InspectionRow(
        id=ПРОВЕРКА,
        tenant_code=ТЕНАНТ,
        unit_name="Demo Pizzeria #1",
        chat_id=1,
        kind="planned",
        inspection_date=date(2026, 9, 12),
        report_lang="ru",
        checklist_version="2026-09",
        pct=97.5,
        grade="A",
        findings_count=5,
        pushed_at="2026-09-12T10:00:00",
        auditor="Аудитор",
        city="Белград",
        partner="Партнёр",
        contact="partner@example.com",
    )
    return InspectionDetail(
        inspection=шапка, deductions=2.5, counts={}, by_zone={}, findings=(), info=()
    )


@pytest.fixture
def клиент(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[FlaskClient, dict[str, list[Any]]]]:
    подменить_двери(monkeypatch, tenant=ТЕНАНТ)
    следы: dict[str, list[Any]] = {"remember": [], "draft": [], "token": []}

    monkeypatch.setattr(data, "load_card", lambda _id, *, tenant: карточка())

    def _remember(inspection_id: str, *, body: str, lang: str, saved_by: str) -> SavedLetter:
        следы["remember"].append((inspection_id, body, lang, saved_by))
        return SavedLetter(
            id="l-1", body=body, lang=lang, saved_by=saved_by, created_at=datetime.now()
        )

    monkeypatch.setattr(data, "remember_letter", _remember)
    monkeypatch.setattr(
        data,
        "saved_letter",
        lambda _id, *, lang=None: SavedLetter(
            id="l-1",
            body=ЗАФИКСИРОВАННОЕ,
            lang=lang or "ru",
            saved_by="tester",
            created_at=datetime.now(),
        ),
    )
    monkeypatch.setattr(letter_draft, "exchange_code_for_token", lambda _s, *, code: "токен")

    def _create(token: str, *, to: str, subject: str, body: str, **_: Any) -> str:
        следы["draft"].append((token, to, subject, body))
        return "r-1"

    monkeypatch.setattr(letter_draft, "create_draft", _create)

    app = собрать(tenant=ТЕНАНТ)
    with app.test_client() as client:
        войти(client)
        yield client, следы


def включить_почту(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "клиент.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "секрет")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "https://стенд/audit/auth/google/callback")
    monkeypatch.setenv("GOOGLE_MAIL_REDIRECT_URI", "https://стенд/auth/google/mail")


def увести(client: FlaskClient, текст: str = "Текст письма") -> Any:
    return client.post(
        f"/inspections/{ПРОВЕРКА}/letter/draft",
        data={"text": текст, "letter_lang": "ru"},
        headers={"Origin": СВОЙ},
    )


def test_письмо_фиксируется_до_ухода_за_согласием(
    клиент: tuple[FlaskClient, dict[str, list[Any]]], monkeypatch: pytest.MonkeyPatch
) -> None:
    включить_почту(monkeypatch)
    client, следы = клиент
    ответ = увести(client, "Текст, который человек поправил")
    assert ответ.status_code in (302, 303)
    assert "accounts.google.com" in ответ.headers["Location"]
    # Главное: правка уже записана, и уход со страницы её не уносит.
    assert следы["remember"] and следы["remember"][0][1] == "Текст, который человек поправил"


def test_уход_просит_почтовый_скоуп_и_ставит_метку(
    клиент: tuple[FlaskClient, dict[str, list[Any]]], monkeypatch: pytest.MonkeyPatch
) -> None:
    включить_почту(monkeypatch)
    client, _ = клиент
    ответ = увести(client)
    поля = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(ответ.headers["Location"]).query))
    assert поля["scope"] == DRAFT_SCOPE
    assert поля["redirect_uri"] == "https://стенд/auth/google/mail"
    assert ответ.headers.getlist("Set-Cookie")


def test_без_реквизитов_почты_экран_говорит_словами(
    клиент: tuple[FlaskClient, dict[str, list[Any]]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Стенд без почтовых реквизитов — законная настройка, а не поломка.

    Письмо при этом всё равно зафиксировано: человек нажал кнопку, и терять
    его правку из-за ненастроенной почты нельзя.
    """
    monkeypatch.delenv("GOOGLE_MAIL_REDIRECT_URI", raising=False)
    client, следы = клиент
    ответ = увести(client)
    assert "gmail=unavailable" in ответ.headers["Location"]
    assert следы["remember"]
    assert not следы["draft"]


def test_черновик_собирается_из_зафиксированного_письма(
    клиент: tuple[FlaskClient, dict[str, list[Any]]], monkeypatch: pytest.MonkeyPatch
) -> None:
    включить_почту(monkeypatch)
    client, следы = клиент
    уход = увести(client, "то, что было в поле")
    метка = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(уход.headers["Location"]).query))[
        "state"
    ]
    ответ = client.get(f"/auth/google/mail?state={метка}&code=код")
    assert "gmail=ok" in ответ.headers["Location"]
    _, кому, тема, тело = следы["draft"][0]
    # Именно зафиксированное: заготовка к этому моменту пересобралась бы.
    assert тело == ЗАФИКСИРОВАННОЕ
    assert кому == "partner@example.com"
    assert тема == "Проверка пиццерии · Белград · 2026-09-12"


def test_подделанная_метка_до_почты_не_доходит(
    клиент: tuple[FlaskClient, dict[str, list[Any]]], monkeypatch: pytest.MonkeyPatch
) -> None:
    включить_почту(monkeypatch)
    client, следы = клиент
    увести(client)
    ответ = client.get("/auth/google/mail?state=чужая-метка&code=код")
    assert "gmail=failed" in ответ.headers["Location"]
    assert not следы["draft"]


def test_отказ_человека_в_окне_согласия_не_поломка(
    клиент: tuple[FlaskClient, dict[str, list[Any]]], monkeypatch: pytest.MonkeyPatch
) -> None:
    включить_почту(monkeypatch)
    client, следы = клиент
    уход = увести(client)
    метка = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(уход.headers["Location"]).query))[
        "state"
    ]
    ответ = client.get(f"/auth/google/mail?state={метка}&error=access_denied")
    assert "gmail=denied" in ответ.headers["Location"]
    assert not следы["draft"]


def test_кнопка_есть_на_экране_письма(
    клиент: tuple[FlaskClient, dict[str, list[Any]]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Маршрут без кнопки — дверь, которой нет на экране.

    Проверяется не разметка, а сам факт: адрес ухода в черновики присутствует
    на странице письма. Кнопка, потерянная правкой шаблона, иначе пропала бы
    молча, и работающий маршрут остался бы недостижимым.
    """
    monkeypatch.setattr(
        data,
        "load_letter",
        lambda detail, *, lang=None: data.Letter(
            text="Заготовка письма",
            lang="ru",
            source="pinned",
            ready=True,
            caveats=(),
            failure=None,
        ),
    )
    страница = client_страница(клиент[0])
    assert f"/inspections/{ПРОВЕРКА}/letter/draft" in страница


def client_страница(client: FlaskClient) -> str:
    ответ = client.get(f"/inspections/{ПРОВЕРКА}/letter")
    assert ответ.status_code == 200
    return ответ.get_data(as_text=True)


def test_кука_похода_помечена_secure_за_туннелем(
    клиент: tuple[FlaskClient, dict[str, list[Any]]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Наружу админка выходит туннелем: TLS кончается на нём (D100).

    `request.is_secure` внутри при этом False, и кука похода ушла бы без
    `Secure` именно там, где это важно, — снаружи, а не на петле.
    """
    включить_почту(monkeypatch)
    client, _ = клиент
    ответ = client.post(
        f"/inspections/{ПРОВЕРКА}/letter/draft",
        data={"text": "Текст", "letter_lang": "ru"},
        # Origin со схемой https — как его и присылает браузер снаружи: заслон
        # происхождения сверяет схему с той, что видна за туннелем.
        headers={"Origin": СВОЙ.replace("http://", "https://"), "X-Forwarded-Proto": "https"},
    )
    кука = next(к for к in ответ.headers.getlist("Set-Cookie") if "dodo_audit_mail_state" in к)
    assert "Secure" in кука
