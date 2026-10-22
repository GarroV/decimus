"""D445: зона записи выводится ПОСЛЕ того, как пункт найден, а не берётся с экрана.

Ядро (зона — это место нарушения в отчёте, ошибка молчалива): чистая функция
`walk_zone.resolve_item_zone` и то, как поиск отдаёт её итог в ответе. Порядок
источников — весь смысл: одна зона пункта → слова аудитора → зона модели → зона
с экрана (только мягкая подсказка) → вопрос пилюлями.
"""

from __future__ import annotations

from typing import Any

import pytest
from test_web_walk_suggest import Модель, _поиск, модель  # noqa: F401 -- фикстура
from test_web_walk_write import Клиент, клиент  # noqa: F401 -- фикстура

from src.bot import propose as ядро
from src.db.queries import pick_usual_zone
from src.recognize.fastpath import FastItem, FastPath
from src.web import walk_suggest, walk_zone
from src.web.walk_zone import resolve_item_zone

ПЕЧЬ = ("hot_kitchen",)
НЕСКОЛЬКО = ("hot_kitchen", "cold_kitchen", "hall")


def test_пункт_одной_зоны_берёт_эту_зону_что_бы_ни_было_на_экране() -> None:
    итог = resolve_item_zone(ПЕЧЬ, spoken=None, model="cold_kitchen", hint="hall")

    assert (итог.zone, итог.source) == ("hot_kitchen", "single")


def test_зона_названная_человеком_сильнее_единственной_зоны_пункта() -> None:
    """D206: названное человеком принимается и вне списка — движок пометит «нетипична»."""
    итог = resolve_item_zone(ПЕЧЬ, spoken="hall", model="cold_kitchen", hint="hot_kitchen")

    assert (итог.zone, итог.source) == ("hall", "words")


def test_слова_аудитора_сильнее_модели_и_экрана() -> None:
    итог = resolve_item_zone(НЕСКОЛЬКО, spoken="cold_kitchen", model="hall", hint="hot_kitchen")

    assert (итог.zone, итог.source) == ("cold_kitchen", "words")


def test_без_слов_берётся_зона_модели_если_она_в_списке_пункта() -> None:
    итог = resolve_item_zone(НЕСКОЛЬКО, spoken=None, model="hall", hint="hot_kitchen")

    assert (итог.zone, итог.source) == ("hall", "model")


def test_зона_модели_вне_списка_пункта_не_берётся_берётся_экран() -> None:
    итог = resolve_item_zone(НЕСКОЛЬКО, spoken=None, model="storage", hint="cold_kitchen")

    assert (итог.zone, итог.source) == ("cold_kitchen", "hint")


def test_экран_вне_списка_пункта_подсказкой_не_служит_спрашиваем() -> None:
    итог = resolve_item_zone(НЕСКОЛЬКО, spoken=None, model=None, hint="storage")

    assert итог.zone is None and итог.source == "ask"
    assert итог.options == НЕСКОЛЬКО, "спрашиваем только зонами пункта, в порядке методики"


def test_зона_вне_списка_пункта_названная_словами_берётся_как_у_бота() -> None:
    итог = resolve_item_zone(НЕСКОЛЬКО, spoken="storage", model="hall", hint="hall")

    assert (итог.zone, итог.source) == ("storage", "words")


def test_ничего_не_сказано_и_экрана_нет_спрашиваем() -> None:
    итог = resolve_item_zone(НЕСКОЛЬКО, spoken=None, model=None, hint=None)

    assert итог.zone is None and итог.source == "ask"


# ── привычная зона пункта (#1109) ─────────────────────────────────────


def test_молчат_все_источники_берётся_привычная_зона_пункта() -> None:
    итог = resolve_item_zone(
        НЕСКОЛЬКО, spoken=None, model=None, hint=None, usual=lambda: "cold_kitchen"
    )

    assert (итог.zone, итог.source) == ("cold_kitchen", "usual")


def test_зона_с_экрана_сильнее_привычки_и_база_не_спрашивается() -> None:
    def привычка() -> str:
        raise AssertionError("привычку не спрашивают, когда зона уже выведена")

    итог = resolve_item_zone(НЕСКОЛЬКО, spoken=None, model=None, hint="hall", usual=привычка)

    assert (итог.zone, итог.source) == ("hall", "hint")


def test_привычная_зона_вне_списка_пункта_не_берётся() -> None:
    итог = resolve_item_zone(НЕСКОЛЬКО, spoken=None, model=None, hint=None, usual=lambda: "storage")

    assert итог.zone is None and итог.source == "ask"


