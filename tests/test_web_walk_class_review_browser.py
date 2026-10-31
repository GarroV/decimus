"""Selected-item UI contract with synthetic responses only; no server or paid requests."""

# ruff: noqa: F811
from __future__ import annotations

import pytest
from test_web_proofread_browser import browser_page  # noqa: F401
from test_web_walk_candidate_identity_browser import card, confirm_assignment, load_sheet

ITEMS = [
    {
        "code": "SYN01",
        "q": "Synthetic first item",
        "label": "Item 1",
        "process": "Alpha",
        "levels": ["D1", "D2"],
        "zones": ["zone_a"],
        "measure": False,
    },
    {
        "code": "SYN02",
        "q": "Synthetic second item",
        "label": "Item 2",
        "process": "Beta",
        "levels": ["D1", "D2"],
        "zones": ["zone_b"],
        "measure": False,
    },
]


def load(page, *, reading=None, second_reading=None, same_code=False):
    first = {
        **card("zone_a", "MODEL WORDING MUST NOT BECOME FACTS"),
        "level": "D2",
        "reading_c": reading,
    }
    second = {
        **card("zone_b", "ANOTHER MODEL WORDING"),
        "code": "SYN01" if same_code else "SYN02",
        "level": "D2",
        "reading_c": second_reading,
    }
    load_sheet(page, [first, second], choose=False, confirm=False, items=ITEMS, defer_levels=True)


def choose(page, index):
    page.locator(".walk-found__card").nth(index).click()
    confirm_assignment(page, index)


def resolve(page, index=0, **result):
    page.evaluate(
        "({index,result}) => levelReply(index,result)", {"index": index, "result": result}
    )


def test_search_requires_deliberate_item_choice_before_any_class_request(browser_page):
    page = browser_page
    load(page)
    assert page.locator(".walk-found__card.is-on").count() == 0
    assert page.locator("[data-class-review]").count() == 0
    assert page.locator(".walk-found__top .walk-level").count() == 0
    assert page.evaluate("levelCalls") == []
    choose(page, 0)
    page.wait_for_function("levelCalls.length === 1")
    body = page.evaluate("levelCalls[0]")
    assert body["run_id"] == "synthetic-run"
    assert body["checklist_version"] == "synthetic-edition"
    assert (body["code"], body["zone"]) == ("SYN01", "zone_a")
    assert body["words"] == "Synthetic observation"
    assert "MODEL" not in body["words"]
    assert body["photos"] == ["synthetic-ref"]
    assert page.get_by_role("button", name="Save", exact=True).is_disabled()


def test_needs_fact_never_applies_provisional_class_and_answer_is_scoped(browser_page):
    page = browser_page
    load(page)
    choose(page, 0)
    page.wait_for_function("levelCalls.length === 1")
    resolve(
        page,
        status="needs_fact",
        level=None,
        provisional_level="D2",
        need_fact="Synthetic missing fact?",
    )
    assert page.locator("[data-class-feedback]").inner_text().startswith("Synthetic missing fact?")
    assert page.get_by_role("button", name="Save", exact=True).is_disabled()
    facts = page.locator(".walk-class-review__facts")
    facts.press_sequentially("Human answer for the first item")
    assert facts.input_value() == "Human answer for the first item"
    assert page.evaluate("levelCalls.length") == 1  # Typing is not a paid request.
    page.locator("[data-class-check]").click()
    page.wait_for_function("levelCalls.length === 2")
    assert page.evaluate("levelCalls[1].words") == "Synthetic observation"
    assert page.evaluate("levelCalls[1].clarifications") == [
        {"question": "Synthetic missing fact?", "answer": "Human answer for the first item"}
    ]
    resolve(page, 1, level="D1")
    page.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_function("ops.length === 1")
    assert page.evaluate("ops[0].level") == "D1"
    assert page.evaluate("ops[0].words") == "Synthetic observation\nHuman answer for the first item"


@pytest.mark.parametrize("same_code", [False, True])
def test_late_reply_cannot_cross_item_or_override_manual_class(browser_page, same_code):
    page = browser_page
    load(page, same_code=same_code)
    choose(page, 0)
    page.wait_for_function("levelCalls.length === 1")
    confirm_assignment(page, 1)
    page.locator(".walk-found__card").nth(1).click()
    page.wait_for_function("levelCalls.length === 2")
    resolve(page, 0, level="D2")
    assert page.get_by_role("button", name="Save", exact=True).is_disabled()
    page.get_by_role("button", name="walk.sheet.class_review.manual", exact=True).click()
    page.locator('[data-manual-class="D2"]').click()
    resolve(page, 1, level="D1")
    page.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_function("ops.length === 1")
    assert (page.evaluate("ops[0].code"), page.evaluate("ops[0].level")) == (
        "SYN01" if same_code else "SYN02",
        "D2",
    )


