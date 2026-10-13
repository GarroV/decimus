"""Проверки входа через учётку Google (T332).

Сеть здесь не нужна и не используется: всё, что решает, пускать ли человека,
делает разбор `id_token`. Поэтому проверяется именно он — тест не зависит ни
от связи, ни от настроения Google, и падает по делу, а не по погоде.
"""

from __future__ import annotations

import base64
import json
import time

import pytest

from src.web.google_auth import (
    GoogleAuthError,
    GoogleSettings,
    authorization_url,
    identity_from_id_token,
    load_google_settings,
    new_state,
)

НАШ_КЛИЕНТ = "639159857771-пример.apps.googleusercontent.com"
ПОЧТА = "director@dodobrands.io"


def токен(**переопределения: object) -> str:
    """Собрать id_token с нужной нагрузкой. Подпись не нужна — её не проверяют."""
    нагрузка = {
        "iss": "https://accounts.google.com",
        "aud": НАШ_КЛИЕНТ,
        "exp": time.time() + 600,
        "email": ПОЧТА,
        "email_verified": True,
    }
    нагрузка.update(переопределения)
    середина = base64.urlsafe_b64encode(json.dumps(нагрузка).encode()).decode().rstrip("=")
    return f"заголовок.{середина}.подпись"


def test_правильный_токен_даёт_почту() -> None:
    кто = identity_from_id_token(токен(), client_id=НАШ_КЛИЕНТ)

    assert кто.email == ПОЧТА
    assert кто.email_verified is True


def test_почта_приводится_к_одному_виду() -> None:
    """Иначе `Director@...` не найдёт учётку, заведённую в нижнем регистре."""
    кто = identity_from_id_token(токен(email="  Director@DodoBrands.IO "), client_id=НАШ_КЛИЕНТ)

    assert кто.email == ПОЧТА


def test_токен_чужого_приложения_отвергается() -> None:
    """Без проверки `aud` в нас входили бы токеном, выписанным кому угодно."""
    with pytest.raises(GoogleAuthError):
        identity_from_id_token(токен(aud="чужое-приложение"), client_id=НАШ_КЛИЕНТ)


def test_токен_не_от_google_отвергается() -> None:
    with pytest.raises(GoogleAuthError):
        identity_from_id_token(токен(iss="https://злоумышленник.example"), client_id=НАШ_КЛИЕНТ)


def test_истёкший_токен_отвергается() -> None:
    with pytest.raises(GoogleAuthError):
        identity_from_id_token(токен(exp=time.time() - 3600), client_id=НАШ_КЛИЕНТ)


def test_неподтверждённая_почта_не_пускает() -> None:
    """Иначе вход достаётся тому, кто завёл аккаунт на чужой адрес."""
    with pytest.raises(GoogleAuthError):
        identity_from_id_token(токен(email_verified=False), client_id=НАШ_КЛИЕНТ)


def test_токен_без_почты_отвергается() -> None:
    без_почты = {
        "iss": "accounts.google.com",
        "aud": НАШ_КЛИЕНТ,
        "exp": time.time() + 600,
    }
    середина = base64.urlsafe_b64encode(json.dumps(без_почты).encode()).decode().rstrip("=")
    with pytest.raises(GoogleAuthError):
        identity_from_id_token(f"з.{середина}.п", client_id=НАШ_КЛИЕНТ)


def test_мусор_вместо_токена_отвергается() -> None:
    with pytest.raises(GoogleAuthError):
        identity_from_id_token("совсем-не-токен", client_id=НАШ_КЛИЕНТ)


def test_адрес_согласия_несёт_метку_захода_и_скоупы() -> None:
    настройки = GoogleSettings(
        client_id=НАШ_КЛИЕНТ, client_secret="секрет", redirect_uri="https://стенд.example/cb"
    )
    метка = new_state()

    адрес = authorization_url(настройки, state=метка)

    assert адрес.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert f"state={метка}" in адрес
    assert "scope=openid+email+profile" in адрес
    assert "gmail" not in адрес


def test_метка_захода_каждый_раз_своя() -> None:
    """Постоянная метка не защищает ни от чего: её узнают один раз и навсегда."""
    assert new_state() != new_state()


def test_без_реквизитов_вход_через_google_просто_отсутствует() -> None:
    """Не отказ входа вообще: стенд без реквизитов работает паролем, как работал."""
    assert load_google_settings({}) is None
    assert load_google_settings({"GOOGLE_CLIENT_ID": "есть"}) is None
    assert (
        load_google_settings({"GOOGLE_CLIENT_ID": "есть", "GOOGLE_CLIENT_SECRET": "есть"}) is None
    )


def test_полные_реквизиты_читаются() -> None:
    настройки = load_google_settings(
        {
            "GOOGLE_CLIENT_ID": " cid ",
            "GOOGLE_CLIENT_SECRET": "sec",
            "GOOGLE_REDIRECT_URI": "https://стенд.example/cb",
        }
    )

    assert настройки is not None
    assert настройки.client_id == "cid"


def test_домен_workspace_читается_из_токена() -> None:
    """`hd` — домен Google Workspace (F-028): по нему решается вход в пространство УК."""
    кто = identity_from_id_token(токен(hd="DodoBrands.io"), client_id=НАШ_КЛИЕНТ)
    assert кто.hosted_domain == "dodobrands.io"


def test_личный_аккаунт_домена_не_несёт() -> None:
    assert identity_from_id_token(токен(), client_id=НАШ_КЛИЕНТ).hosted_domain == ""


# ── Имя и фото в токене (D468) ───────────────────────────────────────────


def test_имя_берётся_из_name_токена() -> None:
    кто = identity_from_id_token(
        токен(name="  Иван   Петров ", picture="https://lh3.googleusercontent.com/a/x=s96-c"),
        client_id=НАШ_КЛИЕНТ,
    )

    assert кто.name == "Иван Петров"
    assert кто.picture == "https://lh3.googleusercontent.com/a/x=s96-c"


def test_без_name_имя_собирается_из_имени_и_фамилии() -> None:
    кто = identity_from_id_token(
        токен(given_name="Иван", family_name="Петров"), client_id=НАШ_КЛИЕНТ
    )

    assert кто.name == "Иван Петров"


def test_нет_имени_и_фото_значит_пусто() -> None:
    кто = identity_from_id_token(токен(), client_id=НАШ_КЛИЕНТ)

    assert кто.name == "" and кто.picture == ""


def test_имя_не_строка_и_управляющие_знаки_не_проходят() -> None:
    assert identity_from_id_token(токен(name=42), client_id=НАШ_КЛИЕНТ).name == ""
    грязное = identity_from_id_token(токен(name="Иван‮\x00\nПетров"), client_id=НАШ_КЛИЕНТ)
    assert "\x00" not in грязное.name and "\n" not in грязное.name


def test_имя_и_адрес_фото_ограничены_по_длине() -> None:
    кто = identity_from_id_token(
        токен(name="я" * 500, picture="https://x.googleusercontent.com/" + "a" * 600),
        client_id=НАШ_КЛИЕНТ,
    )

    assert len(кто.name) == 120
    assert кто.picture == ""


def test_имя_из_токена_чужого_приложения_не_берётся() -> None:
    """Имя читается ПОСЛЕ проверки `aud`: чужой токен не доходит до разбора имени."""
    with pytest.raises(GoogleAuthError):
        identity_from_id_token(токен(aud="чужой", name="Иван"), client_id=НАШ_КЛИЕНТ)
