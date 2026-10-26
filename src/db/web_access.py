"""Учётки и сессии веб-админки: кто входит и чем это подтверждается (T323).

Дверь блока `db` для одного вопроса: «этот человек — тот, за кого себя выдаёт,
и чью историю ему показывать». Ничего другого модуль не умеет и уметь не
должен: ролей, приглашений и регистрации снаружи здесь нет — круг узкий, и
учётки заводит команда проекта (D155).

**ДВЕ РОЛИ, И ЭТО ГЛАВНОЕ.** Опознание и сессии работают под ролью приложения
(`DATABASE_URL`) — той же, под которой живёт весь продукт. Заведение,
отключение и перечисление учёток идут под узкой ролью администратора истории
(`DATABASE_RETRACTION_URL`, права — `0020`, `0041`); владелец схемы
(`DATABASE_ADMIN_URL`) сервисам не выдаётся (F-002) и остаётся только запасным
подключением инструментов (`managing_dsn`). Разделение держит не
код, а права в базе (миграция `0014`): роль приложения на `web_users` имеет
только `select`, поэтому завести учётку или подменить чужой пароль она не
может физически. Четвёртой роли здесь не заводится: администратор истории уже существует.

**ОБРАТИМОГО ХРАНЕНИЯ НЕТ НИГДЕ.** От пароля остаётся scrypt с солью, от
сессионного токена — отпечаток SHA-256, как у токенов MCP
(`src/db/mcp_access.py`). Ни то ни другое не восстанавливается, и обе колонки
держат форму ограничением схемы, а не договорённостью здесь.

**СЕССИЯ ЖИВЁТ В БАЗЕ, А НЕ ТОЛЬКО В КУКЕ.** Иначе выход прекращал бы доступ
ровно в том браузере, где нажали кнопку: снятая копия куки работала бы до
конца срока, и отозвать её было бы нечем. Выход помечает строку закрытой, а
снять эту пометку не может никто — заслон стоит в схеме (`0014`).

**ЛОГИН И ПОЧТА ЕДИНЫЕ НА ВСЮ СИСТЕМУ, НЕ НА АРЕНДАТОРА (D282, `0028`).** Один
человек — одна учётка, и её пространство — просто поле строки (`tenant_code`),
а не то, чем опознание фильтрует поиск. `authenticate`, `find_by_email` и
`resolve_session` ищут по всей базе: партнёр входит через тот же адрес, что и
УК, и получает своё пространство вместе с опознанием. Заведение, отключение,
роль и пароль остаются операциями ОДНОГО пространства (`tenant=` в их
сигнатуре) — это не граница входа, а то, чьими руками человека завели.
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
from typing import Any, Literal

import psycopg

from src.domain.journal import truncate_user_agent
from src.domain.tenants import HQ_TENANT, canonical_tenant

from .config import check_environment
from .database_target import managing_dsn
from .errors import AccessError, EmailTakenError, SecondStepRequiredError
from .pool import connection
from .reading import reading
from .space_guard import require_space

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

#: Предел длины пароля сверху. Его проверяют до scrypt у каждой двери, которая
#: хеширует пароль: иначе одна отправка тела в сотни килобайт заказывает
#: стенду лишнюю работу. 256 знаков с запасом вмещают любую парольную фразу
#: и любой пароль из менеджера паролей. Пароля длиннее нет ни у кого, поэтому
#: на сверке такой пароль просто «не тот».
MAX_PASSWORD_LENGTH = 256

#: Логин — имя, а не свободный текст: он попадает в адрес запроса, в журнал и
#: в разговор людей. Ограничение формы здесь — обычная проверка ввода на
#: границе, а не защита от инъекции (её держат параметры запроса).
LOGIN_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")


_INSERT_USER_SQL = """
    insert into web_users (tenant_code, login, password_hash, role)
    values (%s, %s, %s, %s)
    returning id
"""

_SELECT_USER_SQL = """
    select id, login, tenant_code, password_hash, role, email
      from web_users
     where login = %s and disabled_at is null
"""

#: Пустое пространство (`null`) — люди всех пространств: экран админа УК
#: (D286). Условие в тексте неизменно, охват приходит параметром (S608).
_LIST_USERS_SQL = """
    select u.login, u.created_at, u.disabled_at, u.role, u.tenant_code, u.id, u.email,
           f.login, u.display_name_latin
      from web_users u
      left join web_users f on f.id = u.disabled_by
     where (%(tenant)s::text is null or u.tenant_code = %(tenant)s)
     order by u.tenant_code, u.login
"""

_LIST_SPACES_SQL = "select code from tenants order by code"

#: `roles` — охват правящего по роли ЦЕЛИ (#585): условие в самом запросе, а не
#: только в маршруте. Цель, ставшая админом между чтением перечня и записью,
#: не правится тем, кому админы вне охвата. `null` — без ограничения.
_FREEZE_USER_SQL = """
    update web_users
       set disabled_at = now(), disabled_by = %(by)s
     where tenant_code = %(tenant)s and login = %(login)s and disabled_at is null
       and (%(roles)s::text[] is null or role = any(%(roles)s::text[]))
"""

#: Разморозка снимает только отметку: закрытое заморозкой (`0063`) остаётся
#: закрытым. Условие на роль цели — то же, что у заморозки.
_UNFREEZE_USER_SQL = """
    update web_users
       set disabled_at = null, disabled_by = null
     where tenant_code = %(tenant)s and login = %(login)s and disabled_at is not null
       and (%(roles)s::text[] is null or role = any(%(roles)s::text[]))
