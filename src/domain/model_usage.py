"""Расход модели (D537, `0078`): виды вызова и кто за ним стоит.

Один вызов провайдера — одна строка в `model_usage`. Здесь — то, что не зависит от
базы и сети: стабильные коды видов вызова и «контекст вызова» — кто спросил, в какой
проверке и каком пространстве. Контекст ставят двери (бот, веб, мини-апп) на время
обращения, а читает единственная точка вызова провайдера (`recognize.client`), поэтому
ни один новый вызов не обязан помнить про учёт: он идёт через неё.

Коды видов — данные, а не подписи: названия переводятся (`texts_usage.py`), коды нет.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from typing import Any

#: Распознавание записи: слова и кадры аудитора → предложение пункта (бот).
KIND_RECOGNIZE = "recognize"
#: Подбор пункта по словам и кадрам на экране — мини-апп обхода и вычитка в вебе.
KIND_SUGGEST = "suggest"
#: Разбор исправления записи («поправь формулировку»).
KIND_REVISE = "revise"
#: Сведение комментария записи с новыми словами аудитора.
KIND_MERGE = "merge"
#: Перевод текста на язык отчёта.
KIND_TRANSLATE = "translate"
#: Расшифровка голосового.
KIND_TRANSCRIBE = "transcribe"
#: Всё, что не названо выше.
KIND_OTHER = "other"

KINDS: tuple[str, ...] = (
    KIND_RECOGNIZE,
    KIND_SUGGEST,
    KIND_REVISE,
    KIND_MERGE,
    KIND_TRANSLATE,
    KIND_TRANSCRIBE,
    KIND_OTHER,
)


@dataclass(frozen=True)
class UsageScope:
    """Кто и в какой проверке спрашивает модель. Пустое поле — «не известно».

    `inspection_ref` — номер проверки в базе (веб) или личность проверки чата
    `run_id` (бот и мини-апп: в базе проверки ещё нет, пока её не сдали).
    `kind` — вид работы двери, когда он уже, чем вид вызова: подбор пункта на экране
    идёт тем же `classify`, что и запись в боте, но считается отдельно.
    """

    user_id: str | None = None
    telegram_id: int | None = None
    tenant: str | None = None
    inspection_ref: str | None = None
    kind: str | None = None


_EMPTY = UsageScope()  # неизменяемый: безопасно как умолчание
_SCOPE: ContextVar[UsageScope] = ContextVar("decimus_usage_scope", default=_EMPTY)


def current_scope() -> UsageScope:
    """Контекст обращения; вне двери — пустой."""
    return _SCOPE.get()


def _merged(base: UsageScope, **fields: Any) -> UsageScope:
    """Поверх `base` ложатся только заданные (не `None`) поля."""
    return replace(base, **{k: v for k, v in fields.items() if v is not None})


@contextmanager
def usage_scope(
    *,
    user_id: str | None = None,
    telegram_id: int | None = None,
    tenant: str | None = None,
    inspection_ref: str | None = None,
    kind: str | None = None,
) -> Iterator[UsageScope]:
    """Всё, что внутри блока, учитывается за этим человеком и этой проверкой.

    Вложенный блок дополняет внешний: не названное внутри остаётся с внешнего.
    """
    scope = _merged(
        _SCOPE.get(),
        user_id=user_id,
        telegram_id=telegram_id,
        tenant=tenant,
        inspection_ref=inspection_ref,
        kind=kind,
    )
    mark = _SCOPE.set(scope)
    try:
        yield scope
    finally:
        _SCOPE.reset(mark)


def enter_scope(
    *,
    user_id: str | None = None,
    telegram_id: int | None = None,
    tenant: str | None = None,
    inspection_ref: str | None = None,
    kind: str | None = None,
) -> object:
    """То же без блока `with` — для хуков «до/после» запроса. Метку вернуть в `leave_scope`."""
    return _SCOPE.set(
        _merged(
            _SCOPE.get(),
            user_id=user_id,
            telegram_id=telegram_id,
            tenant=tenant,
            inspection_ref=inspection_ref,
            kind=kind,
        )
    )


def leave_scope(mark: object) -> None:
    """Снять контекст, поставленный `enter_scope`."""
    _SCOPE.reset(mark)  # type: ignore[arg-type]


def resolve_kind(call_kind: str, scope: UsageScope) -> str:
    """Вид вызова для учёта.

    Вид двери (`scope.kind`) уточняет только распознавание: подбор пункта на экране —
    тот же вызов, что запись в боте. Перевод и сведение остаются собой в любой двери.
    Незнакомый код — `other`, а не отказ: учёт не должен ронять вызов.
    """
    kind = scope.kind if call_kind == KIND_RECOGNIZE and scope.kind else call_kind
    return kind if kind in KINDS else KIND_OTHER


@dataclass(frozen=True)
class ModelCall:
    """Один вызов провайдера, как он пишется в `model_usage`."""

    kind: str
    model: str
    ok: bool
    input_tokens: int | None = None
    output_tokens: int | None = None
    #: Секунды звука — когда провайдер отдал длительность, а не токены.
    audio_seconds: float | None = None
    user_id: str | None = None
    telegram_id: int | None = None
    tenant: str | None = None
    inspection_ref: str | None = None


def build_call(
    call_kind: str,
    model: str,
    *,
    ok: bool,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    audio_seconds: float | None = None,
    scope: UsageScope | None = None,
) -> ModelCall:
    """Собрать запись учёта из вызова и контекста двери."""
    s = scope if scope is not None else current_scope()
    return ModelCall(
        kind=resolve_kind(call_kind, s),
        model=model,
        ok=ok,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        audio_seconds=audio_seconds,
        user_id=s.user_id,
        telegram_id=s.telegram_id,
        tenant=s.tenant,
        inspection_ref=s.inspection_ref,
    )
