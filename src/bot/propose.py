"""Предложения по кадрам и словам аудитора — общее ядро бота и мини-аппа (D330).

Коренная механика продукта: аудитор снимает и говорит пару слов, пункт, класс
и формулировку ищет система. Бот и мини-апп обхода ищут ОДНИМ путём, и этот
путь живёт здесь, а не в обработчике Telegram:

1. **Быстрый путь** (`recognize.fastpath`) — слова однозначно называют пункт
   методики. Модель не зовётся.
2. **Выученная фраза** (`bot.phrases.recall`, D119) — эта формулировка уже
   кончалась этим пунктом. Модель не зовётся.
3. **Модель** (`recognize.classify`) — с кадрами по правилам D208/D209: пачка
   с комментарием и кадр с комментарием идут в модель вместе со словами, голый
   кадр без слов — один, слова без кадра — одни.

Пачку с комментарием (D208) первые два шага не берут: по словам записалось бы
то, что сказано, и кадры никто бы не посмотрел.

Чем различаются бот и мини-апп — только тем, что делается с найденным. Бот по
быстрому пути и выученной фразе пишет запись сразу (D064) и разговаривает с
аудитором в чате; мини-апп всё найденное только предлагает карточками, а
фиксирует человек нажатием «Сохранить». Поэтому здесь нет ни записи, ни
сообщений: только «что нашлось».
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from src import domain
from src.domain.errors import DomainError
from src.recognize.classify import album_mode, classify, framed, needs_photo
from src.recognize.fastpath import fast_path
from src.recognize.models import Candidate, Suggestion

from .phrases import recall

#: Уверенность предложения, найденного без модели: слова назвали пункт прямо.
CERTAIN = 1.0

Via = Literal["fast", "learned", "model"]


@dataclass(frozen=True)
class ModelFrames:
    """Какие кадры уходят в модель вместе со словами (D208, D209)."""

    #: Все кадры — пачкой, вместе с комментарием.
    all: bool
    #: Один первый кадр — слов нет, судить не по чему, кроме кадра.
    first: bool


def model_frames(note: str, frames: int, *, correcting: bool = False) -> ModelFrames:
    """Какие кадры смотрит модель. Одно правило для бота и мини-аппа.

    Кадр с комментарием — хоть один — модель смотрит вместе со словами (D209):
    по кадру выбирается класс (дата на наклейке, щуп), а не опровергается
    сказанное. Правка уже записанного кадров заново не разбирает.
    """
    every = not correcting and framed(note, frames)
    return ModelFrames(all=every, first=not every and frames > 0 and needs_photo(note))


def sent_at() -> str:
    """Время снимка для модели: по нему считается просрочка по наклейке (D209)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")


@dataclass(frozen=True)
class Offer:
    """Что нашлось. Ничего не записано — решает тот, кто показывает."""

    via: Via
    candidates: tuple[Candidate, ...]
    #: Что модель увидела на кадрах сверх сказанного (D208) — отдельно от
    #: найденного по словам: это предложение, а не ответ на сказанное.
    also_seen: tuple[Candidate, ...] = ()
    #: Вопрос модели аудитору — когда по словам и кадру не понять класс.
    question: str = ""
    #: Ответ модели целиком — для журнала разбора (#367). Без модели пусто.
    suggestion: Suggestion | None = None


def _only_level(code: str, chat_id: int) -> str:
    """Класс пункта, если методика даёт один. Иначе пусто — выберет человек."""
    try:
        levels = domain.allowed_levels(code, chat_id=chat_id)
    except DomainError:
        return ""
    return levels[0] if len(levels) == 1 else ""


def propose(
    note: str,
    frames: Sequence[bytes],
    *,
    zone: str | None,
    chat_id: int,
    ui_lang: str,
    speech_lang: str,
    report_lang: str,
) -> Offer:
    """Найти пункт по словам и кадрам тем же порядком, что у бота.

    `zone` — зона, которую назвал человек (остановка обхода): подсказка
    поиску, а не ответ. `note` — сказанное дословно: при пути без модели оно
    же становится формулировкой, как у бота.

    Ошибки модели (`ModelUnavailable`, `RecognizeError`) не ловятся: что
    показать вместо предложений, решает вызывающий.
    """
    words = note.strip()
    if words and not album_mode(words, len(frames)):
        fast = fast_path(words, zone, lang=ui_lang, chat_id=chat_id).item
        if fast is not None:
            return Offer(
                via="fast",
                candidates=(
                    Candidate(
                        code=fast.code,
                        level=fast.level,
                        zone=fast.zone,
                        wording=words,
                        confidence=CERTAIN,
                    ),
                ),
            )
        learned = recall(words, lang=speech_lang, chat_id=chat_id)
        if learned is not None:
            return Offer(
                via="learned",
                candidates=(
                    Candidate(
                        code=learned.code,
                        level=_only_level(learned.code, chat_id),
                        zone=zone or "",
                        wording=words,
                        confidence=CERTAIN,
                    ),
                ),
            )
    which = model_frames(words, len(frames))
    suggestion = classify(
        words,
        frames[0] if which.first else None,
        zone,
        lang=report_lang,
        chat_id=chat_id,
        photos=tuple(frames) if which.all else (),
        sent_at=sent_at(),
    )
    return Offer(
        via="model",
        candidates=suggestion.candidates,
        also_seen=suggestion.also_seen,
        question=suggestion.question,
        suggestion=suggestion,
    )
