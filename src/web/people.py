"""Правка человека на вкладке «Пользователи»: роль и почта входа через Google (#399).

Раньше почта привязывалась только командой (`tools/web_user.py email`), роль —
тоже. Экран зовёт те же двери базы (`set_role`, `set_email`) под той же ролью
повышенных полномочий, что заведение и отключение.

Здесь — только проверка ввода и перевод исхода в код ответа. Кому можно
править, решает маршрут (`_hq_admin_only` в `app.py`): админ УК, в любом
пространстве — как заведение и отключение. Админ партнёра людьми не управляет,
его права не решены (D288).

«Доверенные почты» (список адресов или правило домена) — открытый вопрос
владельца и здесь не строятся: почта привязывается к уже заведённому человеку
вручную, по одной.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.db.errors import DbError, EmailTakenError

from . import accounts

#: Почта — грубой формой: «что-то@что-то.что-то» без пробелов. Подтверждает её
#: не эта проверка, а Google при входе; здесь ловится опечатка вроде логина в
#: поле почты, которая иначе молча закрыла бы человеку вход через Google.
EMAIL_SHAPE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass(frozen=True)
class Outcome:
    """Исход правки: код для текста (`users.<ключ>` в `texts.py`) и код ответа."""

    key: str
    status: int


def is_self(*, login: str, tenant: str, actor_login: str, actor_tenant: str) -> bool:
    """Та же ли это учётка, что у правящего: пара (пространство, логин).

    Логин сверяется в том виде, в каком его хранит база (без краёв, нижний
    регистр): дверь базы приводит его сама, и «Director» из формы иначе
    прошёл бы мимо сверки и сменил роль самому правящему.
    """
    return tenant == actor_tenant and login.strip().lower() == actor_login.strip().lower()


def change_role(
    *, login: str, tenant: str, role: str, actor_login: str, actor_tenant: str
) -> Outcome:
    """Назначить роль. Свою — нельзя: снять с себя админа значит закрыть экран людей."""
    if role not in accounts.ROLES:
        return Outcome("role.unknown", 400)
    if is_self(login=login, tenant=tenant, actor_login=actor_login, actor_tenant=actor_tenant):
        return Outcome("role.self", 400)
    try:
        назначена = accounts.set_role(login, tenant=tenant, role=role)
    except DbError:
        return Outcome("role.failed", 503)
    return Outcome("role.ok", 200) if назначена else Outcome("edit.missing", 200)


def change_email(*, login: str, tenant: str, email: str) -> Outcome:
    """Привязать почту входа через Google; пустая — снять (пароль и учётка остаются)."""
    почта = email.strip()
    if почта and not EMAIL_SHAPE.match(почта):
        return Outcome("email.shape", 400)
    try:
        сделано = accounts.set_email(login, tenant=tenant, email=почта or None)
    except EmailTakenError:
        return Outcome("email.taken", 409)
    except DbError:
        return Outcome("email.failed", 503)
    if not сделано:
        return Outcome("edit.missing", 200)
    return Outcome("email.ok" if почта else "email.removed", 200)
