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
"""

from __future__ import annotations

import hashlib

from flask import Flask, g, redirect, render_template, request, url_for
from itsdangerous import BadSignature, URLSafeTimedSerializer
from werkzeug.wrappers import Response

from src.db.web_access import (
    SESSION_TTL,
    Account,
    OpenedSession,
    authenticate,
    close_session,
    open_session,
    resolve_session,
)

from .config import Settings
from .origin import over_https, refuse_foreign_origin

LOGIN_PATH = "/login"
LOGOUT_PATH = "/logout"

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
OPEN_ENDPOINTS = frozenset({"login", "static"})

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

    @app.route(LOGIN_PATH, methods=("GET", "POST"), endpoint="login")
    def login() -> str | Response | tuple[str, int]:
        if request.method != "POST":
            return render_template("login.html", failed=False)
        refuse_foreign_origin()
        account = authenticate(
            request.form.get("login") or "",
            request.form.get("password") or "",
            tenant=conf.tenant,
        )
        if account is None:
            # Один и тот же отказ на «нет такого логина» и «пароль не тот»:
            # иначе форма сама рассказывает перебором, кто здесь заведён.
            # Введённое обратно на страницу не возвращается — среди него
            # пароль, и он уехал бы в разметку, а оттуда в кэш и в снимок
            # экрана.
            return render_template("login.html", failed=True), 401
        session = open_session(account)
        return remember(redirect(url_for("registry")), session)

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
