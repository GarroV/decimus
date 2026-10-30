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

import base64
import email.policy
import json
import urllib.parse
from collections.abc import Iterator
from dataclasses import replace
from datetime import date, datetime
from email.parser import BytesParser
from typing import Any

import pytest
from flask.testing import FlaskClient
from web_harness import СВОЙ, войти, подменить_двери, собрать

from src.db.errors import DbError, StorageError
from src.db.letters import SavedLetter
from src.db.models import InspectionDetail, InspectionRow
from src.db.reports import ReportRef
from src.domain.tenants import canonical_tenant
from src.report.letters import LetterError
from src.web import inspections as data
from src.web import letter_draft
from src.web.google_mail import DRAFT_SCOPE, MailGrant
from src.web.texts import t

ТЕНАНТ = "default"
ПРОВЕРКА = "11111111-1111-1111-1111-111111111111"
ЗАФИКСИРОВАННОЕ = "Здравствуйте! Это письмо человек подтвердил."
#: Почта входа через Google у вошедшего: черновик ложится только в неё (D176).
ПОЧТА = "director@example.com"
PDF = b"%PDF-1.7\ncurrent inspection report\n%%EOF"


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
    подменить_двери(monkeypatch, tenant=ТЕНАНТ, email=ПОЧТА)
    следы: dict[str, list[Any]] = {
        "remember": [],
        "draft": [],
        "token": [],
        "report": [],
        "attachments": [],
    }

    monkeypatch.setattr(data, "load_card", lambda _id, *, reach: карточка())
    ref = ReportRef("report.pdf", "application/pdf", len(PDF), datetime.now())

    def _ensure(detail: InspectionDetail, *, reach: Any) -> ReportRef:
        следы["report"].append((detail, reach))
        return ref

    # Общий helper интегрируется из соседней ветки PDF.
    monkeypatch.setattr(data, "ensure_report", _ensure, raising=False)
    monkeypatch.setattr(data, "report_bytes", lambda actual: PDF if actual == ref else b"")

    def _remember(
        inspection_id: str, *, tenant: str, body: str, lang: str, saved_by: str
    ) -> SavedLetter:
        assert tenant == canonical_tenant(ТЕНАНТ), "письмо фиксируется в пространстве вошедшего"
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
    monkeypatch.setattr(
        letter_draft, "exchange_code_for_grant", lambda _s, *, code: MailGrant("токен", ПОЧТА)
    )

    def _create(token: str, *, to: str, subject: str, body: str, **extra: Any) -> str:
        следы["draft"].append((token, to, subject, body))
        следы["attachments"].append(extra.get("attachments", ()))
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
    # Почтовое право и «кто это»: без `openid email` возврат не узнал бы, какой
    # аккаунт выдал доступ (D176).
    assert поля["scope"].split() == ["openid", "email", DRAFT_SCOPE]
    assert поля["login_hint"] == ПОЧТА
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
    assert следы["report"][0][0].inspection.id == ПРОВЕРКА
    assert следы["attachments"] == [(("Demo Pizzeria #1 2026-09-12.pdf", PDF, "application/pdf"),)]


@pytest.mark.parametrize("failure", [DbError("db"), StorageError("storage"), LetterError("pdf")])
def test_pdf_failure_does_not_create_draft(
    клиент: tuple[FlaskClient, dict[str, list[Any]]],
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
) -> None:
    включить_почту(monkeypatch)
    client, следы = клиент

    def broken(*args: Any, **kwargs: Any) -> Any:
        raise failure

    monkeypatch.setattr(data, "ensure_report", broken)
    уход = увести(client)
    state = urllib.parse.parse_qs(urllib.parse.urlparse(уход.location).query)["state"][0]
    ответ = client.get("/auth/google/mail", query_string={"state": state, "code": "code"})
    assert "gmail=pdf_failed" in ответ.headers["Location"]
    assert not следы["draft"]
    assert следы["remember"], "сохранённый текст должен пережить отказ PDF"


