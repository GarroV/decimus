"""Имя и фото из Google (D468): скачивание фото и запись в учётку.

Сети нет: скачивание подменено на границе `google_profile._open`. Что проверяется —
отказ от всего, что не фото Google: чужой хост, не https, редирект, не картинка,
слишком большое, — и что вход от сбоя фото не страдает.
"""

from __future__ import annotations

import logging
import urllib.request
from typing import ClassVar

import pytest

from src.db.errors import AccessError
from src.web import google_profile
from src.web.google_auth import GoogleIdentity

ФОТО = "https://lh3.googleusercontent.com/a/AEdFTp=s96-c"
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 32


class Скачивание:
    """Двойник `_open`: помнит, звали ли, и отдаёт заданное."""

    def __init__(self, заголовок: str = "image/jpeg", тело: bytes = JPEG) -> None:
        self.заголовок = заголовок
        self.тело = тело
        self.адреса: list[str] = []

    def __call__(self, url: str) -> tuple[str, bytes]:
        self.адреса.append(url)
        return self.заголовок, self.тело


@pytest.fixture
def скачивание(monkeypatch: pytest.MonkeyPatch) -> Скачивание:
    двойник = Скачивание()
    monkeypatch.setattr(google_profile, "_open", двойник)
    return двойник


@pytest.mark.parametrize(
    ("заголовок", "тело", "тип"),
    [
        ("image/jpeg", JPEG, "image/jpeg"),
        ("image/png", PNG, "image/png"),
        ("image/webp", WEBP, "image/webp"),
    ],
)
def test_фото_google_берётся_по_сигнатуре(
    скачивание: Скачивание, заголовок: str, тело: bytes, тип: str
) -> None:
    скачивание.заголовок, скачивание.тело = заголовок, тело

    фото = google_profile.fetch_avatar(ФОТО)

    assert фото.content_type == тип and фото.data == тело


@pytest.mark.parametrize(
    "адрес",
    [
        "http://lh3.googleusercontent.com/a/x",  # не https
        "https://evil.example/a/x",  # чужой хост
        "https://googleusercontent.com/a/x",  # корень без поддомена
        "https://lh3.googleusercontent.com.evil.example/a/x",  # хвост-обманка
        "https://evil.example/.googleusercontent.com",  # домен в пути
        "https://user:pw@lh3.googleusercontent.com/a/x",  # учётные данные
        "https://lh3.googleusercontent.com:8443/a/x",  # чужой порт
        "https://127.0.0.1/a/x",  # внутренний адрес
        "file:///etc/passwd",
        "https://lh3.googleusercontent.com@evil.example/a/x",  # хост после @
        "",
    ],
)
def test_чужой_адрес_отвергается_до_обращения_в_сеть(скачивание: Скачивание, адрес: str) -> None:
    with pytest.raises(google_profile.AvatarRefused):
        google_profile.fetch_avatar(адрес)

    assert скачивание.адреса == [], "в сеть сходили за адресом, которого не должно быть"


def test_не_картинка_по_заголовку_отвергается(скачивание: Скачивание) -> None:
    скачивание.заголовок = "text/html"

    with pytest.raises(google_profile.AvatarRefused):
        google_profile.fetch_avatar(ФОТО)


def test_картинка_по_заголовку_но_не_по_байтам_отвергается(скачивание: Скачивание) -> None:
    скачивание.тело = b"<html><script>alert(1)</script></html>"

    with pytest.raises(google_profile.AvatarRefused):
        google_profile.fetch_avatar(ФОТО)


def test_заголовок_png_при_байтах_jpeg_отвергается(скачивание: Скачивание) -> None:
    скачивание.заголовок = "image/png"

    with pytest.raises(google_profile.AvatarRefused):
        google_profile.fetch_avatar(ФОТО)


def test_больше_предела_отвергается(скачивание: Скачивание) -> None:
    скачивание.тело = JPEG + b"\x00" * google_profile.MAX_AVATAR_BYTES

    with pytest.raises(google_profile.AvatarRefused):
        google_profile.fetch_avatar(ФОТО)


def test_ровно_предел_проходит(скачивание: Скачивание) -> None:
    скачивание.тело = JPEG + b"\x00" * (google_profile.MAX_AVATAR_BYTES - len(JPEG))

    assert len(google_profile.fetch_avatar(ФОТО).data) == google_profile.MAX_AVATAR_BYTES


def test_редирект_отвергается_а_не_выполняется() -> None:
    """Редирект мог бы увести на хост, которого мы не проверяли."""
    обработчик = google_profile._NoRedirect()
    запрос = urllib.request.Request(ФОТО)

    with pytest.raises(google_profile.AvatarRefused):
        обработчик.redirect_request(запрос, None, 302, "Found", {}, "http://169.254.169.254/")


