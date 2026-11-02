"""Предписание по проверке: отбор нарушений и документ (шаг 3 спеки 2026-10-21, D602, D606).

Ядро — данные, которые партнёр читает как факт: что попало в таблицу нарушений и
что в ней написано. Оценку считает движок (подпроцесс на синтетической методике
`tests/methodology`); здесь проверяется, что из его ответа берётся ровно положенное:
все D3 и все нарушения зон, обнулённых целиком; D1/D2 прочих зон — нет.
"""

from __future__ import annotations

import io
import json
from datetime import date
from pathlib import Path
from typing import Any

from conftest import TEST_DATA
from PIL import Image

from src.db.prescriptions import NoticeFinding
from src.report import notice, notice_pdf
from src.report.engine_call import AUDIT_SCRIPT
from src.report.letters import _run

ДАТА = "2026-10-01"


def _оценка(tmp_path: Path, находки: list[tuple[str, str, str]]) -> dict[str, Any]:
    """Ответ `score --json` движка по состоянию из (код пункта, класс, зона)."""
    состояние = tmp_path / "inspection.json"
    состояние.write_text(
        json.dumps(
            {
                "meta": {"unit": "Batumi-1", "date": ДАТА, "lang": "ru", "kind": "planned"},
                "findings": [
                    {
                        "n": n,
                        "qid": qid,
                        "level": level,
                        "zone": zone,
                        "photos": [],
                        "comment": "",
                        "evidence": f"запись {n}",
                    }
                    for n, (qid, level, zone) in enumerate(находки, 1)
                ],
            }
        ),
        encoding="utf-8",
    )
    код, вывод, ошибки = _run(
        AUDIT_SCRIPT, ["score", "--json"], data_dir=TEST_DATA, state=состояние
    )
    assert код == 0, ошибки
    return json.loads(вывод)  # type: ignore[no-any-return]


def test_берутся_d3_и_нарушения_обнулённой_зоны_а_прочие_нет(tmp_path: Path) -> None:
    оценка = _оценка(
        tmp_path,
        [
            ("PRD01", "D3", "fridge"),  # 1: D3 — берём
            ("PRD01", "D1", "fridge"),  # 2: D1 в зоне, обнулённой D3 — берём (D606)
            ("PRD01", "D1", "hot_kitchen"),  # 3: D1 в живой зоне — нет
            ("PRD02", "D2", "cold_kitchen"),  # 4: D2 в живой зоне — нет
        ],
    )
    assert оценка["zones"]["fridge"]["zeroed"] is True
    assert оценка["zones"]["hot_kitchen"]["zeroed"] is False
    assert notice.suggest(оценка) == frozenset({1, 2})


def test_без_d3_ничего_не_предлагается_но_кандидаты_все(tmp_path: Path) -> None:
    оценка = _оценка(tmp_path, [("PRD01", "D1", "fridge"), ("PRD02", "D2", "cold_kitchen")])
    assert notice.suggest(оценка) == frozenset()
    rows = notice.candidates(оценка)
    assert [c.n for c in rows] == [1, 2]
    assert not any(c.suggested for c in rows)


def test_пункт_по_английски_без_пометки_класса_и_срок_движка(tmp_path: Path) -> None:
    rows = notice.candidates(_оценка(tmp_path, [("PRD01", "D1", "fridge")]))
    assert rows[0].clause == "Prep item carries a sample-A tag"
    assert rows[0].engine_due_on == date(2026, 10, 11)


def test_рекомендация_и_информационная_запись_не_кандидаты() -> None:
    оценка: dict[str, Any] = {
        "zones": {"fridge": {"zeroed": True}},
        "findings": [
            {"n": 1, "level": "R", "zone": "fridge", "qid": "X", "question_en": "a"},
            {"n": 2, "level": "D0", "zone": "fridge", "qid": "X", "question_en": "b"},
            {"n": 3, "level": "D3", "zone": "fridge", "qid": "X", "question_en": "c", "due": ""},
        ],
    }
    assert notice.suggest(оценка) == frozenset({3})
    assert [c.n for c in notice.candidates(оценка)] == [3]


def test_зона_обнулённая_набором_d1_тоже_основание_а_живая_зона_нет(tmp_path: Path) -> None:
    # 20 × D1 по 0,5 п. съедают долю зоны в 10 п.; одинокий D1 в другой зоне — нет.
    оценка = _оценка(
        tmp_path,
        [("PRD06", "D1", "hot_kitchen")] * 20 + [("PRD07", "D1", "fridge")],
    )
    assert оценка["zones"]["hot_kitchen"]["zeroed"] is False, "флаг D3 не взведён: это набор D1"
    assert notice.zeroed_zones(оценка) == frozenset({"hot_kitchen"})
    assert notice.suggest(оценка) == frozenset(range(1, 21))


# ── Документ ────────────────────────────────────────────────────────────────


def _кадр(красный: int = 180) -> bytes:
    выход = io.BytesIO()
    Image.new("RGB", (320, 200), (красный, 60, 60)).save(выход, "JPEG")
    return выход.getvalue()


def _нарушение(ident: str, объект: str, срок: date) -> NoticeFinding:
    return NoticeFinding(
        id=ident,
        inspection_id="i1",
        finding_id=ident,
        position=1,
        object_kind="pizzeria",
        object_name=объект,
        level="D3",
        clause="Prep item carries a sample-A tag",
        description="Tubs of different runs stand together",
        description_translated=True,
        due_on=срок,
        engine_due_on=None,
        suggested=True,
        included=True,
    )


def _документ(**поля: Any) -> notice_pdf.NoticeDocument:
    основа: dict[str, Any] = {
        "heading": "Notice <GE>",
        "body": "Country: Georgia\nDue: 2026-11-20\n\nPlease remedy the failures below.",
        "findings": (
            _нарушение("f1", "Batumi-1", date(2026, 11, 20)),
            _нарушение("f2", "Tbilisi-1", date(2026, 11, 20)),
        ),
        "photos": {"f1": [_кадр(180), _кадр(40)]},
        "photos_missing": {"f2": 1},
    }
    return notice_pdf.NoticeDocument(**{**основа, **поля})


def test_документ_по_английски_с_шапкой_таблицей_и_приложением() -> None:
    html = notice_pdf.render_html(_документ())
    assert '<html lang="en">' in html
    # Шапка и текст шаблона; разметка в них экранируется.
    assert "<h1>Notice &lt;GE&gt;</h1>" in html
    assert "<p>Country: Georgia<br>Due: 2026-11-20</p>" in html
    assert "<p>Please remedy the failures below.</p>" in html
    # Таблица нарушений: пункт, описание, срок дд/мм/гггг.
    assert "The identified failure" in html and "<td>20/11/2026</td>" in html
    assert html.count("<tr><td>Batumi-1</td>") == 1 and html.count("<tr><td>Tbilisi-1</td>") == 1
    # Приложение: фото первой записи, видимая отметка потерянного кадра у второй.
    assert html.count("<img") == 2
    assert notice_pdf.PHOTO_MISSING in html


def test_pdf_собирается_по_английски_и_несёт_кадры() -> None:
    данные = notice_pdf.build_pdf(_документ())
    assert данные.startswith(b"%PDF-") and len(данные) > notice_pdf.PDF_MIN_BYTES
    assert данные.count(b"/Subtype /Image") >= 2
