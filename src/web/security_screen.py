"""Экран «Вход и защита» (`/settings/security`, D463): способы подтверждения входа.

Отвечает на один вопрос человека — «чем подтверждается мой вход и как это поменять»:
ключи доступа (несколько, с названиями), приложение-аутентификатор (QR и ключ для ручного
ввода, подтверждение кодом), резервные коды (десять, показываются один раз).

**Чья учётка — решает сессия, а не форма.** Ни один маршрут не читает номер учётки из
запроса; чужой ключ по номеру из адреса не снимается (`remove_passkey(user, key)` ищет
ключ среди ключей ЭТОГО человека).

**Менять способы входа можно сразу после входа — не позже 10 минут.** Старее — экран
показывает только кнопку «Войти заново» (выход и вход с возвратом сюда: вход включает
вторую ступень, так что «свежий вход» — настоящий, а не просто пароль). Угнанная сессия
сама добавить себе ключ не может.

**Админ и главный админ без способа попадают сюда после первого входа** и больше никуда
(`auth._guard`, `second_step.ENROLL_ENDPOINTS`). Последний способ им не снять
(`remove_*` возвращает `LAST_FACTOR`).

Секреты: ключ приложения показывается, только пока приложение не подтверждено (QR и ключ
для ручного ввода); после подтверждения не показывается нигде. Резервные коды видны в ответе
на выпуск и больше нигде — в базе только их отпечатки.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import segno
from flask import (
    Flask,
    current_app,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    url_for,
)
from markupsafe import Markup
from werkzeug.wrappers import Response

from src.db import second_factor as store
from src.db.errors import DbError
from src.db.web_access import close_session
from src.domain.second_factor import (
    FRESH_FOR_ENROLLMENT,
    MAX_PASSKEY_NAME,
    backup_code_hash,
    is_required,
    match_totp_step,
    new_backup_codes,
    new_totp_secret,
    normalize_totp_code,
    totp_uri,
)

from . import auth, webauthn_rp
from .config import Settings
from .db_refusal import note_target_mismatch
from .origin import refuse_foreign_origin
from .second_step import party_of
from .sections import section

logger = logging.getLogger(__name__)

#: Сколько ключей доступа у человека не больше (запас на устройства, а не на перебор).
MAX_PASSKEYS = 10

SECURITY_ENDPOINT = "security_page"


@dataclass(frozen=True)
class Flash:
    """Исход действия: ключ текста, тон и параметры подстановки."""

    key: str
    ok: bool
    params: dict[str, Any] | None = None


@dataclass(frozen=True)
class TotpSetup:
    """Подключение приложения: QR и ключ для ручного ввода. Только пока не подтверждено."""

    qr_svg: Markup
    secret_groups: str


def is_fresh(account: Any, *, now: datetime | None = None) -> bool:
    """Вход не старше `FRESH_FOR_ENROLLMENT`; неизвестно когда — не свежий."""
    когда = getattr(account, "signed_in_at", None)
    if not isinstance(когда, datetime):
        return False
    return (now or datetime.now(UTC)) - когда <= FRESH_FOR_ENROLLMENT


def _qr_svg(uri: str) -> Markup:
    """QR как встроенный SVG на белом: читается и на тёмной теме, адресов наружу нет."""
    svg = segno.make(uri, error="m").svg_inline(
        scale=5, border=2, dark="#000000", light="#ffffff", omitsize=True
    )
    return Markup(svg)  # noqa: S704 — разметку отдаёт segno из нашего же адреса otpauth


def _grouped(secret: str) -> str:
    return " ".join(secret[i : i + 4] for i in range(0, len(secret), 4))


def _clean_name(raw: Any, fallback: str) -> str:
    """Имя ключа: без управляющих знаков, сжатые пробелы, не длиннее предела."""
    текст = " ".join("".join(c for c in str(raw or "") if c.isprintable()).split())
    return текст[:MAX_PASSKEY_NAME] or fallback


def render_page(
    *,
    flash: Flash | None = None,
    codes: tuple[str, ...] | None = None,
    code: int = 200,
) -> Response:
    """Страница целиком — для GET и для ответа на любое действие экрана."""
    account = auth.current_account()
    if account is None:
        raise RuntimeError("«Вход и защита» без вошедшего: маршрут прошёл мимо заслона")
    conf: Settings = current_app.extensions["decimus_conf"]
    try:
        status = store.status_of(account.id)
        totp = store.totp_of(account.id) if status.totp_pending else None
    except DbError as exc:
        note_target_mismatch(exc)
        return make_response(
            render_template("settings/security.html", db_down=True, me=account), 503
        )
    setup = None
    if totp is not None and not totp.confirmed:
        setup = TotpSetup(
            qr_svg=_qr_svg(totp_uri(totp.secret, login=account.login)),
            secret_groups=_grouped(totp.secret),
        )
    ответ = make_response(
        render_template(
            "settings/security.html",
            db_down=False,
            me=account,
            status=status,
            setup=setup,
            flash=flash,
            codes=codes,
            fresh=is_fresh(account),
            required=is_required(account.role),
            enrolled=status.has_factor,
            passkeys_enabled=conf.webauthn_enabled,
            max_passkeys=MAX_PASSKEYS,
            base=f"{request.script_root}{SECURITY_PATH}",
            show_required=request.args.get("required") == "1" and not status.has_factor,
        ),
        code,
    )
    # Ключ приложения и резервные коды в ответе — не в кэш и не в историю.
    ответ.headers["Cache-Control"] = "no-store"
    return ответ


SECURITY_PATH = f"{section('settings').path}/security"


def _stale_response(*, json_body: bool) -> Response | tuple[Response, int]:
    if json_body:
        return jsonify(error="stale"), 403
    return render_page(flash=Flash("sf.sec.stale_refused", ok=False), code=403)


def install(app: Flask, conf: Settings) -> None:
    """Маршруты «Входа и защиты». Имена маршрутов перечислены в `second_step.ENROLL_ENDPOINTS`."""
    app.extensions["decimus_conf"] = conf
    party = party_of(conf)
    base = SECURITY_PATH

    def _me() -> Any:
        account = auth.current_account()
        if account is None:
            raise RuntimeError("«Вход и защита» без вошедшего: маршрут прошёл мимо заслона")
        return account

    @app.get(base, endpoint=SECURITY_ENDPOINT)
    def security_page() -> Response:
        return render_page()

    @app.post(f"{base}/relogin", endpoint="security_relogin")
    def security_relogin() -> Response:
        """Выйти и войти заново с возвратом сюда: свежий вход, включая вторую ступень."""
        refuse_foreign_origin()
        token = auth.current_session_token()
        close_session(token)
        ответ = redirect(url_for("login", next=SECURITY_PATH))
        ответ.delete_cookie(auth.COOKIE_NAME, path="/")
        return ответ

    @app.post(f"{base}/passkey/options", endpoint="security_passkey_options")
    def security_passkey_options() -> Response | tuple[Response, int]:
        refuse_foreign_origin()
        account = _me()
        if party is None:
            return jsonify(error="off"), 400
        if not is_fresh(account):
            return _stale_response(json_body=True)
        try:
            ключи = store.status_of(account.id).passkeys
            if len(ключи) >= MAX_PASSKEYS:
                return jsonify(error="limit"), 409
            параметры, вызов = webauthn_rp.registration_options(
                party,
                user_id=account.id,
                login=account.login,
                existing=tuple(k.credential_id for k in ключи),
            )
            store.store_challenge(
                auth.current_session_token(),
                purpose=store.PURPOSE_REGISTER,
                user_id=account.id,
                challenge=вызов,
            )
        except DbError as exc:
            note_target_mismatch(exc)
            return jsonify(error="db"), 503
        ответ = current_app.response_class(параметры, mimetype="application/json")
        ответ.headers["Cache-Control"] = "no-store"
        return ответ

    @app.post(f"{base}/passkey/register", endpoint="security_passkey_register")
    def security_passkey_register() -> Response | tuple[Response, int]:
        refuse_foreign_origin()
        account = _me()
        if party is None:
            return jsonify(error="off"), 400
        if not is_fresh(account):
            return _stale_response(json_body=True)
        тело = request.get_json(silent=True)
        if not isinstance(тело, dict) or not isinstance(тело.get("credential"), dict):
            return jsonify(error="bad"), 400
        try:
            вызов = store.take_challenge(
                auth.current_session_token(), purpose=store.PURPOSE_REGISTER, user_id=account.id
            )
            if вызов is None:
                return jsonify(error="challenge"), 400
            новое = webauthn_rp.verify_registration(
                party, credential=json.dumps(тело["credential"]), challenge=вызов
            )
            ключи = store.status_of(account.id).passkeys
            if len(ключи) >= MAX_PASSKEYS:
                return jsonify(error="limit"), 409
            имя = _clean_name(тело.get("name"), f"Key {len(ключи) + 1}")
            store.add_passkey(
                account.id,
                credential_id=новое.credential_id,
                public_key=новое.public_key,
                sign_count=новое.sign_count,
                transports=новое.transports,
                name=имя,
            )
        except webauthn_rp.PasskeyError:
            return jsonify(error="failed"), 400
        except DbError as exc:
            note_target_mismatch(exc)
            return jsonify(error="db"), 503
        logger.info("Вторая ступень: учётка %s добавила ключ доступа", account.login)
        return jsonify(ok=True, redirect=f"{request.script_root}{base}?added=passkey")

    @app.post(f"{base}/passkey/<passkey_id>/delete", endpoint="security_passkey_delete")
    def security_passkey_delete(passkey_id: str) -> Response | tuple[Response, int]:
        refuse_foreign_origin()
        account = _me()
        if not is_fresh(account):
            return _stale_response(json_body=False)
        try:
            исход = store.remove_passkey(account.id, passkey_id)
        except DbError as exc:
            note_target_mismatch(exc)
            return render_page(flash=Flash("sf.sec.db", ok=False), code=503)
        except ValueError:
            исход = store.MISSING
        return render_page(flash=_removal_flash(исход, "sf.pk.removed", "sf.pk.missing"))

    @app.post(f"{base}/totp/start", endpoint="security_totp_start")
    def security_totp_start() -> Response | tuple[Response, int]:
        refuse_foreign_origin()
        account = _me()
        if not is_fresh(account):
            return _stale_response(json_body=False)
        try:
            начато = store.begin_totp(account.id, new_totp_secret())
        except DbError as exc:
            note_target_mismatch(exc)
            return render_page(flash=Flash("sf.sec.db", ok=False), code=503)
        return render_page(flash=None if начато else Flash("sf.totp.exists", ok=False))

    @app.post(f"{base}/totp/confirm", endpoint="security_totp_confirm")
    def security_totp_confirm() -> Response | tuple[Response, int]:
        refuse_foreign_origin()
        account = _me()
        if not is_fresh(account):
            return _stale_response(json_body=False)
        try:
            строка = store.totp_of(account.id)
            цифры = normalize_totp_code(request.form.get("code") or "")
            шаг = (
                match_totp_step(строка.secret, цифры)
                if строка is not None and not строка.confirmed and цифры is not None
                else None
            )
            if шаг is None or not store.confirm_totp(account.id, step=шаг):
                return render_page(flash=Flash("sf.totp.bad", ok=False), code=400)
        except DbError as exc:
            note_target_mismatch(exc)
            return render_page(flash=Flash("sf.sec.db", ok=False), code=503)
        logger.info("Вторая ступень: учётка %s подключила приложение", account.login)
        return render_page(flash=Flash("sf.totp.saved", ok=True))

    @app.post(f"{base}/totp/remove", endpoint="security_totp_remove")
    def security_totp_remove() -> Response | tuple[Response, int]:
        refuse_foreign_origin()
        account = _me()
        if not is_fresh(account):
            return _stale_response(json_body=False)
        try:
            исход = store.remove_totp(account.id)
        except DbError as exc:
            note_target_mismatch(exc)
            return render_page(flash=Flash("sf.sec.db", ok=False), code=503)
        return render_page(flash=_removal_flash(исход, "sf.totp.removed", "sf.totp.removed"))

    @app.post(f"{base}/backup/generate", endpoint="security_backup_generate")
    def security_backup_generate() -> Response | tuple[Response, int]:
        refuse_foreign_origin()
        account = _me()
        if not is_fresh(account):
            return _stale_response(json_body=False)
        try:
            if not store.has_any(account.id):
                return render_page(flash=Flash("sf.codes.need_factor", ok=False), code=409)
            коды = new_backup_codes()
            store.replace_backup_codes(
                account.id,
                tuple(h for k in коды if (h := backup_code_hash(account.id, k)) is not None),
            )
        except DbError as exc:
            note_target_mismatch(exc)
            return render_page(flash=Flash("sf.sec.db", ok=False), code=503)
        logger.info("Вторая ступень: учётка %s выпустила резервные коды", account.login)
        return render_page(codes=коды)


def _removal_flash(исход: str, done_key: str, missing_key: str) -> Flash:
    if исход == store.LAST_FACTOR:
        return Flash("sf.sec.last_factor", ok=False)
    if исход == store.REMOVED:
        return Flash(done_key, ok=True)
    return Flash(missing_key, ok=False)
