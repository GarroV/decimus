"""«Добавить нарушение» на вычитке: подбор пункта по словам и кадрам (D535).

Вычитывающий вписывает, что не так, прикладывает кадры, а пункт, класс и зону
ищет система — **тем же путём, что бот и мини-апп обхода** (`bot.propose.propose`:
быстрый путь → выученная фраза → модель с кадрами). Ничего своего в поиске нет:
ни второго подбора, ни своих порогов. Из мини-аппа взята и сборка карточек
предложений (`walk_suggest.answer`) вместе с выводом зоны (D445).

Подбор **ничего не записывает**. Ответ — карточки; запись появляется только
обычным `POST /inspections/<id>/findings`, когда человек выбрал пункт и нажал
«Добавить» (модель предлагает, фиксирует человек). Пункт без выбора сервер
не принимает (`revision._checked_entry`), поэтому «создать по подсказке молча»
невозможно и в обход экрана.

Предложение, которого нет в чек-листе версии ЭТОЙ проверки, не показывается:
поиск идёт по изданию, при котором проверку начали (`chat_id` проверки), но
если снимка издания рядом нет, он берёт действующую методику — и записать такой
пункт в проверку всё равно нельзя.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any

from src.bot.propose import propose
from src.bot.zones import zone_from_words
from src.db.errors import StorageError
from src.db.models import InspectionRow
from src.db.previews import make_preview
from src.domain.errors import DomainError
from src.domain.log_ids import log_id
from src.domain.model_usage import KIND_SUGGEST, usage_scope
from src.recognize.errors import RecognizeError

from .review import Sheet
from .walk_suggest import Ask, answer

logger = logging.getLogger(__name__)

#: Сколько предложений показать. Модель отдаёт до `max_candidates`, но экран
#: вычитки — не лента: остальное человек найдёт поиском по пунктам.
SHOWN_MAX = 5

#: Предел слов: тот же, что у формулировки записи (`revision.MAX_TEXT`).
WORDS_MAX = 1000


class SuggestRefused(Exception):
    """Подобрать не вышло. `key` — ключ текста для экрана, `status` — код ответа."""

    def __init__(self, key: str, status: int = 422) -> None:
        super().__init__(key)
        self.key = key
        self.status = status


@dataclass
class _Busy:
    """Один подбор на проверку за раз: каждый — оплачиваемый вызов модели."""

    held: set[str]
    lock: threading.Lock


_busy = _Busy(held=set(), lock=threading.Lock())


def _take(inspection_id: str) -> None:
    with _busy.lock:
        if inspection_id in _busy.held:
            raise SuggestRefused("proofread.suggest.busy", 429)
        _busy.held.add(inspection_id)


def _release(inspection_id: str) -> None:
    with _busy.lock:
        _busy.held.discard(inspection_id)


def _previews(raw: list[bytes]) -> list[bytes]:
    """Кадры для модели — сжатые копии (D219): и проверка, что это изображения."""
    try:
        return [make_preview(data) for data in raw]
    except StorageError as exc:
        raise SuggestRefused("photo.unreadable") from exc


def _card(card: dict[str, Any], sheet: Sheet, zone_names: dict[str, str]) -> dict[str, Any] | None:
    """Карточка предложения для экрана вычитки; `None` — пункта нет в версии."""
    pick = next((p for p in sheet.picks if p.code == card["code"]), None)
    if pick is None:
        return None
    level = card["level"] if card["level"] in pick.levels else ""
    zone = card["resolution"]["zone"] or ""
    return {
        "code": pick.code,
        "label": pick.label,
        "title": pick.question,
        "level": level,
        "levels": list(pick.levels),
        "zone": zone,
        "zone_name": zone_names.get(zone, ""),
        "wording": card["wording"],
        "confidence": card["confidence"],
        "reading_c": card["reading_c"],
    }


def suggest(
    head: InspectionRow,
    sheet: Sheet,
    *,
    words: str,
    frames: list[bytes],
    lang: str,
) -> dict[str, Any]:
    """Найти пункты по словам и кадрам. Отказ — `SuggestRefused` со словами для экрана."""
    said = words.strip()
    if not said and not frames:
        raise SuggestRefused("proofread.suggest.empty")
    _take(head.id)
    try:
        previews = _previews(frames)
        # Расход модели (D537): подбор на экране — свой вид вызова, проверка — по номеру в базе.
        with usage_scope(kind=KIND_SUGGEST, inspection_ref=str(head.id)):
            offer = propose(
                said,
                previews,
                zone=None,
                chat_id=head.chat_id,
                ui_lang=lang,
                speech_lang=lang,
                report_lang=head.report_lang,
            )
        ask = Ask(
            chat_id=head.chat_id, spoken=zone_from_words(said, chat_id=head.chat_id), hint=None
        )
        found = answer(offer, ask)
    except SuggestRefused:
        raise
    except (RecognizeError, DomainError) as exc:
        # Модель недоступна, ключа нет, методика не читается — экран говорит
        # «не вышло, выберите пункт вручную»; подробность — в журнал сервера.
        logger.warning(
            "вычитка: подбор пункта для проверки %s не вышел: %s", log_id(head.chat_id), exc
        )
        raise SuggestRefused("proofread.suggest.failed", 503) from exc
    finally:
        _release(head.id)
    zone_names = {z.code: z.name for z in sheet.zones}
    cards = [c for c in (_card(x, sheet, zone_names) for x in found["candidates"]) if c is not None]
    logger.info(
        "вычитка: подбор пункта для проверки %s — %s, предложений %s из %s",
        log_id(head.chat_id),
        offer.via,
        len(cards),
        len(found["candidates"]),
    )
    return {
        "via": found["via"],
        "candidates": cards[:SHOWN_MAX],
        "question": found["question"],
        "hidden": len(found["candidates"]) - len(cards),
    }
