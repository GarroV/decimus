"""Слова аудитора в находке — на нужном языке; исходник при этом не трогается (D744, #1619).

Всё, что ввёл аудитор (формулировка и комментарий находки), хранится в исходном виде и на
том языке, на каком записано: `translations(…, lang = speech_lang)`. Отчёт и письмо печатаются
на своём языке, и текст находки для них берётся здесь, одним правилом на все пути (отчёт и PDF
из базы, одиночное и общее письмо, MCP):

1. язык исходника равен языку печати — исходник;
2. иначе лежащий в `translations` перевод на этот язык;
3. иначе перевод делается сейчас ИЗ ИСХОДНИКА (`recognize.translate`, дешёвая модель),
   кладётся рядом и возвращается; следующая сборка берёт его из базы и модель не зовёт;
4. модель недоступна — исходник и пометка: язык находки остаётся прежним, и письмо называет
   такую находку в `not_restored` (`letters._wording_langs`). Отчёт из-за этого не падает.

Исторические проверки (`origin = 'legacy'`, D332) не трогаются: их отчёт перенесён как есть.

Проверки, у которых исходник затёрт переводом до D744 (`bot.finish_translate` писал перевод
в запись), отличить нельзя: в базе строка лежит на языке речи, как у всех. Лежащее считается
исходником на языке речи; перевод ИЗ уже переведённого текста модель отдаёт без изменений
(`recognize.translate`: «уже на нужном языке — вернуть как есть»), так что отчёт не ломается,
а в карточке такая находка подписана языком речи, хотя текст мог быть уже на языке отчёта.
"""

from __future__ import annotations

import contextvars
import logging
import re
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from typing import Any, Literal

from src.db import finding_translations
from src.db.errors import DbError
from src.db.models import FindingRow, InspectionDetail
from src.recognize.errors import RecognizeError
from src.recognize.translate import translate_text

logger = logging.getLogger(__name__)

#: Сколько находок переводится одновременно: сборка отчёта не должна ждать
#: «число находок × задержка модели» подряд.
MAX_PARALLEL = 6

#: Служебная пометка класса в начале вопроса методики: `(D1, D2) …` (`engine/report.py: clean_q`).
#: Запись, у которой вместо слов аудитора лежит вопрос пункта, движок печатает по методике сам и
#: сравнивает её со строкой методики, чтобы снять пометку; переведённая моделью строка с
#: методикой не совпала бы, и пометка уехала бы партнёру. Такой текст не переводится.
_CLASS_MARK = re.compile(r"^\s*\(\s*D[0-9]")

Translate = Callable[[str, str], str]
Origin = Literal["original", "stored", "new", "failed"]


@dataclass(frozen=True)
class Wording:
    """Текст на нужном языке и откуда он взялся."""

    text: str
    origin: Origin


def _model(text: str, lang: str) -> str:
    return translate_text(text, lang=lang)


def finding_text(
    original: str,
    *,
    source_lang: str,
    lang: str,
    stored: str | None = None,
    translate: Translate = _model,
) -> Wording:
    """Текст находки на языке `lang`. Единственное место правила «исходник → перевод».

    `stored` — лежащий в базе перевод на `lang` (если есть). Перевод делается из исходника,
    а не из чужого перевода: цепочка переводов копит ошибки. Отказ модели не бросается, а
    возвращается пометкой `failed` вместе с исходником.
    """
    if not original.strip() or source_lang == lang or _CLASS_MARK.match(original):
        return Wording(original, "original")
    if stored is not None and stored.strip():
        return Wording(stored, "stored")
    try:
        return Wording(translate(original, lang), "new")
    except RecognizeError:
        logger.warning("Перевод находки на %s не получился, остаётся исходник", lang, exc_info=True)
        return Wording(original, "failed")


@dataclass(frozen=True)
class Localized:
    """Проверка с текстом находок на языке печати и номера находок, оставшихся на исходнике."""

    detail: InspectionDetail
    #: Находки, у которых перевод не получился: текст остался на языке исходника.
    kept_original: tuple[int, ...] = ()


def _load(inspection_id: str, lang: str) -> dict[tuple[str, str], str]:
    try:
        return finding_translations.stored(inspection_id, lang)
    except DbError:
        logger.warning("Переводы находок %s не прочитаны", inspection_id, exc_info=True)
        return {}


