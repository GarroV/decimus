"""Учётки и сессии веб-админки: кто входит и чем это подтверждается (T323).

Дверь блока `db` для одного вопроса: «этот человек — тот, за кого себя выдаёт,
и чью историю ему показывать». Ничего другого модуль не умеет и уметь не
должен: ролей, приглашений и регистрации снаружи здесь нет — круг узкий, и
учётки заводит команда проекта (D155).

**ДВЕ РОЛИ, И ЭТО ГЛАВНОЕ.** Опознание и сессии работают под ролью приложения
(`DATABASE_URL`) — той же, под которой живёт весь продукт. Заведение,
отключение и перечисление учёток идут под ролью ВЛАДЕЛЬЦА СХЕМЫ
(`DATABASE_ADMIN_URL`) — той же, что накатывает миграции. Разделение держит не
код, а права в базе (миграция `0014`): роль приложения на `web_users` имеет
только `select`, поэтому завести учётку или подменить чужой пароль она не
может физически. Своей четвёртой роли здесь не заводится — владелец схемы уже
существует, и заведение учётки это работа ровно его класса.

**ОБРАТИМОГО ХРАНЕНИЯ НЕТ НИГДЕ.** От пароля остаётся scrypt с солью, от
сессионного токена — отпечаток SHA-256, как у токенов MCP
(`src/db/mcp_access.py`). Ни то ни другое не восстанавливается, и обе колонки
держат форму ограничением схемы, а не договорённостью здесь.

**СЕССИЯ ЖИВЁТ В БАЗЕ, А НЕ ТОЛЬКО В КУКЕ.** Иначе выход прекращал бы доступ
ровно в том браузере, где нажали кнопку: снятая копия куки работала бы до
конца срока, и отозвать её было бы нечем. Выход помечает строку закрытой, а
снять эту пометку не может никто — заслон стоит в схеме (`0014`).
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import psycopg

from .config import check_environment, load_retraction_settings
from .errors import AccessError, ConfigError
from .migrate import admin_dsn

#: Сколько живёт сессия. Рабочий день с запасом: короче — человек вводит пароль
#: посреди работы, длиннее — забытая на чужом экране вкладка переживает ночь.
#: Величина названа здесь, а не в схеме: «сколько живёт сессия» правится в
#: одном месте, а база только требует, чтобы срок был.
SESSION_TTL = timedelta(hours=12)

#: Байт случайности в сессионном токене. Столько же, сколько у токена MCP:
#: подбор к такому не применяется вовсе, а не «применяется медленно».
SESSION_TOKEN_BYTES = 32

#: Параметры scrypt. `n` — цена одной попытки по памяти и времени
#: (128 × n × r ≈ 16 МиБ и порядка 60 мс на нынешнем железе). Подбор украденной
#: базы это не делает невозможным, но делает его дорогим настолько, что словарь
#: перестаёт окупаться. Записаны они В САМ ХЕШ, а не только здесь: сменить их
#: завтра можно, не потеряв вчерашние учётки.
SCRYPT_N = 16384
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32
SCRYPT_SALT_BYTES = 16

#: Метка алгоритма в начале хеша. Ограничение схемы смотрит на неё же: пароль
#: человека с этой строки не начинается, поэтому «записали пароль вместо хеша»
#: превращается в отказ записи.
HASH_SCHEME = "scrypt"

#: Длина отпечатка SHA-256 шестнадцатеричной записью — ровно то, что принимает
#: колонка `fingerprint`.
FINGERPRINT_LENGTH = 64

#: Короткий пароль — это не «слабее», а «подбирается за вечер». Нижняя граница
#: стоит на заведении учётки, то есть в единственном месте, где пароль вообще
#: выбирают.
MIN_PASSWORD_LENGTH = 12

#: Логин — имя, а не свободный текст: он попадает в адрес запроса, в журнал и
#: в разговор людей. Ограничение формы здесь — обычная проверка ввода на
#: границе, а не защита от инъекции (её держат параметры запроса).
LOGIN_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")

_INSERT_TENANT_SQL = "insert into tenants (code) values (%s) on conflict (code) do nothing"

_INSERT_USER_SQL = """
    insert into web_users (tenant_code, login, password_hash, role)
    values (%s, %s, %s, %s)
    returning id
