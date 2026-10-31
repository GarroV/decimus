"""T031: разбор комментария аудитора в предложения записей.

Порядок один и тот же: сузить перечень (`shortlist`) → собрать строгую схему по
этому перечню (`schema`) → задать вопрос модели (`client`) → разобрать ответ.
Ни на одном шаге ничего не досочиняется: код и класс приходят перечислением,
зона — из слов аудитора или подсказки, а решение принимает человек.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any

from src.domain import get_item, list_zones
from src.domain.model_usage import KIND_RECOGNIZE
from src.domain.models import READING_MAX_C, READING_MIN_C

from .client import ModelAnswer, ask_model
from .config import DEFAULT_LANG, RecognizeSettings, load_recognize_settings
from .cues import class_thresholds
from .guard import MAX_QUESTION_CHARS, MAX_REASON_CHARS, MAX_WORDING_CHARS, clean_text
from .models import ANSWER_LEVELS, NONE_CODE, UNKNOWN_ZONE, Answer, Candidate, Suggestion
from .prompt import catalog_text, correction_line, instructions, question_text, readings_line
from .provenance import frame_indices
from .rules_check import check_wording
from .schema import picks_for, response_schema, split_pick
from .shortlist import shortlist
from .timing import measure


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


#: Сколько кадров делают материал пачкой (D208). Пачка — это то, что обходит
#: быстрый путь по словам; кадры в модель уходят при любом их числе (D209).
ALBUM_MIN_FRAMES = 2


def album_mode(note: str, frames: int) -> bool:
    """Пачка кадров с комментарием (D208): быстрый путь по словам её не пишет."""
    return bool(note.strip()) and frames >= ALBUM_MIN_FRAMES


def framed(note: str, frames: int) -> bool:
    """Кадры с комментарием уходят в модель вместе со словами (D208, D209).

    Любое число кадров, начиная с одного: D081 («есть комментарий — кадр в
    модель не идёт») снят владельцем после боевого случая 25.09.2026 — дата
    просрочки была на наклейке, а модель кадра не видела и занизила класс.
    """
    return bool(note.strip()) and frames >= 1


def _candidate(record: dict[str, Any], frame_count: int = 0) -> Candidate | None:
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
    wording = clean_text(str(record.get("wording", "")), MAX_WORDING_CHARS)
    reason = clean_text(str(record.get("reason", "")), MAX_REASON_CHARS)
    return Candidate(
        code=code,
        level=level,
        zone=zone,
        wording=wording,
        confidence=_clamp(record.get("confidence")),
        reason=reason,
        reading_c=_reading(record.get("reading_c")),
        frame_indices=frame_indices(record.get("frame_indices"), frame_count),
        # Промпт запрещает додумывать масштаб, повреждение и похвалу (правила
        # 2-4), но у текста нет enum — соблюдение проверяется здесь, вторым
        # слоем, а не только просьбой в инструкции.
        flags=check_wording(wording, reason),
    )


def _reading(value: Any) -> float | None:
    """Показание термометра из ответа модели: число в разумных пределах либо ничего.

    Булево значение числом не считается (`True` — это 1), а запредельное
    (`1e9`, `nan`) — признак мусора, и показать его аудитору как «температуру на
    фото» значило бы выдать мусор за измерение.
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    reading = float(value)
    return reading if READING_MIN_C <= reading <= READING_MAX_C else None


def _candidates(
    raw: Any, settings: RecognizeSettings, frame_count: int = 0
) -> tuple[Candidate, ...]:
    """Кандидаты из списка записей ответа; мусор и NONE отбрасываются."""
    records = raw if isinstance(raw, list) else []
    return tuple(
        c
        for record in records
        if isinstance(record, dict)
        for c in (_candidate(record, frame_count),)
        if c is not None
    )[: settings.max_candidates]


#: Длина кнопки ответа: длиннее — это уже не ответ, а пересказ.
MAX_ANSWER_CHARS = 80


def _answers(raw: Any) -> tuple[Answer, ...]:
    """Варианты ответа на вопрос о классе (#1107) — все годные или ни одного.

    Кнопки обещают «нажми — будет такой класс», поэтому негодный набор не
    чинится по частям: один вариант — не выбор, одинаковый класс у всех — ответ
    класс не меняет, пустой текст или класс вне методики — мусор. Тогда вопрос
    остаётся текстом, как было до вариантов.
    """
    if not isinstance(raw, list):
        return ()
    out: list[Answer] = []
    for entry in raw:
        if not isinstance(entry, dict):
            return ()
        text = clean_text(str(entry.get("text", "")), MAX_ANSWER_CHARS)
        level = str(entry.get("level", ""))
        if not text or level not in ANSWER_LEVELS:
            return ()
        out.append(Answer(text=text, level=level))
    if len(out) < 2 or len({a.level for a in out}) < 2:
        return ()
    return tuple(out)


