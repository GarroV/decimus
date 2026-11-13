"""CFT DOM evidence assignment: frame choice is the confirmation, stale mappings."""

# ruff: noqa: F811
from __future__ import annotations

import pytest
from test_web_proofread_browser import browser_page  # noqa: F401
from test_web_walk_candidate_identity_browser import card, load_sheet, row_for_zone

PHOTOS = ["synthetic-first-ref", "synthetic-second-ref"]


def candidates(second_indices=(1,), refs=PHOTOS):
    return [
        {
            **card("zone_a", "Synthetic A"),
            "frame_indices": [0],
            "frame_count": len(refs),
            "frame_refs": refs,
        },
        {
            **card("zone_b", "Synthetic B"),
            "frame_indices": list(second_indices),
            "frame_count": len(refs),
            "frame_refs": refs,
        },
    ]


def box(page, index):
    return page.locator("[data-photo-assignment]").nth(index)


def save_two(page):
    row_for_zone(page, "Zone B").locator(".walk-found__also").click()
    page.get_by_role("button", name="Save 2", exact=True).click()
    page.wait_for_function("ops.length === 2 && !document.querySelector('.walk-sheet')")
    return page.evaluate("ops")


@pytest.mark.parametrize("source", [PHOTOS, [PHOTOS[0], PHOTOS[0], PHOTOS[1]]])
def test_each_finding_receives_only_its_confirmed_model_frames(browser_page, source):
    page = browser_page
    load_sheet(page, candidates(), photos=source, confirm=False)
    assert box(page, 0).locator('[data-frame-index="0"]').is_checked()
    assert not box(page, 0).locator('[data-frame-index="1"]').is_checked()
    assert page.get_by_role("button", name="Save", exact=True).is_enabled()
    assert row_for_zone(page, "Zone B").locator(".walk-found__also").is_enabled()
    assert page.locator("[data-photo-confirm]").count() == 0
    ops = save_two(page)
    assert [op["photos"] for op in ops] == [[PHOTOS[0]], [PHOTOS[1]]]
    assert [op["photo_assignment"]["model_frame_indices"] for op in ops] == [[0], [1]]
    assert [op["photo_assignment"]["assigned_frame_indices"] for op in ops] == [[0], [1]]


def test_unknown_model_evidence_requires_manual_selection_and_can_be_shared(browser_page):
    page = browser_page
    load_sheet(page, candidates((True,)), photos=PHOTOS, confirm=False)
    assert box(page, 1).locator("input[data-frame-index]:checked").count() == 0
    assert row_for_zone(page, "Zone B").locator(".walk-found__also").is_disabled()
    # The auditor deliberately assigns the same supporting frame to both findings.
    box(page, 1).locator('[data-frame-index="0"]').check()
    ops = save_two(page)
    assert [op["photos"] for op in ops] == [[PHOTOS[0]], [PHOTOS[0]]]
    assert ops[1]["photo_assignment"]["model_frame_indices"] is None
    assert ops[1]["photo_assignment"]["assigned_frame_indices"] == [0]


THREE = [*PHOTOS, "synthetic-third-ref"]


def test_removing_a_photo_invalidates_index_mapping_instead_of_reusing_index_zero(browser_page):
    page = browser_page
    load_sheet(page, candidates(refs=THREE), photos=THREE, confirm=False)
    page.get_by_role("button", name="Remove frame 0", exact=True).click()
    assert box(page, 0).locator("input[data-frame-index]:checked").count() == 0
    assert box(page, 1).locator("input[data-frame-index]:checked").count() == 0
    assert page.get_by_role("button", name="Save", exact=True).is_disabled()
    assert page.evaluate("ops") == []
    box(page, 0).locator('[data-frame-index="0"]').check()
    page.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_function("ops.length === 1")
    op = page.evaluate("ops[0]")
    assert op["photos"] == [THREE[1]]
    assert op["photo_assignment"]["model_source_photos"] == THREE
    assert op["photo_assignment"]["model_frame_indices"] == [0]
    assert op["photo_assignment"]["source_photos"] == THREE[1:]
    assert op["photo_assignment"]["assigned_frame_indices"] == [0]


