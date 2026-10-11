"""Правка человека на вкладке «Пользователи»: роль и почта входа через Google (#399).

Раньше почта привязывалась только командой (`tools/web_user.py email`), роль —
тоже. Экран зовёт те же двери базы (`reassign_role`, `set_email`) под той же ролью
повышенных полномочий, что заведение и отключение.

Здесь — проверка ввода, перевод исхода в код ответа и круг людей «контроля».
Кому можно править, решает правило охвата (`access_policy.py`, #585, D364), а
сверяет маршрут; сюда приходит уже разрешённая цель и `only_roles` — охват по
роли цели, который дверь базы держит условием в самом запросе.

«Доверенные почты» (список адресов или правило домена) — открытый вопрос
владельца и здесь не строятся: почта привязывается к уже заведённому человеку
вручную, по одной.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from src.db.errors import DbError, EmailTakenError

from . import accounts

#: След правки людей — строкой журнала приложения, без отдельной таблицы:
#: кто правил, кого, было → стало. Сам адрес почты в журнал не пишется —
#: только факт, что почту задали или сняли. Людям ничего не отправляется.
logger = logging.getLogger(__name__)

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
    *,
    login: str,
    tenant: str,
    role: str,
    actor_login: str,
    actor_tenant: str,
    only_roles: tuple[str, ...] | None = None,
) -> Outcome:
    """Назначить роль. Свою — нельзя: снять с себя админа значит закрыть экран людей."""
    if role not in accounts.roles_for(tenant):
        return Outcome("role.unknown", 400)
    if is_self(login=login, tenant=tenant, actor_login=actor_login, actor_tenant=actor_tenant):
        return Outcome("role.self", 400)
    try:
        прежняя = accounts.reassign_role(login, tenant=tenant, role=role, only_roles=only_roles)
    except accounts.LastSuperadminError:
        return Outcome("role.last_super", 409)
    except DbError:
        return Outcome("role.failed", 503)
    if прежняя is None:
        return Outcome("edit.missing", 200)
    logger.info(
        "люди: роль сменена; правил %s/%s, кому %s/%s, было %s, стало %s",
        actor_tenant,
        actor_login,
        tenant,
        login.strip().lower(),
        прежняя,
        role,
    )
    return Outcome("role.ok", 200)


def change_email(
    *,
    login: str,
    tenant: str,
    email: str,
    actor_login: str,
    actor_tenant: str,
    only_roles: tuple[str, ...] | None = None,
) -> Outcome:
    """Привязать почту входа через Google; пустая — снять (пароль и учётка остаются)."""
    почта = email.strip()
    if почта and not EMAIL_SHAPE.match(почта):
        return Outcome("email.shape", 400)
    try:
        сделано = accounts.set_email(
            login, tenant=tenant, email=почта or None, only_roles=only_roles
        )
    except EmailTakenError:
        return Outcome("email.taken", 409)
    except DbError:
        return Outcome("email.failed", 503)
    if not сделано:
        return Outcome("edit.missing", 200)
    logger.info(
        "люди: почта входа через Google %s; правил %s/%s, кому %s/%s",
        "задана" if почта else "снята",
        actor_tenant,
        actor_login,
        tenant,
        login.strip().lower(),
    )
    return Outcome("email.ok" if почта else "email.removed", 200)
