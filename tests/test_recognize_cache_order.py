"""#1267 (D646): постоянная часть запроса идёт первой, чтобы сработал кэш провайдера.

OpenAI кэширует общий ПРЕФИКС запроса (от 1024 токенов): всё, что стоит до первого
отличия, переиспользуется. Зона и слова аудитора у каждого запроса свои, поэтому они
обязаны стоять ПОСЛЕ перечня пунктов, а перечень — в постоянном порядке, одинаковом
для любой зоны и любых слов. Схема ответа — тоже часть префикса (провайдер дописывает
её к запросу), и перечисление `item` в ней обязано быть тем же.
"""

from __future__ import annotations

import os
from pathlib import Path

from src.recognize.classify import prepare_request
from src.recognize.config import NO_CHAT, RecognizeSettings, load_recognize_settings

_SETTINGS: RecognizeSettings = load_recognize_settings({"OPENAI_API_KEY": "k"})


def _request(note: str, zone: str | None):  # type: ignore[no-untyped-def]
    return prepare_request(note, None, zone, settings=_SETTINGS, chat_id=NO_CHAT)


def test_постоянная_часть_запроса_одинакова_при_любой_зоне_и_любых_словах(
    domain_env: Path,
) -> None:
    без_всего = _request("", None)
    зона = _request("", "hot_kitchen")
    слова = _request("под конвейерной лентой печи нагар", "cold_kitchen")
    другие_слова = _request("температура в холодильнике +9", "fridge")

    общий = os.path.commonprefix([r.ask.question for r in (без_всего, зона, слова, другие_слова)])

    assert "ДОПУСТИМЫЕ ЗНАЧЕНИЯ item" in общий, "перечень пунктов не попал в общий префикс"
    assert "- NONE" in общий, "общий префикс обрывается до конца перечня"
    for r in (зона, слова, другие_слова):
        assert r.ask.instructions == без_всего.ask.instructions
        assert r.ask.schema == без_всего.ask.schema, "перечисление схемы зависит от зоны или слов"


def test_зона_и_слова_стоят_после_перечня(domain_env: Path) -> None:
    запрос = _request("под конвейерной лентой печи нагар", "hot_kitchen").ask.question

    конец_перечня = запрос.index("- NONE")
    assert запрос.index("КОММЕНТАРИЙ АУДИТОРА") > конец_перечня
    assert запрос.index("Вероятная зона") > конец_перечня
    assert запрос.index("ПУНКТЫ ЗОНЫ") > конец_перечня


def test_порядок_зоны_и_слов_не_пропал_а_назван_явно(domain_env: Path) -> None:
    """Порядок — смысловой сигнал (shortlist.py): раньше он был порядком строк перечня."""
    запрос = _request("под конвейерной лентой печи нагар", "hot_kitchen").ask.question

    assert "ПУНКТЫ, ПОДНЯТЫЕ СЛОВАМИ" in запрос
    слова = запрос.split("ПУНКТЫ, ПОДНЯТЫЕ СЛОВАМИ", 1)[1].splitlines()[0]
    assert "CLN05" in слова, "карта слов подняла пункт про печь, а в запросе его нет"


def test_точка_кэша_стоит_ровно_после_перечня(domain_env: Path) -> None:
    запрос = _request("под лентой печи нагар", "hot_kitchen").ask

    assert запрос.question.startswith(запрос.cached_prefix)
    assert запрос.cached_prefix.endswith("- NONE — ни один пункт перечня не подходит")
    assert "КОММЕНТАРИЙ" not in запрос.cached_prefix, "в кэшируемую часть попала меняющаяся"
