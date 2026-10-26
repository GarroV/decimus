"""D652: голосовой ввод в мини-аппе — `POST /tg/walk/transcribe`.

Ядро — граница «модель предлагает, фиксирует человек»: адрес отдаёт текст и ничего
не пишет в проверку. Остальное — отказы словами экрана (размер, неопознанный,
занято, модель не разобрала) и то, что язык речи берётся из чек-листа проверки.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from bot_harness import bound_only
from test_web_walk import АУДИТОР, ТОКЕН, _приложение
from test_web_walk_write import Клиент

from src.db.busy_lock import Hold
from src.domain import get_state, start_inspection
from src.recognize.errors import TranscriptionFailed
from src.web import walk, walk_access, walk_auth, walk_voice

ЗВУК = b"\x1a\x45\xdf\xa3" + b"\x00" * 2000


class Расшифровка:
    """Подмена `recognize.transcribe`: запоминает вызов, отвечает заданным текстом."""

    def __init__(self) -> None:
        self.звали: list[dict[str, Any]] = []
        self.текст = "Нагар на поду печи."
        self.падает = False

    def __call__(self, audio: bytes, *, lang: str | None = None) -> str:
        self.звали.append({"audio": audio, "lang": lang})
        if self.падает:
            raise TranscriptionFailed("ffmpeg упал: секретная подробность")
        return self.текст


@pytest.fixture
def голос(monkeypatch: pytest.MonkeyPatch) -> Расшифровка:
    подмена = Расшифровка()
    monkeypatch.setattr(walk_voice, "transcribe", подмена)
    # Журнал разбора пишет в файл чата — тесту он не нужен.
    monkeypatch.setattr(walk_voice.journal, "note", lambda *a, **k: None)
    return подмена


@pytest.fixture
def завести(domain_env: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[..., Клиент]:
    def _завести(*, speech_lang: str = "ru") -> Клиент:
        start_inspection(
            АУДИТОР,
            unit="Белград-1",
            kind="planned",
            report_lang=speech_lang,
            ui_lang="ru",
            speech_lang=speech_lang,
        )
        monkeypatch.setattr(walk.queries, "previous_findings", lambda **_: None)
        monkeypatch.setattr(walk_access.bot_links, "standing", bound_only(АУДИТОР, 777))
        return Клиент(_приложение(monkeypatch, TELEGRAM_BOT_TOKEN=ТОКЕН).test_client())

    return _завести


def _надиктовать(клиент: Клиент, звук: bytes = ЗВУК, *, подпись: bool = True) -> Any:
    заголовки = {"X-Telegram-Init-Data": клиент.init} if подпись else {}
    return клиент.c.post(
        walk_auth.VOICE_PATH, data=звук, content_type="audio/webm", headers=заголовки
    )


def test_текст_отдаётся_и_ничего_не_записывает(
    завести: Callable[..., Клиент], голос: Расшифровка
) -> None:
    клиент = завести(speech_lang="en")

    ответ = _надиктовать(клиент)

    assert ответ.status_code == 200, ответ.get_json()
    assert ответ.get_json() == {"text": "Нагар на поду печи."}
    assert ответ.headers["Cache-Control"] == "no-store"
    assert голос.звали == [{"audio": ЗВУК, "lang": "en"}], "язык речи — язык чек-листа"
    проверка = get_state(АУДИТОР)
    assert проверка is not None and проверка.findings == [], "модель предлагает, фиксирует человек"


def test_без_подписи_не_работает(завести: Callable[..., Клиент], голос: Расшифровка) -> None:
    клиент = завести()

    ответ = _надиктовать(клиент, подпись=False)

    assert ответ.status_code in (401, 403) and голос.звали == []


def test_слишком_большая_запись_отказ_до_модели(
    завести: Callable[..., Клиент], голос: Расшифровка
) -> None:
    клиент = завести()

    ответ = _надиктовать(клиент, b"\x00" * (walk_auth.MAX_VOICE_BYTES + 1))

    assert ответ.status_code == 413
    assert "слишком большая" in ответ.get_json()["message"]
    assert голос.звали == []


def test_пустая_запись_отказ_до_модели(завести: Callable[..., Клиент], голос: Расшифровка) -> None:
    клиент = завести()

    ответ = _надиктовать(клиент, b"")

    assert ответ.status_code == 400 and голос.звали == []


def test_не_разобрал_отказ_словами_экрана(
    завести: Callable[..., Клиент], голос: Расшифровка
) -> None:
    клиент = завести()
    голос.падает = True

    ответ = _надиктовать(клиент)

    assert ответ.status_code == 503
    сообщение = ответ.get_json()["message"]
    assert "Не разобрал запись" in сообщение
    assert "ffmpeg" not in сообщение, "внутренности — в журнал, не аудитору"


def test_расшифровка_идёт_в_другом_процессе_отказ_без_вызова_модели(
    завести: Callable[..., Клиент], голос: Расшифровка, monkeypatch: pytest.MonkeyPatch
) -> None:
    клиент = завести()
    monkeypatch.setattr(walk_voice, "try_hold", lambda *_a: Hold(acquired=False))

    ответ = _надиктовать(клиент)

    assert ответ.status_code == 429 and голос.звали == []


def test_чат_отпускается_после_себя_и_после_отказа(
    завести: Callable[..., Клиент], голос: Расшифровка, monkeypatch: pytest.MonkeyPatch
) -> None:
    клиент = завести()
    monkeypatch.setattr(walk_voice, "try_hold", lambda *_a: Hold(acquired=True))
    голос.падает = True
    упавший = _надиктовать(клиент)
    голос.падает = False

    следующий = _надиктовать(клиент)

    assert (упавший.status_code, следующий.status_code) == (503, 200), "чат остался занятым"


def test_без_проверки_расшифровывать_нечего(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch, голос: Расшифровка
) -> None:
    monkeypatch.setattr(walk_access.bot_links, "standing", bound_only(АУДИТОР, 777))
    клиент = Клиент(_приложение(monkeypatch, TELEGRAM_BOT_TOKEN=ТОКЕН).test_client())

    ответ = _надиктовать(клиент)

    assert ответ.status_code == 409 and голос.звали == []
