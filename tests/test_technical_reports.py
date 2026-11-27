"""Historical technical evidence remains explicit and comparable across editions."""

from __future__ import annotations

import importlib.util
import json
from datetime import date
from pathlib import Path

import pytest

from src.db.inspection_edits import Editor
from src.db.models import InspectionDetail, InspectionRow
from src.db.technical import TechnicalReviewRefused, _review_point, reconcile
from src.report.letters import state_json
from src.report.technical import history_matrix, present


def snapshot(status: str = "ok", *, title: str = "Стена", check_id: str = "TC01") -> dict:
    return {
        "enabled": True,
        "checks": [
            {
                "id": check_id,
                "zone": "dining",
                "item_codes": ["CLN05"],
                "required": True,
                "title_ru": title,
                "title_en": "Wall",
                "status": status,
                "finding_numbers": [3] if status == "issue" else [],
                "reason": "Отдельный вход" if status == "na" else "",
            }
        ],
    }


def detail(technical: dict | None) -> InspectionDetail:
    row = InspectionRow(
        id="11111111-1111-1111-1111-111111111111",
        tenant_code="HQ",
        unit_name="Test-1",
        chat_id=1,
        kind="planned",
        inspection_date=date(2026, 11, 26),
        report_lang="ru",
        checklist_version="local-test",
        pct=100,
        grade="A",
        findings_count=0,
        pushed_at="2026-11-26T12:00:00Z",
        technical_snapshot=technical,
    )
    return InspectionDetail(inspection=row, deductions=0, counts={}, by_zone={}, findings=())


def test_history_reconstruction_preserves_frozen_wording_and_answers() -> None:
    original = snapshot("na", title="Старая формулировка")
    restored = json.loads(state_json(detail(original), lang="en"))
    assert restored["domain"]["technical_snapshot"] == original
    assert restored["meta"]["lang"] == "en"
    assert restored["findings"] == []  # confirmations never become deductions


def test_old_inspection_does_not_invent_confirmations() -> None:
    restored = json.loads(state_json(detail(None), lang="ru"))
    assert "technical_snapshot" not in restored.get("domain", {})
    result = present(None, lang="ru", previous=snapshot("issue"))
    assert result["enabled"] is False
    assert result["total"] == 0


def test_transient_review_candidates_are_not_exported_to_report_state() -> None:
    original = snapshot("pending")
    original["checks"][0]["candidate_evidence"] = [{"n": 7, "text": "candidate"}]
    exported = json.loads(state_json(detail(original), lang="ru"))["domain"]["technical_snapshot"]
    assert "candidate_evidence" not in exported["checks"][0]
    assert "candidate_evidence" in original["checks"][0]


@pytest.mark.parametrize(("level", "kind"), [("R", "info"), ("D0", "violation"), ("D0", None)])
def test_review_recorded_requires_d0_and_information_checkpoint(level, kind) -> None:
    point = {"status": "pending", "kind": kind, "candidate_evidence": [{"n": 1, "level": level}]}
    with pytest.raises(TechnicalReviewRefused):
        _review_point(
            point,
            status="recorded",
            reason="",
            finding_number=1,
            editor=Editor("11111111-1111-1111-1111-111111111111", "reviewer", "admin"),
        )
    assert point["status"] == "pending"


def test_review_cannot_replace_a_still_valid_issue_with_ok() -> None:
    point = {"status": "issue", "finding_numbers": [3]}
    with pytest.raises(TechnicalReviewRefused):
        _review_point(
            point,
            status="ok",
            reason="",
            finding_number=None,
            editor=Editor("11111111-1111-1111-1111-111111111111", "reviewer", "admin"),
        )
    assert point["status"] == "issue"


def test_review_accepts_explicit_d0_information_evidence() -> None:
    point = {
        "status": "pending",
        "kind": "info",
        "candidate_evidence": [{"n": 1, "level": "D0"}],
    }
    _review_point(
        point,
        status="recorded",
        reason="",
        finding_number=1,
        editor=Editor("11111111-1111-1111-1111-111111111111", "reviewer", "admin"),
    )
    assert point["status"] == "recorded"
    assert point["finding_numbers"] == [1]
    assert point["confirmed_by"] == "reviewer"


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        ("issue", "ok", "fixed"),
        ("issue", "pending", "uncompared"),
        ("issue", "na", "uncompared"),
        ("issue", "issue", "persists"),
        ("ok", "issue", "new_issue"),
        ("pending", "ok", "uncompared"),
    ],
)
def test_only_an_explicit_good_result_counts_as_fixed(before, after, expected) -> None:
    result = present(snapshot(after), lang="en", previous=snapshot(before))
    assert result["rows"][0]["change"] == expected
    assert result["rows"][0]["title"] == "Wall"


def test_same_title_different_checkpoint_is_not_a_match() -> None:
    result = present(snapshot("ok", check_id="TC02"), lang="ru", previous=snapshot("issue"))
    assert result["rows"][0]["change"] == "uncompared"


