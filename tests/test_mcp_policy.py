"""Права MCP по роли учётки сайта (D417): матрица «роль × вид инструментов».

Ядро: ошибка здесь не громкая, а тихая — «контроль» получил бы историю
проверок, партнёр — правку методики УК, и никто бы этого не увидел, пока не
спросил. Поэтому матрица проверяется целиком, клеткой на строку, а не
выборочно, и проверяется дважды: в `tools/list` и на вызове — одна функция на
оба места, и тест держит, что так и есть.

Роль задаётся только у входа через OAuth. Двери бота и `.env` роли не знают
(`role=None`), и для них ничего не меняется — это тоже проверено здесь.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.domain.permissions import ACTION_CODES
from src.mcp.catalogue import (
    KIND_CHECKLIST,
    KIND_CHECKLIST_SOURCE,
    KIND_IMPORT,
    KIND_INSPECTIONS,
    KIND_RATINGS,
    KIND_RATINGS_READ,
    KIND_RETRACTION,
    TOOLS,
)
from src.mcp.policy import action_of, permits
from src.mcp.rpc import handle

ВСЕ_ВИДЫ = (
    KIND_INSPECTIONS,
    KIND_CHECKLIST_SOURCE,
    KIND_CHECKLIST,
    KIND_IMPORT,
    KIND_RATINGS_READ,
    KIND_RATINGS,
    KIND_RETRACTION,
)

#: Матрица из спеки `docs/superpowers/specs/2026-10-12-claude-connect-design.md`,
#: раздел «Права по роли». Клетка «да, если HQ в MCP_CHECKLIST_TENANTS» здесь
#: «да»: условие настройки держит прежний заслон (`rpc._call_tool`), а роль
#: решает только то, что решает роль. Контроль — только рейтинги (D420).
_ВСЁ_УК = frozenset(
    {
        KIND_INSPECTIONS,
        KIND_CHECKLIST_SOURCE,
        KIND_CHECKLIST,
        KIND_IMPORT,
        KIND_RATINGS_READ,
        KIND_RATINGS,
    }
)
МАТРИЦА: dict[tuple[str, str], frozenset[str]] = {
    ("HQ", "superadmin"): _ВСЁ_УК,
    ("HQ", "admin"): _ВСЁ_УК,
    # Девелопер заносит проверки через Claude (D567).
    ("HQ", "developer"): frozenset(
        {KIND_INSPECTIONS, KIND_CHECKLIST_SOURCE, KIND_CHECKLIST, KIND_RATINGS_READ, KIND_IMPORT}
    ),
    # Гость (D440): только чтение проверок и рейтингов. Аудитора в УК больше нет.
    ("HQ", "guest"): frozenset({KIND_INSPECTIONS, KIND_RATINGS_READ}),
    ("HQ", "auditor"): frozenset(),
    ("HQ", "control"): frozenset({KIND_RATINGS_READ, KIND_RATINGS}),
    # Админ партнёра (D460): методика его пространства — как в вебе.
    ("RS", "admin"): frozenset(
        {KIND_INSPECTIONS, KIND_CHECKLIST_SOURCE, KIND_CHECKLIST, KIND_RATINGS_READ}
    ),
    # Сотрудник партнёра (D460): методика на чтение, как в вебе; правящие инструменты закрыты.
    ("RS", "auditor"): frozenset(
        {KIND_INSPECTIONS, KIND_CHECKLIST_SOURCE, KIND_CHECKLIST, KIND_RATINGS_READ}
    ),
}


@pytest.mark.parametrize(("арендатор", "роль"), sorted(МАТРИЦА))
@pytest.mark.parametrize("вид", ВСЕ_ВИДЫ)
def test_клетка_матрицы(арендатор: str, роль: str, вид: str) -> None:
    ожидание = вид in МАТРИЦА[(арендатор, роль)]

    assert permits(роль, арендатор, вид) is ожидание, (
        f"{роль}@{арендатор} × {вид}: ожидалось {'да' if ожидание else 'нет'}"
    )


@pytest.mark.parametrize("роль", ["superadmin", "admin", "developer", "guest", "control"])
def test_снятие_проверки_через_oauth_закрыто_всем(роль: str) -> None:
    assert permits(роль, "HQ", KIND_RETRACTION) is False


def test_старый_код_уk_переводится() -> None:
    """`default` — прежний код УК (D234): права те же, что у `HQ`."""
    assert permits("admin", "default", KIND_IMPORT) is True


@pytest.mark.parametrize("роль", ["control", "superadmin"])
def test_роли_только_уk_у_партнёра_не_дают_больше_чтения(роль: str) -> None:
    """control/superadmin бывают только в HQ (держит база); строка с такой ролью у
    партнёра — незнакомая матрице роль стороны партнёра, и ей не открыто ничего."""
    открыто = {вид for вид in ВСЕ_ВИДЫ if permits(роль, "RS", вид)}

    assert открыто == set()


@pytest.mark.parametrize("роль", ["", "owner", "ADMIN", "root"])
def test_незнакомая_роль_не_получает_ничего(роль: str) -> None:
    assert not any(permits(роль, "HQ", вид) for вид in ВСЕ_ВИДЫ)


def test_незнакомый_вид_закрыт_всем() -> None:
    """Новый вид инструментов, не внесённый в матрицу, закрыт, а не открыт."""
    assert permits("superadmin", "HQ", "новый_вид") is False


# --- одна функция на tools/list и на вызов -----------------------------------


def _список(**доступ: Any) -> set[str]:
    ответ = handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, **доступ)
    assert ответ is not None
    return {t["name"] for t in ответ["result"]["tools"]}


#: Виды, у которых в каталоге уже есть инструменты. Чтения рейтингов
#: (`KIND_RATINGS_READ`) пока нет — инструменты придут отдельной веткой, и
#: тогда списки и вызовы ниже проверят и их без правки этого файла.
ВИДЫ_КАТАЛОГА = {spec.kind for spec in TOOLS}


def _виды(имена: set[str]) -> set[str]:
    return {spec.kind for spec in TOOLS if spec.name in имена}


#: Инструменты открытого роли вида, закрытые ей своим действием (D440): указатель
#: прода двигают только админы.
ЗАКРЫТЫЕ_ИНСТРУМЕНТЫ: dict[tuple[str, str], set[str]] = {
    ("HQ", "developer"): {"apply_checklist"},
    # Указатель прода один на всю сеть и в пространстве партнёра не двигается (D460).
    ("RS", "admin"): {"apply_checklist", "uncovered_phrases"},
}
#: Правящие инструменты методики закрыты сотруднику партнёра (читает, но не правит).
ПИШУЩИЕ_МЕТОДИКИ = {spec.name for spec in TOOLS if spec.kind == KIND_CHECKLIST and spec.writes}
ЗАКРЫТЫЕ_ИНСТРУМЕНТЫ[("RS", "auditor")] = ПИШУЩИЕ_МЕТОДИКИ | {
    "apply_checklist",
    "uncovered_phrases",
}


@pytest.mark.parametrize(("арендатор", "роль"), sorted(МАТРИЦА))
def test_tools_list_показывает_ровно_открытые_роли_виды(арендатор: str, роль: str) -> None:
    имена = _список(tenant=арендатор, role=роль)
    закрыто = ЗАКРЫТЫЕ_ИНСТРУМЕНТЫ.get((арендатор, роль), set())

    assert _виды(имена) == set(МАТРИЦА[(арендатор, роль)]) & ВИДЫ_КАТАЛОГА
    assert имена == {
        spec.name
        for spec in TOOLS
        if spec.kind in МАТРИЦА[(арендатор, роль)] and spec.name not in закрыто
    }


def test_каждый_инструмент_сведён_к_действию_матрицы() -> None:
    """Новый инструмент или вид без действия матрицы роняет сборку списка — и этот тест."""
    for spec in TOOLS:
        assert action_of(spec) in ACTION_CODES, spec.name


def test_девелоперу_указатель_прода_отказом_словами() -> None:
    ответ = _вызов("apply_checklist", tenant="HQ", role="developer")

    assert ответ["result"]["isError"] is True
    assert "только админы" in ответ["result"]["content"][0]["text"]


def test_без_роли_tools_list_пуст() -> None:
    """Роли нет — прав нет: `None` никогда не значит «каталог целиком»."""
    assert _список(tenant="HQ") == set()
    assert _список(tenant="HQ", role=None) == set()
    assert _список(tenant="HQ", role=None, may_retract=True) == set()


def _вызов(имя: str, **доступ: Any) -> dict[str, Any]:
    ответ = handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": имя, "arguments": {}},
        },
        **доступ,
    )
    assert ответ is not None
    return ответ


def _первый(вид: str) -> str:
    return next(spec.name for spec in TOOLS if spec.kind == вид)


#: Закрытые клетки матрицы: открытые проверяют тесты самих инструментов.
ЗАКРЫТЫЕ = [
    (арендатор, роль, вид)
    for (арендатор, роль), открыто in sorted(МАТРИЦА.items())
    for вид in ВСЕ_ВИДЫ
    if вид not in открыто and вид in ВИДЫ_КАТАЛОГА
]


@pytest.mark.parametrize(("арендатор", "роль", "вид"), ЗАКРЫТЫЕ)
def test_вызов_закрытого_роли_вида_это_отказ_роли(арендатор: str, роль: str, вид: str) -> None:
    ответ = _вызов(_первый(вид), tenant=арендатор, role=роль, may_retract=False)

    результат = ответ["result"]
    assert результат["isError"] is True
    assert "роли" in результат["content"][0]["text"]


def test_контроль_не_читает_проверки_даже_с_правом_снятия() -> None:
    """Право снятия, пришедшее мимо роли, не открывает то, что роль закрыла."""
    ответ = _вызов("network_summary", tenant="HQ", role="control", may_retract=True)

    assert ответ["result"]["isError"] is True


def test_админу_партнёра_указатель_прода_отказом_словами() -> None:
    ответ = _вызов("apply_checklist", tenant="RS", role="admin")

    assert ответ["result"]["isError"] is True
    assert "применяет только УК" in ответ["result"]["content"][0]["text"]


def test_админу_партнёра_открыты_инструменты_методики_кроме_указателя_прода() -> None:
    """D460: в `tools/list` у админа партнёра есть и чтение, и правка методики."""
    имена = _список(tenant="RS", role="admin")
    методика = {spec.name for spec in TOOLS if spec.kind in (KIND_CHECKLIST, KIND_CHECKLIST_SOURCE)}

    assert методика - {"apply_checklist", "uncovered_phrases"} <= имена
    assert {"checklists", "edit_checklist_item", "publish_checklist_version"} <= имена
    assert "checklist_source" in имена
    assert not {"apply_checklist", "uncovered_phrases"} & имена


def test_сотруднику_партнёра_в_claude_методика_только_на_чтение() -> None:
    """D460: как в вебе — читает, не правит (D342 про правку и занесение остаётся)."""
    имена = _список(tenant="RS", role="auditor")

    assert {"checklists", "checklist_items", "checklist_source"} <= имена
    assert not ПИШУЩИЕ_МЕТОДИКИ & имена
