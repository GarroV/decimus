"""Пределы загрузки исторических проверок (D305) — ресурсы под агентом.

Инструменты загрузки зовёт LLM-агент, и зациклившийся агент повторит вызов
сколько угодно раз. Каждый предел здесь — отказ с понятной причиной до работы:
кадр — по длине строки base64 ДО разбора, записи и кадры — под замком
черновика, черновики — под замком пространства, поля — по длине и в
обработчике, и в слое базы.
"""

from __future__ import annotations

import base64
import io
from typing import Any

import pytest
from conftest import requires_db

psycopg = pytest.importorskip("psycopg")

from test_db_imports import (  # noqa: E402, F401 — фикстуры набора загрузки
    КТО,
    Склад,
    _добавить,
    _черновик,
    сеть,
    хранилище,
)

from src.db import imports as db  # noqa: E402
from src.db.errors import HistoryImportError  # noqa: E402
from src.mcp import imports  # noqa: E402
from src.mcp.checklist import Store  # noqa: E402
from src.mcp.errors import ToolError  # noqa: E402

# Пространство с точкой и ролью администратора — каждому тесту файла.
pytestmark = [requires_db, pytest.mark.usefixtures("сеть")]


def _кадр(цвет: int) -> str:
    from PIL import Image

    буфер = io.BytesIO()
    Image.new("RGB", (32, 24), (цвет, 30, 30)).save(буфер, format="PNG")
    return base64.b64encode(буфер.getvalue()).decode()


def _приложить(склад: Store, ident: str, n: int, кадр: str) -> Any:
    return imports.import_add_photo(
        tenant="HQ",
        store=склад,
        actor=КТО,
        inspection_id=ident,
        n=n,
        image_base64=кадр,
        mime="image/png",
    )


def test_строка_base64_сверх_предела_отклоняется_до_разбора(
    хранилище: Store,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange — разбор base64 запрещён: дойти до него значит проверить поздно.
    склад = Склад()
    monkeypatch.setattr(imports, "_photo_storage", lambda: склад)
    ident = _черновик(хранилище)
    _добавить(хранилище, ident, "CLN03", "D1", "hot_kitchen")

    def _нельзя(*_a: Any, **_k: Any) -> bytes:
        raise AssertionError("base64 разобран до проверки длины")

    monkeypatch.setattr(imports.base64, "b64decode", _нельзя)

    # Act / Assert
    with pytest.raises(ToolError, match="КБ"):
        # Одни переносы строк: после чистки строка пуста, и отказать до
        # разбора может только предел сырой длины.
        _приложить(хранилище, ident, 1, "\n" * (imports.MAX_PHOTO_B64_RAW + 1))
    with pytest.raises(ToolError, match="КБ"):
        _приложить(хранилище, ident, 1, "A" * (imports.MAX_PHOTO_B64_CHARS + 4))
    assert склад.объекты == {}


def test_кадров_у_записи_не_больше_предела(
    хранилище: Store,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    склад = Склад()
    monkeypatch.setattr(imports, "_photo_storage", lambda: склад)
    monkeypatch.setattr(db, "MAX_PHOTOS_PER_FINDING", 1)
    ident = _черновик(хранилище)
    _добавить(хранилище, ident, "CLN03", "D1", "hot_kitchen")
    _приложить(хранилище, ident, 1, _кадр(10))

    with pytest.raises(ToolError, match="уже 1 кадров"):
        _приложить(хранилище, ident, 1, _кадр(20))
    assert len(склад.объекты) == 1


def test_кадров_у_черновика_не_больше_предела(
    хранилище: Store,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    склад = Склад()
    monkeypatch.setattr(imports, "_photo_storage", lambda: склад)
    monkeypatch.setattr(db, "MAX_PHOTOS_PER_INSPECTION", 1)
    ident = _черновик(хранилище)
    _добавить(хранилище, ident, "CLN03", "D1", "hot_kitchen")
    _добавить(хранилище, ident, "CLN05", "D1", "dining")
    _приложить(хранилище, ident, 1, _кадр(10))

    with pytest.raises(ToolError, match="У черновика уже 1 кадров"):
        _приложить(хранилище, ident, 2, _кадр(20))
    assert len(склад.объекты) == 1


def test_записей_в_черновике_не_больше_предела(
    хранилище: Store,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(db, "MAX_FINDINGS", 1)
    ident = _черновик(хранилище)
    _добавить(хранилище, ident, "CLN03", "D1", "hot_kitchen")

    with pytest.raises(ToolError, match="уже 1 записей"):
        _добавить(хранилище, ident, "CLN05", "D1", "dining")
    вид = imports.import_get_inspection(
        tenant="HQ", store=хранилище, actor=КТО, inspection_id=ident
    )
    assert len(вид["findings"]) == 1


def test_неподтверждённых_черновиков_не_больше_предела(
    хранилище: Store,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(db, "MAX_DRAFTS", 1)
    _черновик(хранилище)

    with pytest.raises(ToolError, match="неподтверждённых черновиков"):
        _черновик(хранилище)


def test_перечень_черновиков_не_длиннее_предела_даже_по_просьбе(
    хранилище: Store,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _черновик(хранилище)
    _черновик(хранилище, date="2024-03-16")
    monkeypatch.setattr(db, "MAX_DRAFTS", 1)

    assert len(db.list_drafts(tenant="HQ", limit=10**6)) == 1


@pytest.mark.parametrize(
    ("поле", "предел"),
    [
        ("unit", imports.MAX_UNIT),
        ("auditor", imports.MAX_AUDITOR),
        ("source_ref", imports.MAX_SOURCE_REF),
    ],
)
def test_длинное_поле_шапки_отклоняется(
    поле: str,
    предел: int,
    хранилище: Store,  # noqa: F811
) -> None:
    with pytest.raises(ToolError, match=f"{поле} длиннее {предел}"):
        _черновик(хранилище, **{поле: "x" * (предел + 1)})


@pytest.mark.parametrize("поле", ["text", "comment"])
def test_длинная_формулировка_отклоняется(
    поле: str,
    хранилище: Store,  # noqa: F811
) -> None:
    ident = _черновик(хранилище)
    with pytest.raises(ToolError, match=f"{поле} длиннее {imports.MAX_TEXT}"):
        _добавить(хранилище, ident, "CLN03", "D1", "hot_kitchen", **{поле: "x" * 1001})


def test_слой_базы_держит_длину_сам(
    хранилище: Store,  # noqa: F811
) -> None:
    """Слой базы зовут не только из MCP: предел формулировки стоит и в нём."""
    ident = _черновик(хранилище)

    def _движок(_detail: Any) -> Any:
        raise AssertionError("движок вызван до проверки длины")

    with pytest.raises(HistoryImportError, match="text длиннее"):
        db.add_finding(
            ident,
            tenant="HQ",
            wording=db.Wording(text="x" * (db.MAX_WORDING + 1), comment=None),
            apply=_движок,
        )
