"""Мастер начала проверки через настоящий диспетчер (T050, T051, T052, T063).

События идут тем же путём, что в бою: `Update` → `Dispatcher.feed_update` →
мидлварь доступа → фильтры → хендлер. Проверяется не текст сообщений, а
поведение: что бот спросил, что положил в состояние проверки и чего не сделал.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from bot_harness import (
    AUDITOR_ID,
    CHAT_ID,
    STRANGER_ID,
    callback_query,
    feed,
    make_bot,
    text_message,
)

from src.bot.access import BindingCache
from src.bot.app import build_dispatcher
from src.bot.config import BotSettings
from src.bot.keyboards import (
    KIND_TITLES,
    NEW_INSPECTION_CALLBACK,
    RESUME_CONTINUE_CALLBACK,
    RESUME_NEW_CALLBACK,
    UNIT_NEW_PREFIX,
    UNIT_NEW_YES,
)
from src.bot.unit_pick import UnitMatch
from src.db.bot_links import Binding, Standing
from src.domain import get_state, start_inspection

pytestmark = pytest.mark.asyncio


def settings(names: dict[int, str] | None = None) -> BotSettings:
    return BotSettings(
        token="unused-in-tests",
        allowed_ids=frozenset({AUDITOR_ID}),
        mode="polling",
        auditor_names=names or {},
    )


async def walk_through_wizard(unit: str = "Белград 2") -> tuple[object, object]:
    """Пройти мастер целиком: /start → «Новая проверка» → название → вид → язык."""
    bot, session = make_bot()
    dp = build_dispatcher(settings())
    await feed(dp, bot, text_message("/start"))
    await feed(dp, bot, callback_query(NEW_INSPECTION_CALLBACK))
    await feed(dp, bot, text_message(unit))
    await feed(dp, bot, callback_query("start:kind:planned"))
    await feed(dp, bot, callback_query("start:lang:ru"))
    return bot, session


async def test_stranger_gets_no_answer_at_all(domain_env: object) -> None:
    """Посторонний не должен получить даже отказа: это подтверждение, что бот есть."""
    bot, session = make_bot()
    dp = build_dispatcher(settings())

    await feed(dp, bot, text_message("/start", user_id=STRANGER_ID))

    assert session.calls == []


async def test_start_offers_new_inspection_button(domain_env: object) -> None:
    bot, session = make_bot()
    dp = build_dispatcher(settings())

    await feed(dp, bot, text_message("/start"))

    assert NEW_INSPECTION_CALLBACK in session.keyboard_data()


async def test_wizard_asks_unit_then_kind_then_language(domain_env: object) -> None:
    bot, session = make_bot()
    dp = build_dispatcher(settings())

    await feed(dp, bot, text_message("/start"))
    await feed(dp, bot, callback_query(NEW_INSPECTION_CALLBACK))
    assert "пиццерии" in session.last_text.lower()

    await feed(dp, bot, text_message("Белград 2"))
    assert set(session.keyboard_data()) == {f"start:kind:{code}" for code in KIND_TITLES}

    await feed(dp, bot, callback_query("start:kind:planned"))
    assert session.keyboard_data() == ["start:lang:ru", "start:lang:en"]


async def test_wizard_creates_inspection_with_typed_unit(domain_env: object) -> None:
    """Пиццерия вводится текстом (D051), а пишется городом по-английски и номером (D233)."""
    await walk_through_wizard(unit="Белград 2")

    inspection = get_state(CHAT_ID)
    assert inspection is not None
    assert inspection.unit == "Belgrade-2"  # D233: город по-английски и номер
    # Вид проверки записан КОДОМ (T152): слово живёт только в шапке для
    # движка и на кнопке мастера, а сама проверка связывается кодом.
    assert inspection.kind == "planned"
    assert inspection.report_lang == "ru"


async def test_auditor_comes_from_telegram_id_and_is_never_asked(domain_env: object) -> None:
    """T063: имя проверяющего подставляется, руками не вводится."""
    bot, session = make_bot()
    dp = build_dispatcher(settings({AUDITOR_ID: "Владимир Гарро"}))

    await feed(dp, bot, text_message("/start"))
    await feed(dp, bot, callback_query(NEW_INSPECTION_CALLBACK))
    await feed(dp, bot, text_message("Белград 2"))
    await feed(dp, bot, callback_query("start:kind:planned"))
    await feed(dp, bot, callback_query("start:lang:ru"))

    inspection = get_state(CHAT_ID)
    assert inspection is not None
    assert inspection.auditor == "Владимир Гарро"
    assert not any("проверяющ" in text.lower() and "?" in text for text in session.texts[:-1])


async def test_date_is_today_and_not_asked(domain_env: object) -> None:
    await walk_through_wizard()

    inspection = get_state(CHAT_ID)
    assert inspection is not None
    assert inspection.date == date.today().isoformat()


async def test_empty_unit_is_asked_again_not_accepted(domain_env: object) -> None:
    bot, session = make_bot()
    dp = build_dispatcher(settings())

    await feed(dp, bot, text_message("/start"))
    await feed(dp, bot, callback_query(NEW_INSPECTION_CALLBACK))
    await feed(dp, bot, text_message("   "))

    assert "пуст" in session.last_text.lower()
    await feed(dp, bot, text_message("Белград 2"))
    assert set(session.keyboard_data()) == {f"start:kind:{code}" for code in KIND_TITLES}


async def test_unfinished_inspection_is_shown_not_overwritten(domain_env: object) -> None:
    """T052: чужую незавершённую проверку не затирать молча."""
    start_inspection(CHAT_ID, "Белград 1", "planned", "ru", auditor="Пётр Петров")

    bot, session = make_bot()
    dp = build_dispatcher(settings())
    await feed(dp, bot, text_message("/start"))

    assert "Белград 1" in session.last_text
    assert "Пётр Петров" in session.last_text
    assert date.today().isoformat() in session.last_text
    assert set(session.keyboard_data()) == {RESUME_CONTINUE_CALLBACK, RESUME_NEW_CALLBACK}

    still_there = get_state(CHAT_ID)
    assert still_there is not None and still_there.unit == "Белград 1"


async def test_new_inspection_button_also_warns_about_unfinished_one(domain_env: object) -> None:
    start_inspection(CHAT_ID, "Белград 1", "planned", "ru")

    bot, session = make_bot()
    dp = build_dispatcher(settings())
    await feed(dp, bot, callback_query(NEW_INSPECTION_CALLBACK))

    assert set(session.keyboard_data()) == {RESUME_CONTINUE_CALLBACK, RESUME_NEW_CALLBACK}
    assert get_state(CHAT_ID) is not None


async def test_continue_keeps_the_inspection(domain_env: object) -> None:
    start_inspection(CHAT_ID, "Белград 1", "planned", "ru")

    bot, session = make_bot()
    dp = build_dispatcher(settings())
    await feed(dp, bot, text_message("/start"))
    await feed(dp, bot, callback_query(RESUME_CONTINUE_CALLBACK))

    assert "Белград 1" in session.last_text
    kept = get_state(CHAT_ID)
    assert kept is not None and kept.unit == "Белград 1"


async def test_start_new_asks_unit_and_replaces_only_after_full_wizard(
    domain_env: object,
) -> None:
    start_inspection(CHAT_ID, "Белград 1", "planned", "ru")

    bot, session = make_bot()
    dp = build_dispatcher(settings())
    await feed(dp, bot, text_message("/start"))
    await feed(dp, bot, callback_query(RESUME_NEW_CALLBACK))

    assert "пиццерии" in session.last_text.lower()
    midway = get_state(CHAT_ID)
    assert midway is not None and midway.unit == "Белград 1"

    await feed(dp, bot, text_message("Белград 3"))
    await feed(dp, bot, callback_query("start:kind:repeat"))
    await feed(dp, bot, callback_query("start:lang:en"))

    replaced = get_state(CHAT_ID)
    assert replaced is not None
    assert replaced.unit == "Belgrade-3"
    assert replaced.report_lang == "en"


# --- пиццерия: город по-английски и номер, новую заводит УК (D233) -----------


def _справочник(monkeypatch: pytest.MonkeyPatch, match: object) -> list[dict[str, object]]:
    from src.bot.routers import start as start_router

    заведено: list[dict[str, object]] = []

    def завести(name: str, **kw: object) -> str:
        заведено.append({"name": name, **kw})
        return "u-new"

    monkeypatch.setattr(start_router, "match_unit", lambda _typed, **_kw: match)
    monkeypatch.setattr(start_router, "upsert_unit", завести)
    return заведено


async def _до_названия(
    unit: str, bindings: BindingCache | None = None
) -> tuple[object, object, object]:
    bot, session = make_bot()
    dp = build_dispatcher(settings(), bindings=bindings)
    await feed(dp, bot, text_message("/start"))
    await feed(dp, bot, callback_query(NEW_INSPECTION_CALLBACK))
    await feed(dp, bot, text_message(unit))
    return bot, session, dp


async def _до_конца(bot: object, dp: object) -> None:
    await feed(dp, bot, callback_query("start:kind:planned"))
    await feed(dp, bot, callback_query("start:lang:ru"))


async def test_знакомая_пиццерия_на_любом_языке_берётся_из_справочника(
    domain_env: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    заведено = _справочник(monkeypatch, UnitMatch(name="Yerevan-2", suggestions=(), checked=True))

    # Act
    bot, _session, dp = await _до_названия("ереван 2")
    await _до_конца(bot, dp)

    # Assert
    inspection = get_state(CHAT_ID)
    assert inspection is not None and inspection.unit == "Yerevan-2"
    assert заведено == []


async def test_новую_пиццерию_уk_заводит_в_справочник_страны(
    domain_env: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — Подгорицы-2 в справочнике нет.
    заведено = _справочник(monkeypatch, UnitMatch(name=None, suggestions=(), checked=True))

    # Act
    bot, session, dp = await _до_названия("ПОдгорица-2")
    вопрос, кнопки = session.last_text, session.keyboard_data()
    await feed(dp, bot, callback_query(f"{UNIT_NEW_PREFIX}{UNIT_NEW_YES}"))
    await _до_конца(bot, dp)

    # Assert
    assert "Новая пиццерия?" in вопрос and "Podgorica-2" in вопрос and "Черногория" in вопрос
    assert кнопки == [f"{UNIT_NEW_PREFIX}{UNIT_NEW_YES}", f"{UNIT_NEW_PREFIX}no"]
    assert заведено == [
        {
            "name": "Podgorica-2",
            "aliases": ("ПОдгорица-2",),
            "country": "ME",
            "city": "podgorica",
            "tenant": "HQ",
        }
    ]
    inspection = get_state(CHAT_ID)
    assert inspection is not None and inspection.unit == "Podgorica-2"


async def test_нет_значит_ввести_заново_и_ничего_не_заводится(
    domain_env: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    заведено = _справочник(monkeypatch, UnitMatch(name=None, suggestions=(), checked=True))
    bot, session, dp = await _до_названия("Podgorica-2")
    await feed(dp, bot, callback_query(f"{UNIT_NEW_PREFIX}no"))
    assert заведено == []
    assert get_state(CHAT_ID) is None
    assert "пиццерии" in session.last_text.lower()


async def test_без_номера_бот_просит_город_и_номер(
    domain_env: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    заведено = _справочник(monkeypatch, UnitMatch(name=None, suggestions=(), checked=True))
    _bot, session, _dp = await _до_названия("Земун")
    assert "городом и номером" in session.last_text
    assert заведено == [] and get_state(CHAT_ID) is None


async def test_партнёр_новую_пиццерию_не_заводит(
    domain_env: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — бот проверяющего привязан к учётке партнёра (D286).
    заведено = _справочник(monkeypatch, UnitMatch(name=None, suggestions=(), checked=True))
    партнёр = BindingCache(
        standing=lambda tg: Standing.live(Binding(tg, "u", "me-auditor", "ME", datetime.now(UTC)))
    )

    # Act
    _bot, session, _dp = await _до_названия("Podgorica-2", партнёр)

    # Assert — вопроса «Новая пиццерия?» нет, точка не заведена, проверки нет.
    assert "только управляющая компания" in session.last_text
    assert f"{UNIT_NEW_PREFIX}{UNIT_NEW_YES}" not in session.keyboard_data()
    assert заведено == [] and get_state(CHAT_ID) is None
