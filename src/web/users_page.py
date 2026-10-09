"""Сборка страницы «Пользователи»: список слева, карточка выбранного справа.

Маршруты (`users_screen.py`) решают, что сделать; здесь — что показать после.
Решений о правах здесь нет: перечень приходит уже суженным правилом
`access_policy.py`, а что вошедший может сделать с человеком в карточке,
спрашивается у того же правила (`role_choices`) — кнопка, которой нет в
правиле, не рисуется.

Карточка бывает четырёх видов: своя (`me` — логин, роль, пароль, бот), чужая
(человек из перечня), форма «Добавить человека» и пустая подсказка. Своя
открыта каждому вошедшему, даже тому, кто людьми не управляет: там его бот и
пароль (D286, #324).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from flask import current_app, render_template, request

from src.db import bot_links
from src.db.errors import DbError
from src.domain.tenants import HQ_TENANT, canonical_tenant

from . import access_policy, accounts, auth, partner_spaces, people, profile, users_mcp
from .access_policy import Scope
from .config import WEB_BOT_USERNAME_VAR
from .db_refusal import note_target_mismatch
from .sections import section
from .users_view import (
    TAB_PEOPLE,
    TAB_SPACES,
    Filters,
    apply_filters,
    read_filters,
    role_options,
    screen_url,
    selected,
)

#: Охваты, которым видны привязки бота чужих людей и их отвязка.
SEES_BINDINGS = frozenset({access_policy.SUPER, access_policy.HQ_ADMIN})

#: Ключ своей карточки в адресе: `?person=me`.
ME = "me"

#: Где приложение держит имя бота для ссылки привязки (`WEB_BOT_USERNAME`).
BOT_USERNAME_KEY = "DECIMUS_BOT_USERNAME"


@dataclass(frozen=True)
class Flash:
    """Исход действия: ключ текста, тон и параметры подстановки."""

    key: str
    ok: bool
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Show:
    """Что открыть после действия: поверх того, что просит адрес."""

    person: str | None = None
    add: bool = False
    tab: str | None = None
    space: str | None = None
    flash: Flash | None = None
    added: accounts.Added | None = None
    added_email_failed: bool = False
    password: profile.Outcome | None = None
    bot_link: str | None = None
    bot_link_until: datetime | None = None
    add_space: bool = False
    #: Показать отключённых: после отключения человек не пропадает из виду.
    show_off: bool = False


def people_scope() -> Scope | None:
    """Охват вошедшего на экране людей; `None` — людьми не управляет, видит себя."""
    вошедший = auth.current_account()
    if вошедший is None:
        return None
    return access_policy.scope_of(вошедший.role, вошедший.tenant)


def source(scope: Scope) -> tuple[accounts.AccountRow, ...]:
    """Перечень из базы — уже суженный запросом, где охват это позволяет."""
    if scope.kind in (access_policy.PARTNER_ADMIN, access_policy.CONTROL):
        return accounts.everyone(tenant=scope.tenant)
    return accounts.everyone(tenant=None)


def _people(круг: Scope | None) -> tuple[tuple[accounts.AccountRow, ...], bool]:
    """Видимые люди и признак «перечень известен». Отказ базы — не «никого нет»."""
    if круг is None:
        return (), True
    try:
        return access_policy.visible(круг, source(круг)), True
    except DbError as exc:
        note_target_mismatch(exc)
        return (), False


def _bindings(круг: Scope | None, люди: tuple[accounts.AccountRow, ...]) -> dict[str, Any]:
    if круг is None or круг.kind not in SEES_BINDINGS:
        return {}
    свои = {r.id for r in люди}
    try:
        return {k: v for k, v in bot_links.live_bindings().items() if k in свои}
    except DbError as exc:
        note_target_mismatch(exc)
        return {}


def _spaces(круг: Scope | None) -> tuple[tuple[Any, ...], bool, bool]:
    """Пространства партнёров для вкладки: (строки, известны ли, есть ли вкладка)."""
    if круг is None:
        return (), True, False
    ведёт = access_policy.manages_spaces(круг)
    if not ведёт and круг.kind != access_policy.PARTNER_ADMIN:
        return (), True, False
    try:
        строки = tuple(
            s
            for s in partner_spaces.overview()
            if s.code != HQ_TENANT and (ведёт or s.code == круг.tenant)
        )
    except DbError as exc:
        note_target_mismatch(exc)
        return (), False, True
    return строки, True, True


def role_choices(круг: Scope | None, строка: Any) -> tuple[str, ...]:
    """Роли для смены у человека; пусто — роль показывается текстом."""
    вошедший = auth.current_account()
    if (
        круг is None
        or круг.kind == access_policy.CONTROL
        or строка.disabled_at is not None
        or вошедший is None
        or people.is_self(
            login=строка.login,
            tenant=строка.tenant,
            actor_login=вошедший.login,
            actor_tenant=вошедший.tenant,
        )
    ):
        return ()
    return access_policy.grantable_roles(круг, строка.tenant)


def _own_binding() -> tuple[Any, bool]:
    вошедший = auth.current_account()
    if вошедший is None:
        return None, True
    try:
        return bot_links.binding_of(вошедший.id), True
    except DbError:
        return None, False


def _pick(
    show: Show, люди: tuple[Any, ...], список: tuple[Any, ...], manage: bool
) -> tuple[str, Any, bool]:
    """Что в панели справа: (вид, строка, выбрано ли явно).

    Явный выбор — из адреса или после действия; только он открывает панель.
    Без него вид — первый человек списка, но панель закрыта.
    """
    вошедший = auth.current_account()
    if show.add or (request.args.get("add") == "1" and manage):
        return "add", None, True
    ключ = show.person or (request.args.get("person") or "").strip()
    if not manage or ключ == ME or (вошедший is not None and ключ == вошедший.id):
        своя = selected(люди, вошедший.id) if вошедший else None
        return "me", своя, bool(ключ) or not manage
    строка = selected(люди, ключ)
    if строка is not None:
        return "person", строка, True
    if список:
        первый = список[0]
        вид = "me" if вошедший is not None and первый.id == вошедший.id else "person"
        return вид, первый, False
    return "none", None, False


def render(show: Show | None = None, code: int = 200) -> tuple[str, int]:
    """Страница целиком — для GET и для ответа на любую отправку экрана."""
    show = show or Show()
    круг = people_scope()
    f = read_filters(request.args)
    if show.show_off:
        f = replace(f, off=True)
    люди, известны = _people(круг)
    список = apply_filters(люди, f)
    manage = круг is not None
    пространства, пр_известны, есть_вкладка = _spaces(круг)
    вкладка = show.tab or request.args.get("tab") or TAB_PEOPLE
    if вкладка != TAB_SPACES or not есть_вкладка:
        вкладка = TAB_PEOPLE
    вид, строка, явно = _pick(show, люди, список, manage)
    своя_привязка, своя_известна = _own_binding()
    привязки = _bindings(круг, люди)
    адрес = f"{request.script_root}{section('users').path}"
    язык = request.args.get("lang") or ""

    def link(**extra: str) -> str:
        return screen_url(адрес, lang=язык, f=f, **extra)

    выбрано_пространство = bool(
        show.space
        or show.add_space
        or request.args.get("space_code")
        or request.args.get("add_space")
    )
    return (
        render_template(
            "users/index.html",
            **_people_context(круг, люди, список, f, известны, привязки),
            **_space_context(круг, show, пространства, пр_известны, есть_вкладка, вкладка),
            card=вид,
            card_row=строка,
            role_choices=lambda r: role_choices(круг, r),
            add_spaces=access_policy.spaces_for_add(круг, _all_spaces()) if круг else (),
            grantable=lambda s: access_policy.grantable_roles(круг, s) if круг else (),
            own_binding=своя_привязка,
            own_binding_known=своя_известна,
            mcp=users_mcp.card_status(
                круг_видит=круг is not None and круг.kind in SEES_BINDINGS,
                own=своя_привязка,
                bindings=привязки,
            ),
            show=show,
            me=auth.current_account(),
            manage=manage,
            link=link,
            link_reset=screen_url(адрес, lang=язык, f=Filters()),
            users_url=адрес,
            # Панель справа — только по явному выбору; без права вести людей
            # своя карточка стоит на странице, а не в панели (закрывать некуда).
            split_open=выбрано_пространство if вкладка == TAB_SPACES else явно and manage,
            split_back=link(tab=вкладка if вкладка == TAB_SPACES else ""),
            bot_username=current_app.config.get(BOT_USERNAME_KEY),
            bot_var=WEB_BOT_USERNAME_VAR,
            min_password=accounts.MIN_PASSWORD_LENGTH,
            max_password=accounts.MAX_PASSWORD_LENGTH,
        ),
        code,
    )


def _people_context(
    круг: Scope | None,
    люди: tuple[accounts.AccountRow, ...],
    список: tuple[accounts.AccountRow, ...],
    f: Filters,
    известны: bool,
    привязки: dict[str, Any],
) -> dict[str, Any]:
    return {
        "scope_kind": None if круг is None else круг.kind,
        "show_bindings": круг is not None and круг.kind in SEES_BINDINGS,
        "filters": f,
        "people": список,
        "people_total": sum(1 for r in люди if r.disabled_at is None),
        "people_off": sum(1 for r in люди if r.disabled_at is not None),
        "people_known": известны,
        "role_filter": role_options(люди),
        "space_filter": sorted({canonical_tenant(r.tenant) for r in люди}),
        "bindings": привязки,
    }


def _space_context(
    круг: Scope | None,
    show: Show,
    пространства: tuple[Any, ...],
    известны: bool,
    есть_вкладка: bool,
    вкладка: str,
) -> dict[str, Any]:
    return {
        "tab": вкладка,
        "has_spaces_tab": есть_вкладка,
        "partner_spaces": пространства,
        "partner_spaces_known": известны,
        "manages_spaces": круг is not None and access_policy.manages_spaces(круг),
        "space_pick": _space_pick(show, пространства),
        "space_add": вкладка == TAB_SPACES
        and (show.add_space or request.args.get("add_space") == "1"),
    }


def _all_spaces() -> tuple[str, ...]:
    try:
        return accounts.spaces()
    except DbError as exc:
        note_target_mismatch(exc)
        return ()


def _space_pick(show: Show, пространства: tuple[Any, ...]) -> Any:
    ключ = show.space or (request.args.get("space_code") or "").strip()
    найдено = next((s for s in пространства if s.code == ключ), None)
    if найдено is not None:
        return найдено
    return пространства[0] if пространства else None
