"""Экран «Пользователи» (`/users`): один экран доступа для всех, охват по роли (#585).

Вынесен из `app.py` вместе с расширением D362/D364: главный админ, админ УК,
контроль и админ партнёра ведут людей на одном экране, каждый — в своём
охвате. Кто кого видит и трогает — правило `access_policy.py`; здесь —
маршруты, которые его сверяют на КАЖДОЙ отправке, и страница.

Заслон стоит на маршруте, а не в разметке: адрес известен, и POST набирается
руками. Цель правки сверяется с базой (перечень учёток), а не с формой:
поддельное пространство, роль или логин вне охвата — 403 до двери записи, а
сама дверь ещё раз держит охват условием на роль цели (`only_roles`).

Перечень фильтруется на сервере: чужой логин и чужая почта на страницу вне
охвата не попадают вовсе.

Людям ничего не отправляется: пароль новой учётки показывается один раз на
странице ответа, писем и уведомлений нет.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from flask import Flask, render_template, request
from flask import Response as FlaskResponse

from src.db import bot_links
from src.db.errors import DbError
from src.domain.log_ids import log_id
from src.domain.tenants import canonical_tenant

from . import (
    access_policy,
    accounts,
    auth,
    connections_screen,
    guard,
    partner_spaces,
    people,
)
from .access_policy import Scope
from .config import Settings
from .db_refusal import note_target_mismatch
from .origin import refuse_foreign_origin
from .sections import section
from .users_page import (
    ME,
    SEES_BINDINGS,
    Flash,
    Show,
    people_scope,
    render,
    source,
)
from .users_view import TAB_CONNECTIONS, TAB_SPACES

logger = logging.getLogger(__name__)


def forbidden() -> FlaskResponse:
    """Отказ 403 на экране людей."""
    return render_template("users/forbidden.html"), 403  # type: ignore[return-value]


def _target(scope: Scope, login: str, tenant: str) -> accounts.AccountRow | None:
    """Учётка из формы — если она есть в базе И в охвате; иначе `None` (отказ 403).

    «Нет такой» и «не ваша» снаружи неразличимы: оба — 403.
    """
    имя = login.strip().lower()
    где = canonical_tenant(tenant)
    for строка in access_policy.visible(scope, source(scope)):
        if строка.login.strip().lower() == имя and canonical_tenant(строка.tenant) == где:
            return строка
    return None


def _touchable_roles(scope: Scope, tenant: str) -> tuple[str, ...]:
    """Роли цели, которые охват может трогать в этом пространстве — для `only_roles`."""
    return access_policy.grantable_roles(scope, tenant)


def _flash(key: str, *, ok: bool, **params: object) -> Flash:
    return Flash(key, ok, dict(params))


def install(app: Flask, conf: Settings) -> None:
    """Маршруты экрана «Пользователи»: люди, своя карточка, пространства партнёров."""
    users_path = section("users").path

    @app.get(users_path)
    def users() -> FlaskResponse | tuple[str, int]:
        if request.args.get("tab") == TAB_CONNECTIONS:
            return connections_screen.show()
        return render()

    @app.post(f"{users_path}/bot-unlink")
    @guard.action("people.manage")
    def bot_unlink() -> FlaskResponse | tuple[str, int]:
        """Снять привязку бота ЧУЖОЙ учётки: главный админ и админ УК, только в своём охвате.

        Свою привязку человек снимает в «Настройках» (`settings_screen.py`, D447):
        здесь свой `user_id` — отказ, второй двери для того же дела нет.
        """
        refuse_foreign_origin()
        вошедший = auth.current_account()
        if вошедший is None:
            raise RuntimeError("отвязка бота без вошедшего: маршрут прошёл мимо заслона")
        чей = (request.form.get("user_id") or "").strip()
        круг = people_scope()
        if not чей or чей == вошедший.id or круг is None or круг.kind not in SEES_BINDINGS:
            return forbidden()
        try:
            if not any(r.id == чей for r in access_policy.visible(круг, source(круг))):
                return forbidden()
            отвязано = bot_links.unbind(чей)
        except DbError:
            return render(Show(person=чей, flash=_flash("users.bot.unlink_failed", ok=False)), 503)
        исход = "users.bot.unlinked" if отвязано else "users.bot.unlink_missing"
        return render(Show(person=чей, flash=_flash(исход, ok=отвязано)))

    _install_edits(app, users_path)
    _install_add_freeze(app, users_path)
    _install_spaces(app, users_path)
    connections_screen.install(app)


def _install_edits(app: Flask, users_path: str) -> None:
    """Смена роли и почты в карточке человека."""

    def _правка(
        действие: Callable[[str, str, tuple[str, ...]], people.Outcome],
        *,
        роль_меняется: bool = False,
    ) -> FlaskResponse | tuple[str, int]:
        """Общее у правки роли и почты: охват, происхождение, цель по базе.

        Смена роли — отдельная клетка матрицы (`people.role`): контролю её нет (D360).
        """
        круг = people_scope()
        if круг is None or (роль_меняется and not guard.may("people.role")):
            return forbidden()
        refuse_foreign_origin()
        логин = (request.form.get("login") or "").strip()
        пространство = canonical_tenant((request.form.get("tenant") or "").strip())
        if not логин or not пространство:
            return render(Show(flash=_flash("users.edit.space", ok=False)), 400)
        вошедший = auth.current_account()
        if (
            роль_меняется
            and вошедший is not None
            and people.is_self(
                login=логин,
                tenant=пространство,
                actor_login=вошедший.login,
                actor_tenant=вошедший.tenant,
            )
        ):
            # Свою роль не меняет никто: снять с себя админа — закрыть себе экран.
            return render(Show(person=ME, flash=_flash("users.role.self", ok=False)), 400)
        try:
            цель = _target(круг, логин, пространство)
        except DbError:
            return render(Show(flash=_flash("users.edit.failed", ok=False)), 503)
        if цель is None:
            return forbidden()
        исход = действие(цель.login, цель.tenant, _touchable_roles(круг, цель.tenant))
        удача = исход.status == 200 and исход.key != "edit.missing"
        return render(
            Show(person=цель.id, flash=_flash(f"users.{исход.key}", ok=удача)), исход.status
        )

    @app.post(f"{users_path}/role")
    @guard.action("people.role")
    def user_role() -> FlaskResponse | tuple[str, int]:
        """Назначить роль человеку в охвате; выдать можно только роль из охвата. Свою — нельзя."""
        вошедший = auth.current_account()
        роль = (request.form.get("role") or "").strip()
        круг = people_scope()

        def сменить(логин: str, пространство: str, охват: tuple[str, ...]) -> people.Outcome:
            # Незаведённая для пространства роль — 400 «нет такой роли» (её
            # отсекает `change_role`); заведённая, но вне охвата — 403.
            if (
                круг is not None
                and роль in accounts.roles_for(пространство)
                and not access_policy.may_grant(круг, tenant=пространство, role=роль)
            ):
                return people.Outcome("role.forbidden", 403)
            return people.change_role(
                login=логин,
                tenant=пространство,
                role=роль,
                actor_login=вошедший.login if вошедший else "",
                actor_tenant=вошедший.tenant if вошедший else "",
                only_roles=охват,
            )

        return _правка(сменить, роль_меняется=True)

    @app.post(f"{users_path}/email")
    @guard.action("people.manage")
    def user_email() -> FlaskResponse | tuple[str, int]:
        """Почта входа через Google (#399): задать или снять (пустое поле). Цель — в охвате."""
        вошедший = auth.current_account()
        почта = request.form.get("email") or ""
        return _правка(
            lambda логин, пространство, охват: people.change_email(
                login=логин,
                tenant=пространство,
                email=почта,
                actor_login=вошедший.login if вошедший else "",
                actor_tenant=вошедший.tenant if вошедший else "",
                only_roles=охват,
            )
        )


def _install_add_freeze(app: Flask, users_path: str) -> None:
    """Добавить человека, заморозить и разморозить."""

    def _set_email(круг: Scope, логин: str, пространство: str, почта: str) -> bool:
        вошедший = auth.current_account()
        исход = people.change_email(
            login=логин,
            tenant=пространство,
            email=почта,
            actor_login=вошедший.login if вошедший else "",
            actor_tenant=вошедший.tenant if вошедший else "",
            only_roles=_touchable_roles(круг, пространство),
        )
        return исход.key == "email.ok"

    @app.post(f"{users_path}/add")
    @guard.action("people.manage")
    def add_user() -> FlaskResponse | tuple[str, int]:
        """Добавить человека. Пароль показывается ОДИН раз — на этой же странице.

        Страница, а не перенаправление: пароль в адресе остался бы в истории
        браузера и в журнале обратного прокси. Пространство или роль вне охвата
        — подделка, отказ 403 до базы. Почта для Google необязательна и
        задаётся той же дверью, что в карточке, уже после заведения.
        """
        круг = people_scope()
        if круг is None:
            return forbidden()
        refuse_foreign_origin()
        логин = (request.form.get("login") or "").strip()
        роль = request.form.get("role") or accounts.ROLE_AUDITOR
        пространство = canonical_tenant((request.form.get("tenant") or "").strip())
        почта = (request.form.get("email") or "").strip()
        if not access_policy.grantable_roles(круг, пространство):
            return forbidden()
        if почта and not people.EMAIL_SHAPE.match(почта):
            return render(Show(add=True, flash=_flash("users.email.shape", ok=False)), 400)
        try:
            if пространство not in accounts.spaces():
                return render(
                    Show(add=True, flash=_flash("users.add.space_unknown", ok=False)), 400
                )
            if роль not in accounts.roles_for(пространство):
                return render(Show(add=True, flash=_flash("users.add.role_space", ok=False)), 400)
            if not access_policy.may_grant(круг, tenant=пространство, role=роль):
                return forbidden()
            заведённый = accounts.add(логин, tenant=пространство, role=роль)
        except DbError as exc:
            note_target_mismatch(exc)
            return render(Show(add=True, flash=_flash("users.add.failed", ok=False)), 400)
        почта_не_легла = bool(почта) and not _set_email(круг, заведённый.login, пространство, почта)
        return render(Show(add=True, added=заведённый, added_email_failed=почта_не_легла))

    def _цель_заморозки() -> tuple[Scope, str, str] | FlaskResponse:
        """Общее у заморозки и разморозки: охват, происхождение, логин и пространство из формы."""
        круг = people_scope()
        if круг is None:
            return forbidden()
        refuse_foreign_origin()
        логин = (request.form.get("login") or "").strip()
        пространство = canonical_tenant((request.form.get("tenant") or "").strip())
        return круг, логин, пространство

    @app.post(f"{users_path}/freeze")
    @guard.action("people.manage")
    def freeze_user() -> FlaskResponse | tuple[str, int]:
        """Заморозить учётку в охвате (D462): всё, чем человек входил, закрывается разом.

        Сессии, подключения Claude, токены MCP, бот — одной транзакцией базы
        (`0063`). Себя — нельзя; последнего главного админа — тоже. Главного
        админа замораживает только главный: он не в охвате админа УК.
        """
        решено = _цель_заморозки()
        if not isinstance(решено, tuple):
            return решено
        круг, логин, пространство = решено
        вошедший = auth.current_account()
        if вошедший is not None and логин.lower() == вошедший.login.strip().lower():
            # Заморозить себя — это выйти и не вернуться. Логин единый на всю
            # систему (D282), поэтому сверка по нему одному, без пространства.
            return render(Show(person=ME, flash=_flash("users.freeze.self", ok=False)), 400)
        try:
            цель = _target(круг, логин, пространство)
            if цель is None:
                return forbidden()
            заморожено = accounts.freeze(
                цель.login,
                tenant=цель.tenant,
                only_roles=_touchable_roles(круг, цель.tenant),
                by=вошедший.id if вошедший else None,
            )
        except accounts.LastSuperadminError:
            return render(Show(flash=_flash("users.freeze.last_super", ok=False)), 409)
        except DbError as exc:
            note_target_mismatch(exc)
            return render(Show(flash=_flash("users.freeze.failed", ok=False)), 400)
        if заморожено:
            logger.info(
                "Веб: учётка %s заморозила учётку %s",
                log_id(вошедший.id if вошедший else ""),
                log_id(цель.id),
            )
        исход = "users.freeze.ok" if заморожено else "users.freeze.missing"
        return render(Show(person=цель.id, show_off=True, flash=_flash(исход, ok=заморожено)))

    @app.post(f"{users_path}/unfreeze")
    @guard.action("people.manage")
    def unfreeze_user() -> FlaskResponse | tuple[str, int]:
        """Разморозить учётку (D462): только главный админ. Снимает одну отметку.

        Сессии, подключения Claude, токены и бот остаются закрытыми: человек
        входит заново, привязывает бота и подключает Claude сам.
        """
        решено = _цель_заморозки()
        if not isinstance(решено, tuple):
            return решено
        круг, логин, пространство = решено
        if not access_policy.may_unfreeze(круг):
            return forbidden()
        try:
            цель = _target(круг, логин, пространство)
            if цель is None:
                return forbidden()
            разморожено = accounts.unfreeze(
                цель.login, tenant=цель.tenant, only_roles=_touchable_roles(круг, цель.tenant)
            )
        except DbError as exc:
            note_target_mismatch(exc)
            return render(Show(flash=_flash("users.unfreeze.failed", ok=False)), 400)
        if разморожено:
            вошедший = auth.current_account()
            logger.info(
                "Веб: учётка %s разморозила учётку %s",
                log_id(вошедший.id if вошедший else ""),
                log_id(цель.id),
            )
        исход = "users.unfreeze.ok" if разморожено else "users.unfreeze.missing"
        return render(Show(person=цель.id, show_off=True, flash=_flash(исход, ok=разморожено)))


def _install_spaces(app: Flask, users_path: str) -> None:
    """Пространства партнёров и их страны (D364): главный админ и админ УК."""

    def _ведёт_пространства() -> FlaskResponse | None:
        круг = people_scope()
        if круг is None or not access_policy.manages_spaces(круг):
            return forbidden()
        refuse_foreign_origin()
        return None

    def _исход(код: str, ключ: str, *, ok: bool, add_space: bool = False) -> Show:
        return Show(tab=TAB_SPACES, space=код, add_space=add_space, flash=_flash(ключ, ok=ok))

    @app.post(f"{users_path}/spaces/add")
    @guard.action("space.manage")
    def add_space() -> FlaskResponse | tuple[str, int]:
        """Завести пространство партнёра вместе со странами (D364)."""
        отказ = _ведёт_пространства()
        if отказ is not None:
            return отказ
        код = (request.form.get("code") or "").strip().upper()
        try:
            partner_spaces.create_partner_space(
                код,
                name=request.form.get("name") or "",
                countries=partner_spaces.parse_countries(request.form.get("countries") or ""),
            )
        except DbError as exc:
            note_target_mismatch(exc)
            return render(_исход("", "users.spaces.space_failed", ok=False, add_space=True), 400)
        return render(_исход(код, "users.spaces.space_added", ok=True))

    @app.post(f"{users_path}/spaces/countries")
    @guard.action("space.manage")
    def space_countries() -> FlaskResponse | tuple[str, int]:
        """Добавить страны пространству партнёра."""
        отказ = _ведёт_пространства()
        if отказ is not None:
            return отказ
        код = (request.form.get("code") or "").strip()
        try:
            partner_spaces.add_countries(
                код, partner_spaces.parse_countries(request.form.get("countries") or "")
            )
        except DbError as exc:
            note_target_mismatch(exc)
            return render(_исход(код, "users.spaces.countries_failed", ok=False), 400)
        return render(_исход(код, "users.spaces.countries_added", ok=True))
