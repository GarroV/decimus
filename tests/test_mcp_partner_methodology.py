"""D460: админ партнёра ведёт методику своего пространства и в Claude, как в вебе.

Ядро — права: ошибка здесь тихая (партнёр правит чужое или эталон УК, и никто не
увидит). Проверяется сквозь настоящую дверь: `Settings` без партнёра в
`MCP_CHECKLIST_TENANTS` (партнёров в базе много, список им не нужен), роль из входа
через OAuth, хранилище подставляет `server._checklist_for`, вызов идёт через `handle`.
Базы тестам не нужно.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from mcp_checklist_harness import build_methodology

from src.mcp.catalogue import KIND_CHECKLIST, KIND_CHECKLIST_SOURCE, TOOLS
from src.mcp.checklist import Store, current_version, read_journal
from src.mcp.checklist_layout import read_meta
from src.mcp.checklists import create
from src.mcp.config import MIN_TOKEN_LENGTH, Settings
from src.mcp.rpc import ETALON_READONLY_FOR_PARTNER, ROLE_CLOSED, handle
from src.mcp.server import _checklist_for, _checklist_source_for

ПАРТНЁР = "GE"
ЧУЖОЙ = "AM"
СЕГОДНЯ = date(2026, 10, 13)

ПРАВКА_ЭТАЛОНА = {"checklist": "bizdev", "name_ru": "Захват"}


@pytest.fixture
def настройки(tmp_path: Path) -> Settings:
    методика = build_methodology(tmp_path / "методика")
    store = Store(root=tmp_path / "хранилище", live=методика)
    current_version(store)
    for space, tenant, code in (("ge", ПАРТНЁР, "own"), ("am", ЧУЖОЙ, "rnd")):
        create(
            replace(store, space=space, code=code),
            tenant=tenant,
            name_ru="Свой",
            name_en="Own",
            today=СЕГОДНЯ,
        )
    return Settings(
        tokens={"h" * MIN_TOKEN_LENGTH: "HQ"},
        tenants=("HQ",),
        host="127.0.0.1",
        port=0,
        checklist_store=store.root,
        # Партнёров в списке нет нарочно: их открывает роль, а не `.env`.
        checklist_tenants=("HQ",),
        data_dir=методика,
    )


def _вызов(
    имя: str, аргументы: dict[str, Any], настройки: Settings, *, role: str, tenant: str = ПАРТНЁР
) -> dict[str, Any]:
    ответ = handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": имя, "arguments": аргументы},
        },
        tenant=tenant,
        checklist=_checklist_for(настройки, tenant, role),
        source=_checklist_source_for(настройки, tenant, role),
        role=role,
    )
    assert ответ is not None
    return ответ


def _список(настройки: Settings, *, role: str, tenant: str = ПАРТНЁР) -> set[str]:
    ответ = handle(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        tenant=tenant,
        checklist=_checklist_for(настройки, tenant, role),
        source=_checklist_source_for(настройки, tenant, role),
        role=role,
    )
    assert ответ is not None
    return {t["name"] for t in ответ["result"]["tools"]}


def _отказ(ответ: dict[str, Any]) -> bool:
    """Отказ инструмента или отказ разбора запроса (лишний ключ, JSON-RPC error)."""
    return "error" in ответ or bool(ответ["result"].get("isError"))


def _текст(ответ: dict[str, Any]) -> str:
    if "error" in ответ:
        return str(ответ["error"])
    return "".join(блок.get("text", "") for блок in ответ["result"]["content"])


def _store(настройки: Settings, *, space: str, code: str) -> Store:
    assert настройки.checklist_store is not None and настройки.data_dir is not None
    return Store(root=настройки.checklist_store, live=настройки.data_dir, space=space, code=code)


def test_админу_партнёра_в_tools_list_видна_методика(настройки: Settings) -> None:
    имена = _список(настройки, role="admin")

    assert {"checklists", "checklist_items", "edit_checklist_item", "checklist_source"} <= имена
    assert {"create_checklist", "publish_checklist_version"} <= имена
    assert "apply_checklist" not in имена


def test_сотруднику_партнёра_методика_видна_только_на_чтение(настройки: Settings) -> None:
    имена = _список(настройки, role="auditor")

    assert {"checklists", "checklist_items", "checklist_source"} <= имена
    assert not имена & {"edit_checklist_item", "rename_checklist", "publish_checklist_version"}


def test_хранилище_партнёру_даёт_роль_а_не_список_env(настройки: Settings) -> None:
    своё = _checklist_for(настройки, ПАРТНЁР, "admin")
    assert своё is not None and своё.space == "ge"
    assert _checklist_for(настройки, ПАРТНЁР, "auditor") is not None  # читает; правку режет роль
    assert _checklist_for(настройки, ПАРТНЁР, "guest") is None
    # Токен без роли (карта `.env`): решает список, как раньше, — партнёра в нём нет.
    assert _checklist_for(настройки, ПАРТНЁР, None) is None
    assert _checklist_source_for(настройки, ПАРТНЁР, None) is None
    эталон = _checklist_source_for(настройки, ПАРТНЁР, "admin")
    assert эталон is not None and эталон.space == "hq"


def test_админ_партнёра_правит_свой_чек_лист_в_своём_пространстве(настройки: Settings) -> None:
    ответ = _вызов(
        "rename_checklist", {"checklist": "own", "name_ru": "Новое"}, настройки, role="admin"
    )

    assert ответ["result"].get("isError") is not True
    assert json.loads(_текст(ответ))["space"] == "ge"
    assert read_meta(_store(настройки, space="ge", code="own")).name_ru == "Новое"


def test_админ_партнёра_заводит_чек_лист_только_у_себя(настройки: Settings) -> None:
    ответ = _вызов(
        "create_checklist",
        {"checklist": "second", "name_ru": "Второй", "name_en": "Second"},
        настройки,
        role="admin",
    )

    assert ответ["result"].get("isError") is not True, _текст(ответ)
    assert read_meta(_store(настройки, space="ge", code="second")).name_ru == "Второй"
    assert read_meta(_store(настройки, space="hq", code="second")) is None


def test_админ_партнёра_читает_эталон_но_не_правит_его(настройки: Settings) -> None:
    эталон = _store(настройки, space="hq", code="bizdev")
    журнал_до, карточка_до = read_journal(эталон), read_meta(эталон)

    чтение = _вызов("checklist_source", {}, настройки, role="admin")
    правка = _вызов("rename_checklist", ПРАВКА_ЭТАЛОНА, настройки, role="admin")

    assert чтение["result"].get("isError") is not True
    assert правка["result"].get("isError") is True
    assert _текст(правка) == ETALON_READONLY_FOR_PARTNER.format(код="bizdev")
    assert read_journal(эталон) == журнал_до
    assert read_meta(эталон) == карточка_до


def test_админ_партнёра_не_правит_чек_лист_чужого_партнёра(настройки: Settings) -> None:
    чужой = _store(настройки, space="am", code="rnd")
    карточка_до, журнал_до = read_meta(чужой), read_journal(чужой)

    ответ = _вызов(
        "rename_checklist", {"checklist": "rnd", "name_ru": "x"}, настройки, role="admin"
    )

    assert ответ["result"].get("isError") is True
    assert "в пространстве «ge» нет" in _текст(ответ)
    assert read_meta(чужой) == карточка_до
    assert read_journal(чужой) == журнал_до


def test_админ_партнёра_не_двигает_указатель_прода(настройки: Settings) -> None:
    ответ = _вызов("apply_checklist", {"checklist": "own"}, настройки, role="admin")

    assert ответ["result"].get("isError") is True
    assert "применяет только УК" in _текст(ответ)


def test_сотрудник_партнёра_читает_методику_но_не_правит(настройки: Settings) -> None:
    чтение = _вызов("checklists", {}, настройки, role="auditor")
    правка = _вызов(
        "rename_checklist", {"checklist": "own", "name_ru": "x"}, настройки, role="auditor"
    )

    assert чтение["result"].get("isError") is not True
    assert правка["result"].get("isError") is True
    assert _текст(правка) == ROLE_CLOSED.format(роль="auditor")
    assert read_meta(_store(настройки, space="ge", code="own")).name_ru == "Свой"


# --- ревью безопасности: токен партнёра не выходит за своё пространство ---------

ИНСТРУМЕНТЫ_МЕТОДИКИ = sorted(
    spec.name for spec in TOOLS if spec.kind in (KIND_CHECKLIST, KIND_CHECKLIST_SOURCE)
)
#: Всё, что вызывающий может подсунуть, чтобы выйти из пространства: код эталона и
#: чужого партнёра, пути, чужое пространство отдельными ключами.
НАЦЕЛИВАНИЯ: list[dict[str, Any]] = [
    {},
    {"checklist": "bizdev"},
    {"checklist": "rnd"},
    {"checklist": "../am/rnd"},
    {"checklist": "am/rnd"},
    {"checklist": "bizdev", "tenant": "HQ", "space": "hq", "store": "x", "path": "/nonexistent"},
]


def _снимок(настройки: Settings) -> dict[str, bytes]:
    """Всё хранилище, кроме пространства партнёра GE: эталон УК, чужой партнёр, указатель."""
    assert настройки.checklist_store is not None
    корень = настройки.checklist_store
    return {
        str(путь.relative_to(корень)): путь.read_bytes()
        for путь in sorted(корень.rglob("*"))
        if путь.is_file() and путь.relative_to(корень).parts[0] != "ge"
    }


@pytest.mark.parametrize("роль", ["admin", "auditor"])
@pytest.mark.parametrize("цель", НАЦЕЛИВАНИЯ, ids=lambda x: ",".join(sorted(x)) or "без аргументов")
@pytest.mark.parametrize("инструмент", ИНСТРУМЕНТЫ_МЕТОДИКИ)
def test_ни_один_инструмент_методики_не_трогает_чужое_пространство(
    настройки: Settings, инструмент: str, цель: dict[str, Any], роль: str
) -> None:
    """Перебор всех инструментов методики: эталон УК, чужой партнёр и указатель прода
    после любого вызова партнёра A байт в байт те же — и записью, и чтением со
    сторонними ключами. Чтение эталона законно (D132), поэтому проверяется изменение,
    а не недоступность; чтение чужого партнёра — отдельным тестом ниже."""
    до = _снимок(настройки)

    _вызов(инструмент, dict(цель), настройки, role=роль)

    assert _снимок(настройки) == до, f"{инструмент} {цель}: тронуто чужое пространство"


@pytest.mark.parametrize("инструмент", sorted(n for n in ИНСТРУМЕНТЫ_МЕТОДИКИ if n != "checklists"))
def test_партнёр_не_читает_методику_чужого_партнёра(настройки: Settings, инструмент: str) -> None:
    """Ни один читающий инструмент не отдаёт карточку или состав чек-листа партнёра B.
    Пишущие отказывают, а не отвечают данными."""
    ответ = _вызов(инструмент, {"checklist": "rnd"}, настройки, role="admin")
    текст = _текст(ответ)

    assert "РНД" not in текст and "RnD" not in текст, f"{инструмент}: утечка чужого чек-листа"
    assert _отказ(ответ) or инструмент.startswith("checklist_source")


def test_перечень_партнёра_не_называет_чужие_чек_листы(настройки: Settings) -> None:
    текст = _текст(_вызов("checklists", {}, настройки, role="admin"))

    assert "rnd" not in текст and "own" in текст


def test_накопитель_слов_аудиторов_партнёру_не_отдаётся(
    настройки: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Накопитель непокрытых слов общий на все пространства (разделения в нём нет): по
    ревью безопасности он не открывается партнёру ни ролью, ни списком `.env`."""
    monkeypatch.setattr(
        "src.mcp.uncovered.read_uncovered",
        lambda: [],
    )
    адрес = {"read_all_called": False}

    def _не_читать(**_: Any) -> dict[str, Any]:
        адрес["read_all_called"] = True
        return {"candidates": ["слово чужого пространства"]}

    monkeypatch.setattr("src.mcp.uncovered.read_all", _не_читать)
    по_роли = _вызов("uncovered_phrases", {"checklist": "own"}, настройки, role="admin")
    # Токен без роли, партнёр назван в списке `.env`: матрицы нет, держит второй замок.
    список = replace(настройки, checklist_tenants=("HQ", ПАРТНЁР))
    ответ = handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "uncovered_phrases", "arguments": {"checklist": "own"}},
        },
        tenant=ПАРТНЁР,
        checklist=_checklist_for(список, ПАРТНЁР),
        source=_checklist_source_for(список, ПАРТНЁР),
    )
    assert ответ is not None

    assert _отказ(по_роли)
    assert _отказ(ответ)
    assert "чужого пространства" not in _текст(по_роли) + _текст(ответ)
    assert адрес["read_all_called"] is False
