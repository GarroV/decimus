"""Зона из карты кадров называется догадкой и на пути через модель (T156, T262).

Правило одно на оба пути, а поведение было разное. Быстрый путь (T124, T121)
честно говорил под записью, откуда зона. На пути через модель того же
предупреждения не было — подсказка уходила в модель, модель возвращала ту же
зону уже как свою, и подтверждение печаталось без оговорки.

Опасность здесь меньше: зона видна на кнопке кандидата до подтверждения, то
есть промах не тихий. Но зона — то, куда уезжает вычет в отчёте партнёру, и
объяснять аудитору происхождение зоны в одном месте и умалчивать в другом
нельзя: он перестаёт доверять пометке вовсе.

**Источник изменился задачей T264 (#218).** До неё зона-догадка бралась из
памяти о прошлой записи (D048) — и это был весь механизм промаха: пункт про
печь уезжал в холодный цех, потому что там была прошлая запись. Памяти среди
источников зоны больше нет вовсе. Теперь догадка — это зона, которую держит
словарь объектов карты кадров (`tests/methodology/photo-cues.md`) за
названным объектом: аудитор сказал «печь», сам объект её не назвал, а карта
твёрдо знает её место. Тот же принцип, что и был: пометка стоит там, где зону
выбрал не человек, а не молчит из-за того, откуда взялась подсказка.

Догадкой зона считается ровно тогда, когда её никто не называл в этих словах, а
запись легла в ту самую зону, которую словарь объектов держит за названным
объектом. Ответила модель другой зоной — это её ответ, а не словарь, и пометки
такая запись не получает: пометка не про «зону выбрал не человек», а про «зону
взяли из карты кадров».
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from bot_harness import (
    AUDITOR_ID,
    CHAT_ID,
    callback_query,
    candidate,
    feed,
    make_bot,
    manual,
    photo_message,
    stub_classify,
    stub_manual,
    suggestion,
)

from src.bot.app import build_dispatcher
from src.bot.config import BotSettings
from src.bot.texts import t
from src.domain import get_state, start_inspection

pytestmark = pytest.mark.asyncio

SETTINGS = BotSettings(
    token="unused-in-tests",
    allowed_ids=frozenset({AUDITOR_ID}),
    mode="polling",
    auditor_names={},
)

#: Оговорка про зону из карты кадров — та же самая, что у быстрого пути. Второй
#: формулировки заводить нельзя: разошлись бы, как разошлось само поведение.
GUESS = t("record.fixed_zone_from_cues", "ru").strip()

#: Комментарий называет объект карты кадров («Печь» → `hot_kitchen`,
#: `tests/methodology/photo-cues.md`), но не называет ни грязь, ни поломку —
#: быстрый путь по нему не решает (нужна ещё и колонка), и материал уходит
#: модели. Ровно то, что нужно тестам файла: зона выводится словарём объектов,
#: а разбирает её модель, а не сверка со списком нарушений.
СЛОВА_С_ОБЪЕКТОМ = "печь, посмотрите пожалуйста"


def начата() -> None:
    start_inspection(CHAT_ID, "Белград 2", "planned", "ru", date="2026-08-21", auditor="Гарро")


async def разобрать_моделью(
    dp: Any, bot: Any, monkeypatch: pytest.MonkeyPatch, *, зона: str, слова: str
) -> None:
    """Кадр с комментарием → модель отвечает кандидатом → аудитор его подтверждает."""
    stub_classify(monkeypatch, suggestion(candidate("CLN05", "D1", зона, "Нагар на поду печи")))
    await feed(dp, bot, photo_message("frame-1", caption=слова, message_id=501))
    await feed(dp, bot, callback_query("rec:pick:0"))


async def test_подтверждённая_запись_называет_зону_догадкой_если_её_не_называли(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Сам случай задачи: слова называют объект, а не зону; зону дал словарь."""
    начата()
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await разобрать_моделью(dp, bot, monkeypatch, зона="hot_kitchen", слова=СЛОВА_С_ОБЪЕКТОМ)

    состояние = get_state(CHAT_ID)
    assert состояние is not None and состояние.findings, "запись не появилась"
    assert GUESS in session.last_text, "зона взята из карты кадров, а подтверждение об этом молчит"