def test_matrix_keeps_missing_cells_and_joins_only_stable_checkpoint_and_zone() -> None:
    old = snapshot("issue", title="Первое название")
    current = snapshot("ok", title="Уточнённое название")
    current["checks"].append(
        {
            "id": "TC02",
            "zone": "dining",
            "title_ru": "Новый пункт",
            "status": "na",
            "reason": "Оборудование не установлено",
        }
    )
    matrix = history_matrix(
        [
            {"inspection_id": "old", "date": "2026-01-01", "snapshot": old},
            {"inspection_id": "missing", "date": "2026-06-01", "snapshot": None},
            {"inspection_id": "current", "date": "2026-11-26", "snapshot": current},
        ],
        lang="ru",
    )
    assert [column["date"] for column in matrix["columns"]] == [
        "2026-01-01",
        "2026-06-01",
        "2026-11-26",
    ]
    first, added = matrix["rows"]
    assert first["title"] == "Уточнённое название"
    assert [cell["status"] for cell in first["cells"]] == ["issue", "absent", "ok"]
    assert [cell["status"] for cell in added["cells"]] == ["absent", "absent", "na"]


def test_matrix_groups_zones_without_losing_retired_points_or_expanded_wording() -> None:
    old = snapshot("issue")
    old["checks"][0]["guidance_ru"] = "Прежняя формулировка"
    kitchen = {**old["checks"][0], "zone": "hot_kitchen", "status": "ok"}
    old["checks"].append(kitchen)
    current = snapshot("ok")
    current["checks"][0]["guidance_ru"] = "Проверить всю поверхность и крепления."
    matrix = history_matrix(
        [{"snapshot": old}, {"snapshot": current}],
        lang="ru",
        zone_order=["hot_kitchen", "dining"],
    )
    assert [group["zone"] for group in matrix["groups"]] == ["hot_kitchen", "dining"]
    retired = matrix["groups"][0]["rows"][0]
    assert [cell["status"] for cell in retired["cells"]] == ["ok", "absent"]
    assert matrix["groups"][1]["rows"][0]["guidance"] == ("Проверить всю поверхность и крепления.")


@pytest.mark.parametrize("change", ["deleted", "text", "code", "zone", "photos"])
def test_editing_linked_evidence_requires_new_confirmation(change) -> None:
    frozen = snapshot("issue")
    frozen["checks"][0]["finding_evidence"] = [
        dict(n=3, code="CLN05", level="D1", zone="dining", text="Дефект", photos=["p1"])
    ]
    original = [3, "CLN05", "D1", "dining", "Дефект", ["p1"]]

    class Cursor:
        def __init__(self):
            self.rows = [original]

        def execute(self, *args):
            pass

        def fetchall(self):
            return self.rows

    cursor = Cursor()
    unchanged = reconcile(cursor, "inspection", "HQ", frozen)
    assert unchanged["checks"][0]["status"] == "issue"
    if change == "deleted":
        cursor.rows = []
    else:
        index = {"code": 1, "zone": 3, "text": 4, "photos": 5}[change]
        updated = list(original)
        updated[index] = [] if change == "photos" else "changed"
        cursor.rows = [updated]
    invalidated = reconcile(cursor, "inspection", "HQ", frozen)
    assert invalidated["required_pending"] == 1
    assert invalidated["checks"][0]["status"] == "pending"
    assert invalidated["checks"][0]["finding_numbers"] == []
    assert frozen["checks"][0]["status"] == "issue"  # frozen source is preserved


def test_report_fragment_escapes_text_and_links_existing_evidence() -> None:
    path = Path(__file__).parents[1] / "engine" / "technical_report.py"
    spec = importlib.util.spec_from_file_location("technical_report", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    html = module.render(snapshot("issue", title="Стена <script>"), "ru", {"dining": "Зал"})
    assert "Проверено 1 из 1" in html
    assert "Стена &lt;script&gt;" in html
    assert 'href="#finding-3"' in html
    assert "Нарушение" in html
    assert "не собиралось" in module.render(None, "ru", {})
    assert "did not collect" in module.render(None, "en", {})
    assert "toplanmadı" in module.render(None, "tr", {})


def test_real_html_report_keeps_technical_evidence_separate_from_score(started, report, workdir):
    before = started("score", "--json")
    state_file = workdir / "inspection.json"
    raw = json.loads(state_file.read_text())
    raw.setdefault("domain", {})["technical_snapshot"] = snapshot("pending")
    state_file.write_text(json.dumps(raw, ensure_ascii=False))
    rendered = report("html", "--lang", "ru")
    after = started("score", "--json")
    assert rendered.code == 0, rendered.text
    assert "Техническое состояние" in rendered.out
    assert "Проверено 0 из 1" in rendered.out
    assert "Не проверено" in rendered.out
    assert json.loads(before.out) == json.loads(after.out)