def test_model_zero_reading_is_not_a_fact_until_explicit_confirmation(browser_page):
    page = browser_page
    load(page, reading=0)
    choose(page, 0)
    assert page.evaluate("levelCalls") == []
    assert page.locator(".walk-input--reading").input_value() == "0"
    assert page.get_by_role("button", name="Save", exact=True).is_disabled()
    assert not page.locator("[data-reading-confirm]").is_checked()
    page.locator("[data-reading-confirm]").check()
    page.wait_for_function("levelCalls.length === 1")
    body = page.evaluate("levelCalls[0]")
    assert body["reading_c"] == 0 and body["reading_confirmed"] is True
    assert body["reading_source"] == "model"
    page.locator(".walk-input--reading").fill("5")
    assert not page.locator("[data-reading-confirm]").is_checked()
    resolve(page, 0, level="D2")
    assert page.get_by_role("button", name="Save", exact=True).is_disabled()
    page.locator("[data-reading-confirm]").check()
    page.wait_for_function("levelCalls.length === 2")
    assert page.evaluate("levelCalls[1].reading_source") == "human"
    assert page.evaluate("levelCalls[1].reading_c") == 5


@pytest.mark.parametrize("change", ["words", "run", "edition"])
def test_late_reply_cannot_cross_changed_facts_or_server_context(browser_page, change):
    page = browser_page
    load(page)
    choose(page, 0)
    page.wait_for_function("levelCalls.length === 1")
    if change == "words":
        page.locator(".walk-area--words").fill("Changed human facts")
    elif change == "run":
        page.evaluate("DecimusWalk.state.data.run_id='other-run'")
    else:
        page.evaluate("DecimusWalk.state.data.checklist_version='other-edition'")
    resolve(page, 0, level="D2")
    # Force a normal UI refresh after simulated server data update.
    if change != "words":
        page.locator(".walk-area--words").fill("Changed human facts")
    assert page.get_by_role("button", name="Save", exact=True).is_disabled()
    assert page.evaluate("ops") == []


def test_human_item_facts_survive_switch_without_becoming_another_items_facts(browser_page):
    page = browser_page
    load(page)
    choose(page, 0)
    page.locator(".walk-class-review__facts").fill("Only the first item's human fact")
    confirm_assignment(page, 1)
    page.locator(".walk-found__card").nth(1).click()
    page.wait_for_function("levelCalls.length === 2")
    assert "Only the first" not in page.evaluate("levelCalls[1].words")
    saved = page.evaluate("lastDraft.class_facts")
    assert any(
        entry["code"] == "SYN01" and entry["answer"] == "Only the first item's human fact"
        for entry in saved
    )


@pytest.mark.parametrize(
    "result",
    [
        {"level": "D9"},
        {"level": None},
        {"criteria_hash": ""},
        {"code": "SYN02"},
        {"photo_refs": []},
    ],
)
def test_malformed_or_mismatched_ready_never_falls_back_to_coarse_class(browser_page, result):
    page = browser_page
    load(page)
    choose(page, 0)
    page.wait_for_function("levelCalls.length === 1")
    resolve(page, **result)
    assert page.get_by_role("button", name="Save", exact=True).is_disabled()
    assert (
        "walk.sheet.class_review.unavailable" in page.locator("[data-class-feedback]").inner_text()
    )
    page.get_by_role("button", name="walk.sheet.class_review.manual", exact=True).click()
    page.locator('[data-manual-class="D1"]').click()
    page.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_function("ops.length === 1")
    assert page.evaluate("ops[0].level") == "D1"


def test_manual_catalogue_keeps_other_zones_available_before_class(browser_page):
    from test_web_proofread_browser import ROOT

    page = browser_page
    load(page)
    choose(page, 0)
    page.add_script_tag(path=str(ROOT / "src/web/static/walk-menu.js"))
    page.get_by_role("button", name="walk.sheet.pick_manual", exact=True).click()
    # A point from another zone remains in the unfiltered manual catalogue.
    option = page.locator(".walk-search__list button").filter(has_text="Synthetic second item")
    if not option.count():
        option = page.locator(".walk-menu button").filter(has_text="Synthetic second item")
    assert option.count() == 1
    option.click()
    assert page.locator(".walk-found__card.is-on").inner_text().startswith("Item 2")
    assert page.get_by_role("button", name="Save", exact=True).is_disabled()