"""

#: «Выйти везде» — функцией базы (`0063`): строку выбирает живая сессия.
_SIGN_OUT_EVERYWHERE_SQL = "select sign_out_everywhere(%s)"

#: Прежняя роль читается той же командой, что пишет новую: строка запирается
#: (`for update`), и между «было» и «стало» вторая правка не вклинится.
_SET_ROLE_SQL = """
    with прежняя as (
        select id, role
          from web_users
         where tenant_code = %(tenant)s and login = %(login)s and disabled_at is null
           and (%(roles)s::text[] is null or role = any(%(roles)s::text[]))
           for update
    )
    update web_users u
       set role = %(role)s
      from прежняя
     where u.id = прежняя.id
 returning прежняя.role
"""

_CHANGE_PASSWORD_SQL = """
    update web_users
       set password_hash = %s
     where tenant_code = %s and login = %s and disabled_at is null
 returning id
"""  # noqa: S105 — это текст ЗАПРОСА, а не пароль

#: Свой хеш — по живой сессии, тем же условием, что у опознания: закрытая,
#: просроченная сессия или отключённая учётка пароля не меняют.
_SELECT_OWN_HASH_SQL = """
    select u.password_hash
      from web_sessions s
      join web_users u on u.id = s.user_id
     where s.fingerprint = %s
       and s.closed_at is null
       and s.expires_at > now()
       and u.disabled_at is null
"""

#: Запись — функцией базы (`0032`): роль приложения хеш не пишет, а функция
#: трогает только строку той сессии, чей токен ей предъявлен. От пробитого
#: приложения это не защищает — см. `change_own_password` ниже.
_CHANGE_OWN_PASSWORD_SQL = "select change_own_password(%s, %s, %s)"  # noqa: S105 — текст запроса

_CLOSE_USER_SESSIONS_SQL = """
    update web_sessions
       set closed_at = now()
     where user_id = %s and closed_at is null
"""

#: Смена пароля или почты отзывает и подключения Claude (`0054`): вошедший по
#: старому паролю или почте мог успеть разрешить доступ, и подключение пережило
#: бы смену. Причина — `password` или `email`.
_REVOKE_USER_OAUTH_SQL = """
    update oauth_grants
       set revoked_at = now(), revoked_reason = %s
     where user_id = %s and revoked_at is null
"""

#: И ещё не обменянные коды: выданный до смены код иначе обменялся бы после
#: неё на новое подключение. Гасятся ДО отзыва подключений — см. `_revoke_oauth`.
_EXPIRE_USER_OAUTH_CODES_SQL = """
    update oauth_codes
       set expires_at = now()
     where user_id = %s and used_at is null and expires_at > now()
"""

#: Прежняя почта читается той же командой, что пишет новую (строка заперта):
#: сессии закрываются, только если почта на деле сменилась.
_SET_EMAIL_SQL = """
    with прежняя as (
        select id, email
          from web_users
         where tenant_code = %(tenant)s and login = %(login)s and disabled_at is null
           and (%(roles)s::text[] is null or role = any(%(roles)s::text[]))
           for update
    )
    update web_users u
       set email = %(email)s
      from прежняя
     where u.id = прежняя.id
 returning u.id, прежняя.email is distinct from u.email
"""

_SET_NAME_LATIN_SQL = """
    update web_users
       set display_name_latin = %(name)s
     where tenant_code = %(tenant)s and login = %(login)s and disabled_at is null
       and (%(roles)s::text[] is null or role = any(%(roles)s::text[]))
 returning id
"""

_SELECT_USER_BY_ID_SQL = """
    select id, login, tenant_code, role, email
      from web_users
     where id = %s and disabled_at is null
"""

_SELECT_USER_BY_EMAIL_SQL = """
    select id, login, tenant_code, role, email
      from web_users
     where email = %s and disabled_at is null
"""

_OPEN_SESSION_SQL = """
    insert into web_sessions (user_id, fingerprint, expires_at, ip, user_agent, second_step_at)
    select %(user)s, %(fp)s, now() + %(ttl)s, %(ip)s, %(ua)s, case when %(second)s then now() end
     where %(second)s
        or %(waived)s
        or not (exists (select 1 from web_passkeys p where p.user_id = %(user)s)
                or exists (select 1 from web_totp t
                            where t.user_id = %(user)s and t.confirmed_at is not null))
    returning expires_at, id
