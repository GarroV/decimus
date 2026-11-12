"""Тур по интерфейсу (D756, D759 п.6): какие шаги увидит человек и что в них написано.

Тур одностраничный: левая панель, поиск, колокольчик и меню учётки есть на каждой
странице, поэтому весь интерфейс обходится на одном месте, без переходов между экранами.
Шаги собирает сервер, по разделам, которые открыты именно этой роли: тур не зовёт туда,
куда не пустят. Тексты — из словаря на языке страницы; в браузер уходят готовые строки,
экранированные для разметки (библиотека вставляет описание шага как HTML).

Контроллер в браузере (`static/onboarding-tour.js`) берёт те шаги, чьи цели видны на
экране: на телефоне боковой панели нет, и шаги групп сменяются шагом нижней панели.

Автозапуск — только партнёру и только при первом входе (`tour_seen_at is null`), на
«Главной». Повтор из меню учётки — любой роли и ничего не пишет в базу.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from markupsafe import escape

from src.domain.permissions import SIDE_PARTNER, side_of
from src.domain.tenants import canonical_tenant

from .sections import Section
from .texts import t

#: Группы левой панели в порядке показа (`Section.group`, D499).
GROUPS = ("work", "stats", "admin")


def is_partner(tenant: str) -> bool:
    """Пространство партнёра (не УК)."""
    код = canonical_tenant(tenant or "")
    return bool(код) and side_of(код) == SIDE_PARTNER


def should_autostart(*, tenant: str, seen: bool, peeking: bool, demo_seen: bool | None) -> bool:
    """Открывать ли тур сам: партнёру, который его ещё не видел.

    `demo_seen` — отметка из куки открытого демо (там общие учётки, в базу не пишем);
    `None` — не демо, решает `seen` из профиля. Просмотр чужими глазами (D726) — только
    чтение, тур там не открывается.
    """
    if peeking or not is_partner(tenant):
        return False
    return not (seen if demo_seen is None else demo_seen)


def _line(item: Section, lang: str) -> str:
    """Строка о разделе: жирное название и пояснение. Всё экранировано."""
    title = escape(t(f"section.{item.key}.title", lang))
    return f"<b>{title}</b> — {escape(t(f'tour.section.{item.key}', lang))}"


def _text(items: Sequence[Section], lang: str) -> str:
    return "<br>".join(_line(item, lang) for item in items)


def _step(key: str, targets: list[str], title: str, text: str, **extra: Any) -> dict[str, Any]:
    return {"key": key, "targets": targets, "title": str(escape(title)), "text": text, **extra}


def steps(
    sections: Sequence[Section], lang: str, *, partner: bool, settings_href: str
) -> list[dict[str, Any]]:
    """Шаги тура для разделов, открытых человеку.

    `targets` — имена `data-tour` в разметке; браузер берёт первую видимую цель и
    пропускает шаг, у которого ни одной нет (группы — на телефоне, нижняя панель — на
    компьютере).
    """
    shown = [item for item in sections if item.menu]
    result = [
        _step(
            "welcome", [], t("tour.welcome.title", lang), str(escape(t("tour.welcome.text", lang)))
        )
    ]
    for group in GROUPS:
        items = [item for item in shown if item.group == group]
        if items:
            result.append(
                _step(
                    f"group-{group}",
                    [f"group-{group}"],
                    t(f"tour.group.{group}", lang),
                    _text(items, lang),
                )
            )
    if shown:
        result.append(_step("tabbar", ["tabbar"], t("tour.tabbar.title", lang), _text(shown, lang)))
    result.extend(
        [
            _step(
                "search",
                ["search"],
                t("tour.search.title", lang),
                str(escape(t("tour.search.text", lang))),
            ),
            _step(
                "bell", ["bell"], t("tour.bell.title", lang), str(escape(t("tour.bell.text", lang)))
            ),
            _step(
                "menu", ["menu"], t("tour.menu.title", lang), str(escape(t("tour.menu.text", lang)))
            ),
        ]
    )
    key = "tour.settings.text_partner" if partner else "tour.settings.text"
    link = (
        f'<a class="tour-link" href="{escape(settings_href)}">'
        f"{escape(t('tour.settings.link', lang))}</a>"
    )
    result.append(
        _step(
            "settings",
            ["settings", "menu"],
            t("tour.settings.title", lang),
            f"{escape(t(key, lang))}<br>{link}",
        )
    )
    return result


def config(
    sections: Sequence[Section],
    lang: str,
    *,
    tenant: str,
    autostart: bool,
    settings_href: str,
    done_url: str,
    lib_js: str,
    lib_css: str,
    tour_css: str,
) -> dict[str, Any]:
    """Всё, что нужно контроллеру в браузере: шаги, подписи кнопок, адреса, автозапуск."""
    return {
        "steps": steps(sections, lang, partner=is_partner(tenant), settings_href=settings_href),
        "autostart": autostart,
        "doneUrl": done_url,
        "lib": {"js": lib_js, "css": lib_css, "tourCss": tour_css},
        "ui": {
            "next": t("tour.next", lang),
            "prev": t("tour.prev", lang),
            "done": t("tour.done", lang),
            "close": t("tour.close", lang),
            "progress": t("tour.progress", lang),
        },
    }
