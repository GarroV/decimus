"""Черновик письма в почте вошедшего (D174, D176, #332).

Сети здесь нет: всё, что решает судьбу письма, — это сборка MIME и разбор
ответа Gmail. Оба места чистые, поэтому проверяются напрямую, а не через
живой запрос, который падал бы по погоде и молчал бы по делу.
"""

from __future__ import annotations

import base64
import email
import email.policy
import json
import urllib.parse

import pytest

from src.web.google_auth import GoogleSettings
from src.web.google_mail import (
    DRAFT_SCOPE,
    GoogleMailError,
    consent_url,
    create_draft,
    draft_subject,
    mime_message,
)

НАСТРОЙКИ = GoogleSettings(
    client_id="639159857771-пример.apps.googleusercontent.com",
    client_secret="секрет-стенда",
    redirect_uri="https://muspelheim.tail48dfee.ts.net/audit/auth/google/mail",
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
    assert поля["scope"] == DRAFT_SCOPE
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
    assert письмо.get_content().strip() == "Здравствуйте!"


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
        create_draft(
            "токен", to="p@example.com", subject="Тема", body="Текст", opener=открыватель
        )
    assert "согласие" in str(сбой.value).lower()


def test_ответ_без_номера_черновика_не_выдаётся_за_успех() -> None:
    def открыватель(запрос: object, timeout: float) -> ОтветЗаглушка:
        return ОтветЗаглушка(json.dumps({"message": {"id": "m-1"}}).encode())

    with pytest.raises(GoogleMailError):
        create_draft(
            "токен", to="p@example.com", subject="Тема", body="Текст", opener=открыватель
        )
