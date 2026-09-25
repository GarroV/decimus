"""Края решения о синониме формулировки в разговоре (T285, решение D119).

`test_bot_learned_phrase.py` запирает три свойства самого решения: непрямое
совпадение копится, прямое — нет, а накопленное срабатывает. Здесь — то, что
остаётся вокруг этих трёх путей и без чего решение легко сломать по частям:
отказ карты (на чтении и на записи) не должен останавливать обход точки,
мёртвая строка карты не должна ронять разбор, класс и зону за аудитора никто
не выбирает молча, ключ карты — язык РЕЧИ, а не интерфейса, а починка неверного
пункта под записью без подтверждения остаётся доступной кнопкой «Разобрать
моделью».

Карта синонимов подменяется на уровне модуля `src.bot.phrases.synonyms`, как и
в соседнем файле: базы Postgres в прогоне нет, а поведение бота от неё не
зависит.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from bot_harness import (
    AUDITOR_ID,
    CHAT_ID,
    Calls,
    callback_query,
    candidate,
    feed,
    make_bot,
    photo_message,
    stub_classify,
    suggestion,
)

from src.bot.app import build_dispatcher
from src.bot.config import BotSettings
from src.bot.keyboards import MODEL_CALLBACK, ZONE_FOR_ITEM_PREFIX
from src.bot.phrases import synonyms
from src.bot.texts import t
from src.bot.zones import allowed_zones
from src.db.errors import SynonymError
from src.db.synonyms import LEARNED, REMEMBERED, PhraseAlias, PhraseMemory
from src.domain import get_state, start_inspection

pytestmark = pytest.mark.asyncio

SETTINGS = BotSettings(token="unused-in-tests", allowed_ids=frozenset({AUDITOR_ID}), mode="polling")

#: Пункт синтетической методики с ОДНОЙ зоной и одним классом.
ОДНОЗОННЫЙ = "CLN05"
#: Пункт многих зон, но одного класса — кандидат карты, место за аудитором.
МНОГОЗОННЫЙ = "PRD06"
#: Пункт с НЕСКОЛЬКИМИ классами — синоним пункта класс не хранит.
МНОГОКЛАССОВЫЙ = "PRD01"
#: Код, которого в синтетической методике нет и не было: строка карты,
#: пережившая снятый пункт.
НЕТ_ТАКОГО = "НЕТ-ТАКОГО"
#: Слова, которых карта кадров не знает: прямого совпадения не будет ни разу.
НЕПРЯМЫЕ_СЛОВА = "духовка закоптилась, глянь"


def начата() -> None:
    start_inspection(CHAT_ID, "Белград 2", "planned", "ru", date="2026-08-21", auditor="Гарро")


def _alias(code: str, phrase: str, *, lang: str = "ru") -> PhraseAlias:
    return PhraseAlias(
        item_code=code,
        lang=lang,
        phrase=phrase,
        key=synonyms.normalize_phrase(phrase),
        origin=LEARNED,
        created_at=None,  # type: ignore[arg-type]
    )


def _lookup_returns(monkeypatch: pytest.MonkeyPatch, alias: PhraseAlias | None) -> None:
    """Чтение карты отвечает заданным синонимом (или молчит — `None`)."""

    def _lookup(text: str, **kw: Any) -> PhraseAlias | None:
        return alias

    monkeypatch.setattr(synonyms, "lookup_phrase", _lookup)


def _lookup_raises(monkeypatch: pytest.MonkeyPatch, exc: Exception) -> None:
    """Чтение карты отказывает — так, как отказывает недоступная база."""

    def _lookup(text: str, **kw: Any) -> PhraseAlias | None:
        raise exc

    monkeypatch.setattr(synonyms, "lookup_phrase", _lookup)


def _remember_records(monkeypatch: pytest.MonkeyPatch) -> Calls:
    """Запись в карту проходит и складывается в список вызовов."""
    записано = Calls()

    def _remember(text: str, **kw: Any) -> PhraseMemory:
        записано.append((text, kw.get("item_code"), kw.get("lang"), kw.get("origin")))
        return PhraseMemory(
            REMEMBERED,
            PhraseAlias(
                item_code=str(kw.get("item_code")),
                lang=str(kw.get("lang")),
                phrase=text,
                key=synonyms.normalize_phrase(text),
                origin=str(kw.get("origin")),
                created_at=None,  # type: ignore[arg-type]
            ),
        )

    monkeypatch.setattr(synonyms, "remember_phrase", _remember)
    return записано


def _remember_raises(monkeypatch: pytest.MonkeyPatch, exc: Exception) -> None:
    """Запись в карту отказывает — так, как отказывает недоступная база."""

    def _remember(text: str, **kw: Any) -> PhraseMemory:
        raise exc

    monkeypatch.setattr(synonyms, "remember_phrase", _remember)


async def test_отказ_карты_на_чтении_не_останавливает_обход(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Невыученное слово — не повод остановить обход точки (`bot.phrases`).

    `lookup_phrase` бросает `SynonymError`: `recall` глотает любой `DbError` и
    отвечает «не знаю», а материал разбирается моделью как обычно. Аудитору
    об отказе карты не сказано ни слова — экран у него ровно тот же, что и без
    карты синонимов вовсе.
    """
    начата()
    _lookup_raises(monkeypatch, SynonymError("карта не отвечает на чтении"))
    # Запись в карту проходит: этот тест — про чтение, а не про запись, и не
    # должен зависеть от отдельного отказа записи (он заперт другим тестом).
    _remember_records(monkeypatch)
    звонки = stub_classify(
        monkeypatch, suggestion(candidate(ОДНОЗОННЫЙ, "D1", "hot_kitchen", "Нагар"))
    )
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await feed(dp, bot, photo_message("frame-1", caption=НЕПРЯМЫЕ_СЛОВА, message_id=601))
    await feed(dp, bot, callback_query("rec:pick:0"))

    состояние = get_state(CHAT_ID)
    assert состояние is not None and состояние.findings, (
        "материал не разобрался, хотя отказ карты обязан был пройти мимо"
    )
    assert звонки, "модель не была позвана, хотя карта отказала на чтении"
    assert all("уже сводили" not in text for text in session.texts), (
        "аудитору сказано про сработавший синоним, которого не было"
    )


