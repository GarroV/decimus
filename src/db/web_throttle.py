"""Ограничитель перебора пароля на форме входа (T325, решения D154 и D155).

Дверь блока `db` для одного вопроса: «этому можно ещё раз попробовать пароль
или уже нет». Опознанием и сессиями занимается соседний `web_access`; здесь не
знают ни про учётки, ни про пароли — только про то, сколько неудач подряд
пришло с адреса и сколько прилетело на логин.

**ЗАПРЕТ, А НЕ ЗАДЕРЖКА.** Растущая пауза перед ответом выглядит мягче, но на
синхронном сервере она — способ уронить админку целиком: waitress держит
ограниченный пул потоков, и полсотни запросов, каждый из которых спит минуту,
занимают этот пул на минуту для всех, включая тех, кто знает пароль.
Ограничитель обязан делать запросы ДЕШЕВЛЕ, а не дороже, поэтому запертый
ключ получает отказ немедленно и не доходит до сверки пароля вовсе — то есть
не платится и scrypt (16 МиБ и десятки миллисекунд на попытку, сам по себе
годный рычаг перегрузки).

**СЧИТАЮТСЯ ДВА КЛЮЧА, И НУЖНЫ ОБА.** По логину ловится перебор с меняющихся
адресов, по адресу — перебор по разным логинам. Порог у адреса заметно выше:
за одним адресом бывает контора целиком, а за туннелем — вообще все (см.
`WEB_TRUSTED_PROXIES` в `src/web/config.py`, без него счётчик по адресу
становится общим на всех).

**СРОК ЗАПРЕТА НЕ ХРАНИТСЯ, А СЧИТАЕТСЯ.** В базе лежит число неудач и время
последней; запрет — функция от них (`lock_for`). Отдельная колонка «заперт до»
была бы вторым местом, где записан тот же факт, и разъехалась бы с первым
молча.

**ЗАПЕРТЫЙ КЛЮЧ ОТКРЫВАЕТСЯ ВРЕМЕНЕМ ИЛИ РУКОЙ (T328).** Учётной команды
«разблокировать» здесь не было намеренно — СНЯТО 18.09.2026, решение D158:
посторонний, знающий логин администратора, держит его запертым сколь угодно
долго, посылая запрос раз в час, и пароль для этого не нужен вовсе. Сам по
себе запрет по-прежнему проходит по времени; вдобавок его снимает команда
(`tools/web_unlock.py`) — и снимает РОЛЬ АДМИНИСТРАТОРА ИСТОРИИ
(`src/db/web_unlock.py`), а не роль приложения: иначе тот, кто вошёл, снимал
бы запреты кому угодно.

**ПУСКАЕТ И СЧИТАЕТ ОДНА ОПЕРАЦИЯ (T328).** Раньше вопрос «пускать ли» и
запись неудачи были двумя походами в базу, а между ними стояла сверка пароля —
самая долгая часть запроса. Параллельные попытки успевали прочитать одно и то
же число и проходили заслон все разом: за волну проходило «порог + число
потоков − 1» попыток вместо порога. Теперь решение и запись идут ОДНОЙ
транзакцией под замком на ключ (`admit_attempt`), а сверка пароля остаётся
снаружи замка: обещание «после пятой — сразу отказ» держится базой, а не
удачным порядком событий.

**АДРЕС ПРИВОДИТСЯ К КАНОНУ ДО ОТПЕЧАТКА (T328).** `2001:db8::1` и
`2001:db8:0:0:0:0:0:1` — один и тот же адрес, и ключ у них обязан быть один:
иначе счётчик по адресу обходится записью того же адреса в другом виде.

**ПРОМАХ ЧЕЛОВЕКА СТОИТ МИНУТУ, УПОРСТВО — ЧАС.** Первый запрет короткий:
человек, забывший раскладку, не должен получать наказание длиной в рабочий
день. Каждая следующая неудача после запрета удлиняет срок (`LOCK_STEPS`),
поэтому перебор упирается в потолок из нескольких попыток в час, а опечатка —
нет.
"""

from __future__ import annotations

import hashlib
import ipaddress
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import psycopg

