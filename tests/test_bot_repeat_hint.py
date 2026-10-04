"""D255 (уточняет D191, #359): повтор находит система, решает проверяющий.

Пункт уже был нарушением в предыдущей проверке этой пиццерии — бот сам
спрашивает, считать ли запись повтором ×2, и ждёт ответа. «Да» (кнопкой или
словами в ответ на вопрос) ставит пометку повтора тем же путём, что и старая
кнопка (`audit.py edit --repeat`), и вычет удваивается; «нет» — не ставит.
Без ответа запись повтором не считается.

Что здесь стережётся, кроме самого вопроса: наблюдение системы само ничего не
меняет в записи. Система, решившая за человека, удвоила бы вычет там, где
нарушение другое, — тот же код мог относиться к другому объекту, а
исправленное и снова сломавшееся не равно не исправленному вовсе.
"""

from __future__ import annotations

import logging
from datetime import date

import pytest
from bot_harness import (
    AUDITOR_ID,
    CHAT_ID,
    bot_message,
    candidate,
    feed,
    make_bot,
    photo_message,
    stub_classify,
    suggestion,
    text_message,
)
from bot_harness import (
    callback_query as callback,
)

from src import domain
from src.bot import repeats
from src.bot.app import build_dispatcher
from src.bot.config import BotSettings
from src.bot.keyboards import REPEAT_NO_PREFIX, REPEAT_YES_PREFIX
from src.bot.texts import t
from src.db.errors import DbError
from src.db.models import PreviousInspection
from src.domain import get_item, get_state, start_inspection
from src.domain.models import Inspection

pytestmark = [pytest.mark.asyncio]

SETTINGS = BotSettings(token="unused-in-tests", allowed_ids=frozenset({AUDITOR_ID}), mode="polling")

ПРОШЛЫЙ_РАЗ = date(2026, 9, 1)


def текст_вопроса() -> str:
    """Вопрос о повторе для записи CLN05: пункт назван словами, а не номером."""
    item = get_item("CLN05", chat_id=CHAT_ID).question("ru")
    return t("record.repeat_ask", "ru", item=item, date="01.09.2026")


def проверка(*, unit: str = "Белград 2", tenant: str = "dodo") -> Inspection:
    return Inspection(
        chat_id=CHAT_ID,
        unit=unit,
        kind="planned",
        date="2026-09-24",
        report_lang="en",
        ui_lang="ru",
        speech_lang="ru",
        checklist_version="v1",
        tenant=tenant,
    )


def подменить(monkeypatch: pytest.MonkeyPatch, ответ: object) -> list[dict[str, str]]:
    """Подменить поход в базу за прошлой проверкой. `ответ` — коды, None или отказ."""
    звали: list[dict[str, str]] = []

    def вместо(*, tenant: str, unit: str) -> PreviousInspection | None:
        звали.append({"tenant": tenant, "unit": unit})
        if isinstance(ответ, Exception):
            raise ответ
        if ответ is None:
            return None
        assert isinstance(ответ, set)
        return PreviousInspection(date=ПРОШЛЫЙ_РАЗ, codes=frozenset(ответ))

    monkeypatch.setattr(repeats.queries, "previous_inspection", вместо)
    return звали


def запись() -> domain.Finding:
    состояние = get_state(CHAT_ID)
    assert состояние is not None
    найдена = состояние.finding(1)
    assert найдена is not None
    return найдена


def номер_сообщения(session: object, текст: str) -> int:
    """Номер сообщения бота, текст которого содержит `текст`."""
    отправленные = [
        c
        for c in session.calls  # type: ignore[attr-defined]
        if type(c).__name__ in {"SendMessage", "SendPhoto", "SendDocument", "EditMessageText"}
    ]
    for вызов, номер in zip(отправленные, session.sent_ids, strict=True):  # type: ignore[attr-defined]
        if текст in str(getattr(вызов, "text", "")):
            return int(номер)
    raise AssertionError(f"бот не отправлял сообщения с «{текст}»")


# --- наблюдение само по себе ------------------------------------------------


def test_пункт_из_прошлой_проверки_узнаётся_с_датой(monkeypatch: pytest.MonkeyPatch) -> None:
    звали = подменить(monkeypatch, {"CLN05", "PRD01"})

    assert repeats.seen_before(проверка(), code="CLN05", level="D1") == ПРОШЛЫЙ_РАЗ
    assert звали == [{"tenant": "dodo", "unit": "Белград 2"}]


def test_новый_пункт_вопроса_не_поднимает(monkeypatch: pytest.MonkeyPatch) -> None:
    подменить(monkeypatch, {"PRD01"})

    assert repeats.seen_before(проверка(), code="CLN05", level="D1") is None


