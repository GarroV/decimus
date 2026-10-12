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

from src.mcp.catalogue import (
    KIND_CHECKLIST,
    KIND_CHECKLIST_SOURCE,
    KIND_IMPORT,
    KIND_INSPECTIONS,
    KIND_RATINGS,
    KIND_RETRACTION,
    TOOLS,
)
from src.mcp.policy import permits
from src.mcp.rpc import handle

ВСЕ_ВИДЫ = (
    KIND_INSPECTIONS,
    KIND_CHECKLIST_SOURCE,
    KIND_CHECKLIST,
    KIND_IMPORT,
    KIND_RATINGS,
    KIND_RETRACTION,
)

#: Матрица из спеки `docs/superpowers/specs/2026-10-12-claude-connect-design.md`,
#: раздел «Права по роли». Клетка «да, если HQ в MCP_CHECKLIST_TENANTS» здесь
#: «да»: условие настройки держит прежний заслон (`rpc._call_tool`), а роль
#: решает только то, что решает роль.
МАТРИЦА: dict[tuple[str, str], frozenset[str]] = {
    ("HQ", "superadmin"): frozenset(
        {KIND_INSPECTIONS, KIND_CHECKLIST_SOURCE, KIND_CHECKLIST, KIND_IMPORT, KIND_RATINGS}
    ),
    ("HQ", "admin"): frozenset(
        {KIND_INSPECTIONS, KIND_CHECKLIST_SOURCE, KIND_CHECKLIST, KIND_IMPORT, KIND_RATINGS}
    ),
    ("HQ", "auditor"): frozenset({KIND_INSPECTIONS, KIND_CHECKLIST_SOURCE}),
    ("HQ", "control"): frozenset({KIND_RATINGS}),
    ("RS", "admin"): frozenset({KIND_INSPECTIONS}),
    ("RS", "auditor"): frozenset({KIND_INSPECTIONS}),
}


@pytest.mark.parametrize(("арендатор", "роль"), sorted(МАТРИЦА))
@pytest.mark.parametrize("вид", ВСЕ_ВИДЫ)
def test_клетка_матрицы(арендатор: str, роль: str, вид: str) -> None:
    ожидание = вид in МАТРИЦА[(арендатор, роль)]

    assert permits(роль, арендатор, вид) is ожидание, (
        f"{роль}@{арендатор} × {вид}: ожидалось {'да' if ожидание else 'нет'}"
    )


@pytest.mark.parametrize("роль", ["superadmin", "admin", "auditor", "control"])
def test_снятие_проверки_через_oauth_закрыто_всем(роль: str) -> None:
    assert permits(роль, "HQ", KIND_RETRACTION) is False


def test_старый_код_уk_переводится() -> None:
    """`default` — прежний код УК (D234): права те же, что у `HQ`."""
    assert permits("admin", "default", KIND_IMPORT) is True


@pytest.mark.parametrize("роль", ["control", "superadmin"])
def test_роли_только_уk_у_партнёра_не_дают_больше_чтения(роль: str) -> None:
    """control/superadmin бывают только в HQ; если такая строка всё же есть у
    партнёра — это партнёр, и открыто ему ровно чтение своих проверок."""
    открыто = {вид for вид in ВСЕ_ВИДЫ if permits(роль, "RS", вид)}

    assert открыто == {KIND_INSPECTIONS}


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


def _виды(имена: set[str]) -> set[str]:
    return {spec.kind for spec in TOOLS if spec.name in имена}


@pytest.mark.parametrize(("арендатор", "роль"), sorted(МАТРИЦА))
def test_tools_list_показывает_ровно_открытые_роли_виды(арендатор: str, роль: str) -> None:
    имена = _список(tenant=арендатор, role=роль)

    assert _виды(имена) == set(МАТРИЦА[(арендатор, роль)])
    assert имена == {spec.name for spec in TOOLS if spec.kind in МАТРИЦА[(арендатор, роль)]}


def test_без_роли_tools_list_как_раньше() -> None:
    """Двери бота и `.env` роли не знают: каталог целиком, как до D417."""
    assert _список(tenant="HQ") == {spec.name for spec in TOOLS}
    assert _список(tenant="HQ", role=None) == {spec.name for spec in TOOLS}


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
    if вид not in открыто
]


@pytest.mark.parametrize(("арендатор", "роль", "вид"), ЗАКРЫТЫЕ)
def test_вызов_закрытого_роли_вида_это_отказ_роли(арендатор: str, роль: str, вид: str) -> None:
    ответ = _вызов(_первый(вид), tenant=арендатор, role=роль, may_retract=True)

    результат = ответ["result"]
    assert результат["isError"] is True
    assert "роли" in результат["content"][0]["text"]


def test_контроль_не_читает_проверки_даже_с_правом_снятия() -> None:
    """Право снятия, пришедшее мимо роли, не открывает то, что роль закрыла."""
    ответ = _вызов("network_summary", tenant="HQ", role="control", may_retract=True)

    assert ответ["result"]["isError"] is True
