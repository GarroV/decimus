"""D739: инструменты MCP `batch_letter` и `save_batch_letter`.

То же правило выбора, что на сайте, и то же «своё пространство»: инструмент записи его не
обходит, а чужая проверка отвечает как несуществующая. Базу подменяет граница модуля.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytest
from mcp_checklist_harness import build_edition, build_methodology
from test_batch_letter import ВЕРСИЯ, ТЕНАНТ, _проверка

from src.db import batch_letters as store
from src.db.models import InspectionDetail
from src.mcp import batch_letter as tool
from src.mcp.errors import ToolError
from src.report.letters import Papers


@pytest.fixture
def стенд(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, list[Any]]:
    build_edition(tmp_path / "store" / "versions" / ВЕРСИЯ)
    build_methodology(tmp_path / "live")
    monkeypatch.setattr(
        tool, "sources", lambda: Papers(live=tmp_path / "live", store=tmp_path / "store")
    )
    базa: dict[str, InspectionDetail] = {
        d.inspection.id: d
        for d in (
            _проверка(1, day=date(2026, 11, 2)),
            _проверка(2, day=date(2026, 11, 4)),
            _проверка(3, day=date(2026, 10, 1)),
            _проверка(4, unit_country="GE"),
            _проверка(5, tenant_code="чужой"),
        )
    }

    def details(ids: list[str], tenant: str) -> list[InspectionDetail]:
        out = []
        for i in ids:
            d = базa.get(i)
            if d is None or d.inspection.tenant_code != tenant:
                raise ToolError(f"{tool.NO_SUCH_INSPECTION}: {i}")
            out.append(d)
        return out

    журнал: dict[str, list[Any]] = {"saved": [], "latest": []}
    monkeypatch.setattr(tool, "_details", details)
    monkeypatch.setattr(store, "latest_for_set", lambda *_a, **_k: None)
    monkeypatch.setattr(store, "count_for_set", lambda *_a, **_k: 1)

    def save(ids: Any, **поля: Any) -> store.SavedBatchLetter:
        журнал["saved"].append((tuple(ids), поля))
        return store.SavedBatchLetter(
            id="x",
            country=поля["country"],
            body=поля["body"],
            lang=поля["lang"],
            saved_by=поля["saved_by"],
            created_at=datetime(2026, 11, 9, 12, 0),
            inspection_ids=tuple(ids),
        )

    monkeypatch.setattr(store, "save_batch_letter", save)
    return журнал


def _id(n: int) -> str:
    return f"{n:08d}-1111-1111-1111-111111111111"


def test_собирает_письмо_из_записанного(стенд: Any) -> None:
    ответ = tool.batch_letter(tenant=ТЕНАНТ, ids=[_id(1), _id(2)], lang="en")

    assert ответ["source"] == "template"
    assert ответ["score_verified"] is True
    assert "Белград-1 | 02.11.2026 | 99.5% | A" in str(ответ["letter"])


def test_сохранённое_письмо_отдаётся_вместо_заготовки(
    стенд: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    письмо = store.SavedBatchLetter(
        id="x", country="RS", body="Согласованный текст", lang="ru", saved_by="u",
        created_at=datetime(2026, 11, 9, 12, 0), inspection_ids=(_id(1), _id(2)),
    )  # fmt: skip
    monkeypatch.setattr(store, "latest_for_set", lambda *_a, **_k: письмо)

    ответ = tool.batch_letter(tenant=ТЕНАНТ, ids=[_id(1), _id(2)])
    свежее = tool.batch_letter(tenant=ТЕНАНТ, ids=[_id(1), _id(2)], fresh=True)

    assert ответ["source"] == "saved" and ответ["letter"] == "Согласованный текст"
    assert свежее["source"] == "template"


@pytest.mark.parametrize(
    ("ids", "фраза"),
    [
        ([1, 3], "не больше 7"),
        ([1, 4], "разным странам"),
        ([1], "не меньше 2"),
    ],
)
def test_нарушение_правила_отказ_с_причиной_а_не_письмо(
    стенд: Any, ids: list[int], фраза: str
) -> None:
    with pytest.raises(ToolError, match=фраза):
        tool.batch_letter(tenant=ТЕНАНТ, ids=[_id(i) for i in ids])


def test_чужая_проверка_отвечает_как_несуществующая(стенд: Any) -> None:
    with pytest.raises(ToolError, match="no inspection found"):
        tool.batch_letter(tenant=ТЕНАНТ, ids=[_id(1), _id(5)])


def test_запись_кладёт_письмо_с_автором_из_токена_и_страной(стенд: Any) -> None:
    ответ = tool.save_batch_letter(
        tenant=ТЕНАНТ, actor="web:director", ids=[_id(1), _id(2)], text="Письмо"
    )

    ((_ids, поля),) = стенд["saved"]
    assert ответ["saved"] is True and ответ["version"] == 1
    assert поля["saved_by"] == "director" and поля["country"] == "RS"
    assert поля["lang"] == "ru" and поля["tenant"] == ТЕНАНТ


def test_запись_не_обходит_правило_выбора(стенд: Any) -> None:
    with pytest.raises(ToolError, match="не больше 7"):
        tool.save_batch_letter(tenant=ТЕНАНТ, actor="u", ids=[_id(1), _id(3)], text="Письмо")
    with pytest.raises(ToolError, match="no inspection found"):
        tool.save_batch_letter(tenant=ТЕНАНТ, actor="u", ids=[_id(1), _id(5)], text="Письмо")
    assert стенд["saved"] == []


def test_пустой_текст_и_чужой_язык_отказ(стенд: Any) -> None:
    with pytest.raises(ToolError, match="нет текста"):
        tool.save_batch_letter(tenant=ТЕНАНТ, actor="u", ids=[_id(1), _id(2)], text="  ")
    with pytest.raises(ToolError, match="не поддерживается"):
        tool.save_batch_letter(tenant=ТЕНАНТ, actor="u", ids=[_id(1), _id(2)], text="т", lang="de")


def test_ids_не_список_отказ(стенд: Any) -> None:
    with pytest.raises(ToolError):
        tool.batch_letter(tenant=ТЕНАНТ, ids="не список")
