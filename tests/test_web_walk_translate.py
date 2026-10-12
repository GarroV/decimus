"""D394: перевод свободного текста на язык отчёта в мини-аппе.

Ядро здесь — выбор языка перевода: он берётся из языка ОТЧЁТА проверки, а не
из языка интерфейса. Ошибка молчалива: перевод придёт гладкий, но на не тот
язык, и аудитор поправит его в поле, не заметив, что отчёт будет на другом.
Остальное — отказы и то, что адрес ничего не записывает (модель предлагает,
фиксирует человек).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from test_web_walk import АУДИТОР, ТОКЕН, _приложение
from test_web_walk_write import Клиент

from src.db.bot_links import NEVER_BOUND
from src.domain import get_state, start_inspection
from src.recognize import translate
from src.recognize.client import ModelAnswer
from src.recognize.config import load_recognize_settings
from src.recognize.errors import ModelUnavailable
from src.web import walk, walk_access, walk_translate, walk_write


class Модель:
    """Подмена модели: запоминает инструкцию и вопрос, отвечает заданным текстом."""

    def __init__(self) -> None:
        self.звали: list[dict[str, Any]] = []
        self.ответ: dict[str, Any] = {"text": "Burnt-on grease on the oven floor."}
        self.падает = False

    def __call__(self, **kw: Any) -> ModelAnswer:
        self.звали.append(kw)
        if self.падает:
            raise ModelUnavailable("нет ключа")
        return ModelAnswer(payload=self.ответ)


@pytest.fixture
def модель(monkeypatch: pytest.MonkeyPatch) -> Модель:
    m = Модель()
    monkeypatch.setattr(translate, "ask_model", m)
    # Ключ читает подменённый `ask_model`, но имя модели берётся из настроек.
    monkeypatch.setattr(
        translate,
        "load_recognize_settings",
        lambda: load_recognize_settings({"OPENAI_API_KEY": "k"}),
    )
    return m


@pytest.fixture
def завести(domain_env: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[..., Клиент]:
    """Проверка с заданными языками интерфейса и чек-листа и клиент с подписью Telegram.

    Язык отчёта до конца обхода равен языку чек-листа (D415).
    """

    def _завести(*, ui_lang: str, speech_lang: str) -> Клиент:
        start_inspection(
            АУДИТОР,
            unit="Белград-1",
            kind="planned",
            report_lang=speech_lang,
            ui_lang=ui_lang,
            speech_lang=speech_lang,
        )
        monkeypatch.setattr(walk.queries, "previous_findings", lambda **_: None)
        monkeypatch.setattr(walk_access.bot_links, "standing", lambda _: NEVER_BOUND)
        return Клиент(
            _приложение(
                monkeypatch, TELEGRAM_BOT_TOKEN=ТОКЕН, ALLOWED_TELEGRAM_IDS=f"{АУДИТОР},777"
            ).test_client()
        )

    return _завести


def _перевести(клиент: Клиент, *, подпись: bool = True, **тело: Any) -> Any:
    заголовки = {"X-Telegram-Init-Data": клиент.init} if подпись else {}
    return клиент.c.post(
        walk_translate.TRANSLATE_PATH,
        data=json.dumps(тело),
        content_type="application/json",
        headers=заголовки,
    )


def test_перевод_отдаётся_и_ничего_не_записывает(
    завести: Callable[..., Клиент], модель: Модель
) -> None:
    клиент = завести(ui_lang="ru", speech_lang="ru")

    ответ = _перевести(клиент, text="Нагар на поду печи.")

    assert ответ.status_code == 200, ответ.get_json()
    assert ответ.get_json() == {"text": "Burnt-on grease on the oven floor.", "lang": "en"}
    assert ответ.headers["Cache-Control"] == "no-store"
    assert модель.звали[0]["question"] == "Нагар на поду печи."
    проверка = get_state(АУДИТОР)
    assert проверка is not None and проверка.findings == [], "модель предлагает, фиксирует человек"


def test_язык_перевода_это_другой_язык_а_не_язык_чек_листа_и_не_интерфейса(
    завести: Callable[..., Клиент], модель: Модель
) -> None:
    клиент = завести(ui_lang="ru", speech_lang="ru")

    ответ = _перевести(клиент, text="Нагар на поду печи.")

    assert ответ.get_json()["lang"] == "en"
    assert "into English" in модель.звали[0]["instructions"], (
        "интерфейс и чек-лист русские: переводить надо на другой язык платформы, английский"
    )


def test_чек_лист_английский_переводит_на_русский(
    завести: Callable[..., Клиент], модель: Модель
) -> None:
    клиент = завести(ui_lang="en", speech_lang="en")

    ответ = _перевести(клиент, text="Burnt-on grease.")

    assert ответ.get_json()["lang"] == "ru"
    assert "into Russian" in модель.звали[0]["instructions"]


def test_перевод_без_подписи_не_работает(завести: Callable[..., Клиент], модель: Модель) -> None:
    клиент = завести(ui_lang="ru", speech_lang="ru")

    ответ = _перевести(клиент, подпись=False, text="нагар")

    assert ответ.status_code in (401, 403) and модель.звали == []


def test_модель_недоступна_отказ_словами_экрана(
    завести: Callable[..., Клиент], модель: Модель
) -> None:
    клиент = завести(ui_lang="ru", speech_lang="ru")
    модель.падает = True

    ответ = _перевести(клиент, text="нагар")

    assert ответ.status_code == 503
    сообщение = ответ.get_json()["message"]
    assert "Перевод" in сообщение, "аудитор должен понять, что перевод не вышел"
    assert "нет ключа" not in сообщение, "внутренности — в журнал, не аудитору"


def test_слишком_длинный_текст_отклоняется_до_модели(
    завести: Callable[..., Клиент], модель: Модель
) -> None:
    клиент = завести(ui_lang="ru", speech_lang="ru")

    ответ = _перевести(клиент, text="а" * (walk_write.MAX_TEXT + 1))

    assert ответ.status_code == 422 and модель.звали == []


def test_пустой_текст_отклоняется_до_модели(завести: Callable[..., Клиент], модель: Модель) -> None:
    клиент = завести(ui_lang="ru", speech_lang="ru")

    ответ = _перевести(клиент, text="   ")

    assert ответ.status_code == 422 and модель.звали == []


def test_слишком_длинный_перевод_отклоняется(
    завести: Callable[..., Клиент], модель: Модель
) -> None:
    клиент = завести(ui_lang="ru", speech_lang="ru")
    модель.ответ = {"text": "a" * (walk_write.MAX_TEXT + 1)}

    ответ = _перевести(клиент, text="нагар")

    assert ответ.status_code == 422


def test_пустой_ответ_модели_это_отказ_а_не_пустое_поле(
    завести: Callable[..., Клиент], модель: Модель
) -> None:
    клиент = завести(ui_lang="ru", speech_lang="ru")
    модель.ответ = {"text": "  "}

    ответ = _перевести(клиент, text="нагар")

    assert ответ.status_code == 503, "пустой перевод затёр бы текст аудитора"


def test_без_проверки_переводить_некуда(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch, модель: Модель
) -> None:
    monkeypatch.setattr(walk_access.bot_links, "standing", lambda _: NEVER_BOUND)
    клиент = Клиент(
        _приложение(
            monkeypatch, TELEGRAM_BOT_TOKEN=ТОКЕН, ALLOWED_TELEGRAM_IDS=f"{АУДИТОР},777"
        ).test_client()
    )

    ответ = _перевести(клиент, text="нагар")

    assert ответ.status_code == 409 and модель.звали == []


def test_данные_экрана_несут_язык_кнопки_перевода(завести: Callable[..., Клиент]) -> None:
    клиент = завести(ui_lang="ru", speech_lang="ru")

    ответ = клиент.c.post(walk.DATA_PATH, headers={"X-Telegram-Init-Data": клиент.init})

    данные = ответ.get_json()
    assert данные["translate_lang"] == "en", "кнопка называет язык по этому полю"
    assert данные["report_lang"] == "ru", "до конца обхода язык отчёта равен языку чек-листа"