async def test_названная_словами_зона_догадкой_не_называется(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Пометка не бывает дежурной: сказал человек зону сам — оговорки нет."""
    начата()
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    # «Касса» — обиходное имя зоны `dining` (`src/bot/zones.py: SPOKEN`), и
    # словами она названа целиком: сверке зацепиться не за что (объекта карты
    # кадров тут нет), и материал тоже уходит модели.
    await разобрать_моделью(dp, bot, monkeypatch, зона="dining", слова="на кассе беспорядок")

    assert GUESS not in session.last_text


async def test_своя_зона_модели_догадкой_из_словаря_не_считается(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Модель ответила не тем, что подсказал словарь объектов, — он тут ни при чём."""
    начата()
    # CLN05 (печь) методика держит только в `hot_kitchen` — не годится показать
    # на нём зону, отличную от подсказки словаря, движок её и не примет.
    # PRD01 живёт в трёх зонах разом, и `fridge` — среди них, поэтому модель
    # вправе ответить им, не столкнувшись с отказом движка.
    stub_classify(monkeypatch, suggestion(candidate("PRD01", "D1", "fridge", "Без ярлыка")))
    начата()
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await feed(dp, bot, photo_message("frame-1", caption=СЛОВА_С_ОБЪЕКТОМ, message_id=501))
    await feed(dp, bot, callback_query("rec:pick:0"))

    состояние = get_state(CHAT_ID)
    assert состояние is not None and [f.zone for f in состояние.findings] == ["fridge"], (
        "запись легла не в ту зону, которую ответила модель"
    )
    assert GUESS not in session.last_text


async def test_зона_выбранная_кнопкой_догадкой_не_называется(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Кандидат без зоны: её называет сам аудитор кнопкой, и это не словарь."""
    начата()
    stub_classify(monkeypatch, suggestion(candidate("CLN05", "D1", "", "Нагар на поду печи")))
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await feed(dp, bot, photo_message("frame-1", caption="мусор в углу", message_id=501))
    await feed(dp, bot, callback_query("rec:pick:0"))
    await feed(dp, bot, callback_query("rec:zp:hot_kitchen"))

    состояние = get_state(CHAT_ID)
    assert состояние is not None and состояние.findings, "запись не появилась"
    assert GUESS not in session.last_text


async def test_ручной_выбор_пункта_тоже_называет_зону_из_словаря_догадкой(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Модель недоступна — перечень собирается по зоне, и зона та же из словаря.

    Путь другой, правило то же: аудитор выбрал пункт, но не зону, а вычет
    уедет партнёру именно в неё.
    """
    начата()
    stub_classify(monkeypatch, suggestion())
    stub_manual(monkeypatch, (manual("CLN05", ("D1",), "Печь чистая?"),))
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await feed(dp, bot, photo_message("frame-1", caption=СЛОВА_С_ОБЪЕКТОМ, message_id=501))
    await feed(dp, bot, callback_query("rec:mi:0"))

    состояние = get_state(CHAT_ID)
    assert состояние is not None and состояние.findings, "запись не появилась"
    assert GUESS in session.last_text


async def test_зона_названная_кнопкой_в_ручном_перечне_догадкой_не_называется(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Словарь молчит, зону спросили кнопкой — и записал пункт по ней сам аудитор.

    Ветка, на которой пометка легче всего становится дежурной: перечень тут
    собран по зоне, но зону эту назвал человек, а не словарь объектов.
    """
    начата()
    stub_classify(monkeypatch, suggestion())
    stub_manual(monkeypatch, (manual("CLN05", ("D1",), "Печь чистая?"),))
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await feed(dp, bot, photo_message("frame-1", caption="мусор в углу", message_id=501))
    await feed(dp, bot, callback_query("rec:zm:hot_kitchen"))
    await feed(dp, bot, callback_query("rec:mi:0"))

    состояние = get_state(CHAT_ID)
    assert состояние is not None and состояние.findings, "запись не появилась"
    assert GUESS not in session.last_text
