"""Свой профиль с экрана «Настройки» (D447): почта Google и язык сайта — уровень базы.

Пишут функции базы (`0061`), роль приложения прямой записи в `web_users` не
имеет. Каждой функции предъявляется ТОКЕН сессии из куки, и строку учётки
выбирает она сама — поэтому ни одна дверь здесь не принимает ключ учётки.

**Метка привязки одноразовая и своя.** `begin_google_link` записывает метку
за сессией, `finish_google_link` гасит её тем же движением, что пишет почту:
повтор метки или возврат от Google в чужой сессии получают `state`, а не
привязку.

**Снятие почты требует пароля.** После снятия человек входит паролем; не зная
его, он запер бы себя. Пароль сверяется здесь (scrypt живёт в коде), а функция
базы снимает почту, только если сверенный хеш всё ещё стоит на учётке.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Literal

import psycopg

from .config import check_environment
from .errors import AccessError
from .pool import connection
from .web_access import MAX_PASSWORD_LENGTH, normalize_email, password_hash, password_matches
from .web_access import session_fingerprint as _fingerprint

LinkResult = Literal["ok", "session", "state", "linked", "taken"]
UnlinkResult = Literal["ok", "none", "denied"]

_LINK_RESULTS: frozenset[str] = frozenset({"ok", "session", "state", "linked", "taken"})
_UNLINK_RESULTS: frozenset[str] = frozenset({"ok", "none", "denied"})

_BEGIN_SQL = "select begin_own_google_link(%s, %s, %s)"
_FINISH_SQL = "select finish_own_google_link(%s, %s, %s)"
_UNLINK_SQL = "select unlink_own_google(%s, %s)"
_SET_LANG_SQL = "select set_own_web_lang(%s, %s)"

#: Свой хеш — по живой сессии, тем же условием, что у опознания.
_SELECT_OWN_HASH_SQL = """
    select u.password_hash
      from web_sessions s
      join web_users u on u.id = s.user_id
     where s.fingerprint = %s
       and s.closed_at is null
       and s.expires_at > now()
       and u.disabled_at is null
"""


@contextmanager
def _connected(зачем: str) -> Iterator[psycopg.Connection[Any]]:
    """Роль приложения. Наружу — тип исключения драйвера, не текст (в нём бывает DSN)."""
    settings = check_environment()
    try:
        with connection(settings.dsn) as conn:
            yield conn
    except psycopg.Error as exc:
        raise AccessError(f"Не удалось {зачем} ({type(exc).__name__})") from exc


def _one(sql: str, params: tuple[object, ...], зачем: str) -> object:
    with _connected(зачем) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        строка = cur.fetchone()
    return None if строка is None else строка[0]


def begin_google_link(token: str, *, state: str, ttl_seconds: int) -> bool:
    """Записать метку привязки за живой сессией. `False` — сессии нет."""
    return bool(_one(_BEGIN_SQL, (token, state, ttl_seconds), "начать привязку почты Google"))


def finish_google_link(token: str, *, state: str, email: str) -> LinkResult:
    """Погасить метку и привязать почту своей учётке. Исход — код, не исключение."""
    итог = str(_one(_FINISH_SQL, (token, state, normalize_email(email)), "привязать почту Google"))
    if итог not in _LINK_RESULTS:
        raise AccessError(f"функция привязки вернула незнакомый исход {итог!r}")
    return итог  # type: ignore[return-value]


def unlink_google(token: str, *, current: str) -> UnlinkResult:
    """Снять свою почту Google, если `current` — действующий пароль учётки.

    `denied` — сессии нет или пароль не тот: снаружи это одно и то же, как у
    смены своего пароля. Незнакомая сессия всё равно стоит одного scrypt —
    иначе по времени ответа видно, жива ли она.
    """
    if len(current) > MAX_PASSWORD_LENGTH:
        return "denied"
    хеш = _one(_SELECT_OWN_HASH_SQL, (_fingerprint(token),), "прочитать свою учётку")
    if хеш is None:
        password_hash(current)
        return "denied"
    if not password_matches(current, str(хеш)):
        return "denied"
    итог = str(_one(_UNLINK_SQL, (token, str(хеш)), "снять почту Google"))
    if итог not in _UNLINK_RESULTS:
        raise AccessError(f"функция снятия почты вернула незнакомый исход {итог!r}")
    return итог  # type: ignore[return-value]


def set_web_lang(token: str, lang: str) -> bool:
    """Сохранить язык сайта своей учётке. `False` — сессии нет.

    Какие языки заведены, проверяет вызывающий (`texts.UI_LANGS`): база держит
    только форму, чтобы третий язык добавлялся словарём, без миграции.
    """
    return bool(_one(_SET_LANG_SQL, (token, lang), "сохранить язык сайта"))
