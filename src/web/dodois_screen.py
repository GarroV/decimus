"""Вкладка «Dodo IS» раздела «Администрирование»: входы по странам и ссылки (D640, D641, #951).

С D641 это отдельная вкладка `?tab=dodois` рядом с «Подключениями» (раньше — блок внутри них);
формы и POST-маршруты возвращают в неё же. Страны — одна таблица (страна · статус ·
через кого, D651; строка открывает панель страны с действиями, D653): все страны сети из
справочника пиццерий, у страны без входа написано «Входа нет».

**Кто.** Только главный админ УК (заслон вкладки — `connections_screen._boss`, остальным
404 и на чтение, и на каждый POST). Коллеги в админку не заходят: владелец выдаёт им
ССЫЛКУ-приглашение, они подтверждают вход на сайте Dodo IS по публичной странице
(`dodois_connect.py`), а здесь видно, кто подтвердил и в каком состоянии вход.

**Ссылка.** Выдача — случайный токен (`domain.dodois.new_token`, 32 байта), живёт 24 часа,
привязан к стране, одноразовый; в базе только его хэш. Показывается ОДИН раз ответом на
выдачу (без перенаправления, `Cache-Control: private, no-store`), дальше — только статус:
выдано, использовано, истекло, отозвано. Токен не пишется ни в журнал, ни в сессию.

**Заслоны выдачи** — как у ключей сервисов (`connections_screen._key_action`): роль (404) →
`refuse_foreign_origin()` → второй шаг входа в этой сессии → свежее подтверждение → предел
попыток. Отзыв и «Проверить сейчас» ничего не выдают: роль и происхождение.

**Ключи приложения (D648).** Первым блоком вкладки — пара `client_id` / `client_secret`
приложения Decimus в маркетплейсе Dodo IS (сервис `dodois` реестра `src/domain/service_keys.py`;
на «Подключениях» её больше нет). Формы и адреса те же, что у ключей сервисов
(`connections_screen._key_action`, заслоны те же); после действия — эта же вкладка (скрытое поле
формы `back`, только известные вкладки). Пока пары нет, страны и выдача ссылки подсказывают
сначала задать её.

**Ключей входа на экране нет.** Ни ключей входа стран, ни значений ключей приложения: только
состояние, «••••» и последние четыре знака пары, счёт пиццерий и время.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from flask import Flask, abort, current_app, g, make_response, render_template, request
from flask import Response as FlaskResponse
from werkzeug.wrappers import Response

from src.db import dodois_logins, web_throttle
from src.db import ratings_read as ratings
from src.db.errors import DbError
from src.dodois import service
from src.domain import dodois as rules
from src.domain.dodois import Invite, Login

from . import administration, auth, guard, service_keys_screen
from .db_refusal import note_target_mismatch
from .journal import TARGET_OVERRIDE
from .origin import refuse_foreign_origin
from .sections import section
from .users_view import TAB_DODOIS

_log = logging.getLogger(__name__)

#: Сколько последних приглашений показываем.
INVITES_SHOWN = 30
ISSUE_ACTION = "dodois_invite_issue"
REVOKE_ACTION = "dodois_invite_revoke"
CHECK_ACTION = "dodois_check"


@dataclass(frozen=True)
class Flash:
    """Исход действия блока: ключ текста, тон и подстановки (без значений)."""

    key: str
    ok: bool
    params: dict[str, Any]


@dataclass(frozen=True)
class IssuedLink:
    """Только что выданная ссылка — показывается один раз. Не печатается."""

    country: str
    url: str
    expires_at: datetime
    #: Рабочий вход страны, который новая привязка может заменить, — для предупреждения.
    replaces: Login | None = None

    def __repr__(self) -> str:
        return "IssuedLink(<скрыто>)"


@dataclass(frozen=True)
class CountryRow:
    """Строка таблицы стран: вход (если есть) и свежайшее приглашение."""

    code: str
    login: Login | None
    #: Свежайшее приглашение страны — для строки, когда входа ещё нет.
    latest: Invite | None


@dataclass(frozen=True)
class View:
    rows: tuple[CountryRow, ...]
    invites: tuple[Invite, ...]
    known: bool
    flash: Flash | None
    issued: IssuedLink | None
    registry: tuple[tuple[str, str, str], ...]


def public_link(token: str) -> str:
    """Полный адрес ссылки для коллеги: публичный адрес админки или адрес этого запроса."""
    conf = current_app.extensions["decimus_conf"]
    base = (conf.admin_public_url or request.url_root).rstrip("/")
    return f"{base}/dodois/connect/{token}"


def _registry() -> tuple[tuple[str, str, str], ...]:
    try:
        return tuple((c.code, c.name_ru, c.name_en) for c in ratings.countries())
    except DbError as exc:
        note_target_mismatch(exc)
        return ()


def _rows(
    logins: tuple[Login, ...],
    invites: tuple[Invite, ...],
    network: tuple[str, ...] = (),
) -> tuple[CountryRow, ...]:
    """Страны сети (порядок справочника), затем прочие со входом или ссылкой — по коду."""
    by_country = {login.country: login for login in logins}
    latest: dict[str, Invite] = {}
    for invite in invites:  # свежие первыми
        latest.setdefault(invite.country, invite)
    extra = sorted((set(by_country) | set(latest)) - set(network))
    return tuple(CountryRow(c, by_country.get(c), latest.get(c)) for c in (*network, *extra))


def view(flash: Flash | None = None, issued: IssuedLink | None = None) -> View:
    try:
        logins = dodois_logins.list_logins()
        invites = dodois_logins.list_invites(INVITES_SHOWN)
    except DbError as exc:
        note_target_mismatch(exc)
        _log.warning("dodois: входы не прочитаны (%s)", type(exc).__name__)
        return View((), (), False, flash, issued, ())
    registry = _registry()
    rows = _rows(logins, invites, tuple(code for code, _, _ in registry))
    return View(rows, invites, True, flash, issued, registry)


def context(
    flash: Flash | None = None,
    issued: IssuedLink | None = None,
    key_flash: service_keys_screen.KeyFlash | None = None,
) -> dict[str, Any]:
    """Переменные шаблона вкладки: страны, ссылки и ключи приложения маркетплейса."""
    return {
        "dodois": view(flash, issued),
        "dodois_flash": flash,
        **service_keys_screen.app_context(key_flash),
        "dodois_now": datetime.now(UTC),
        "dodois_stamp": _stamp,
    }


def _stamp(moment: datetime | None) -> str:
    return "" if moment is None else moment.astimezone(UTC).strftime("%d.%m %H:%M UTC")


def _link(**extra: str) -> str:
    """Адрес вкладки; `tab` в шаблонах — наследство «Подключений»."""
    return administration.url(TAB_DODOIS, **{k: v for k, v in extra.items() if k != "tab"})


def _boss() -> str:
    from . import connections_screen  # connections_screen сам берёт этот модуль

    return connections_screen._boss()


def page(
    flash: Flash | None = None,
    issued: IssuedLink | None = None,
    code: int = 200,
    key_flash: service_keys_screen.KeyFlash | None = None,
    picked: str = "",
) -> FlaskResponse:
    """Вкладка целиком — для GET и для ответа на любое действие (в том числе над ключами).

    `picked` — страна, чья панель открыта справа: выбор из адреса или страна действия.
    """
    from . import connections_screen

    html = render_template(
        "administration/dodois.html",
        users_url=f"{request.script_root}{section('administration').path}",
        link=_link,
        picked=picked,
        split_open=bool(picked),
        split_back=_link(),
        day=connections_screen._day,
        **context(flash, issued, key_flash),
        **administration.nav(TAB_DODOIS),
    )
    response = make_response(html, code)
    # Ссылка-приглашение в теле ответа выдачи: ни браузер, ни прокси не оставляют копии.
    response.headers["Cache-Control"] = "private, no-store"
    return response


def show() -> FlaskResponse:
    """GET `/administration?tab=dodois[&country=<код>]`: список стран и, при выборе, панель."""
    _boss()
    raw = (request.args.get("country") or "").strip().upper()
    if raw and (not rules.is_country(raw) or raw not in {c for c, _, _ in _registry()}):
        abort(404)
    return page(picked=raw)


# --- действия ------------------------------------------------------------------------


def _country_from_form() -> str | None:
    """Код страны из формы — только из реестра стран; иначе `None`."""
    code = (request.form.get("country") or "").strip()
    if not rules.is_country(code):
        return None
    if code not in {c for c, _, _ in _registry()}:
        return None
    return code


def issue(by_login: str, account: Any) -> tuple[Flash | IssuedLink, int]:
    """Выдать ссылку на страну из формы. Токен возвращается только здесь, один раз."""
    country = _country_from_form()
    if country is None:
        return Flash("dodois.err.country", False, {}), 400
    token = rules.new_token()
    now = datetime.now(UTC)
    try:
        invite_id = dodois_logins.create_invite(
            country=country,
            token_hash=rules.hash_token(token),
            issued_by=by_login,
            issued_by_id=str(account.id),
            issued_by_role=str(account.role),
            issued_by_tenant=str(account.tenant),
            now=now,
            expires_at=now + rules.INVITE_TTL,
        )
    except DbError as exc:
        note_target_mismatch(exc)
        _log.warning("dodois: ссылка не записана (%s)", type(exc).__name__)
        return Flash("dodois.err.db", False, {}), 503
    # Цель журнала — номер и страна; токена в ней нет, он не попадает и в форму.
    setattr(g, TARGET_OVERRIDE, f"country={country}; invite={invite_id}")
    try:
        replaces = dodois_logins.get_login(country)
    except DbError:
        replaces = None  # предупреждение — подсказка; ссылка уже выдана
    return IssuedLink(country, public_link(token), now + rules.INVITE_TTL, replaces), 200


def revoke(invite_id: int) -> tuple[Flash, int]:
    setattr(g, TARGET_OVERRIDE, f"invite={invite_id}")
    try:
        done = dodois_logins.revoke_invite(invite_id, datetime.now(UTC))
    except DbError as exc:
        note_target_mismatch(exc)
        return Flash("dodois.err.db", False, {}), 503
    if not done:
        return Flash("dodois.err.not_revocable", False, {}), 409
    return Flash("dodois.ok.revoked", True, {}), 200


def check_now(country: str) -> tuple[Flash, int]:
    """«Проверить сейчас»: счёт открытых пиццерий. Только чтение у Dodo IS."""
    setattr(g, TARGET_OVERRIDE, f"country={country}")
    try:
        login = service.check(country)
    except DbError as exc:
        note_target_mismatch(exc)
        return Flash("dodois.err.db", False, {}), 503
    if login is None:
        return Flash("dodois.err.no_login", False, {}), 409
    return Flash("dodois.ok.checked", login.state in (rules.OK, rules.PARTIAL), {}), 200


def install(app: Flask) -> None:
    """Действия блока. Заслоны — общие с ключами сервисов (`connections_screen`)."""
    from . import connections_screen as screen

    base = f"{section('administration').path}/dodois"

    @app.post(f"{base}/invite", endpoint=ISSUE_ACTION)
    @guard.action("keys.manage", hidden=True)
    def dodois_invite_issue() -> Response:
        login = _boss()
        refuse_foreign_origin()
        back = f"{section('administration').path}?tab={TAB_DODOIS}"
        refused = screen._key_gate(login, back)
        if isinstance(refused, tuple):
            flash, code = refused
            return page(
                Flash(flash.key, False, flash.params or {}),
                code=code,
                picked=_country_from_form() or "",
            )
        if refused is not None:
            return refused
        result, code = issue(login, auth.current_account())
        if isinstance(result, IssuedLink):
            web_throttle.note_service_key_ok(tenant=screen._stand(), login=login)
            return page(issued=result, code=code, picked=result.country)
        return page(result, code=code)

    @app.post(f"{base}/invite/<int:invite_id>/revoke", endpoint=REVOKE_ACTION)
    @guard.action("keys.manage", hidden=True)
    def dodois_invite_revoke(invite_id: int) -> Response:
        _boss()
        refuse_foreign_origin()
        flash, code = revoke(invite_id)
        return page(flash, code=code, picked=_country_from_form() or "")

    @app.post(f"{base}/<country>/check", endpoint=CHECK_ACTION)
    @guard.action("keys.manage", hidden=True)
    def dodois_check(country: str) -> Response:
        _boss()
        if not rules.is_country(country):
            abort(404)
        refuse_foreign_origin()
        flash, code = check_now(country)
        return page(flash, code=code, picked=country)
