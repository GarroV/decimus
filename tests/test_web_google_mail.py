"""Черновик письма в почте вошедшего (D174, D176, #332).

Сети здесь нет: всё, что решает судьбу письма, — это сборка MIME и разбор
ответа Gmail. Оба места чистые, поэтому проверяются напрямую, а не через
живой запрос, который падал бы по погоде и молчал бы по делу.
"""

from __future__ import annotations

import base64
import email
import email.message
import email.policy
import json
import urllib.parse

import pytest

from src.web.google_auth import GoogleSettings
from src.web.google_mail import (
    DRAFT_SCOPE,
    GoogleMailError,
    MailAccountMismatchError,
    MailGrant,
    consent_url,
    create_draft,
    draft_subject,
    exchange_code_for_grant,
    mime_message,
    verified_token,
)

НАСТРОЙКИ = GoogleSettings(
    client_id="639159857771-пример.apps.googleusercontent.com",
    client_secret="секрет-стенда",
    redirect_uri="https://<TAILNET_HOST>/audit/auth/google/mail",
)


def параметры(адрес: str) -> dict[str, str]:
    return dict(urllib.parse.parse_qsl(urllib.parse.urlparse(адрес).query))


class ОтветЗаглушка:
    """Минимальный ответ urlopen: контекстный менеджер с `read`."""

    def __init__(self, тело: bytes) -> None:
        self._тело = тело

    def __enter__(self) -> ОтветЗаглушка:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return self._тело


# --- согласие на почту ---------------------------------------------------


def test_согласие_просит_именно_почтовый_скоуп() -> None:
    поля = параметры(consent_url(НАСТРОЙКИ, state="метка", login_hint="a@dodoteam.io"))
    # Почтовое право и «кто это» (D176): `openid email` — чтобы на возврате
    # узнать, какой аккаунт выдал доступ.
    assert поля["scope"].split() == ["openid", "email", DRAFT_SCOPE]
    assert поля["state"] == "метка"
    assert поля["redirect_uri"] == НАСТРОЙКИ.redirect_uri


def test_согласие_не_теряет_уже_выданные_права() -> None:
    """Без `include_granted_scopes` Google выдал бы токен ТОЛЬКО на почту.

    Тогда следующий вход по тому же приложению переспрашивал бы согласие с
    нуля — человек видел бы экран согласия при каждом заходе.
    """
    поля = параметры(consent_url(НАСТРОЙКИ, state="метка", login_hint="a@dodoteam.io"))
    assert поля["include_granted_scopes"] == "true"


def test_согласие_ведёт_в_тот_же_аккаунт_под_которым_вошли() -> None:
    поля = параметры(consent_url(НАСТРОЙКИ, state="метка", login_hint="auditor@dodoteam.io"))
    assert поля["login_hint"] == "auditor@dodoteam.io"


# --- сборка письма -------------------------------------------------------


def test_тема_и_тело_на_кириллице_доезжают_целыми() -> None:
    """Письмо разбирается обратно почтовым разбором, а не глазами по подстроке.

    Кодирование заголовков делает сама стандартная почтовая сборка, поэтому
    проверять «нет сырого UTF-8» значило бы проверять её, а не нас. Падает
    эта проверка от НАШИХ ошибок: потерянной темы, потерянного адресата,
    испорченного тела.
    """
    сырое = mime_message(
        to="partner@example.com", subject="Проверка · Белград", body="Здравствуйте!"
    )
    письмо = email.message_from_bytes(
        base64.urlsafe_b64decode(сырое + "=" * (-len(сырое) % 4)), policy=email.policy.default
    )
    assert письмо["Subject"] == "Проверка · Белград"
    assert письмо["To"] == "partner@example.com"
    assert письмо.get_body(preferencelist=("plain",)).get_content().strip() == "Здравствуйте!"


def _разобрать(сырое: str) -> email.message.EmailMessage:
    письмо = email.message_from_bytes(
        base64.urlsafe_b64decode(сырое + "=" * (-len(сырое) % 4)), policy=email.policy.default
    )
    assert isinstance(письмо, email.message.EmailMessage)
    return письмо


