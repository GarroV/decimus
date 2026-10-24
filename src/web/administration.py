"""Раздел «Администрирование» (D639, #1251): все настройки сервиса, вкладки по роли.

Слева столбец вкладок, справа содержимое выбранной. Вкладка видна только тем, кому
открыто её содержимое; роли без единой вкладки нет и пункта меню — вид
`view.administration` выдаётся ровно этим ролям (сверяет `tests/test_web_administration.py`).
Права не меняются: вкладка открывает то же, что открывал прежний экран, только в одном
месте. Методика (`/admin`) — своим пунктом меню, сюда не входит.

Выбранная вкладка — в адресе (`?tab=<код>`), вкладки — обычные ссылки.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from flask import Flask, abort, request
from flask import Response as FlaskResponse

from . import access_policy, auth
from .sections import section

TAB_CONNECTIONS = "connections"


def _is_super(account: object) -> bool:
    охват = access_policy.scope_of(getattr(account, "role", None), getattr(account, "tenant", None))
    return охват is not None and охват.kind == access_policy.SUPER


@dataclass(frozen=True)
class Tab:
    """Вкладка раздела: код (он же `?tab=`), кому открыта."""

    key: str
    open_to: Callable[[object], bool]

    @property
    def title_key(self) -> str:
        return f"administration.tab.{self.key}"


#: Вкладки в порядке показа. Шаги #1251 добавляют сюда «Люди и доступ», «Страны»,
#: «Рейтинги», «Журнал».
TABS: tuple[Tab, ...] = (
    # Ключи сервисов, ключи `/api/v1` и состояние подключений — главный админ (D638).
    Tab(TAB_CONNECTIONS, _is_super),
)


def tabs_for(account: object | None) -> tuple[Tab, ...]:
    """Вкладки, открытые этому человеку."""
    if account is None:
        return ()
    return tuple(tab for tab in TABS if tab.open_to(account))


def url(tab: str, **extra: str) -> str:
    """Адрес вкладки с подстановками; язык — из текущего адреса."""
    params = {"tab": tab, **{k: v for k, v in extra.items() if v}}
    lang = request.args.get("lang") or ""
    if lang:
        params["lang"] = lang
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{request.script_root}{section('administration').path}?{query}"


def nav(current: str) -> dict[str, object]:
    """Что нужно шаблону для столбца вкладок."""
    return {
        "admin_tabs": tabs_for(auth.current_account()),
        "admin_tab": current,
        "admin_url": url,
    }


def install(app: Flask) -> None:
    """Страница раздела. Вкладки ставят свои маршруты действий сами."""
    from . import connections_screen

    shows: dict[str, Callable[[], FlaskResponse]] = {TAB_CONNECTIONS: connections_screen.show}

    @app.get(section("administration").path)
    def administration() -> FlaskResponse:
        tabs = tabs_for(auth.current_account())
        if not tabs:
            abort(404)
        key = request.args.get("tab") or tabs[0].key
        if key not in {tab.key for tab in tabs}:
            abort(404)
        return shows[key]()
