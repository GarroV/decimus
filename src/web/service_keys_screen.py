"""Блок «Наши ключи к внешним сервисам» на «Ключах и API»: проверить, заменить, удалить (D576).

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
from datetime import UTC, datetime
from typing import Any

from flask import request

from src.db import health_store, secret_crypto, service_keys
from src.db.errors import DbError
from src.domain import health
from src.domain import service_keys as registry
from src.health import checks
from src.health import rows as health_rows
from src.health.probes import PROBES, KeyRejected, KeyUnverified

from .db_refusal import note_target_mismatch

_log = logging.getLogger(__name__)

#: Пара ключей приложения Decimus в маркетплейсе Dodo IS: показывается на вкладке «Dodo IS»
#: (`dodois_screen`), а не среди «Ключей сервисов» на «Подключениях». Маршруты, заслоны и
#: проверка у неё те же — реестр и `connections_screen._key_action`.
APP_SERVICE = "dodois"


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
    env_masked: str | None = None
    identifier: str | None = None


@dataclass(frozen=True)
class ServiceRow:
    """Карточка сервиса: поля и общее состояние (`db` / `env` / `unset` / `partial`)."""

    code: str
    fields: tuple[FieldRow, ...]
    state: str
    health: health.Status | None = None

    @property
    def configured(self) -> bool:
        return all(f.status or f.in_env for f in self.fields)

    @property
    def current_check_available(self) -> bool:
        # App credentials require an OAuth device request, not a read-only probe.
        # Country connection health is separate evidence, never proof of this pair.
        return self.code != APP_SERVICE


@dataclass(frozen=True)
class KeysView:
    """Что рисует блок: карточки (или отказ чтения) и исход последнего действия."""

    services: tuple[ServiceRow, ...]
    known: bool
    flash: KeyFlash | None


def _state(fields: tuple[FieldRow, ...]) -> str:
    sources = {"db" if f.status else "env" if f.in_env else "unset" for f in fields}
    return sources.pop() if len(sources) == 1 else "partial"


def _field(
    service: registry.Service, field: registry.KeyField, found: dict[str, service_keys.KeyStatus]
) -> FieldRow:
    raw_env = (os.environ.get(field.env_var) or "").strip()
    status = found.get(field.vault_name)
    identifier = None
    if field.code == "client_id":
        try:
            identifier = service_keys.resolve(service.code, field.code)
        except DbError:
            identifier = None
    return FieldRow(
        field.code,
        registry.form_name(field.code),
        status,
        bool(raw_env),
        "••••" + raw_env[-registry.LAST_CHARS :] if raw_env else None,
        identifier,
    )


def _last_probe(
    service: registry.Service,
    fields: tuple[FieldRow, ...],
    probes: dict[str, health.ProbeRow] | None,
) -> health.Status | None:
    if service.code == APP_SERVICE:
        return health.Status(health.GREY, "keys.health.app_pair")
    if probes is None:
        return None
    row = probes.get(service.code)
    if not all(f.status or f.in_env for f in fields):
        return health.Status(health.GREY, "health.reason.no_key", row.checked_at if row else None)
    changed_at = max((f.status.set_at for f in fields if f.status), default=None)
    if row is not None and changed_at is not None and changed_at > row.checked_at:
        return health.Status(health.YELLOW, "keys.health.changed", row.checked_at)
    connection = checks.connection(service.code)
    every = checks.PROBE_EVERY if connection and connection.scheduled else None
    return health_rows.probe_status(service.code, row, datetime.now(UTC), every=every)


def _row(
    service: registry.Service,
    found: dict[str, service_keys.KeyStatus],
    probes: dict[str, health.ProbeRow] | None,
) -> ServiceRow:
    fields = tuple(_field(service, f, found) for f in service.fields)
    return ServiceRow(service.code, fields, _state(fields), _last_probe(service, fields, probes))


def _stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%d.%m.%Y %H:%M UTC")


def view(flash: KeyFlash | None = None, *, app: bool = False) -> KeysView:
    """Карточки сервисов: `app=False` — все, кроме приложения Dodo IS; `True` — только оно."""
    try:
        found = service_keys.statuses()
    except DbError as exc:
        note_target_mismatch(exc)
        _log.warning("service_keys: записи не прочитаны (%s)", type(exc).__name__)
        return KeysView((), False, flash)
    try:
        probes = health_store.probes()
    except DbError as exc:
        note_target_mismatch(exc)
        _log.warning("service_keys: состояние подключения не прочитано (%s)", type(exc).__name__)
        probes = None
    shown = tuple(
        _row(s, found, probes) for s in registry.SERVICES if (s.code == APP_SERVICE) is app
    )
    return KeysView(shown, True, flash)


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
    if request.form.get("current_connection") == "1":
        return check_current(service)
    values, refusal = _typed(service)
    if values is None:
        return KeyFlash(service.code, refusal or "keys.err.empty", False), 400
    refused = _verify(service, values)
    if refused is not None:
        return refused, 422
    return KeyFlash(service.code, "keys.ok.checked", True), 200


def check_current(service: registry.Service) -> tuple[KeyFlash, int]:
    """Probe effective DB→ENV credentials; never save or return credential values."""
    if service.code == APP_SERVICE:
        return KeyFlash(service.code, "keys.err.current_unavailable", False), 409
    try:
        outcome = checks.probe_and_record(service.code)
    except DbError as exc:
        note_target_mismatch(exc)
        _log.warning("service_keys: исход проверки не записан (%s)", type(exc).__name__)
        return KeyFlash(service.code, "keys.err.health_db", False), 503
    if outcome is None:
        return KeyFlash(service.code, "keys.err.current_unavailable", False), 409
    light, _reason = outcome
    return KeyFlash(service.code, "keys.ok.current_checked", light == health.GREEN), (
        200 if light == health.GREEN else 422
    )


def _require_recheck(service: registry.Service) -> KeyFlash | None:
    """Do not keep a successful result for credentials about to be replaced/removed.

    Keep the actual probe time; invalidation is not a new provider check.
    If invalidation cannot be stored, refuse the key mutation before it happens.
    """
    if service.code == APP_SERVICE:
        return None
    try:
        previous = health_store.probes().get(service.code)
        if previous is not None:
            health_store.record(
                service.code, health.GREY, "health.reason.credentials_recheck", previous.checked_at
            )
    except DbError as exc:
        note_target_mismatch(exc)
        _log.warning("service_keys: прежний исход проверки не сброшен (%s)", type(exc).__name__)
        return KeyFlash(service.code, "keys.err.health_db", False)
    return None


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
    stale = _require_recheck(service)
    if stale is not None:
        return stale, 503, ""
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
    stale = _require_recheck(service)
    if stale is not None:
        return stale, 503
    try:
        removed = service_keys.clear_many(tuple(f.vault_name for f in service.fields))
    except DbError as exc:
        note_target_mismatch(exc)
        _log.warning("service_keys: удаление не прошло (%s)", type(exc).__name__)
        return KeyFlash(service.code, "keys.err.db", False), 503
    if removed:
        return KeyFlash(service.code, "keys.ok.removed", True), 200
    return KeyFlash(service.code, "keys.err.none", False), 409


def selected(rows: tuple[ServiceRow, ...], flash: KeyFlash | None) -> str:
    """Сервис в панели: тот, у кого исход действия, иначе `?key=`, иначе первый не заданный."""
    codes = [r.code for r in rows]
    for wanted in (flash.service if flash else "", request.args.get("key") or ""):
        if wanted in codes:
            return wanted
    unset = [r.code for r in rows if r.state == "unset"]
    return (unset or codes or [""])[0]


def is_ready(row: ServiceRow | None) -> bool:
    """Каждое поле пары задано — в админке или в окружении сервера."""
    return row is not None and all(f.status or f.in_env for f in row.fields)


def app_context(flash: KeyFlash | None = None) -> dict[str, Any]:
    """Переменные шаблона вкладки «Dodo IS»: ключи приложения и готовность пары."""
    shown = view(flash, app=True)
    row = shown.services[0] if shown.services else None
    return {
        "keys": shown,
        "keys_max": registry.MAX_LENGTH,
        "app_keys_ready": is_ready(row),
        "keys_stamp": _stamp,
    }


def context(flash: KeyFlash | None = None) -> dict[str, Any]:
    """Переменные шаблона блока."""
    shown = view(flash)
    return {
        "keys": shown,
        "keys_max": registry.MAX_LENGTH,
        "keys_stamp": _stamp,
        "keys_selected": selected(shown.services, flash),
    }
