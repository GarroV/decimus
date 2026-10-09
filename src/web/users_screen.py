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
from datetime import datetime

from flask import Flask, make_response, render_template, request
from flask import Response as FlaskResponse

from src.db import bot_links
from src.db.errors import DbError
from src.domain.tenants import HQ_TENANT, canonical_tenant

from . import access_policy, accounts, auth, partner_spaces, people, profile
from .access_policy import Scope
from .config import WEB_BOT_USERNAME_VAR, Settings
from .db_refusal import note_target_mismatch
from .origin import refuse_foreign_origin
from .remote import client_address
from .sections import section

#: Охваты, которым видны привязки бота чужих людей и их отвязка (было — админ УК).
_SEES_BINDINGS = frozenset({access_policy.SUPER, access_policy.HQ_ADMIN})


def link_url(bot_username: str, token: str) -> str:
    """Ссылка привязки бота: Telegram передаст метку боту командой `/start` (D286)."""
    return f"https://t.me/{bot_username}?start={bot_links.LINK_PREFIX}{token}"


def people_scope() -> Scope | None:
    """Охват вошедшего на экране людей; `None` — людьми не управляет, видит себя."""
    вошедший = auth.current_account()
    if вошедший is None:
        return None
    return access_policy.scope_of(вошедший.role, вошедший.tenant)


def forbidden() -> FlaskResponse:
    """Отказ 403 на экране людей."""
    return render_template("users/forbidden.html"), 403  # type: ignore[return-value]


def _source(scope: Scope) -> tuple[accounts.AccountRow, ...]:
    """Перечень из базы — уже суженный запросом, где охват это позволяет.

    Админ партнёра и контроль читают только своё пространство; дальше всё равно
    фильтрует правило — сужение запроса здесь не единственный заслон.
    """
    if scope.kind in (access_policy.PARTNER_ADMIN, access_policy.CONTROL):
        return accounts.everyone(tenant=scope.tenant)
    return accounts.everyone(tenant=None)


def _target(scope: Scope, login: str, tenant: str) -> accounts.AccountRow | None:
    """Учётка из формы — если она есть в базе И в охвате; иначе `None` (отказ 403).

    «Нет такой» и «не ваша» снаружи неразличимы: оба — 403.
    """
    имя = login.strip().lower()
    где = canonical_tenant(tenant)
    for строка in access_policy.visible(scope, _source(scope)):
        if строка.login.strip().lower() == имя and canonical_tenant(строка.tenant) == где:
            return строка
    return None


def _touchable_roles(scope: Scope, tenant: str) -> tuple[str, ...]:
    """Роли цели, которые охват может трогать в этом пространстве — для `only_roles`."""
    return access_policy.grantable_roles(scope, tenant)


