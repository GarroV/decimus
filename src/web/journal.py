"""Журналы входов и действий на стороне веба (D462, `0067`).

**Входы.** `login_origin` даёт откуда пришли: адрес по цепочке доверенных звеньев
(`remote.client_address`, а не сырой `X-Forwarded-For`) и браузер. Записывают
дверь входа (`auth.py`), согласие Claude (`oauth.py`) и выпуск личного токена
(`settings_screen.py`).

**Действия — одной точкой.** `install` вешает ОДИН `after_request`: любой запрос
записи (POST, PUT, PATCH, DELETE) вошедшего админа или главного админа попадает в
журнал, какой бы маршрут его ни обслужил. Маршруты о журнале не знают, поэтому
новый маршрут покрыт с первого дня, а забыть шаг нечем. Что записывается: кто
(учётка, роль, пространство), чем вошёл (сессия), откуда, код действия (имя
маршрута), сводка цели и код ответа. Сводка собирается правилом по именам полей
(`src/domain/journal.py`): пароль, токен, ключ, почта и свободный текст остаются без
значения. Отказ (403, 4xx) пишется так же, как успех: попытку важно видеть.

Запись не меняет ответ: действие уже выполнено, и отказ журнала уходит в журнал
процесса (`db.journals`), а не человеку.
"""

from __future__ import annotations

from typing import Any

from flask import Flask, Response, request
from werkzeug.exceptions import HTTPException

from src.db import journals
from src.domain.journal import (
    DOOR_WEB,
    JOURNALED_ROLES,
    summarize_target,
    truncate_user_agent,
)

from .config import Settings
from .remote import UNKNOWN, client_address

#: Подключение и снятие способов входа пишутся в журнал действий КАЖДОЙ роли, а не только
#: админской (D463): человек, чей ключ добавили или сняли, должен видеть это в следах.
SECOND_FACTOR_ENDPOINTS = frozenset(
    {
        "security_passkey_register",
        "security_passkey_delete",
        "security_totp_confirm",
        "security_totp_remove",
        "security_backup_generate",
    }
)

#: Методы, которые считаются изменением состояния.
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def client_ip(conf: Settings) -> str | None:
    """Адрес клиента по цепочке доверенных звеньев; не определён — `None`."""
    адрес = client_address(trusted_proxies=conf.trusted_proxies)
    return None if адрес == UNKNOWN else адрес


def login_origin(conf: Settings) -> tuple[str | None, str | None]:
    """Откуда пришёл запрос: адрес и браузер (усечённый)."""
    return client_ip(conf), truncate_user_agent(request.headers.get("User-Agent"))


def _body_fields() -> dict[str, Any]:
    """Поля формы или JSON-тела верхнего уровня; ошибка разбора — пустой набор."""
    try:
        if request.is_json:
            тело = request.get_json(silent=True)
            return dict(тело) if isinstance(тело, dict) else {}
        return {ключ: request.form.get(ключ) for ключ in request.form}
    except HTTPException:
        # Тело не разобралось (слишком большое, кривое): запрос уже получил свой отказ,
        # а сводка цели ответ не меняет.
        return {}


def action_target() -> str:
    """Сводка цели запроса: части пути, строка запроса и поля тела — правилом по именам."""
    return summarize_target(
        {ключ: значение for ключ, значение in request.args.items()},
        _body_fields(),
        ids=request.view_args or {},
    )


def install(app: Flask, conf: Settings) -> None:
    """Повесить журнал действий: один `after_request` на весь веб."""
    from .auth import current_account

    @app.after_request
    def _journal_action(response: Response) -> Response:
        if request.method not in WRITE_METHODS or request.endpoint is None:
            return response
        account = current_account()
        if account is None or (
            account.role not in JOURNALED_ROLES and request.endpoint not in SECOND_FACTOR_ENDPOINTS
        ):
            return response
        сессия = account.session_id
        journals.record_action(
            user_id=account.id,
            role=account.role,
            tenant=account.tenant,
            action=request.endpoint,
            target=action_target(),
            outcome=str(response.status_code),
            ip=client_ip(conf),
            credential=f"session:{сессия}" if сессия else None,
            door=DOOR_WEB,
        )
        return response
