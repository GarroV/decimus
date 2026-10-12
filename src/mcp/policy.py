"""Права MCP по роли учётки сайта (D417): матрица «роль × вид инструментов».

Роль известна у личного токена из бота и у входа через OAuth
(`config.resolve_access`): оба выпущены на учётку decimus, и права даёт её роль,
а не пространство. С аудита 12.10 (F-017, F-022) личный токен тоже несёт роль —
до этого он открывал всё пространство любому, кто попал в круг. Роли не знает
только служебный токен из карты `MCP_TOKENS` в `.env`: его заводит владелец
стенда руками, и для него матрица не применяется.

**Матрица только сужает.** Она отвечает «может ли эта роль вообще», а прежние
заслоны (`rpc._call_tool`: методика по `MCP_CHECKLIST_TENANTS`, загрузка по
`MCP_IMPORT_TENANTS`, рейтинги только УК) стоят дальше и действуют как раньше.
Поэтому клетка «правка методики — да, если HQ открыта методика» здесь просто
«да»: условие настройки держит настройка.

**Одна функция на `tools/list` и на вызов.** Две копии одной таблицы
разошлись бы молча: инструмент, скрытый из списка, но открытый на вызове, —
это дыра, которую видно только перебором имён.

Незнакомая роль и незнакомый вид закрыты: новая роль или новый вид, не
внесённые сюда, получают отказ, а не тихий доступ.
"""

from __future__ import annotations

from src.domain.tenants import ADMIN_ROLES, CONTROL_ROLE, HQ_TENANT, canonical_tenant

from .catalogue import (
    KIND_CHECKLIST,
    KIND_CHECKLIST_SOURCE,
    KIND_IMPORT,
    KIND_INSPECTIONS,
    KIND_RATINGS,
    KIND_RATINGS_READ,
)

#: Аудитор УК — роль учётки сайта, которой открыта проверка, но не методика.
AUDITOR_ROLE = "auditor"

#: Роли сайта, известные матрице. Остальные — ничего.
KNOWN_ROLES = frozenset({AUDITOR_ROLE, CONTROL_ROLE, *ADMIN_ROLES})

#: УК: админ и главный админ — всё, кроме снятия (D335, D344).
_HQ_ADMIN = frozenset(
    {
        KIND_INSPECTIONS,
        KIND_CHECKLIST_SOURCE,
        KIND_CHECKLIST,
        KIND_IMPORT,
        KIND_RATINGS_READ,
        KIND_RATINGS,
    }
)

#: УК: аудитор читает проверки, эталон и рейтинги; методику не правит (D344).
_HQ_AUDITOR = frozenset({KIND_INSPECTIONS, KIND_CHECKLIST_SOURCE, KIND_RATINGS_READ})

#: УК: контролинг — только рейтинги, чтение и управление; проверок не касается
#: никак (D420, отменяет D350; D344, D358).
_HQ_CONTROL = frozenset({KIND_RATINGS_READ, KIND_RATINGS})

#: Партнёр, любая роль: чтение своих проверок и рейтингов (D335 — загрузки нет
#: никогда).
_PARTNER = frozenset({KIND_INSPECTIONS, KIND_RATINGS_READ})

#: Снятие проверки (`KIND_RETRACTION`) не открыто ни одной строке намеренно:
#: через OAuth его нет ни у кого (спека D417, «Безопасность»).


def kinds_for(role: str, tenant: str) -> frozenset[str]:
    """Виды инструментов, открытые роли учётки в её пространстве."""
    if role not in KNOWN_ROLES:
        return frozenset()
    if canonical_tenant(tenant) != HQ_TENANT:
        return _PARTNER
    if role in ADMIN_ROLES:
        return _HQ_ADMIN
    if role == CONTROL_ROLE:
        return _HQ_CONTROL
    return _HQ_AUDITOR


def permits(role: str, tenant: str, kind: str) -> bool:
    """Открыт ли роли вид инструментов. Одна функция и на список, и на вызов."""
    return kind in kinds_for(role, tenant)
