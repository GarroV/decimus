"""Шаблон письма партнёру по проверке во вкладке «Письма и уведомления» (D550, D608, #977, #1130).

Текст письма — по слоту (с планом действий, без D2 и D3, без записей) и языку: сохранённый
в базе, а если его нет — встроенный текст движка. Редактор — свободный текст плюс блоки-
подстановки `{unit}`, `{grade}`…: что подставлять, решает движок, неизвестная подстановка
при сохранении — отказ с причиной (`domain.letter_template`). Каждое сохранение — новая
версия с автором и временем (`db.mailing_templates`), «Вернуть встроенный» — тоже версия.

Оценку, сводку по зонам, критичное и срок плана шаблон не считает: он ставит в текст то,
что дал движок. Два шаблона на выбор отправителя (D664) остаются: блоки `{good_block}` и
`{end_block}` кладут обратную связь аудитора в разные места по выбранному шаблону.

Вкладка ничего не отправляет: письмо по сохранённому тексту собирается на экране проверки,
и в почту его кладёт человек сам.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from flask import abort, request

from src.db import mailing_templates as store
from src.db.errors import DbError
from src.domain import letter_template as lt
from src.report.letters import LetterError, builtin_bodies

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SlotRow:
    """Строка списка шаблонов: слот, язык и его текущая версия (`None` — встроенный)."""

    slot: str
    lang: str
    version: store.Version | None


@dataclass(frozen=True)
class Editor:
    """Открытый редактор: текст в поле, откуда он, версия и история слота."""

    slot: str
    lang: str
    text: str
    #: Текст в поле — встроенный текст движка (сохранённого нет или последняя версия «встроенный»).
    is_builtin: bool
    version: store.Version | None
    #: Прежние версии; `None` — история не прочиталась.
    history: tuple[store.Version, ...] | None
    #: Встроенный текст движка не получен — поле пустое не из-за шаблона.
    builtin_failed: bool = False
    #: Отказ при сохранении: код и подстановка из `letter_template.problem_of`.
    error: tuple[str, str] | None = None


@dataclass(frozen=True)
class TemplateView:
    """Всё, что нужно разделу «Шаблон письма»: строки списка и редактор выбранного."""

    #: `None` — шаблоны не прочитались.
    rows: tuple[SlotRow, ...] | None
    editor: Editor | None
    fields: tuple[str, ...] = lt.FIELDS


def picked_slot() -> tuple[str, str] | None:
    """Выбранный слот из адреса (`slot`, `tlang`); ни одного — `None`, неверный — 404."""
    slot = request.args.get("slot", "").strip()
    lang = request.args.get("tlang", "").strip()
    if not slot and not lang:
        return None
    if slot not in lt.SLOTS or lang not in lt.LANGS:
        abort(404)
    return slot, lang


def _builtin(slot: str, lang: str) -> str | None:
    try:
        return builtin_bodies()[slot][lang]
    except (LetterError, KeyError):
        log.warning("Встроенный текст письма %s/%s не получен", slot, lang, exc_info=True)
        return None


def load(
    selected: tuple[str, str] | None,
    *,
    form_body: str | None = None,
    error: tuple[str, str] | None = None,
) -> TemplateView:
    """Строки списка и, если слот выбран, редактор.

    `form_body` — текст, который человек отправил и который не принят: он остаётся в поле
    вместе с причиной, а не пропадает.
    """
    try:
        now = store.current()
    except DbError:
        log.warning("Шаблоны писем для вкладки не прочитались", exc_info=True)
        return TemplateView(rows=None, editor=None)
    rows = tuple(
        SlotRow(slot, lang, now.get((slot, lang))) for slot in lt.SLOTS for lang in lt.LANGS
    )
    if selected is None:
        return TemplateView(rows=rows, editor=None)
    slot, lang = selected
    version = now.get(selected)
    try:
        history: tuple[store.Version, ...] | None = store.history(slot, lang)
    except DbError:
        log.warning("История шаблона %s/%s не прочиталась", slot, lang, exc_info=True)
        history = None
    stored = version.body if version is not None else None
    builtin = None if stored is not None else _builtin(slot, lang)
    text = form_body if form_body is not None else (stored if stored is not None else builtin or "")
    return TemplateView(
        rows=rows,
        editor=Editor(
            slot=slot,
            lang=lang,
            text=text,
            is_builtin=stored is None and form_body is None,
            version=version,
            history=history,
            builtin_failed=stored is None and builtin is None and form_body is None,
            error=error,
        ),
    )
