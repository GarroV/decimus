"""#1015, #1033: подбор пунктов по карте слов (откат) и ответ `import_suggest_items` — без базы."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.domain.models import Zone
from src.mcp import import_draft as dr
from src.mcp.errors import ToolError
from src.recognize.cues import load_cues

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
def черновик(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dr.Draft:
    карта = tmp_path / "photo-cues.md"
    карта.write_text(КАРТА, encoding="utf-8")
    monkeypatch.setattr(
        dr.store_api, "read_item", lambda s, code, version=None: {"criteria": f"D1: {code}"}
    )
    return dr.Draft(
        ident="i1",
        history=False,
        version="v1",
        lang="ru",
        store=object(),  # type: ignore[arg-type]
        rows=СТРОКИ,
        zones=[
            Zone(code=z["code"], title_ru=z["name_ru"], title_en=z["name_en"], share_pct=0.0)
            for z in ЗОНЫ
        ],
        cues=load_cues(карта, chat_id=None),
        data_dir=tmp_path,
    )


def _спросить(draft: dr.Draft, text: str, zone: str | None = None) -> dict[str, Any]:
    кандидаты, угадана, однозначно = dr.word_map_suggest(draft, text, dr.check_zone(draft, zone))
    return {"candidates": кандидаты, "single": однозначно, **угадана}


def test_карта_слов_называет_пункт_и_зону(черновик: dr.Draft) -> None:
    ответ = _спросить(черновик, "Жир на вытяжке")

    коды = [c["code"] for c in ответ["candidates"]]
    assert коды == ["CLN05"]
    assert ответ["candidates"][0]["criteria"] == "D1: CLN05"
    assert ответ["candidates"][0]["question"] == "Вытяжка чистая"
    assert ответ["zone_guess"] == "hot_kitchen"
    assert ответ["zone_source"] == "cue_map"
    assert ответ["single"] is True
    assert ответ["candidates"][0]["single_level"] is False


def test_служебные_не_предлагаются(черновик: dr.Draft) -> None:
    ответ = _спросить(черновик, "плесень на стене")

    assert [c["code"] for c in ответ["candidates"]] == ["CLN06"]
    assert ответ["single"] is True


def test_карта_молчит_без_зоны_пусто_и_честно(черновик: dr.Draft) -> None:
    ответ = _спросить(черновик, "что-то непонятное")

    assert ответ["candidates"] == []
    assert ответ["single"] is False


def test_карта_молчит_зона_даёт_только_свои_пункты_с_пометкой(черновик: dr.Draft) -> None:
    ответ = _спросить(черновик, "что-то непонятное", zone="hot_kitchen")

    assert [c["code"] for c in ответ["candidates"]] == ["CLN05", "CLN06", "CLN07"]
    assert {c["source"] for c in ответ["candidates"]} == {"zone"}


def test_неизвестная_зона_отказ(черновик: dr.Draft) -> None:
    with pytest.raises(ToolError, match="Нет зоны"):
        _спросить(черновик, "жир на вытяжке", zone="moon")


def test_лайн_это_горячий_цех_по_словам_места(черновик: dr.Draft) -> None:
    """Слова места сильнее карты: «на лайне» — горячий цех (D207)."""
    ответ = _спросить(черновик, "температура на лайне 12 градусов")

    assert ответ["zone_guess"] == "hot_kitchen"
    assert ответ["zone_source"] == "words"


def test_без_слов_места_и_без_карты_зона_не_угадывается(черновик: dr.Draft) -> None:
    assert "zone_guess" not in _спросить(черновик, "что-то непонятное")
