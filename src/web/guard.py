"""Заслон прав веба (спека «Администрирование»): каждый пишущий маршрут — через `can`.

Маршрут объявляет код действия декоратором `action`. Маршрут своего
пространства проверяется целиком до входа (`before_request`). Маршрут, чей
объект может лежать в чужом пространстве или принадлежать другому автору
(`object_in_route=True`), сам зовёт `permit(код, пространство_объекта,
object_author=...)` — пространство и автор берутся из объекта, а не из формы.
Забыл позвать — пишущий запрос падает 500 (`after_request`): запись без границы
громче, чем тихая.

Учётка без `id` не действует вовсе: журнал действий УК в чужом пространстве
(`src/db/cross_space.py`) требует, кто действовал, и без него дошёл бы до 500.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Any, TypeVar

from flask import Flask, current_app, g, render_template, request
from werkzeug.wrappers import Response

from src.domain.permissions import (
    AUTHOR_NOT_GIVEN,
    INSPECTION_OBJECT_ACTIONS,
    AuthorNotGiven,
    can,
    require_action,
)

from . import auth

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

ACTIONS_ATTR = "required_actions"
OBJECT_IN_ROUTE_ATTR = "object_in_route"
WRITING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

#: GET, который пишет: возврат от Google кладёт письмо и отправляет предписание.
WRITING_GETS = frozenset({"google_mail_callback"})

#: Пишущие маршруты без кода каталога — со своей причиной.
EXEMPT_ENDPOINTS: Mapping[str, str] = {
    "logout": "выход закрывает свою сессию",
    "own_password": "свой пароль — у себя, без доступа к остальному (спека)",
    "bot_link": "ссылка привязки — всегда своей учётке (D286)",
}

_PERMITTED = "action_permitted"


def action(*codes: str, object_in_route: bool = False) -> Callable[[F], F]:
    """Объявить код действия маршрута. Ошибка объявления — при сборке приложения."""
    if not codes:
        raise ValueError("Маршрут без кода действия: заслону нечего спрашивать")
    for код in codes:
        require_action(код)
    if not object_in_route and (len(codes) > 1 or codes[0] in INSPECTION_OBJECT_ACTIONS):
        raise ValueError(
            "Несколько кодов или действие над проверкой — объект решает маршрут: "
            "object_in_route=True"
        )

    def mark(view: F) -> F:
        setattr(view, ACTIONS_ATTR, codes)
        setattr(view, OBJECT_IN_ROUTE_ATTR, object_in_route)
        return view

    return mark


def _view() -> Any:
    return current_app.view_functions.get(request.endpoint or "")


def forbidden() -> tuple[str, int]:
    """Страница отказа 403 — одна на весь заслон прав."""
    return render_template("users/forbidden.html"), 403


def permit(
    code: str,
    object_tenant: str,
    *,
    object_author: str | AuthorNotGiven | None = AUTHOR_NOT_GIVEN,
) -> tuple[str, int] | None:
    """Спросить `can` о вошедшем. `None` — можно; иначе страница отказа 403."""
    объявлено = getattr(_view(), ACTIONS_ATTR, ())
    if code not in объявлено:
        raise RuntimeError(f"Маршрут {request.endpoint} спрашивает «{code}», а объявил {объявлено}")
    субъект = auth.current_actor()
    setattr(g, _PERMITTED, True)
    if not субъект.user_id:
        logger.warning("права: отказ %s %s — у учётки нет id", request.endpoint, code)
        return forbidden()
    решение = can(субъект, code, object_tenant, object_author=object_author)
    if решение.allowed:
        return None
    logger.info(
        "права: отказ %s %s над %s (%s)", request.endpoint, code, object_tenant, решение.rule
    )
    return forbidden()


def mark_own() -> None:
    """Маршрут с объектом действует над своим (своя привязка): граница не нужна."""
    setattr(g, _PERMITTED, True)


def install(app: Flask) -> None:
    """Повесить заслон. Ставится ПОСЛЕ заслона входа: без вошедшего сюда не доходят."""

    @app.before_request
    def _права() -> tuple[str, int] | None:
        if request.endpoint in auth.OPEN_ENDPOINTS or auth.current_account() is None:
            return None
        view = app.view_functions.get(request.endpoint or "")
        коды = getattr(view, ACTIONS_ATTR, ())
        if not коды or getattr(view, OBJECT_IN_ROUTE_ATTR, False):
            return None
        return permit(коды[0], auth.current_tenant())

    @app.after_request
    def _спросил_ли(response: Response) -> Response:
        view = app.view_functions.get(request.endpoint or "")
        if request.method not in WRITING_METHODS:
            return response
        if not getattr(view, OBJECT_IN_ROUTE_ATTR, False):
            return response
        if response.status_code >= 400 or getattr(g, _PERMITTED, False):
            return response
        raise RuntimeError(
            f"Маршрут {request.endpoint} объявил объект и не спросил can: запись прошла без границы"
        )


def uncovered(app: Flask) -> list[str]:
    """Пишущие маршруты без кода каталога и без причины-исключения — `эндпоинт (путь)`."""
    непокрытые: list[str] = []
    for rule in app.url_map.iter_rules():
        if rule.endpoint in auth.OPEN_ENDPOINTS or rule.endpoint in EXEMPT_ENDPOINTS:
            continue
        пишет = bool((rule.methods or set()) & WRITING_METHODS) or rule.endpoint in WRITING_GETS
        if not пишет:
            continue
        if not getattr(app.view_functions[rule.endpoint], ACTIONS_ATTR, ()):
            непокрытые.append(f"{rule.endpoint} ({rule.rule})")
    return sorted(непокрытые)
