"""Классы и аннотации инструментов MCP (#1338): инструмент без класса не проходит."""

from __future__ import annotations

from src.mcp.annotations import DESTRUCTIVE, READ, TOOL_CLASSES, annotations_for
from src.mcp.audit import READ_ONLY_TOOLS
from src.mcp.catalogue import TOOLS, as_list


def test_у_каждого_инструмента_есть_класс_и_нет_лишних_записей() -> None:
    имена = {spec.name for spec in TOOLS}

    assert имена - set(TOOL_CLASSES) == set(), "инструмент без класса: допишите в annotations.py"
    assert set(TOOL_CLASSES) - имена == set(), "запись класса для несуществующего инструмента"


def test_инструмент_с_подтверждением_обязан_быть_разрушительным() -> None:
    for spec in TOOLS:
        if spec.confirm_effect:
            assert TOOL_CLASSES[spec.name].kind == DESTRUCTIVE, spec.name


def test_читающий_инструмент_не_идёт_в_журнал_действий() -> None:
    """Журнал берёт чтение из классов (#1340): `import_info_fields` только читает, а в
    каталоге он `writes=True` — раньше его вызовы писались как изменяющие."""
    assert "import_info_fields" in READ_ONLY_TOOLS
    assert {"list_action_plans", "get_action_plan"} <= READ_ONLY_TOOLS
    for имя, класс in TOOL_CLASSES.items():
        assert (класс.kind == READ) == (имя in READ_ONLY_TOOLS), имя


def test_читающий_по_каталогу_инструмент_имеет_класс_read() -> None:
    for spec in TOOLS:
        if not spec.writes:
            assert TOOL_CLASSES[spec.name].kind == READ, spec.name


def test_читающий_инструмент_идемпотентен() -> None:
    for имя, класс in TOOL_CLASSES.items():
        if класс.kind == READ:
            assert класс.idempotent, имя


def test_tools_list_отдаёт_аннотации_каждого_инструмента() -> None:
    for запись in as_list():
        аннотации = запись["annotations"]
        assert isinstance(аннотации, dict)
        assert set(аннотации) == {
            "readOnlyHint",
            "destructiveHint",
            "idempotentHint",
            "openWorldHint",
        }
        assert аннотации["openWorldHint"] is False
        assert not (аннотации["readOnlyHint"] and аннотации["destructiveHint"])


def test_аннотации_по_классам() -> None:
    assert annotations_for("list_inspections") == {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
    assert annotations_for("add_zone") == {
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    }
    assert annotations_for("retract_inspection") == {
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    }
    assert annotations_for("нет_такого") is None