from .config import check_environment
from .errors import AccessError

#: Что считаем. Коды, а не формулировки: они уезжают в схему (`0015`).
SCOPE_ADDRESS = "address"
SCOPE_LOGIN = "login"
SCOPES = (SCOPE_ADDRESS, SCOPE_LOGIN)

#: Сколько неудач подряд ключ переживает без запрета.
#:
#: У логина порог человеческий: пять промахов — это уже не «не туда нажал».
#: У адреса он выше, потому что за одним адресом законно живёт несколько
#: человек (контора за одним выходом, туннель), и запирать их всех из-за
#: чужой опечатки нельзя. Двадцать неудач за час с одного адреса человеком не
#: объясняются.
FAILURES_BEFORE_LOCK = {SCOPE_LOGIN: 5, SCOPE_ADDRESS: 20}

#: Сроки запрета: первый, второй, третий, дальше потолок. Растут, а не стоят
#: на месте: постоянный короткий запрет замедляет перебор в разы, а растущий —
#: в тысячи раз, и при этом стоит одну минуту тому, кто просто ошибся.
LOCK_STEPS = (
    timedelta(minutes=1),
    timedelta(minutes=5),
    timedelta(minutes=15),
    timedelta(minutes=60),
)

#: Столько тишины — и счётчик забыт: неудачи перестают складываться, ключ
#: начинает с чистого листа.
#:
#: ОБЯЗАН БЫТЬ БОЛЬШЕ САМОГО ДЛИННОГО ЗАПРЕТА. Иначе счётчик забывался бы
#: РАНЬШЕ, чем истекает запрет, посчитанный по нему же, — и ключ открывался бы
#: досрочно сам, причём тем скорее, чем злее был перебор. Проверку этого
#: держит тест, а не внимательность: оба числа правятся здесь, рядом, и
#: испортить их правкой одного проще всего.
FORGET_AFTER = LOCK_STEPS[-1] + timedelta(minutes=15)

#: Длина отпечатка SHA-256 шестнадцатеричной записью — ровно то, что принимает
#: колонка `key_fingerprint`.
FINGERPRINT_LENGTH = 64

#: Пара «что считаем → отпечаток ключа» на одну попытку входа. Отдельным именем
#: затем, что по этому порядку берутся замки (`attempt_transaction`).
_Keys = tuple[tuple[str, str], ...]

#: Пространство рекомендательных замков. Замки в Postgres общие на всю базу, и
#: без своего номера счётчик попыток делил бы их с любым другим кодом, который
#: однажды возьмёт замок по хешу строки. Число — номер задачи, чтобы владельца
#: замка было видно в `pg_locks` без похода в исходники.
ADVISORY_NAMESPACE = 325

#: Замок на ключ, а не на строку: `select ... for update` не запирает строку,
#: которой ещё нет, — а первый залп на свежий логин приходит именно на такую.
_ADVISORY_LOCK_SQL = "select pg_advisory_xact_lock(%s, hashtext(%s))"

_BUMP_SQL = """
    insert into web_login_attempts (tenant_code, scope, key_fingerprint, failures, updated_at)
    values (%s, %s, %s, 1, now())
    on conflict (tenant_code, scope, key_fingerprint) do update
       set failures = case when web_login_attempts.updated_at < %s then 1
                           else web_login_attempts.failures + 1 end,
           updated_at = now()
    returning failures, updated_at
"""

_LOAD_SQL = """
    select failures, updated_at
      from web_login_attempts
     where tenant_code = %s and scope = %s and key_fingerprint = %s
"""

_FORGET_SQL = """
    delete from web_login_attempts
     where tenant_code = %s and scope = %s and key_fingerprint = %s
"""

_DROP_STALE_SQL = "delete from web_login_attempts where updated_at < %s"


@dataclass(frozen=True)
class Counter:
    """Строка счётчика: сколько неудач подряд и когда была последняя."""

    failures: int
    updated_at: datetime


