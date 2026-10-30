"""A plan is requested for every D1/D2/D3, independently of the engine grade."""

import json
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

import pytest
from conftest import AUDIT, REPORT, Run, run_engine

PLAN_FOOTER = {
    "ru": (
        "Во вложении — подробный отчёт с фотографиями. По результатам проверки "
        "просим подготовить план устранения выявленных отклонений."
    ),
    "en": (
        "Attached is the detailed report with photographs. Following the inspection, "
        "please prepare an action plan to address the identified deviations."
    ),
}

CLEAN_FOOTER = {
    "ru": (
        "Нарушений не зафиксировано. Во вложении — подробный отчёт с фотографиями. "
        "План устранения нарушений не требуется."
    ),
    "en": (
        "No violations were recorded. Attached is the detailed report with photographs. "
        "No action plan to address violations is required."
    ),
}


@pytest.fixture
def invoke(workdir: Path, data_copy: Path) -> Callable[..., Run]:
    def call(script: Path, *args: str) -> Run:
        return run_engine(
            script, *args, cwd=workdir, state=workdir / "inspection.json", data_dir=data_copy
        )

    return call


@pytest.mark.parametrize("lang", ["ru", "en"])
@pytest.mark.parametrize("template", ["1", "2"])
@pytest.mark.parametrize(
    ("case", "entries", "grade", "slot"),
    [
        ("minor-a", (("PRD01", "D1"),), "A", "plan"),
        ("major-b", (("PRD01", "D2"),), "B", "plan"),
        ("major-c", (("PRD01", "D2"), ("PRD05", "D2")), "C", "plan"),
        ("minor-c", (("PRD01", "D1"),), "C", "plan"),
        ("critical-d", (("PRD04", "D3"),), "D", "plan"),
        ("mixed", (("PRD01", "D1"), ("PRD05", "D2")), "B", "plan"),
        ("mixed-critical", (("PRD01", "D1"), ("PRD05", "D2"), ("PRD04", "D3")), "D", "plan"),
        ("d0-only", (("INF10", "D0"),), "A", "clean"),
        ("recommendation", (("NOTE", "R"),), "A", "clean"),
        ("info-only", (), "A", "empty"),
        ("empty", (), "A", "empty"),
    ],
)
def test_plan_and_stored_slot_follow_violation_classes_not_grade(
    invoke: Callable[..., Run],
    data_copy: Path,
    tmp_path: Path,
    lang: str,
    template: str,
    case: str,
    entries: tuple[tuple[str, str], ...],
    grade: str,
    slot: str,
) -> None:
    if case == "minor-c":
        # The private production methodology is never changed. One fictional
        # fixture deduction makes C with only D1 so grade and class are independent.
        scoring_file = data_copy / "scoring.json"
        scoring = json.loads(scoring_file.read_text())
        scoring["penalty"]["D1"] = 13
        scoring_file.write_text(json.dumps(scoring))
    init = invoke(AUDIT, "init", "--unit", "Synthetic", "--date", "2026-08-21")
    assert init.code == 0, init.text
    observations = []
    for code, level in entries:
        evidence = f"Complete observation for {code}: unique ending END-{code}"
        observations.append(evidence)
        added = invoke(
            AUDIT,
            "add",
            "--qid",
            code,
            "--level",
            level,
            "--zone",
            "fridge",
            "--evidence",
            evidence,
        )
        assert added.code == 0, added.text
    if case == "info-only":
        added = invoke(AUDIT, "info", "--qid", "INF01", "--text", "Synthetic roster")
        assert added.code == 0, added.text
    before = invoke(AUDIT, "score", "--json")
    assert before.code == 0, before.text
    assert json.loads(before.out)["grade"] == grade
    letter = invoke(REPORT, "letter", "--lang", lang, "--template", template)
    assert letter.code == 0, letter.text
    request = PLAN_FOOTER[lang]
    assert (request in letter.out) is (slot == "plan")
    if grade == "C":
        assert (
            "Это ниже стандарта и требует плана действий."
            if lang == "ru"
            else "This is below standard and requires an action plan."
        ) in letter.out
    if slot == "plan":
        assert letter.out.count(PLAN_FOOTER[lang]) == 1
        assert "Просим до" not in letter.out
        assert "сроками устранения по каждому пункту" not in letter.out
        assert "Нарушения D2 ждём закрытыми" not in letter.out
        assert "Please send us your action plan by" not in letter.out
        assert "a deadline for every item" not in letter.out
        assert "D2 violations are expected to be closed" not in letter.out
        assert "31.08.2026" not in letter.out
        assert "Плана действий не ждём" not in letter.out
        assert "No action plan is expected" not in letter.out
        for evidence in observations:
            assert evidence in letter.out
    elif slot == "clean":
        assert letter.out.count(CLEAN_FOOTER[lang]) == 1
        assert "перечисленные отклонения" not in letter.out
        assert "the deviations listed above" not in letter.out
        assert "в сроки, указанные в отчёте" not in letter.out
        assert "within the deadlines stated in the report" not in letter.out
        assert "31.08.2026" not in letter.out
    bodies_file = tmp_path / "bodies.json"
    bodies = {name: f"SELECTED_{name.upper()} {{unit}}" for name in ("plan", "clean", "empty")}
    bodies["plan"] += " CUSTOM_REPLY_BY {plan_due}"
    bodies_file.write_text(json.dumps(bodies))
    stored = invoke(
        REPORT,
        "letter",
        "--lang",
        lang,
        "--template",
        template,
        "--bodies-file",
        str(bodies_file),
    )
    assert stored.code == 0, stored.text
    expected_stored = f"SELECTED_{slot.upper()} Synthetic"
    if slot == "plan":
        configured_days = json.loads((data_copy / "scoring.json").read_text())["plan_due_days"]
        due = date(2026, 8, 21) + timedelta(days=configured_days)
        expected_stored += f" CUSTOM_REPLY_BY {due:%d.%m.%Y}"
    assert stored.out.strip() == expected_stored
    after = invoke(AUDIT, "score", "--json")
    assert after.code == 0, after.text
    assert json.loads(after.out) == json.loads(before.out)