@pytest.mark.parametrize("content", [b"", b"<html>storage error</html>"])
def test_invalid_pdf_does_not_create_draft(
    клиент: tuple[FlaskClient, dict[str, list[Any]]],
    monkeypatch: pytest.MonkeyPatch,
    content: bytes,
) -> None:
    включить_почту(monkeypatch)
    client, следы = клиент
    monkeypatch.setattr(data, "report_bytes", lambda ref: content)
    уход = увести(client)
    state = urllib.parse.parse_qs(urllib.parse.urlparse(уход.location).query)["state"][0]
    ответ = client.get("/auth/google/mail", query_string={"state": state, "code": "code"})
    assert "gmail=pdf_failed" in ответ.headers["Location"]
    assert not следы["draft"]


def test_callback_sends_current_pdf_in_gmail_mime(
    клиент: tuple[FlaskClient, dict[str, list[Any]]], monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.web import google_mail

    включить_почту(monkeypatch)
    client, следы = клиент
    sent: list[Any] = []

    class Reply:
        def __enter__(self) -> Reply:
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def read(self) -> bytes:
            return b'{"id":"draft-with-report"}'

    def opener(request: Any, **kwargs: Any) -> Reply:
        sent.append(request)
        return Reply()

    monkeypatch.setattr(
        letter_draft,
        "create_draft",
        lambda token, **fields: google_mail.create_draft(token, opener=opener, **fields),
    )
    уход = увести(client)
    # Между уходом и возвратом могли исправить проверку: helper получает
    # свежую карточку, а текст по-прежнему берётся из saved_letter.
    current = replace(карточка(), inspection=replace(карточка().inspection, city="Новый город"))
    monkeypatch.setattr(data, "load_card", lambda _id, *, reach: current)
    state = urllib.parse.parse_qs(urllib.parse.urlparse(уход.location).query)["state"][0]
    ответ = client.get("/auth/google/mail", query_string={"state": state, "code": "code"})
    assert "gmail=ok" in ответ.headers["Location"]
    assert следы["report"][0][0] is current
    assert len(sent) == 1
    raw = json.loads(sent[0].data)["message"]["raw"]
    message = BytesParser(policy=email.policy.default).parsebytes(
        base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    )
    assert "Новый город" in str(message["Subject"])
    assert message.get_body(preferencelist=("plain",)).get_content().strip() == ЗАФИКСИРОВАННОЕ
    assert ЗАФИКСИРОВАННОЕ in message.get_body(preferencelist=("html",)).get_content()
    (attachment,) = message.iter_attachments()
    assert attachment.get_content_type() == "application/pdf"
    assert attachment.get_payload(decode=True) == PDF


def test_черновик_в_чужой_аккаунт_google_не_ложится(
    клиент: tuple[FlaskClient, dict[str, list[Any]]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """D176: доступ выдал не тот аккаунт, которым вошли, — черновика нет, исход словами."""
    включить_почту(monkeypatch)
    client, следы = клиент
    monkeypatch.setattr(
        letter_draft,
        "exchange_code_for_grant",
        lambda _s, *, code: MailGrant("токен", "someone-else@example.com"),
    )
    уход = увести(client)
    метка = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(уход.headers["Location"]).query))[
        "state"
    ]
    ответ = client.get(f"/auth/google/mail?state={метка}&code=код")
    assert "gmail=wrong_account" in ответ.headers["Location"]
    assert not следы["draft"], "черновик лёг в чужой аккаунт"
    monkeypatch.setattr(
        data,
        "load_letter",
        lambda detail, *, lang=None, template=None: data.Letter(
            text="Заготовка", lang="ru", source="pinned", ready=True, caveats=(), failure=None
        ),
    )
    # Возврат — в панель письма реестра (20.10.2026): список проверок подменён.
    monkeypatch.setattr(data, "load_registry", lambda **_: data.Registry((), True))
    экран = client.get(ответ.headers["Location"]).get_data(as_text=True)
    assert t("letter.gmail.wrong_account", "ru") in экран


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
        lambda detail, *, lang=None, template=None: data.Letter(
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


_КНОПКИ_ЗАПИСИ = ("letter.gmail.submit", "letter.save.submit")


@pytest.mark.parametrize(("пространство", "видны"), [(ТЕНАНТ, True), ("GE", False)])
def test_у_проверки_чужого_пространства_нет_кнопок_записи_письма(
    клиент: tuple[FlaskClient, dict[str, list[Any]]],
    monkeypatch: pytest.MonkeyPatch,
    пространство: str,
    видны: bool,
) -> None:
    """Ревью #340, п.9: УК читает письмо проверки партнёра, но не пишет его."""
    своя = карточка()
    monkeypatch.setattr(
        data,
        "load_card",
        lambda _id, *, reach: replace(
            своя, inspection=replace(своя.inspection, tenant_code=пространство)
        ),
    )
    monkeypatch.setattr(
        data,
        "load_letter",
        lambda detail, *, lang=None, template=None: data.Letter(
            text="Заготовка письма",
            lang="ru",
            source="pinned",
            ready=True,
            caveats=(),
            failure=None,
        ),
    )
    страница = client_страница(клиент[0])
    for ключ in _КНОПКИ_ЗАПИСИ:
        assert (t(ключ, "ru") in страница) is видны, ключ
    for адрес in ("/letter/draft", "/letter/save"):
        assert (f"/inspections/{ПРОВЕРКА}{адрес}" in страница) is видны, адрес


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


def test_перевод_строки_в_контакте_даёт_отказ_а_не_500(
    клиент: tuple[FlaskClient, dict[str, list[Any]]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Контакт из шапки со вписанным переводом строки — ревью санитайзера, п.4."""
    from src.web import google_mail

    включить_почту(monkeypatch)
    client, _ = клиент
    своя = карточка()
    monkeypatch.setattr(
        data,
        "load_card",
        lambda _id, *, reach: replace(
            своя,
            inspection=replace(
                своя.inspection, contact="partner@example.com\r\nBcc: z@evil.example"
            ),
        ),
    )

    def _не_звать(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("до Gmail письмо с битым заголовком доходить не должно")

    # Настоящая сборка письма, подменён только сетевой вызов.
    monkeypatch.setattr(
        letter_draft,
        "create_draft",
        lambda token, **поля: google_mail.create_draft(token, opener=_не_звать, **поля),
    )
    уход = увести(client)
    метка = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(уход.headers["Location"]).query))[
        "state"
    ]

    ответ = client.get(f"/auth/google/mail?state={метка}&code=код")

    assert ответ.status_code == 303
    assert "gmail=failed" in ответ.headers["Location"]


def _на_приёмке(monkeypatch: pytest.MonkeyPatch) -> None:
    ждущая = карточка()
    ждущая = replace(ждущая, inspection=replace(ждущая.inspection, on_review=True))
    monkeypatch.setattr(data, "load_card", lambda _id, *, reach: ждущая)


def test_у_ждущей_приёмки_черновик_в_почту_не_уходит(
    клиент: tuple[FlaskClient, dict[str, list[Any]]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """D199: письмо непринятой проверки смотрят, но не фиксируют и в Gmail не кладут."""
    # Arrange
    включить_почту(monkeypatch)
    _на_приёмке(monkeypatch)
    client, следы = клиент

    # Act
    ответ = увести(client)

    # Assert
    assert "gmail=on_review" in ответ.headers["Location"]
    assert not следы["remember"]
    assert not следы["draft"]


def test_возврат_от_google_по_ждущей_приёмки_черновика_не_создаёт(
    клиент: tuple[FlaskClient, dict[str, list[Any]]], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — уход начат по принятой, к возврату проверка на приёмке.
    включить_почту(monkeypatch)
    client, следы = клиент
    уход = увести(client)
    метка = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(уход.headers["Location"]).query))[
        "state"
    ]
    _на_приёмке(monkeypatch)

    # Act
    ответ = client.get(f"/auth/google/mail?state={метка}&code=код")

    # Assert
    assert "gmail=on_review" in ответ.headers["Location"]
    assert not следы["draft"]


def test_у_ждущей_приёмки_письмо_не_сохраняется(
    клиент: tuple[FlaskClient, dict[str, list[Any]]], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    _на_приёмке(monkeypatch)
    client, следы = клиент

    # Act
    ответ = client.post(
        f"/inspections/{ПРОВЕРКА}/letter/save",
        data={"text": "Текст", "letter_lang": "ru"},
        headers={"Origin": СВОЙ},
    )

    # Assert
    assert ответ.status_code == 303
    assert "saved=on_review" in ответ.headers["Location"]
    assert not следы["remember"]
