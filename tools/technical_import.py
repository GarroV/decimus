#!/usr/bin/env python3
"""Импорт уточнений технического обхода из DOCX в отдельное издание методики.

Содержимое методики и таблица сопоставления передаются файлами вне репозитория.
Без --apply команда только проверяет входные файлы и показывает состав изменений.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import shutil
import tempfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from typing import Any
from zipfile import BadZipFile, ZipFile

from defusedxml import ElementTree as SafeET
from defusedxml.common import DefusedXmlException

NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
DATA_FILES = (
    "checklist.csv",
    "zones.csv",
    "scoring.json",
    "criteria.md",
    "route.csv",
    "photo-cues.md",
    "checklist_version.txt",
)
REQUIRED_FILES = DATA_FILES[:4]
CHECK_ID = re.compile(r"^[A-Z][A-Z0-9_-]{1,47}$")


def _cell_text(cell: ET.Element) -> str:
    paragraphs = [
        "".join(t.text or "" for t in p.findall(".//w:t", NS)) for p in cell.findall(".//w:p", NS)
    ]
    return " ".join(" ".join(paragraphs).split()).strip()


def read_source(source: Path) -> list[dict[str, Any]]:
    """Прочитать нумерованные строки и непустые продолжения табличного DOCX."""
    if source.stat().st_size > 20_000_000:
        raise ValueError("DOCX превышает допустимый размер")
    with ZipFile(source) as archive:
        member = archive.getinfo("word/document.xml")
        if member.file_size > 30_000_000:
            raise ValueError("XML документа превышает допустимый размер")
        root = SafeET.fromstring(archive.read(member))
    result: list[dict[str, Any]] = []
    section = ""
    continuation = 0
    last_number: int | None = None
    for tr in root.findall(".//w:tr", NS):
        cells = [_cell_text(tc) for tc in tr.findall("w:tc", NS)]
        if len(cells) < 5:
            continue
        number, text, level, reference, required = cells[:5]
        if not number and text and not any((level, reference, required)):
            section = text
            continue
        if number.isdecimal():
            last_number = int(number)
            continuation = 0
            source_ref = str(last_number)
        elif not number and text and level and last_number is not None:
            continuation += 1
            source_ref = f"{last_number}.{continuation}"
        else:
            continue
        result.append(
            {
                "source_ref": source_ref,
                "source_row": last_number,
                "section_ru": section,
                "guidance_ru": text.lstrip(". "),
                "source_level": level,
                "source_item_reference": reference,
                "source_required": required,
            }
        )
    refs = [row["source_ref"] for row in result]
    if not refs or len(set(refs)) != len(refs):
        raise ValueError("В документе нет контрольных строк или повторяются их номера")
    return result


def _csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        rows = [dict(row) for row in reader]
        return list(reader.fieldnames or []), rows


def _strings(value: Any, field: str, *, nonempty: bool = True) -> list[str]:
    if (
        not isinstance(value, list)
        or (nonempty and not value)
        or any(not isinstance(v, str) or not v.strip() for v in value)
        or len(value) != len(set(value))
    ):
        raise ValueError(f"Некорректный список {field}")
    return value


def build_import(source: Path, base: Path, mapping_path: Path, edition: str) -> dict[str, Any]:
    """Проверить полное сопоставление и собрать изменения без записи на диск."""
    missing = [name for name in REQUIRED_FILES if not (base / name).is_file()]
    if missing:
        raise ValueError(f"В исходной методике нет файлов: {', '.join(missing)}")
    if not re.fullmatch(r"[A-Za-z0-9_-]+ \d{4}-\d{2}-\d{2}", edition):
        raise ValueError("Издание задаётся как 'name YYYY-MM-DD'")
    source_rows = read_source(source)
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    if mapping.get("source_sha256") != source_hash:
        raise ValueError("Отпечаток DOCX не совпал с таблицей сопоставления")
    entries = mapping.get("checks")
    if not isinstance(entries, list) or not entries:
        raise ValueError("В таблице сопоставления нет checks")
    mapped = {str(entry.get("source_ref")): entry for entry in entries}
    source_refs = {row["source_ref"] for row in source_rows}
    if len(mapped) != len(entries) or set(mapped) != source_refs:
        raise ValueError("Таблица сопоставления должна покрывать каждую строку DOCX ровно один раз")
    fields, checklist = _csv(base / "checklist.csv")
    by_code = {row["id"]: row for row in checklist if row.get("id")}
    _, zones = _csv(base / "zones.csv")
    known_zones = {row["code"] for row in zones if row.get("code")}
    extended: dict[str, list[str]] = {}
    for code, extra_zones in mapping.get("zone_extensions", {}).items():
        if code not in by_code:
            raise ValueError(f"Расширение зон неизвестного пункта: {code}")
        extra_zones = _strings(extra_zones, f"zones:{code}")
        if not set(extra_zones) <= known_zones:
            raise ValueError(f"Неизвестная зона расширения: {code}")
        row = by_code[code]
        old = row.get("zones", "").split(",")
        if "*" not in old:
            added = [zone for zone in extra_zones if zone not in old]
            if added:
                row["zones"] = ",".join([*old, *added])
                extended[code] = added
    checks = []
    criteria_notes: dict[str, list[str]] = defaultdict(list)
    ids: set[str] = set()
    for row in source_rows:
        entry = mapped[row["source_ref"]]
        check_id = entry.get("id", "")
        if not CHECK_ID.fullmatch(check_id) or check_id in ids:
            raise ValueError(f"Неверный или повторный id: {check_id}")
        ids.add(check_id)
        codes = _strings(entry.get("item_codes"), f"item_codes:{check_id}")
        places = _strings(entry.get("zones"), f"zones:{check_id}")
        if not set(codes) <= set(by_code) or not set(places) <= known_zones:
            raise ValueError(f"Неизвестные коды или зоны: {check_id}")
        for zone in places:
            if not any(
                "*" in by_code[code].get("zones", "").split(",")
                or zone in by_code[code].get("zones", "").split(",")
                for code in codes
            ):
                raise ValueError(f"Ни один пункт {check_id} не применим в зоне {zone}")
        for field in ("title_ru", "title_en", "guidance_en"):
            if not isinstance(entry.get(field), str) or not entry[field].strip():
                raise ValueError(f"Нет текста {field}:{check_id}")
        required = entry.get("required", row["source_required"].startswith("Обяз"))
        if not isinstance(required, bool):
            raise ValueError(f"Неверный required:{check_id}")
        check = {
            **row,
            "id": check_id,
            "source_rows": [row["source_row"]],
            "item_codes": codes,
            "zones": places,
            "required": required,
            "title_ru": entry["title_ru"],
            "title_en": entry["title_en"],
            "guidance_en": entry["guidance_en"],
            "countries": _strings(entry.get("countries", []), "countries", nonempty=False),
        }
        for field in ("kind", "requires_photo", "applicability_ru", "applicability_en", "seasonal"):
            if field in entry:
                check[field] = entry[field]
        checks.append(check)
        for code in entry.get("criteria_codes", codes):
            if code not in codes:
                raise ValueError(f"Критерии {code} не связаны с {check_id}")
            note = entry.get("criteria_ru", row["guidance_ru"])
            criteria_notes[code].append(f"- [{check_id}; строка {row['source_ref']}] {note}")
    criteria = (base / "criteria.md").read_text(encoding="utf-8")
    for code, notes in criteria_notes.items():
        marker = f"<!-- technical-checks:{code} -->"
        if marker in criteria:
            raise ValueError(
                "В исходную методику уже внесены технические уточнения; выберите исходное издание"
            )
        heading = re.search(rf"^## {re.escape(code)}\s*$", criteria, re.MULTILINE)
        if heading is None:
            raise ValueError(f"Нет раздела критериев {code}")
        following = re.search(r"^## ", criteria[heading.end() :], re.MULTILINE)
        at = heading.end() + following.start() if following else len(criteria)
        supplement = (
            f"\n{marker}\n### Технический осмотр\n\n"
            "Уточнения объектов осмотра. Класс нарушения определяется действующими критериями "
            "пункта и допустимыми уровнями чек-листа; уточнения не вводят новых вычетов.\n\n"
            + "\n".join(notes)
            + "\n\n"
        )
        criteria = criteria[:at].rstrip() + "\n" + supplement + criteria[at:]
    output_csv = io.StringIO(newline="")
    writer = csv.DictWriter(output_csv, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(checklist)
    manifest = {
        "version": 1,
        "source_name": source.name,
        "source_sha256": source_hash,
        "source_rows_count": len(source_rows),
        "source_numbered_rows_count": len({row["source_row"] for row in source_rows}),
        "checks": checks,
    }
    provenance = {
        "source_sha256": source_hash,
        "mapping_sha256": hashlib.sha256(mapping_path.read_bytes()).hexdigest(),
        "base_files_sha256": {
            name: hashlib.sha256((base / name).read_bytes()).hexdigest()
            for name in DATA_FILES
            if (base / name).is_file()
        },
        "edition": edition,
        "conflicts": mapping.get("conflicts", []),
    }
    return {
        "manifest": manifest,
        "provenance": provenance,
        "contents": {
            "checklist.csv": output_csv.getvalue(),
            "criteria.md": criteria,
            "checklist_version.txt": edition + "\n",
            "technical_checks.json": json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            "technical_import_provenance.json": json.dumps(provenance, ensure_ascii=False, indent=2)
            + "\n",
        },
        "summary": {
            "checks": len(checks),
            "numbered_rows": manifest["source_numbered_rows_count"],
            "required": sum(c["required"] for c in checks),
            "zone_extensions": extended,
            "criteria_sections": len(criteria_notes),
            "new_scored_items": 0,
            "scoring_changed": False,
            "conflicts": mapping.get("conflicts", []),
        },
    }


def write_import(result: dict[str, Any], base: Path, output: Path) -> None:
    """Создать новое издание атомарно; существующие каталоги не перезаписываются."""
    if output.exists() or base.resolve() == output.resolve():
        raise ValueError("Выходной каталог уже существует; исходное издание не перезаписывается")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".technical-import-", dir=output.parent))
    try:
        for name in DATA_FILES:
            if (base / name).is_file():
                shutil.copyfile(base / name, staging / name)
        for name, content in result["contents"].items():
            (staging / name).write_text(content, encoding="utf-8")
        staging.rename(output)
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--base", required=True, type=Path)
    parser.add_argument("--mapping", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--edition", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        result = build_import(args.source, args.base, args.mapping, args.edition)
        if args.apply:
            write_import(result, args.base, args.output)
        print(
            json.dumps({"applied": args.apply, **result["summary"]}, ensure_ascii=False, indent=2)
        )
    except (ValueError, OSError, BadZipFile, ET.ParseError, DefusedXmlException, KeyError) as exc:
        parser.exit(2, f"Импорт не выполнен: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
