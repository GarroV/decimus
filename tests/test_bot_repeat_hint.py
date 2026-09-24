"""#359: бот подсказывает, что такой же пункт был в прошлой проверке точки.

Кнопка «Повтор ×2» появилась раньше подсказки, и в этом была дыра: чтобы ею
воспользоваться, аудитор должен был ПОМНИТЬ прошлую проверку наизусть. Правило
D191 при этом существовало — и не применялось, потому что применить его было
нечем.

Что здесь стережётся, кроме самого показа: подсказка приносит наблюдение и не
трогает запись. Система, решившая за аудитора, удвоила бы вычет там, где
нарушение другое, — тот же код мог относиться к другому объекту, а
исправленное и снова сломавшееся не равно не исправленному вовсе.
"""

from __future__ import annotations

import logging

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
from bot_harness import (
    callback_query as callback,
)

from src.bot import repeats
from src.bot.app import build_dispatcher
from src.bot.config import BotSettings
from src.bot.texts import t
from src.db.errors import DbError
from src.domain import get_state, start_inspection
from src.domain.models import Inspection

pytestmark = [pytest.mark.asyncio]

SETTINGS = BotSettings(token="unused-in-tests", allowed_ids=frozenset({AUDITOR_ID}), mode="polling")

ПОДСКАЗКА = t("record.repeat_seen", "ru")


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
    """Подменить поход в базу за кодами прошлой проверки. Возврат — журнал вызовов."""
    звали: list[dict[str, str]] = []

    def вместо(*, tenant: str, unit: str) -> set[str]:
        звали.append({"tenant": tenant, "unit": unit})
        if isinstance(ответ, Exception):
            raise ответ
        assert isinstance(ответ, set)
        return ответ

    monkeypatch.setattr(repeats.queries, "previous_codes", вместо)
    return звали


# --- наблюдение само по себе ------------------------------------------------


def test_пункт_из_прошлой_проверки_узнаётся(monkeypatch: pytest.MonkeyPatch) -> None:
    звали = подменить(monkeypatch, {"CLN05", "PRD01"})

    assert repeats.seen_before(проверка(), code="CLN05", level="D1") is True
    assert звали == [{"tenant": "dodo", "unit": "Белград 2"}]


def test_новый_пункт_подсказки_не_поднимает(monkeypatch: pytest.MonkeyPatch) -> None:
    подменить(monkeypatch, {"PRD01"})

    assert repeats.seen_before(проверка(), code="CLN05", level="D1") is False


def test_d3_не_спрашивает_базу_вовсе(monkeypatch: pytest.MonkeyPatch) -> None:
    """Класс сжигает долю зоны целиком — ставки за запись нет, удваивать нечего.

    Подсказка, зовущая нажать кнопку, которая ничего не изменит, хуже её
    отсутствия: она обещает аудитору действие, а действие не работает.
    """
    звали = подменить(monkeypatch, {"CLN05"})

    assert repeats.seen_before(проверка(), code="CLN05", level="D3") is False
    assert звали == [], "за подсказкой, которую нельзя показать, в базу не ходят"


def test_без_проверки_подсказывать_нечем(monkeypatch: pytest.MonkeyPatch) -> None:
    звали = подменить(monkeypatch, {"CLN05"})

    assert repeats.seen_before(None, code="CLN05", level="D1") is False
    assert звали == []


def test_безымянная_точка_в_базу_не_ходит(monkeypatch: pytest.MonkeyPatch) -> None:
    """Пустое название вернуло бы отказ — поход за ним бессмыслен."""
    звали = подменить(monkeypatch, {"CLN05"})

    assert repeats.seen_before(проверка(unit="  "), code="CLN05", level="D1") is False
    assert repeats.seen_before(проверка(tenant=""), code="CLN05", level="D1") is False
    assert звали == []


def test_молчащая_база_снимает_подсказку_и_говорит_об_этом(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Обход не зависит от справочного запроса, но пропажа подсказки не молчит."""
    подменить(monkeypatch, DbError("база недоступна"))

    with caplog.at_level(logging.WARNING):
        assert repeats.seen_before(проверка(), code="CLN05", level="D1") is False

    assert any("предыдущей проверки" in r.getMessage() for r in caplog.records)


# --- показ на обходе --------------------------------------------------------


async def зафиксировать(dp: object, bot: object, monkeypatch: pytest.MonkeyPatch) -> None:
    stub_classify(monkeypatch, suggestion(candidate("CLN05", "D1", "hot_kitchen", "Печь в нагаре")))
    # Формулировка намеренно НЕ совпадает со списком нарушений напрямую: прямое
    # совпадение фиксирует запись сразу, и кнопка кандидата тогда лишняя.
    await feed(
        dp, bot, photo_message("frame-1", caption="печь, посмотри что тут, тепловой участок")
    )
    await feed(dp, bot, callback("rec:pick:0"))


async def test_запись_повторяющая_прошлую_проверку_получает_подсказку(
    domain_env: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    start_inspection(CHAT_ID, "Белград 2", "planned", "ru")
    подменить(monkeypatch, {"CLN05"})
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await зафиксировать(dp, bot, monkeypatch)

    assert ПОДСКАЗКА in session.texts


async def test_подсказка_идёт_после_записи_и_не_вместо_неё(
    domain_env: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Блок записи говорит, что записано; подсказка — что известно про прошлый раз.

    Порядок здесь и есть смысл: наблюдение системы не выдаётся за часть записи,
    которую аудитор принял.
    """
    start_inspection(CHAT_ID, "Белград 2", "planned", "ru")
    подменить(monkeypatch, {"CLN05"})
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await зафиксировать(dp, bot, monkeypatch)

    assert session.texts[-1] == ПОДСКАЗКА
    блок = next(текст for текст in session.texts if "CLN05" in текст)
    assert session.texts.index(блок) < session.texts.index(ПОДСКАЗКА)


async def test_подсказка_ничего_не_меняет_в_записи(
    domain_env: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Цену назначает аудитор кнопкой — система только приносит наблюдение."""
    start_inspection(CHAT_ID, "Белград 2", "planned", "ru")
    подменить(monkeypatch, {"CLN05"})
    bot, _session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await зафиксировать(dp, bot, monkeypatch)

    состояние = get_state(CHAT_ID)
    assert состояние is not None
    запись = состояние.finding(1)
    assert запись is not None
    assert запись.repeat is False


async def test_новый_пункт_подсказки_не_получает(
    domain_env: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    start_inspection(CHAT_ID, "Белград 2", "planned", "ru")
    подменить(monkeypatch, {"PRD01"})
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await зафиксировать(dp, bot, monkeypatch)

    assert ПОДСКАЗКА not in session.texts