"""

_SELECT_USER_SQL = """
    select id, login, tenant_code, password_hash, role
      from web_users
     where tenant_code = %s and login = %s and disabled_at is null
"""

_LIST_USERS_SQL = """
    select login, created_at, disabled_at, role
      from web_users
     where tenant_code = %s
     order by login
"""

_DISABLE_USER_SQL = """
    update web_users
       set disabled_at = now()
     where tenant_code = %s and login = %s and disabled_at is null
"""

_SET_ROLE_SQL = """
    update web_users
       set role = %s
     where tenant_code = %s and login = %s and disabled_at is null
"""

_OPEN_SESSION_SQL = """
    insert into web_sessions (user_id, fingerprint, expires_at)
    values (%s, %s, now() + %s)
    returning expires_at
"""

#: Учётка сверяется ВМЕСТЕ с сессией, одним запросом. Отдельной проверкой
#: «а жива ли учётка» это быть не может: между двумя запросами помещается
#: отключение, и отключённый доработал бы страницу до конца.
_RESOLVE_SESSION_SQL = """
    select u.id, u.login, u.tenant_code, u.role
      from web_sessions s
      join web_users u on u.id = s.user_id
     where s.fingerprint = %s
       and s.closed_at is null
       and s.expires_at > now()
       and u.disabled_at is null
       and u.tenant_code = %s
"""

_CLOSE_SESSION_SQL = """
    update web_sessions
       set closed_at = now()
     where fingerprint = %s and closed_at is null
