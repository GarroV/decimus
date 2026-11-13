"""Автоперевод комментариев при сборке отчёта (D443, D744).

Аудитор пишет «что видно» и рекомендации на языке чек-листа (`speech_lang`), а
язык отчёта выбирается только в конце проверки (D441) — раньше перевода
сохранять некуда: целевой язык неизвестен. Поэтому, если человек выбрал в
настройках мини-аппа «Автоматически» (`db.translate_modes`), перевод идёт здесь,
перед сборкой PDF, той же функцией, что и кнопка под полем (D394):
`recognize.translate.translate_text`.

Что переводится: комментарий и текст записи — свободный текст аудитора (текст, которым
служит вопрос пункта, не переводится: его печатает методика, `report.finding_text`).
Сведения о визите здесь не переводятся: их заполняют отдельно.

**Исходник не затирается** (D744): перевод в запись не пишется, возвращается вызывающему.
Тот отдаёт его сборке PDF и письма (`report.build`) и кладёт в `translations` рядом с
исходником, когда проверка слита (`db.finding_translations`). До D744 перевод ложился в
запись вместо исходника, и слив записывал его под языком речи.

Отказ перевода — модель недоступна, перевод слишком длинный — отчёт не роняет:
запись остаётся как написана, число таких записей возвращается вызывающему,
чтобы сказать об этом аудитору в чат. Нет базы — режим «по кнопке», не ошибка.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from src import domain
from src.db import translate_modes
from src.db.errors import DbError
from src.domain.log_ids import log_id
from src.report.finding_text import finding_text

from .usage import chat_usage

logger = logging.getLogger(__name__)

#: Поля записи со свободным текстом аудитора (`translations.field`).
FIELDS = ("text", "comment")


def mode_of(chat_id: int) -> str:
    """Режим перевода человека. Не выбирал или база молчит — по кнопке (D394)."""
    try:
        mode = translate_modes.chosen_translate_mode(chat_id)
    except DbError:
        logger.warning("Режим перевода чата %s не прочитался", log_id(chat_id), exc_info=True)
        return translate_modes.DEFAULT_MODE
    return mode if mode in translate_modes.MODES else translate_modes.DEFAULT_MODE


@dataclass(frozen=True)
class Translated:
    """Переводы записей на язык отчёта: номер записи → поле → текст. Исходник не затронут."""

    texts: dict[int, dict[str, str]] = field(default_factory=dict)
    #: Сколько полей перевести не удалось (0 — всё хорошо или перевод не нужен).
    failed: int = 0
    #: Язык, на который переведено.
    lang: str = ""


def translate_comments(chat_id: int, inspection: domain.Inspection) -> Translated:
    """Перевести свободный текст записей на язык отчёта, если человек выбрал «Автоматически».

    Язык отчёта равен языку чек-листа — переводить нечего. Запись проверки не меняется.
    """
    target = inspection.report_lang
    if target == inspection.speech_lang or mode_of(chat_id) != translate_modes.AUTO:
        return Translated()
    with chat_usage(chat_id):
        return _translate_findings(chat_id, inspection, target)


def _translate_findings(chat_id: int, inspection: domain.Inspection, target: str) -> Translated:
    texts: dict[int, dict[str, str]] = {}
    failed = 0
    for finding in inspection.findings:
        done: dict[str, str] = {}
        for name in FIELDS:
            source = getattr(finding, name)
            if not source.strip():
                continue
            wording = finding_text(source, source_lang=inspection.speech_lang, lang=target)
            if wording.origin == "failed":
                logger.warning(
                    "Автоперевод: запись #%s чата %s не переведена", finding.n, log_id(chat_id)
                )
                failed += 1
            elif wording.origin == "new":
                done[name] = wording.text
        if done:
            texts[finding.n] = done
    return Translated(texts, failed, target)
