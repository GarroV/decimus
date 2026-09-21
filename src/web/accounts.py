"""Учётки админки так, как их видит экран (T338, #322).

Дверь веба в блок `db` для одного вопроса: «кто заведён у этого арендатора и
что с этим может сделать вошедший». Своей логики прав здесь нет и не будет —
роль приезжает вместе с опознанием, а заслон стоит на маршруте.

ПОЧЕМУ ПАРОЛЬ ГЕНЕРИРУЕТ СИСТЕМА, А НЕ ВВОДИТ ЧЕЛОВЕК. Пароль, придуманный
заводящим, выбирается так, чтобы его было удобно продиктовать, — и именно
такой подбирается по украденной базе за вечер. Заодно исчезает соблазн завести
всем одинаковый. Показывается он ровно один раз, на странице ответа: в адрес
он не попадает, потому что адреса остаются в истории браузера и в журналах
обратного прокси.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass

from src.db.web_access import (
    ROLE_ADMIN,
    ROLE_AUDITOR,
    ROLES,
    AccountRow,
    create_account,
    disable_account,
    list_accounts,
    set_role,
)

__all__ = [
    "ROLES",
    "ROLE_ADMIN",
    "ROLE_AUDITOR",
    "AccountRow",
    "Added",
    "add",
    "disable",
    "everyone",
    "set_role",
]

#: Длина сгенерированного пароля в байтах случайности. 18 байт — 24 знака в
#: base64url; короче делать нечего, а длиннее человеку неудобно переносить
#: руками, и он начнёт заводить свои.
_PASSWORD_BYTES = 18


@dataclass(frozen=True)
class Added:
    """Заведённая учётка и её пароль — для показа ОДИН раз."""

    login: str
    role: str
    password: str


def everyone(*, tenant: str) -> tuple[AccountRow, ...]:
    """Кто заведён у арендатора, вместе с отключёнными.

    Отключённые не прячутся: вопрос «у кого был доступ» задают после
    инцидента, и пустое место на него не отвечает.
    """
    return list_accounts(tenant=tenant)


def add(login: str, *, tenant: str, role: str = ROLE_AUDITOR) -> Added:
    """Завести человека и вернуть его пароль — единственный раз, когда он виден."""
    пароль = secrets.token_urlsafe(_PASSWORD_BYTES)
    заведённая = create_account(login, tenant=tenant, password=пароль, role=role)
    return Added(login=заведённая.login, role=заведённая.role, password=пароль)


def disable(login: str, *, tenant: str) -> bool:
    """Отключить учётку. `False` — такой живой учётки нет."""
    return disable_account(login, tenant=tenant)