def _suggestion(
    payload: dict[str, Any],
    usage: dict[str, int],
    settings: RecognizeSettings,
    *,
    used_photo: bool,
    frame_count: int = 0,
) -> Suggestion:
    candidates = _candidates(payload.get("records"), settings, frame_count)
    question = clean_text(str(payload.get("question", "")), MAX_QUESTION_CHARS)
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
        # Варианты без вопроса не показать: нечему отвечать.
        answers=_answers(payload.get("answers")) if question else (),
        used_photo=used_photo,
        usage=usage,
    )


@dataclass(frozen=True)
class AskArgs:
    """Аргументы `ask_model` одним куском: собрали сейчас, спросят потом."""

    kind: str
    instructions: str
    question: str
    schema: dict[str, Any]
    photo: bytes | None
    photos: Sequence[bytes]
    settings: RecognizeSettings
    model: str | None
    #: Начало `question`, неизменное от запроса к запросу, — за ним точка кэша (#1267).
    cached_prefix: str = ""

    def call(self) -> ModelAnswer:
        return ask_model(
            kind=self.kind,
            instructions=self.instructions,
            question=self.question,
            schema=self.schema,
            photo=self.photo,
            photos=self.photos,
            settings=self.settings,
            model=self.model,
            cached_prefix=self.cached_prefix,
        )


@dataclass(frozen=True)
class PreparedRequest:
    """Собранный запрос к модели и то, что нужно знать при разборе ответа."""

    ask: AskArgs
    settings: RecognizeSettings
    shortlist: tuple[str, ...]
    used_photo: bool
    album: bool
    reading_c: float | None
    frame_count: int = 0
    #: Строки словаря подсказок, поднятые словами аудитора, — пункты с первым
    #: допустимым классом; запас на случай, когда модель спрашивает (D597).
    cue_rows: tuple[tuple[tuple[str, str], ...], ...] = ()


def prepare_request(
    note: str,
    photo: bytes | None = None,
    zone_hint: str | None = None,
    *,
    lang: str = DEFAULT_LANG,
    settings: RecognizeSettings | None = None,
    model: str | None = None,
    chat_id: int | None,
    photos: Sequence[bytes] = (),
    sent_at: str = "",
    reading_c: float | None = None,
) -> PreparedRequest:
    """Собрать запрос к модели по комментарию аудитора — сам вызов не делается.

    Выделено из `classify`, чтобы MCP собирал запросы под издание черновика по
    очереди (каталог методики назначается на время сборки, `pinned_data_dir`), а
    сами вызовы к модели слал пакетом параллельно. Бот зовёт `classify` — тот же
    путь целиком.


    `reading_c` — температура, которую аудитор ИСПРАВИЛ после того, как модель
    неверно прочла термометр (#836). Тот же запрос, того же семейства промптов,
    с одним добавленным утверждением; в каждом ответе показание — это число
    аудитора, а не повторное чтение кадра.

    `lang` — язык формулировок и текста пунктов (язык отчёта проверки).
    `settings` и `model` нужны замеру точности (T035), который гоняет один и тот
    же вход по нескольким моделям; бот их не передаёт.

    `chat_id` обязателен и умолчания не имеет (T226): весь запрос — перечень
    кандидатов, перечисление классов, названия зон, пороги из карты слов —
    собирается по изданию ТОЙ проверки (T169), а не по каталогу, который лежит
    в `AUDIT_DATA_DIR` сейчас. Пустой чат (`config.NO_CHAT`) — законное
    «проверки нет»: так зовут замеры по выгрузкам `examples/`.
    """
    album = framed(note, len(photos))
    cfg = settings or load_recognize_settings()
    picked = shortlist(note, zone_hint, chat_id=chat_id)
    # Перечень значений — в постоянном порядке чек-листа (#1267): порядок зоны и слов
    # назван в конце запроса, чтобы общий префикс кэшировался провайдером.
    picks = picks_for(picked.canonical, chat_id=chat_id)
    zones = list_zones(chat_id=chat_id)
    use_photo = album or (photo is not None and needs_photo(note))
    readings = readings_line(tuple(dict.fromkeys(row[0] for row in picked.cue_rows)))
    catalog = catalog_text(picks, zones, lang, chat_id=chat_id)
    ask = AskArgs(
        kind=KIND_RECOGNIZE,
        instructions=instructions(class_thresholds(chat_id=chat_id)),
        question=question_text(
            note if reading_c is None else f"{note.strip()}\n{correction_line(reading_c)}".strip(),
            picks,
            zones,
            zone_hint,
            lang,
            with_photo=use_photo,
            chat_id=chat_id,
            album_frames=len(photos) if album else 0,
            sent_at=sent_at,
            catalog=catalog,
            zone_codes=picked.zone_codes,
            raised_codes=picked.cue_hits,
        )
        + (f"\n\n{readings}" if readings else ""),
        schema=response_schema(picks, [z.code for z in zones], album=album),
        photo=photo if use_photo and not album else None,
        photos=photos if album else (),
        settings=cfg,
        model=model,
        cached_prefix=catalog,
    )
    return PreparedRequest(
        ask=ask,
        settings=cfg,
        shortlist=picked.codes,
        used_photo=use_photo,
        album=album,
        reading_c=reading_c,
        frame_count=len(ask.photos) + int(ask.photo is not None),
        cue_rows=tuple(
            tuple((code, get_item(code, chat_id=chat_id).levels[0]) for code in row)
            for row in picked.cue_rows
        ),
    )