def test_без_прошлых_проверок_спрашивать_не_о_чем(monkeypatch: pytest.MonkeyPatch) -> None:
    подменить(monkeypatch, None)

    assert repeats.seen_before(проверка(), code="CLN05", level="D1") is None


@pytest.mark.parametrize("класс", ["D3", "D0"])
def test_класс_без_ставки_не_спрашивает_базу_вовсе(
    monkeypatch: pytest.MonkeyPatch, класс: str
) -> None:
    """D3 сжигает долю зоны целиком, у D0 вычета нет — удваивать нечего (D191)."""
    звали = подменить(monkeypatch, {"CLN05"})

    assert repeats.seen_before(проверка(), code="CLN05", level=класс) is None
    assert звали == [], "за вопросом, который нельзя задать, в базу не ходят"


def test_без_проверки_спрашивать_нечем(monkeypatch: pytest.MonkeyPatch) -> None:
    звали = подменить(monkeypatch, {"CLN05"})

    assert repeats.seen_before(None, code="CLN05", level="D1") is None
    assert звали == []


def test_безымянная_точка_в_базу_не_ходит(monkeypatch: pytest.MonkeyPatch) -> None:
    """Пустое название вернуло бы отказ — поход за ним бессмыслен."""
    звали = подменить(monkeypatch, {"CLN05"})

    assert repeats.seen_before(проверка(unit="  "), code="CLN05", level="D1") is None
    assert repeats.seen_before(проверка(tenant=""), code="CLN05", level="D1") is None
    assert звали == []


