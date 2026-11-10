"""#1619: текст методики на языке печати: из издания проверки, из действующего, английский.

Проверка, пройденная по старому изданию, печатается на турецком, а турецких колонок в её
издании нет. Правило отката одно на весь движок (`audit.py: resolve_text`) и такое:

1. `*_<язык>` из самого издания проверки, если заполнено;
2. иначе та же строка по КОДУ из действующего издания (`CHECKLIST_FALLBACK_DIR`);
3. иначе английский (в том же порядке: сначала издание проверки, потом действующее);
4. отчёт при этом не падает.

Тест гоняет настоящий движок подпроцессом, как продукт, на копии синтетической методики.
"""

from __future__ import annotations

import csv
import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from conftest import AUDIT, Run, run_engine

ПУНКТ = "PRD01"
ЗОНА = "fridge"
FALLBACK_VAR = "CHECKLIST_FALLBACK_DIR"


def _rewrite(path: Path, edit: Callable[[list[dict[str, str]]], None], extra: list[str]) -> None:
    """Дописать колонки `extra` в CSV и дать `edit` заполнить их."""
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fields = [*(reader.fieldnames or []), *extra]
        rows = [dict(r) for r in reader]
    for row in rows:
        for name in extra:
            row.setdefault(name, "")
    edit(rows)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _издание_с_турецким(src: Path, dst: Path, *, вопрос: str, зона: str, метка: str) -> Path:
    """Копия методики, где у пункта PRD01, зоны и подписи оценки есть турецкий."""
    shutil.copytree(src, dst)

    def checklist(rows: list[dict[str, str]]) -> None:
        for row in rows:
            if row["id"] == ПУНКТ:
                row["question_tr"], row["process_tr"] = вопрос, "Hazırlıklar"

    def zones(rows: list[dict[str, str]]) -> None:
        for row in rows:
            if row["code"] == ЗОНА:
                row["name_tr"] = зона

    _rewrite(dst / "checklist.csv", checklist, ["process_tr", "question_tr"])
    _rewrite(dst / "zones.csv", zones, ["name_tr"])
    cfg: dict[str, Any] = json.loads((dst / "scoring.json").read_text(encoding="utf-8"))
    for rule in cfg["grades"]["rules"]:
        rule["label_tr"] = метка
    cfg["grades"]["fallback"]["label_tr"] = метка
    (dst / "scoring.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    return dst


def _score(
    started: Callable[..., Run], workdir: Path, data: Path, fallback: Path | None
) -> dict[str, Any]:
    r = started("add", "--qid", ПУНКТ, "--level", "D1", "--zone", ЗОНА)
    assert r.code == 0, r.text
    env = {} if fallback is None else {FALLBACK_VAR: str(fallback)}
    r = run_engine(
        AUDIT,
        "score",
        "--json",
        cwd=workdir,
        state=workdir / "inspection.json",
        env_extra=env,
        data_dir=data,
    )
    assert r.code == 0, r.text
    return json.loads(r.out)  # type: ignore[no-any-return]


def test_нет_перевода_нигде_значит_английский_а_не_русский(
    started: Callable[..., Run], workdir: Path, data_copy: Path
) -> None:
    res = _score(started, workdir, data_copy, None)
    item = res["findings"][0]
    assert item["question_tr"] == item["question_en"] != item["question_ru"]
    assert res["zones"][ЗОНА]["name_tr"] == res["zones"][ЗОНА]["name_en"]
    assert res["grade_label_tr"] == res["grade_label_en"]


def test_перевод_берётся_из_действующего_издания_по_коду(
    started: Callable[..., Run], workdir: Path, data_copy: Path, tmp_path: Path
) -> None:
    действующее = _издание_с_турецким(
        data_copy,
        tmp_path / "current",
        вопрос="Hazırlık etiketi var",
        зона="Soğuk dolap",
        метка="Standart",
    )
    res = _score(started, workdir, data_copy, действующее)
    item = res["findings"][0]
    assert item["question_tr"] == "Hazırlık etiketi var"
    assert item["process_tr"] == "Hazırlıklar"
    assert res["zones"][ЗОНА]["name_tr"] == "Soğuk dolap"
    assert res["grade_label_tr"] == "Standart"
    # Остальные зоны, которых в действующем издании на турецком тоже нет, — английский.
    other = next(code for code in res["zones"] if code != ЗОНА)
    assert res["zones"][other]["name_tr"] == res["zones"][other]["name_en"]


def test_собственный_турецкий_издания_проверки_главнее_действующего(
    started: Callable[..., Run], workdir: Path, data_copy: Path, tmp_path: Path
) -> None:
    своё = _издание_с_турецким(
        data_copy, tmp_path / "own", вопрос="Kendi sorusu", зона="Kendi bölgesi", метка="Kendi"
    )
    действующее = _издание_с_турецким(
        data_copy, tmp_path / "current", вопрос="Yeni soru", зона="Yeni bölge", метка="Yeni"
    )
    res = _score(started, workdir, своё, действующее)
    assert res["findings"][0]["question_tr"] == "Kendi sorusu"
    assert res["zones"][ЗОНА]["name_tr"] == "Kendi bölgesi"
    assert res["grade_label_tr"] == "Kendi"


def test_битое_или_отсутствующее_действующее_издание_не_роняет_отчёт(
    started: Callable[..., Run], workdir: Path, data_copy: Path, tmp_path: Path
) -> None:
    битое = tmp_path / "broken"
    битое.mkdir()
    (битое / "checklist.csv").write_text("id\n\x00\xff", encoding="utf-8")
    (битое / "scoring.json").write_text("{не json", encoding="utf-8")
    res = _score(started, workdir, data_copy, битое)
    assert res["findings"][0]["question_tr"] == res["findings"][0]["question_en"]
    assert res["pct"] == 99.5