async def test_отказ_карты_на_записи_не_отменяет_находку(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Отказ на записи в карту не должен утащить за собой саму запись.

    К моменту, когда `learn` зовёт `remember_phrase`, запись аудитора уже
    сделана и показана — «не сохранено» из-за невыученного слова было бы
    неправдой о его работе. Проверка целее памяти.
    """
    начата()
    _lookup_returns(monkeypatch, None)
    _remember_raises(monkeypatch, SynonymError("карта не приняла запись"))
    звонки = stub_classify(
        monkeypatch, suggestion(candidate(ОДНОЗОННЫЙ, "D1", "hot_kitchen", "Нагар"))
    )
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await feed(dp, bot, photo_message("frame-1", caption=НЕПРЯМЫЕ_СЛОВА, message_id=601))
    await feed(dp, bot, callback_query("rec:pick:0"))

    состояние = get_state(CHAT_ID)
    assert состояние is not None and состояние.findings, (
        "отказ карты на записи стёр саму находку по кандидату"
    )
    assert звонки, "материал должен был дойти до модели"
    assert t("error.unexpected", "ru") not in session.texts, (
        "отказ карты на записи дошёл до аудитора как сбой сервиса"
    )


async def test_синоним_снятого_пункта_не_роняет_разбор(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Строка карты пережила методику — пункта в издании этой проверки нет.

    `_applicable` отбраковывает такой код на чтении: разбор идёт дальше как
    обычно, до модели, а не падает и не ставит запись по мёртвой строке.
    """
    начата()
    _lookup_returns(monkeypatch, _alias(НЕТ_ТАКОГО, НЕПРЯМЫЕ_СЛОВА))
    звонки = stub_classify(
        monkeypatch, suggestion(candidate(ОДНОЗОННЫЙ, "D1", "hot_kitchen", "Нагар"))
    )
    bot, _ = make_bot()
    dp = build_dispatcher(SETTINGS)

    await feed(dp, bot, photo_message("frame-1", caption=НЕПРЯМЫЕ_СЛОВА, message_id=601))
    await feed(dp, bot, callback_query("rec:pick:0"))

    состояние = get_state(CHAT_ID)
    assert состояние is not None and состояние.findings, (
        "материал не разобрался из-за строки карты, ведущей в никуда"
    )
    assert звонки, "синоним снятого пункта не пустил материал к модели"


async def test_многозонный_синоним_спрашивает_зону_кнопками(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Пункт назвала карта, место — нет: зона не подставляется, а спрашивается.

    Кнопками идут ТОЛЬКО зоны, допустимые методикой для этого пункта (T266):
    методика не даст записать чужую пару, и предлагать её нельзя. После
    нажатия текстом записи становятся слова аудитора, а не формулировка карты.
    """
    начата()
    _lookup_returns(monkeypatch, _alias(МНОГОЗОННЫЙ, НЕПРЯМЫЕ_СЛОВА))
    # Пишущая сторона тут ничем не проверяется: `_save` неизбежно зовёт
    # `remember_phrase` вторым разом (слой ответил бы `ALREADY_KNOWN`), и это
    # ожидаемо, а не предмет этого теста.
    _remember_records(monkeypatch)
    звонки = stub_classify(monkeypatch, suggestion())
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await feed(dp, bot, photo_message("frame-1", caption=НЕПРЯМЫЕ_СЛОВА, message_id=601))

    assert session.last_text == t("record.ask_zone_for_item", "ru", code=МНОГОЗОННЫЙ)
    своих = [
        f"{ZONE_FOR_ITEM_PREFIX}{zone}" for zone in allowed_zones(МНОГОЗОННЫЙ, chat_id=CHAT_ID)
    ]
    # Все зоны, зоны пункта — первыми (D206): место находки выбирает человек.
    assert session.keyboard_data()[: len(своих)] == своих, "зоны пункта не стоят первыми"
    assert звонки == [], "модель позвана раньше, чем аудитор назвал зону"

    await feed(dp, bot, callback_query(f"{ZONE_FOR_ITEM_PREFIX}hot_kitchen"))

    состояние = get_state(CHAT_ID)
    assert состояние is not None and состояние.findings, "запись не появилась после выбора зоны"
    запись = состояние.findings[0]
    assert (запись.code, запись.zone) == (МНОГОЗОННЫЙ, "hot_kitchen")
    assert запись.text == НЕПРЯМЫЕ_СЛОВА, "в отчёт ушли не слова аудитора"


async def test_многоклассовый_синоним_не_выбирает_класс_сам(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """У пункта несколько классов — синоним смысла не имеет: класс не выбран.

    Синоним хранит только код пункта, не класс (`Learned` не знает уровня), а
    выбирать класс за аудитора нельзя. Материал уходит модели, как будто
    карта промолчала.
    """
    начата()
    _lookup_returns(monkeypatch, _alias(МНОГОКЛАССОВЫЙ, НЕПРЯМЫЕ_СЛОВА))
    звонки = stub_classify(
        monkeypatch, suggestion(candidate(МНОГОКЛАССОВЫЙ, "D1", "hot_kitchen", "Заготовка"))
    )
    bot, _ = make_bot()
    dp = build_dispatcher(SETTINGS)

    await feed(dp, bot, photo_message("frame-1", caption=НЕПРЯМЫЕ_СЛОВА, message_id=601))
    await feed(dp, bot, callback_query("rec:pick:0"))

    состояние = get_state(CHAT_ID)
    assert состояние is not None and состояние.findings, (
        "материал не разобрался, хотя у пункта несколько классов"
    )
    assert звонки, "синоним пункта с несколькими классами применился сам, без модели"


async def test_карта_ключуется_языком_речи_а_не_интерфейса(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ключ карты — язык РЕЧИ аудитора, а не интерфейса и не отчёта (T285).

    Проверка начата с русским интерфейсом и английской речью аудитора: спутай
    их — и карта, накопленная на одном языке, молча перестанет отвечать на
    другом.
    """
    start_inspection(
        CHAT_ID,
        "Белград 2",
        "planned",
        "ru",
        ui_lang="ru",
        speech_lang="en",
        date="2026-08-21",
        auditor="Гарро",
    )
    _lookup_returns(monkeypatch, None)
    записано = _remember_records(monkeypatch)
    stub_classify(monkeypatch, suggestion(candidate(ОДНОЗОННЫЙ, "D1", "hot_kitchen", "Нагар")))
    bot, _ = make_bot()
    dp = build_dispatcher(SETTINGS)

    await feed(dp, bot, photo_message("frame-1", caption=НЕПРЯМЫЕ_СЛОВА, message_id=601))
    await feed(dp, bot, callback_query("rec:pick:0"))

    assert записано, "непрямое совпадение не сложилось синонимом"
    assert записано[-1][2] == "en", "remember_phrase получил не язык речи аудитора"


async def test_разбор_моделью_работает_под_записью_синонима(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Запись поставил синоним без подтверждения — «Разобрать моделью» жива.

    Починить неверный ПУНКТ такой записи можно только этой кнопкой: правка в
    чате меняет зону, класс и формулировку, но не код, а те же слова снова
    подняли бы тот же синоним.
    """
    начата()
    _lookup_returns(monkeypatch, _alias(ОДНОЗОННЫЙ, НЕПРЯМЫЕ_СЛОВА))
    звонки = stub_classify(
        monkeypatch, suggestion(candidate(ОДНОЗОННЫЙ, "D1", "hot_kitchen", "Другая формулировка"))
    )
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await feed(dp, bot, photo_message("frame-1", caption=НЕПРЯМЫЕ_СЛОВА, message_id=601))

    до = get_state(CHAT_ID)
    assert до is not None and до.findings, "накопленный синоним не поставил запись сам"
    assert звонки == [], "запись по накопленному синониму не обязана звать модель заранее"

    await feed(dp, bot, callback_query(MODEL_CALLBACK))

    assert звонки, "«Разобрать моделью» не позвала настоящий разбор"
    assert session.last_text != t("record.stale", "ru"), (
        "кнопка ответила «предложение устарело» вместо разбора"
    )
    после = get_state(CHAT_ID)
    assert после is not None and после.findings, "запись пропала после разбора моделью"
