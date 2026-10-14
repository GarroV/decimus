"""Вход в админку: форма, сессия в подписанной куке, выход (T323, D155).

**Заслон стоит на ВСЕХ маршрутах разом, а не на каждом по отдельности.** Он
повешен на `before_request`, поэтому новый экран закрыт с того мгновения, как
появился, и закрыть его не забудут: забыть можно то, что делаешь руками на
каждом маршруте. Открыт ровно один список — `OPEN_ENDPOINTS`, и он назван
здесь явно, чтобы дырку было видно глазами в одной строке, а не собирать её по
декораторам всего приложения.

**Кука подписана, а сессия живёт в базе — нужно и то и другое.** Подпись
отвечает на вопрос «мы это выдавали», база — на вопрос «это ещё действует».
Одной подписи мало: выход тогда прекращал бы доступ ровно в том браузере, где
нажали кнопку, а снятая копия куки работала бы до конца срока. Одной базы мало
затем, что без подписи каждая подделанная строка в куке стоила бы похода в
базу.

**В куке едет не то, что лежит в базе.** В браузере — подписанный токен, в
базе — его отпечаток SHA-256. Украденная база не даёт войти ни под кем.

**Пароль подбирать дорого (T325, T328).** Попытки считаются по адресу и по
логину (`src/db/web_throttle.py`), и запертая попытка не доходит до сверки
пароля вовсе. Порядок вызовов здесь важен и держится двумя строками: заявка
(`admit_attempt`) ДО `authenticate` — она же и записывает попытку, — и забыть
счётчик при удаче. Забыть последнее — значит запирать людей, которые давно
вошли. Заявка и запись слиты в одну операцию не для красоты: врозь они
пропускали мимо порога столько лишних параллельных попыток, сколько у сервера
потоков.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

from flask import Flask, current_app, g, make_response, redirect, render_template, request, url_for
from itsdangerous import BadSignature, URLSafeTimedSerializer
from werkzeug.wrappers import Response

from src.db import journals, web_own_profile
from src.db.errors import DbError, SecondStepRequiredError
from src.db.reach import Reach, reach_of
from src.db.space import enter_space, leave_space
from src.db.web_access import (
    SESSION_TTL,
    Account,
    OpenedSession,
    authenticate,
    close_session,
    find_by_email,
    open_session,
    resolve_session,
)
from src.db.web_throttle import Verdict, admit_attempt, note_success
from src.domain.journal import (
    METHOD_GOOGLE,
    METHOD_PASSWORD,
    RESULT_OK,
    RESULT_RATE_LIMITED,
    RESULT_REFUSED,
)
from src.domain.tenants import HQ_TENANT, canonical_tenant

from . import google_link, google_profile, oauth, reauth, second_step, swarm_api, walk_auth
from . import journal as web_journal
from .config import Settings
from .google_auth import (
    FRONT_MARKER_HEADER,
    GoogleAuthError,
    GoogleIdentity,
    GoogleSettings,
    authorization_url,
    exchange_code,
    for_request,
    hq_domain_ok,
    load_google_settings,
    load_hq_domains,
    new_state,
)
from .origin import over_https, refuse_foreign_origin
from .remote import client_address

LOGIN_PATH = "/login"
LOGOUT_PATH = "/logout"

#: Вход через учётку Google (T332). Путь возврата обязан совпадать побуквенно
#: с тем, что вписано в консоли Google, иначе вход падает `redirect_uri_mismatch`.
GOOGLE_START_PATH = "/login/google"
GOOGLE_CALLBACK_PATH = "/auth/google/callback"

#: Кука с меткой захода живёт минуты: столько идёт согласие у Google. Дольше —
#: и украденная метка остаётся годной вместе с ней.
GOOGLE_STATE_COOKIE = "dodo_audit_google_state"
GOOGLE_STATE_SALT = "google-state"
GOOGLE_STATE_TTL_SECONDS = 600

#: Кука-подсказка: почта, которой человек успешно входил через Google. Это не
#: сессия и не доступ — только `login_hint`, чтобы Google не спрашивал аккаунт
#: заново. Выход её не стирает; стирает отказ в допуске (чтобы окно выбора вернулось).
GOOGLE_HINT_COOKIE = "dodo_audit_google_hint"
GOOGLE_HINT_TTL_SECONDS = 180 * 24 * 3600
GOOGLE_HINT_MAX_LENGTH = 254

#: Где в `app.extensions` лежит начало привязки почты Google из «Настроек».
GOOGLE_LINK_KEY = "decimus_google_link"

#: Имя куки. Своё, а не `session`: рядом на той же машине живут другие стенды,
#: и одноимённая кука соседа затирала бы нашу на общем хосте.
COOKIE_NAME = "dodo_audit_session"

#: Подпись отделена своей солью от любых других подписей этого ключа. Без неё
#: строка, подписанная для другой цели тем же ключом, годилась бы как кука.
COOKIE_SALT = "web-session"

#: ЕДИНСТВЕННОЕ, что открыто без опознания.
#:
#: `login` — иначе вход уводил бы на вход. `static` — это дизайн-система
#: (CSS и шрифты): форма входа обязана быть одетой, а о данных стенда эти
#: файлы не рассказывают ничего. Как только в статику попадёт хоть что-то про
#: данные, её место здесь придётся пересмотреть — поэтому список короткий и
#: лежит на виду.
#:
#: `walk_page` и `walk_data` — мини-апп обхода в Telegram (#418, `walk.py`):
#: у аудитора нет учётки админки, его опознаёт подпись Telegram, а не кука.
#:
#: `swarm_api_*` — API чтения для Swarm (#567, D387): опознаёт сервисный токен
#: из `api.tokens` по отпечатку (`swarm_api._authorize`, D388), а не кука; без
#: живого токена с нужным правом каждый адрес отвечает 401/403/429.
#:
#: `oauth_*` (кроме согласия) — метаданные, регистрация клиента и выдача
#: токенов OAuth (D417, `oauth.py`): их зовёт сервер Claude, а не браузер
#: вошедшего; сами они держатся PKCE и одноразовым кодом. Согласие
#: (`oauth_authorize`) здесь НЕ стоит — оно требует входа.
OPEN_ENDPOINTS = (
    frozenset({"login", "static", "google_start", "google_callback"})
    | walk_auth.ENDPOINTS
    | swarm_api.ENDPOINTS
    | oauth.ENDPOINTS
    | second_step.ENDPOINTS
)


#: Куда можно вернуть после входа (D417, D465): на любую свою страницу — путь
#: внутри приложения. Произвольный `next` — открытый редирект: ссылка «войдите в
#: decimus» уводила бы после входа на чужой сайт под видом своего.
def safe_next(raw: str | None) -> str | None:
    """Путь возврата после входа — или `None`, если он не путь внутри приложения.

    Принимается только путь ВНУТРИ приложения (без префикса площадки — его
    добавляет `request.script_root` при редиректе): ровно одна ведущая «/»,
    без схемы и хоста, без «//» и обратной косой черты, которые браузеры читают
    как начало чужого хоста, без управляющих знаков и без сегментов «.» и «..».
    """
    if not raw or not raw.startswith("/") or raw.startswith("//"):
        return None
    if "\\" in raw or any(not знак.isprintable() for знак in raw):
        return None
    части = urlsplit(raw)
    if части.scheme or части.netloc or части.fragment:
        return None
    if any(сегмент in (".", "..") for сегмент in части.path.split("/")):
        return None
    return raw


def after_login(raw: str | None) -> Response:
    """Куда уйти после входа: туда, откуда выбросило (свой путь), иначе — на главную."""
    путь = safe_next(raw)
    if путь is None:
        return redirect(url_for("home"))
    return redirect(f"{request.script_root}{путь}")


#: Ключ в `g`, под которым живёт вошедший на время запроса.
CURRENT = "account"

#: Ключ в `g` для токена сессии этого запроса: смена своего пароля (#324)
#: предъявляет базе ИМЕННО его — строку учётки выбирает живая сессия, а не
#: поле формы.
SESSION_TOKEN = "session_token"  # noqa: S105 — имя ключа в `g`, а не токен


def current_account() -> Account | None:
    """Кто сейчас на странице. `None` — никого, и до страницы дело не дошло."""
    return getattr(g, CURRENT, None)


#: Где в `app.extensions` лежит «настроен ли вход через Google» (D468).
GOOGLE_ENABLED_KEY = "decimus_google_enabled"

#: Где в `app.extensions` лежит тенант, по которому ведётся счётчик попыток.
THROTTLE_KEY = "decimus_throttle_tenant"


def throttle_tenant() -> str:
    """Тенант счётчика попыток — тот же, что у формы входа (T325, #324).

    Форма смены своего пароля сверяет текущий пароль и обязана считать
    попытки в ТОМ ЖЕ счётчике, что и вход: иначе она стала бы вторым входом
    для подбора. Источник один — `install`, второго здесь не заводится.
    """
    return str(current_app.extensions[THROTTLE_KEY])


def current_session_token() -> str:
    """Токен сессии вошедшего — из куки этого запроса, сверенный заслоном.

    Без вошедшего — ошибка кода: маршрут прошёл мимо заслона.
    """
    токен = getattr(g, SESSION_TOKEN, None)
    if not токен:
        raise RuntimeError(
            "current_session_token() вызван без вошедшего: маршрут прошёл мимо заслона"
        )
    return str(токен)


#: Ключ охвата вошедшего в `g`: страны читаются из базы один раз на запрос.
REACH = "reach"

#: Ключ в `g` метки пространства вошедшего (`src/db/space.py`): снимается на
#: выходе из запроса, чтобы не достаться следующему на том же потоке.
SPACE_MARK = "space_mark"


def begin_google_link() -> Response:
    """Увести вошедшего к Google привязать почту к СВОЕЙ учётке (D447).

    Само начало живёт в `install` — рядом с подписью метки и реквизитами
    Google, которыми пользуется и вход: метка, кука и адрес возврата у двух
    заходов одни, различает их вид метки (`google_link.LINK_KIND`).
    """
    return current_app.extensions[GOOGLE_LINK_KEY]()  # type: ignore[no-any-return]


def current_tenant() -> str:
    """Пространство вошедшего — для записи (D283).

    Без вошедшего — ошибка кода, а не «покажем УК»: маршрут, дошедший сюда без
    человека, прошёл мимо заслона, и молчаливый тенант по умолчанию спрятал бы это.
    """
    account = current_account()
    if account is None:
        raise RuntimeError("current_tenant() вызван без вошедшего: маршрут прошёл мимо заслона")
    return canonical_tenant(account.tenant)


def is_own(tenant_code: str) -> bool:
    """Запись принадлежит пространству вошедшего — писать можно только такую (D283)."""
    return canonical_tenant(tenant_code) == current_tenant()


def current_reach() -> Reach:
    """Охват вошедшего — для чтения (D283, D289). Считается один раз на запрос."""
    охват = getattr(g, REACH, None)
    if охват is None:
        охват = reach_of(current_tenant())
        setattr(g, REACH, охват)
    return охват


def install(app: Flask, conf: Settings) -> None:
    """Повесить заслон и зарегистрировать вход с выходом."""
    signer = URLSafeTimedSerializer(
        conf.secret_key, salt=COOKIE_SALT, signer_kwargs={"digest_method": hashlib.sha256}
    )
    max_age = int(SESSION_TTL.total_seconds())
    # Счётчик попыток ведётся по тенанту СТЕНДА: до входа пространство
    # человека неизвестно, а счётчик — защита от перебора, не граница.
    рубеж = conf.tenant
    app.extensions[THROTTLE_KEY] = рубеж

    def token_of_request() -> str | None:
        """Токен из куки, если подпись наша и не просрочена. Иначе — ничего."""
        подписанное = request.cookies.get(COOKIE_NAME)
        if not подписанное:
            return None
        try:
            return str(signer.loads(подписанное, max_age=max_age))
        except BadSignature:
            # Подделанная или просроченная подпись — это «куки нет», а не
            # отказ страницей: человеку в таком положении нужна форма входа.
            return None

    def remember(response: Response, session: OpenedSession) -> Response:
        """Положить куку. Срок берётся у САМОЙ СЕССИИ, а не считается заново.

        Браузер и база обязаны говорить об одном и том же сроке. Посчитанный
        здесь второй раз, он разошёлся бы с записанным при любой разнице часов,
        и кука пережила бы сессию (или наоборот) — а разбираться в этом пришлось
        бы по жалобе «меня выкидывает».
        """
        response.set_cookie(
            COOKIE_NAME,
            signer.dumps(session.token),
            expires=session.expires_at,
            httponly=True,
            samesite="Lax",
            secure=over_https(),
            path="/",
        )
        return response

    second_step.install(app, conf, remember=remember, stand=рубеж)

    @app.errorhandler(SecondStepRequiredError)
    def _second_step_required(_: SecondStepRequiredError) -> Response:
        """Путь входа попытался выдать полную сессию без второй ступени: на вход, без куки."""
        ответ = redirect(url_for("login", second_step="expired"))
        ответ.delete_cookie(COOKIE_NAME, path="/")
        return ответ

    @app.before_request
    def _guard() -> Response | None:
        """Ни одна страница админки не отдаётся неопознанному.

        Сессия сверяется НА КАЖДОМ запросе, а не запоминается на входе: выход
        и отключение учётки обязаны действовать немедленно, а снятый однажды
        ответ — это ровно тот способ, которым «немедленно» превращается в
        «когда-нибудь». Цена — одно обращение по уникальному индексу.
        """
        if request.endpoint in OPEN_ENDPOINTS:
            return None
        token = token_of_request()
        account = resolve_session(token) if token else None
        if account is None:
            if request.method == "GET":
                # Сессия истекла на открытой странице (согласие OAuth, карточка в
                # панели реестра): на вход и обратно сюда, а не на главную (D465).
                # Только чтение: на POST-адрес обратно по GET не вернуться.
                return redirect(url_for("login", next=request.full_path.rstrip("?")))
            return redirect(url_for("login"))
        # Админ без второго способа (D463) пользуется только подключением способа: пока
        # он не подключён, остальное закрыто — и для сессии, выданной до включения ступени.
        if (
            second_step.must_enroll(account)
            and request.endpoint not in second_step.ENROLL_ENDPOINTS
        ):
            if request.method == "GET":
                return redirect(url_for("security_page", required="1"))
            return make_response("", 403)
        setattr(g, CURRENT, account)
        setattr(g, SESSION_TOKEN, token)
        # Пространство вошедшего — и базе (F-037): политики роли приложения
        # отдают по нему, даже если запрос маршрута забыл условие охвата.
        setattr(g, SPACE_MARK, enter_space(account.tenant))
        return None

    @app.teardown_request
    def _снять_пространство(_exc: BaseException | None) -> None:
        метка = g.pop(SPACE_MARK, None)
        if метка is not None:
            leave_space(метка)

    def заперто(приговор: Verdict) -> Response:
        """Ответ запертому: та же форма, но со сроком и без сверки пароля.

        Код 429, а не 401: «не подошло» и «больше не принимаем» — разные
        ответы, и второй обязан быть виден и человеку на экране, и тому, кто
        потом будет разбирать журнал площадки. `Retry-After` ставится тем же
        числом, что напечатано человеку: два источника одного срока разъехались
        бы при первой же правке шага.
        """
        ответ = make_response(
            render_template(
                "login.html",
                failed=False,
                locked_minutes=приговор.retry_after_minutes,
                next_path=safe_next(request.form.get("next")),
            ),
            429,
        )
        ответ.headers["Retry-After"] = str(приговор.retry_after_seconds)
        return ответ

    # Реквизиты Google читаются один раз: от них зависят и вход через Google, и
    # то, закрыт ли пароль учёткам с привязанной почтой.
    google = load_google_settings()
    hq_domains = load_hq_domains()

    @app.route(LOGIN_PATH, methods=("GET", "POST"), endpoint="login")
    def login() -> str | Response | tuple[str, int]:
        if request.method != "POST":
            return render_template(
                "login.html",
                failed=False,
                locked_minutes=None,
                second_expired=request.args.get("second_step") == "expired",
                next_path=safe_next(request.args.get("next")),
            )
        refuse_foreign_origin()
        имя = request.form.get("login") or ""
        адрес = client_address(trusted_proxies=conf.trusted_proxies)
        # ОДНИМ движением: пустить ли к сверке пароля и записать саму попытку.
        # Раздельные «спросить» и «записать» пропускали мимо порога столько
        # лишних параллельных попыток, сколько у сервера потоков (T328). Сверка
        # пароля идёт ПОСЛЕ: смысл ограничителя в том, что запертый не доходит
        # до дорогой части вовсе — ни до scrypt, ни до базы учёток.
        попытка = admit_attempt(tenant=рубеж, address=адрес, login=имя)
        откуда, браузер = web_journal.login_origin(conf)
        if not попытка.admitted:
            journals.record_failed_login(
                login=имя,
                method=METHOD_PASSWORD,
                ip=откуда,
                user_agent=браузер,
                result=RESULT_RATE_LIMITED,
            )
            return заперто(попытка.verdict)
        account = authenticate(имя, request.form.get("password") or "")
        if account is not None and google is not None and account.email:
            # Учётка с привязанной почтой Google паролем не входит: пароль по
            # дороге проходит через фронт и прокси, Google — нет. Отказ стоит
            # ПОСЛЕ сверки пароля: до неё он рассказал бы любому, у кого какой
            # вход. Аварийный путь — снять привязку командой обслуживания
            # (`tools/web_user.py email <логин>`, docs/12-web-admin.md).
            journals.record_login(
                method=METHOD_PASSWORD,
                result=RESULT_REFUSED,
                user_id=account.id,
                ip=откуда,
                user_agent=браузер,
            )
            return render_template(
                "login.html",
                failed=False,
                use_google=True,
                locked_minutes=None,
                next_path=safe_next(request.form.get("next")),
            ), 403
        if account is None:
            if попытка.verdict.locked:
                journals.record_failed_login(
                    login=имя,
                    method=METHOD_PASSWORD,
                    ip=откуда,
                    user_agent=браузер,
                    result=RESULT_RATE_LIMITED,
                )
                return заперто(попытка.verdict)
            journals.record_failed_login(
                login=имя, method=METHOD_PASSWORD, ip=откуда, user_agent=браузер
            )
            # Один и тот же отказ на «нет такого логина» и «пароль не тот»:
            # иначе форма сама рассказывает перебором, кто здесь заведён.
            # Введённое обратно на страницу не возвращается — среди него
            # пароль, и он уехал бы в разметку, а оттуда в кэш и в снимок
            # экрана.
            страница = render_template(
                "login.html",
                failed=True,
                locked_minutes=None,
                next_path=safe_next(request.form.get("next")),
            )
            return страница, 401
        note_success(tenant=рубеж, login=имя)
        # Первая ступень пройдена. Есть второй способ — сессии пока нет (D463).
        вторая = second_step.begin(
            account, method=METHOD_PASSWORD, next_path=safe_next(request.form.get("next"))
        )
        if вторая is not None:
            return вторая
        session = open_session(account, ip=откуда, user_agent=браузер)
        journals.record_login(
            method=METHOD_PASSWORD,
            result=RESULT_OK,
            user_id=account.id,
            ip=откуда,
            user_agent=браузер,
            session_id=session.session_id,
        )
        return remember(after_login(request.form.get("next")), session)

    state_signer = URLSafeTimedSerializer(
        conf.secret_key, salt=GOOGLE_STATE_SALT, signer_kwargs={"digest_method": hashlib.sha256}
    )

    # То же знание — для маршрутов, которым нужен признак без шаблона (меню учётки).
    app.extensions[GOOGLE_ENABLED_KEY] = google is not None

    @app.context_processor
    def _вход_через_google_доступен() -> dict[str, bool]:
        """Одно место на все страницы: есть ли у стенда реквизиты Google.

        Через процессор контекста, а не аргументом render_template: форму
        входа рисуют три разных пути (GET, отказ пароля, отказ возврата), и
        забытый аргумент в одном из них убрал бы кнопку молча.
        """
        return {"google_enabled": google is not None}

    @app.get(GOOGLE_START_PATH, endpoint="google_start")
    def google_start() -> Response:
        """Увести к Google за согласием. Реквизитов нет — возвращаем на форму.

        Не 404 и не ошибка: стенд без реквизитов работает паролем, и человек,
        ткнувший в кнопку по старой памяти, должен увидеть форму входа, а не
        поломку.
        """
        if google is None:
            return redirect(url_for("login"))
        метка = new_state()
        ответ = redirect(
            authorization_url(
                _google_here(google), state=метка, login_hint=_подсказка_google(request.cookies)
            )
        )
        # Метка кладётся В КУКУ, а не в память процесса: стенд может работать
        # несколькими воркерами, и возврат придёт не обязательно в тот, что
        # уводил. Туда же — путь возврата после входа (D417): в подписанной
        # куке его не подменить, а через Google он бы не доехал.
        ответ.set_cookie(
            GOOGLE_STATE_COOKIE,
            state_signer.dumps({"state": метка, "next": safe_next(request.args.get("next"))}),
            max_age=GOOGLE_STATE_TTL_SECONDS,
            httponly=True,
            samesite="Lax",
            secure=over_https(),
            path="/",
        )
        return ответ

    @app.get(GOOGLE_CALLBACK_PATH, endpoint="google_callback")
    def google_callback() -> str | Response | tuple[str, int]:
        """Возврат от Google: сверить метку, обменять код, найти своего.

        Порядок проверок не случаен. Метка сверяется ДО обращения к Google:
        иначе чужая страница приводила бы нас к обмену своего кода, то есть
        тратила бы наш запрос и открывала бы сессию чужим аккаунтом в браузере
        человека.
        """
        if google is None:
            return redirect(url_for("login"))

        отказано = отказ_входа()
        подписанная = request.cookies.get(GOOGLE_STATE_COOKIE)
        пришедшая = request.args.get("state") or ""
        if not подписанная or not пришедшая:
            return отказано
        try:
            содержимое = state_signer.loads(подписанная, max_age=GOOGLE_STATE_TTL_SECONDS)
        except BadSignature:
            return отказано
        # Кука прежнего вида — одна метка строкой; нынешнего — метка и путь возврата.
        if isinstance(содержимое, dict):
            ожидаемая, вернуться = содержимое.get("state") or "", содержимое.get("next")
        else:
            ожидаемая, вернуться = содержимое, None
        # Сравнение постоянного времени: обычное `==` на строках отвечает тем
        # быстрее, чем раньше расходятся байты, и по этому времени метку
        # подбирают.
        # Сравнение В БАЙТАХ, а не в строках: `compare_digest` на строках с
        # не-ASCII падает TypeError, и подделанная метка с кириллицей давала бы
        # 500 вместо отказа. Поймано тестом, а не в бою.
        if not hmac.compare_digest(str(ожидаемая).encode(), пришедшая.encode()):
            return отказано

        # Заход «привязать почту» из «Настроек» (D447): тот же клиент и тот же
        # адрес возврата, своя ветка. Метка уже сверена выше — общим кодом.
        if isinstance(содержимое, dict) and содержимое.get("kind") == google_link.LINK_KIND:
            return очистить_метку(_вернуть_привязку(google, str(ожидаемая)))
        # Подтверждение входа перед действием, создающим долгоживущий доступ.
        if isinstance(содержимое, dict) and содержимое.get("kind") == reauth.REAUTH_KIND:
            назад = reauth.safe_back(str(содержимое.get("next") or ""))
            return очистить_метку(_вернуть_подтверждение(google, str(ожидаемая), назад))

        # `error=access_denied` приходит, когда человек сам отказался в окне
        # согласия. Это не поломка: возвращаем на форму без красного.
        if request.args.get("error"):
            return очистить_метку(redirect(url_for("login")))

        код = request.args.get("code") or ""
        if not код:
            return отказано

        try:
            кто = exchange_code(_google_here(google), code=код)
        except GoogleAuthError:
            return отказано

        # Второй заслон на подтверждённость почты. Первый стоит в разборе
        # токена (`google_auth.identity_from_id_token`), и обычно этого хватает
        # — но `GoogleIdentity` несёт признак с собой, а маршрут его
        # игнорировал. Появится завтра второй путь получения личности (другой
        # провайдер, кеш, тест-двойник) — и неподтверждённая почта пройдёт
        # сюда молча. Проверка стоит строки, пропуск стоит чужого входа.
        if not кто.email_verified:
            return отказ_входа(забыть_подсказку=True)

        # ВОТ ЗДЕСЬ круг допущенных: Google подтвердил владение почтой и не
        # более того. Незнакомая почта получает отказ, а не заводит учётку —
        # иначе круг допущенных задавал бы Google, а не владелец.
        откуда, браузер = web_journal.login_origin(conf)
        account = find_by_email(кто.email)
        if account is None:
            journals.record_failed_login(
                email=кто.email, method=METHOD_GOOGLE, ip=откуда, user_agent=браузер
            )
            return отказ_входа(забыть_подсказку=True)
        # Учётка УК — только из домена компании (D430, F-028): совпавшая почта
        # без `hd` компании — это аккаунт, заведённый на чужой адрес, а не
        # сотрудник. Партнёров проверка не касается: они входят по почтам из
        # списка своего пространства, без домена.
        if canonical_tenant(account.tenant) == HQ_TENANT and not hq_domain_ok(кто, hq_domains):
            # В журнал — пришедший домен организации, не почта: по нему видно,
            # что дописать в GOOGLE_HQ_DOMAINS, если отказали своему.
            current_app.logger.warning(
                "вход через Google: домен организации %r не в GOOGLE_HQ_DOMAINS",
                кто.hosted_domain,
            )
            journals.record_login(
                method=METHOD_GOOGLE,
                result=RESULT_REFUSED,
                user_id=account.id,
                ip=откуда,
                user_agent=браузер,
            )
            return отказ_входа(забыть_подсказку=True)

        note_success(tenant=рубеж, login=account.login)
        вторая = second_step.begin(account, method=METHOD_GOOGLE, next_path=вернуться)
        if вторая is not None:
            return запомнить_подсказку(очистить_метку(вторая), кто.email)
        session = open_session(account, ip=откуда, user_agent=браузер)
        journals.record_login(
            method=METHOD_GOOGLE,
            result=RESULT_OK,
            user_id=account.id,
            ip=откуда,
            user_agent=браузер,
            session_id=session.session_id,
        )
        # Имя и фото из Google (D468) — после открытия сессии и мимо исхода
        # входа: сбой здесь не отнимает у человека вход.
        google_profile.remember(session.token, кто)
        return запомнить_подсказку(
            очистить_метку(remember(after_login(вернуться), session)), кто.email
        )

    def _начать_привязку() -> Response:
        """Метка за сессией в базе и в куке, затем увод к Google с `nonce`.

        Только по POST со своей страницы (маршрут в `settings_screen`), поэтому
        чужая страница не начнёт привязку в браузере человека. Метка пишется в
        базу за ЭТОЙ сессией: возврат в другой сессии её не погасит.
        """
        if google is None:
            return redirect(url_for("settings_page"))
        метка = new_state()
        try:
            записана = web_own_profile.begin_google_link(
                current_session_token(), state=метка, ttl_seconds=GOOGLE_STATE_TTL_SECONDS
            )
        except DbError:
            current_app.logger.exception("привязка Google: метку записать не удалось")
            записана = False
        if not записана:
            return google_link.back_to_settings("db")
        ответ = redirect(
            authorization_url(_google_here(google), state=метка, nonce=google_link.nonce_for(метка))
        )
        ответ.set_cookie(
            GOOGLE_STATE_COOKIE,
            state_signer.dumps({"state": метка, "kind": google_link.LINK_KIND}),
            max_age=GOOGLE_STATE_TTL_SECONDS,
            httponly=True,
            samesite="Lax",
            secure=over_https(),
            path="/",
        )
        return ответ

    app.extensions[GOOGLE_LINK_KEY] = _начать_привязку

    def _обновить_сессию(account: Account, назад: str, *, arm: bool = True) -> Response:
        """Подтверждённый вход: прежняя сессия закрывается, новая — свежая (`reauth`)."""
        прежний = token_of_request()
        новая = open_session(
            account, second_step=bool(getattr(account, "passed_second_step", False))
        )
        if прежний:
            close_session(прежний)
        ответ = redirect(f"{request.script_root}{назад}")
        if arm:
            reauth.arm_intent(ответ, account, назад)
        return remember(ответ, новая)

    def _начать_подтверждение(назад: str) -> Response:
        """Увод к Google подтвердить вход; метка и путь возврата — в подписанной куке."""
        if google is None:
            return redirect(url_for(reauth.CONFIRM_ENDPOINT, next=назад))
        метка = new_state()
        ответ = redirect(
            authorization_url(_google_here(google), state=метка, nonce=google_link.nonce_for(метка))
        )
        ответ.set_cookie(
            GOOGLE_STATE_COOKIE,
            state_signer.dumps({"state": метка, "kind": reauth.REAUTH_KIND, "next": назад}),
            max_age=GOOGLE_STATE_TTL_SECONDS,
            httponly=True,
            samesite="Lax",
            secure=over_https(),
            path="/",
        )
        return ответ

    def _вернуть_подтверждение(реквизиты: GoogleSettings, метка: str, назад: str) -> Response:
        """Возврат подтверждения: Google обязан назвать почту ЭТОЙ учётки."""
        token = token_of_request()
        account = resolve_session(token) if token else None
        if account is None or token is None:
            return redirect(url_for("login"))
        мимо = redirect(url_for(reauth.CONFIRM_ENDPOINT, next=назад, failed="1"))
        код = request.args.get("code") or ""
        if request.args.get("error") or not код:
            return мимо
        try:
            кто = exchange_code(_google_here(реквизиты), code=код)
        except GoogleAuthError:
            return мимо
        if not reauth.google_confirms(account, кто, state=метка, hq_domains=hq_domains):
            return мимо
        return _обновить_сессию(account, назад)

    def _выполнить_намерение(действие: str) -> Any:
        # Импорт при вызове: экран «Настроек» сам импортирует `auth`.
        from . import settings_screen

        return settings_screen.run_intent(conf, действие)

    reauth.install(
        app,
        stand=рубеж,
        trusted_proxies=conf.trusted_proxies,
        google_enabled=google is not None,
        rotate=_обновить_сессию,
        run_intent=_выполнить_намерение,
        begin_google=_начать_подтверждение,
        # Имя ищется в момент вызова: так сверка идёт ровно той дверью, что у входа.
        verify=lambda login, password: authenticate(login, password),
        secret_key=conf.secret_key,
    )

    def _вернуть_привязку(реквизиты: GoogleSettings, метка: str) -> Response:
        """Возврат привязки: учётка — из сессии этого браузера, исход — в «Настройки»."""
        token = token_of_request()
        account = resolve_session(token) if token else None
        if account is None or token is None:
            return redirect(url_for("login"))
        итог = _исход_привязки(реквизиты, token, account, метка)
        return google_link.back_to_settings(итог)

    def _исход_привязки(реквизиты: GoogleSettings, token: str, account: Account, метка: str) -> str:
        if request.args.get("error"):
            return "cancelled"
        код = request.args.get("code") or ""
        if not код:
            return "failed"
        try:
            кто: GoogleIdentity = exchange_code(_google_here(реквизиты), code=код)
        except GoogleAuthError:
            return "failed"
        return google_link.finish(
            token=token,
            login=account.login,
            tenant=account.tenant,
            state=метка,
            identity=кто,
            hq_domains=hq_domains,
        )

    def отказ_входа(*, забыть_подсказку: bool = False) -> tuple[str, int]:
        """Один и тот же отказ на все осечки возврата.

        Разные ответы на «метка не та», «код не тот» и «почты нет в списке»
        рассказали бы подбирающему, на каком шаге он остановился, и заодно —
        кто здесь заведён.

        `забыть_подсказку` — отказ в ДОПУСКЕ (почты нет в списке, не тот домен,
        не подтверждена): куку-подсказку стираем, чтобы в следующий раз Google
        показал выбор аккаунта, а не вёл по кругу в тот же отказ.
        """
        страница = render_template("login.html", failed=True, locked_minutes=None)
        ответ = make_response(страница, 401)
        ответ.delete_cookie(GOOGLE_STATE_COOKIE, path="/")
        if забыть_подсказку:
            ответ.delete_cookie(GOOGLE_HINT_COOKIE, path="/")
        return ответ  # type: ignore[return-value]

    def запомнить_подсказку(response: Response, email: str) -> Response:
        """После успешного входа — почта в долгую куку для `login_hint` (не сессия)."""
        response.set_cookie(
            GOOGLE_HINT_COOKIE,
            email,
            max_age=GOOGLE_HINT_TTL_SECONDS,
            httponly=True,
            samesite="Lax",
            secure=over_https(),
            path="/",
        )
        return response

    def очистить_метку(response: Response) -> Response:
        """Метка одноразовая: заход состоялся — её больше быть не должно."""
        response.delete_cookie(GOOGLE_STATE_COOKIE, path="/")
        return response

    @app.post(LOGOUT_PATH, endpoint="logout")
    def logout() -> Response:
        """Выход. Только POST и только со своей страницы.

        По ссылке (GET) выход не делается намеренно: картинка на чужой
        странице выбивала бы человека из админки без единого его движения.
        Мелочь, но чинится она одной строкой, а объясняется потом долго.
        """
        refuse_foreign_origin()
        token = token_of_request()
        if token:
            # Сначала база, потом кука. Обратный порядок означал бы, что при
            # отказе базы браузер уже «вышел», а сессия осталась живой.
            close_session(token)
        ответ = redirect(url_for("login"))
        ответ.delete_cookie(COOKIE_NAME, path="/")
        return ответ


def _подсказка_google(cookies: Mapping[str, str]) -> str | None:
    """Почта из куки-подсказки, если она похожа на почту; иначе `None` (окно выбора)."""
    сырое = (cookies.get(GOOGLE_HINT_COOKIE) or "").strip()
    if not сырое or len(сырое) > GOOGLE_HINT_MAX_LENGTH or "@" not in сырое:
        return None
    return сырое


def _google_here(google: GoogleSettings) -> GoogleSettings:
    """Реквизиты Google под адрес, с которого пришёл этот запрос (D236)."""
    return for_request(google, via_front=request.headers.get(FRONT_MARKER_HEADER) == "1")
