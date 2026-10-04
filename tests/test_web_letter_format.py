"""Письмо с форматированием на экране, при сохранении и в выгрузке (T353, #332).

Сам белый список проверяется в `test_web_letter_markup.py`. Здесь — что он
стоит на каждой двери: письмо, сохранённое через экран, ложится в запись
очищенным; запись выводится очищенной, даже если легла в базу в обход экрана;
заготовка движка — простой текст и разметкой не становится; файл выгрузки
несёт то же форматирование, что и черновик Google, и честный текстовый вариант.
"""

from __future__ import annotations

import email
import email.message
import email.policy
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from flask.testing import FlaskClient
from test_web_letter import ПРОВЕРКА, СВОЙ, собранное, стенд  # noqa: F401 — фикстура

from src.db import letters as letters_store
from src.web import inspections as data

ВРЕДНОЕ = (
    '<b onclick="alert(1)">Жирно</b> <a href="javascript:alert(2)">клик</a>'
    "<script>alert(3)</script><img src=x onerror=alert(4)>"
    '<i><a href="https://dodo.example/plan" onmouseover="alert(5)">план</a></i>'
)
ОЧИЩЕННОЕ = '<b>Жирно</b> клик<i><a href="https://dodo.example/plan">план</a></i>'


def _записанное(body: str) -> SimpleNamespace:
    return SimpleNamespace(
        id="1",
        body=body,
        lang="en",
        saved_by="director",
        created_at=datetime(2026, 10, 4, tzinfo=UTC),
    )


def _без_опасного(страница: str) -> None:
    for след in ("alert(", "javascript:", "onclick", "onerror", "onmouseover", "<script", "<img"):
        assert след not in страница, след


def test_сохраняется_очищенная_разметка(
    стенд: FlaskClient,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange — подменяется сама запись, а не `remember_letter`: очистка
    # стоит именно в нём, и подмена выше по цепочке её бы обошла.
    легло: list[str] = []

    def _save(_id: str, **поля: Any) -> object:
        легло.append(поля["body"])
        return _записанное(поля["body"])

    monkeypatch.setattr(letters_store, "save_letter", _save)

    # Act
    ответ = стенд.post(
        f"/inspections/{ПРОВЕРКА}/letter/save",
        data={"text": ВРЕДНОЕ, "letter_lang": "en"},
        headers=СВОЙ,
    )

    # Assert
    assert ответ.status_code == 303
    assert легло == [ОЧИЩЕННОЕ]


def test_письмо_из_одной_разметки_уходит_в_запись_пустым(
    стенд: FlaskClient,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Пустое письмо запись отклоняет своим правилом — его и надо задействовать."""
    легло: list[str] = []
    monkeypatch.setattr(
        letters_store, "save_letter", lambda _id, **поля: легло.append(поля["body"])
    )

    стенд.post(
        f"/inspections/{ПРОВЕРКА}/letter/save",
        data={"text": "<b> </b><script>alert(1)</script>", "letter_lang": "en"},
        headers=СВОЙ,
    )

    assert легло == [""]


def test_записанное_выводится_очищенным(
    стенд: FlaskClient,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Запись могла лечь в базу в обход экрана — вывод ей на слово не верит."""
    monkeypatch.setattr(data, "saved_letter", lambda *_a, **_k: _записанное(ВРЕДНОЕ))

    страница = стенд.get(f"/inspections/{ПРОВЕРКА}/letter").get_data(as_text=True)

    # Страница целиком — со своими скриптами, поэтому смотрим окно письма.
    окно = страница[страница.index("data-letter-editor") :]
    окно = окно[: окно.index("</div>")]
    _без_опасного(окно)
    for след in ("alert(", "javascript:", "onerror", "onmouseover"):
        assert след not in страница, след
    # В редакторе — разметка, в поле без скрипта — она же текстом.
    assert окно.endswith(f">{ОЧИЩЕННОЕ}")
    assert "&lt;b&gt;Жирно&lt;/b&gt;" in страница


def test_заготовка_движка_не_становится_разметкой(
    стенд: FlaskClient,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Заготовка — простой текст: угловая скобка в ней остаётся скобкой."""
    monkeypatch.setattr(
        data,
        "build_letter",
        lambda *_a, **_k: собранное(letter="Срок <b>3</b> дня <script>alert(1)</script>"),
    )

    страница = стенд.get(f"/inspections/{ПРОВЕРКА}/letter").get_data(as_text=True)

    assert "<b>3</b>" not in страница
    assert "<script>alert" not in страница
    assert "Срок &lt;b&gt;3&lt;/b&gt; дня" in страница


def _письмо_из(ответ: Any) -> email.message.EmailMessage:
    письмо = email.message_from_bytes(ответ.get_data(), policy=email.policy.default)
    assert isinstance(письмо, email.message.EmailMessage)
    return письмо


def test_выгрузка_несёт_форматирование_и_честный_текст(стенд: FlaskClient) -> None:  # noqa: F811
    ответ = стенд.post(
        f"/inspections/{ПРОВЕРКА}/letter",
        data={"text": ВРЕДНОЕ + "\nВторая строка", "letter_lang": "en"},
        headers=СВОЙ,
    )

    assert ответ.status_code == 200
    assert ответ.mimetype == "message/rfc822"
    письмо = _письмо_из(ответ)
    assert письмо["X-Unsent"] == "1"
    разметка = письмо.get_body(preferencelist=("html",)).get_content()
    текст = письмо.get_body(preferencelist=("plain",)).get_content()
    assert ОЧИЩЕННОЕ in разметка
    assert текст.strip() == "Жирно кликплан (https://dodo.example/plan)\nВторая строка"
    _без_опасного(разметка)
    _без_опасного(текст)


def test_пустое_письмо_файлом_не_отдаётся(стенд: FlaskClient) -> None:  # noqa: F811
    ответ = стенд.post(
        f"/inspections/{ПРОВЕРКА}/letter",
        data={"text": "<script>alert(1)</script>", "letter_lang": "en"},
        headers=СВОЙ,
    )

    assert ответ.status_code == 303
    assert "export=empty" in ответ.headers["Location"]
