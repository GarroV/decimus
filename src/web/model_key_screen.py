"""Блок «Ключ модели» на вкладке «Подключения»: вставить, проверить, убрать (D491).

Только главный админ УК (заслон вкладки — `connections_screen._boss`, 404 всем прочим).
Маршруты и порядок заслонов — в `connections_screen.install`; здесь разбор формы и
исходы.

**Ключ только на запись.** Полное значение приходит из формы и уходит в `src/db/model_key`
(шифрование, база); назад — никуда: ни в страницу, ни в ответ, ни в журнал процесса, ни в
журнал действий (поле формы названо так, что журнал его в сводку не берёт, а ответ на
отказ не подставляет введённое обратно в поле). На экране — провайдер, `••••` и
последние четыре знака, кто и когда поставил.

**Сохранение не бывает без проверки.** Ключ, который провайдер не принял, не записывается;
если проверить не удалось (сеть, лимит) — тоже не записывается. «Проверить» делает тот же
вызов, но ничего не пишет.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from flask import request

from src.db import model_key, secret_crypto
from src.db.errors import DbError
from src.recognize import client
from src.recognize.errors import ModelKeyRejected, ModelUnavailable

from .db_refusal import note_target_mismatch

#: Имя поля формы. «Секретное» по правилу журнала действий: значение в сводку не попадает.
FIELD = "secret_value"
#: Предел длины: настоящие ключи — десятки знаков; больше — вставили не то.
MAX_LENGTH = 400

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class KeyFlash:
    """Исход действия над ключом: ключ текста и тон. Подстановок нет намеренно."""

    key: str
    ok: bool


@dataclass(frozen=True)
class KeyView:
    """Что рисует блок: запись о ключе (или её нет) и отказ чтения."""

    status: model_key.KeyStatus | None
    known: bool
    flash: KeyFlash | None


def view(flash: KeyFlash | None = None) -> KeyView:
    try:
        return KeyView(model_key.status(), True, flash)
    except DbError as exc:
        note_target_mismatch(exc)
        _log.warning("model_key: запись не прочитана (%s)", type(exc).__name__)
        return KeyView(None, False, flash)


def _typed() -> tuple[str | None, KeyFlash | None]:
    raw = (request.form.get(FIELD) or "").strip()
    if not raw:
        return None, KeyFlash("model_key.err.empty", False)
    if len(raw) > MAX_LENGTH or any(not c.isprintable() or c.isspace() for c in raw):
        return None, KeyFlash("model_key.err.shape", False)
    return raw, None


def _verify(value: str) -> KeyFlash | None:
    """`None` — провайдер ключ принял."""
    try:
        client.verify_key(value)
    except ModelKeyRejected:
        return KeyFlash("model_key.err.rejected", False)
    except ModelUnavailable:
        return KeyFlash("model_key.err.unverified", False)
    return None


def check() -> tuple[KeyFlash, int]:
    """Проверить введённый ключ у провайдера; ничего не записывать."""
    value, flash = _typed()
    if value is None or flash is not None:
        return flash or KeyFlash("model_key.err.empty", False), 400
    refused = _verify(value)
    if refused is not None:
        return refused, 422
    return KeyFlash("model_key.ok.checked", True), 200


def save(by: str) -> tuple[KeyFlash, int]:
    """Проверить и записать. Непринятый или непроверенный ключ не пишется."""
    value, flash = _typed()
    if value is None or flash is not None:
        return flash or KeyFlash("model_key.err.empty", False), 400
    refused = _verify(value)
    if refused is not None:
        return refused, 422
    try:
        model_key.save(value, by=by)
    except secret_crypto.SecretCryptoError as exc:
        # Нет или негоден `SECRETS_KEY`: хранить нечем. Текст исключения не показываем.
        _log.warning("model_key: запись отказана (%s)", type(exc).__name__)
        return KeyFlash("model_key.err.no_secrets_key", False), 503
    except DbError as exc:
        note_target_mismatch(exc)
        _log.warning("model_key: запись не прошла (%s)", type(exc).__name__)
        return KeyFlash("model_key.err.db", False), 503
    return KeyFlash("model_key.ok.saved", True), 200


def remove() -> tuple[KeyFlash, int]:
    """Убрать ключ из базы: дальше работает ключ из окружения."""
    try:
        removed = model_key.clear()
    except DbError as exc:
        note_target_mismatch(exc)
        _log.warning("model_key: удаление не прошло (%s)", type(exc).__name__)
        return KeyFlash("model_key.err.db", False), 503
    return KeyFlash("model_key.ok.removed" if removed else "model_key.err.none", removed), (
        200 if removed else 409
    )


def context(flash: KeyFlash | None = None) -> dict[str, Any]:
    """Переменные шаблона блока."""
    return {"model_key": view(flash), "model_key_max": MAX_LENGTH, "model_key_field": FIELD}