def test_one_frame_is_assigned_to_every_selected_finding_without_any_action(browser_page):
    page = browser_page
    one = [PHOTOS[0]]
    load_sheet(page, candidates(refs=one), photos=one, confirm=False)
    assert page.locator("[data-photo-assignment]").count() == 0
    assert page.locator("[data-photo-confirm]").count() == 0
    assert page.get_by_role("button", name="Save", exact=True).is_enabled()
    assert row_for_zone(page, "Zone B").locator(".walk-found__also").is_enabled()
    ops = save_two(page)
    assert [op["photos"] for op in ops] == [one, one]
    assert ops[1]["photo_assignment"]["assigned_frame_indices"] == [0]
    assert ops[1]["photo_assignment"]["confirmed"] is True


def test_editing_words_resets_assignment_without_modifying_raw_proposal(browser_page):
    page = browser_page
    load_sheet(page, candidates(), photos=PHOTOS, confirm=False)
    page.locator(".walk-area--words").fill("Changed synthetic words")
    assert box(page, 0).locator("input[data-frame-index]:checked").count() == 0
    assert page.get_by_role("button", name="Save", exact=True).is_disabled()
    assert page.evaluate("cards[0].frame_indices") == [0]
    assert page.evaluate("ops") == []


def test_existing_primary_receives_only_its_assigned_new_frame(browser_page):
    page = browser_page
    load_sheet(page, candidates(), photos=PHOTOS, confirm=False)
    page.evaluate("DecimusWalk.state.data.zones[0].recorded = [{n:1, code:'SYN01',level:'D1'}]")
    ops = save_two(page)
    assert ops[0]["op"] == "attach"
    assert ops[0]["n"] == 1 and ops[0]["ref"] == PHOTOS[0]
    assert ops[0]["photo_assignment"]["assigned_frame_indices"] == [0]
    assert ops[1]["op"] == "add" and ops[1]["photos"] == [PHOTOS[1]]


def test_new_search_with_same_photos_needs_a_new_frame_choice(browser_page):
    page = browser_page
    cards = candidates()
    cards[0]["reading_c"] = 5
    load_sheet(page, cards, photos=PHOTOS, confirm=False)
    box(page, 0).locator('[data-frame-index="1"]').check()
    page.locator(".walk-area--words").fill("New synthetic search facts")
    page.get_by_role("button", name="walk.sheet.find_again", exact=True).click()
    page.locator(".walk-found__card").first.click()
    # The earlier manual choice is gone; only the new run's proposal is pre-filled.
    assert box(page, 0).locator('[data-frame-index="0"]').is_checked()
    assert not box(page, 0).locator('[data-frame-index="1"]').is_checked()
    assert page.evaluate("ops") == []


def test_single_manual_finding_does_not_require_second_photo_confirmation(browser_page):
    page = browser_page
    load_sheet(page, candidates(), photos=PHOTOS, confirm=False)
    page.evaluate("""() => {
      const W = DecimusWalk;
      W.sheet.close(true);
      W.local.get = () => ({run_id:'synthetic-run',mode:'violation',
        queued:['synthetic-first-ref','synthetic-second-ref']});
      W.sheet.open({mode:'violation',code:'SYN01',level:'D1',zone:'zone_a'});
    }""")
    assert page.locator("[data-photo-assignment]").count() == 0
    page.get_by_role("button", name="walk.sheet.class_review.manual", exact=True).click()
    page.locator('[data-manual-class="D1"]').click()
    page.locator("[data-finding-text]").fill("Synthetic human observation")
    page.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_function("ops.length === 1")
    assert page.evaluate("ops[0].photos") == PHOTOS
    assert page.evaluate("ops[0].photo_assignment") is None