def test_письмо_несёт_html_и_честный_текст() -> None:
    """Форматирование доезжает HTML-частью, а текстовая часть — без разметки.

    Почта без HTML показывает текстовую часть: тег в ней читается партнёром
    буквально, а ссылка без адреса превращается в слово, которое некуда нажать.
    """
    сырое = mime_message(
        to="",
        subject="Тема",
        body='<b>Срок</b> — <s>5</s> 3 дня\nПлан: <a href="https://dodo.example/p">ссылка</a>',
    )
    письмо = _разобрать(сырое)

    assert письмо.get_content_type() == "multipart/alternative"
    текст = письмо.get_body(preferencelist=("plain",)).get_content()
    разметка = письмо.get_body(preferencelist=("html",)).get_content()
    assert текст.strip() == "Срок — 5 3 дня\nПлан: ссылка (https://dodo.example/p)"
    assert "<b>Срок</b>" in разметка
    assert "<s>5</s>" in разметка
    assert '<a href="https://dodo.example/p">ссылка</a>' in разметка


def test_в_письмо_не_уезжает_неочищенное() -> None:
    """Сборка письма чистит сама: запись могла лечь в базу в обход сохранения."""
    сырое = mime_message(
        to="",
        subject="Тема",
        body='<a href="javascript:alert(1)" onclick="x">a</a><script>alert(2)</script>'
        "<img src=x onerror=alert(3)>",
    )
    письмо = _разобрать(сырое)

    разметка = письмо.get_body(preferencelist=("html",)).get_content()
    текст = письмо.get_body(preferencelist=("plain",)).get_content()
    for часть in (разметка, текст):
        assert "javascript" not in часть
        assert "alert" not in часть
        assert "onclick" not in часть and "onerror" not in часть


def test_письмо_из_одной_разметки_без_слов_отвергается() -> None:
    with pytest.raises(GoogleMailError):
        mime_message(to="", subject="Тема", body="<b> </b><script>x</script>")


def test_сырое_письмо_закодировано_безопасно_для_адреса() -> None:
    сырое = mime_message(to="partner@example.com", subject="Тема", body="Текст")
    assert "+" not in сырое and "/" not in сырое and "\n" not in сырое


def test_без_адресата_заголовка_to_в_письме_нет() -> None:
    """Пустой контакт — обычное дело (шапка заполняется мастером бота).

    Строка `To:` с пустым значением превращает черновик в письмо, которое
    Gmail откажется отправлять, и человек узнает об этом последним.
    """
    сырое = mime_message(to="", subject="Тема", body="Текст")
    восстановлено = base64.urlsafe_b64decode(сырое + "=" * (-len(сырое) % 4)).decode()
    assert "To:" not in восстановлено


def test_пустое_тело_письма_отвергается() -> None:
    with pytest.raises(GoogleMailError):
        mime_message(to="partner@example.com", subject="Тема", body="   ")


def test_тема_собирается_из_шапки_и_не_несёт_прочерков() -> None:
    assert (
        draft_subject(city="Белград", date="2026-09-12", lang="ru")
        == "Проверка пиццерии · Белград · 2026-09-12"
    )
    # Пустой город не даёт «Проверка ·  · дата»: разделитель без части — это
    # мусор в теме письма партнёру.
    assert draft_subject(city="", date="2026-09-12", lang="ru") == "Проверка пиццерии · 2026-09-12"
    assert (
        draft_subject(city="Belgrade", date="2026-09-12", lang="en")
        == "Pizzeria audit · Belgrade · 2026-09-12"
    )


# --- разговор с Gmail ----------------------------------------------------


def test_черновик_создан_возвращает_свой_номер() -> None:
    def открыватель(запрос: object, timeout: float) -> ОтветЗаглушка:
        return ОтветЗаглушка(json.dumps({"id": "r-123", "message": {"id": "m-1"}}).encode())

    номер = create_draft(
        "токен", to="p@example.com", subject="Тема", body="Текст", opener=открыватель
    )
    assert номер == "r-123"


def test_отказ_прав_объясняется_словами_а_не_общим_сбоем() -> None:
    """403 от Gmail значит одно: согласие на почту не выдано или отозвано.

    Общий текст «не удалось» отправил бы человека искать поломку в письме,
    тогда как чинится это одним походом за согласием.
    """

    class Отказ(Exception):
        code = 403

    def открыватель(запрос: object, timeout: float) -> ОтветЗаглушка:
        raise Отказ("forbidden")

    with pytest.raises(GoogleMailError) as сбой:
        create_draft("токен", to="p@example.com", subject="Тема", body="Текст", opener=открыватель)
    assert "согласие" in str(сбой.value).lower()