"""

#: Учётка сверяется ВМЕСТЕ с сессией, одним запросом. Отдельной проверкой
#: «а жива ли учётка» это быть не может: между двумя запросами помещается
#: отключение, и отключённый доработал бы страницу до конца.
_RESOLVE_SESSION_SQL = """
    select u.id, u.login, u.tenant_code, u.role, u.email, u.web_lang, s.issued_at,
           u.display_name, u.avatar_etag, s.id,
           (exists (select 1 from web_passkeys p where p.user_id = u.id)
            or exists (select 1 from web_totp t
                        where t.user_id = u.id and t.confirmed_at is not null)),
           s.second_step_at is not null,
           u.country_filter
      from web_sessions s
      join web_users u on u.id = s.user_id
     where s.fingerprint = %s
       and s.closed_at is null
       and s.expires_at > now()
       and u.disabled_at is null
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
#: Контроль УК (D319): рейтинги — загрузка и справочники. Только в HQ (`0040`).
ROLE_CONTROL = "control"
#: Главный админ (D364): всё по проекту. Только в HQ; последнего действующего
#: отключить или понизить не даёт база (`0041`, триггер на `web_users`).
ROLE_SUPERADMIN = "superadmin"
#: Бизнес-девелопер (D440): в УК вместо аудитора — пользуется сервисом полностью,
#: методику и людей не трогает. Только в HQ (`0060`).
ROLE_DEVELOPER = "developer"
#: Гость (D440): вся сеть только на чтение. Только в HQ (`0060`).
ROLE_GUEST = "guest"
#: ОСБ (D599): гость плюс ведение предписаний. Только в HQ.
ROLE_OSB = "osb"
#: От самой узкой к самой широкой: в таком порядке роли идут в форме.
ROLES = (
    ROLE_AUDITOR,
    ROLE_GUEST,
    ROLE_OSB,
    ROLE_DEVELOPER,
    ROLE_CONTROL,
    ROLE_ADMIN,
    ROLE_SUPERADMIN,
)
#: Роли, которые бывают только в пространстве УК (`0040`, `0041`, `0060`).
HQ_ONLY_ROLES = (ROLE_CONTROL, ROLE_SUPERADMIN, ROLE_DEVELOPER, ROLE_GUEST, ROLE_OSB)
#: Роль, которой в УК больше нет (D440, `0060`): аудиторы УК стали девелоперами.
PARTNER_ONLY_ROLES = (ROLE_AUDITOR,)


#: Код отказа триггера `keep_last_superadmin` (`0041`): последнего действующего
#: главного админа отключить или понизить нельзя.
LAST_SUPERADMIN_SQLSTATE = "DC001"


class LastSuperadminError(AccessError):
    """Отказ базы: правка сняла бы последнего действующего главного админа (D364).

    Отдельным классом: это ответ по существу («назначьте сначала другого»), а
    не сбой, и экран говорит его словами, а не «база недоступна».
    """


@contextmanager
def _guarding_last_superadmin() -> Iterator[None]:
    """Перевести отказ триггера `0041` в `LastSuperadminError`; остальное — как было."""
    try:
        yield
    except psycopg.Error as exc:
        if exc.sqlstate == LAST_SUPERADMIN_SQLSTATE:
            raise LastSuperadminError(
                "Это последний действующий главный админ: сначала назначьте другого"
            ) from exc
        raise


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
    #: Почта входа через Google (`web_users.email`); `None` — не привязана.
    #: Привязанная закрывает вход паролем и решает, в чью почту ложится
    #: черновик письма (D176).
    email: str | None = None
    #: Язык сайта из «Настроек» (`web_users.web_lang`, `0061`); `None` — язык
    #: стенда. Приезжает только с сессией: вход сразу уводит на страницу, и
    #: она опознаётся сессией заново.
    web_lang: str | None = None
    #: Когда открыта сессия этого запроса (`web_sessions.issued_at`); `None` —
    #: учётка пришла не из сессии (вход, опознание по почте). По нему действия,
    #: создающие долгоживущий доступ, требуют свежего входа (`web.reauth`).
    signed_in_at: datetime | None = None
    #: Имя и фамилия из Google (`web_users.display_name`, `0065`); `None` —
    #: показывается логин. Приезжает с сессией, как язык.
    display_name: str | None = None
    #: Версия фото из Google (`web_users.avatar_etag`, `0065`); `None` — фото
    #: нет, показываются инициалы. Сами байты с сессией не едут.
    avatar_etag: str | None = None
    #: Номер сессии этого запроса (`web_sessions.id`); `None` — учётка не из сессии.
    #: Нужен журналу действий (D462): чем вошёл тот, кто действует.
    session_id: str | None = None
    #: Подключена ли вторая ступень входа (ключ доступа или приложение, D463). Приезжает
    #: с сессией: админу без неё заслон оставляет только экран подключения.
    has_second_factor: bool = False
    #: Сессия выдана после второй ступени; без неё способы входа не снимаются (D463).
    passed_second_step: bool = False
    #: Постоянный отбор стран экрана «Страны» (`web_users.country_filter`, `0077`,
    #: D536); `None` — отбора нет. Приезжает с сессией, как язык.
    country_filter: tuple[str, ...] | None = None


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
    #: Пространство учётки (волна 1, #340): экран админа УК показывает людей
    #: всех пространств одним списком.
    tenant: str = ""
    #: Ключ учётки — для привязки бота на экране людей (D286): привязка
    #: ссылается на учётку, а не на логин.
    id: str = ""
    #: Почта входа через Google (#399): экран людей правит её и обязан видеть,
    #: какая стоит сейчас. `None` — вход через Google закрыт.
    email: str | None = None
    #: Логин того, кто заморозил (D462); `None` — не заморожена, заморожена
    #: командой с машины или до `0063`.
    disabled_by: str | None = None
    #: Имя проверяющего латиницей (D644, `0100`); `None` — не задано, в отчёт идёт
    #: автоперевод имени из Google.
    name_latin: str | None = None


@dataclass(frozen=True)
class OpenedSession:
    """Только что открытая сессия. `token` уезжает в куку и больше нигде не живёт."""

    token: str
    expires_at: datetime
    #: Номер строки сессии: им входы и действия в журналах (D462) ссылаются на неё.
    session_id: str = ""


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
    что у `mcp_access._connected` и `reading.reading`.
    """
    settings = check_environment()
    try:
        with connection(settings.dsn) as conn:
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

    Выбранное подключение сверяется с остальными заданными (#487): ведут в
    разные базы — отказ с названием каждой, а не запись туда, куда пришла
    первая по порядку переменная. Сверяет `managing_dsn` (#515), здесь второй
    раз не нужно.
    """
    _, dsn = managing_dsn(зачем)
    try:
        with psycopg.connect(dsn) as conn:
            yield conn
    except psycopg.Error as exc:
        raise AccessError(f"Не удалось {зачем} ({type(exc).__name__})") from exc


