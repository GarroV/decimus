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

from flask import Flask, g, make_response, redirect, render_template, request, url_for
from itsdangerous import BadSignature, URLSafeTimedSerializer
from werkzeug.wrappers import Response

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

from .config import Settings
from .google_auth import (
    GoogleAuthError,
    authorization_url,
    exchange_code,
    load_google_settings,
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
OPEN_ENDPOINTS = frozenset({"login", "static", "google_start", "google_callback"})

#: Ключ в `g`, под которым живёт вошедший на время запроса.
CURRENT = "account"


def current_account() -> Account | None:
    """Кто сейчас на странице. `None` — никого, и до страницы дело не дошло."""
    return getattr(g, CURRENT, None)


def install(app: Flask, conf: Settings) -> None:
    """Повесить заслон и зарегистрировать вход с выходом."""
    signer = URLSafeTimedSerializer(
        conf.secret_key, salt=COOKIE_SALT, signer_kwargs={"digest_method": hashlib.sha256}
    )
    max_age = int(SESSION_TTL.total_seconds())

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
        account = resolve_session(token, tenant=conf.tenant) if token else None
        if account is None:
            return redirect(url_for("login"))
        setattr(g, CURRENT, account)
        return None

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
                "login.html", failed=False, locked_minutes=приговор.retry_after_minutes
            ),
            429,
        )
        ответ.headers["Retry-After"] = str(приговор.retry_after_seconds)
        return ответ

    @app.route(LOGIN_PATH, methods=("GET", "POST"), endpoint="login")
    def login() -> str | Response | tuple[str, int]:
        if request.method != "POST":
            return render_template("login.html", failed=False, locked_minutes=None)
        refuse_foreign_origin()
        имя = request.form.get("login") or ""
        адрес = client_address(trusted_proxies=conf.trusted_proxies)
        # ОДНИМ движением: пустить ли к сверке пароля и записать саму попытку.
        # Раздельные «спросить» и «записать» пропускали мимо порога столько
        # лишних параллельных попыток, сколько у сервера потоков (T328). Сверка
        # пароля идёт ПОСЛЕ: смысл ограничителя в том, что запертый не доходит
        # до дорогой части вовсе — ни до scrypt, ни до базы учёток.
        попытка = admit_attempt(tenant=conf.tenant, address=адрес, login=имя)
        if not попытка.admitted:
            return заперто(попытка.verdict)
        account = authenticate(имя, request.form.get("password") or "", tenant=conf.tenant)
        if account is None:
            if попытка.verdict.locked:
                return заперто(попытка.verdict)
            # Один и тот же отказ на «нет такого логина» и «пароль не тот»:
            # иначе форма сама рассказывает перебором, кто здесь заведён.
            # Введённое обратно на страницу не возвращается — среди него
            # пароль, и он уехал бы в разметку, а оттуда в кэш и в снимок
            # экрана.
            return render_template("login.html", failed=True, locked_minutes=None), 401
        note_success(tenant=conf.tenant, address=адрес, login=имя)
        session = open_session(account)
        return remember(redirect(url_for("registry")), session)

    google = load_google_settings()
    state_signer = URLSafeTimedSerializer(
        conf.secret_key, salt=GOOGLE_STATE_SALT, signer_kwargs={"digest_method": hashlib.sha256}
    )

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
        ответ = redirect(authorization_url(google, state=метка))
        # Метка кладётся В КУКУ, а не в память процесса: стенд может работать
        # несколькими воркерами, и возврат придёт не обязательно в тот, что
        # уводил.
        ответ.set_cookie(
            GOOGLE_STATE_COOKIE,
            state_signer.dumps(метка),
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
            ожидаемая = state_signer.loads(подписанная, max_age=GOOGLE_STATE_TTL_SECONDS)
        except BadSignature:
            return отказано
        # Сравнение постоянного времени: обычное `==` на строках отвечает тем
        # быстрее, чем раньше расходятся байты, и по этому времени метку
        # подбирают.
        # Сравнение В БАЙТАХ, а не в строках: `compare_digest` на строках с
        # не-ASCII падает TypeError, и подделанная метка с кириллицей давала бы
        # 500 вместо отказа. Поймано тестом, а не в бою.
        if not hmac.compare_digest(str(ожидаемая).encode(), пришедшая.encode()):
            return отказано

        # `error=access_denied` приходит, когда человек сам отказался в окне
        # согласия. Это не поломка: возвращаем на форму без красного.
        if request.args.get("error"):
            return очистить_метку(redirect(url_for("login")))

        код = request.args.get("code") or ""
        if not код:
            return отказано

        try:
            кто = exchange_code(google, code=код)
        except GoogleAuthError:
            return отказано

        # Второй заслон на подтверждённость почты. Первый стоит в разборе
        # токена (`google_auth.identity_from_id_token`), и обычно этого хватает
        # — но `GoogleIdentity` несёт признак с собой, а маршрут его
        # игнорировал. Появится завтра второй путь получения личности (другой
        # провайдер, кеш, тест-двойник) — и неподтверждённая почта пройдёт
        # сюда молча. Проверка стоит строки, пропуск стоит чужого входа.
        if not кто.email_verified:
            return отказано

        # ВОТ ЗДЕСЬ круг допущенных: Google подтвердил владение почтой и не
        # более того. Незнакомая почта получает отказ, а не заводит учётку —
        # иначе круг допущенных задавал бы Google, а не владелец.
        account = find_by_email(кто.email, tenant=conf.tenant)
        if account is None:
            return отказано

        note_success(
            tenant=conf.tenant,
            address=client_address(trusted_proxies=conf.trusted_proxies),
            login=account.login,
        )
        session = open_session(account)
        return очистить_метку(remember(redirect(url_for("registry")), session))

    def отказ_входа() -> tuple[str, int]:
        """Один и тот же отказ на все осечки возврата.

        Разные ответы на «метка не та», «код не тот» и «почты нет в списке»
        рассказали бы подбирающему, на каком шаге он остановился, и заодно —
        кто здесь заведён.
        """
        страница = render_template("login.html", failed=True, locked_minutes=None)
        ответ = make_response(страница, 401)
        ответ.delete_cookie(GOOGLE_STATE_COOKIE, path="/")
        return ответ  # type: ignore[return-value]

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