def test_extra_question_and_answer_do_not_change_primary_class_or_reading(browser_page):
    page = browser_page
    load(page)
    choose(page, 0)
    resolve(page, level="D1")
    confirm_assignment(page, 1)
    page.locator(".walk-found__row").filter(has_text="Synthetic second item").locator(
        ".walk-found__also"
    ).click()
    page.wait_for_function("levelCalls.length === 2")
    assert page.evaluate("levelCalls[1].words") == ""
    resolve(
        page,
        1,
        status="needs_fact",
        level=None,
        provisional_level="D2",
        need_fact="Fact for second item only?",
    )
    extra = page.locator('[data-class-review="SYN02"]')
    primary = page.locator('[data-class-review="SYN01"]')
    assert "Fact for second item" in extra.inner_text()
    assert "Fact for second item" not in primary.inner_text()
    assert page.get_by_role("button", name="Save 2", exact=True).is_disabled()
    extra.locator(".walk-class-review__facts").press_sequentially("Only second-item answer")
    extra.locator("[data-class-check]").click()
    page.wait_for_function("levelCalls.length === 3")
    assert page.evaluate("levelCalls[2].words") == ""
    assert page.evaluate("levelCalls[2].clarifications") == [
        {"question": "Fact for second item only?", "answer": "Only second-item answer"}
    ]
    assert page.evaluate("levelCalls[2].reading_c") is None
    resolve(page, 2, level="D2")
    page.get_by_role("button", name="Save 2", exact=True).click()
    page.wait_for_function("ops.length === 2")
    assert [(op["code"], op["level"]) for op in page.evaluate("ops")] == [
        ("SYN01", "D1"),
        ("SYN02", "D2"),
    ]
    assert page.evaluate("ops[1].words") == "Only second-item answer"
    assert "Synthetic observation" not in page.evaluate("ops[1].words")


def test_each_selected_item_confirms_its_own_reading_without_copying_primary_number(browser_page):
    page = browser_page
    load(page, reading=0, second_reading=8)
    choose(page, 0)
    page.locator("[data-reading-confirm]").check()
    page.wait_for_function("levelCalls.length === 1")
    resolve(page, level="D1")
    confirm_assignment(page, 1)
    page.locator(".walk-found__row").filter(has_text="Synthetic second item").locator(
        ".walk-found__also"
    ).click()
    extra = page.locator('[data-class-review="SYN02"]')
    assert extra.locator("[data-extra-reading]").input_value() == "8"
    assert page.evaluate("levelCalls.length") == 1
    extra.locator("[data-extra-reading]").fill("9")
    extra.locator("[data-extra-reading-confirm]").check()
    page.wait_for_function("levelCalls.length === 2")
    assert page.evaluate("levelCalls[0].reading_c") == 0
    assert page.evaluate("levelCalls[0].reading_source") == "model"
    assert page.evaluate("levelCalls[1].reading_c") == 9
    assert page.evaluate("levelCalls[1].reading_source") == "human"
    resolve(page, 1, level="D2")
    page.get_by_role("button", name="Save 2", exact=True).click()
    page.wait_for_function("ops.length === 2")
    assert [op["reading_c"] for op in page.evaluate("ops")] == [0, 9]


def test_endpoint_failure_keeps_explicit_manual_class_available(browser_page):
    page = browser_page
    load(page)
    choose(page, 0)
    page.wait_for_function("levelCalls.length === 1")
    page.evaluate(
        "levelReply(0,{status:'unavailable',level:null,message:'Synthetic unavailable'},false)"
    )
    assert "Synthetic unavailable" in page.locator("[data-class-feedback]").inner_text()
    assert page.get_by_role("button", name="Save", exact=True).is_disabled()
    page.get_by_role("button", name="walk.sheet.class_review.manual", exact=True).click()
    page.locator('[data-manual-class="D2"]').click()
    page.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_function("ops.length === 1")
    assert page.evaluate("ops[0].level") == "D2"