def roles_for(tenant: str) -> tuple[str, ...]:
    """Роли, которые бывают в пространстве (D440).

    УК: главный админ, админ, бизнес-девелопер, контроль, гость — аудитора там
    больше нет. У партнёра две роли (D346): админ пространства (`admin`) и
    сотрудник (`auditor`).
    """
    if canonical_tenant(tenant) == HQ_TENANT:
        return tuple(role for role in ROLES if role not in PARTNER_ONLY_ROLES)
    return tuple(role for role in ROLES if role not in HQ_ONLY_ROLES)


def _checked_role(role: str, *, tenant: str) -> str:
    if role not in ROLES:
        raise AccessError(f"Роль «{role}» не заведена. Есть: {', '.join(ROLES)}")
    if role not in roles_for(tenant):
        if role in PARTNER_ONLY_ROLES:
            raise AccessError(f"Роль «{role}» бывает только у партнёра: в УК её заменил девелопер")
        raise AccessError(f"Роль «{role}» бывает только в пространстве УК (HQ)")
    return role


def _checked_password(password: str) -> str:
    """Пароль или отказ. Одно место на заведение и на смену.

    Стояла только в заведении, и это был обход в один шаг: завести с длинным
    паролем, сменить на короткий. Правило, которое действует на одной двери из
    двух, — не правило.
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AccessError(
            f"Пароль короче {MIN_PASSWORD_LENGTH} знаков. Короткий подбирается по "
            f"украденной базе за вечер, и никакой хеш этого не меняет"
        )
    if len(password) > MAX_PASSWORD_LENGTH:
        raise AccessError(
            f"Пароль длиннее {MAX_PASSWORD_LENGTH} знаков. Предел стоит до scrypt: "
            f"без него одна отправка заказывает стенду лишнюю работу"
        )
    return password


def _checked_login(login: str) -> str:
    имя = login.strip().lower()
    if not LOGIN_PATTERN.match(имя):
        raise AccessError(
            f"Логин «{login}» не годится: латиница в нижнем регистре, цифры, точка, "
            f"дефис и подчёркивание, от 2 до 64 знаков, первый знак — буква или цифра"
        )
    return имя


def _require_tenant(tenant: str) -> None:
    """Пространство учётки обязано быть заведено — иначе отказ (#481).

    Раньше незаведённое пространство здесь же и заводилось ролью владельца
    схемы, и опечатка в коде (`HQQ` вместо `HQ`) давала человеку новое пустое
    пространство вместо отказа. Пространства заводит команда (`make space`),
    строку `HQ` — схема (`0029`).

    Проверка идёт под ролью приложения: читать список пространств ей можно, а
    заводящей человека роли это право незачем.
    """
    with _connected("проверить пространство") as conn, conn.cursor() as cur:
        require_space(cur, tenant, error=AccessError)


def create_account(login: str, *, tenant: str, password: str, role: str | None = None) -> Account:
    """Завести учётку. Роль владельца схемы, повтор логина — отказ.

    Пароль сюда приходит от человека, который учётку заводит, и в репозитории
    не лежит. Возвращается учётка без него: печатать пароль обратно вызывающему
    незачем, а напечатанное уезжает в историю команд.
    """
    имя = _checked_login(login)
    # Роль по умолчанию — САМАЯ УЗКАЯ: в УК гость (только чтение), у партнёра
    # сотрудник. Заводящий человек думает про «завести Петра», а не про объём
    # его прав, и умолчание, дающее больше, раздавало бы админов молча.
    if role is None:
        role = ROLE_GUEST if canonical_tenant(tenant) == HQ_TENANT else ROLE_AUDITOR
    роль = _checked_role(role, tenant=tenant)
    хеш = password_hash(_checked_password(password))
    _require_tenant(tenant)
    with _managing("завести учётку") as conn, conn.cursor() as cur:
        try:
            cur.execute(_INSERT_USER_SQL, (tenant, имя, хеш, роль))
        except psycopg.errors.UniqueViolation as exc:
            raise AccessError(
                f"Логин «{имя}» уже занят — логины единые на всю систему. Возьмите другой"
            ) from exc
        row = cur.fetchone()
    assert row is not None  # noqa: S101 — insert ... returning без строки не бывает
    return Account(id=str(row[0]), login=имя, tenant=tenant, role=роль)


def list_accounts(*, tenant: str | None) -> tuple[AccountRow, ...]:
    """Кто заведён у этого арендатора; `None` — во всех пространствах. Роль владельца схемы."""
    with _managing("перечислить учётки") as conn, conn.cursor() as cur:
        cur.execute(_LIST_USERS_SQL, {"tenant": tenant})
        строки = cur.fetchall()
    return tuple(
        AccountRow(
            login=str(r[0]),
            created_at=r[1],
            disabled_at=r[2],
            role=str(r[3]),
            tenant=str(r[4]),
            id=str(r[5]),
            email=None if r[6] is None else str(r[6]),
            disabled_by=None if r[7] is None else str(r[7]),
            name_latin=None if r[8] is None else str(r[8]),
        )
        for r in строки
    )


def list_spaces() -> tuple[str, ...]:
    """Коды заведённых пространств — для выбора в форме заведения человека.

    Читает роль приложения: таблицу пространств ей читать дано (0004), а
    администратору истории — нет, и расширять его права ради списка кодов незачем.
    """
    with reading("перечень пространств") as conn, conn.cursor() as cur:
        cur.execute(_LIST_SPACES_SQL)
        return tuple(str(r[0]) for r in cur.fetchall())


def _roles_param(only_roles: tuple[str, ...] | None) -> list[str] | None:
    return None if only_roles is None else list(only_roles)


def freeze_account(
    login: str,
    *,
    tenant: str,
    only_roles: tuple[str, ...] | None = None,
    by: str | None = None,
) -> bool:
    """Заморозить учётку (D462). `False` — такой живой учётки нет (или её роль вне `only_roles`).

    Одним запросом ставится отметка и кто заморозил (`by` — `web_users.id`;
    `None` — команда с машины). Остальное делает база в той же транзакции:
    триггеры `0059` (токены MCP) и `0063` (сессии, подключения Claude, привязка
    бота, ссылки привязки). Действует немедленно: опознание сверяет учётку на
    каждом запросе. Последнего главного админа не замораживает —
    `LastSuperadminError` (`0041`).
    """
    with _managing("заморозить учётку") as conn, conn.cursor() as cur:
        with _guarding_last_superadmin():
            cur.execute(
                _FREEZE_USER_SQL,
                {
                    "tenant": tenant,
                    "login": login.strip().lower(),
                    "roles": _roles_param(only_roles),
                    "by": by,
                },
            )
        return cur.rowcount > 0


def unfreeze_account(login: str, *, tenant: str, only_roles: tuple[str, ...] | None = None) -> bool:
    """Разморозить учётку: снять отметку. `False` — такой замороженной учётки нет.

    Сессии, подключения Claude, токены и привязка бота остаются закрытыми:
    человек входит заново, привязывает бота и подключает Claude сам.

    Почта замороженной не держится (F-031, `0075`): пока учётка заморожена, её
    адрес могли отдать другой живой учётке. Тогда разморозка отказывает
    `EmailTakenError` и учётка остаётся замороженной — двух живых учёток на
    одну почту не бывает, и решать, чья она, должен человек, а не порядок строк.
    """
    with _managing("разморозить учётку") as conn, conn.cursor() as cur:
        try:
            cur.execute(
                _UNFREEZE_USER_SQL,
                {
                    "tenant": tenant,
                    "login": login.strip().lower(),
                    "roles": _roles_param(only_roles),
                },
            )
        except psycopg.errors.UniqueViolation as занято:
            raise EmailTakenError(
                "почта этой учётки за время заморозки привязана к другой живой учётке: "
                "снимите её у одной из двух, затем разморозьте"
            ) from занято
        return cur.rowcount > 0


def sign_out_everywhere(token: str) -> bool:
    """«Выйти везде»: закрыть ВСЕ сессии человека (и ту, чей токен предъявлен) и всё, чем он
    подключал Claude. `False` — сессия не живая, ничего не сделано.

    Привязка бота остаётся. Строку выбирает функция базы по живой сессии
    (`0063`): чужую учётку этой дверью не закрыть.
    """
    with _connected("выйти на всех устройствах") as conn, conn.cursor() as cur:
        cur.execute(_SIGN_OUT_EVERYWHERE_SQL, (token,))
        строка = cur.fetchone()
    return bool(строка and строка[0])


def set_role(login: str, *, tenant: str, role: str) -> bool:
    """Назначить роль живой учётке. `False` — такой живой учётки нет.

    Отдельной операцией, а не полем формы заведения: первый админ стенда
    назначается именно ей. Накат `0020` не даёт прав НИКОМУ — кто заведён в
    бою, миграция не знает, и раздача «всем» или «по имени» выдала бы права
    людям, которых на это никто не смотрел.
    """
    return reassign_role(login, tenant=tenant, role=role) is not None


def reassign_role(
    login: str, *, tenant: str, role: str, only_roles: tuple[str, ...] | None = None
) -> str | None:
    """Назначить роль живой учётке и вернуть ПРЕЖНЮЮ. `None` — такой живой учётки нет.

    Прежняя роль нужна следу в журнале приложения (кто, кого, было → стало):
    экран правит роли, а таблицы истории ролей нет и не заводится.
    `only_roles` — нынешняя роль цели обязана быть из них (охват правящего);
    иначе `None`. Последнего главного админа не понижает — `LastSuperadminError`.
    """
    роль = _checked_role(role, tenant=tenant)
    with _managing("сменить роль учётки") as conn, conn.cursor() as cur:
        with _guarding_last_superadmin():
            cur.execute(
                _SET_ROLE_SQL,
                {
                    "tenant": tenant,
                    "login": login.strip().lower(),
                    "role": роль,
                    "roles": _roles_param(only_roles),
                },
            )
        строка = cur.fetchone()
    return None if строка is None else str(строка[0])


def _revoke_oauth(cur: Any, user_id: object, *, reason: str) -> None:
    """Отозвать подключения Claude человека в транзакции вызывающего.

    Сперва гасятся необменянные коды, затем отзываются подключения: обмен кода
    держит строку кода до конца своей транзакции, и отзыв, идущий вторым,
    видит подключение, которое этот обмен успел выпустить (`0054`).
    """
    cur.execute(_EXPIRE_USER_OAUTH_CODES_SQL, (user_id,))
    cur.execute(_REVOKE_USER_OAUTH_SQL, (reason, user_id))


def change_password(login: str, *, tenant: str, password: str) -> bool:
    """Сменить пароль живой учётке. `False` — такой живой учётки нет.

    **Открытые сессии закрываются тем же движением**, и подключения Claude
    отзываются (`0054`). Пароль меняют в ответ на «его кто-то узнал»: если
    вошедший по старому паролю продолжает работать — сам или через Claude,
    которому успел разрешить доступ, — смена не выгнала того, ради кого её
    делали. Всё идёт в той же транзакции — иначе между записью хеша и закрытием
    остаётся окно, в котором старая сессия ещё жива, а новый пароль уже роздан.

    Роль повышенных полномочий: пароль любой учётки меняет команда с машины
    («пароль забыт совсем»). Свой пароль с экрана меняет `change_own_password`
    — другой дверью и без этого права (#324).
    """
    хеш = password_hash(_checked_password(password))
    with _managing("сменить пароль учётки") as conn, conn.cursor() as cur:
        cur.execute(_CHANGE_PASSWORD_SQL, (хеш, tenant, login.strip().lower()))
        строка = cur.fetchone()
        if строка is None:
            return False
        cur.execute(_CLOSE_USER_SESSIONS_SQL, (строка[0],))
        _revoke_oauth(cur, строка[0], reason="password")
        return True


def change_own_password(token: str, *, current: str, new: str) -> bool:
    """Сменить СВОЙ пароль по живой сессии (#324). `False` — текущий не тот или сессии нет.

    Оба отказа — один `False`, и это намеренно: экран не должен подсказывать,
    что именно не так с текущим паролем, а «сессия закрыта» по эту сторону
    формы выглядит так же — пароль не сменён.

    Новый пароль проверяется тем же правилом, что при заведении и смене
    командой (`_checked_password`), — и до похода в базу.

    Роль приложения: прямой записи хеша у неё нет (`0014`). Пишет функция
    базы `change_own_password` (`0032`, путь поиска — `0033`) — только строку
    той сессии, чей токен предъявлен, только если прежний хеш всё ещё на месте,
    и тем же движением закрывает остальные сессии человека, оставляя эту, и
    отзывает его подключения Claude (`0054`).

    Это сужение поверхности, а НЕ защита от пробитого приложения: оно читает
    хеши и открывает сессии само, значит может пройти эту дверь за любого
    (`docs/12-web-admin.md`, «Кто пишет хеш при смене с экрана»).
    """
    _checked_password(new)
    if len(current) > MAX_PASSWORD_LENGTH:
        # Такого текущего нет ни у кого: «не тот», без scrypt и без базы.
        return False
    отпечаток = session_fingerprint(token)
    with _connected("сменить свой пароль") as conn, conn.cursor() as cur:
        cur.execute(_SELECT_OWN_HASH_SQL, (отпечаток,))
        строка = cur.fetchone()
        if строка is None:
            # Сверка всё равно стоит одного scrypt: иначе по времени ответа
            # видно, жива ли сессия, — то же правило, что у `authenticate`.
            password_hash(current)
            return False
        прежний = str(строка[0])
        if not password_matches(current, прежний):
            return False
        cur.execute(_CHANGE_OWN_PASSWORD_SQL, (token, прежний, password_hash(new)))
        итог = cur.fetchone()
    return bool(итог and итог[0])


def normalize_email(email: str) -> str:
    """Почта к единственному виду хранения: без краёв, в нижнем регистре.

    `Ivan@Dodobrands.io` и `ivan@dodobrands.io ` — один человек, и Google
    вернёт ту форму, в какой почту завели у него, а не ту, в какой её завели
    у нас. Без приведения один и тот же человек заводится дважды, а входит
    как кто-то один — и какой именно, решит порядок строк.

    Приводит вызывающий код, а база держит это ограничением (`0021`): так
    забывчивость становится отказом записи, а не тихой второй учёткой.
    """
    приведённая = email.strip().lower()
    if not приведённая:
        raise ValueError("пустая почта: входить по ней некому")
    return приведённая


def set_email(
    login: str, *, tenant: str, email: str | None, only_roles: tuple[str, ...] | None = None
) -> bool:
    """Привязать почту к живой учётке (или снять её, `None`). `False` — учётки нет.

    Снятие — не удаление учётки: человек остаётся и входит паролем. Это и есть
    способ закрыть кому-то вход через Google, не трогая всё остальное.

    Роль владельца схемы, как заведение и роли: право менять круг допущенных
    не выдаётся приложению, иначе кнопка на экране и дыра в нём — одно и то же.

    **Сменилась почта — открытые сессии человека закрываются тем же движением**,
    как при смене пароля командой (`change_password`), и теми же правами
    роли (`0022`). Почту меняют в ответ на «к ней получили доступ чужие», и
    вошедший через Google по прежней почте не должен пережить смену — ни
    сессией, ни подключением Claude (оно отзывается тем же движением). Та же
    почта, сохранённая повторно, — не смена, сессии остаются.
    """
    значение = None if email is None else normalize_email(email)
    with _managing("привязать почту к учётке") as conn, conn.cursor() as cur:
        try:
            cur.execute(
                _SET_EMAIL_SQL,
                {
                    "tenant": tenant,
                    "login": login.strip().lower(),
                    "email": значение,
                    "roles": _roles_param(only_roles),
                },
            )
        except psycopg.errors.UniqueViolation as занято:
            # Не «сбой базы», а ответ по существу: почта уже у кого-то из своих.
            # Экрану «Люди» нужно сказать именно это, иначе админ ищет поломку
            # там, где была опечатка в логине.
            raise EmailTakenError(f"почта {значение} уже привязана к другой учётке") from занято
        строка = cur.fetchone()
        if строка is None:
            return False
        if строка[1]:
            cur.execute(_CLOSE_USER_SESSIONS_SQL, (строка[0],))
            _revoke_oauth(cur, строка[0], reason="email")
        return True


def set_name_latin(
    login: str, *, tenant: str, name: str | None, only_roles: tuple[str, ...] | None = None
) -> bool:
    """Записать имя проверяющего латиницей в карточку (или снять, `None`). `False` — учётки нет.

    Роль владельца схемы или администратора, как почта: грант колоночный (`0100`).
    Сессии не трогаются — имя не доступ.
    """
    with _managing("записать имя латиницей") as conn, conn.cursor() as cur:
        cur.execute(
            _SET_NAME_LATIN_SQL,
            {
                "tenant": tenant,
                "login": login.strip().lower(),
                "name": name,
                "roles": _roles_param(only_roles),
            },
        )
        return cur.fetchone() is not None


def find_by_email(email: str) -> Account | None:
    """Почта от Google → учётка. Незнакомая или отключённая — `None`.

    **Это и есть круг допущенных.** Google подтверждает, что человек владеет
    почтой, и ничего больше: кому можно в админку, решает эта строка в базе.
    Поэтому незнакомая почта обязана получить `None`, а не завести учётку —
    иначе круг допущенных задавал бы Google, а не владелец.

    Отключённые не проходят по тому же условию, что и при входе паролем:
    отзыв доступа обязан закрывать ВСЕ двери сразу, иначе он не отзыв.

    **Пространство приходит из строки учётки (D282).** Почта, как и логин,
    единая на всю систему: опознание ищет её во всей базе, а не в границах
    тенанта стенда — стенд УК опознаёт учётку партнёра ровно так же, как свою.
    """
    try:
        приведённая = normalize_email(email)
    except ValueError:
        return None
    with _connected("опознать по почте") as conn, conn.cursor() as cur:
        cur.execute(_SELECT_USER_BY_EMAIL_SQL, (приведённая,))
        row = cur.fetchone()
    if row is None:
        return None
    return Account(
        id=str(row[0]), login=str(row[1]), tenant=str(row[2]), role=str(row[3]), email=row[4]
    )


#: Исходы сверки номера аккаунта Google: тот же или записан впервые — `ok`;
#: за учёткой другой аккаунт — `other`; живой учётки с этой почтой нет — `missing`.
GoogleSubVerdict = Literal["ok", "other", "missing"]
_CLAIM_GOOGLE_SUB_SQL = "select claim_google_sub(%s, %s, %s)"


def claim_google_sub(email: str, subject: str, *, record: bool) -> GoogleSubVerdict:
    """Тот ли аккаунт Google держит учётку с этой почтой (аудит 12.10, F-027).

    Почта у аккаунта Google не постоянна, номер (`sub`) — постоянен. Первый вход
    записывает номер за живой учёткой с этой почтой, следующие сверяют. Пишет
    функция владельца (`0076`): роль приложения строку `web_users` не правит, а
    выбрать чужую учётку функция не даёт — только ту, чья почта подтверждена
    Google в этом же входе. Смена почты снимает номер (триггер `0076`).

    `record=False` — только сверка, номер не пишется: так вход проверяет аккаунт
    до остальных шагов, а записывает (`record=True`) лишь там, где тут же
    открывает сессию. Иначе вход, который дальше не пустили, занял бы номер.
    """
    номер = subject.strip()
    if not номер:
        raise ValueError("сверка без номера аккаунта Google")
    try:
        приведённая = normalize_email(email)
    except ValueError:
        return "missing"
    with _connected("сверить аккаунт Google") as conn, conn.cursor() as cur:
        cur.execute(_CLAIM_GOOGLE_SUB_SQL, (приведённая, номер, record))
        строка = cur.fetchone()
    итог = None if строка is None else str(строка[0])
    if итог == "ok":
        return "ok"
    if итог == "other":
        return "other"
    if итог == "missing":
        return "missing"
    raise AccessError(f"сверка аккаунта Google вернула незнакомый исход {итог!r}")


def find_by_login(login: str) -> Account | None:
    """Логин → действующая учётка без сверки пароля. Только для входа в демо (D524).

    Вход без пароля открыт одним маршрутом `/demo` и только на стенде демо
    (`WEB_DEMO=1`); продукт этой функцией не опознаёт никого.
    """
    with _connected("найти учётку") as conn, conn.cursor() as cur:
        cur.execute(_SELECT_USER_SQL, (login.strip().lower(),))
        row = cur.fetchone()
    if row is None:
        return None
    return Account(
        id=str(row[0]), login=str(row[1]), tenant=str(row[2]), role=str(row[4]), email=row[5]
    )


def find_by_id(user_id: str) -> Account | None:
    """Номер учётки → учётка. Нет такой или отключена — `None`.

    Для второй ступени входа (D463): первая ступень назвала человека, вторая обязана
    открыть сессию той же учётке — и только если её не заморозили за это время.
    """
    with _connected("найти учётку") as conn, conn.cursor() as cur:
        cur.execute(_SELECT_USER_BY_ID_SQL, (user_id,))
        row = cur.fetchone()
    if row is None:
        return None
    return Account(
        id=str(row[0]), login=str(row[1]), tenant=str(row[2]), role=str(row[3]), email=row[4]
    )


def authenticate(login: str, password: str) -> Account | None:
    """Логин и пароль → учётка. Не тот пароль и нет такой учётки — `None`.

    **Оба отказа неотличимы снаружи, и это намеренно.** Иначе форма входа сама
    сообщает перебором, какие логины заведены.

    Незнакомый логин всё равно стоит одного вычисления scrypt. Без этого ответ
    «такого нет» приходил бы мгновенно, а «пароль не тот» — через десятки
    миллисекунд, и разница по времени рассказала бы ровно то, что предыдущий
    абзац запрещает говорить словами.

    **Пространство приходит из строки учётки (D282).** Логин единый на всю
    систему: опознание ищет его во всей базе, а не в границах тенанта стенда —
    один адрес входа пускает в любое пространство ту учётку, которой оно
    принадлежит.

    Пароль длиннее `MAX_PASSWORD_LENGTH` — `None` сразу, без scrypt: такого
    пароля нет ни у кого, и быстрый отказ не выдаёт, заведён ли логин.
    """
    if len(password) > MAX_PASSWORD_LENGTH:
        return None
    with _connected("сверить учётку") as conn, conn.cursor() as cur:
        cur.execute(_SELECT_USER_SQL, (login.strip().lower(),))
        row = cur.fetchone()
    if row is None:
        password_hash(password)
        return None
    if not password_matches(password, str(row[3])):
        return None
    return Account(
        id=str(row[0]), login=str(row[1]), tenant=str(row[2]), role=str(row[4]), email=row[5]
    )


def open_session(
    account: Account,
    *,
    ip: str | None = None,
    user_agent: str | None = None,
    second_step: bool = False,
    step_waived: bool = False,
) -> OpenedSession:
    """Открыть сессию. Токен возвращается один раз — дальше он живёт в куке.

    `step_waived` — вторая ступень при входе выключена (D485): сессию выдают без неё, но
    `second_step_at` остаётся пустым. Отметку ставит только настоящее доказательство
    (`second_step=True`: ключ доступа, код приложения), и только с ней можно снимать способы.

    **Полную сессию человеку со вторым способом без `second_step=True` не выдаёт сама эта
    функция** (`SecondStepRequiredError`): любой путь входа, нынешний или будущий, упрётся здесь.
    Админ без способа получает сессию, но заслон оставляет ему одно подключение способа.

    `ip` и `user_agent` — откуда вошли (D462): адрес по цепочке доверенных звеньев и
    браузер, усечённый до `MAX_USER_AGENT`. `second_step` — сессия прошла вторую ступень
    (D463): только такой сессии разрешено СНИМАТЬ способы входа.
    """
    token = new_session_token()
    with _connected("открыть сессию") as conn, conn.cursor() as cur:
        cur.execute(
            _OPEN_SESSION_SQL,
            {
                "user": account.id,
                "fp": session_fingerprint(token),
                "ttl": SESSION_TTL,
                "ip": ip,
                "ua": truncate_user_agent(user_agent),
                "second": second_step,
                "waived": step_waived,
            },
        )
        row = cur.fetchone()
    if row is None:
        # У человека есть второй способ, а доказательства второй ступени нет (D463): полная
        # сессия не выдаётся ни одним путём. Проверка — в самом запросе, а не у вызывающих.
        raise SecondStepRequiredError("сессия без второй ступени человеку, у которого она есть")
    return OpenedSession(token=token, expires_at=row[0], session_id=str(row[1]))


def resolve_session(token: str) -> Account | None:
    """Токен из куки → кто вошёл. Закрытая или просроченная сессия, отключённая учётка — `None`.

    Спрашивается на КАЖДЫЙ запрос, а не запоминается на входе: отключение
    учётки и выход обязаны действовать немедленно, а снятый однажды ответ —
    это ровно тот способ, которым «немедленно» превращается в «когда-нибудь».

    Отказ базы уходит отказом (`AccessError`), а не `None`: `None` означает
    «эта кука не действует», а упавшая база означает «мы не смогли посмотреть»,
    и выдать второе за первое — молча выбросить из админки всех и объяснить
    это каждому неверным словом.

    **Пространство приходит из строки учётки (D282).** Сессия несёт своё
    пространство в `Account.tenant`, а не сверяется с тенантом стенда: один
    адрес входа обязан впускать учётку любого пространства.
    """
    with _connected("сверить сессию") as conn, conn.cursor() as cur:
        cur.execute(_RESOLVE_SESSION_SQL, (session_fingerprint(token),))
        row = cur.fetchone()
    if row is None:
        return None
    return Account(
        id=str(row[0]),
        login=str(row[1]),
        tenant=str(row[2]),
        role=str(row[3]),
        email=row[4],
        web_lang=row[5],
        signed_in_at=row[6],
        display_name=row[7],
        avatar_etag=row[8],
        session_id=str(row[9]),
        has_second_factor=bool(row[10]),
        passed_second_step=bool(row[11]),
        country_filter=tuple(row[12]) if row[12] else None,
    )


def close_session(token: str) -> bool:
    """Закрыть сессию. `False` — такой живой сессии не было.

    Это и есть выход. Пометка ставится в базе, поэтому перестаёт работать
    любая копия куки, а не только та вкладка, где нажали кнопку. Обратно
    пометка не снимается — заслон стоит в схеме (`0014`).
    """
    with _connected("закрыть сессию") as conn, conn.cursor() as cur:
        cur.execute(_CLOSE_SESSION_SQL, (session_fingerprint(token),))
        return cur.rowcount > 0