@pytest.mark.parametrize(
    ("счёт", "ждём"),
    [
        ([("hot_kitchen", 3)], "hot_kitchen"),
        ([("hot_kitchen", 7), ("cold_kitchen", 3)], "hot_kitchen"),
        ([("hot_kitchen", 2)], None),
        ([("hot_kitchen", 6), ("cold_kitchen", 4)], None),
        ([], None),
    ],
)
def test_привычка_это_не_меньше_трёх_записей_и_семидесяти_процентов(
    счёт: list[tuple[str, int]], ждём: str | None
) -> None:
    assert pick_usual_zone(счёт) == ждём


# ── в ответе поиска ─────────────────────────────────────────────────────


@pytest.fixture
def зоны(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        walk_suggest, "allowed_zones", lambda code, chat_id: НЕСКОЛЬКО if code == "CLN05" else ПЕЧЬ
    )
    monkeypatch.setattr(walk_suggest, "zone_from_words", lambda note, chat_id: None)


def _разбор(клиент: Клиент, **тело: Any) -> dict[str, Any]:  # noqa: F811
    ответ = _поиск(клиент, photos=[клиент.ссылка()], **тело)
    assert ответ.status_code == 200, ответ.get_json()
    return dict(ответ.get_json()["candidates"][0]["resolution"])


def test_ответ_поиска_несёт_зону_и_источник(
    клиент: Клиент,  # noqa: F811
    модель: Модель,  # noqa: F811
    зоны: None,
) -> None:
    # Модель вернула hot_kitchen, пункт бывает в трёх зонах, экран — холодный цех:
    # зона модели лежит в списке пункта и сильнее экрана.
    итог = _разбор(клиент, zone_hint="cold_kitchen", words="нагар")

    assert итог == {"zone": "hot_kitchen", "source": "model", "options": list(НЕСКОЛЬКО)}


def test_ответ_поиска_экран_не_пишется_зоной_записи_если_пункт_в_другой_зоне(
    клиент: Клиент,  # noqa: F811
    модель: Модель,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    зоны: None,
) -> None:
    monkeypatch.setattr(walk_suggest, "allowed_zones", lambda code, chat_id: ("hall",))

    итог = _разбор(клиент, zone_hint="hot_kitchen", words="нагар")

    assert итог["zone"] == "hall" and итог["source"] == "single"


def test_слово_аудитора_из_общего_разбора_бота_доходит_до_ответа(
    клиент: Клиент,  # noqa: F811
    модель: Модель,  # noqa: F811
    зоны: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(walk_suggest, "zone_from_words", lambda note, chat_id: "hall")

    итог = _разбор(клиент, zone_hint="cold_kitchen", words="нагар в зале")

    assert (итог["zone"], итог["source"]) == ("hall", "words")


def test_старый_клиент_с_полем_zone_читается_как_подсказка(
    клиент: Клиент,  # noqa: F811
    модель: Модель,  # noqa: F811
    зоны: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Модель молчит о зоне пункта в списке — решает подсказка с экрана.
    monkeypatch.setattr(
        walk_suggest, "allowed_zones", lambda code, chat_id: ("cold_kitchen", "hall")
    )
    итог = _разбор(клиент, zone="cold_kitchen", words="нагар")

    assert (итог["zone"], итог["source"]) == ("cold_kitchen", "hint")


def test_ответ_поиска_без_экрана_берёт_привычную_зону_пространства(
    клиент: Клиент,  # noqa: F811
    модель: Модель,  # noqa: F811
    зоны: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    спросили: list[tuple[str, str]] = []

    def привычка(*, tenant: str, code: str) -> str:
        спросили.append((tenant, code))
        return "cold_kitchen"

    # Модель называет горячий цех, а у пункта его нет — её зона не годится.
    monkeypatch.setattr(
        walk_suggest, "allowed_zones", lambda code, chat_id: ("cold_kitchen", "hall")
    )
    monkeypatch.setattr(walk_suggest.queries, "usual_zone", привычка)
    итог = _разбор(клиент, words="нагар")

    assert (итог["zone"], итог["source"]) == ("cold_kitchen", "usual")
    assert спросили and спросили[0][1] == "CLN05"


def test_модуль_зоны_экспортирует_источники() -> None:
    assert set(walk_zone.SOURCES) == {"single", "words", "model", "hint", "usual", "ask"}


def test_быстрый_путь_повторяет_подсказку_экрана_и_это_не_зона_модели(
    клиент: Клиент,  # noqa: F811
    модель: Модель,  # noqa: F811
    зоны: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Быстрый путь зону не выбирает — он эхом возвращает подсказку. Выдать её
    # за «зону модели» значило бы показать подсказку экрана как вывод системы.
    пункт = FastItem(code="CLN05", level="D1", zone="cold_kitchen", title="Печь", cue="нагар")
    monkeypatch.setattr(ядро, "fast_path", lambda *a, **k: FastPath(item=пункт, reason=""))

    итог = _разбор(клиент, zone_hint="cold_kitchen", words="нагар")

    assert (итог["zone"], итог["source"]) == ("cold_kitchen", "hint")
