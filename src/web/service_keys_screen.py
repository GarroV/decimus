"""Блок «Ключи сервисов» на вкладке «Подключения»: проверить, заменить, удалить (D491, D576).

Только главный админ УК (заслон вкладки — `connections_screen._boss`, 404 всем прочим).
Маршруты и порядок заслонов — в `connections_screen.install_service_keys`; здесь разбор
формы и исходы. Список сервисов и полей — реестр `src/domain/service_keys.py`: код из
адреса, которого в реестре нет, — 404.

**Значение только на запись.** Оно приходит из формы и уходит в `src/db/service_keys`
(шифрование, база); назад — никуда: ни в страницу, ни в ответ, ни в журнал процесса, ни в
журнал действий (имена полей содержат `secret`, а цель записи журнала задаётся здесь
явно: сервис, поля и последние четыре знака), ни в текст исключения. На экране — статус,
`••••` и последние четыре знака, кто и когда поставил.

**Сохранение не бывает без проверки.** Значение, которое провайдер не принял, не
записывается; если проверить не удалось (сеть, лимит, таймаут) — тоже. «Проверить» делает
тот же вызов, но ничего не пишет. Сервис с несколькими полями (iSpring) проверяется и
пишется парой, одной транзакцией.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

from flask import request

from src.db import secret_crypto, service_keys
from src.db.errors import DbError
from src.domain import service_keys as registry

from .db_refusal import note_target_mismatch
from .service_probes import PROBES, KeyRejected, KeyUnverified

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class KeyFlash:
    """Исход действия над ключом сервиса: у какой карточки, ключ текста, тон и подстановки.

    Подстановки — только число (код ответа, минуты): значения ключа здесь нет намеренно.
    """

    service: str
    key: str
    ok: bool
    params: dict[str, int] | None = None


@dataclass(frozen=True)
class FieldRow:
    """Поле сервиса на экране: запись из базы (или нет) и задано ли оно в окружении."""

    code: str
    form_name: str
    status: service_keys.KeyStatus | None
    in_env: bool


@dataclass(frozen=True)
class ServiceRow:
    """Карточка сервиса: поля и общее состояние (`db` / `env` / `unset` / `partial`)."""

    code: str
    fields: tuple[FieldRow, ...]
    state: str


@dataclass(frozen=True)
class KeysView:
    """Что рисует блок: карточки (или отказ чтения) и исход последнего действия."""

    services: tuple[ServiceRow, ...]
    known: bool
    flash: KeyFlash | None


def _state(fields: tuple[FieldRow, ...]) -> str:
    sources = {"db" if f.status else "env" if f.in_env else "unset" for f in fields}
    return sources.pop() if len(sources) == 1 else "partial"


def _row(service: registry.Service, found: dict[str, service_keys.KeyStatus]) -> ServiceRow:
    fields = tuple(
        FieldRow(
            f.code,
            registry.form_name(f.code),
            found.get(f.vault_name),
            bool((os.environ.get(f.env_var) or "").strip()),
        )
        for f in service.fields
    )
    return ServiceRow(service.code, fields, _state(fields))


def view(flash: KeyFlash | None = None) -> KeysView:
    try:
        found = service_keys.statuses()
    except DbError as exc:
        note_target_mismatch(exc)
        _log.warning("service_keys: записи не прочитаны (%s)", type(exc).__name__)
        return KeysView((), False, flash)
    return KeysView(tuple(_row(s, found) for s in registry.SERVICES), True, flash)


def _typed(service: registry.Service) -> tuple[dict[str, str] | None, str | None]:
    """Значения всех полей сервиса из формы (код поля → значение) либо ключ текста отказа."""
    values: dict[str, str] = {}
    for field in service.fields:
        raw = (request.form.get(registry.form_name(field.code)) or "").strip()
        if not raw:
            return None, "keys.err.empty"
        if not registry.is_acceptable(raw):
            return None, "keys.err.shape"
        values[field.code] = raw
    return values, None


def _verify(service: registry.Service, values: dict[str, str]) -> KeyFlash | None:
    """`None` — провайдер значение принял."""
    try:
        PROBES[service.code](values)
    except KeyRejected as exc:
        if exc.status is None:
            return KeyFlash(service.code, "keys.err.rejected_nostatus", False)
        return KeyFlash(service.code, "keys.err.rejected", False, {"status": exc.status})
    except KeyUnverified as exc:
        if exc.status is None:
            return KeyFlash(service.code, "keys.err.unverified", False)
        return KeyFlash(service.code, "keys.err.unverified_status", False, {"status": exc.status})
    return None


def check(service: registry.Service) -> tuple[KeyFlash, int]:
    """Проверить введённое у провайдера; ничего не записывать."""
    values, refusal = _typed(service)
    if values is None:
        return KeyFlash(service.code, refusal or "keys.err.empty", False), 400
    refused = _verify(service, values)
    if refused is not None:
        return refused, 422
    return KeyFlash(service.code, "keys.ok.checked", True), 200


def save(service: registry.Service, by: str) -> tuple[KeyFlash, int, str]:
    """Проверить и записать. Непринятое или непроверенное не пишется.

    Третье значение — безопасная сводка для журнала действий (поля и последние знаки).
    """
    values, refusal = _typed(service)
    if values is None:
        return KeyFlash(service.code, refusal or "keys.err.empty", False), 400, ""
    refused = _verify(service, values)
    if refused is not None:
        return refused, 422, ""
    by_name = {f.vault_name: values[f.code] for f in service.fields}
    try:
        saved = service_keys.save_many(by_name, provider=service.code, by=by)
    except secret_crypto.SecretCryptoError as exc:
        # Нет или негоден `SECRETS_KEY`: хранить нечем. Текст исключения не показываем.
        _log.warning("service_keys: запись отказана (%s)", type(exc).__name__)
        return KeyFlash(service.code, "keys.err.no_secrets_key", False), 503, ""
    except DbError as exc:
        note_target_mismatch(exc)
        _log.warning("service_keys: запись не прошла (%s)", type(exc).__name__)
        return KeyFlash(service.code, "keys.err.db", False), 503, ""
    summary = ",".join(f"{f.code}:{saved[f.vault_name].last4}" for f in service.fields)
    return KeyFlash(service.code, "keys.ok.saved", True), 200, f"set={summary}"


def remove(service: registry.Service) -> tuple[KeyFlash, int]:
    """Убрать записи сервиса из базы: дальше работает окружение."""
    try:
        removed = service_keys.clear_many(tuple(f.vault_name for f in service.fields))
    except DbError as exc:
        note_target_mismatch(exc)
        _log.warning("service_keys: удаление не прошло (%s)", type(exc).__name__)
        return KeyFlash(service.code, "keys.err.db", False), 503
    if removed:
        return KeyFlash(service.code, "keys.ok.removed", True), 200
    return KeyFlash(service.code, "keys.err.none", False), 409


def context(flash: KeyFlash | None = None) -> dict[str, Any]:
    """Переменные шаблона блока."""
    return {"keys": view(flash), "keys_max": registry.MAX_LENGTH}
