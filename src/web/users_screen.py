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

from collections.abc import Callable

from flask import Flask, make_response, render_template, request
from flask import Response as FlaskResponse

from src.db import bot_links, mcp_access
from src.db.errors import DbError
from src.domain.tenants import canonical_tenant

from . import access_policy, accounts, auth, partner_spaces, people, profile, users_mcp
from .access_policy import Scope
from .config import WEB_BOT_USERNAME_VAR, Settings
from .db_refusal import note_target_mismatch
from .origin import refuse_foreign_origin
from .remote import client_address
from .sections import section
from .users_page import (
    BOT_USERNAME_KEY,
    ME,
    SEES_BINDINGS,
    Flash,
    Show,
    people_scope,
    render,
    source,
)
from .users_view import TAB_SPACES


def link_url(bot_username: str, token: str) -> str:
    """Ссылка привязки бота: Telegram передаст метку боту командой `/start` (D286)."""
    return f"https://t.me/{bot_username}?start={bot_links.LINK_PREFIX}{token}"


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
    app.config[BOT_USERNAME_KEY] = conf.bot_username

    @app.get(users_path)
    def users() -> tuple[str, int]:
        return render()

    @app.post(f"{users_path}/bot-link")
    def bot_link() -> FlaskResponse | tuple[str, int]:
        """Выпустить ссылку привязки бота — ВСЕГДА своей учётке (D286).

        Ключ учётки из формы не читается вовсе: ссылка привязала бы чужой
        Telegram к выбранному человеку. Ссылка показывается на странице ответа,
        а не в адресе: адрес оседает в истории браузера и журнале прокси.
        """
        refuse_foreign_origin()
        вошедший = auth.current_account()
        if вошедший is None:
            raise RuntimeError("выпуск ссылки привязки без вошедшего: маршрут прошёл мимо заслона")
        if not conf.bot_username:
            return render(
                Show(
                    person=ME, flash=_flash("profile.bot.unset", ok=False, var=WEB_BOT_USERNAME_VAR)
                ),
                503,
            )
        try:
            ссылка = bot_links.issue_link(вошедший.id)
        except DbError:
            return render(Show(person=ME, flash=_flash("profile.bot.link_failed", ok=False)), 503)
        return render(
            Show(
                person=ME,
                bot_link=link_url(conf.bot_username, ссылка.token),
                bot_link_until=ссылка.expires_at,
            )
        )

    @app.post(f"{users_path}/bot-unlink")
    def bot_unlink() -> FlaskResponse | tuple[str, int]:
        """Отвязать бота: свою привязку — каждый; чужую — главный админ и админ УК в охвате."""
        refuse_foreign_origin()
        вошедший = auth.current_account()
        if вошедший is None:
            raise RuntimeError("отвязка бота без вошедшего: маршрут прошёл мимо заслона")
        чей = (request.form.get("user_id") or "").strip() or вошедший.id
        карточка = ME if чей == вошедший.id else чей
        if чей != вошедший.id:
            круг = people_scope()
            if круг is None or круг.kind not in SEES_BINDINGS:
                return forbidden()
            try:
                if not any(r.id == чей for r in access_policy.visible(круг, source(круг))):
                    return forbidden()
            except DbError:
                return render(Show(flash=_flash("users.bot.unlink_failed", ok=False)), 503)
        try:
            отвязано = bot_links.unbind(чей)
        except DbError:
            return render(
                Show(person=карточка, flash=_flash("users.bot.unlink_failed", ok=False)), 503
            )
        исход = "users.bot.unlinked" if отвязано else "users.bot.unlink_missing"
        return render(Show(person=карточка, flash=_flash(исход, ok=отвязано)))

    @app.post(f"{users_path}/password")
    def own_password() -> FlaskResponse | tuple[str, int]:
        """Сменить СВОЙ пароль (#324). Чей — решает сессия этого запроса, не форма."""
        refuse_foreign_origin()
        вошедший = auth.current_account()
        if вошедший is None:
            raise RuntimeError("смена пароля без вошедшего: маршрут прошёл мимо заслона")
        исход = profile.change_own(
            current=request.form.get("current") or "",
            new=request.form.get("new") or "",
            repeat=request.form.get("repeat") or "",
            token=auth.current_session_token(),
            login=вошедший.login,
            stand=auth.throttle_tenant(),
            address=client_address(trusted_proxies=conf.trusted_proxies),
        )
        страница, код = render(Show(person=ME, password=исход), исход.status)
        if исход.retry_after_seconds is None:
            return страница, код
        ответ = make_response(страница, код)
        ответ.headers["Retry-After"] = str(исход.retry_after_seconds)
        return ответ

    _install_edits(app, users_path)
    _install_add_disable(app, users_path)
    _install_mcp(app, users_path)
    _install_spaces(app, users_path)