def test_403_несёт_машинную_причину_google_без_текста_ответа() -> None:
    """403 даёт и отозванное согласие, и выключенный Gmail API — чинятся по-разному.

    Причина из тела (`SERVICE_DISABLED`) попадает в сообщение и в журнал;
    человекочитаемый текст Google — нет: в нём бывает адрес почты.
    """
    тело = {
        "error": {
            "code": 403,
            "message": "Gmail API has not been used in project 1 by me@example.com",
            "status": "PERMISSION_DENIED",
            "details": [{"reason": "SERVICE_DISABLED"}],
        }
    }

    class Отказ(Exception):
        code = 403

        def read(self) -> bytes:
            return json.dumps(тело).encode()

    def открыватель(запрос: object, timeout: float) -> ОтветЗаглушка:
        raise Отказ("forbidden")

    with pytest.raises(GoogleMailError) as сбой:
        create_draft("токен", to="p@example.com", subject="Тема", body="Текст", opener=открыватель)
    текст = str(сбой.value)
    assert "SERVICE_DISABLED" in текст
    assert "PERMISSION_DENIED" in текст
    assert "example.com" not in текст


def test_ответ_без_номера_черновика_не_выдаётся_за_успех() -> None:
    def открыватель(запрос: object, timeout: float) -> ОтветЗаглушка:
        return ОтветЗаглушка(json.dumps({"message": {"id": "m-1"}}).encode())

    with pytest.raises(GoogleMailError):
        create_draft("токен", to="p@example.com", subject="Тема", body="Текст", opener=открыватель)


@pytest.mark.parametrize(
    ("кому", "тема"),
    [
        ("partner@example.com\r\nBcc: z@evil.example", "Тема"),
        ("partner@example.com", "Тема\r\nBcc: z@evil.example"),
        ("partner@example.com\nBcc: z@evil.example", "Тема"),
    ],
)
def test_перевод_строки_в_заголовке_отказ_словами(кому: str, тема: str) -> None:
    """CR/LF в теме или адресате — не 500 из почтовой сборки, а внятный отказ."""
    with pytest.raises(GoogleMailError):
        mime_message(to=кому, subject=тема, body="Текст")


# --- чей доступ к почте (D176, F-018/F-029 аудита 12.10) ---------------------


def _id_token(**нагрузка: object) -> str:
    полная = {
        "iss": "https://accounts.google.com",
        "aud": НАСТРОЙКИ.client_id,
        "exp": 4_000_000_000,
        "email": "lead@example.com",
        "email_verified": True,
        "sub": "110169484474386276334",
        **нагрузка,
    }
    середина = base64.urlsafe_b64encode(json.dumps(полная).encode()).decode().rstrip("=")
    return f"заголовок.{середина}.подпись"


def _обмен(monkeypatch: pytest.MonkeyPatch, тело: dict[str, object]) -> None:
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_a, **_k: ОтветЗаглушка(json.dumps(тело).encode()),
    )


def test_обмен_кода_говорит_чей_доступ(monkeypatch: pytest.MonkeyPatch) -> None:
    _обмен(monkeypatch, {"access_token": "т", "id_token": _id_token(email="Lead@Example.com")})
    доступ = exchange_code_for_grant(НАСТРОЙКИ, code="к")
    assert доступ == MailGrant(access_token="т", email="lead@example.com")


def test_обмен_без_id_token_не_выдаёт_доступ(monkeypatch: pytest.MonkeyPatch) -> None:
    _обмен(monkeypatch, {"access_token": "т"})
    with pytest.raises(GoogleMailError, match="id_token"):
        exchange_code_for_grant(НАСТРОЙКИ, code="к")


def test_доступ_чужого_приложения_отвергается(monkeypatch: pytest.MonkeyPatch) -> None:
    _обмен(monkeypatch, {"access_token": "т", "id_token": _id_token(aud="чужое")})
    with pytest.raises(GoogleMailError):
        exchange_code_for_grant(НАСТРОЙКИ, code="к")


@pytest.mark.parametrize("своя", ["other@example.com", "", None])
def test_чужой_аккаунт_или_неизвестная_почта_отказ(своя: str | None) -> None:
    with pytest.raises(MailAccountMismatchError):
        verified_token(MailGrant("т", "lead@example.com"), expected_email=своя)


def test_свой_аккаунт_отдаёт_токен() -> None:
    assert (
        verified_token(MailGrant("т", "lead@example.com"), expected_email="Lead@example.com") == "т"
    )