def test_молчащая_база_снимает_вопрос_и_говорит_об_этом(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Обход не зависит от справочного запроса, но пропажа вопроса не молчит."""
    подменить(monkeypatch, DbError("база недоступна"))

    with caplog.at_level(logging.WARNING):
        assert repeats.seen_before(проверка(), code="CLN05", level="D1") is None

    assert any("предыдущая проверка" in r.getMessage() for r in caplog.records)


# --- вопрос на обходе -------------------------------------------------------


async def зафиксировать(
    dp: object,
    bot: object,
    monkeypatch: pytest.MonkeyPatch,
    *,
    code: str = "CLN05",
    level: str = "D1",
) -> None:
    stub_classify(monkeypatch, suggestion(candidate(code, level, "hot_kitchen", "Печь в нагаре")))
    # Формулировка намеренно НЕ совпадает со списком нарушений напрямую: прямое
    # совпадение фиксирует запись сразу, и кнопка кандидата тогда лишняя.
    await feed(
        dp,
        bot,  # type: ignore[arg-type]
        photo_message("frame-1", caption="печь, посмотри что тут, тепловой участок"),
    )
    await feed(dp, bot, callback("rec:pick:0"))  # type: ignore[arg-type]


async def начать(
    monkeypatch: pytest.MonkeyPatch, прошлые: set[str]
) -> tuple[object, object, object]:
    start_inspection(CHAT_ID, "Белград 2", "planned", "ru")
    подменить(monkeypatch, прошлые)
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)
    return dp, bot, session


async def test_пункт_прошлой_проверки_получает_вопрос_с_датой_и_да_нет(
    domain_env: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    dp, bot, session = await начать(monkeypatch, {"CLN05"})

    await зафиксировать(dp, bot, monkeypatch)

    assert session.last_text == текст_вопроса()  # type: ignore[attr-defined]
    assert "01.09.2026" in текст_вопроса()
    assert session.keyboard_data() == [  # type: ignore[attr-defined]
        f"{REPEAT_YES_PREFIX}1:CLN05",
        f"{REPEAT_NO_PREFIX}1:CLN05",
    ]


async def test_вопрос_идёт_после_записи_и_сам_ничего_не_меняет(
    domain_env: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Без ответа проверяющего запись повтором не считается (D255)."""
    dp, bot, session = await начать(monkeypatch, {"CLN05"})

    await зафиксировать(dp, bot, monkeypatch)

    блок = next(текст for текст in session.texts if "CLN05" in текст)  # type: ignore[attr-defined]
    assert session.texts.index(блок) < session.texts.index(текст_вопроса())  # type: ignore[attr-defined]
    assert запись().repeat is False


async def test_новый_пункт_вопроса_не_получает(
    domain_env: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    dp, bot, session = await начать(monkeypatch, {"PRD01"})

    await зафиксировать(dp, bot, monkeypatch)

    assert текст_вопроса() not in session.texts  # type: ignore[attr-defined]


async def test_d3_вопроса_не_получает(domain_env: object, monkeypatch: pytest.MonkeyPatch) -> None:
    """D3 повтором не удваивается — спрашивать о ×2 нечего."""
    dp, bot, session = await начать(monkeypatch, {"PRD04"})

    await зафиксировать(dp, bot, monkeypatch, code="PRD04", level="D3")

    assert запись().level == "D3"
    assert not any("повтором" in текст for текст in session.texts)  # type: ignore[attr-defined]


async def test_да_кнопкой_ставит_повтор_и_удваивает_вычет(
    domain_env: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    dp, bot, session = await начать(monkeypatch, {"CLN05"})
    await зафиксировать(dp, bot, monkeypatch)
    без_повтора = domain.score(CHAT_ID)

    await feed(dp, bot, callback(f"{REPEAT_YES_PREFIX}1:CLN05"))  # type: ignore[arg-type]

    assert запись().repeat is True
    стало = domain.score(CHAT_ID)
    # Цифры — ответ движка, а не свой счёт: вычет за запись вдвое больше.
    assert стало.deductions == pytest.approx(без_повтора.deductions * 2)
    assert стало.pct < без_повтора.pct
    assert session.last_text == t("edit.repeat_on", "ru", n=1)  # type: ignore[attr-defined]


async def test_нет_кнопкой_повтор_не_ставит(
    domain_env: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    dp, bot, session = await начать(monkeypatch, {"CLN05"})
    await зафиксировать(dp, bot, monkeypatch)
    без_повтора = domain.score(CHAT_ID)

    await feed(dp, bot, callback(f"{REPEAT_NO_PREFIX}1:CLN05"))  # type: ignore[arg-type]

    assert запись().repeat is False
    assert domain.score(CHAT_ID).pct == без_повтора.pct
    assert session.last_text == t("record.repeat_declined", "ru", n=1)  # type: ignore[attr-defined]


@pytest.mark.parametrize(("слово", "повтор"), [("да", True), ("Да!", True), ("нет", False)])
async def test_ответ_словами_на_вопрос(
    domain_env: object, monkeypatch: pytest.MonkeyPatch, слово: str, повтор: bool
) -> None:
    dp, bot, session = await начать(monkeypatch, {"CLN05"})
    await зафиксировать(dp, bot, monkeypatch)
    вопрос = номер_сообщения(session, текст_вопроса())

    await feed(dp, bot, text_message(слово, reply_to=bot_message(вопрос)))  # type: ignore[arg-type]

    assert запись().repeat is повтор
    assert len(get_state(CHAT_ID).findings) == 1, "ответ на вопрос завёл запись"  # type: ignore[union-attr]


async def test_невнятный_ответ_на_вопрос_переспрашивает_и_ничего_не_меняет(
    domain_env: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    dp, bot, session = await начать(monkeypatch, {"CLN05"})
    await зафиксировать(dp, bot, monkeypatch)
    вопрос = номер_сообщения(session, текст_вопроса())

    await feed(dp, bot, text_message("может быть", reply_to=bot_message(вопрос)))  # type: ignore[arg-type]

    assert запись().repeat is False
    assert session.last_text == t("record.repeat_unclear", "ru", n=1)  # type: ignore[attr-defined]


async def test_не_повтор_ответом_на_запись_снимает_пометку(
    domain_env: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    dp, bot, session = await начать(monkeypatch, {"CLN05"})
    await зафиксировать(dp, bot, monkeypatch)
    await feed(dp, bot, callback(f"{REPEAT_YES_PREFIX}1:CLN05"))  # type: ignore[arg-type]
    assert запись().repeat is True
    # Показ записи — сообщение прямо перед вопросом: вопрос идёт следом за ним.
    вопрос = номер_сообщения(session, текст_вопроса())
    показ = session.sent_ids[session.sent_ids.index(вопрос) - 1]  # type: ignore[attr-defined]

    await feed(dp, bot, text_message("не повтор", reply_to=bot_message(показ)))  # type: ignore[arg-type]

    assert запись().repeat is False
    assert session.last_text == t("edit.repeat_off", "ru", n=1)  # type: ignore[attr-defined]


async def test_да_на_вопрос_о_прежнем_пункте_не_удваивает_поправленную_запись(
    domain_env: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Вопрос задан о пункте: запись поправили на другой — «да» снимается."""
    dp, bot, session = await начать(monkeypatch, {"CLN05"})
    await зафиксировать(dp, bot, monkeypatch)
    domain.edit_finding(CHAT_ID, 1, code="PRD01", zone="hot_kitchen")

    await feed(dp, bot, callback(f"{REPEAT_YES_PREFIX}1:CLN05"))  # type: ignore[arg-type]

    assert запись().repeat is False
    assert session.last_text == t("record.repeat_stale", "ru", n=1)  # type: ignore[attr-defined]
