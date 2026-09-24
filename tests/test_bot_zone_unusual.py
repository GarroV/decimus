"""T147/T271: пара «пункт + зона» вне методики (#118, #239).

До задачи T271 движок нетипичную зону не отклонял, а помечал флагом
`zone_unusual` (`engine/audit.py`, `docs/04-engine.md`) — собственная
документация `view.confirm_line` объясняла это словами «иначе о ней узнает
только партнёр» и требовала показывать пометку аудитору.

Ровно это и было дефектом. Пометку показывала одна первичная фиксация. Правка
зоны — самый частый способ увести запись туда, где пункта нет, — молчала;
список перед сборкой отчёта молчал тоже. Аудитор менял зону, видел
«Поправлено», ничего настораживающего не читал и отправлял отчёт. Партнёр
получал вычет по одной зоне со свидетельством про другую. Живой прогон
владельца показал ту же историю на пункте про печь.

**T271 (#239) сняла саму развилку.** Движок больше не пропускает пару «пункт +
зона», которой методика не даёт, — он её отклоняет, и отказ доходит до
аудитора его же словами (T127), а не тихой пометкой, которую читал только
тот, кто смотрел вывод команды. Флаг `zone_unusual` в коде и в модели данных
остался: выгрузки прошлых лет несут его, и `Finding.zone_unusual` обязан
прочитать его так же, как видел движок тогда. Выставлять его новая запись
больше не может ничем — читать старый файл продукт обязан.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from bot_harness import AUDITOR_ID, CHAT_ID, feed, make_bot, text_message
from bot_harness import callback_query as callback

from src.bot import view
from src.bot.app import build_dispatcher
from src.bot.config import BotSettings
from src.bot.texts import t
from src.domain import Finding, add_finding, get_state, start_inspection

SETTINGS = BotSettings(token="unused-in-tests", allowed_ids=frozenset({AUDITOR_ID}), mode="polling")

#: Пункт заведён только для горячего цеха, поэтому зал для него — зона, которой
#: методика не даёт. Пара взята из `tests/test_domain_finding_invariants.py`,
#: где то же самое проверяется со стороны движка.
ПУНКТ = "CLN05"
СВОЯ_ЗОНА = "hot_kitchen"
ЧУЖАЯ_ЗОНА = "dining"

ПОМЕТКА = t("record.zone_unusual", "ru")


def начать_с_записью() -> None:
    """Проверка с одной записью в правильной для пункта зоне."""
    start_inspection(CHAT_ID, "Белград 2", "planned", "ru", date="2026-08-21", auditor="Гарро")
    finding = add_finding(CHAT_ID, code=ПУНКТ, level="D1", zone=СВОЯ_ЗОНА, text="нагар на поду")
    assert finding.zone_unusual is False, "оснастка начала с уже нетипичной зоны"


@pytest.mark.asyncio
async def test_зона_выбранная_кнопкой_принимается_с_пометкой(domain_env: Path) -> None:
    """D177: зона — там, где продукт. Выбранную человеком зону движок принимает.

    До D177 (с T271) тот же диалог кончался отказом «сбой на моей стороне», и
    сгущёнку, найденную в горячем цехе, туда записать было нельзя. Теперь запись
    переезжает, а пометка «зона нетипична» показывает, что зона вне списка пункта.
    """
    начать_с_записью()
    bot, _ = make_bot()

    await feed(build_dispatcher(SETTINGS), bot, callback(f"ez:1:{ЧУЖАЯ_ЗОНА}"))

    состояние = get_state(CHAT_ID)
    assert состояние is not None
    finding = состояние.finding(1)
    assert finding is not None and finding.zone == ЧУЖАЯ_ЗОНА, "выбранная зона не записалась"
    assert finding.zone_unusual is True, "зона вне списка пункта осталась без пометки"


@pytest.mark.asyncio
async def test_возврат_в_зону_пункта_снимает_пометку(domain_env: Path) -> None:
    """Пометка — свойство зоны вне списка, а не записи навсегда."""
    начать_с_записью()
    bot, _ = make_bot()
    dp = build_dispatcher(SETTINGS)

    await feed(dp, bot, callback(f"ez:1:{ЧУЖАЯ_ЗОНА}"))
    await feed(dp, bot, callback(f"ez:1:{СВОЯ_ЗОНА}"))

    состояние = get_state(CHAT_ID)
    assert состояние is not None
    finding = состояние.finding(1)
    assert finding is not None and finding.zone == СВОЯ_ЗОНА
    assert finding.zone_unusual is False


@pytest.mark.asyncio
async def test_старая_пометка_видна_в_списке_перед_сборкой_отчёта(domain_env: Path) -> None:
    """Предвычитка — последний момент, когда ошибку в зоне ещё можно поймать.

    Флаг больше не выставляется новой записью, но выгрузки прошлых лет несут
    его в состоянии, и список перед сборкой отчёта обязан показать пометку у
    такой записи так же, как показывал раньше, — иначе давняя находка молча
    исчезла бы из предвычитки вместе со сменой движка.
    """
    начать_с_записью()
    файл = domain_env / f"chat_{CHAT_ID}" / "inspection.json"
    сырое = json.loads(файл.read_text(encoding="utf-8"))
    сырое["findings"][0]["zone_unusual"] = True
    файл.write_text(json.dumps(сырое, ensure_ascii=False), encoding="utf-8")

    bot, session = make_bot()
    await feed(build_dispatcher(SETTINGS), bot, text_message("/finish"))

    список = [текст for текст in session.texts if f"#1 {ПУНКТ}" in текст]
    assert список, "в итоге завершения нет строки записи"
    assert ПОМЕТКА in список[0], "список перед сборкой отчёта о нетипичной зоне молчит"


@pytest.mark.asyncio
async def test_обычная_запись_список_не_засоряет(domain_env: Path) -> None:
    """Пометка редкая и потому заметная — на каждой строке она бы обесценилась."""
    начать_с_записью()
    bot, session = make_bot()

    await feed(build_dispatcher(SETTINGS), bot, text_message("/finish"))

    assert ПОМЕТКА not in "\n".join(session.texts), "пометка стоит у записи в её же зоне"


def test_пометка_собирается_одним_правилом_на_все_три_строки(domain_env: Path) -> None:
    """Фиксация, правка и список обязаны решать про пометку одинаково.

    Три места, три отдельных условия — это ровно тот способ, которым пометка и
    потерялась в двух из трёх до T271. Флаг здесь заводится НЕ движком (он
    больше не умеет его выставлять), а собран руками — так же, как выглядит в
    состоянии выгрузка прошлых лет, — потому что здесь проверяется показ, а не
    вывод движка.
    """
    начать_с_записью()
    запись = Finding(
        n=1, code=ПУНКТ, level="D1", zone=ЧУЖАЯ_ЗОНА, text="нагар на поду", zone_unusual=True
    )

    assert ПОМЕТКА in view.confirm_line(запись, "ru", chat_id=CHAT_ID)
    assert ПОМЕТКА in view.changed_line(запись, "ru", chat_id=CHAT_ID)
    assert ПОМЕТКА in view.record_lines([запись], "ru", chat_id=CHAT_ID)


def test_пометка_переводится_вместе_с_остальным_интерфейсом(domain_env: Path) -> None:
    """Язык — параметр и здесь: английский аудитор читает предупреждение по-английски."""
    начать_с_записью()
    запись = Finding(
        n=1, code=ПУНКТ, level="D1", zone=ЧУЖАЯ_ЗОНА, text="нагар на поду", zone_unusual=True
    )
    английская = t("record.zone_unusual", "en")

    assert английская in view.changed_line(запись, "en", chat_id=CHAT_ID)
    assert английская in view.record_lines([запись], "en", chat_id=CHAT_ID)
