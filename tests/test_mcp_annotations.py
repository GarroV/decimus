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


#: Читает, но журнал (`audit.READ_ONLY_TOOLS`) осторожно числит пишущим: лишняя строка
#: журнала дешевле пропущенного действия. Новое имя сюда — только после чтения обработчика.
ЧИТАЕТ_НО_ЖУРНАЛ_ПИШЕТ = frozenset({"import_info_fields"})


def test_класс_read_совпадает_с_тем_что_другие_карты_считают_чтением() -> None:
    """`writes=False` и список журнала (`audit.READ_ONLY_TOOLS`) — другие карты того же
    свойства. Читающий по ним обязан быть `read`; `read` без их согласия — только из
    явного списка исключений. Иначе запись, названная чтением, лишила бы клиента
    подтверждения (`readOnlyHint`)."""
    for spec in TOOLS:
        читает = not spec.writes or spec.name in READ_ONLY_TOOLS
        класс_read = TOOL_CLASSES[spec.name].kind == READ
        if читает:
            assert класс_read, spec.name
        else:
            assert _read_допустим(spec.name, класс_read), spec.name


def _read_допустим(имя: str, класс_read: bool) -> bool:
    return not класс_read or имя in ЧИТАЕТ_НО_ЖУРНАЛ_ПИШЕТ


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
