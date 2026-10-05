"""Куда ведёт строка подключения — и все ли подключения ведут в одну базу (#487).

Подключений у продукта три, и у каждого своя роль: приложение
(`DATABASE_URL`), накат (`DATABASE_ADMIN_URL`) и администратор истории
(`DATABASE_RETRACTION_URL`). Роли разные, а база ОДНА — так их и описывает
`docs/08-deploy.md`. Код этого раньше не проверял нигде, и на стенде, где
переопределили два подключения из трёх, а третье пришло из `.env`, учётка
заводилась в общей тестовой базе: команда отвечала «заведена», вход на стенде
давал 401, и ни одна строка вывода не называла базу, куда шла запись.

Поэтому здесь две вещи, и обе без пароля:

* `target_of` — разобрать строку подключения в «хост, порт, база, роль»,
  ничего не подключая. Это то, что можно напечатать человеку: пароля в нём нет.
* `same_database_or_refuse` — сверить все ЗАДАННЫЕ подключения с выбранным и
  отказать вслух, назвав каждое, если хоть одно ведёт в другую базу.

Сверка строковая: `localhost` и `127.0.0.1` для неё разные хосты. Это
намеренно — отказ из-за разного написания одного хоста громкий и чинится
правкой строки, а пропущенное расхождение баз молчит и пишет в чужую базу.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from psycopg import ProgrammingError
from psycopg.conninfo import conninfo_to_dict

from .config import DATABASE_RETRACTION_URL_VAR, DATABASE_URL_VAR, load_retraction_settings
from .errors import AccessError, ConfigError
from .migrate import DATABASE_ADMIN_URL_VAR, admin_dsn

#: Порт Postgres, когда в строке он не назван, — так же его подставляет libpq.
DEFAULT_PORT = "5432"

#: Все подключения продукта к базе. Порядок — порядок вывода в отказе.
CONNECTION_VARS = (DATABASE_URL_VAR, DATABASE_ADMIN_URL_VAR, DATABASE_RETRACTION_URL_VAR)


@dataclass(frozen=True)
class DatabaseTarget:
    """Куда ведёт подключение. Пароля здесь нет намеренно — это можно печатать."""

    host: str
    port: str
    dbname: str
    user: str

    def same_database(self, other: DatabaseTarget) -> bool:
        """Та же база: хост, порт и имя. Роль не сравнивается — роли и должны быть разные."""
        return (self.host, self.port, self.dbname) == (other.host, other.port, other.dbname)

    def label(self) -> str:
        """`база dodo_audit на db:5432, роль dodo_audit_admin` — для человека, без пароля."""
        host = self.host or "локальный сокет"
        return f"база {self.dbname or '?'} на {host}:{self.port}, роль {self.user or '?'}"


def target_of(dsn: str, *, var: str) -> DatabaseTarget:
    """Разобрать строку подключения из переменной `var`. Не подключается.

    Неразборная строка — `ConfigError` с именем переменной, но БЕЗ самой
    строки: в ней пароль, а текст отказа уходит в терминал и в журнал.
    Имя базы по умолчанию — имя роли, как у libpq.
    """
    try:
        params = conninfo_to_dict(dsn)
    except ProgrammingError:
        raise ConfigError(f"Строка подключения {var} не разбирается") from None
    user = str(params.get("user") or "")
    return DatabaseTarget(
        host=str(params.get("host") or "").lower(),
        port=str(params.get("port") or DEFAULT_PORT),
        dbname=str(params.get("dbname") or user),
        user=user,
    )


def same_database_or_refuse(
    chosen_var: str, chosen_dsn: str, env: Mapping[str, str] | None = None
) -> DatabaseTarget:
    """Цель выбранного подключения — или отказ, если другое заданное ведёт в другую базу.

    Незаданные подключения не сверяются: их отсутствие — отдельный отказ того,
    кто их просит, а не повод отказать здесь.
    """
    src = os.environ if env is None else env
    chosen = target_of(chosen_dsn, var=chosen_var)
    targets = {chosen_var: chosen}
    for var in CONNECTION_VARS:
        dsn = (src.get(var) or "").strip()
        if dsn and var not in targets:
            targets[var] = target_of(dsn, var=var)
    if all(chosen.same_database(t) for t in targets.values()):
        return chosen
    listed = "; ".join(
        f"{var} → {targets[var].label()}" for var in CONNECTION_VARS if var in targets
    )
    raise ConfigError(
        f"Подключения ведут в разные базы: {listed}. Роли у них разные, а база "
        f"обязана быть одна — иначе запись уйдёт не туда, где её потом ищут. "
        f"Поправьте переменную, которая указывает не на ту базу"
    )


def same_database_or_deny(var: str, dsn: str, зачем: str) -> DatabaseTarget:
    """То же, что `same_database_or_refuse`, но отказом двери учёток (`AccessError`)."""
    try:
        return same_database_or_refuse(var, dsn)
    except ConfigError as exc:
        raise AccessError(f"Не удалось {зачем}: {exc}") from None


def managing_dsn(зачем: str) -> tuple[str, str]:
    """Подключение, которым трогают учётки: имя переменной и строка.

    Первая — узкая роль администратора истории, без неё — владелец схемы;
    почему именно так, сказано у `web_access._managing`. Ни той ни другой —
    отказ с названием обеих.
    """
    try:
        return DATABASE_RETRACTION_URL_VAR, load_retraction_settings().dsn
    except ConfigError:
        pass
    dsn = admin_dsn()
    if dsn:
        return DATABASE_ADMIN_URL_VAR, dsn
    raise AccessError(
        f"Не удалось {зачем}: не задано ни DATABASE_RETRACTION_URL, ни "
        f"DATABASE_ADMIN_URL. Учётки трогает роль повышенных полномочий; "
        f"роль приложения этого права не имеет намеренно (D155)"
    )


def managing_target() -> str:
    """Куда пойдёт запись учёток: база, хост, роль и переменная — без пароля (#487).

    Для вывода команды `tools/web_user.py`: она раньше не называла базу вовсе,
    и запись в чужую базу выглядела как успех. Сверка баз та же, что у записи,
    поэтому расхождение команда узнаёт до первого изменения, а не после.
    """
    зачем = "назвать базу учёток"
    var, dsn = managing_dsn(зачем)
    return f"{same_database_or_deny(var, dsn, зачем).label()} ({var})"
