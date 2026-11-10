"""D739: общее письмо по нескольким проверкам одной страны.

Ядро — то, чья ошибка молчит, а платит за неё партнёр:

* **правило выбора** — только принятые проверки одной страны и одного пространства, не
  меньше двух, между крайними датами не больше семи дней; нарушение — отказ с кодом, а не
  тихое отсечение;
* **таблица и итог строит код из записанного** — оценка в строке таблицы та, что лежит в
  проверке, а не пересчитанная;
* **не сошлась сверка у одной проверки — письма нет**, и в отказе названа эта проверка;
* **один срок на письмо — от самой поздней проверки**.

Слова проверок приезжают от настоящего движка (оснастка методики из `mcp_checklist_harness`).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from mcp_checklist_harness import build_edition, build_methodology, harness_edition

from src.db.models import FindingRow, InfoRow, InspectionDetail, InspectionRow
from src.report import batch_letter as bl
from src.report.batch_letter import BatchLetterError, Piece
from src.report.letters import Papers

ВЕРСИЯ = harness_edition()
ТЕНАНТ = "укашка"


def _строка(
    n: int = 1,
    *,
    day: date = date(2026, 11, 4),
    unit: str | None = None,
    pct: float = 99.5,
    grade: str = "A",
    **поля: Any,
) -> InspectionRow:
    основа: dict[str, Any] = {
        "id": f"{n:08d}-1111-1111-1111-111111111111",
        "tenant_code": ТЕНАНТ,
        "unit_name": unit or f"Белград-{n}",
        "chat_id": 100500100,
        "kind": "planned",
        "inspection_date": day,
        "report_lang": "ru",
        "checklist_version": ВЕРСИЯ,
        "pct": pct,
        "grade": grade,
        "findings_count": 1,
        "pushed_at": f"{day.isoformat()}T18:0{n}:00+02:00",
        "unit_country": "RS",
        "partner": "Партнёр",
        "auditor": "Auditor One",
    }
    основа.update(поля)
    return InspectionRow(**основа)


def _находка(n: int) -> FindingRow:
    return FindingRow(
        id=f"{n:08d}-2222-2222-2222-222222222222",
        inspection_id=f"{n:08d}-1111-1111-1111-111111111111",
        unit_name=f"Белград-{n}",
        inspection_date=date(2026, 11, 4),
        n=1,
        code="CLN01",
        level="D1",
        zone="fridge",
        zone_unusual=False,
        source="comment",
        lang="ru",
        text=f"Пол в холодильнике {n} в разводах",
        comment="",
    )


def _проверка(n: int = 1, **kw: Any) -> InspectionDetail:
    return InspectionDetail(
        inspection=_строка(n, **kw),
        deductions=0.5,
        counts={"D1": 1},
        by_zone={},
        findings=(_находка(n),),
        info=(InfoRow(code="INF07", text="12.11.2026"),),
    )


def _выбор(*, ещё: int = 1) -> list[InspectionDetail]:
    return [_проверка(1), *[_проверка(2 + i) for i in range(ещё)]]


# --- правило выбора ---------------------------------------------------------------


def test_годный_выбор_отдаётся_по_датам_старые_первыми() -> None:
    позже = _проверка(1, day=date(2026, 11, 6))
    раньше = _проверка(2, day=date(2026, 11, 4))

    итог = bl.check_selection([позже, раньше], tenant=ТЕНАНТ)

    assert [d.inspection.id for d in итог] == [раньше.inspection.id, позже.inspection.id]


def test_одна_проверка_отказ_одиночное_письмо_для_неё() -> None:
    with pytest.raises(BatchLetterError) as отказ:
        bl.check_selection([_проверка(1)], tenant=ТЕНАНТ)
    assert отказ.value.code == "too_few"


def test_та_же_проверка_дважды_отказ_а_не_тихое_схлопывание() -> None:
    с = _проверка(1)
    with pytest.raises(BatchLetterError) as отказ:
        bl.check_selection([с, с], tenant=ТЕНАНТ)
    assert отказ.value.code == "duplicate"


def test_семь_дней_между_крайними_можно_восемь_нельзя() -> None:
    начало = date(2026, 11, 1)
    годный = [_проверка(1, day=начало), _проверка(2, day=начало + timedelta(days=7))]
    bl.check_selection(годный, tenant=ТЕНАНТ)

    с_лишним = [_проверка(1, day=начало), _проверка(2, day=начало + timedelta(days=8))]
    with pytest.raises(BatchLetterError) as отказ:
        bl.check_selection(с_лишним, tenant=ТЕНАНТ)

    assert отказ.value.code == "spread"
    assert отказ.value.facts["days"] == 8
    assert отказ.value.facts["maximum"] == 7
    # Отказ говорит словами, какие две даты не уживаются.
    assert "01.11.2026" in str(отказ.value) and "09.11.2026" in str(отказ.value)


def test_разброс_считается_по_крайним_а_не_по_соседним() -> None:
    # Каждая соседняя пара в пределах недели, а крайние — через десять дней.
    дни = [date(2026, 11, 1), date(2026, 11, 5), date(2026, 11, 11)]
    выбор = [_проверка(i + 1, day=д) for i, д in enumerate(дни)]
    with pytest.raises(BatchLetterError) as отказ:
        bl.check_selection(выбор, tenant=ТЕНАНТ)
    assert отказ.value.code == "spread"


def test_разные_страны_отказ() -> None:
    выбор = [_проверка(1), _проверка(2, unit_country="GE")]
    with pytest.raises(BatchLetterError) as отказ:
        bl.check_selection(выбор, tenant=ТЕНАНТ)
    assert отказ.value.code == "other_country"


def test_страна_экрана_не_совпала_со_страной_проверок_отказ() -> None:
    with pytest.raises(BatchLetterError) as отказ:
        bl.check_selection(_выбор(), tenant=ТЕНАНТ, country="ge")
    assert отказ.value.code == "other_country"


def test_страна_пиццерии_не_указана_отказ() -> None:
    выбор = [_проверка(1, unit_country=""), _проверка(2, unit_country="")]
    with pytest.raises(BatchLetterError) as отказ:
        bl.check_selection(выбор, tenant=ТЕНАНТ)
    assert отказ.value.code == "other_country"


@pytest.mark.parametrize(
    ("поле", "код"),
    [
        ({"on_review": True}, "not_accepted"),
        ({"origin": "legacy"}, "uploaded"),
        ({"retracted": True}, "retracted"),
        ({"tenant_code": "чужой"}, "other_space"),
    ],
)
def test_негодная_проверка_в_выборе_отказ_с_названием(поле: dict[str, Any], код: str) -> None:
    выбор = [_проверка(1), _проверка(2, **поле)]
    with pytest.raises(BatchLetterError) as отказ:
        bl.check_selection(выбор, tenant=ТЕНАНТ)
    assert отказ.value.code == код
    assert "Белград-2" in str(отказ.value)


# --- таблица, итог, срок: из записанного, без модели -------------------------------------


def _часть(**поля: Any) -> dict[str, Any]:
    основа: dict[str, Any] = {
        "unit": "X",
        "auditor": "",
        "counts": {"D1": 0, "D2": 0, "D3": 0},
        "summary": "",
        "urgent": {"D3": [], "D2": []},
        "immediately": "immediately",
        "feedback_heads": {"strengths": "What is going well:", "growth": "What to work on:"},
        "strengths": "",
        "growth": "",
        "plan_due": "12.11.2026",
    }
    основа.update(поля)
    return основа


def _piece(n: int, *, counts: dict[str, int] | None = None, **kw: Any) -> Piece:
    части = _часть(counts=counts or {"D1": 0, "D2": 0, "D3": 0})
    return Piece(detail=_проверка(n, **kw), parts=части)


def test_таблица_несёт_записанную_оценку_и_счётчики() -> None:
    p = _piece(1, counts={"D1": 3, "D2": 1, "D3": 0}, pct=88.0, grade="C")

    таблица = bl.table_text([p], "en").splitlines()

    assert таблица[0] == "Pizzeria | Date | Score | Grade | D1 | D2 | D3"
    assert таблица[1] == "Белград-1 | 04.11.2026 | 88% | C | 3 | 1 | 0"


def test_итог_все_соответствуют_когда_нет_d2_d3_и_плохих_букв() -> None:
    итог = bl.summary_text([_piece(1), _piece(2, grade="B", pct=92.0)], "ru")
    assert итог.startswith("Все пиццерии соответствуют стандарту")


def test_итог_называет_сколько_из_скольки_грейд_d() -> None:
    pieces = [
        _piece(1, counts={"D1": 1, "D2": 0, "D3": 1}, grade="D", pct=80.0),
        _piece(2, counts={"D1": 0, "D2": 0, "D3": 1}, grade="D", pct=70.0),
        _piece(3),
        _piece(4),
    ]
    итог = bl.summary_text(pieces, "en")
    assert "2 of 4 pizzerias scored grade D" in итог
    assert "critical (D3) — 2" in итог


def test_итог_c_без_d3_называет_ниже_стандарта() -> None:
    pieces = [_piece(1, counts={"D1": 4, "D2": 2, "D3": 0}, grade="C", pct=85.0), _piece(2)]
    итог = bl.summary_text(pieces, "en")
    assert "1 of 2 pizzerias are below the standard" in итог
    assert "grade D" not in итог


def test_период_один_день_один_месяц_два_месяца() -> None:
    assert bl.period_text(date(2026, 11, 4), date(2026, 11, 4)) == "04.11.2026"
    assert bl.period_text(date(2026, 10, 13), date(2026, 10, 16)) == "13–16.10.2026"
    assert bl.period_text(date(2026, 10, 30), date(2026, 11, 3)) == "30.10–03.11.2026"
    assert bl.period_text(date(2026, 12, 30), date(2027, 1, 2)) == "30.12.2026–02.01.2027"


def test_срок_один_и_берётся_у_самой_поздней_проверки() -> None:
    ранняя = Piece(_проверка(1, day=date(2026, 11, 2)), _часть(plan_due="05.11.2026"))
    поздняя = Piece(_проверка(2, day=date(2026, 11, 4)), _часть(plan_due="14.11.2026"))
    плохая = {"D1": 1, "D2": 0, "D3": 0}
    ранняя = replace(ранняя, parts=_часть(plan_due="05.11.2026", counts=плохая))
    поздняя = replace(поздняя, parts=_часть(plan_due="14.11.2026", counts=плохая))

    текст = bl.compose([ранняя, поздняя], lang="en", template=1)

    assert text_count(текст, "14.11.2026") == 1
    assert "05.11.2026" not in текст.split("What needs to be done:")[1]
    assert "Please eliminate all violations by 14.11.2026." in текст


def text_count(текст: str, часть: str) -> int:
    return текст.count(часть) - текст.count(f"{часть} |")  # строки таблицы тоже несут дату


def test_без_нарушений_плана_и_срока_в_письме_нет() -> None:
    текст = bl.compose([_piece(1), _piece(2)], lang="en", template=1)
    assert "No action plan to address violations is required." in текст
    assert "Please eliminate" not in текст


def test_срочное_d3_и_d2_идёт_раньше_списка_по_пиццериям() -> None:
    части = _часть(
        counts={"D1": 0, "D2": 1, "D3": 1},
        urgent={
            "D3": [{"text": "Лампа над входом не горит", "zone": "Зал"}],
            "D2": [{"text": "Нет термометра", "zone": "Холодильник"}],
        },
    )
    p = Piece(_проверка(1, grade="D", pct=60.0), части)

    todo = bl.todo_text([p, _piece(2)], "ru", "12.11.2026")

    assert todo.index("Критические нарушения (D3)") < todo.index("Значительные нарушения (D2)")
    assert todo.index("Значительные нарушения (D2)") < todo.index("По пиццериям:")
    assert "• Белград-1: Лампа над входом не горит — Зал" in todo
    assert "Критические нарушения (D3) — immediately:" in todo


def test_шаблон_2_кладёт_обратную_связь_в_конец_блока_пиццерии() -> None:
    p = Piece(
        _проверка(1),
        _часть(
            counts={"D1": 1, "D2": 0, "D3": 0},
            summary="— 1 minor D1.",
            strengths="Чисто",
            growth="Сроки",
        ),
    )
    первый = bl._unit_block(p, "en", 1)
    второй = bl._unit_block(p, "en", 2)

    assert (
        первый.index("What is going well:")
        < первый.index("— 1 minor D1.")
        < первый.index("What to work on:")
    )
    assert (
        второй.index("— 1 minor D1.")
        < второй.index("What is going well:")
        < второй.index("What to work on:")
    )


def test_язык_без_словаря_отказ_а_не_русский() -> None:
    from src.report.batch_letter_texts import say
    from src.report.errors import ReportError

    with pytest.raises(ReportError):
        say("hello", "de")


# --- сборка настоящим движком ----------------------------------------------------------


@pytest.fixture
def хранилище(tmp_path: Path) -> Papers:
    build_edition(tmp_path / "store" / "versions" / ВЕРСИЯ)
    build_methodology(tmp_path / "live")
    return Papers(live=tmp_path / "live", store=tmp_path / "store")


def test_письмо_собрано_движком_таблица_несёт_записанное(хранилище: Papers) -> None:
    выбор = [_проверка(1, day=date(2026, 11, 2)), _проверка(2, day=date(2026, 11, 4))]

    ответ = bl.build(выбор, tenant=ТЕНАНТ, papers=хранилище, lang="en")

    письмо = str(ответ["letter"])
    assert письмо.startswith(
        "Subject: Inspection results for Белград-1, Белград-2 for 02–04.11.2026"
    )
    assert "Белград-1 | 02.11.2026 | 99.5% | A | 1 | 0 | 0" in письмо
    assert "Белград-2 | 04.11.2026 | 99.5% | A | 1 | 0 | 0" in письмо
    assert "Пол в холодильнике 1 в разводах" in письмо  # слова аудитора, как записаны
    # Ответа про план в оснастке нет: срок — дата самой поздней проверки + plan_due_days (10).
    assert "Please eliminate all violations by 14.11.2026." in письмо
    assert ответ["score_verified"] is True
    assert ответ["inspection_ids"] == [d.inspection.id for d in выбор]
    assert ответ["auditors"] == ["Auditor One"]


def test_письмо_на_русском_по_умолчанию_на_языке_отчёта(хранилище: Papers) -> None:
    ответ = bl.build(_выбор(), tenant=ТЕНАНТ, papers=хранилище)
    assert str(ответ["letter"]).startswith("Тема: Результаты проверок")
    assert ответ["lang"] == "ru"


def test_не_сошлась_сверка_у_одной_общего_письма_нет_и_названа_она(хранилище: Papers) -> None:
    выбор = [_проверка(1), _проверка(2, pct=88.0, grade="C")]  # движок посчитает 99.5 A

    with pytest.raises(BatchLetterError) as отказ:
        bl.build(выбор, tenant=ТЕНАНТ, papers=хранилище)

    assert отказ.value.code == "unit_failed"
    assert отказ.value.facts["unit"] == "Белград-2"
    assert "не сходится с записанной" in str(отказ.value)


def test_версии_методики_нет_у_одной_проверки_общего_письма_нет(хранилище: Papers) -> None:
    выбор = [_проверка(1), _проверка(2, checklist_version="harness-2026-01-01-000000000000")]

    with pytest.raises(BatchLetterError) as отказ:
        bl.build(выбор, tenant=ТЕНАНТ, papers=хранилище)

    assert отказ.value.code == "unit_failed"
    assert "Белград-2" in str(отказ.value)


def test_правило_выбора_работает_и_в_сборке(хранилище: Papers) -> None:
    выбор = [_проверка(1), _проверка(2, day=date(2026, 11, 20))]
    with pytest.raises(BatchLetterError) as отказ:
        bl.build(выбор, tenant=ТЕНАНТ, papers=хранилище)
    assert отказ.value.code == "spread"


def test_у_самой_поздней_нет_информационной_части_срок_назван_подставленным(
    хранилище: Papers,
) -> None:
    выбор = [_проверка(1), replace(_проверка(2), info=())]

    ответ = bl.build(выбор, tenant=ТЕНАНТ, papers=хранилище)

    assert ответ["ready_to_send"] is False
    assert "action plan deadline" in ответ["not_restored"]  # type: ignore[operator]


def test_разные_партнёры_видны_в_ответе_без_запрета(хранилище: Papers) -> None:
    выбор = [_проверка(1), _проверка(2, partner="Другой партнёр")]
    ответ = bl.build(выбор, tenant=ТЕНАНТ, papers=хранилище)
    assert ответ["partners"] == ["Другой партнёр", "Партнёр"]


def test_у_каждого_кода_отказа_есть_текст_на_обоих_языках() -> None:
    """Код отказа без текста показал бы человеку пустую строку вместо причины."""
    from src.web.texts_batch_letter import BATCH_LETTER_TEXTS

    for code in bl.REFUSAL_CODES:
        text = BATCH_LETTER_TEXTS.get(f"batch.refuse.{code}")
        assert text, f"нет текста отказа {code}"
        assert text.get("ru") and text.get("en"), f"отказ {code}: нужен RU и EN"
