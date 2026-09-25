"""T344: крючки MCP — «какой чек-лист» у каждого инструмента методики.

Главное обещание задачи проверяется здесь: **старые вызовы агента продолжают
работать слово в слово**. Инструмент, позванный без кода, работает с тем
чек-листом, что применён к проду, — не с тем, что был единственным до
множественности, и не с первым попавшимся.

Зовётся всё через точку входа (`handle`), а не через обработчики напрямую:
параметр снимает именно она, и проверка мимо неё проверяла бы не то.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from mcp_checklist_harness import build_methodology

from src.mcp.checklist import Store, current_version
from src.mcp.checklist_layout import DRAFT, applied
from src.mcp.checklists import apply_to_production, create
from src.mcp.rpc import handle

АРЕНДАТОР = "укашка"


@pytest.fixture
def хранилище(tmp_path: Path) -> Store:
    методика = build_methodology(tmp_path / "живая-методика")
    store = Store(root=tmp_path / "хранилище", live=методика)
    current_version(store)
    return store


def _вызвать(имя: str, аргументы: dict[str, Any], *, store: Store) -> dict[str, Any]:
    ответ = handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": имя, "arguments": аргументы},
        },
        tenant=АРЕНДАТОР,
        checklist=store,
        source=store,
        may_retract=False,
    )
    assert ответ is not None
    return ответ


def _текст(ответ: dict[str, Any]) -> str:
    return "".join(блок.get("text", "") for блок in ответ["result"]["content"])


def _ошибка(ответ: dict[str, Any]) -> bool:
    return bool(ответ["result"].get("isError"))


def test_перечень_чеклистов_отдаётся_через_инструмент(хранилище: Store) -> None:
    ответ = _вызвать("checklists", {}, store=хранилище)

    assert not _ошибка(ответ)
    текст = _текст(ответ)
    assert "bizdev" in текст and "applied_to_production" in текст


def test_заведение_чеклиста_идёт_через_инструмент(хранилище: Store) -> None:
    """Возможность не появляется только на экране: то, что умеет админка,
    умеет и агент (D180)."""
    ответ = _вызвать(
        "create_checklist",
        {"checklist": "rnd", "name_ru": "Аудит РНД", "name_en": "RnD audit"},
        store=хранилище,
    )

    assert not _ошибка(ответ)
    assert DRAFT in _текст(ответ)
    assert (хранилище.root / "hq" / "rnd").is_dir()


def test_вызов_без_кода_идёт_в_применённый_к_проду(хранилище: Store) -> None:
    """Обещание совместимости: старый вызов работает слово в слово.

    Причём «по умолчанию» — это ПРИМЕНЁННЫЙ к проду, а не тот, что был
    единственным: иначе после смены прода правка без кода уходила бы в
    чек-лист, по которому больше не считают, и не сказала бы об этом.
    """
    import json

    свой = Store(root=хранилище.root, live=хранилище.live, code="rnd")
    create(свой, tenant=АРЕНДАТОР, name_ru="Аудит РНД", name_en="RnD")
    правка = _вызвать(
        "add_checklist_item",
        {
            "checklist": "rnd",
            "code": "RND01",
            "process": "Проба",
            "question_ru": "Проба пера",
            "levels": "D1",
            "zones": "all",
            "days": 5,
            "criteria": "D1: проба",
            "version_name": "rnd",
        },
        store=хранилище,
    )
    # Издание берётся из ОТВЕТА правки, а не угадывается по перечню: у двух
    # изданий одного дня порядок решает строка, и угаданное оказалось бы
    # бланком, из которого чек-лист родился.
    новое = json.loads(_текст(правка))["version"]

    # До применения вызов без кода читает чек-лист прода — в нём пункта нет.
    было = _текст(_вызвать("checklist_items", {}, store=хранилище))
    assert "RND01" not in было

    # Применяем rnd к проду и повторяем ТОТ ЖЕ вызов без кода.
    _вызвать(
        "publish_checklist_version",
        {"checklist": "rnd", "version": новое},
        store=хранилище,
    )
    apply_to_production(свой, tenant=АРЕНДАТОР)

    стало = json.loads(_текст(_вызвать("checklist_items", {}, store=хранилище)))

    assert applied(хранилище.root) == ("hq", "rnd")
    assert any(пункт["id"] == "RND01" for пункт in стало["items"])


def test_негодный_код_чеклиста_это_отказ_а_не_чужой_чеклист(хранилище: Store) -> None:
    """Код приходит снаружи и становится куском пути внутри хранилища."""
    ответ = _вызвать("checklist_versions", {"checklist": "../побег"}, store=хранилище)

    assert _ошибка(ответ)
    assert "не годится" in _текст(ответ)


def test_незнакомый_код_не_заводит_чеклист_молча(хранилище: Store) -> None:
    """Иначе опечатка в коде рождала бы копию боевой методики под новым именем."""
    ответ = _вызвать("checklist_items", {"checklist": "opechatka"}, store=хранилище)

    assert _ошибка(ответ)
    assert "create_checklist" in _текст(ответ)