def test_saved_human_facts_restore_only_for_the_same_item_and_evidence(browser_page):
    page = browser_page
    load(page)
    choose(page, 0)
    page.locator(".walk-class-review__facts").fill("Saved human fact")
    page.evaluate("window.savedDraft=JSON.parse(JSON.stringify(lastDraft))")
    page.evaluate("""() => {
      const W=DecimusWalk; W.sheet.close(true);
      W.local.get=key=>key==='synthetic_draft'?savedDraft:null;
      W.sheet.open({mode:'violation'});
    }""")
    assert page.locator(".walk-class-review__facts").input_value() == "Saved human fact"
    page.evaluate("""() => {
      DecimusWalk.sheet.close(true);
      savedDraft.photos=['another-synthetic-ref'];
      DecimusWalk.sheet.open({mode:'violation'});
    }""")
    assert page.locator(".walk-class-review__facts").input_value() == ""
    recovery = page.locator("[data-class-feedback] details")
    recovery.locator("summary").click()
    assert "Saved human fact" in recovery.inner_text()
    recovery.get_by_role(
        "button", name="walk.sheet.class_review.use_saved_facts", exact=True
    ).click()
    assert page.locator(".walk-class-review__facts").input_value() == "Saved human fact"


def test_information_candidate_does_not_enter_normative_class_endpoint(browser_page):
    page = browser_page
    info = {**card("zone_a", "Synthetic reading"), "code": "SYN03", "level": "D0", "reading_c": 0}
    items = [
        {
            "code": "SYN03",
            "q": "Synthetic measurement",
            "label": "Reading 1",
            "process": "Readings",
            "levels": ["D0"],
            "zones": ["zone_a"],
            "measure": True,
        }
    ]
    load_sheet(page, [info], choose=True, confirm=False, items=items, defer_levels=True)
    assert page.evaluate("levelCalls") == []
    page.locator("[data-reading-confirm]").check()
    assert page.evaluate("levelCalls") == []
    page.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_function("ops.length === 1")
    assert page.evaluate("ops[0].level") == "D0"
    assert page.evaluate("ops[0].reading_c") == 0


def test_repeated_clarification_chain_stays_scoped_and_is_saved_as_human_evidence(browser_page):
    page = browser_page
    load(page)
    choose(page, 0)
    resolve(page, status="needs_fact", level=None, need_fact="First synthetic question?")
    page.locator(".walk-class-review__facts").fill("First human answer")
    page.locator("[data-class-check]").click()
    page.wait_for_function("levelCalls.length === 2")
    resolve(page, 1, status="needs_fact", level=None, need_fact="Second synthetic question?")
    assert page.locator(".walk-class-review__facts").input_value() == ""
    page.locator(".walk-class-review__facts").fill("Second human answer")
    page.locator("[data-class-check]").click()
    page.wait_for_function("levelCalls.length === 3")
    chain = [
        {"question": "First synthetic question?", "answer": "First human answer"},
        {"question": "Second synthetic question?", "answer": "Second human answer"},
    ]
    assert page.evaluate("levelCalls[2].clarifications") == chain
    assert page.evaluate("levelCalls[2].words") == "Synthetic observation"
    resolve(page, 2, level="D1")
    page.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_function("ops.length === 1")
    assert page.evaluate("ops[0].class_context") == {
        "clarifications": chain,
        "run_id": "synthetic-run",
        "checklist_version": "synthetic-edition",
        "code": "SYN01",
        "zone": "zone_a",
        "photo_refs": ["synthetic-ref"],
    }
    assert (
        page.evaluate("ops[0].words")
        == "Synthetic observation\nFirst human answer\nSecond human answer"
    )
    assert "question" not in page.evaluate("ops[0].words")


def test_not_established_does_not_create_d0_or_coarse_fallback(browser_page):
    page = browser_page
    load(page)
    choose(page, 0)
    resolve(
        page,
        status="not_established",
        level=None,
        provisional_level=None,
        need_fact=None,
        reason="Synthetic facts do not establish this violation",
    )
    assert (
        "walk.sheet.class_review.not_established"
        in page.locator("[data-class-feedback]").inner_text()
    )
    assert page.get_by_role("button", name="Save", exact=True).is_disabled()
    page.get_by_role("button", name="walk.sheet.class_review.manual", exact=True).click()
    page.locator('[data-manual-class="D1"]').click()
    page.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_function("ops.length === 1")
    assert page.evaluate("ops[0].level") == "D1"


@pytest.mark.parametrize("invalid", [{"clarifications": []}, {"clarification_hash": ""}])
def test_mismatched_clarification_response_cannot_assign_class(browser_page, invalid):
    page = browser_page
    load(page)
    choose(page, 0)
    resolve(page, status="needs_fact", level=None, need_fact="Scoped question?")
    page.locator(".walk-class-review__facts").fill("Scoped answer")
    page.locator("[data-class-check]").click()
    page.wait_for_function("levelCalls.length === 2")
    resolve(page, 1, **invalid)
    assert page.get_by_role("button", name="Save", exact=True).is_disabled()


