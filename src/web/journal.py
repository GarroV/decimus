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

**Просмотр глазами партнёра (D726).** Пока главный админ смотрит как партнёр, журнал пишет и
чтения: каждый GET страницы или API (кроме `static` и ответов 3xx) — действие `peek_view` НАСТОЯЩЕЙ
учётки, цель — `as=<пространство>; <путь>` без строки запроса. Вне просмотра чтение не пишется.

**Способы входа — для любой роли.** Подключение, снятие ключей и приложения и выпуск
резервных кодов (`SECOND_FACTOR_ENDPOINTS`, D463) пишутся и у ролей, которые админами
не являются: смена способов входа важна независимо от роли.
"""

from __future__ import annotations

from typing import Any

from flask import Flask, Response, g, request
from werkzeug.exceptions import HTTPException

from src.db import journals
from src.domain.journal import (
    DOOR_WEB,
    JOURNALED_ROLES,
    MAX_TARGET,
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

#: Код действия «открыл страницу, пока смотрел глазами партнёра» (D726): читающий запрос
#: журналируется только при просмотре, у обычной работы чтение не пишется.
PEEK_VIEW_ACTION = "peek_view"

#: Маршруты, чьи чтения при просмотре не журналируются: отдача файлов, а не страницы.
_NOT_A_VIEW_ENDPOINTS = frozenset({"static"})


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


#: Ключ в `flask.g`: маршрут сам называет цель записи. Тогда сводка из формы не строится вовсе —
#: так делают маршруты с секретами (ключи сервисов, D576): в журнал идёт только то, что
#: маршрут положил сам, а не то, что правило по именам решило пропустить.
TARGET_OVERRIDE = "journal_target"


def action_target() -> str:
    """Сводка цели запроса: части пути, строка запроса и поля тела — правилом по именам."""
    явная = g.get(TARGET_OVERRIDE)
    if isinstance(явная, str):
        return явная[:MAX_TARGET]
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
        if request.endpoint is None:
            return response
        shown = current_account()
        peeking = shown is not None and shown.is_peeking
        is_write = request.method in WRITE_METHODS
        if not is_write and not (peeking and _is_page_view(response)):
            return response
        # Пока главный админ смотрит глазами партнёра (D726), в журнал идёт НАСТОЯЩАЯ учётка:
        # кто на деле нажал, а не вид, в котором он смотрел; вид — пометкой в цели.
        account = None if shown is None else shown.actual
        if account is None or (
            account.role not in JOURNALED_ROLES and request.endpoint not in SECOND_FACTOR_ENDPOINTS
        ):
            return response
        сессия = account.session_id
        if is_write:
            действие, цель = request.endpoint, action_target()
        else:
            # Только путь: строка запроса может нести личное (поиск по имени, фильтры).
            действие, цель = PEEK_VIEW_ACTION, request.path
        if peeking and shown is not None:
            цель = f"as={shown.tenant}; {цель}"[:MAX_TARGET]
        journals.record_action(
            user_id=account.id,
            role=account.role,
            tenant=account.tenant,
            action=действие,
            target=цель,
            outcome=str(response.status_code),
            ip=client_ip(conf),
            credential=f"session:{сессия}" if сессия else None,
            door=DOOR_WEB,
        )
        return response


def _is_page_view(response: Response) -> bool:
    """Чтение, которое стоит записать: GET настоящей страницы или API, отданный телом.

    Файлы (`static`) и ответы 3xx (редирект, `304`) — не просмотр; отказ (4xx) пишется.
    """
    if request.method != "GET" or request.endpoint in _NOT_A_VIEW_ENDPOINTS:
        return False
    code = response.status_code
    return code < 300 or code >= 400
