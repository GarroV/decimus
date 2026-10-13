"""Вторая ступень входа: «Подтвердите вход» после Google или пароля (D463).

**Сессия выдаётся только после обеих ступеней.** Первая (Google или пароль) у человека
со вторым способом открывает не сессию, а «полупройденный вход» (`web_second_steps`):
строку на 5 минут, одноразовую, привязанную к браузеру подписанной кукой
`decimus_second_step`. Опознаёт сессию только `web_sessions`, а полупройденный вход знают
лишь маршруты этого модуля, поэтому он не открывает ни одного экрана: заслон
(`auth._guard`) на эту куку не смотрит вовсе. Вторая ступень — ключ доступа (Touch ID),
шестизначный код приложения или резервный код; после неё полупройденный вход гасится ОДНИМ
запросом (`consume_pending`) и открывается настоящая сессия.

**Админ и главный админ без второго способа** сюда не попадают: у них сессия обычная, но
`auth._guard` оставляет им только экран подключения (`ENROLL_ENDPOINTS`), пока способ не
подключён. Тот же заслон ловит и старую сессию, выданную до включения ступени.

**Попытки считаются отдельным ключом `2fa:<логин>`** тем же ограничителем, что и пароль
(`web_throttle`). Общий ключ с паролем был бы дырой: удачный пароль сбрасывает счётчик
логина, и перебирающий код чередовал бы «пароль — одна попытка кода» без предела. Сверх
этого полупройденный вход умирает после пяти неверных ответов.

**Ответ один на все осечки** («не подошло»): по различиям перебирающий узнавал бы, что
верно, а что нет.

Журнал входов: `second-step` с исходами `ok`, `bad-code`, `passkey-fail`, `backup-used`.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Any

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
from itsdangerous import BadSignature, URLSafeTimedSerializer
from werkzeug.wrappers import Response

from src.db import journals
from src.db import second_factor as store
from src.db.web_access import Account, OpenedSession, find_by_id, open_session
from src.db.web_throttle import admit_attempt, note_success
from src.domain.journal import (
    METHOD_SECOND_STEP,
    RESULT_BACKUP_USED,
    RESULT_BAD_CODE,
    RESULT_OK,
    RESULT_PASSKEY_FAIL,
    RESULT_RATE_LIMITED,
)
from src.domain.second_factor import (
    PENDING_TTL,
    backup_code_hash,
    is_required,
    match_totp_step,
    normalize_totp_code,
)

from . import journal as web_journal
from . import webauthn_rp
from .config import Settings
from .origin import over_https, refuse_foreign_origin
from .remote import client_address

STEP_PATH = "/login/second-step"
STEP_ENDPOINT = "second_step_page"
PENDING_COOKIE = "decimus_second_step"
PENDING_SALT = "decimus-second-step"
SIGNER_KEY = "decimus_second_step_signer"
BEGIN_KEY = "decimus_second_step_begin"

#: Адреса, открытые без сессии: их защищает кука полупройденного входа, а не заслон.
ENDPOINTS = frozenset(
    {
        STEP_ENDPOINT,
        "second_step_code",
        "second_step_passkey_options",
        "second_step_passkey_verify",
    }
)

#: Что доступно админу без второго способа: экран подключения, выход, статика и свои
#: безобидные чтения меню учётки. Остальное — мимо (`auth._guard`).
ENROLL_ENDPOINTS = frozenset(
    {
        "security_page",
        "security_relogin",
        "security_passkey_options",
        "security_passkey_register",
        "security_passkey_delete",
        "security_totp_start",
        "security_totp_confirm",
        "security_totp_remove",
        "security_backup_generate",
        "logout",
        "static",
        "settings_menu",
        "settings_avatar",
        "settings_lang",
    }
)

#: Ключ счётчика попыток второй ступени: отдельный от пароля (см. выше).
THROTTLE_PREFIX = "2fa:"


def must_enroll(account: Any) -> bool:
    """Админу или главному админу без второго способа доступен только экран подключения."""
    return is_required(str(account.role)) and not bool(getattr(account, "has_second_factor", True))


def throttle_key(login: str) -> str:
    return f"{THROTTLE_PREFIX}{login}"


def begin(account: Account, *, method: str, next_path: str | None) -> Response | None:
    """После первой ступени: `None` — второго способа нет, сессию открывать можно.

    Иначе — переход на «Подтвердите вход» с кукой полупройденного входа; сессии нет.
    """
    return current_app.extensions[BEGIN_KEY](account, method, next_path)  # type: ignore[no-any-return]


def party_of(conf: Settings) -> webauthn_rp.RelyingParty | None:
    """Домен и происхождение ключей доступа из настроек; не заданы — `None`."""
    if conf.webauthn_rp_id is None or conf.webauthn_origin is None:
        return None
    return webauthn_rp.RelyingParty(rp_id=conf.webauthn_rp_id, origin=conf.webauthn_origin)


def install(
    app: Flask,
    conf: Settings,
    *,
    remember: Callable[[Response, OpenedSession], Response],
    stand: str,
) -> None:
    """Маршруты второй ступени. `remember` кладёт сессионную куку — тот же, что у первой."""
    signer = URLSafeTimedSerializer(
        conf.secret_key, salt=PENDING_SALT, signer_kwargs={"digest_method": hashlib.sha256}
    )
    app.extensions[SIGNER_KEY] = signer
    max_age = int(PENDING_TTL.total_seconds())
    party = party_of(conf)

    def _set_cookie(response: Response, token: str) -> None:
        response.set_cookie(
            PENDING_COOKIE,
            signer.dumps(token),
            max_age=max_age,
            httponly=True,
            # Lax: ставится в ответ на возврат от Google (чужой переход), и Strict-куку
            # следующий шаг цепочки не принёс бы. Кука ничего не открывает сама.
            samesite="Lax",
            secure=over_https(),
            path="/",
        )

    def _drop_cookie(response: Response) -> Response:
        response.delete_cookie(PENDING_COOKIE, path="/")
        return response

    def _token() -> str | None:
        raw = request.cookies.get(PENDING_COOKIE)
        if not raw:
            return None
        try:
            return str(signer.loads(raw, max_age=max_age))
        except BadSignature:
            return None

    def _begin(account: Account, method: str, next_path: str | None) -> Response | None:
        if not store.has_any(account.id):
            return None
        token = store.open_pending(account.id, method=method, next_path=next_path)
        откуда, браузер = web_journal.login_origin(conf)
        # Первая ступень прошла, сессии нет: в журнале видно «пароль верный, дальше не пустили».
        journals.record_login(
            method=method,
            result=RESULT_OK,
            user_id=account.id,
            ip=откуда,
            user_agent=браузер,
        )
        ответ = redirect(url_for(STEP_ENDPOINT))
        _set_cookie(ответ, token)
        ответ.headers["Cache-Control"] = "no-store"
        return ответ

    app.extensions[BEGIN_KEY] = _begin

    def _live() -> tuple[str, store.Pending, Account] | None:
        """Токен, полупройденный вход и учётка; любое «нет» — `None`."""
        token = _token()
        if token is None:
            return None
        pending = store.find_pending(token)
        if pending is None:
            return None
        account = find_by_id(pending.user_id)
        if account is None:
            return None
        return token, pending, account

    def _page(
        token_status: store.Status,
        account: Account,
        *,
        failed: bool = False,
        locked_minutes: int | None = None,
        code: int = 200,
    ) -> Response:
        ответ = make_response(
            render_template(
                "login_second_step.html",
                failed=failed,
                locked_minutes=locked_minutes,
                has_passkeys=bool(token_status.passkeys) and party is not None,
                has_code=token_status.totp_confirmed or token_status.backup_left > 0,
                passkeys_off=bool(token_status.passkeys) and party is None,
                login=account.login,
            ),
            code,
        )
        ответ.headers["Cache-Control"] = "no-store"
        return ответ

    def _expired() -> Response:
        """Вход потерян: просрочен, погашен, мёртв от неудач, заморожена учётка, нет куки."""
        ответ = redirect(url_for("login", second_step="expired"))
        return _drop_cookie(ответ)

    def _failure(
        token: str, account: Account, *, result: str, ip: str | None, ua: str | None
    ) -> int:
        journals.record_login(
            method=METHOD_SECOND_STEP, result=result, user_id=account.id, ip=ip, user_agent=ua
        )
        return store.note_pending_failure(token)

    def _open(token: str, account: Account, *, result: str) -> Response | None:
        """Погасить полупройденный вход и открыть сессию. `None` — вход уже погашен/мёртв."""
        pending = store.consume_pending(token)
        if pending is None or pending.user_id != account.id:
            return None
        откуда, браузер = web_journal.login_origin(conf)
        session = open_session(account, ip=откуда, user_agent=браузер)
        journals.record_login(
            method=METHOD_SECOND_STEP,
            result=result,
            user_id=account.id,
            ip=откуда,
            user_agent=браузер,
            session_id=session.session_id,
        )
        note_success(tenant=stand, login=throttle_key(account.login))
        return remember(_drop_cookie(_after(pending.next_path)), session)

    def _after(next_path: str | None) -> Response:
        from .auth import safe_next

        путь = safe_next(next_path)
        if путь is None:
            return redirect(url_for("home"))
        return redirect(f"{request.script_root}{путь}")

    def _admit(account: Account) -> tuple[bool, int | None, int]:
        """Пустить ли попытку: (пустить, минут ожидания, секунд ожидания)."""
        адрес = client_address(trusted_proxies=conf.trusted_proxies)
        попытка = admit_attempt(tenant=stand, address=адрес, login=throttle_key(account.login))
        вердикт = попытка.verdict
        return попытка.admitted, вердикт.retry_after_minutes, вердикт.retry_after_seconds

    def _locked(
        account: Account, status: store.Status, minutes: int | None, seconds: int
    ) -> Response:
        откуда, браузер = web_journal.login_origin(conf)
        journals.record_failed_login(
            login=account.login,
            method=METHOD_SECOND_STEP,
            ip=откуда,
            user_agent=браузер,
            result=RESULT_RATE_LIMITED,
        )
        ответ = _page(status, account, locked_minutes=minutes, code=429)
        ответ.headers["Retry-After"] = str(seconds)
        return ответ

    @app.get(STEP_PATH, endpoint=STEP_ENDPOINT)
    def second_step_page() -> Response:
        вход = _live()
        if вход is None:
            return _expired()
        _, _pending, account = вход
        return _page(store.status_of(account.id), account)

    @app.post(f"{STEP_PATH}/code", endpoint="second_step_code")
    def second_step_code() -> Response:
        """Шесть цифр из приложения или резервный код."""
        refuse_foreign_origin()
        вход = _live()
        if вход is None:
            return _expired()
        token, _pending, account = вход
        status = store.status_of(account.id)
        допущена, минут, секунд = _admit(account)
        if not допущена:
            return _locked(account, status, минут, секунд)
        сырой = request.form.get("code") or ""
        результат = _check_code(account, status, сырой)
        if результат is not None:
            открыт = _open(token, account, result=результат)
            if открыт is not None:
                return open_response(открыт)
        откуда, браузер = web_journal.login_origin(conf)
        _failure(token, account, result=RESULT_BAD_CODE, ip=откуда, ua=браузер)
        if store.find_pending(token) is None:
            return _expired()
        return _page(status, account, failed=True, code=401)

    def open_response(response: Response) -> Response:
        response.headers["Cache-Control"] = "no-store"
        return response

    def _check_code(account: Account, status: store.Status, raw: str) -> str | None:
        """Верный ли код; вернуть исход журнала (`ok` / `backup-used`) или `None`."""
        цифры = normalize_totp_code(raw)
        if цифры is not None:
            if not status.totp_confirmed:
                return None
            строка = store.totp_of(account.id)
            if строка is None or not строка.confirmed:
                return None
            шаг = match_totp_step(строка.secret, цифры)
            if шаг is None or not store.accept_totp_step(account.id, step=шаг):
                return None
            return RESULT_OK
        отпечаток = backup_code_hash(account.id, raw)
        if отпечаток is not None and store.use_backup_code(account.id, отпечаток):
            return RESULT_BACKUP_USED
        return None

    @app.post(f"{STEP_PATH}/passkey/options", endpoint="second_step_passkey_options")
    def second_step_passkey_options() -> Response | tuple[Response, int]:
        refuse_foreign_origin()
        вход = _live()
        if вход is None or party is None:
            return jsonify(error="expired", login=url_for("login", second_step="expired")), 401
        token, _pending, account = вход
        ключи = store.status_of(account.id).passkeys
        if not ключи:
            return jsonify(error="none"), 400
        параметры, вызов = webauthn_rp.authentication_options(
            party, credential_ids=tuple(k.credential_id for k in ключи)
        )
        store.store_challenge(
            token, purpose=store.PURPOSE_AUTHENTICATE, user_id=account.id, challenge=вызов
        )
        ответ = current_app.response_class(параметры, mimetype="application/json")
        ответ.headers["Cache-Control"] = "no-store"
        return ответ

    @app.post(f"{STEP_PATH}/passkey/verify", endpoint="second_step_passkey_verify")
    def second_step_passkey_verify() -> Response | tuple[Response, int]:
        refuse_foreign_origin()
        вход = _live()
        if вход is None or party is None:
            return jsonify(error="expired", login=url_for("login", second_step="expired")), 401
        token, _pending, account = вход
        допущена, _, секунд = _admit(account)
        if not допущена:
            ответ = jsonify(error="locked")
            ответ.headers["Retry-After"] = str(секунд)
            return ответ, 429
        откуда, браузер = web_journal.login_origin(conf)
        try:
            session_response = _verify_passkey(party, token, account)
        except webauthn_rp.PasskeyError:
            session_response = None
        if session_response is None:
            _failure(token, account, result=RESULT_PASSKEY_FAIL, ip=откуда, ua=браузер)
            if store.find_pending(token) is None:
                return jsonify(error="expired", login=url_for("login", second_step="expired")), 401
            return jsonify(error="failed"), 401
        # Куку сессии и увод несёт сам ответ: браузер идёт на `redirect` после `ok`.
        ответ = make_response(jsonify(ok=True, redirect=session_response.headers["Location"]))
        for кука in session_response.headers.getlist("Set-Cookie"):
            ответ.headers.add("Set-Cookie", кука)
        ответ.headers["Cache-Control"] = "no-store"
        return ответ

    def _verify_passkey(
        rp: webauthn_rp.RelyingParty, token: str, account: Account
    ) -> Response | None:
        сырое = request.get_data(as_text=True)
        номер = webauthn_rp.credential_id_of(сырое)
        найден = store.passkey_by_credential(номер)
        # Ключ обязан принадлежать ЭТОМУ человеку: чужой ключ первую ступень не закрывает.
        if найден is None or найден[1] != account.id:
            # Вызов всё равно снимается: попытка потрачена.
            store.take_challenge(token, purpose=store.PURPOSE_AUTHENTICATE, user_id=account.id)
            return None
        ключ = найден[0]
        вызов = store.take_challenge(token, purpose=store.PURPOSE_AUTHENTICATE, user_id=account.id)
        if вызов is None:
            return None
        итог = webauthn_rp.verify_authentication(
            rp,
            credential=сырое,
            challenge=вызов,
            public_key=ключ.public_key,
            sign_count=ключ.sign_count,
        )
        if not store.touch_passkey(
            ключ.id, old_count=ключ.sign_count, new_count=итог.new_sign_count
        ):
            return None
        return _open(token, account, result=RESULT_OK)
