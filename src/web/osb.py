"""Страница «ОСБ»: очереди предписаний сети (D599, D606; шаг 1 спеки 2026-10-21-osb-prescriptions).

Один вопрос на экран — «какие предписания ждут нас и в каком они состоянии».
Раскладка по D611: слева столбец стран (сверху «Все страны») со счётчиками того,
что ждёт ОСБ, справа блоки по состоянию — «На согласовании», «Согласовано, не
отправлено», «Действуют» (просроченные сверху), «Черновики», «Закрытые» (свёрнуты).
Ряда вкладок и чипов нет. Выбранное предписание открывается панелью справа
(`actions_screen`, `actions/index.html`), как у «Действий»; сборка частей —
`actions_columns`.

Страницу видят ОСБ, админ и главный админ (`view.osb`); кнопки действий в панели
и «Новое предписание» — только у тех, у кого есть `prescription.manage`
(ОСБ, главный админ): админ смотрит без кнопок. Записи ведут маршруты
`prescriptions.py` — здесь только чтение и раскладка.
"""

from __future__ import annotations

from typing import Any

from flask import Flask, request, url_for

from src.db.config import load_action_plan_settings

from . import actions_columns as columns
from . import actions_screen
from . import country as country_data
from . import prescriptions as web_rx
from .actions_screen import TAB_OSB
from .config import Settings
from .sections import section


def screen_context(lang: str) -> dict[str, Any]:
    """Столбец стран и блоки по состоянию: страна и «закрытые» живут в адресе."""
    страна = country_data.normalize_code(request.args.get("country") or "")
    новый_адрес: dict[str, Any] = {k: v for k, v in (("country", страна), ("lang", lang)) if v}
    return {
        **columns.rx_screen(
            lang,
            endpoint="osb",
            fixed={},
            count_closed=True,
            empty_key="osb.empty",
            title_key="section.osb.title",
        ),
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
