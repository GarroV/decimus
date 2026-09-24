"""T031: разбор комментария аудитора в предложения записей.

Порядок один и тот же: сузить перечень (`shortlist`) → собрать строгую схему по
этому перечню (`schema`) → задать вопрос модели (`client`) → разобрать ответ.
Ни на одном шаге ничего не досочиняется: код и класс приходят перечислением,
зона — из слов аудитора или подсказки, а решение принимает человек.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import Any

from src.domain import list_zones

from .client import ask_model
from .config import DEFAULT_LANG, RecognizeSettings, load_recognize_settings
from .cues import class_thresholds
from .models import NONE_CODE, UNKNOWN_ZONE, Candidate, Suggestion
from .prompt import instructions, question_text
from .rules_check import check_wording
from .schema import picks_for, response_schema, split_pick
from .shortlist import shortlist


def _clamp(value: Any) -> float:
    """Уверенность в границах 0…1. В строгой схеме границ числа не заявить."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return min(1.0, max(0.0, number))


def needs_photo(note: str) -> bool:
    """Смотреть ли на кадр. Есть комментарий — разбирается комментарий (D081).

    Решение D081: есть комментарий — разбирается только он, нет комментария —
    разбирается кадр и возвращается то, что на нём распознано. Развилки здесь
    больше нет: слова аудитора и кадр — два разных потока, а не два источника
    одного разбора.

    Прежнее правило пропускало кадр мимо модели ровно тогда, когда карта слов
    поднимала один пункт с единственным классом. На сегодняшней карте
    (`data/photo-cues.md`) таких случаев нет вовсе: из семнадцати боевых
    записей двух проверок кадр уезжал в запрос во всех семнадцати — прогон
    старого правила по `examples/`, 05.09.2026. Единственная запись с одним
    поднятым пунктом попадала под общее правило по второй причине: у пункта
    больше одного допустимого класса. То есть экономии у оговорки не было
    никакой, она только выглядела экономией. Ценой
    были 1148 лишних токенов входа на комментарий и скачивание кадра у
    телеграма; выгодой считалось «поймать расхождение слов с изображением».
    Владелец от этой выгоды отказался: на точке правит человек, и правка теперь
    вносится ответом на сообщение бота (T204), а не догадкой модели о том, что
    аудитор смотрит не туда.

    `cue_hits` в сигнатуре больше нет намеренно: пока он там стоял, правило
    выглядело зависящим от карты слов, и следующий читатель искал бы, какой
    комментарий всё-таки отправит кадр. Не отправит ни один.
    """
    return not note.strip()


#: Сколько кадров делают материал пачкой (D180). Один кадр с комментарием
#: по-прежнему разбирается по словам (D081).
ALBUM_MIN_FRAMES = 2


def album_mode(note: str, frames: int) -> bool:
    """Пачка кадров с комментарием: модель смотрит и слова, и кадры (D180)."""
    return bool(note.strip()) and frames >= ALBUM_MIN_FRAMES


def _candidate(record: dict[str, Any]) -> Candidate | None:
    """Один кандидат из ответа модели. Зона берётся её ответом, и только им.

    `UNKNOWN` подсказкой НЕ подменяется (T264, #218). Раньше подменялся, и это
    был весь механизм промаха: модель отвечала честно «места не знаю», а сюда
    садилась зона ПРОШЛОЙ записи — так пункт про печь и уехал в холодный цех.
    Гадала не модель.

    `UNKNOWN` теперь доживает до `_suggestion`, где становится поводом спросить
    человека (`needs_human`), — то есть ровно тем, чем и был ответ модели.
    """
    code, level = split_pick(str(record.get("item", "")))
    if code == NONE_CODE or not level:
        return None
    zone = str(record.get("zone", UNKNOWN_ZONE))
    wording = str(record.get("wording", "")).strip()
    reason = str(record.get("reason", "")).strip()
    return Candidate(
        code=code,
        level=level,
        zone=zone,
        wording=wording,
        confidence=_clamp(record.get("confidence")),
        reason=reason,
        # Промпт запрещает додумывать масштаб, повреждение и похвалу (правила
        # 2-4), но у текста нет enum — соблюдение проверяется здесь, вторым
        # слоем, а не только просьбой в инструкции.
        flags=check_wording(wording, reason),
    )


def _candidates(raw: Any, settings: RecognizeSettings) -> tuple[Candidate, ...]:
    """Кандидаты из списка записей ответа; мусор и NONE отбрасываются."""
    records = raw if isinstance(raw, list) else []
    return tuple(
        c
        for record in records
        if isinstance(record, dict)
        for c in (_candidate(record),)
        if c is not None
    )[: settings.max_candidates]


def _suggestion(
    payload: dict[str, Any],
    usage: dict[str, int],
    settings: RecognizeSettings,
    *,
    used_photo: bool,
) -> Suggestion:
    candidates = _candidates(payload.get("records"), settings)
    question = str(payload.get("question", "")).strip()
    top = candidates[0] if candidates else None
    needs_human = (
        top is None
        or bool(question)
        or top.confidence < settings.min_confidence
        or top.zone == UNKNOWN_ZONE
    )
    return Suggestion(
        candidates=candidates,
        needs_human=needs_human,
        question=question,
        used_photo=used_photo,
        usage=usage,
    )


def classify(
    note: str,
    photo: bytes | None = None,
    zone_hint: str | None = None,
    *,
    lang: str = DEFAULT_LANG,
    settings: RecognizeSettings | None = None,
    model: str | None = None,
    chat_id: int | None,
    photos: Sequence[bytes] = (),
) -> Suggestion:
    """Предложить записи по комментарию аудитора. Решение остаётся за ним.

    `lang` — язык формулировок и текста пунктов (язык отчёта проверки).
    `settings` и `model` нужны замеру точности (T035), который гоняет один и тот
    же вход по нескольким моделям; бот их не передаёт.

    `chat_id` обязателен и умолчания не имеет (T226): весь запрос — перечень
    кандидатов, перечисление классов, названия зон, пороги из карты слов —
    собирается по изданию ТОЙ проверки (T169), а не по каталогу, который лежит
    в `AUDIT_DATA_DIR` сейчас. Пустой чат (`config.NO_CHAT`) — законное
    «проверки нет»: так зовут замеры по выгрузкам `examples/`.
    """
    album = album_mode(note, len(photos))
    cfg = settings or load_recognize_settings()
    picked = shortlist(note, zone_hint, chat_id=chat_id)
    picks = picks_for(picked.codes, chat_id=chat_id)
    zones = list_zones(chat_id=chat_id)
    use_photo = album or (photo is not None and needs_photo(note))
    answer = ask_model(
        instructions=instructions(class_thresholds(chat_id=chat_id)),
        question=question_text(
            note,
            picks,
            zones,
            zone_hint,
            lang,
            with_photo=use_photo,
            chat_id=chat_id,
            album_frames=len(photos) if album else 0,
        ),
        schema=response_schema(picks, [z.code for z in zones], album=album),
        photo=photo if use_photo and not album else None,
        photos=photos if album else (),
        settings=cfg,
        model=model,
    )
    return replace(
        _suggestion(answer.payload, answer.usage, cfg, used_photo=use_photo),
        shortlist=picked.codes,
        also_seen=_candidates(answer.payload.get("also_seen"), cfg) if album else (),
    )
