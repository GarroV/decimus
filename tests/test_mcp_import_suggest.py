"""#1015: подбор пунктов по карте слов черновика — без базы и хранилища методики."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.mcp import import_suggest as sug
from src.mcp.errors import ToolError

КАРТА = """## Грязь

| Что видно | Кандидаты | Зона |
|---|---|---|
| жир на вытяжке | CLN05 | hot_kitchen |
| плесень на стене | CLN06, MGM22 | |
"""

СТРОКИ = [
    {
        "id": "CLN05",
        "kind": "violation",
        "question_ru": "Вытяжка чистая",
        "question_en": "Hood clean",
        "levels": "D1;D2",
        "zones": "hot_kitchen",
    },
    {
        "id": "CLN06",
        "kind": "violation",
        "question_ru": "Стены чистые",
        "question_en": "",
        "levels": "D2",
        "zones": "",
    },
    {
        "id": "CLN07",
        "kind": "violation",
        "question_ru": "Пол чистый",
        "question_en": "",
        "levels": "D1",
        "zones": "hot_kitchen",
    },
    {
        "id": "MGM22",
        "kind": "violation",
        "question_ru": "Другое",
        "question_en": "",
        "levels": "D3",
        "zones": "",
    },
    {
        "id": "INF01",
        "kind": "info",
        "question_ru": "Инфо",
        "question_en": "",
        "levels": "D0",
        "zones": "hot_kitchen",
    },
]
ЗОНЫ = [
    {"code": "hot_kitchen", "name_ru": "Цех А", "name_en": "Area A"},
    {"code": "hall", "name_ru": "Место Б", "name_en": "Place B"},
]


@pytest.fixture
def подмена(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    карта = tmp_path / "photo-cues.md"
    карта.write_text(КАРТА, encoding="utf-8")
    голова = SimpleNamespace(origin="import")
    деталь = SimpleNamespace(inspection=SimpleNamespace(report_lang="ru", checklist_version="v1"))
    monkeypatch.setattr(sug, "_only_import", lambda ident, tenant: (деталь, голова))
    monkeypatch.setattr(sug, "_require_inspection_id", lambda x: x)
    monkeypatch.setattr(sug, "locate", lambda store, tenant, code: object())
    monkeypatch.setattr(sug.store_api, "current_version", lambda s: "v1")
    monkeypatch.setattr(
        sug.store_api,
        "read_items",
        lambda s, version=None, what="items": ЗОНЫ if what == "zones" else СТРОКИ,
    )
    monkeypatch.setattr(sug.store_api, "cues_file", lambda s, version=None: карта)
    monkeypatch.setattr(
        sug.store_api, "read_item", lambda s, code, version=None: {"criteria": f"D1: {code}"}
    )


def _спросить(text: str, zone: str | None = None) -> dict[str, Any]:
    return sug.import_suggest_items(  # type: ignore[return-value]
        tenant="HQ",
        store=object(),
        actor="a",
        inspection_id="i1",
        text=text,
        zone=zone,  # type: ignore[arg-type]
    )


def test_карта_слов_называет_пункт_и_зону(подмена: None) -> None:
    ответ = _спросить("Жир на вытяжке")

    коды = [c["code"] for c in ответ["candidates"]]
    assert коды == ["CLN05"]
    assert ответ["candidates"][0]["criteria"] == "D1: CLN05"
    assert ответ["candidates"][0]["question"] == "Вытяжка чистая"
    assert ответ["zone_guess"] == "hot_kitchen"
    assert ответ["zone_source"] == "cue_map"
    assert ответ["single"] is True
    assert ответ["candidates"][0]["single_level"] is False
    assert "note" not in ответ


def test_служебные_не_предлагаются(подмена: None) -> None:
    ответ = _спросить("плесень на стене")

    assert [c["code"] for c in ответ["candidates"]] == ["CLN06"]
    assert ответ["single"] is True


def test_карта_молчит_без_зоны_пусто_и_честно(подмена: None) -> None:
    ответ = _спросить("что-то непонятное")

    assert ответ["candidates"] == []
    assert ответ["single"] is False
    assert "checklist_items" in ответ["note"]


def test_карта_молчит_зона_даёт_только_свои_пункты_с_пометкой(подмена: None) -> None:
    ответ = _спросить("что-то непонятное", zone="hot_kitchen")

    assert [c["code"] for c in ответ["candidates"]] == ["CLN05", "CLN06", "CLN07"]
    assert {c["source"] for c in ответ["candidates"]} == {"zone"}
    assert "word map found no candidates" in ответ["note"]


def test_неизвестная_зона_отказ(подмена: None) -> None:
    with pytest.raises(ToolError, match="Нет зоны"):
        _спросить("жир на вытяжке", zone="moon")


def test_лайн_это_горячий_цех_по_словам_места(подмена: None) -> None:
    """Слова места сильнее карты: «на лайне» — горячий цех (D207)."""
    ответ = _спросить("температура на лайне 12 градусов")

    assert ответ["zone_guess"] == "hot_kitchen"
    assert ответ["zone_source"] == "words"


def test_без_слов_места_и_без_карты_зона_не_угадывается(подмена: None) -> None:
    assert "zone_guess" not in _спросить("что-то непонятное")
