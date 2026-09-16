"""T124: зона берётся из слов комментария (задача #99), и другого источника речи нет.

Правило 6 `docs/03-recording-rules.md`: «Зону определяет человек или разбор его
комментария». Спека — «зона бралась из моих слов». D047 — зона из слов
комментария.

До задачи порядок был обратный: зона всегда бралась из заметок бота, то есть из
памяти о ПРОШЛОЙ записи, а слова текущего комментария на неё не влияли вовсе.
«В зале лужа» ложилось в горячий цех, а бот при этом писал «записал по вашим
словам» — вычет уезжал в чужую зону отчёта партнёру.

**Памяти о прошлой зоне с T264 не существует вовсе** (решение D118): D048
отводило ей роль догадки, и живой прогон 07.09.2026 показал, чего эта догадка
стоит — пункт про печь уехал в холодный цех. Источников осталось три: слова
аудитора, словарь карты кадров, кнопка. Поэтому здесь проверяется не «слова
сильнее памяти», а то, что слова доходят до записи и что на месте снятой памяти
не завелось молчаливой подстановки.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from bot_harness import (
    AUDITOR_ID,
    CHAT_ID,
    candidate,
    feed,
    make_bot,
    photo_message,
    stub_classify,
    suggestion,
)

from src.bot import zones
from src.bot.app import build_dispatcher
from src.bot.config import BotSettings
from src.bot.texts import t
from src.domain import get_state, start_inspection

SETTINGS = BotSettings(token="unused-in-tests", allowed_ids=frozenset({AUDITOR_ID}), mode="polling")


def начата() -> None:
    start_inspection(CHAT_ID, "Белград 2", "planned", "ru", date="2026-08-21", auditor="Гарро")


# --- разбор слов сам по себе ------------------------------------------------


@pytest.mark.parametrize(
    ("слова", "зона"),
    [
        ("в зале разлито и скользко", "dining"),
        ("Полы в зале не убраны с утра", "dining"),
        ("касса грязная", "dining"),
        ("щель между оборудованием и стеной за кассовой стойкой", "dining"),
        ("пол грязный, тепловой участок", "hot_kitchen"),
        ("загрязнение рабочего стола, холодный участок", "cold_kitchen"),
        ("тестомес не накрыт", "dough"),
        ("мусор в углу, мучной участок", "dough"),
        # Дословный пример владельца из ответа 03.09.2026: «мучной цех, на
        # дрожжах нет маркировки». Приёмка поймала, что разбор его не узнавал.
        ("мучной цех, на дрожжах нет маркировки", "dough"),
        ("налёт, посудный участок", "dishwashing"),
        ("dish station is not cleaned", "dishwashing"),
        ("на стеллаже хранения коробки на полу", "dry_storage"),
        ("в низкотемпературном шкафу наледь", "freezer"),
        ("в морозилке наледь", "freezer"),
        ("в среднетемпературном шкафу коробки на полу", "fridge"),
        ("пол в бытовом блоке в пыли", "staff"),
        ("utility block is a mess", "staff"),
        # Составное имя зоны («Бытовой блок / раздевалка») — два имени одного
        # места, и произносят их по отдельности. Ветку разрезания имени
        # (`_SPLIT` в `src/bot/zones.py`) стережёт именно эта пара случаев:
        # без них зона с косой чертой в названии перестала бы узнаваться по
        # второму имени молча.
        ("в раздевалке не убрано", "staff"),
        ("the changing room is a mess", "staff"),
        ("внешний контур в подтёках", "facade"),
        ("на внешнем контуре здания мусор", "facade"),
        ("the low-temperature cabinet door does not close", "freezer"),
        ("dirt on the floor in the heat station", "hot_kitchen"),
    ],
)
def test_зона_читается_из_слов_аудитора(domain_env: Path, слова: str, зона: str) -> None:
    assert zones.zone_from_words(слова, chat_id=CHAT_ID) == зона


@pytest.mark.parametrize(
    "слова",
    [
        "",
        "нагар на подине печи",
        "просрочка чизкейк",
        "мусор в углу",
    ],
)
def test_слова_без_зоны_зоны_не_дают(domain_env: Path, слова: str) -> None:
    """Молчание лучше догадки: зону в этом случае подставит память (D048)."""
    assert zones.zone_from_words(слова, chat_id=CHAT_ID) is None


def test_две_названные_зоны_не_выбираются_за_аудитора(domain_env: Path) -> None:
    """Названы обе — выбирать между ними системе нечем, и она не выбирает."""
    слова = "тепловой участок, холодный участок: открытый продукт носят между ними"
    assert zones.zone_from_words(слова, chat_id=CHAT_ID) is None


def test_длинное_название_зоны_сильнее_короткого(domain_env: Path) -> None:
    """Зона, названная одним словом, слабее зоны, названной двумя.

    Разбор идёт по названным целиком строкам, и более длинная выигрывает:
    иначе оборудование или обстановка с похожим названием утащили бы запись в
    чужую зону. Здесь «зал» задевает гостевой зал одной основой, а тепловой
    участок назван двумя, — выигрывает участок.
    """
    assert zones.zone_from_words("зал, тепловой участок", chat_id=CHAT_ID) == "hot_kitchen"
    assert (
        zones.zone_from_words("течь под мойкой, тепловой участок", chat_id=CHAT_ID) == "hot_kitchen"
    )


def test_зоны_берутся_из_методики_а_не_из_списка_в_коде(domain_env: Path) -> None:
    """Код зоны, которого нет в методике, разбор вернуть не может."""
    from src.domain import list_zones

    известные = {z.code for z in list_zones()}
    for слова in ("в зале лужа", "посудный участок в налёте", "внешний контур в подтёках"):
        assert zones.zone_from_words(слова, chat_id=CHAT_ID) in известные


# --- разговор: слова сильнее памяти -----------------------------------------


@pytest.mark.asyncio
async def test_запись_ложится_в_названную_словами_зону(
    domain_env: Path,
) -> None:
    """Тот самый случай из сверки: «в зале» — и запись ложится в зал.

    Слово аудитора о месте доходит до самой записи, а не теряется по дороге в
    быстром пути: иначе вычет уезжает в чужую зону отчёта партнёру, а бот при
    этом пишет «по вашим словам».
    """
    начата()
    bot, _ = make_bot()

    await feed(
        build_dispatcher(SETTINGS),
        bot,
        photo_message("frame-1", caption="в зале урна переполнена"),
    )

    проверка = get_state(CHAT_ID)
    assert проверка is not None and проверка.findings, "запись не появилась"
    assert проверка.findings[-1].zone == "dining", "слово аудитора о месте до записи не дошло"


@pytest.mark.asyncio
async def test_зона_из_слов_уходит_подсказкой_и_в_модель(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Разбор моделью получает ту же зону: она подсказка, а не украшение."""
    начата()
    звали = stub_classify(monkeypatch, suggestion(candidate("SFT03", "D1", "dining")))
    bot, _ = make_bot()

    await feed(
        build_dispatcher(SETTINGS),
        bot,
        photo_message("frame-1", caption="сотрудник без перчаток в зале"),
    )

    assert звали, "разбор не состоялся — проверять подсказку зоны не на чем"
    _note, _photo, подсказка, _lang = звали[-1]
    assert подсказка == "dining", "названная аудитором зона до модели не доехала"


