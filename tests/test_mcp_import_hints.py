"""#563: отказ движка в загрузке называет инструменты MCP, а не команды audit.py."""

from __future__ import annotations

from src.mcp.imports import mcp_hints

ОТКАЗ = (
    "CLN05 в зоне hot_kitchen уже зафиксировано — запись #3. "
    "Доснимите фото (audit.py photo 3 --add ...) или поправьте её (audit.py edit --n 3 ...)"
)


def test_подсказки_движка_становятся_инструментами() -> None:
    текст = mcp_hints(ОТКАЗ)

    assert "audit.py" not in текст
    assert "import_add_photo к записи #3" in текст
    assert "import_edit_finding, n=3" in текст


def test_незнакомая_команда_движка_убирается() -> None:
    assert mcp_hints("Не вышло (audit.py score --json)") == "Не вышло"


def test_отказ_без_подсказок_не_меняется() -> None:
    assert mcp_hints("Пункт не найден") == "Пункт не найден"
