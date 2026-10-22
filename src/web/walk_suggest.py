"""Мини-апп обхода: поиск пункта по кадру и словам (D330) — `POST /tg/walk/suggest`.

Коренная механика продукта: аудитор снимает и говорит пару слов, пункт ищет
система. Ищет она тем же путём, что бот (`bot.propose`: быстрый путь →
выученная фраза → модель с кадрами по D208/D209), и ничего не записывает:
ответ — карточки предложений, а запись появляется только по «Сохранить»
обычным `POST /tg/walk/finding` (модель предлагает, фиксирует человек).

Опознание и замки те же, что у записи: подпись Telegram в заголовке, сданная
проверка не ищет — после сдачи записывать уже некуда.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any

from flask import Flask, Response, jsonify, request

from src.bot import journal
from src.bot.propose import Offer, propose
from src.bot.zones import allowed_zones, zone_from_words
from src.db import queries
from src.db.busy_lock import WALK_SUGGEST, try_hold
from src.db.errors import DbError
from src.domain import check_environment, get_state, handed_over, upload_file
from src.domain.errors import DomainError
from src.domain.log_ids import log_id
from src.domain.model_usage import KIND_SUGGEST, usage_scope
from src.recognize.errors import ModelUnavailable, RecognizeError
from src.recognize.models import Candidate

from .texts_walk import WALK_TEXTS
from .walk_auth import SUGGEST_ENDPOINT, SUGGEST_PATH, WalkSettings
from .walk_write import Identify, WalkRefused, _code, _refs, _text, reading_of
from .walk_zone import resolve_item_zone

logger = logging.getLogger(__name__)

#: Сколько кадров уходит в один поиск (F-120). Каждый читается в память и
#: отправляется в платный вызов модели; настоящий запрос несёт два-три кадра,
#: двадцать — с большим запасом. Остальные не отправляются, ответ говорит об этом.
MAX_SUGGEST_PHOTOS = 20


def _frames(refs: list[str]) -> list[bytes]:
    """Байты кадров мини-аппа — той же дверью, что у бота (`bot.photos`)."""
    settings = check_environment()
    frames: list[bytes] = []
    for ref in refs:
        path = upload_file(ref, settings)
        if path is None:
            raise WalkRefused("walk.err.photo_lost")
        frames.append(path.read_bytes())
    return frames


def _card(c: Candidate, offer: Offer, ask: Ask) -> dict[str, Any]:
    # Зона записи — не зона экрана (D445): выводится по пункту и словам.
    # Зону кандидата как «зону модели» берём только у модели: у быстрого пути
    # и выученной фразы это эхо подсказки с экрана, а не её вывод.
    options = allowed_zones(c.code, chat_id=ask.chat_id)
    found = resolve_item_zone(
        options,
        spoken=ask.spoken,
        model=c.zone if offer.via == "model" else None,
        hint=ask.hint,
        usual=lambda: _usual_zone(ask.tenant, c.code),
    )
    return {
        "code": c.code,
        "level": c.level,
        "zone": c.zone,
        "wording": c.wording,
        "confidence": round(c.confidence, 2),
        # Показание термометра, прочитанное моделью (#836): форма показывает его
        # числовым полем, и аудитор его правит.
        "reading_c": c.reading_c,
        # Пометки проверки правил (`rules_check`): бот их показывал, а обход —
        # нет, и служебная оговорка модели уехала в отчёт как текст записи (#970).
        "flags": list(c.flags),
        "resolution": {
            "zone": found.zone,
            "source": found.source,
            "options": list(found.options),
        },
    }


def _usual_zone(tenant: str | None, code: str) -> str | None:
    """Привычная зона пункта (#1109). База молчит — спросим человека, как раньше."""
    if not tenant:
        return None
    try:
        return queries.usual_zone(tenant=tenant, code=code)
    except DbError:
        logger.warning("Обход: привычная зона пункта %s недоступна", code, exc_info=True)
        return None


@dataclass(frozen=True)
class Ask:
    """Что известно о запросе при выводе зоны: слова, подсказка, чат."""

    chat_id: int
    spoken: str | None
    hint: str | None
    #: Пространство проверки — для привычной зоны пункта (#1109). Пусто — не спрашивать.
    tenant: str | None = None


def cap_photos(value: Any) -> tuple[Any, int]:
    """Первые `MAX_SUGGEST_PHOTOS` ссылок и сколько отброшено; не список — как есть."""
    if isinstance(value, list) and len(value) > MAX_SUGGEST_PHOTOS:
        return value[:MAX_SUGGEST_PHOTOS], len(value) - MAX_SUGGEST_PHOTOS
    return value, 0


def answer(offer: Offer, ask: Ask) -> dict[str, Any]:
    # Увиденное на кадрах сверх сказанного (D208) — после найденного по
    # словам: у бота это отдельное предложение, здесь — нижние карточки.
    seen = [c for c in offer.also_seen if all(c.code != x.code for x in offer.candidates)]
    # Пункты словаря, которых модель не назвала, задав вопрос (D597), — в самом низу.
    cue = offer.suggestion.cue_extras if offer.suggestion else ()
    extras = [c for c in cue if all(c.code != x.code for x in (*offer.candidates, *seen))]
    return {
        "via": offer.via,
        "candidates": [_card(c, offer, ask) for c in (*offer.candidates, *seen, *extras)],
        "question": offer.question,
        # Ответы на вопрос о классе первой карточки — кнопками (#1107).
        "answers": [
            {"text": a.text, "level": a.level}
            for a in (offer.suggestion.answers if offer.suggestion else ())
        ],
    }


def install(app: Flask, *, conf: WalkSettings, ui_lang: str, identify: Identify) -> None:
    """Повесить поиск пункта. Опознание — то же, что у записи.

    Один поиск на чат за раз: каждый — оплачиваемый вызов модели, и второй,
    пока идёт первый, — это двойное нажатие или зацикленный клиент, а не
    работа аудитора. «За раз» — на все процессы: внутри процесса держит набор,
    между процессами — замок в базе (`src/db/busy_lock.py`, F-110).
    """
    busy: set[int] = set()
    guard = threading.Lock()

    def refused(key: str, lang: str, status: int = 422) -> tuple[Response, int]:
        entry = WALK_TEXTS[key]
        return jsonify({"error": "refused", "message": entry.get(lang) or entry[ui_lang]}), status

    @app.post(SUGGEST_PATH, endpoint=SUGGEST_ENDPOINT)
    def walk_suggest() -> tuple[Response, int]:
        who = identify(conf, ui_lang, header_only=True)
        if not isinstance(who, int):
            return who
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return refused("walk.err.bad_request", ui_lang, 400)
        inspection = get_state(who)
        if inspection is None:
            return refused("walk.none.title", ui_lang, 409)
        lang = inspection.ui_lang
        if handed_over(who):
            return refused("walk.sealed", lang, 409)
        with guard:
            if who in busy:
                return refused("walk.err.suggest_busy", lang, 429)
            busy.add(who)
        hold = try_hold(WALK_SUGGEST, str(who))
        if not hold.acquired:
            with guard:
                busy.discard(who)
            return refused("walk.err.suggest_busy", lang, 429)
        try:
            words = _text(body, "words")
            # Зона на экране — только подсказка (D445). Старый клиент слал её
            # полем `zone`.
            hint_key = "zone_hint" if body.get("zone_hint") else "zone"
            zone = _code(body, hint_key) if body.get(hint_key) else None
            photos, omitted = cap_photos(body.get("photos"))
            frames = _frames(_refs(photos, who, inspection))
            # Расход модели (D537): подбор на экране — свой вид вызова.
            with usage_scope(kind=KIND_SUGGEST, telegram_id=who, tenant=inspection.tenant):
                offer = propose(
                    words,
                    frames,
                    zone=zone,
                    chat_id=who,
                    ui_lang=inspection.ui_lang,
                    speech_lang=inspection.speech_lang,
                    report_lang=inspection.report_lang,
                    # Исправленная температура: тот же поиск, с утверждением «реально
                    # N °C» (#836). Пусто — обычный поиск.
                    reading_c=reading_of(body),
                )
        except WalkRefused as exc:
            return refused(str(exc), lang)
        except ModelUnavailable as exc:
            # Модель недоступна — обход не встаёт: аудитор выбирает пункт
            # вручную, как в боте. Сырой текст исключения — в журнал.
            logger.warning("Обход: модель недоступна для чата %s: %s", log_id(who), exc)
            return refused("walk.err.recognize", lang, 503)
        except (RecognizeError, DomainError) as exc:
            logger.warning("Обход: поиск пункта для чата %s не удался: %s", log_id(who), exc)
            return refused("walk.err.recognize", lang, 503)
        finally:
            hold.release()
            with guard:
                busy.discard(who)
        # Что ушло в поиск и что вернулось (#367) — тем же журналом, что у
        # бота: промах разбирается по нему, а не по скриншотам.
        journal.note(
            who,
            "walk_suggest",
            via=offer.via,
            words=words,
            zone=zone,
            frames=len(frames),
            frames_omitted=omitted,
            candidates=journal.candidates(offer.candidates),
            also_seen=journal.candidates(offer.also_seen),
            question=offer.question,
            usage=offer.suggestion.usage if offer.suggestion else {},
        )
        logger.info(
            "Обход: чат %s — поиск пункта %s, предложений %s",
            log_id(who),
            offer.via,
            len(offer.candidates),
        )
        ask = Ask(
            chat_id=who,
            spoken=zone_from_words(words, chat_id=who),
            hint=zone,
            tenant=inspection.tenant,
        )
        reply = answer(offer, ask)
        if omitted:
            # Не ошибка: поиск идёт по первым кадрам, клиент видит, что часть не учтена.
            reply["photos_omitted"] = omitted
        return jsonify(reply), 200