def _install_edits(app: Flask, users_path: str) -> None:
    """Смена роли и почты в карточке человека."""

    def _правка(
        действие: Callable[[str, str, tuple[str, ...]], people.Outcome],
        *,
        роль_меняется: bool = False,
    ) -> FlaskResponse | tuple[str, int]:
        """Общее у правки роли и почты: охват, происхождение, цель по базе.

        Контролю смена роли не открывается никогда (D360).
        """
        круг = people_scope()
        if круг is None or (роль_меняется and круг.kind == access_policy.CONTROL):
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


def _install_add_disable(app: Flask, users_path: str) -> None:
    """Добавить человека и отключить доступ."""

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

    @app.post(f"{users_path}/disable")
    def disable_user() -> FlaskResponse | tuple[str, int]:
        """Отключить учётку в охвате. Себя — нельзя; последнего главного админа — тоже."""
        круг = people_scope()
        if круг is None:
            return forbidden()
        refuse_foreign_origin()
        логин = (request.form.get("login") or "").strip()
        пространство = canonical_tenant((request.form.get("tenant") or "").strip())
        вошедший = auth.current_account()
        if вошедший is not None and логин.lower() == вошедший.login.strip().lower():
            # Отключить себя — это выйти и не вернуться. Логин единый на всю
            # систему (D282), поэтому сверка по нему одному, без пространства.
            return render(Show(person=ME, flash=_flash("users.disable.self", ok=False)), 400)
        try:
            цель = _target(круг, логин, пространство)
            if цель is None:
                return forbidden()
            отключено = accounts.disable(
                цель.login, tenant=цель.tenant, only_roles=_touchable_roles(круг, цель.tenant)
            )
        except accounts.LastSuperadminError:
            return render(Show(flash=_flash("users.disable.last_super", ok=False)), 409)
        except DbError as exc:
            note_target_mismatch(exc)
            return render(Show(flash=_flash("users.disable.failed", ok=False)), 400)
        исход = "users.disable.ok" if отключено else "users.disable.missing"
        return render(Show(person=цель.id, show_off=True, flash=_flash(исход, ok=отключено)))


def _install_mcp(app: Flask, users_path: str) -> None:
    """Дать и снять доступ к Claude (MCP) из карточки человека (#583, правило круга D099)."""

    def _цель_круга() -> tuple[accounts.AccountRow, int, int] | None:
        """(человек, его Telegram, Telegram вошедшего) — или `None` (отказ 403)."""
        круг = people_scope()
        вошедший = auth.current_account()
        if круг is None or круг.kind not in SEES_BINDINGS or вошедший is None:
            return None
        чей = (request.form.get("user_id") or "").strip()
        цель = next((r for r in access_policy.visible(круг, source(круг)) if r.id == чей), None)
        if цель is None or цель.id == вошедший.id:
            return None
        своя = bot_links.binding_of(вошедший.id)
        его = bot_links.binding_of(чей)
        if своя is None or его is None or not users_mcp.actor_may_edit(своя):
            return None
        return цель, int(его.telegram_id), int(своя.telegram_id)

    @app.post(f"{users_path}/mcp-grant")
    def mcp_grant() -> FlaskResponse | tuple[str, int]:
        """Дать доступ к Claude: привести человека в круг, как `/mcp_add` в боте."""
        refuse_foreign_origin()
        try:
            найдено = _цель_круга()
            if найдено is None:
                return forbidden()
            цель, его, мой = найдено
            mcp_access.add_admin(его, by=мой)
        except DbError as exc:
            note_target_mismatch(exc)
            return render(Show(flash=_flash("users.mcp.failed", ok=False)), 503)
        return render(Show(person=цель.id, flash=_flash("users.mcp.granted", ok=True)))

    @app.post(f"{users_path}/mcp-revoke")
    def mcp_revoke() -> FlaskResponse | tuple[str, int]:
        """Снять доступ к Claude и погасить живые токены, как `/mcp_revoke` в боте."""
        refuse_foreign_origin()
        try:
            найдено = _цель_круга()
            if найдено is None:
                return forbidden()
            цель, его, мой = найдено
            if его == users_mcp.founder_id():
                return render(
                    Show(person=цель.id, flash=_flash("users.mcp.founder", ok=False)), 400
                )
            отзыв = mcp_access.revoke_access(его, by=мой)
        except DbError as exc:
            note_target_mismatch(exc)
            return render(Show(flash=_flash("users.mcp.failed", ok=False)), 503)
        return render(
            Show(
                person=цель.id,
                flash=_flash("users.mcp.revoked", ok=True, tokens=отзыв.tokens_revoked),
            )
        )


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
