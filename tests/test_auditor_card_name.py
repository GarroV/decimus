"""Имя проверяющего: карточка человека → `AUDITOR_NAMES` → профиль Telegram (D642).

Имя уходит партнёру в шапку отчёта и на штамп кадра, поэтому порядок источников
и поведение при сбое чтения карточки закреплены здесь, без базы.
"""

from __future__ import annotations

import logging

import pytest

from src.bot.auditor import auditor_name, auditor_name_was_shortened
from src.db import auditor_card
from src.db.errors import AccessError


def test_карточка_сильнее_перечня_и_профиля() -> None:
    имя = auditor_name(111, "Rinat", {111: "Из перечня"}, card_name="Rinat Zhulfaev")
    assert имя == "Rinat Zhulfaev"


def test_нет_карточки_берётся_перечень() -> None:
    assert auditor_name(111, "Rinat", {111: "Из перечня"}, card_name=None) == "Iz perechnia"


def test_нет_карточки_и_перечня_берётся_профиль() -> None:
    assert auditor_name(111, "Rinat", {}, card_name=None) == "Rinat"


def test_в_карточке_одно_имя_без_фамилии_берётся_что_есть() -> None:
    assert auditor_name(111, "Rinat", {}, card_name="Rinat") == "Rinat"


def test_пустая_карточка_как_отсутствующая() -> None:
    assert auditor_name(111, "Rinat", {}, card_name="   ") == "Rinat"


def test_кириллица_карточки_уходит_в_отчёт_латиницей() -> None:
    assert auditor_name(111, "Rinat", {}, card_name="Жульфаев Ринат") == "Zhulfaev Rinat"


def test_длинное_имя_из_карточки_обрезается_и_это_видно() -> None:
    длинное = "Фамилия " * 30
    assert auditor_name_was_shortened(111, "Rinat", {}, card_name=длинное) is True
    assert len(auditor_name(111, "Rinat", {}, card_name=длинное).encode()) <= 100


def test_сбой_чтения_карточки_не_ломает_старт_и_пишется_в_журнал(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def упало(*_a: object, **_k: object) -> None:
        raise AccessError("база недоступна")

    monkeypatch.setattr(auditor_card, "_fetch_name", упало)
    with caplog.at_level(logging.WARNING):
        assert auditor_card.name_by_telegram_or_none(111) is None
        assert auditor_card.name_by_login_or_none("HQ", "rinat") is None
    assert "карточк" in caplog.text.lower()


def test_карточка_найдена_имя_возвращается(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auditor_card, "_fetch_name", lambda *_a, **_k: "Zhulfaev Rinat")
    assert auditor_card.name_by_telegram_or_none(111) == "Zhulfaev Rinat"


def test_mcp_имя_из_карточки_вошедшего(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.mcp import imports

    seen: list[tuple[str, str]] = []

    def карточка(tenant: str, login: str) -> str:
        seen.append((tenant, login))
        return "Rinat Zhulfaev"

    monkeypatch.setattr(auditor_card, "name_by_login_or_none", карточка)
    assert imports._card_name("HQ", "web:rinat") == "Rinat Zhulfaev"
    assert seen == [("HQ", "rinat")]


def test_mcp_служебный_токен_карточки_не_ищет(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.mcp import imports

    def не_звать(*_a: object, **_k: object) -> str:
        raise AssertionError("у служебного токена карточки нет")

    monkeypatch.setattr(auditor_card, "name_by_login_or_none", не_звать)
    assert imports._card_name("HQ", "mcp:HQ") is None