def install(app: Flask, conf: Settings) -> None:
    """Маршруты экрана «Пользователи» и его пространств."""
    users_path = section("users").path

    def _страница(
        *,
        added: accounts.Added | None = None,
        outcome: str | None = None,
        code: int = 200,
        bot_link: str | None = None,
        bot_link_until: datetime | None = None,
        password: profile.Outcome | None = None,
        edit: people.Outcome | None = None,
        space_outcome: str | None = None,
    ) -> tuple[str, int]:
        круг = people_scope()
        вошедший = auth.current_account()
        люди: tuple[accounts.AccountRow, ...] = ()
        пространства: tuple[str, ...] = ()
        перечень_известен = True
        привязки: dict[str, bot_links.Binding] = {}
        страны: tuple[partner_spaces.SpaceRow, ...] = ()
        страны_известны = True
        if круг is not None:
            try:
                люди = access_policy.visible(круг, _source(круг))
                пространства = access_policy.spaces_for_add(круг, accounts.spaces())
                if круг.kind in _SEES_BINDINGS:
                    свои = {r.id for r in люди}
                    привязки = {k: v for k, v in bot_links.live_bindings().items() if k in свои}
            except DbError as exc:
                note_target_mismatch(exc)
                # Отказ базы НЕ выдаётся за «никого нет»: на экране, где считают
                # людей с доступом, это была бы молчаливая ложь.
                перечень_известен = False
            if access_policy.manages_spaces(круг) or круг.kind == access_policy.PARTNER_ADMIN:
                try:
                    страны = tuple(
                        s
                        for s in partner_spaces.overview()
                        if s.code != HQ_TENANT
                        and (access_policy.manages_spaces(круг) or s.code == круг.tenant)
                    )
                except DbError as exc:
                    note_target_mismatch(exc)
                    страны_известны = False
        своя_привязка: bot_links.Binding | None = None
        привязка_известна = True
        try:
            своя_привязка = bot_links.binding_of(вошедший.id) if вошедший else None
        except DbError:
            привязка_известна = False

        def role_choices(строка: accounts.AccountRow) -> tuple[str, ...]:
            """Роли для смены у строки; пусто — показать роль текстом."""
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

        return (
            render_template(
                "users/index.html",
                manage=круг is not None,
                scope_kind=None if круг is None else круг.kind,
                show_bindings=круг is not None and круг.kind in _SEES_BINDINGS,
                people=люди,
                people_known=перечень_известен,
                spaces=пространства,
                add_roles=(
                    ()
                    if круг is None
                    else tuple(
                        dict.fromkeys(
                            r for s in пространства for r in access_policy.grantable_roles(круг, s)
                        )
                    )
                ),
                role_choices=role_choices,
                partner_spaces=страны,
                partner_spaces_known=страны_известны,
                manages_spaces=круг is not None and access_policy.manages_spaces(круг),
                space_outcome=space_outcome,
                added=added,
                outcome=outcome,
                users_path=users_path,
                bindings=привязки,
                own_binding=своя_привязка,
                own_binding_known=привязка_известна,
                bot_username=conf.bot_username,
                bot_link=bot_link,
                bot_link_until=bot_link_until,
                bot_var=WEB_BOT_USERNAME_VAR,
                password=password,
                min_password=accounts.MIN_PASSWORD_LENGTH,
                max_password=accounts.MAX_PASSWORD_LENGTH,
                edit=edit,
            ),
            code,
        )

    @app.get(users_path)
    def users() -> FlaskResponse | tuple[str, int]:
        return _страница()

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
            return _страница(outcome="bot_unset", code=503)
        try:
            ссылка = bot_links.issue_link(вошедший.id)
        except DbError:
            return _страница(outcome="bot_link_failed", code=503)
        return _страница(
            bot_link=link_url(conf.bot_username, ссылка.token),
            bot_link_until=ссылка.expires_at,
        )

    @app.post(f"{users_path}/bot-unlink")
    def bot_unlink() -> FlaskResponse | tuple[str, int]:
        """Отвязать бота: свою привязку — каждый; чужую — главный админ и админ УК в охвате."""
        refuse_foreign_origin()
        вошедший = auth.current_account()
        if вошедший is None:
            raise RuntimeError("отвязка бота без вошедшего: маршрут прошёл мимо заслона")
        чей = (request.form.get("user_id") or "").strip() or вошедший.id
        if чей != вошедший.id:
            круг = people_scope()
            if круг is None or круг.kind not in _SEES_BINDINGS:
                return forbidden()
            try:
                if not any(r.id == чей for r in access_policy.visible(круг, _source(круг))):
                    return forbidden()
            except DbError:
                return _страница(outcome="bot_unlink_failed", code=503)
        try:
            отвязано = bot_links.unbind(чей)
        except DbError:
            return _страница(outcome="bot_unlink_failed", code=503)
        return _страница(outcome="bot_unlinked" if отвязано else "bot_unlink_missing")

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
        страница, код = _страница(password=исход, code=исход.status)
        if исход.retry_after_seconds is None:
            return страница, код
        ответ = make_response(страница, код)
        ответ.headers["Retry-After"] = str(исход.retry_after_seconds)
        return ответ

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
            return _страница(edit=people.Outcome("edit.space", 400), code=400)
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
            return _страница(edit=people.Outcome("role.self", 400), code=400)
        try:
            цель = _target(круг, логин, пространство)
        except DbError:
            return _страница(edit=people.Outcome("edit.failed", 503), code=503)
        if цель is None:
            return forbidden()
        исход = действие(цель.login, цель.tenant, _touchable_roles(круг, цель.tenant))
        return _страница(edit=исход, code=исход.status)

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

    @app.post(f"{users_path}/add")
    def add_user() -> FlaskResponse | tuple[str, int]:
        """Завести человека. Пароль показывается ОДИН раз — на этой же странице.

        Страница, а не перенаправление: пароль в адресе остался бы в истории
        браузера и в журнале обратного прокси. Пространство или роль вне охвата
        — подделка, отказ 403 до базы.
        """
        круг = people_scope()
        if круг is None:
            return forbidden()
        refuse_foreign_origin()
        логин = (request.form.get("login") or "").strip()
        роль = request.form.get("role") or accounts.ROLE_AUDITOR
        пространство = canonical_tenant((request.form.get("tenant") or "").strip())
        if not access_policy.grantable_roles(круг, пространство):
            return forbidden()
        try:
            if пространство not in accounts.spaces():
                return _страница(outcome="add_space_unknown", code=400)
            if роль not in accounts.roles_for(пространство):
                return _страница(outcome="add_role_space", code=400)
            if not access_policy.may_grant(круг, tenant=пространство, role=роль):
                return forbidden()
            заведённый = accounts.add(логин, tenant=пространство, role=роль)
        except DbError as exc:
            note_target_mismatch(exc)
            return _страница(outcome="add_failed", code=400)
        return _страница(added=заведённый, outcome="added")

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
            return _страница(outcome="disable_self", code=400)
        try:
            цель = _target(круг, логин, пространство)
            if цель is None:
                return forbidden()
            отключено = accounts.disable(
                цель.login, tenant=цель.tenant, only_roles=_touchable_roles(круг, цель.tenant)
            )
        except accounts.LastSuperadminError:
            return _страница(outcome="disable_last_super", code=409)
        except DbError as exc:
            note_target_mismatch(exc)
            return _страница(outcome="disable_failed", code=400)
        return _страница(outcome="disabled" if отключено else "disable_missing")

    def _ведёт_пространства() -> FlaskResponse | None:
        круг = people_scope()
        if круг is None or not access_policy.manages_spaces(круг):
            return forbidden()
        refuse_foreign_origin()
        return None

    @app.post(f"{users_path}/spaces/add")
    def add_space() -> FlaskResponse | tuple[str, int]:
        """Завести пространство партнёра вместе со странами (D364). Главный админ и админ УК."""
        отказ = _ведёт_пространства()
        if отказ is not None:
            return отказ
        try:
            partner_spaces.create_partner_space(
                (request.form.get("code") or "").strip().upper(),
                name=request.form.get("name") or "",
                countries=partner_spaces.parse_countries(request.form.get("countries") or ""),
            )
        except DbError as exc:
            note_target_mismatch(exc)
            return _страница(space_outcome="space_failed", code=400)
        return _страница(space_outcome="space_added")

    @app.post(f"{users_path}/spaces/countries")
    def space_countries() -> FlaskResponse | tuple[str, int]:
        """Добавить страны пространству партнёра. Главный админ и админ УК."""
        отказ = _ведёт_пространства()
        if отказ is not None:
            return отказ
        try:
            partner_spaces.add_countries(
                (request.form.get("code") or "").strip(),
                partner_spaces.parse_countries(request.form.get("countries") or ""),
            )
        except DbError as exc:
            note_target_mismatch(exc)
            return _страница(space_outcome="countries_failed", code=400)
        return _страница(space_outcome="countries_added")
