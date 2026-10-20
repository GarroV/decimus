"""Вкладка «Подключения» экрана «Пользователи»: ключи API сервисов (D425, #568).

Главный админ выдаёт, правит, перевыпускает и отзывает ключи `/api/v1/*` без
командной строки и видит, как каждый сервис ходит. Вся работа с базой — слой
`src/db/api_access.py`; здесь маршруты, заслон и страница.

**Заслон.** Экран открыт только главному админу УК (охват `SUPER`). Всем
остальным — 404, а не 403: снаружи этого экрана не существует, и по ответу
нельзя понять, что он есть. Порядок на каждой отправке: общий заслон
происхождения приложения (чужая страница — 403 на любой POST), затем роль, затем
`refuse_foreign_origin()` ещё раз, затем разбор формы.

**Ключ показывается один раз.** Ответ на выдачу и перевыпуск — страница с
ключом, без перенаправления (адрес оседает в истории браузера и журнале прокси)
и с `Cache-Control: private, no-store`. Ключ не пишется ни в журнал, ни в
уведомление исхода, ни в сессию; в базе от него только отпечаток.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from flask import Flask, abort, g, make_response, render_template, request
from flask import Response as FlaskResponse
from werkzeug.wrappers import Response

from src.db import api_access, web_throttle
from src.db import ratings_read as ratings
from src.db.errors import DbError
from src.domain import service_keys as registry

from . import access_policy, auth, connections_form, guard, reauth, service_keys_screen
from .connections_form import Draft, Refusal
from .db_refusal import note_target_mismatch
from .journal import TARGET_OVERRIDE
from .origin import refuse_foreign_origin
from .sections import section
from .users_view import TAB_CONNECTIONS, Filters, screen_url

#: Сколько дней обращений и строк журнала показывает карточка.
USAGE_DAYS = 14
LOG_LINES = 20

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Flash:
    """Исход действия: ключ текста, тон и подстановки."""

    key: str
    ok: bool
    params: dict[str, Any]


def _refusal(refusal: Refusal) -> Flash:
    return Flash(f"connections.err.{refusal.key}", False, refusal.params)


def _fail(key: str) -> Flash:
    return Flash(f"connections.err.{key}", False, {})


def _boss() -> str:
    """Логин вошедшего главного админа УК; для любого другого — 404.

    Охват берётся из роли и пространства СЕССИИ, а не из формы.
    """
    вошедший = auth.current_account()
    охват = None if вошедший is None else access_policy.scope_of(вошедший.role, вошедший.tenant)
    if вошедший is None or охват is None or охват.kind != access_policy.SUPER:
        abort(404)
    return str(вошедший.login)


def status_of(token: api_access.TokenRow, now: datetime) -> str:
    """`live`, `revoked` или `expired` — подпись и порядок в списке."""
    if token.revoked_at is not None:
        return "revoked"
    return "live" if token.is_live(now) else "expired"


def _stamp(moment: datetime | None) -> str:
    return "" if moment is None else moment.astimezone(UTC).strftime("%Y-%m-%d %H:%M")


def _day(moment: datetime | None) -> str:
    return "" if moment is None else moment.astimezone(UTC).strftime("%Y-%m-%d")


def _tokens() -> tuple[tuple[api_access.TokenRow, ...], bool]:
    """Перечень сервисов и признак «перечень известен»: отказ базы — не «никого нет»."""
    try:
        return tuple(api_access.list_tokens()), True
    except DbError as exc:
        note_target_mismatch(exc)
        _log.warning("connections: перечень ключей не прочитан (%s)", type(exc).__name__)
        return (), False


def _days(token_id: int, today: date) -> list[api_access.DayUsage] | None:
    """Обращения за `USAGE_DAYS` дней, от свежего дня к старому, с нулевыми днями."""
    try:
        got = {u.day: u for u in api_access.usage(token_id, days=USAGE_DAYS)}
    except DbError as exc:
        _log.warning("connections: обращения не прочитаны (%s)", type(exc).__name__)
        return None
    days = (today - timedelta(days=n) for n in range(USAGE_DAYS))
    return [got.get(d) or api_access.DayUsage(d, 0, 0) for d in days]


def _lines(token_id: int) -> list[api_access.LogLine] | None:
    try:
        return api_access.recent_log(token_id, limit=LOG_LINES)
    except DbError as exc:
        _log.warning("connections: журнал не прочитан (%s)", type(exc).__name__)
        return None


def _values_of(token: api_access.TokenRow) -> dict[str, Any]:
    """Поля формы правки — как сейчас у сервиса."""
    return {
        "code": token.consumer,
        "title": token.title or "",
        "contact": token.contact or "",
        "scopes": token.scopes,
        "countries": " ".join(token.countries or ()),
        "expires": _day(token.expires_at),
    }


_EMPTY_VALUES: dict[str, Any] = {
    "code": "",
    "title": "",
    "contact": "",
    "scopes": (),
    "countries": "",
    "expires": "",
}


def _link(**extra: str) -> str:
    base = f"{request.script_root}{section('users').path}"
    return screen_url(base, lang=request.args.get("lang") or "", f=Filters(), **extra)


def _page(
    *,
    flash: Flash | None = None,
    values: dict[str, Any] | None = None,
    issued: api_access.IssuedApiToken | None = None,
    reissued: bool = False,
    picked_id: int | None = None,
    add: bool = False,
    key_flash: service_keys_screen.KeyFlash | None = None,
    code: int = 200,
) -> FlaskResponse:
    """Страница вкладки целиком — для GET и для ответа на любое действие."""
    now = datetime.now(UTC)
    tokens, known = _tokens()
    живые = [t for t in tokens if status_of(t, now) == "live"]
    прочие = [t for t in tokens if status_of(t, now) != "live"]
    picked = next((t for t in tokens if t.id == picked_id), None)
    days = _days(picked.id, now.date()) if picked is not None else None
    log = _lines(picked.id) if picked is not None else None
    if values is None:
        values = _values_of(picked) if picked is not None and not add else _EMPTY_VALUES
    base = f"{request.script_root}{section('users').path}"
    html = render_template(
        "users/connections.html",
        tab=TAB_CONNECTIONS,
        has_spaces_tab=True,
        manages_spaces=True,
        has_connections_tab=True,
        has_journal_tab=True,
        has_usage_tab=True,
        users_url=base,
        link=_link,
        tokens_known=known,
        live=живые,
        older=прочие,
        total=len(tokens),
        status_of=lambda t: status_of(t, now),
        stamp=_stamp,
        day=_day,
        scopes=api_access.SCOPES,
        picked=picked,
        days=days,
        log=log,
        issued=issued,
        reissued=reissued,
        add=add,
        values=values,
        show_flash=flash,
        max_name=connections_form.MAX_NAME,
        max_contact=connections_form.MAX_CONTACT,
        split_open=issued is not None or add or picked is not None,
        split_back=_link(tab=TAB_CONNECTIONS),
        **service_keys_screen.context(key_flash),
    )
    response = make_response(html, code)
    # Ключ API в теле ответа выдачи и записи о ключах сервисов: ни браузер, ни прокси не
    # оставляют копии вкладки (D576 — для всех ответов вкладки, не только для выдачи).
    response.headers["Cache-Control"] = "private, no-store"
    return response


def _int(raw: str | None) -> int | None:
    try:
        return int(raw or "")
    except ValueError:
        return None


def show() -> FlaskResponse:
    """GET `/users?tab=connections[&service=<№>|&add=1]`."""
    _boss()
    return _page(picked_id=_int(request.args.get("service")), add=request.args.get("add") == "1")


def _draft(
    *, with_code: bool, code: str = "", keep: date | None = None
) -> tuple[Draft | None, Flash | None, int]:
    """Форма → проверенный ввод либо исход отказа и его HTTP-код."""
    form = request.form
    known: frozenset[str] = frozenset()
    if (form.get("countries") or "").strip():
        try:
            known = frozenset(c.code for c in ratings.countries())
        except DbError as exc:
            note_target_mismatch(exc)
            return None, _fail("countries_db"), 503
    parsed = connections_form.parse(
        form,
        known_countries=known,
        today=datetime.now(UTC).date(),
        with_code=with_code,
        code=code,
        keep_expiry=keep,
    )
    if isinstance(parsed, Refusal):
        return None, _refusal(parsed), 400
    return parsed, None, 200


def _live_token(token_id: int) -> api_access.TokenRow | None:
    """Живой (не отозванный) сервис по номеру; отказ базы поднимается как `DbError`."""
    return next(
        (t for t in api_access.list_tokens() if t.id == token_id and t.revoked_at is None), None
    )


def install(app: Flask) -> None:
    """Действия вкладки. Страница (GET) отдаётся маршрутом `/users` через `show()`."""
    base = f"{section('users').path}/connections"

    @app.post(f"{base}/issue")
    @guard.action("api.manage", hidden=True)
    def connections_issue() -> FlaskResponse:
        """Выдать ключ. Ключ — на странице ответа, один раз."""
        автор = _boss()
        refuse_foreign_origin()
        draft, flash, code = _draft(with_code=True)
        if draft is None:
            return _page(
                flash=flash, values=connections_form.raw_values(request.form), add=True, code=code
            )
        try:
            issued = api_access.issue(
                draft.consumer,
                draft.scopes,
                by=автор,
                title=draft.title,
                contact=draft.contact,
                expires_at=draft.expires_at,
                countries=draft.countries,
            )
        except DbError as exc:
            note_target_mismatch(exc)
            return _page(
                flash=_fail("db"),
                values=connections_form.raw_values(request.form),
                add=True,
                code=503,
            )
        return _page(issued=issued, picked_id=issued.id)

    @app.post(f"{base}/<int:token_id>/update")
    @guard.action("api.manage", hidden=True)
    def connections_update(token_id: int) -> FlaskResponse:
        """Поправить права, название, контакт, страны и срок живого ключа."""
        _boss()
        refuse_foreign_origin()
        try:
            token = _live_token(token_id)
        except DbError as exc:
            note_target_mismatch(exc)
            return _page(flash=_fail("db"), picked_id=token_id, code=503)
        if token is None:
            return _page(flash=_fail("gone"), code=409)
        draft, flash, code = _draft(
            with_code=False,
            code=token.consumer,
            keep=None if token.expires_at is None else token.expires_at.astimezone(UTC).date(),
        )
        if draft is None:
            return _page(
                flash=flash,
                values=connections_form.raw_values(request.form),
                picked_id=token_id,
                code=code,
            )
        try:
            saved = api_access.update(
                token_id,
                draft.scopes,
                title=draft.title,
                contact=draft.contact,
                expires_at=draft.expires_at,
                countries=draft.countries,
            )
        except DbError as exc:
            note_target_mismatch(exc)
            return _page(flash=_fail("db"), picked_id=token_id, code=503)
        if not saved:
            return _page(flash=_fail("gone"), code=409)
        return _page(flash=Flash("connections.ok.saved", True, {}), picked_id=token_id)

    @app.post(f"{base}/<int:token_id>/reissue")
    @guard.action("api.manage", hidden=True)
    def connections_reissue(token_id: int) -> FlaskResponse:
        """Новый ключ с теми же правами; старый отозван той же транзакцией."""
        автор = _boss()
        refuse_foreign_origin()
        try:
            issued = api_access.reissue(token_id, by=автор)
        except DbError as exc:
            note_target_mismatch(exc)
            return _page(flash=_fail("db"), picked_id=token_id, code=503)
        if issued is None:
            return _page(flash=_fail("gone"), code=409)
        return _page(issued=issued, reissued=True, picked_id=issued.id)

    @app.post(f"{base}/<int:token_id>/revoke")
    @guard.action("api.manage", hidden=True)
    def connections_revoke(token_id: int) -> FlaskResponse:
        """Отозвать ключ: пускать перестаёт сразу, строка остаётся со следом."""
        автор = _boss()
        refuse_foreign_origin()
        try:
            name = next((t.name for t in api_access.list_tokens() if t.id == token_id), "")
            revoked = api_access.revoke(token_id, by=автор)
        except DbError as exc:
            note_target_mismatch(exc)
            return _page(flash=_fail("db"), picked_id=token_id, code=503)
        if not revoked:
            return _page(flash=_fail("gone"), picked_id=token_id, code=409)
        return _page(
            flash=Flash("connections.ok.revoked", True, {"name": name}), picked_id=token_id
        )


def _key_gate(login: str, back: str) -> Response | tuple[service_keys_screen.KeyFlash, int] | None:
    """Заслоны действий над ключами сервисов после роли и происхождения (D576).

    Порядок: второй шаг входа включён → он пройден в ЭТОЙ сессии → вход не старше
    `STEP_UP_MINUTES` (иначе «Подтвердите вход») → предел попыток. `None` — можно действовать.
    Возвращает исход-отказ (его рисует страница) либо готовый ответ-увод.
    """
    вошедший = auth.current_account()
    if not bool(getattr(вошедший, "has_second_factor", False)):
        return service_keys_screen.KeyFlash("", "keys.err.no_factor", False), 403
    if not bool(getattr(вошедший, "passed_second_step", False)):
        return service_keys_screen.KeyFlash("", "keys.err.prove_step", False), 403
    переспрос = reauth.require_fresh(back, max_age=timedelta(minutes=registry.STEP_UP_MINUTES))
    if переспрос is not None:
        return переспрос
    попытка = web_throttle.admit_service_key_action(tenant=_stand(), login=login)
    if not попытка.admitted:
        minutes = попытка.verdict.retry_after_minutes
        return service_keys_screen.KeyFlash("", "keys.err.rate", False, {"minutes": minutes}), 429
    return None


def _stand() -> str:
    from flask import current_app

    return str(current_app.extensions["decimus_conf"].tenant)


def _key_action(
    service_code: str,
    do: Callable[[registry.Service, str], tuple[service_keys_screen.KeyFlash, int]],
) -> Response:
    """Общий порядок действий над ключами сервисов (D576).

    Роль (404) → сервис из реестра (404) → происхождение (403) → заслоны `_key_gate` →
    действие. Ответ — вкладка целиком, а не перенаправление: исход виден сразу, значения в
    ответе нет. Цель записи журнала названа здесь заранее и без формы.
    """
    автор = _boss()
    service = registry.service(service_code)
    if service is None:
        abort(404)
    setattr(g, TARGET_OVERRIDE, f"service={service.code}")
    refuse_foreign_origin()
    back = f"{section('users').path}?tab={TAB_CONNECTIONS}"
    refused = _key_gate(автор, back)
    if isinstance(refused, tuple):
        flash, code = refused
        return _page(key_flash=_with_service(flash, service.code), code=code)
    if refused is not None:
        return refused
    flash, code = do(service, автор)
    if flash.ok:
        web_throttle.note_service_key_ok(tenant=_stand(), login=автор)
    return _page(key_flash=flash, code=code)


def _with_service(flash: service_keys_screen.KeyFlash, code: str) -> service_keys_screen.KeyFlash:
    return service_keys_screen.KeyFlash(code, flash.key, flash.ok, flash.params)


def install_service_keys(app: Flask) -> None:
    """Действия блока «Ключи сервисов»: проверить, заменить, удалить."""
    base = f"{section('users').path}/connections/keys/<service_code>"

    @app.post(f"{base}/check")
    @guard.action("keys.manage", hidden=True)
    def service_key_check(service_code: str) -> Response:
        return _key_action(service_code, lambda svc, _by: service_keys_screen.check(svc))

    @app.post(f"{base}/save")
    @guard.action("keys.manage", hidden=True)
    def service_key_save(service_code: str) -> Response:
        def do(svc: registry.Service, by: str) -> tuple[service_keys_screen.KeyFlash, int]:
            flash, code, summary = service_keys_screen.save(svc, by)
            if summary:
                setattr(g, TARGET_OVERRIDE, f"service={svc.code}; {summary}")
            return flash, code

        return _key_action(service_code, do)

    @app.post(f"{base}/delete")
    @guard.action("keys.manage", hidden=True)
    def service_key_delete(service_code: str) -> Response:
        return _key_action(service_code, lambda svc, _by: service_keys_screen.remove(svc))