def _save(inspection_id: str, lang: str, items: Mapping[tuple[str, str], str]) -> None:
    try:
        finding_translations.store(inspection_id, lang, items)
    except DbError:
        # Текст в этой сборке уже переведён; не легло в базу — переведём при следующей.
        logger.warning("Переводы находок %s не сохранены", inspection_id, exc_info=True)


def _fields(finding: FindingRow) -> dict[str, str]:
    """Поля находки со свободным текстом аудитора; пустых и отсутствующих нет."""
    return {
        name: value
        for name in finding_translations.FIELDS
        if (value := getattr(finding, name)) is not None and value.strip()
    }


def localize(
    detail: InspectionDetail,
    lang: str,
    *,
    allow_model: bool = True,
    translate: Translate = _model,
) -> Localized:
    """Текст всех находок проверки на языке `lang` — для отчёта, письма, карточки.

    `allow_model=False` — только исходник и лежащие переводы: для мест, где модель звать
    нельзя (проверка «не изменилось ли за сборку», карточка). Повторный вызов на результате
    безвреден: находка, чей язык уже `lang`, остаётся как есть.
    """
    head = detail.inspection
    if head.is_legacy:
        return Localized(detail)
    todo = {
        finding.id: _fields(finding)
        for finding in detail.findings
        if finding.lang != lang and not finding.source_lang and _fields(finding)
    }
    if not todo:
        return Localized(detail)
    stored = _load(head.id, lang)
    jobs = [
        (finding, name, text)
        for finding in detail.findings
        for name, text in todo.get(finding.id, {}).items()
        if (finding.id, name) not in stored and not _CLASS_MARK.match(text)
    ]
    fresh: dict[tuple[str, str], Wording] = {}
    if jobs and allow_model:
        fresh = _translate_all(jobs, lang, translate)
        _save(
            head.id,
            lang,
            {key: w.text for key, w in fresh.items() if w.origin == "new"},
        )
    rows: list[FindingRow] = []
    kept: list[int] = []
    for finding in detail.findings:
        if finding.id not in todo:
            rows.append(finding)
            continue
        row, ok = _localized_row(finding, lang, todo[finding.id], stored, fresh)
        rows.append(row)
        if not ok:
            kept.append(finding.n)
    return Localized(replace(detail, findings=tuple(rows)), tuple(kept))


def _translate_all(
    jobs: list[tuple[FindingRow, str, str]], lang: str, translate: Translate
) -> dict[tuple[str, str], Wording]:
    """Перевести поля параллельно: учёт расхода модели (контекст) переезжает в рабочие потоки."""

    def run(job: tuple[FindingRow, str, str]) -> tuple[tuple[str, str], Wording]:
        finding, name, text = job
        wording = finding_text(text, source_lang=finding.lang, lang=lang, translate=translate)
        return (finding.id, name), wording

    contexts = [contextvars.copy_context() for _ in jobs]
    with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL, len(jobs))) as pool:
        done = pool.map(lambda pair: pair[0].run(run, pair[1]), zip(contexts, jobs, strict=True))
        return dict(done)


def _localized_row(
    finding: FindingRow,
    lang: str,
    fields: Mapping[str, str],
    stored: Mapping[tuple[str, str], str],
    fresh: Mapping[tuple[str, str], Wording],
) -> tuple[FindingRow, bool]:
    """Находка с текстом на `lang`. Второе — все ли поля удалось перевести."""
    shown: dict[str, str] = {}
    originals: dict[str, str] = {}
    ok = True
    for name, original in fields.items():
        key = (finding.id, name)
        if _CLASS_MARK.match(original):
            continue
        wording = (
            Wording(stored[key], "stored")
            if key in stored
            else fresh.get(key, Wording(original, "failed"))
        )
        if wording.origin == "failed":
            ok = False
            continue
        shown[name] = wording.text
        originals[name] = original
    if not shown:
        return (replace(finding, lang=lang) if ok else finding), ok
    changes: dict[str, Any] = {
        **shown,
        **{f"original_{name}": text for name, text in originals.items()},
        "source_lang": finding.lang,
    }
    if ok:
        changes["lang"] = lang
    return replace(finding, **changes), ok