@dataclass(frozen=True)
class Verdict:
    """Пускать ли пробовать пароль. `retry_after` больше нуля — нет, не пускать."""

    retry_after: timedelta = timedelta(0)

    @property
    def locked(self) -> bool:
        return self.retry_after > timedelta(0)

    @property
    def retry_after_seconds(self) -> int:
        """Для заголовка `Retry-After` — в секундах и вверх, а не вниз.

        Вниз — это ответ «приходи через ноль секунд» на запрет длиной в
        полсекунды, то есть приглашение долбиться в закрытую дверь.
        """
        return max(1, -(-int(self.retry_after.total_seconds()) // 1))

    @property
    def retry_after_minutes(self) -> int:
        """Для человека на экране — в минутах и вверх. Ноль минут не бывает."""
        return max(1, -(-self.retry_after_seconds // 60))


@dataclass(frozen=True)
class Attempt:
    """Чем кончилась заявка на попытку входа.

    `admitted` — дошло ли дело до сверки пароля. `verdict` — запрет, который
    действует СЕЙЧАС: для недопущенной попытки это остаток чужого запрета, для
    допущенной — запрет, наступивший из-за неё самой (ноль, если не наступил).
    """

    admitted: bool
    verdict: Verdict


def lock_for(failures: int, *, scope: str) -> timedelta:
    """Насколько заперт ключ, у которого `failures` неудач подряд. Ноль — не заперт."""
    порог = FAILURES_BEFORE_LOCK[scope]
    if failures < порог:
        return timedelta(0)
    return LOCK_STEPS[min(failures - порог, len(LOCK_STEPS) - 1)]


def verdict_of(counter: Counter | None, *, scope: str, now: datetime | None = None) -> Verdict:
    """Приговор по строке счётчика. Чистая функция: в базу не ходит.

    Отдельно от запросов затем, что правило «после скольких неудач и насколько»
    — это решение продукта, и проверяется оно арифметикой за миллисекунды, а не
    поднятой базой и ожиданием часа.
    """
    if counter is None:
        return Verdict()
    запрет = lock_for(counter.failures, scope=scope)
    if not запрет:
        return Verdict()
    осталось = (counter.updated_at + запрет) - (now or datetime.now(UTC))
    return Verdict(осталось) if осталось > timedelta(0) else Verdict()


def key_fingerprint(value: str) -> str:
    """Ключ счётчика → отпечаток, который единственный попадает в базу.

    Тайны в отпечатке нет и не предполагается: и адрес, и логин перебираются по
    нему за секунды. Смысл в другом. Во-первых, длина строки в базе перестаёт
    зависеть от того, что прислал посторонний. Во-вторых, дословно введённое в
    поле «логин» в базу не попадает — а вводят туда, среди прочего, пароль от
    соседней системы.
    """
    отпечаток = hashlib.sha256(value.strip().lower().encode("utf-8")).hexdigest()
    if len(отпечаток) != FINGERPRINT_LENGTH:
        raise AccessError(
            f"отпечаток вышел длиной {len(отпечаток)} вместо {FINGERPRINT_LENGTH} — "
            f"схема такой не примет"
        )
    return отпечаток


def canonical_address(value: str) -> str:
    """Адрес → его единственная запись. Не адрес — строка как есть.

    Один и тот же адрес приходит записанным по-разному: `2001:db8::1` и
    `2001:db8:0:0:0:0:0:1`, `::ffff:203.0.113.7` и `203.0.113.7`. До T328
    отпечаток считался от строки, поэтому каждая запись заводила СВОЙ счётчик,
    и порог по адресу обходился сменой записи — счётчик при этом выглядел
    работающим.

    Не разобранное `ipaddress` не отбрасывается: сюда приходит и `unknown`
    (сокет без адреса, тестовый клиент), и оно обязано считаться таким же
    ключом, как всё остальное, — общим, но считаться.
    """
    попытка = value.strip()
    try:
        адрес = ipaddress.ip_address(попытка)
    except ValueError:
        return попытка
    if isinstance(адрес, ipaddress.IPv6Address) and адрес.ipv4_mapped is not None:
        # `::ffff:203.0.113.7` — это тот же IPv4-адрес, записанный по-другому.
        # Оставить их разными ключами значило бы дать перебирающему второй
        # запас попыток на тот же адрес одной строкой в заголовке.
        return str(адрес.ipv4_mapped)
    return str(адрес)


@contextmanager
def _connected(зачем: str) -> Iterator[psycopg.Connection[Any]]:
    """Подключение роли приложения. Отказ базы — `AccessError`, а не тишина.

    Наружу уходит ТИП исключения драйвера, а не его текст: в тексте psycopg
    может оказаться строка подключения целиком. Тот же приём и та же причина,
    что у `web_access._connected` и `queries._reading`.
    """
    settings = check_environment()
    try:
        with psycopg.connect(settings.dsn) as conn:
            yield conn
    except psycopg.Error as exc:
        raise AccessError(f"Не удалось {зачем} ({type(exc).__name__})") from exc


def load_counter(*, tenant: str, scope: str, fingerprint: str) -> Counter | None:
    """Строка счётчика или `None`, если по этому ключу неудач не числится."""
    with _connected("прочитать счётчик попыток") as conn, conn.cursor() as cur:
        cur.execute(_LOAD_SQL, (tenant, scope, fingerprint))
        row = cur.fetchone()
    return None if row is None else Counter(failures=int(row[0]), updated_at=row[1])


class AttemptStore(Protocol):
    """Хранилище счётчика на время одной попытки. Правило живёт не здесь.

    Ровно та граница, которую подменяет набор тестов: правило «после скольких
    неудач и насколько» остаётся продуктовым, а таблица заменяется памятью.
    Подменить заодно и правило значило бы проверять оснастку.
    """

    def load(self, *, scope: str, fingerprint: str) -> Counter | None:
        """Строка счётчика или `None`."""

    def bump(self, *, scope: str, fingerprint: str) -> Counter:
        """Записать попытку и вернуть счётчик ПОСЛЕ неё."""


class _Rows:
    """Строки счётчика в уже открытой транзакции. Своих подключений не берёт."""

    def __init__(self, cur: psycopg.Cursor[Any], *, tenant: str, forget_before: datetime) -> None:
        self._cur = cur
        self._tenant = tenant
        self._forget_before = forget_before

    def load(self, *, scope: str, fingerprint: str) -> Counter | None:
        self._cur.execute(_LOAD_SQL, (self._tenant, scope, fingerprint))
        row = self._cur.fetchone()
        return None if row is None else Counter(failures=int(row[0]), updated_at=row[1])

    def bump(self, *, scope: str, fingerprint: str) -> Counter:
        """Прибавление идёт одним запросом, а не «прочитали, посчитали, записали».

        Давно молчащий ключ начинает с единицы: условие забвения уезжает в тот
        же запрос параметром, чтобы решение «забыть» и решение «прибавить»
        принимались в одном месте и об одной и той же строке.
        """
        self._cur.execute(_BUMP_SQL, (self._tenant, scope, fingerprint, self._forget_before))
        row = self._cur.fetchone()
        assert row is not None  # noqa: S101 — insert ... returning без строки не бывает
        return Counter(failures=int(row[0]), updated_at=row[1])


@contextmanager
def attempt_transaction(*, tenant: str, keys: _Keys) -> Iterator[AttemptStore]:
    """Одна транзакция на попытку: ключи под замком, строки доступны.

    **ЗАМОК БЕРЁТСЯ ДО ЧТЕНИЯ, И В ЭТОМ ВЕСЬ СМЫСЛ.** Без него параллельные
    попытки читают одно и то же число неудач и проходят заслон все разом —
    ровно то, что здесь чинится (T328). Замок рекомендательный
    (`pg_advisory_xact_lock`), потому что запирать нужно и ключ, строки у
    которого ещё нет вовсе: `select ... for update` на несуществующей строке не
    запирает ничего, и первый же залп на свежий логин проходит целиком.

    **ПОРЯДОК ЗАМКОВ ПОСТОЯННЫЙ** — тот, в котором `_keys` перечисляет ключи
    (адрес, потом логин). Два замка, взятые в разном порядке, — это взаимная
    блокировка; постоянный порядок её исключает.

    Замок держится до конца транзакции, а сверка пароля идёт СНАРУЖИ нас:
    внутри остаются два чтения и две записи, то есть доли миллисекунды. Держать
    замок на время scrypt значило бы выстроить попытки в очередь длиной в
    шестнадцать мегабайт памяти на каждую.
    """
    забыть_старше = datetime.now(UTC) - FORGET_AFTER
    with _connected("проверить и записать попытку входа") as conn, conn.cursor() as cur:
        for scope, отпечаток in keys:
            ключ = f"{tenant}\x1f{scope}\x1f{отпечаток}"
            cur.execute(_ADVISORY_LOCK_SQL, (ADVISORY_NAMESPACE, ключ))
        yield _Rows(cur, tenant=tenant, forget_before=забыть_старше)
        # Чистка идёт попутно и под ту же запись: отдельного расписания у
        # админки нет, а таблица иначе растёт ровно от того, что в неё пишет
        # посторонний, — то есть неограниченно.
        cur.execute(_DROP_STALE_SQL, (забыть_старше,))


def forget_counter(*, tenant: str, scope: str, fingerprint: str) -> None:
    """Забыть неудачи по ключу. Зовётся при удачном входе."""
    with _connected("обнулить счётчик попыток") as conn, conn.cursor() as cur:
        cur.execute(_FORGET_SQL, (tenant, scope, fingerprint))


def _keys(address: str, login: str) -> _Keys:
    """Пара «что считаем → отпечаток ключа» для одной попытки входа.

    Порядок постоянный: адрес, потом логин. На нём держится отсутствие взаимной
    блокировки в `attempt_transaction`.
    """
    return (
        (SCOPE_ADDRESS, key_fingerprint(canonical_address(address))),
        (SCOPE_LOGIN, key_fingerprint(login)),
    )


def _строже(приговоры: list[Verdict]) -> Verdict:
    """Заперт хоть один ключ — заперта попытка."""
    return max(приговоры, key=lambda v: v.retry_after)


def admit_attempt(*, tenant: str, address: str, login: str) -> Attempt:
    """Пустить попытку к сверке пароля — и тем же движением её записать.

    Одна операция вместо двух намеренно. Раньше «спросить» и «записать» стояли
    по разные стороны от сверки пароля, и параллельные попытки успевали
    прочитать одно и то же число: за волну проходило «порог + число потоков −
    1» попыток вместо порога (T328). Теперь между решением и записью не
    происходит ничего.

    Записывается ПОПЫТКА, а не подтверждённая неудача: сверки ещё не было, и
    её исход этой записи не меняет. Удачный вход строку удаляет целиком
    (`note_success`), поэтому «неудач подряд» и «попыток подряд без удачи» —
    для счётчика одно и то же число.

    Приговор возвращается ПОСЛЕ записи: запрет обязан наступать с той же
    попытки, которая его вызвала, иначе пятая неудача отвечает «пароль не тот»,
    и закрытая дверь обнаруживается только на шестой.
    """
    ключи = _keys(address, login)
    with attempt_transaction(tenant=tenant, keys=ключи) as строки:
        было = [
            verdict_of(строки.load(scope=scope, fingerprint=отпечаток), scope=scope)
            for scope, отпечаток in ключи
        ]
        запрет = _строже(было)
        if запрет.locked:
            # Запертый не платит ни записи, ни сверки пароля — в этом и смысл
            # ограничителя: поток попыток обязан становиться ДЕШЕВЛЕ.
            return Attempt(admitted=False, verdict=запрет)
        стало = [
            verdict_of(строки.bump(scope=scope, fingerprint=отпечаток), scope=scope)
            for scope, отпечаток in ключи
        ]
    return Attempt(admitted=True, verdict=_строже(стало))


def note_success(*, tenant: str, address: str, login: str) -> None:
    """Забыть неудачи обоих ключей: человек доказал, что он тот самый.

    Адрес забывается вместе с логином намеренно. Сохранить его — значит
    запереть вход конторе, где один человек трижды ошибся, а остальные
    работают; а тому, у кого есть верный пароль, перебор не нужен вовсе.
    """
    for scope, отпечаток in _keys(address, login):
        forget_counter(tenant=tenant, scope=scope, fingerprint=отпечаток)
