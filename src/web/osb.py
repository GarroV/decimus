"""Страница «ОСБ»: очереди предписаний сети (D599, D606; шаг 1 спеки 2026-10-21-osb-prescriptions).

Один вопрос на экран — «какие предписания ждут нас и в каком они состоянии».
Раскладка та же, что у «Действий» (`actions_screen`, `actions/index.html`):
список слева, панель выбранного предписания справа. Отличие — вместо вкладок
«Экшн-планы» и «Предписания» очереди со счётчиками: «На согласовании»,
«Согласовано, не отправлено», «Действуют» (просроченные сверху), «Черновики»,
«Закрытые».

Страницу видят ОСБ, админ и главный админ (`view.osb`); кнопки действий в панели
и «Новое предписание» — только у тех, у кого есть `prescription.manage`
(ОСБ, главный админ): админ смотрит без кнопок. Записи ведут маршруты
`prescriptions.py` — здесь только чтение и раскладка.
"""

from __future__ import annotations

from typing import Any

from flask import Flask, request, url_for

from src.db import prescriptions as rx
from src.db.config import load_action_plan_settings

from . import actions_screen, auth, ui_lang
from . import country as country_data
from . import prescriptions as web_rx
from .actions_screen import TAB_OSB
from .config import Settings
from .sections import section

#: Очереди страницы в порядке показа; `closed` читается отдельным запросом.
QUEUE_REVIEW = "review"
QUEUE_APPROVED = "approved"
QUEUE_ACTIVE = "active"
QUEUE_DRAFTS = "drafts"
QUEUE_CLOSED = "closed"
QUEUES = (QUEUE_REVIEW, QUEUE_APPROVED, QUEUE_ACTIVE, QUEUE_DRAFTS, QUEUE_CLOSED)
DEFAULT_QUEUE = QUEUE_REVIEW

#: Статус базы, чьи строки лежат в очереди.
_STATUS_OF = {
    QUEUE_REVIEW: rx.STATUS_REVIEW,
    QUEUE_APPROVED: rx.STATUS_APPROVED,
    QUEUE_ACTIVE: rx.STATUS_ISSUED,
    QUEUE_DRAFTS: rx.STATUS_DRAFT,
}


def _lang(conf: Settings) -> str:
    return ui_lang.request_lang(conf.ui_lang)


def queue_rows(
    rows: tuple[rx.Prescription, ...], queue: str, *, today: Any
) -> tuple[rx.Prescription, ...]:
    """Строки очереди «Действуют» — просроченные сверху, по сроку; остальные как пришли."""
    if queue != QUEUE_ACTIVE:
        return rows
    return tuple(sorted(rows, key=lambda p: (not p.overdue(today), p.due_on, p.created_at)))


def _first_busy(counts: dict[str, int]) -> str:
    return next((q for q in QUEUES if q != QUEUE_CLOSED and counts.get(q)), DEFAULT_QUEUE)


def screen_context(lang: str) -> dict[str, Any]:
    """Список очереди и полоса отбора: очередь и страна живут в адресе."""
    страна = country_data.normalize_code(request.args.get("country") or "")
    заказанная = (request.args.get("queue") or "").strip()
    reach = auth.current_reach()
    сегодня = rx.today()

    открытые = rx.list_prescriptions(reach=reach)
    закрытые = (
        rx.list_prescriptions(reach=reach, closed=True) if заказанная == QUEUE_CLOSED else None
    )
    страны = tuple(sorted({p.country for p in (закрытые or открытые).rows} | {страна} - {""}))

    def в_стране(rows: tuple[rx.Prescription, ...]) -> tuple[rx.Prescription, ...]:
        return tuple(p for p in rows if not страна or p.country == страна)

    открытые_в_стране = в_стране(открытые.rows)
    счётчики = {
        queue: sum(1 for p in открытые_в_стране if p.status == status)
        for queue, status in _STATUS_OF.items()
    }
    # Очередь без выбора — первая непустая: пустое «На согласовании» при живом
    # «Согласовано · 1» выглядело бы как «ничего нет».
    очередь = заказанная if заказанная in QUEUES else _first_busy(счётчики)
    счётчики[QUEUE_CLOSED] = rx.status_counts(reach=reach, country=страна or None)[rx.STATUS_CLOSED]
    if закрытые is not None:
        строки = в_стране(закрытые.rows)
        обрезано = закрытые.truncated
    else:
        строки = queue_rows(
            tuple(p for p in открытые_в_стране if p.status == _STATUS_OF[очередь]),
            очередь,
            today=сегодня,
        )
        обрезано = открытые.truncated

    def отбор(**изменения: str) -> str:
        параметры: dict[str, Any] = {
            "country": страна,
            "queue": заказанная if заказанная in QUEUES else "",
            "lang": lang,
            **изменения,
        }
        return url_for("osb", **{k: v for k, v in параметры.items() if v})

    новый_адрес: dict[str, Any] = {k: v for k, v in (("country", страна), ("lang", lang)) if v}
    return {
        "title_key": "section.osb.title",
        "rows": строки,
        "countries": страны,
        "country": страна,
        "queue": очередь,
        "queues": tuple((q, f"osb.queue.{q}", счётчики[q]) for q in QUEUES),
        "empty_key": f"osb.empty.{очередь}",
        "truncated": обрезано,
        "truncated_key": "rx.truncated",
        "limit": rx.LIST_LIMIT,
        "total": len(строки),
        "select_url": отбор,
        "hq": True,
        "new_url": url_for("rx_new", **новый_адрес),
        **web_rx.common(),
    }


def install(app: Flask, conf: Settings) -> None:
    """Повесить страницу «ОСБ» и подключить к ней панель предписания."""
    max_bytes = load_action_plan_settings().max_bytes
    actions_screen.register(
        app,
        TAB_OSB,
        actions_screen.Tab(
            screen=screen_context,
            panel=lambda item_id, **outcome: web_rx.panel_context(
                item_id, max_bytes=max_bytes, **outcome
            ),
            missing=web_rx.not_found,
        ),
    )

    @app.get(section("osb").path, endpoint="osb")
    def osb_page() -> str:
        return actions_screen.view(conf, TAB_OSB)
