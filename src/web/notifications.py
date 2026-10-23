"""Колокольчик и красные точки: уведомления в приложении (#1129, D604, D614).

Две вещи на каждой странице — колокольчик в панели (красная точка, если есть
непрочитанное) и точка на пункте меню раздела, где новое. Список открывается
по клику на колокольчик фрагментом `GET /settings/notifications` — по образцу
меню учётки (`account_menu.py`): страница рисует только точки, а список платит
тот, кто его открыл.

**Текст не хранится.** В базе вид события и параметры (`src/db/notifications.py`);
фраза берётся из словаря по ключу `notif.<вид>` на языке человека. Вид, которого
словарь не знает (событие более новой версии), показывается общей строкой, а не
роняет список.

**Раздел точки — по виду** (`SECTION_OF_KIND`): запрос на согласование ведёт на
страницу «ОСБ», ответы автору — в «Действия».

**Прочитанное.** Клик по уведомлению отмечает его (POST) и ведёт по адресу;
открытие страницы, чей адрес совпадает с адресом уведомления, отмечает его тоже —
на сервере, при отрисовке страницы (`state`). Читается и отмечается только своё:
чья учётка — решает сессия, а не форма.

Ничего наружу не отправляется — ни почты, ни Telegram (§7 глобальных правил).
Отказ базы страницу не роняет: колокольчик остаётся без точки.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlsplit

from flask import Flask, Response, g, make_response, render_template, request
from flask import Response as FlaskResponse

from src.db import notifications as store
from src.db.errors import DbError

from . import auth, ui_lang
from .config import Settings
from .db_refusal import note_target_mismatch
from .errors import WebTextError
from .origin import refuse_foreign_origin
from .texts import t

logger = logging.getLogger(__name__)

#: Раздел меню, на пункте которого горит точка, — по виду события. Вид без записи
#: точки на пункте не даёт (колокольчик горит всё равно).
SECTION_OF_KIND: dict[str, str] = {
    "rx_requested": "osb",
    "rx_returned": "actions",
    "rx_approved": "actions",
    "rx_issued": "actions",
    "plan_requested": "actions",
    "plan_submitted": "actions",
    "plan_accepted": "actions",
    "plan_returned": "actions",
    "plan_row_done": "actions",
    "plan_row_confirmed": "actions",
    "plan_row_returned": "actions",
}

#: Ключ текста вида, которого словарь не знает.
UNKNOWN_KIND_KEY = "notif.unknown"

_STATE_KEY = "decimus_notifications_state"
_BASE = "/settings/notifications"


@dataclass(frozen=True)
class State:
    """Что рисует оболочка страницы: горит ли колокольчик и на каких разделах точки."""

    unread: bool = False
    sections: frozenset[str] = frozenset()


def text_key(kind: str) -> str:
    """Ключ текста вида: `notif.<вид>`; незнакомый вид — общая строка."""
    return f"notif.{kind}" if kind in SECTION_OF_KIND else UNKNOWN_KIND_KEY


def text_of(row: store.Notification, lang: str) -> str:
    """Фраза уведомления на языке человека; не сошлись параметры — общая строка, не отказ списка."""
    try:
        return t(text_key(row.kind), lang, **{k: str(v) for k, v in row.params.items()})
    except WebTextError:
        logger.warning("уведомление %s: текст вида %s не собрался", row.id, row.kind)
        return t(UNKNOWN_KIND_KEY, lang)


def link_matches_page(link: str, path: str, args: dict[str, list[str]]) -> bool:
    """Адрес уведомления — это текущая страница: тот же путь и все его параметры в адресе страницы.

    Лишние параметры страницы (язык, отбор) не мешают: `/osb?id=X&lang=en` — та же
    страница, что `/osb?id=X`. Страница без параметра уведомления — другая.
    """
    parts = urlsplit(link)
    if parts.path != path:
        return False
    return all(value in args.get(key, []) for key, value in parse_qsl(parts.query))


def _page_args() -> dict[str, list[str]]:
    return {key: request.args.getlist(key) for key in request.args}


def _compute(user: str) -> State:
    """Непрочитанное учётки; открытая страница, чей адрес совпал, отмечает свои строки."""
    if not store.unread_count(user):
        return State()
    rows = store.list_for(user, unread_only=True)
    if request.method == "GET":
        args = _page_args()
        here = {row.link for row in rows if link_matches_page(row.link, request.path, args)}
        for link in sorted(here):
            store.mark_read_by_link(user, link)
        rows = [row for row in rows if row.link not in here]
    # Список упёрся в предел и после отметки полон — значит, непрочитанное есть наверняка.
    sections = frozenset(
        section for section in (SECTION_OF_KIND.get(row.kind) for row in rows) if section
    )
    return State(unread=bool(rows), sections=sections)


def state() -> State:
    """Состояние колокольчика для этой страницы — один раз на запрос, отказ базы — без точек."""
    cached: State | None = getattr(g, _STATE_KEY, None)
    if cached is not None:
        return cached
    account = auth.current_account()
    result = State()
    if account is not None:
        try:
            result = _compute(str(account.id))
        except DbError as exc:
            note_target_mismatch(exc)
            logger.warning("уведомления: не прочитались (%s)", type(exc).__name__)
    setattr(g, _STATE_KEY, result)
    return result


def _own_id() -> str:
    вошедший = auth.current_account()
    if вошедший is None:
        raise RuntimeError("уведомления без вошедшего: маршрут прошёл мимо заслона")
    return str(вошедший.id)


def install(app: Flask, conf: Settings) -> None:
    """Состояние для шаблонов и три двери: список, «прочитано», «прочитать всё»."""

    @app.context_processor
    def _notifications() -> dict[str, object]:
        # Функцией, а не значением: фрагменты и страницы без оболочки базу не трогают.
        return {
            "notif_state": state,
            "notif_text": lambda row: text_of(row, ui_lang.request_lang(conf.ui_lang)),
        }

    @app.get(_BASE, endpoint="notifications_menu")
    def notifications_menu() -> FlaskResponse:
        """Список своих уведомлений фрагментом для всплывающего окна колокольчика."""
        try:
            rows = store.list_for(_own_id())
            failed = False
        except DbError as exc:
            note_target_mismatch(exc)
            rows, failed = [], True
        ответ = make_response(render_template("_notifications_menu.html", rows=rows, failed=failed))
        ответ.headers["Cache-Control"] = "no-store"
        return ответ

    @app.post(f"{_BASE}/<int:notification_id>/read", endpoint="notifications_read")
    def notifications_read(notification_id: int) -> Response:
        """Отметить прочитанным своё уведомление. Чужое и несуществующее — тот же пустой ответ."""
        refuse_foreign_origin()
        try:
            store.mark_read(_own_id(), notification_id)
        except DbError as exc:
            note_target_mismatch(exc)
            return make_response("", 503)
        return make_response("", 204)

    @app.post(f"{_BASE}/read-all", endpoint="notifications_read_all")
    def notifications_read_all() -> Response:
        """Отметить прочитанными все свои."""
        refuse_foreign_origin()
        try:
            store.mark_all_read(_own_id())
        except DbError as exc:
            note_target_mismatch(exc)
            return make_response("", 503)
        return make_response("", 204)
