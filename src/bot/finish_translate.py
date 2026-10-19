"""Автоперевод комментариев при сборке отчёта (D443).

Аудитор пишет «что видно» и рекомендации на языке чек-листа (`speech_lang`), а
язык отчёта выбирается только в конце проверки (D441) — раньше перевода
сохранять некуда: целевой язык неизвестен. Поэтому, если человек выбрал в
настройках мини-аппа «Автоматически» (`db.translate_modes`), перевод идёт здесь,
перед сборкой PDF, той же функцией, что и кнопка под полем (D394):
`recognize.translate.translate_text`.

Что переводится: комментарий записи и текст рекомендации (`R`) — только
свободный текст аудитора. Формулировка нарушения привязана к коду пункта и
берётся из методики на языке отчёта (D416), её не трогаем. Сведения о визите
здесь не переводятся: их заполняют отдельно, и кнопка у поля остаётся.

Переведённый текст ложится в запись вместо исходного: в отчёт идёт то, что
сохранено в проверке, а правка оригинала возможна в вычитке. Повторный запуск
безопасен — модель возвращает текст на нужном языке без изменений.

Отказ перевода — модель недоступна, перевод слишком длинный — отчёт не роняет:
запись остаётся как написана, число таких записей возвращается вызывающему,
чтобы сказать об этом аудитору в чат. Нет базы — режим «по кнопке», не ошибка.
"""

from __future__ import annotations

import logging

from src import domain
from src.db import translate_modes
from src.db.errors import DbError
from src.domain.errors import DomainError
from src.domain.log_ids import log_id
from src.recognize.errors import RecognizeError
from src.recognize.translate import translate_text

from .usage import chat_usage

logger = logging.getLogger(__name__)

#: Рекомендация партнёру (уровень `R`): её текст — свободный, а не из методики.
ADVICE_LEVEL = "R"
#: Предел длины записи — как у поля в мини-аппе (`web.walk_write.MAX_TEXT`).
MAX_TEXT = 1000


def mode_of(chat_id: int) -> str:
    """Режим перевода человека. Не выбирал или база молчит — по кнопке (D394)."""
    try:
        mode = translate_modes.chosen_translate_mode(chat_id)
    except DbError:
        logger.warning("Режим перевода чата %s не прочитался", log_id(chat_id), exc_info=True)
        return translate_modes.DEFAULT_MODE
    return mode if mode in translate_modes.MODES else translate_modes.DEFAULT_MODE


def _fields(finding: domain.Finding) -> dict[str, str]:
    """Поля записи со свободным текстом аудитора и их значения; пустые не берём."""
    fields = {"comment": finding.comment}
    if finding.level == ADVICE_LEVEL:
        fields["text"] = finding.text
    return {name: value for name, value in fields.items() if value.strip()}


def translate_comments(chat_id: int, inspection: domain.Inspection) -> int:
    """Перевести комментарии на язык отчёта, если человек выбрал «Автоматически».

    Возвращает, сколько полей перевести не удалось (0 — всё хорошо или перевод не
    нужен). Язык отчёта равен языку чек-листа — переводить нечего.
    """
    target = inspection.report_lang
    if target == inspection.speech_lang or mode_of(chat_id) != translate_modes.AUTO:
        return 0
    with chat_usage(chat_id):
        return _translate_findings(chat_id, inspection, target)


def _translate_findings(chat_id: int, inspection: domain.Inspection, target: str) -> int:
    failed = 0
    for finding in inspection.findings:
        done: dict[str, str] = {}
        for name, source in _fields(finding).items():
            try:
                translated = translate_text(source, lang=target)
            except RecognizeError:
                logger.warning(
                    "Автоперевод: запись #%s чата %s не переведена",
                    finding.n,
                    log_id(chat_id),
                    exc_info=True,
                )
                failed += 1
                continue
            if len(translated) > MAX_TEXT:
                logger.warning(
                    "Автоперевод: запись #%s чата %s — перевод слишком длинный",
                    finding.n,
                    log_id(chat_id),
                )
                failed += 1
            elif translated != source:
                done[name] = translated
        if done:
            try:
                domain.edit_finding(chat_id, finding.n, zone_by_person=False, repeat=None, **done)
            except DomainError:
                logger.warning(
                    "Автоперевод: запись #%s чата %s не сохранилась",
                    finding.n,
                    log_id(chat_id),
                    exc_info=True,
                )
                failed += len(done)
    return failed
