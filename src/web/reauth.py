"""Свежий вход для действий, создающих долгоживущий доступ (аудит безопасности 12.10).

Одной украденной сессией нельзя выпустить себе 30-дневный токен MCP, привязать
свой Telegram, привязать или снять почту Google и разрешить подключение Claude:
эти права пережили бы выход и смену пароля. Поэтому такие действия требуют
входа в ЭТОЙ сессии не старше `MAX_AGE`; иначе — страница «Подтвердите вход»
(`/settings/confirm`) тем же способом, каким учётка входит: паролем или, у
учётки с почтой Google при включённом входе Google (D450), через Google.

Подтверждение не продлевает старую сессию, а заменяет её новой: прежняя
закрывается, новая открывается с текущим временем. Так «когда вошли» остаётся
одним полем базы (`web_sessions.issued_at`), а не вторым, которое надо держать
в согласии с первым.

После подтверждения человек возвращается туда, откуда его попросили: в «Настройки»
или на страницу согласия Claude. Действие в «Настройках» (токен Claude, ссылка
бота, уход к Google) после подтверждения ПАРОЛЕМ выполняется тут же, после
подтверждения через Google — после одной кнопки (D457): при отказе по свежести в подписанную
куку кладётся намерение — только название действия и учётка, ничего из формы;
подтверждение «заряжает» его, а выполняет его POST `/settings/continue` (кнопка
«Продолжить», проверка происхождения) тем же кодом, что кнопка, и снимает куку.
`GET /settings` — чистое чтение: изменение состояния на GET мог бы вызвать чужой
сайт, пока намерение заряжено. Незаряженное (вход обычным путём), чужое, поддельное или
просроченное намерение не выполняется. Снятие почты Google пароль берёт из формы,
а форму не храним, а «Разрешить» на согласии Claude — осознанное согласие:
оба возвращают к кнопке.

Попытки пароля считаются тем же счётчиком, что у входа: иначе подтверждение
было бы вторым входом для подбора.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from flask import Flask, current_app, make_response, redirect, render_template, request, url_for
from itsdangerous import BadSignature, URLSafeTimedSerializer
from werkzeug.wrappers import Response

from src.db.web_throttle import admit_attempt, note_success
from src.domain.tenants import HQ_TENANT, canonical_tenant

from .google_auth import GoogleIdentity, hq_domain_ok
from .google_link import nonce_for
from .origin import over_https, refuse_foreign_origin
from .remote import client_address

#: Сколько вход считается свежим для действий, создающих долгоживущий доступ.
#: D457: активного человека в пределах рабочего дня не переспрашиваем (было 15 минут).
MAX_AGE = timedelta(hours=12)

#: Кука намерения «после подтверждения сделать это», её жизнь и подпись (D457).
INTENT_COOKIE = "decimus_reauth_intent"
INTENT_TTL_SECONDS = 10 * 60
INTENT_SALT = "decimus-reauth-intent"
INTENT_SIGNER_KEY = "decimus_reauth_intent_signer"

#: Действия, которые выполняются само после подтверждения: без данных формы.
INTENT_ACTIONS = frozenset({"claude-token", "bot-link", "google-link"})

CONFIRM_PATH = "/settings/confirm"
CONFIRM_GOOGLE_PATH = "/settings/confirm/google"
CONFIRM_ENDPOINT = "reauth_confirm"

#: Вид метки в куке захода Google: подтверждение входа.
REAUTH_KIND = "reauth"

#: Куда можно вернуть после подтверждения: «Настройки», согласие OAuth и вкладка
#: «Подключения» и «Dodo IS» в «Администрировании» (ключ модели, D491, D639; ссылка Dodo IS, D641).
_BACK_PREFIXES = (
    "/settings#",
    "/settings?",
    "/oauth/authorize?",
    "/administration?tab=connections",
    "/administration?tab=dodois",
)


def is_fresh(account: object, *, now: datetime | None = None, max_age: timedelta = MAX_AGE) -> bool:
    """Сессия открыта не раньше `max_age` назад (по умолчанию `MAX_AGE`). Неизвестно когда — нет."""
    когда = getattr(account, "signed_in_at", None)
    if not isinstance(когда, datetime):
        return False
    сейчас = now or datetime.now(UTC)
    return сейчас - когда <= max_age


def safe_back(raw: str | None) -> str:
    """Путь возврата после подтверждения — только свои страницы; иначе «Настройки»."""
    if raw == "/settings":
        return raw
    if (
        raw
        and raw.startswith(_BACK_PREFIXES)
        and "\\" not in raw
        and all(знак.isprintable() for знак in raw)
        and not urlsplit(raw).netloc
        and not urlsplit(raw).scheme
    ):
        return raw
    return "/settings"


def require_fresh(
    back: str, action: str | None = None, *, max_age: timedelta = MAX_AGE
) -> Response | None:
    """`None` — вход свежий, действие можно делать; иначе — увод на подтверждение.

    `max_age` — строже общего окна для действий с секретами (ключи сервисов, D576: 10 минут).

    `action` — название действия из `INTENT_ACTIONS`: после подтверждения оно
    выполнится само (D457); без него человек нажмёт кнопку ещё раз.
    """
    from . import auth

    account = auth.current_account()
    if is_fresh(account, max_age=max_age):
        return None
    ответ = ask_confirm(back)
    if action is not None and account is not None:
        _set_intent(ответ, account, action, armed=False)
    return ответ


def _signer() -> URLSafeTimedSerializer:
    return current_app.extensions[INTENT_SIGNER_KEY]  # type: ignore[no-any-return]


def _set_intent(ответ: Response, account: object, action: str, *, armed: bool) -> None:
    if action not in INTENT_ACTIONS:
        raise ValueError(f"неизвестное намерение: {action}")
    ответ.set_cookie(
        INTENT_COOKIE,
        _signer().dumps({"a": action, "u": str(getattr(account, "id", "")), "armed": armed}),
        max_age=INTENT_TTL_SECONDS,
        httponly=True,
        # Lax, а не Strict: заряженную куку ставит ответ возврата от Google, и
        # следующий переход «Google -> Настройки» Strict-куку не принёс бы. Кука
        # ничего не запускает сама: действие — только POST с проверкой происхождения,
        # а кросс-сайтовый POST Lax-куку и так не несёт.
        samesite="Lax",
        secure=over_https(),
        path="/",
    )


def _read_intent(account: object) -> tuple[str, bool] | None:
    """Намерение из куки: действие и «заряжено ли». Чужое, битое, старое — `None`."""
    сырое = request.cookies.get(INTENT_COOKIE)
    if not сырое:
        return None
    try:
        содержимое = _signer().loads(сырое, max_age=INTENT_TTL_SECONDS)
    except BadSignature:
        return None
    if not isinstance(содержимое, dict):
        return None
    действие = содержимое.get("a")
    if (
        действие not in INTENT_ACTIONS
        or not getattr(account, "id", None)
        or содержимое.get("u") != str(account.id)  # type: ignore[attr-defined]
    ):
        return None
    return str(действие), содержимое.get("armed") is True


def arm_intent(ответ: Response, account: object, back: str) -> None:
    """Подтверждение прошло: заряжаем намерение этой же учётки, если возврат в «Настройки»."""
    найдено = _read_intent(account)
    if найдено is None or not (
        back == "/settings" or back.startswith(("/settings#", "/settings?"))
    ):
        drop_intent(ответ)
        return
    _set_intent(ответ, account, найдено[0], armed=True)


def pending_intent(account: object, back: str) -> str | None:
    """Намерение этой учётки (заряженное или нет) для выполнения прямо при подтверждении
    паролем: подпись, учётка и срок те же, возврат — только в «Настройки»."""
    найдено = _read_intent(account)
    if найдено is None or not (
        back == "/settings" or back.startswith(("/settings#", "/settings?"))
    ):
        return None
    return найдено[0]


def take_intent(account: object) -> str | None:
    """Заряженное намерение этой учётки при свежем входе; иначе `None`.

    Кука при этом НЕ снимается: это делает `POST /settings/continue` (`drop_intent`)
    на ответе, которым действие выполнено, — одноразовость держится на этом.
    """
    найдено = _read_intent(account)
    if найдено is None or not найдено[1] or not is_fresh(account):
        return None
    return найдено[0]


def drop_intent(ответ: Response) -> None:
    ответ.delete_cookie(INTENT_COOKIE, path="/")


def ask_confirm(back: str) -> Response:
    """Увести на «Подтвердите вход» с возвратом на `back`."""
    return redirect(url_for(CONFIRM_ENDPOINT, next=back))


def uses_google(account: object, google_enabled: bool) -> bool:
    """Учётка подтверждает вход через Google: с почтой паролем не входят (D450)."""
    return google_enabled and bool(getattr(account, "email", None))


def google_confirms(
    account: Any, identity: GoogleIdentity, *, state: str, hq_domains: frozenset[str]
) -> bool:
    """Google подтвердил ТУ ЖЕ учётку: её почта, подтверждена, этот заход, домен УК."""
    if not identity.email_verified or not account.email:
        return False
    if not identity.nonce or not hmac.compare_digest(
        identity.nonce.encode(), nonce_for(state).encode()
    ):
        return False
    if identity.email != str(account.email).strip().lower():
        return False
    if canonical_tenant(account.tenant) == HQ_TENANT and not hq_domain_ok(identity, hq_domains):
        return False
    return True


def install(
    app: Flask,
    *,
    stand: str,
    trusted_proxies: int,
    google_enabled: bool,
    rotate: Callable[..., Response],
    run_intent: Callable[[str], Any],
    begin_google: Callable[[str], Response],
    verify: Callable[[str, str], Any],
    secret_key: str,
) -> None:
    """Страница подтверждения входа.

    `rotate(account, back, arm=…)` меняет сессию на свежую, `run_intent(action)` выполняет
    намерение (то же, что кнопка), `begin_google(back)` уводит
    к Google, `verify(login, password)` — сверка пароля той же дверью, что у входа.
    """

    app.extensions[INTENT_SIGNER_KEY] = URLSafeTimedSerializer(
        secret_key, salt=INTENT_SALT, signer_kwargs={"digest_method": hashlib.sha256}
    )

    def _page(back: str, *, failed: bool = False, locked: int | None = None) -> str:
        from . import auth

        return render_template(
            "settings/confirm.html",
            back=back,
            via_google=uses_google(auth.current_account(), google_enabled),
            failed=failed,
            locked_minutes=locked,
        )

    @app.get(CONFIRM_PATH, endpoint=CONFIRM_ENDPOINT)
    def reauth_confirm() -> str:
        return _page(safe_back(request.args.get("next")), failed=request.args.get("failed") == "1")

    @app.post(CONFIRM_PATH)
    def reauth_confirm_password() -> Response | tuple[str, int]:
        from . import auth

        refuse_foreign_origin()
        back = safe_back(request.form.get("next"))
        account = auth.current_account()
        if account is None:
            raise RuntimeError("подтверждение без вошедшего: маршрут прошёл мимо заслона")
        if uses_google(account, google_enabled):
            return _page(back), 403
        адрес = client_address(trusted_proxies=trusted_proxies)
        попытка = admit_attempt(tenant=stand, address=адрес, login=account.login)
        if not попытка.admitted:
            ответ = make_response(_page(back, locked=попытка.verdict.retry_after_minutes), 429)
            ответ.headers["Retry-After"] = str(попытка.verdict.retry_after_seconds)
            return ответ
        сверено = verify(account.login, request.form.get("password") or "")
        if сверено is None or str(сверено.id) != str(account.id):
            return _page(back, failed=True), 401
        note_success(tenant=stand, login=account.login)
        действие = pending_intent(account, back)
        if действие is None:
            return rotate(account, back)
        # Пароль подтверждён POST'ом со своей страницы (проверка Origin выше): то,
        # что человек просил, выполняется здесь же (D457), пока прежняя сессия жива,
        # а ответ несёт куку новой. Кука намерения снимается этим же ответом —
        # повторная отправка подтверждения второй раз ничего не выпустит.
        ответ = make_response(run_intent(действие))
        for кука in rotate(account, back, arm=False).headers.getlist("Set-Cookie"):
            ответ.headers.add("Set-Cookie", кука)
        drop_intent(ответ)
        ответ.headers["Cache-Control"] = "no-store"
        return ответ

    @app.post(CONFIRM_GOOGLE_PATH)
    def reauth_confirm_google() -> Response:
        refuse_foreign_origin()
        return begin_google(safe_back(request.form.get("next")))
