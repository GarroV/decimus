"""Тур по интерфейсу (D756) — ядро: чьи шаги, что в них написано, кому тур открывается сам."""

from __future__ import annotations

import re
from typing import Any

from src.web import onboarding_tour as tour
from src.web.sections import SECTIONS, Section
from src.web.texts import t

ССЫЛКА = "/settings?lang=ru&tile=claude#connections"


def _разделы(*ключи: str) -> list[Section]:
    return [s for s in SECTIONS if s.key in ключи]


def _шаги(*ключи: str, lang: str = "ru", partner: bool = True) -> list[dict[str, Any]]:
    return tour.steps(_разделы(*ключи), lang, partner=partner, settings_href=ССЫЛКА)


def test_у_каждого_раздела_меню_есть_строка_тура_на_обоих_языках() -> None:
    for раздел in (s for s in SECTIONS if s.menu):
        for lang in ("ru", "en"):
            assert t(f"tour.section.{раздел.key}", lang)


def test_шаги_идут_по_группам_панели_и_кончаются_настройками() -> None:
    ключи = [s["key"] for s in _шаги("overview", "registry", "country", "ratings", "admin")]

    assert ключи == [
        "welcome",
        "group-work",
        "group-stats",
        "group-admin",
        "tabbar",
        "search",
        "bell",
        "menu",
        "settings",
    ]


def test_шага_группы_без_открытых_разделов_нет_и_названия_закрытого_раздела_тоже() -> None:
    шаги = _шаги("overview", "registry")
    ключи = [s["key"] for s in шаги]
    текст = " ".join(s["text"] for s in шаги)

    assert "group-stats" not in ключи and "group-admin" not in ключи
    assert t("section.osb.title", "ru") not in текст
    # «Календарь» (D760: у партнёра снят) в туре появляется, только если раздел открыт роли.
    assert t("section.calendar.title", "ru") not in текст


def test_раздел_роли_назван_в_шаге_своей_группы_и_в_нижней_панели() -> None:
    шаги = {s["key"]: s for s in _шаги("overview", "calendar")}

    assert t("section.calendar.title", "ru") in шаги["group-work"]["text"]
    assert t("section.calendar.title", "ru") in шаги["tabbar"]["text"]


def test_цели_шагов_у_панели_и_у_телефона_разные() -> None:
    шаги = {s["key"]: s for s in _шаги("overview")}

    assert шаги["group-work"]["targets"] == ["group-work"]
    assert шаги["tabbar"]["targets"] == ["tabbar"]
    # Последний шаг на телефоне, где шестерёнки нет, показывает на меню учётки.
    assert шаги["settings"]["targets"] == ["settings", "menu"]
    assert шаги["welcome"]["targets"] == []


def test_у_партнёра_про_claude_честно_что_загрузки_проверок_нет() -> None:
    партнёр = _шаги("overview", partner=True)[-1]["text"]
    ук = _шаги("overview", partner=False)[-1]["text"]

    assert t("tour.settings.text_partner", "ru") in партнёр
    assert t("tour.settings.text", "ru") in ук and t("tour.settings.text_partner", "ru") not in ук
    assert ССЫЛКА.replace("&", "&amp;") in партнёр


def test_в_описания_идёт_только_разрешённая_разметка() -> None:
    """Библиотека вставляет описание шага как HTML: кроме наших `<b>`, `<br>`, `<a>` — ничего."""
    for lang in ("ru", "en"):
        for шаг in _шаги("overview", "registry", "country", "admin", "administration", lang=lang):
            остаток = re.sub(r"</?(b|br|a)( [^<>]*)?>", "", шаг["text"] + шаг["title"])
            assert "<" not in остаток and ">" not in остаток, шаг["key"]


def test_чужая_разметка_в_тексте_экранируется(monkeypatch) -> None:
    monkeypatch.setitem(
        tour.t.__globals__["TEXTS"], "tour.search.text", {"ru": "<img src=x onerror=1>", "en": "x"}
    )

    текст = next(s for s in _шаги("overview") if s["key"] == "search")["text"]

    assert "<img" not in текст and "&lt;img" in текст


def test_автозапуск_партнёру_который_тур_не_видел() -> None:
    assert tour.should_autostart(tenant="ARMENIA", seen=False, peeking=False, demo_seen=None)
    assert not tour.should_autostart(tenant="ARMENIA", seen=True, peeking=False, demo_seen=None)


def test_автозапуска_нет_у_ук_и_при_просмотре_чужими_глазами() -> None:
    assert not tour.should_autostart(tenant="HQ", seen=False, peeking=False, demo_seen=None)
    assert not tour.should_autostart(tenant="ARMENIA", seen=False, peeking=True, demo_seen=None)


def test_в_демо_решает_кука_а_не_профиль_общей_учётки() -> None:
    assert tour.should_autostart(tenant="demo", seen=True, peeking=False, demo_seen=False)
    assert not tour.should_autostart(tenant="demo", seen=False, peeking=False, demo_seen=True)
