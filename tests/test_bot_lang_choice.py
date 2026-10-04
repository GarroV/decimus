"""Аудитор сам выбирает язык бота (D303, #411).

Ядро — порядок выбора и хранение выбора: ошибка здесь тихая, бот просто
заговорит не на том языке. Порядок: выбор человека → язык начатой проверки →
язык стенда `BOT_UI_LANG` (владелец 04.10.2026: «Пока дефолт на русском, потом
переключим на инглиш» — умолчание из настройки стенда, а не из клиента Telegram).

Обвязка (команда и кнопки) проверяется прогоном через настоящий диспетчер.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from bot_harness import AUDITOR_ID, CHAT_ID, callback_query, feed, make_bot, text_message

from src.bot import lang_choice
from src.bot.app import build_dispatcher
from src.bot.config import UI_LANG_VAR, BotSettings
from src.bot.keyboards import UI_LANG_PREFIX
from src.bot.lang import chat_ui_lang, pick_ui_lang
from src.bot.lang_choice import RETRY_AFTER, LangChoices
from src.bot.texts import t
from src.domain import get_state

SETTINGS = BotSettings(token="unused-in-tests", allowed_ids=frozenset({AUDITOR_ID}), mode="polling")


# --- порядок выбора ------------------------------------------------------------


def test_выбор_человека_сильнее_проверки_и_стенда(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(UI_LANG_VAR, "ru")
    assert pick_ui_lang(chosen="en", started="ru") == "en"


def test_без_выбора_язык_начатой_проверки_сильнее_стенда(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(UI_LANG_VAR, "en")
    assert pick_ui_lang(chosen=None, started="ru") == "ru"


@pytest.mark.parametrize("stand", ["ru", "en"])
def test_без_выбора_и_проверки_язык_стенда(monkeypatch: pytest.MonkeyPatch, stand: str) -> None:
    """Умолчание — настройка стенда: переключение на английский — одна переменная."""
    monkeypatch.setenv(UI_LANG_VAR, stand)
    assert pick_ui_lang(chosen=None, started=None) == stand


def test_без_настройки_стенда_русский() -> None:
    assert pick_ui_lang(chosen=None, started=None) == "ru"


def test_язык_не_из_словаря_пропускается(monkeypatch: pytest.MonkeyPatch) -> None:
    """Выбор, сохранённый до того, как язык убрали из словаря, не роняет `t()`."""
    monkeypatch.setenv(UI_LANG_VAR, "en")
    assert pick_ui_lang(chosen="de", started="xx") == "en"


def test_испорченный_стенд_не_роняет_выбор_языка(monkeypatch: pytest.MonkeyPatch) -> None:
    """`lang.py` намеренно не падает на выборе языка (T126) — и с D303 тоже."""
    monkeypatch.setenv(UI_LANG_VAR, "klingon")
    assert pick_ui_lang(chosen=None, started=None) == "ru"


# --- хранение выбора -----------------------------------------------------------


class _Store:
    """База выборов в памяти: считает походы и умеет отказывать."""

    def __init__(self) -> None:
        self.rows: dict[int, str] = {}
        self.reads = 0
        self.broken = False

    def load(self, telegram_id: int) -> str | None:
        self.reads += 1
        if self.broken:
            raise OSError("база молчит")
        return self.rows.get(telegram_id)

    def save(self, telegram_id: int, lang: str) -> None:
        if self.broken:
            raise OSError("база молчит")
        self.rows[telegram_id] = lang


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> _Store:
    база = _Store()
    monkeypatch.setattr(lang_choice, "_load_from_db", база.load)
    monkeypatch.setattr(lang_choice, "_save_to_db", база.save)
    return база


def test_выбор_пишется_в_базу_и_читается_новым_процессом(store: _Store) -> None:
    """«Переживает перезапуск»: новый кэш (новый процесс) читает выбор из базы."""
    LangChoices().choose(AUDITOR_ID, "en")

    assert store.rows == {AUDITOR_ID: "en"}
    assert LangChoices().chosen(AUDITOR_ID) == "en"


def test_выбор_перезаписывается(store: _Store) -> None:
    выборы = LangChoices()
    выборы.choose(AUDITOR_ID, "en")
    выборы.choose(AUDITOR_ID, "ru")

    assert store.rows[AUDITOR_ID] == "ru"
    assert LangChoices().chosen(AUDITOR_ID) == "ru"


def test_база_спрашивается_один_раз_на_человека(store: _Store) -> None:
    выборы = LangChoices()
    for _ in range(5):
        assert выборы.chosen(AUDITOR_ID) is None
    assert store.reads == 1


def test_отказ_базы_при_чтении_не_роняет_и_не_долбит_базу(store: _Store) -> None:
    сейчас = [datetime(2026, 10, 4, tzinfo=UTC)]
    выборы = LangChoices(now=lambda: сейчас[0])
    store.broken = True

    assert выборы.chosen(AUDITOR_ID) is None
    assert выборы.chosen(AUDITOR_ID) is None
    assert store.reads == 1, "молчащую базу спрашивают на каждом сообщении"

    store.broken = False
    store.rows[AUDITOR_ID] = "en"
    сейчас[0] += RETRY_AFTER + timedelta(seconds=1)
    assert выборы.chosen(AUDITOR_ID) == "en", "после паузы база не спрошена снова"


def test_несохранённый_выбор_не_запоминается(store: _Store) -> None:
    """Сказать «запомнил» о выборе, который не переживёт перезапуск, нельзя."""
    выборы = LangChoices()
    store.broken = True

    with pytest.raises(OSError):
        выборы.choose(AUDITOR_ID, "en")

    store.broken = False
    assert выборы.chosen(AUDITOR_ID) is None


def test_вне_апдейта_выбор_не_спрашивается(store: _Store, domain_env: object) -> None:
    """Без человека в контексте — язык стенда, и в базу никто не ходит."""
    assert chat_ui_lang(CHAT_ID) == "ru"
    assert store.reads == 0


# --- команда и кнопки ------------------------------------------------------------


async def _choose(dp: object, bot: object, code: str) -> None:
    await feed(dp, bot, text_message("/lang"))
    await feed(dp, bot, callback_query(f"{UI_LANG_PREFIX}{code}"))


@pytest.mark.asyncio
async def test_команда_показывает_языки_на_них_самих(domain_env: object) -> None:
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await feed(dp, bot, text_message("/lang"))

    assert session.keyboard_texts() == ["Русский", "English"]
    assert session.last_text == t("lang.ask", "ru", current="Русский")


@pytest.mark.asyncio
async def test_нажатие_сохраняет_выбор_и_бот_переходит_на_него(
    domain_env: object, выборы_языка: dict[int, str]
) -> None:
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await _choose(dp, bot, "en")

    assert выборы_языка == {AUDITOR_ID: "en"}
    assert session.last_text == t("lang.chosen", "en")
    await feed(dp, bot, text_message("/start"))
    assert session.last_text == t("start.greeting", "en")


@pytest.mark.asyncio
async def test_выбор_переживает_перезапуск_бота(
    domain_env: object, выборы_языка: dict[int, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    bot, _ = make_bot()
    await _choose(build_dispatcher(SETTINGS), bot, "en")

    # Перезапуск: память процесса пуста, база (здесь — словарь фикстуры) та же.
    monkeypatch.setattr(lang_choice, "CHOICES", LangChoices())
    bot, session = make_bot()
    await feed(build_dispatcher(SETTINGS), bot, text_message("/start"))

    assert session.last_text == t("start.greeting", "en")


@pytest.mark.asyncio
async def test_выбор_одного_не_меняет_язык_другому(
    domain_env: object, выборы_языка: dict[int, str]
) -> None:
    """Выбор — за человеком, а не за ботом целиком."""
    другой = AUDITOR_ID + 1
    settings = BotSettings(
        token="unused-in-tests", allowed_ids=frozenset({AUDITOR_ID, другой}), mode="polling"
    )
    bot, session = make_bot()
    dp = build_dispatcher(settings)
    await _choose(dp, bot, "en")

    await feed(dp, bot, text_message("/start", user_id=другой, chat_id=другой))

    assert session.last_text == t("start.greeting", "ru")


@pytest.mark.asyncio
async def test_выбор_посреди_проверки_меняет_разговор_но_не_отчёт(
    domain_env: object, выборы_языка: dict[int, str]
) -> None:
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)
    await feed(dp, bot, text_message("/start"))
    await feed(dp, bot, callback_query("start:new"))
    await feed(dp, bot, text_message("Белград 2"))
    await feed(dp, bot, callback_query("start:kind:planned"))
    await feed(dp, bot, callback_query("start:lang:ru"))

    await _choose(dp, bot, "en")
    await feed(dp, bot, text_message("/start"))

    assert session.keyboard_texts() == [t("btn.resume_continue", "en"), t("btn.resume_new", "en")]
    проверка = get_state(CHAT_ID)
    assert проверка is not None
    assert (проверка.report_lang, проверка.speech_lang) == ("ru", "ru"), "выбор тронул отчёт"


@pytest.mark.asyncio
async def test_несохранённый_выбор_называется_и_язык_не_меняется(
    domain_env: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    def отказ(_tg: int, _lang: str) -> None:
        raise OSError("база молчит")

    monkeypatch.setattr(lang_choice, "_save_to_db", отказ)
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await _choose(dp, bot, "en")

    assert session.last_text == t("lang.save_failed", "ru")
    await feed(dp, bot, text_message("/start"))
    assert session.last_text == t("start.greeting", "ru")


@pytest.mark.asyncio
async def test_кнопка_языка_не_из_словаря_ничего_не_меняет(
    domain_env: object, выборы_языка: dict[int, str]
) -> None:
    bot, _ = make_bot()
    dp = build_dispatcher(SETTINGS)

    await feed(dp, bot, callback_query(f"{UI_LANG_PREFIX}de"))

    assert выборы_языка == {}


@pytest.mark.parametrize(
    "key", ["cmd.lang", "lang.self_name", "lang.ask", "lang.chosen", "lang.save_failed"]
)
@pytest.mark.parametrize("lang", ["ru", "en"])
def test_тексты_выбора_заведены_на_обоих_языках(key: str, lang: str) -> None:
    assert t(key, lang, current="x").strip()