def test_changed_facts_require_explicit_review_before_reusing_chain(browser_page):
    page = browser_page
    load(page)
    choose(page, 0)
    resolve(page, status="needs_fact", level=None, need_fact="Question about original facts?")
    page.locator(".walk-class-review__facts").fill("Answer about original facts")
    page.locator("[data-class-check]").click()
    page.wait_for_function("levelCalls.length === 2")
    resolve(page, 1, level="D1")
    page.locator(".walk-area--words").fill("Changed human observation")
    assert page.locator("[data-class-check]").is_disabled()
    assert page.get_by_role("button", name="Save", exact=True).is_disabled()
    confirm_assignment(page, 0)
    page.get_by_role("button", name="walk.sheet.class_review.reaffirm", exact=True).click()
    page.locator("[data-class-check]").click()
    page.wait_for_function("levelCalls.length === 3")
    assert page.evaluate("levelCalls[2].words") == "Changed human observation"
    assert page.evaluate("levelCalls[2].clarifications[0].answer") == "Answer about original facts"


def test_chain_uses_one_bounded_budget_without_sending_a_partial_answer(browser_page):
    page = browser_page
    load(page)
    choose(page, 0)
    resolve(page, status="needs_fact", level=None, need_fact="Synthetic question?")
    page.locator(".walk-class-review__facts").fill("x" * 990)
    assert page.locator("[data-class-check]").is_disabled()
    assert page.get_by_role("button", name="Save", exact=True).is_disabled()
    assert page.evaluate("levelCalls.length") == 1
    assert page.locator(".walk-class-review__facts").input_value() == "x" * 990


def test_chain_survives_reload_without_restoring_a_model_class(browser_page):
    page = browser_page
    load(page)
    choose(page, 0)
    resolve(page, status="needs_fact", level=None, need_fact="Synthetic saved question?")
    page.locator(".walk-class-review__facts").fill("Saved human answer")
    page.locator("[data-class-check]").click()
    page.wait_for_function("levelCalls.length === 2")
    resolve(page, 1, level="D1")
    page.evaluate("window.savedDraft=JSON.parse(JSON.stringify(lastDraft))")
    page.evaluate("""() => {
      const W=DecimusWalk; W.sheet.close(true);
      W.local.get=key=>key==='synthetic_draft'?savedDraft:null;
      W.sheet.open({mode:'violation'});
    }""")
    assert page.get_by_role("button", name="Save", exact=True).is_disabled()
    page.locator("[data-class-feedback] summary").first.click()
    assert "Saved human answer" in page.locator("[data-class-feedback]").inner_text()
    page.locator("[data-class-check]").click()
    page.wait_for_function("levelCalls.length === 3")
    assert page.evaluate("levelCalls[2].clarifications") == [
        {"question": "Synthetic saved question?", "answer": "Saved human answer"}
    ]


def test_primary_violation_blank_text_cannot_save_a_checklist_question(browser_page):
    page = browser_page
    load(page)
    choose(page, 0)
    resolve(page, level="D1")
    editor = page.locator("[data-finding-text]")
    editor.fill("   ")
    assert page.get_by_role("button", name="Save", exact=True).is_disabled()
    editor.fill("Human observed condition")
    page.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_function("ops.length === 1")
    assert page.evaluate("ops[0].text") == "Human observed condition"


def test_extra_finding_exposes_full_independent_editable_description(browser_page):
    page = browser_page
    load(page)
    choose(page, 0)
    resolve(page, level="D1")
    confirm_assignment(page, 1)
    page.locator(".walk-found__row").filter(has_text="Synthetic second item").locator(
        ".walk-found__also"
    ).click()
    page.wait_for_function("levelCalls.length === 2")
    resolve(page, 1, level="D2")
    editor = page.locator('[data-extra-text="SYN02"]')
    assert editor.is_visible()
    assert editor.input_value() == "ANOTHER MODEL WORDING"
    editor.fill("")
    assert page.get_by_role("button", name="Save 2", exact=True).is_disabled()
    editor.fill("Human fact for second item only")
    assert page.evaluate("cards[1].wording") == "ANOTHER MODEL WORDING"
    page.get_by_role("button", name="Save 2", exact=True).click()
    page.wait_for_function("ops.length === 2")
    assert [op["text"] for op in page.evaluate("ops")] == [
        "MODEL WORDING MUST NOT BECOME FACTS",
        "Human fact for second item only",
    ]
