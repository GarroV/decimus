"""Блок «Dodo IS» на вкладке «Подключения»: входы по странам и ссылки для коллег (D640, #951).

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

**Ключей на экране нет.** Ни ключей входа, ни ключей приложения, ни их хвостов: только
состояние, счёт пиццерий и время.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from flask import Flask, abort, current_app, g, request
from werkzeug.wrappers import Response

from src.db import dodois_logins, web_throttle
from src.db import ratings_read as ratings
from src.db.errors import DbError
from src.dodois import service
from src.domain import dodois as rules
from src.domain.dodois import Invite, Login

from . import auth, guard
from .db_refusal import note_target_mismatch
from .journal import TARGET_OVERRIDE
from .origin import refuse_foreign_origin
from .sections import section

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

    def __repr__(self) -> str:
        return "IssuedLink(<скрыто>)"


@dataclass(frozen=True)
class CountryRow:
    """Строка страны слева: вход (если есть) и приглашения."""

    code: str
    login: Login | None
    #: Свежайшее приглашение страны — для строки, когда входа ещё нет.
    latest: Invite | None


@dataclass(frozen=True)
class View:
    rows: tuple[CountryRow, ...]
    invites: tuple[Invite, ...]
    selected: str
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


def _rows(logins: tuple[Login, ...], invites: tuple[Invite, ...]) -> tuple[CountryRow, ...]:
    by_country = {login.country: login for login in logins}
    latest: dict[str, Invite] = {}
    for invite in invites:  # свежие первыми
        latest.setdefault(invite.country, invite)
    return tuple(
        CountryRow(c, by_country.get(c), latest.get(c))
        for c in sorted(set(by_country) | set(latest))
    )


def view(flash: Flash | None = None, issued: IssuedLink | None = None) -> View:
    try:
        logins = dodois_logins.list_logins()
        invites = dodois_logins.list_invites(INVITES_SHOWN)
    except DbError as exc:
        note_target_mismatch(exc)
        _log.warning("dodois: входы не прочитаны (%s)", type(exc).__name__)
        return View((), (), "", False, flash, issued, ())
    rows = _rows(logins, invites)
    codes = [r.code for r in rows]
    wanted = issued.country if issued else request.args.get("country") or ""
    selected = wanted if wanted in codes or wanted == "add" else ""
    if not selected and not request.args.get("country") and codes:
        selected = codes[0]
    return View(rows, invites, selected, True, flash, issued, _registry())


def context(flash: Flash | None = None, issued: IssuedLink | None = None) -> dict[str, Any]:
    """Переменные шаблона блока."""
    return {
        "dodois": view(flash, issued),
        "dodois_now": datetime.now(UTC),
        "dodois_stamp": _stamp,
    }


def _stamp(moment: datetime | None) -> str:
    return "" if moment is None else moment.astimezone(UTC).strftime("%d.%m %H:%M UTC")


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
    return IssuedLink(country, public_link(token), now + rules.INVITE_TTL), 200


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

    base = f"{section('administration').path}/connections/dodois"

    @app.post(f"{base}/invite", endpoint=ISSUE_ACTION)
    @guard.action("keys.manage", hidden=True)
    def dodois_invite_issue() -> Response:
        login = screen._boss()
        refuse_foreign_origin()
        back = f"{section('administration').path}?tab=connections"
        refused = screen._key_gate(login, back)
        if isinstance(refused, tuple):
            flash, code = refused
            return screen._page(dodois_flash=Flash(flash.key, False, flash.params or {}), code=code)
        if refused is not None:
            return refused
        result, code = issue(login, auth.current_account())
        if isinstance(result, IssuedLink):
            web_throttle.note_service_key_ok(tenant=screen._stand(), login=login)
            return screen._page(dodois_issued=result, code=code)
        return screen._page(dodois_flash=result, code=code)

    @app.post(f"{base}/invite/<int:invite_id>/revoke", endpoint=REVOKE_ACTION)
    @guard.action("keys.manage", hidden=True)
    def dodois_invite_revoke(invite_id: int) -> Response:
        screen._boss()
        refuse_foreign_origin()
        flash, code = revoke(invite_id)
        return screen._page(dodois_flash=flash, code=code)

    @app.post(f"{base}/<country>/check", endpoint=CHECK_ACTION)
    @guard.action("keys.manage", hidden=True)
    def dodois_check(country: str) -> Response:
        screen._boss()
        if not rules.is_country(country):
            abort(404)
        refuse_foreign_origin()
        flash, code = check_now(country)
        return screen._page(dodois_flash=flash, code=code)
