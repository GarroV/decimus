"""Заслон прав веба: каждый маршрут спрашивает матрицу (`src/domain/permissions.py`).

**Запись.** Пишущий маршрут объявляет код действия декоратором `action`. Маршрут
своего пространства проверяется целиком до входа (`before_request`). Маршрут,
чей объект может лежать в чужом пространстве (`object_in_route=True`), сам зовёт
`permit(код, пространство_объекта)` — пространство берётся из объекта (строки
базы), а не из формы. Забыл позвать — пишущий запрос падает 500
(`after_request`): запись без границы громче, чем тихая. Пишущий маршрут без
кода и без причины в `EXEMPT_ENDPOINTS` — 403 (запрет по умолчанию), а тест
`tests/test_web_guard.py` называет его по имени.

**Чтение.** Раздел веба (`sections.py`) открыт, если у роли есть `view.<раздел>`;
закрытый — 404, как несуществующий адрес. Адреса вне разделов, которые читают
данные сети, перечислены в `ENDPOINT_VIEWS`.

**Граница пространств — тоже из матрицы, и по умолчанию закрыто** (аудит 12.10,
F-004). Партнёрское пространство пускается к маршруту, только если хоть один код,
которым маршрут объявлен в матрице (действие, `view.<раздел>` по пути,
`ENDPOINT_VIEWS`), этому пространству открыт (`open_to_space`), либо маршрут — дело
самого человека (`EXEMPT_ENDPOINTS`, свой раздел), переадресация (`NAVIGATION_ENDPOINTS`) или
своя дверь (`auth.OPEN_ENDPOINTS`). Маршрут без объявления партнёру закрыт (404 в
`app._install_hq_gate`), а `undeclared` называет его по имени. Второго реестра
«кому открыт маршрут» нет: аудитория выводится из тех же объявлений.

Этот заслон заменил заслоны контроля, гостя и методики: один вопрос — одна
матрица.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Any, TypeVar

from flask import Flask, abort, current_app, g, render_template, request
from werkzeug.wrappers import Response

from src.domain.permissions import Actor, can, grants_of, open_to_space, require_action

from . import auth
from .sections import OWN_SECTIONS, current_section, section_view

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

ACTIONS_ATTR = "required_actions"
OBJECT_IN_ROUTE_ATTR = "object_in_route"
HIDDEN_ATTR = "hidden_route"
WRITING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

#: GET, который пишет: возврат от Google кладёт черновик письма в почту.
WRITING_GETS = frozenset({"google_mail_callback"})

#: Пишущие маршруты без кода каталога — дела самого человека над своей учёткой.
#: Матрица их не решает: их делает любая роль, включая гостя (D440, D448).
EXEMPT_ENDPOINTS: Mapping[str, str] = {
    "logout": "выход закрывает свою сессию",
    "settings_own_password": "свой пароль — у себя, без доступа к остальному (D447)",
    "settings_claude_token": "личный токен Claude себе выпускает любая роль (D448)",
    "settings_claude_token_revoke": "свой токен Claude гасит сам (D448)",
    "settings_claude_revoke": "своё подключение Claude отзывает сам (D417)",
    "settings_lang": "язык сайта своей учётки (D447)",
    "settings_google_link": "свою почту Google привязывает сам (D447, D450)",
    "settings_google_unlink": "свою почту Google отвязывает сам (D447, D450)",
    "settings_continue": "своё отложенное до подтверждения входа действие; право бота — внутри",
    "reauth_confirm_password": "подтверждение своего входа паролем перед выдачей доступа",
    "reauth_confirm_google": "подтверждение своего входа через Google перед выдачей доступа",
    "oauth_authorize": "согласие на подключение своего Claude (D417)",
}

#: Адреса без данных, открытые любому вошедшему: только переадресация.
NAVIGATION_ENDPOINTS: Mapping[str, str] = {
    "home": "корень сайта переадресует на стартовый экран роли (D378, D420)",
}

#: Адреса вне разделов, которые читают данные сети: карточка пиццерии — история
#: проверок, то же, что «Проверки».
ENDPOINT_VIEWS: Mapping[str, str] = {"unit": "view.registry"}

_PERMITTED = "action_permitted"
_REACHED = "guard_reached_view"


def action(*codes: str, object_in_route: bool = False, hidden: bool = False) -> Callable[[F], F]:
    """Объявить код действия маршрута. Ошибка объявления — при сборке приложения.

    `hidden` — экрана для закрытой роли «нет вовсе»: отказ 404, а не 403
    (ключи API главного админа — остальным экрана снаружи не видно).
    """
    if not codes:
        raise ValueError("Маршрут без кода действия: заслону нечего спрашивать")
    for код in codes:
        require_action(код)
    if len(codes) > 1 and not object_in_route:
        raise ValueError("Несколько кодов — какой спросить, решает объект: object_in_route=True")

    def mark(view: F) -> F:
        setattr(view, ACTIONS_ATTR, codes)
        setattr(view, OBJECT_IN_ROUTE_ATTR, object_in_route)
        setattr(view, HIDDEN_ATTR, hidden)
        return view

    return mark


def current_actor() -> Actor:
    """Вошедший как субъект матрицы. Без вошедшего — ошибка кода."""
    вошедший = auth.current_account()
    if вошедший is None:
        raise RuntimeError("current_actor() вызван без вошедшего: маршрут прошёл мимо заслона")
    return Actor(tenant=вошедший.tenant, role=вошедший.role, user_id=вошедший.id)


def may(code: str, object_tenant: str | None = None) -> bool:
    """Может ли вошедший — для разметки и развилок маршрута, без отметки «спросил»."""
    return auth.current_account() is not None and can(current_actor(), code, object_tenant).allowed


def _view() -> Any:
    return current_app.view_functions.get(request.endpoint or "")


def forbidden() -> tuple[str, int]:
    """Страница отказа 403 — одна на весь заслон прав; у скрытого маршрута — 404."""
    if getattr(_view(), HIDDEN_ATTR, False):
        abort(404)
    return render_template("users/forbidden.html"), 403


def permit(code: str, object_tenant: str | None = None) -> tuple[str, int] | None:
    """Спросить матрицу о вошедшем. `None` — можно; иначе страница отказа 403."""
    объявлено = getattr(_view(), ACTIONS_ATTR, ())
    if code not in объявлено:
        raise RuntimeError(f"Маршрут {request.endpoint} спрашивает «{code}», а объявил {объявлено}")
    решение = can(current_actor(), code, object_tenant)
    if решение.allowed:
        setattr(g, _PERMITTED, True)
        return None
    logger.info(
        "права: отказ %s %s над %s (%s)", request.endpoint, code, object_tenant, решение.rule
    )
    return forbidden()


def _writes(endpoint: str | None, methods: set[str] | frozenset[str]) -> bool:
    return bool(set(methods) & WRITING_METHODS) or endpoint in WRITING_GETS


def _read_code(endpoint: str | None, path: str) -> str | None:
    ключ = current_section(path)
    if ключ is not None:
        return section_view(ключ)
    return ENDPOINT_VIEWS.get(endpoint or "")


def install(app: Flask) -> None:
    """Повесить заслон. Ставится ПОСЛЕ заслона входа: без вошедшего сюда не доходят."""

    @app.before_request
    def _права() -> tuple[str, int] | None:
        if request.endpoint in auth.OPEN_ENDPOINTS or request.routing_exception is not None:
            return None
        вошедший = auth.current_account()
        if вошедший is None:
            return None
        setattr(g, _REACHED, True)
        if not _writes(request.endpoint, {request.method}):
            код = _read_code(request.endpoint, request.path)
            if код is not None and not can(current_actor(), код).allowed:
                abort(404)
            return None
        if request.endpoint in EXEMPT_ENDPOINTS:
            return None
        view = app.view_functions.get(request.endpoint or "")
        коды = getattr(view, ACTIONS_ATTR, ())
        if not коды:
            logger.error("права: пишущий маршрут %s без кода действия — отказ", request.endpoint)
            return forbidden()
        if getattr(view, OBJECT_IN_ROUTE_ATTR, False):
            # Объект решает маршрут, но роли без единой из объявленных клеток
            # до объекта (и до базы) дела нет: отказ сразу.
            if not any(код in grants_of(вошедший.role, вошедший.tenant) for код in коды):
                return forbidden()
            return None
        return permit(коды[0])

    @app.after_request
    def _спросил_ли(response: Response) -> Response:
        view = app.view_functions.get(request.endpoint or "")
        if not _writes(request.endpoint, {request.method}):
            return response
        if not getattr(view, OBJECT_IN_ROUTE_ATTR, False):
            return response
        # Ответ заслона входа или другого заслона до маршрута — не запись: без
        # вошедшего или мимо нашего `before_request` маршрут не исполнялся.
        if not getattr(g, _REACHED, False) or auth.current_account() is None:
            return response
        if response.status_code >= 400 or getattr(g, _PERMITTED, False):
            return response
        raise RuntimeError(
            f"Маршрут {request.endpoint} объявил объект и не спросил матрицу: "
            "запись прошла без границы"
        )


def uncovered(app: Flask) -> list[str]:
    """Пишущие маршруты без кода каталога и без причины-исключения — `эндпоинт (путь)`."""
    непокрытые: list[str] = []
    for rule in app.url_map.iter_rules():
        if rule.endpoint in auth.OPEN_ENDPOINTS or rule.endpoint in EXEMPT_ENDPOINTS:
            continue
        if not _writes(rule.endpoint, frozenset(rule.methods or ())):
            continue
        if not getattr(app.view_functions[rule.endpoint], ACTIONS_ATTR, ()):
            непокрытые.append(f"{rule.endpoint} ({rule.rule})")
    return sorted(непокрытые)


def _open_to_all(endpoint: str | None, path: str) -> bool:
    """Своя дверь, дело человека над своей учёткой, переадресация — любому пространству."""
    if endpoint in auth.OPEN_ENDPOINTS or endpoint in EXEMPT_ENDPOINTS:
        return True
    if endpoint in NAVIGATION_ENDPOINTS:
        return True
    return current_section(path) in OWN_SECTIONS


def _declared_codes(app: Flask, endpoint: str | None, path: str) -> frozenset[str]:
    """Коды матрицы, которыми объявлен маршрут: действия, чтение раздела, `ENDPOINT_VIEWS`."""
    view = app.view_functions.get(endpoint or "")
    коды = set(getattr(view, ACTIONS_ATTR, ()))
    ключ = current_section(path)
    if ключ is not None and (код := section_view(ключ)) is not None:
        коды.add(код)
    if (код := ENDPOINT_VIEWS.get(endpoint or "")) is not None:
        коды.add(код)
    return frozenset(коды)


def open_to_tenant(app: Flask, endpoint: str | None, path: str, tenant: str) -> bool:
    """Пускать ли пространство `tenant` к маршруту — по объявлениям матрицы.

    Без объявления — закрыто (аудит 12.10, F-004). Открыто — значит лишь «сюда
    ходят»: что именно человек увидит и изменит, решают роль (`can`) и охват.
    """
    if _open_to_all(endpoint, path):
        return True
    return any(open_to_space(код, tenant) for код in _declared_codes(app, endpoint, path))


def undeclared(app: Flask) -> list[str]:
    """Маршруты, которые матрица не объявила ничем, — `эндпоинт (путь)`; партнёру они закрыты."""
    return sorted(
        f"{rule.endpoint} ({rule.rule})"
        for rule in app.url_map.iter_rules()
        if not _open_to_all(rule.endpoint, rule.rule)
        and not _declared_codes(app, rule.endpoint, rule.rule)
    )