#: Сколько пунктов словаря дописывается к ответу с вопросом — не больше двух:
#: это подсказка «может быть и это», а не второй перечень.
MAX_CUE_EXTRAS = 2

#: Пометка дописанного кандидата: его нашёл словарь, а не модель.
CUE_REASON = "по словарю подсказок"


def with_cue_extras(found: Suggestion, cue_rows: Sequence[Sequence[tuple[str, str]]]) -> Suggestion:
    """Модель спрашивает — дописать пункты словаря, которых она не назвала (D597).

    Правило 7 велит модели при двусмысленных словах дать оба пункта, но по
    пробам на боевой методике она делает это не всегда: «не была произведена
    уборка в туалете» у снимка графика давала только чистоту туалета. Словарь
    подсказок — документ управляющей компании, и пункт, который он связывает
    со словами аудитора, показывается рядом, ниже предложенных моделью, без
    формулировки — её пишет аудитор. Отдельным полем, а не хвостом
    `candidates`: бот строит по кандидатам строки с формулировкой и зоной, а у
    этого пункта нет ни того, ни другого. Без вопроса модель уверена, и запас
    не нужен.

    По одному пункту из строки, и строка, из которой модель уже назвала пункт,
    пропускается: строка — один объект, и её второй код (поломка того же
    туалета) — не другое прочтение слов, а шум, который вытеснил бы нужное.
    """
    if not found.question:
        return found
    named = {c.code for c in found.candidates}
    picked: dict[str, str] = {}
    for row in cue_rows:
        if any(code in named for code, _ in row):
            continue
        fresh = [(code, level) for code, level in row if code != NONE_CODE and code not in picked]
        if fresh:
            picked.setdefault(*fresh[0])
    extras = tuple(
        Candidate(
            code=code,
            level=level,
            zone=UNKNOWN_ZONE,
            wording="",
            confidence=0.0,
            reason=CUE_REASON,
        )
        for code, level in list(picked.items())[:MAX_CUE_EXTRAS]
    )
    if not extras:
        return found
    return replace(found, cue_extras=extras)


def finish(request: PreparedRequest, answer: ModelAnswer) -> Suggestion:
    """Разобрать ответ модели на собранный запрос в предложение."""
    found = replace(
        _suggestion(
            answer.payload,
            answer.usage,
            request.settings,
            used_photo=request.used_photo,
            frame_count=request.frame_count,
        ),
        shortlist=request.shortlist,
        frame_count=request.frame_count,
        also_seen=(
            _candidates(answer.payload.get("also_seen"), request.settings, request.frame_count)
            if request.album
            else ()
        ),
    )
    found = with_cue_extras(found, request.cue_rows)
    reading_c = request.reading_c
    if reading_c is None:
        return found
    # Показание — слово аудитора: что бы модель ни вернула в поле, остаётся оно.
    return replace(
        found,
        candidates=tuple(replace(c, reading_c=reading_c) for c in found.candidates),
        also_seen=tuple(replace(c, reading_c=reading_c) for c in found.also_seen),
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
    sent_at: str = "",
    reading_c: float | None = None,
) -> Suggestion:
    """Предложить записи по комментарию аудитора. Решение остаётся за ним.

    `reading_c` — температура, которую аудитор ИСПРАВИЛ после того, как модель
    неверно прочла термометр (#836). Тот же запрос, того же семейства промптов,
    с одним добавленным утверждением; в каждом ответе показание — это число
    аудитора, а не повторное чтение кадра.

    `lang` — язык формулировок и текста пунктов (язык отчёта проверки).
    `settings` и `model` нужны замеру точности (T035), который гоняет один и тот
    же вход по нескольким моделям; бот их не передаёт.

    `chat_id` обязателен и умолчания не имеет (T226): весь запрос — перечень
    кандидатов, перечисление классов, названия зон, пороги из карты слов —
    собирается по изданию ТОЙ проверки (T169), а не по каталогу, который лежит
    в `AUDIT_DATA_DIR` сейчас. Пустой чат (`config.NO_CHAT`) — законное
    «проверки нет»: так зовут замеры по выгрузкам `examples/`.
    """
    with measure("prepare"):
        request = prepare_request(
            note,
            photo,
            zone_hint,
            lang=lang,
            settings=settings,
            model=model,
            chat_id=chat_id,
            photos=photos,
            sent_at=sent_at,
            reading_c=reading_c,
        )
    answer = request.ask.call()
    with measure("parse"):
        return finish(request, answer)