@pytest.mark.asyncio
async def test_прошлая_зона_подсказкой_модели_не_становится(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T264 отменяет D048: не вывелась — подсказки нет, а не «возьмём прошлую».

    Тест развёрнут намеренно, а не удалён. Подстановка прошлой зоны и есть
    дефект #218, и запирать снятое поведение обязан тест: без него оно вернётся
    первой же правкой, которой «не хватает подсказки».

    «Мусор в углу» — слова без места и без строки карты кадров: зону взять
    неоткуда ни одному из трёх источников. Модель на это отвечает «места не
    знаю» (`UNKNOWN`), и ответ доживает до вопроса человеку, а не подменяется.
    """
    начата()
    звали = stub_classify(monkeypatch, suggestion(candidate("CLN05", "D1", "hot_kitchen")))
    bot, _ = make_bot()

    await feed(build_dispatcher(SETTINGS), bot, photo_message("frame-1", caption="мусор в углу"))

    assert звали, "разбор не состоялся — проверять подсказку зоны не на чем"
    _note, _photo, подсказка, _lang = звали[-1]
    assert подсказка is None, "на месте снятой памяти завелась молчаливая подстановка зоны"


@pytest.mark.asyncio
async def test_запись_по_словам_называет_источник_зоны_если_её_не_называли(
    domain_env: Path,
) -> None:
    """Быстрый путь пишет без подтверждения — значит, не имеет права умалчивать.

    Зону здесь дал СЛОВАРЬ карты кадров (T263): аудитор назвал объект, а не
    место. Сообщение при этом говорит «по вашим словам» — про зону это неправда,
    и именно на ней промах остаётся незамеченным, потому что подтверждать запись
    никто не будет. Оговорка `record.fixed_zone_from_cues` и закрывает разрыв.
    """
    начата()
    bot, session = make_bot()

    await feed(build_dispatcher(SETTINGS), bot, photo_message("frame-1", caption="печь в нагаре"))

    запись = get_state(CHAT_ID)
    assert запись is not None and запись.findings, "быстрый путь не сработал — проверять нечего"
    assert запись.findings[-1].zone == "hot_kitchen", "словарь карты кадров зону не поставил"
    assert t("record.fixed_zone_from_cues", "ru").strip() in session.last_text, (
        "зона из карты кадров выдана за слова аудитора"
    )


@pytest.mark.asyncio
async def test_названная_словами_зона_догадкой_не_называется(
    domain_env: Path,
) -> None:
    """Зону произнесли — оговорки в записи нет, она была бы шумом."""
    начата()
    bot, session = make_bot()

    await feed(
        build_dispatcher(SETTINGS),
        bot,
        photo_message("frame-1", caption="печь в нагаре, тепловой участок"),
    )

    запись = get_state(CHAT_ID)
    assert запись is not None and запись.findings
    assert запись.findings[-1].zone == "hot_kitchen"
    assert t("record.fixed_zone_from_cues", "ru").strip() not in session.last_text
