"""Импорт технических уточнений: полнота источника и сохранение исходной методики."""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZipFile

import pytest

from tools.technical_import import build_import, read_source, write_import

NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


@pytest.fixture
def input_files(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Выдуманные строки, включая ненумерованное продолжение из редактора Word."""
    base = tmp_path / "base"
    shutil.copytree(Path(__file__).parent / "methodology", base)
    document = ET.Element(f"{{{NS}}}document")
    table = ET.SubElement(ET.SubElement(document, f"{{{NS}}}body"), f"{{{NS}}}tbl")
    rows = [
        ["№", "Что проверить", "Уровень", "Код", "Обяз."],
        ["", "Тестовый раздел", "", "", ""],
        ["1", "Тестовый объект целый", "D1", "TEH06", "Обяз."],
        ["", "Тестовое продолжение", "D1", "TEH06", ""],
        ["2", "Тестовое наблюдение", "D0", "INF09", "Доп."],
    ]
    for cells in rows:
        tr = ET.SubElement(table, f"{{{NS}}}tr")
        for value in cells:
            tc = ET.SubElement(tr, f"{{{NS}}}tc")
            p = ET.SubElement(tc, f"{{{NS}}}p")
            run = ET.SubElement(p, f"{{{NS}}}r")
            ET.SubElement(run, f"{{{NS}}}t").text = value
    source = tmp_path / "source.docx"
    with ZipFile(source, "w") as archive:
        archive.writestr("word/document.xml", ET.tostring(document))
    checks = []
    for ref, code, zone in [
        ("1", "TEH06", "dining"),
        ("1.1", "TEH06", "dining"),
        ("2", "INF09", "hot_kitchen"),
    ]:
        checks.append(
            {
                "source_ref": ref,
                "id": "TEST" + ref.replace(".", "_"),
                "item_codes": [code],
                "zones": [zone],
                "title_ru": "Тест",
                "title_en": "Example",
                "guidance_en": "Check the example.",
                "criteria_codes": [code] if code == "TEH06" else [],
            }
        )
    mapping = tmp_path / "mapping.json"
    mapping.write_text(
        json.dumps(
            {
                "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "checks": checks,
                "zone_extensions": {"TEH06": ["dining"]},
            }
        ),
        encoding="utf-8",
    )
    return source, base, mapping


def test_import_preserves_original_and_scoring_and_covers_continuation(
    input_files: tuple[Path, Path, Path],
    tmp_path: Path,
) -> None:
    source, base, mapping = input_files
    original = {file.name: file.read_bytes() for file in base.iterdir() if file.is_file()}
    result = build_import(source, base, mapping, "example 2026-11-26")
    assert [row["source_ref"] for row in read_source(source)] == ["1", "1.1", "2"]
    assert result["summary"]["checks"] == 3
    assert result["summary"]["numbered_rows"] == 2
    assert result["manifest"]["checks"][0]["required"] is True
    assert result["manifest"]["checks"][2]["required"] is False
    output = tmp_path / "edition"
    assert not output.exists(), "Сухой прогон не должен создавать издание"
    write_import(result, base, output)
    assert (output / "scoring.json").read_bytes() == original["scoring.json"]
    assert (output / "zones.csv").read_bytes() == original["zones.csv"]
    assert (output / "route.csv").read_bytes() == original["route.csv"]
    assert {file.name: file.read_bytes() for file in base.iterdir() if file.is_file()} == original
    saved = json.loads((output / "technical_checks.json").read_text())
    assert saved["checks"][1]["source_rows"] == [1]
    assert saved["checks"][0]["guidance_ru"] == "Тестовый объект целый"
    with (output / "checklist.csv").open() as stream:
        changed = next(row for row in csv.DictReader(stream) if row["id"] == "TEH06")
    assert "dining" in changed["zones"].split(",")
    with (base / "checklist.csv").open() as stream:
        prior = next(row for row in csv.DictReader(stream) if row["id"] == "TEH06")
    assert changed["levels"] == prior["levels"]
    assert "technical-checks:TEH06" in (output / "criteria.md").read_text()


def test_missing_or_duplicate_mapping_and_modified_source_are_refused(
    input_files: tuple[Path, Path, Path],
) -> None:
    source, base, mapping = input_files
    raw = json.loads(mapping.read_text())
    original = mapping.read_text()
    raw["checks"].pop(1)
    mapping.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="каждую строку"):
        build_import(source, base, mapping, "example 2026-11-26")
    mapping.write_text(original)
    raw = json.loads(original)
    raw["checks"][1]["source_ref"] = "1"
    mapping.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="каждую строку"):
        build_import(source, base, mapping, "example 2026-11-26")
    mapping.write_text(original)
    with source.open("ab") as stream:
        stream.write(b"changed")
    with pytest.raises(ValueError, match="Отпечаток DOCX"):
        build_import(source, base, mapping, "example 2026-11-26")


def test_existing_output_and_unknown_zone_are_refused(
    input_files: tuple[Path, Path, Path],
    tmp_path: Path,
) -> None:
    source, base, mapping = input_files
    result = build_import(source, base, mapping, "example 2026-11-26")
    with pytest.raises(ValueError, match="уже существует"):
        write_import(result, base, base)
    raw = json.loads(mapping.read_text())
    raw["checks"][0]["zones"] = ["invented_zone"]
    mapping.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="Неизвестные коды или зоны"):
        build_import(source, base, mapping, "example 2026-11-26")
