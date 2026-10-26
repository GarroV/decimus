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
from urllib.parse import urlencode

from flask import Flask, abort, request
from flask import Response as FlaskResponse

from src.domain.tenants import may_manage_ratings

from . import access_policy, auth
from .config import Settings
from .sections import section
from .users_view import (
    TAB_CONNECTIONS,
    TAB_COUNTRIES,
    TAB_DODOIS,
    TAB_JOURNAL,
    TAB_KEYS,
    TAB_PEOPLE,
    TAB_RATINGS,
    TAB_SPACES,
    TAB_USAGE,
)

#: Группы вкладок: подзаголовок в столбце, если в группе у роли видно больше одной вкладки.


def _scope(account: object) -> access_policy.Scope | None:
    return access_policy.scope_of(getattr(account, "role", None), getattr(account, "tenant", None))


def _is_super(account: object) -> bool:
    охват = _scope(account)
    return охват is not None and охват.kind == access_policy.SUPER


def _sees_people(account: object) -> bool:
    """Главный, админ УК, админ партнёра, контроль — те, у кого есть охват людей."""
    return _scope(account) is not None


def manages_spaces(account: object) -> bool:
    """Ведёт ли человек все пространства партнёров (а не только своё)."""
    охват = _scope(account)
    return охват is not None and access_policy.manages_spaces(охват)


def _sees_spaces(account: object) -> bool:
    охват = _scope(account)
    return охват is not None and (
        access_policy.manages_spaces(охват) or охват.kind == access_policy.PARTNER_ADMIN
    )


def _sees_countries(account: object) -> bool:
    """Главный, админ УК и ОСБ — те, у кого есть `space.manage` или `contract.manage` (D640)."""
    from . import countries_screen  # countries_screen сам берёт адреса отсюда

    return countries_screen.may_see(
        getattr(account, "role", None), getattr(account, "tenant", None)
    )


def _sees_usage(account: object) -> bool:
    from . import usage_screen  # usage_screen сам берёт адреса отсюда

    return usage_screen.may_see(getattr(account, "role", None), getattr(account, "tenant", None))


def _sees_ratings(account: object) -> bool:
    """Те, кто ведёт рейтинги (`ratings.manage`): главный, админ УК, контроль (D319)."""
    return may_manage_ratings(
        str(getattr(account, "role", "") or ""), str(getattr(account, "tenant", "") or "")
    )


@dataclass(frozen=True)
class Tab:
    """Вкладка раздела: код (он же `?tab=`) и кому открыта."""

    key: str
    open_to: Callable[[object], bool]

    @property
    def title_key(self) -> str:
        return f"administration.tab.{self.key}"

    def title_key_for(self, account: object | None) -> str:
        """Подпись для этого человека: админ партнёра видит «Ваше пространство»."""
        if self.key == TAB_SPACES and account is not None and not manages_spaces(account):
            return "administration.tab.spaces_own"
        return self.title_key


#: Вкладки в порядке показа. Следом встают «Рейтинги».
TABS: tuple[Tab, ...] = (
    Tab(TAB_PEOPLE, _sees_people),
    Tab(TAB_SPACES, _sees_spaces),
    Tab(TAB_COUNTRIES, _sees_countries),
    # Настройки рейтингов: те же роли, что вели «Загрузки» (D654).
    Tab(TAB_RATINGS, _sees_ratings),
    Tab(TAB_JOURNAL, _is_super),
    Tab(TAB_USAGE, _sees_usage),
    # Состояние подключений — главный админ (D638).
    Tab(TAB_CONNECTIONS, _is_super),
    # Ключи сервисов и ключи `/api/v1` — отдельная вкладка после «Подключений»; права те же.
    Tab(TAB_KEYS, _is_super),
    # Входы Dodo IS по странам — отдельная вкладка рядом с «Подключениями» (D641); права те же.
    Tab(TAB_DODOIS, _is_super),
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
    query = urlencode(params)
    return f"{request.script_root}{section('administration').path}?{query}"


def nav(current: str) -> dict[str, object]:
    """Что нужно шаблону для столбца вкладок."""
    account = auth.current_account()
    tabs = tabs_for(account)
    now = next((tab for tab in tabs if tab.key == current), None)
    return {
        "admin_heading": now.title_key_for(account) if now else f"administration.tab.{current}",
        "admin_tabs": tabs,
        "admin_tab": current,
        "admin_url": url,
        "admin_title": lambda tab: tab.title_key_for(account),
    }


def install(app: Flask, conf: Settings) -> None:
    """Страница раздела. Вкладки ставят свои маршруты действий сами."""
    from . import (
        connections_screen,
        countries_screen,
        dodois_screen,
        journal_screen,
        ratings,
        usage_screen,
        users_page,
    )

    def people() -> FlaskResponse | tuple[str, int]:
        return users_page.render(users_page.Show(tab=TAB_PEOPLE))

    def spaces() -> FlaskResponse | tuple[str, int]:
        return users_page.render(users_page.Show(tab=TAB_SPACES))

    shows: dict[str, Callable[[], FlaskResponse | tuple[str, int]]] = {
        TAB_PEOPLE: people,
        TAB_SPACES: spaces,
        TAB_COUNTRIES: lambda: countries_screen.show(conf.ui_lang),
        TAB_RATINGS: lambda: ratings.show_admin(conf),
        TAB_JOURNAL: lambda: journal_screen.show_users(conf),
        TAB_USAGE: lambda: usage_screen.show(conf),
        TAB_CONNECTIONS: connections_screen.show,
        TAB_KEYS: connections_screen.show_keys,
        TAB_DODOIS: dodois_screen.show,
    }

    @app.get(section("administration").path)
    def administration() -> FlaskResponse | tuple[str, int]:
        tabs = tabs_for(auth.current_account())
        if not tabs:
            abort(404)
        key = request.args.get("tab") or tabs[0].key
        if key not in {tab.key for tab in tabs}:
            abort(404)
        return shows[key]()
