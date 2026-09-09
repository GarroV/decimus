"""D106/D107, issue #231: DECIMUS — имя всей системы, появляется в шапке отчёта.

Продукт до этого решения не назывался никак: отчёт был озаглавлен описательно
(«Отчёт о проверке пиццерии»), и партнёр, который бота никогда не открывал, не
видел нигде, чей это документ. Владелец сузил объём (D107): бот сейчас не
трогается, а DECIMUS ставится только рядом с заголовком отчёта — единственной
поверхности, которую видит партнёр.

Имя не переводится (не строка каталога `T`): проверяется, что оно одинаковое
на обоих языках и не исчезает вместе с локализованным заголовком.
"""

from __future__ import annotations

from collections.abc import Callable

from conftest import Run

BRAND = "DECIMUS"
ЗАГОЛОВОК = {"ru": "Отчёт о проверке пиццерии", "en": "Pizzeria inspection report"}


def html_of(report: Callable[..., Run], *args: str) -> str:
    r = report("html", *args)
    assert r.code == 0, r.text
    return r.out


def test_бренд_виден_в_шапке_отчёта_ru(
    started: Callable[..., Run], report: Callable[..., Run]
) -> None:
    html = html_of(report, "--lang", "ru")
    assert BRAND in html, f"DECIMUS нет в шапке ru-отчёта:\n{html[:1500]}"
    assert ЗАГОЛОВОК["ru"] in html, "описательный заголовок пропал вместе с брендом"


def test_бренд_виден_в_шапке_отчёта_en(
    started: Callable[..., Run], report: Callable[..., Run]
) -> None:
    html = html_of(report, "--lang", "en")
    assert BRAND in html, f"DECIMUS нет в шапке en-отчёта:\n{html[:1500]}"
    assert ЗАГОЛОВОК["en"] in html, "описательный заголовок пропал вместе с брендом"


def test_бренд_не_переводится(started: Callable[..., Run], report: Callable[..., Run]) -> None:
    """Одна и та же строка на обоих языках — DECIMUS не строка каталога `T`."""
    ru = html_of(report, "--lang", "ru")
    en = html_of(report, "--lang", "en")
    assert ru.count(BRAND) == en.count(BRAND) == 1, "бренд должен встречаться ровно один раз"