"""


#: Роли внутри админки. Перечислены здесь И ограничением схемы (`0020`):
#: код без схемы пропустил бы опечатку в базу, схема без кода молчала бы о
#: ней до первой записи.
ROLE_AUDITOR = "auditor"
ROLE_ADMIN = "admin"
ROLES = (ROLE_AUDITOR, ROLE_ADMIN)


@dataclass(frozen=True)
class Account:
    """Учётка так, как её видят страницы: кто вошёл и чью историю показывать."""

    id: str
    login: str
    tenant: str
    #: Что человеку можно В АДМИНКЕ (`auditor` | `admin`), а не чью историю
    #: ему видно: за историю отвечает арендатор, и роль его не расширяет.
    #: Приезжает вместе с опознанием, одним запросом с ним: спрошенная
    #: отдельно, она успела бы устареть между двумя запросами.
    role: str = ROLE_AUDITOR


@dataclass(frozen=True)
class AccountRow:
    """Строка перечня учёток для команды обслуживания.

    Хеша здесь нет намеренно: вопрос команды — «кто заведён», а не «чем он
    входит». Напечатанный в терминал хеш уезжает в историю команд и в лог
    сессии, откуда его уже не отозвать.
    """

    login: str
    role: str
    created_at: datetime
    #: Когда учётка отключена; `None` — работает. Признаком-свойством это не
    #: оборачивается: единственный читатель — команда обслуживания, и ей нужна
    #: сама дата, а не «да/нет».
    disabled_at: datetime | None


@dataclass(frozen=True)
class OpenedSession:
    """Только что открытая сессия. `token` уезжает в куку и больше нигде не живёт."""

    token: str
    expires_at: datetime


def password_hash(password: str) -> str:
    """Пароль → строка хранения `scrypt$n$r$p$соль$хеш`.

    Соль своя у каждого вызова: одинаковые пароли обязаны давать разные строки,
    иначе по совпадению видно, что у двух людей пароль один и тот же, — а это
    уже половина подбора.

    Параметры едут внутри строки, а не только в константах модуля. Смена их
    завтра (железо подешевеет) не обязана обесценивать вчерашние учётки:
    старый хеш проверится своими параметрами, новый запишется новыми.
    """
    соль = secrets.token_bytes(SCRYPT_SALT_BYTES)
    свёртка = hashlib.scrypt(
        password.encode("utf-8"),
        salt=соль,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_DKLEN,
    )
    return f"{HASH_SCHEME}${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${соль.hex()}${свёртка.hex()}"


def password_matches(password: str, stored: str) -> bool:
    """Тот ли это пароль. Строка хранения неизвестного вида — отказ, а не `False`.

    Разница существенная: `False` означает «пароль не тот» и человеку говорят
    «проверьте пароль», а испорченная строка означает «мы не смогли сверить», и
    выдать второе за первое — это молча запереть человека снаружи с неверным
    объяснением.

    Сравнение постоянного времени обязательно: здесь сверяется СЕКРЕТ, и по
    времени ответа он подбирается посимвольно.
    """
    части = stored.split("$")
    if len(части) != 6 or части[0] != HASH_SCHEME:
        raise AccessError(f"Строка хранения пароля не похожа на {HASH_SCHEME}")
    try:
        n, r, p = (int(части[1]), int(части[2]), int(части[3]))
        соль = bytes.fromhex(части[4])
        свёртка = bytes.fromhex(части[5])
    except ValueError as exc:
        raise AccessError("Строка хранения пароля испорчена") from exc

    заново = hashlib.scrypt(password.encode("utf-8"), salt=соль, n=n, r=r, p=p, dklen=len(свёртка))
    return hmac.compare_digest(заново, свёртка)


def new_session_token() -> str:
    """Новый сессионный токен. Значение живёт в куке, в базе — только отпечаток."""
    return secrets.token_urlsafe(SESSION_TOKEN_BYTES)


def session_fingerprint(token: str) -> str:
    """Отпечаток сессионного токена — то единственное, что от него остаётся в базе.

    Соли здесь нет, и это не упущение: токен — 256 случайных бит, словарём он
    не берётся, а поиск по отпечатку обязан быть одним обращением по индексу.
    Та же развилка и тот же ответ, что у токенов MCP.
    """
    отпечаток = hashlib.sha256(token.encode("utf-8")).hexdigest()
    if len(отпечаток) != FINGERPRINT_LENGTH:
        raise AccessError(
            f"отпечаток вышел длиной {len(отпечаток)} вместо {FINGERPRINT_LENGTH} — "
            f"схема такой не примет"
        )
    return отпечаток


@contextmanager
def _connected(зачем: str) -> Iterator[psycopg.Connection[Any]]:
    """Подключение роли приложения. Отказ базы — `AccessError`, а не тишина.

    Наружу уходит ТИП исключения драйвера, а не его текст: в тексте psycopg
    может оказаться строка подключения целиком. Тот же приём и та же причина,
    что у `mcp_access._connected` и `queries._reading`.
    """
    settings = check_environment()
    try:
        with psycopg.connect(settings.dsn) as conn:
            yield conn
    except psycopg.Error as exc:
        raise AccessError(f"Не удалось {зачем} ({type(exc).__name__})") from exc


@contextmanager
def _owned(зачем: str) -> Iterator[psycopg.Connection[Any]]:
    """Подключение ВЛАДЕЛЬЦА СХЕМЫ — то, чем заводят и отключают учётки.

    Отдельно от `_connected`, потому что роль другая и отказывает по-другому:
    «роль приложения не смогла прочитать учётку» чинится не там, где «на этой
    машине не задано подключение владельца». Отсутствие настройки — отказ с
    названной переменной, а не молчаливый откат на роль приложения: такой
    откат выглядел бы работающим ровно до первой попытки записи и объяснил бы
    её отказом прав вместо настоящей причины.
    """
    dsn = admin_dsn()
    if not dsn:
        raise AccessError(
            f"Не удалось {зачем}: не задано DATABASE_ADMIN_URL. Учётки заводит роль "
            f"владельца схемы — та же, что накатывает миграции; роль приложения "
            f"этого права не имеет намеренно"
        )
    try:
        with psycopg.connect(dsn) as conn:
            yield conn
    except psycopg.Error as exc:
        raise AccessError(f"Не удалось {зачем} ({type(exc).__name__})") from exc


@contextmanager
def _managing(зачем: str) -> Iterator[psycopg.Connection[Any]]:
    """Подключение, которым МОЖНО тронуть строку учётки.

    Таких ролей две, и обе законны: администратор истории
    (`DATABASE_RETRACTION_URL`, права выданы миграцией `0020`) и владелец схемы
    (`DATABASE_ADMIN_URL`, он владеет таблицей). Берётся ПЕРВАЯ — узкая, — и
    это не удобство, а разница в цене ошибки: веб-процесс, которому дали
    владельца схемы, умеет не только завести учётку, но и снести таблицу
    вместе с историей проверок.

    Откатом на вторую это не является: обе роли имеют право по схеме, выбор
    объявлен здесь и повторяется всегда одинаково. Молчаливым откат был бы,
    если бы вторая роль права НЕ имела и отказывала уже на записи — тогда
    настоящая причина («не задано подключение») пряталась бы за чужой.
    """
    try:
        dsn = load_retraction_settings().dsn
    except ConfigError:
        dsn = admin_dsn() or ""
    if not dsn:
        raise AccessError(
            f"Не удалось {зачем}: не задано ни DATABASE_RETRACTION_URL, ни "
            f"DATABASE_ADMIN_URL. Учётки трогает роль повышенных полномочий; "
            f"роль приложения этого права не имеет намеренно (D155)"
        )
    try:
        with psycopg.connect(dsn) as conn:
            yield conn
    except psycopg.Error as exc:
        raise AccessError(f"Не удалось {зачем} ({type(exc).__name__})") from exc


def _checked_role(role: str) -> str:
    if role not in ROLES:
        raise AccessError(f"Роль «{role}» не заведена. Есть: {', '.join(ROLES)}")
    return role


def _checked_login(login: str) -> str:
    имя = login.strip().lower()
    if not LOGIN_PATTERN.match(имя):
        raise AccessError(
            f"Логин «{login}» не годится: латиница в нижнем регистре, цифры, точка, "
            f"дефис и подчёркивание, от 2 до 64 знаков, первый знак — буква или цифра"
        )
    return имя


def create_account(login: str, *, tenant: str, password: str, role: str = ROLE_AUDITOR) -> Account:
    """Завести учётку. Роль владельца схемы, повтор логина — отказ.

    Пароль сюда приходит от человека, который учётку заводит, и в репозитории
    не лежит. Возвращается учётка без него: печатать пароль обратно вызывающему
    незачем, а напечатанное уезжает в историю команд.
    """
    имя = _checked_login(login)
    # Роль по умолчанию — САМАЯ УЗКАЯ. Заводящий человек думает про «завести
    # Петра», а не про объём его прав, и умолчание, дающее больше, раздавало
    # бы админов молча.
    роль = _checked_role(role)
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AccessError(
            f"Пароль короче {MIN_PASSWORD_LENGTH} знаков. Короткий подбирается по "
            f"украденной базе за вечер, и никакой хеш этого не меняет"
        )
    хеш = password_hash(password)
    with _managing("завести учётку") as conn, conn.cursor() as cur:
        cur.execute(_INSERT_TENANT_SQL, (tenant,))
        try:
            cur.execute(_INSERT_USER_SQL, (tenant, имя, хеш, роль))
        except psycopg.errors.UniqueViolation as exc:
            raise AccessError(
                f"Учётка «{имя}» у арендатора «{tenant}» уже есть. Сменить пароль "
                f"существующей эта команда не умеет — отключите старую и заведите новую"
            ) from exc
        row = cur.fetchone()
    assert row is not None  # noqa: S101 — insert ... returning без строки не бывает
    return Account(id=str(row[0]), login=имя, tenant=tenant, role=роль)


def list_accounts(*, tenant: str) -> tuple[AccountRow, ...]:
    """Кто заведён у этого арендатора. Роль владельца схемы."""
    with _managing("перечислить учётки") as conn, conn.cursor() as cur:
        cur.execute(_LIST_USERS_SQL, (tenant,))
        строки = cur.fetchall()
    return tuple(
        AccountRow(login=str(r[0]), created_at=r[1], disabled_at=r[2], role=str(r[3]))
        for r in строки
    )


def disable_account(login: str, *, tenant: str) -> bool:
    """Отключить учётку. `False` — такой живой учётки нет. Роль владельца схемы.

    Действует немедленно и на уже открытые сессии: опознание сверяет учётку
    вместе с сессией на каждом запросе, а не запоминает её при входе.
    """
    with _managing("отключить учётку") as conn, conn.cursor() as cur:
        cur.execute(_DISABLE_USER_SQL, (tenant, login.strip().lower()))
        return cur.rowcount > 0


def set_role(login: str, *, tenant: str, role: str) -> bool:
    """Назначить роль живой учётке. `False` — такой живой учётки нет.

    Отдельной операцией, а не полем формы заведения: первый админ стенда
    назначается именно ей. Накат `0020` не даёт прав НИКОМУ — кто заведён в
    бою, миграция не знает, и раздача «всем» или «по имени» выдала бы права
    людям, которых на это никто не смотрел.
    """
    роль = _checked_role(role)
    with _managing("сменить роль учётки") as conn, conn.cursor() as cur:
        cur.execute(_SET_ROLE_SQL, (роль, tenant, login.strip().lower()))
        return cur.rowcount > 0


def authenticate(login: str, password: str, *, tenant: str) -> Account | None:
    """Логин и пароль → учётка. Не тот пароль, нет такой учётки, чужой арендатор — `None`.

    **Все три отказа неотличимы снаружи, и это намеренно.** Иначе форма входа
    сама сообщает перебором, какие логины заведены.

    Незнакомый логин всё равно стоит одного вычисления scrypt. Без этого ответ
    «такого нет» приходил бы мгновенно, а «пароль не тот» — через десятки
    миллисекунд, и разница по времени рассказала бы ровно то, что предыдущий
    абзац запрещает говорить словами.

    Арендатор приходит из окружения стенда, а не от человека: подставить его
    в форму мог бы кто угодно, и это была бы не граница арендаторов, а её
    отсутствие.
    """
    with _connected("сверить учётку") as conn, conn.cursor() as cur:
        cur.execute(_SELECT_USER_SQL, (tenant, login.strip().lower()))
        row = cur.fetchone()
    if row is None:
        password_hash(password)
        return None
    if not password_matches(password, str(row[3])):
        return None
    return Account(id=str(row[0]), login=str(row[1]), tenant=str(row[2]), role=str(row[-1]))


def open_session(account: Account) -> OpenedSession:
    """Открыть сессию. Токен возвращается один раз — дальше он живёт в куке."""
    token = new_session_token()
    with _connected("открыть сессию") as conn, conn.cursor() as cur:
        cur.execute(_OPEN_SESSION_SQL, (account.id, session_fingerprint(token), SESSION_TTL))
        row = cur.fetchone()
    assert row is not None  # noqa: S101 — insert ... returning без строки не бывает
    return OpenedSession(token=token, expires_at=row[0])


def resolve_session(token: str, *, tenant: str) -> Account | None:
    """Токен из куки → кто вошёл. Закрытая, просроченная и чужая сессия — `None`.

    Спрашивается на КАЖДЫЙ запрос, а не запоминается на входе: отключение
    учётки и выход обязаны действовать немедленно, а снятый однажды ответ —
    это ровно тот способ, которым «немедленно» превращается в «когда-нибудь».

    Отказ базы уходит отказом (`AccessError`), а не `None`: `None` означает
    «эта кука не действует», а упавшая база означает «мы не смогли посмотреть»,
    и выдать второе за первое — молча выбросить из админки всех и объяснить
    это каждому неверным словом.
    """
    with _connected("сверить сессию") as conn, conn.cursor() as cur:
        cur.execute(_RESOLVE_SESSION_SQL, (session_fingerprint(token), tenant))
        row = cur.fetchone()
    if row is None:
        return None
    return Account(id=str(row[0]), login=str(row[1]), tenant=str(row[2]), role=str(row[-1]))


def close_session(token: str) -> bool:
    """Закрыть сессию. `False` — такой живой сессии не было.

    Это и есть выход. Пометка ставится в базе, поэтому перестаёт работать
    любая копия куки, а не только та вкладка, где нажали кнопку. Обратно
    пометка не снимается — заслон стоит в схеме (`0014`).
    """
    with _connected("закрыть сессию") as conn, conn.cursor() as cur:
        cur.execute(_CLOSE_SESSION_SQL, (session_fingerprint(token),))
        return cur.rowcount > 0