def test_скачивание_идёт_открывальщиком_без_редиректов(monkeypatch: pytest.MonkeyPatch) -> None:
    """`_open` строит открывальщик с запретом редиректов, а не обычный `urlopen`."""
    собрано: list[type] = []

    class Ответ:
        status = 200
        headers: ClassVar[dict[str, str]] = {"Content-Type": "image/jpeg"}

        def __enter__(self) -> Ответ:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def read(self, _n: int) -> bytes:
            return JPEG

    class Открывальщик:
        def open(self, запрос: object, timeout: float) -> Ответ:
            assert timeout == google_profile.AVATAR_TIMEOUT_SECONDS
            return Ответ()

    def build_opener(*обработчики: type) -> Открывальщик:
        собрано.extend(обработчики)
        return Открывальщик()

    monkeypatch.setattr(urllib.request, "build_opener", build_opener)

    assert google_profile._open(ФОТО) == ("image/jpeg", JPEG)
    assert google_profile._NoRedirect in собрано


# ── remember: запись и сбои ───────────────────────────────────────────────


@pytest.fixture
def записано(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    журнал: list[dict[str, object]] = []

    def save(
        token: str, *, name: str | None, avatar: bytes | None, avatar_type: str | None
    ) -> bool:
        журнал.append({"token": token, "name": name, "avatar": avatar, "type": avatar_type})
        return True

    monkeypatch.setattr(google_profile.web_own_profile, "save_google_profile", save)
    return журнал


def _кто(**поля: str) -> GoogleIdentity:
    return GoogleIdentity(email="a@dodobrands.io", email_verified=True, **поля)  # type: ignore[arg-type]


def test_имя_и_фото_записываются_своей_сессии(
    скачивание: Скачивание, записано: list[dict[str, object]]
) -> None:
    google_profile.remember("токен-сессии", _кто(name="Иван Петров", picture=ФОТО))

    assert записано == [
        {"token": "токен-сессии", "name": "Иван Петров", "avatar": JPEG, "type": "image/jpeg"}
    ]


def test_отказ_фото_не_мешает_записать_имя(
    скачивание: Скачивание, записано: list[dict[str, object]], caplog: pytest.LogCaptureFixture
) -> None:
    скачивание.заголовок = "text/html"

    with caplog.at_level(logging.INFO):
        google_profile.remember("т", _кто(name="Иван Петров", picture=ФОТО))

    assert записано == [{"token": "т", "name": "Иван Петров", "avatar": None, "type": None}]
    assert "Иван" not in caplog.text and "googleusercontent" not in caplog.text


def test_сбой_сети_не_пробрасывается_и_не_пишет_адрес_в_журнал(
    monkeypatch: pytest.MonkeyPatch,
    записано: list[dict[str, object]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    def упало(url: str) -> tuple[str, bytes]:
        raise RuntimeError(f"совсем непредвиденное {url}")

    monkeypatch.setattr(google_profile, "_open", упало)

    with caplog.at_level(logging.INFO):
        google_profile.remember("т", _кто(name="", picture=ФОТО))

    assert записано == []
    assert "googleusercontent" not in caplog.text


def test_отказ_базы_не_пробрасывается(
    скачивание: Скачивание, monkeypatch: pytest.MonkeyPatch
) -> None:
    def молчит(*_: object, **__: object) -> bool:
        raise AccessError("двойник: база молчит")

    monkeypatch.setattr(google_profile.web_own_profile, "save_google_profile", молчит)

    google_profile.remember("т", _кто(name="Иван", picture=ФОТО))


def test_без_имени_и_фото_в_базу_не_ходим(записано: list[dict[str, object]]) -> None:
    google_profile.remember("т", _кто())

    assert записано == []


def test_настоящий_редирект_не_выполняется(monkeypatch: pytest.MonkeyPatch) -> None:
    """Живой сервер на localhost отвечает 302 на другой хост: `_open` отказывает, а не идёт туда."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    ходили: list[str] = []

    class Обработчик(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            ходили.append(self.path)
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:1/secret")
            self.end_headers()

        def log_message(self, *_: object) -> None:
            return None

    сервер = HTTPServer(("127.0.0.1", 0), Обработчик)
    поток = threading.Thread(target=сервер.serve_forever, daemon=True)
    поток.start()
    try:
        with pytest.raises(google_profile.AvatarRefused):
            google_profile._open(f"http://127.0.0.1:{сервер.server_port}/photo")
    finally:
        сервер.shutdown()
        сервер.server_close()

    assert ходили == ["/photo"], "после редиректа сходили ещё куда-то"
