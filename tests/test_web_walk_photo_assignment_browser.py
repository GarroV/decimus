"""CFT DOM evidence assignment: explicit confirmation, stale mappings, shared evidence."""

# ruff: noqa: F811
from __future__ import annotations

import pytest
from test_web_proofread_browser import browser_page  # noqa: F401
from test_web_walk_candidate_identity_browser import card, load_sheet, row_for_zone

PHOTOS = ["synthetic-first-ref", "synthetic-second-ref"]


def candidates(second_indices=(1,)):
    return [
        {
            **card("zone_a", "Synthetic A"),
            "frame_indices": [0],
            "frame_count": 2,
            "frame_refs": PHOTOS,
        },
        {
            **card("zone_b", "Synthetic B"),
            "frame_indices": list(second_indices),
            "frame_count": 2,
            "frame_refs": PHOTOS,
        },
    ]


def box(page, index):
    return page.locator("[data-photo-assignment]").nth(index)


def confirm(page, index):
    box(page, index).locator("[data-photo-confirm]").check()


def save_two(page):
    row_for_zone(page, "Zone B").locator(".walk-found__also").click()
    page.get_by_role("button", name="Save 2", exact=True).click()
    page.wait_for_function("ops.length === 2")
    return page.evaluate("ops")


@pytest.mark.parametrize("source", [PHOTOS, [PHOTOS[0], PHOTOS[0], PHOTOS[1]]])
def test_each_finding_receives_only_its_confirmed_model_frames(browser_page, source):
    page = browser_page
    load_sheet(page, candidates(), photos=source, confirm=False)
    assert box(page, 0).locator('[data-frame-index="0"]').is_checked()
    assert not box(page, 0).locator('[data-frame-index="1"]').is_checked()
    assert page.get_by_role("button", name="Save", exact=True).is_disabled()
    assert row_for_zone(page, "Zone B").locator(".walk-found__also").is_disabled()
    confirm(page, 0)
    confirm(page, 1)
    ops = save_two(page)
    assert [op["photos"] for op in ops] == [[PHOTOS[0]], [PHOTOS[1]]]
    assert [op["photo_assignment"]["model_frame_indices"] for op in ops] == [[0], [1]]
    assert [op["photo_assignment"]["assigned_frame_indices"] for op in ops] == [[0], [1]]


def test_unknown_model_evidence_requires_manual_selection_and_can_be_shared(browser_page):
    page = browser_page
    load_sheet(page, candidates((True,)), photos=PHOTOS, confirm=False)
    assert box(page, 1).locator("[data-photo-confirm]").is_disabled()
    assert box(page, 1).locator("input[data-frame-index]:checked").count() == 0
    confirm(page, 0)
    # The auditor deliberately assigns the same supporting frame to both findings.
    box(page, 1).locator('[data-frame-index="0"]').check()
    confirm(page, 1)
    ops = save_two(page)
    assert [op["photos"] for op in ops] == [[PHOTOS[0]], [PHOTOS[0]]]
    assert ops[1]["photo_assignment"]["model_frame_indices"] is None
    assert ops[1]["photo_assignment"]["assigned_frame_indices"] == [0]


def test_removing_a_photo_invalidates_index_mapping_instead_of_reusing_index_zero(browser_page):
    page = browser_page
    load_sheet(page, candidates(), photos=PHOTOS, confirm=False)
    confirm(page, 0)
    confirm(page, 1)
    page.get_by_role("button", name="Remove frame 0", exact=True).click()
    assert box(page, 0).locator("input[data-frame-index]:checked").count() == 0
    assert box(page, 1).locator("input[data-frame-index]:checked").count() == 0
    assert page.get_by_role("button", name="Save", exact=True).is_disabled()
    assert page.evaluate("ops") == []
    box(page, 0).locator('[data-frame-index="0"]').check()
    confirm(page, 0)
    page.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_function("ops.length === 1")
    op = page.evaluate("ops[0]")
    assert op["photos"] == [PHOTOS[1]]
    assert op["photo_assignment"]["model_source_photos"] == PHOTOS
    assert op["photo_assignment"]["model_frame_indices"] == [0]
    assert op["photo_assignment"]["source_photos"] == [PHOTOS[1]]
    assert op["photo_assignment"]["assigned_frame_indices"] == [0]


def test_editing_words_resets_confirmation_without_modifying_raw_proposal(browser_page):
    page = browser_page
    load_sheet(page, candidates(), photos=PHOTOS, confirm=False)
    confirm(page, 0)
    page.locator(".walk-area--words").fill("Changed synthetic words")
    assert box(page, 0).locator("input[data-frame-index]:checked").count() == 0
    assert page.get_by_role("button", name="Save", exact=True).is_disabled()
    assert page.evaluate("cards[0].frame_indices") == [0]
    assert page.evaluate("ops") == []


def test_existing_primary_receives_only_its_assigned_new_frame(browser_page):
    page = browser_page
    load_sheet(page, candidates(), photos=PHOTOS, confirm=False)
    page.evaluate("DecimusWalk.state.data.zones[0].recorded = [{n:1, code:'SYN01',level:'D1'}]")
    confirm(page, 0)
    confirm(page, 1)
    ops = save_two(page)
    assert ops[0]["op"] == "attach"
    assert ops[0]["n"] == 1 and ops[0]["ref"] == PHOTOS[0]
    assert ops[0]["photo_assignment"]["assigned_frame_indices"] == [0]
    assert ops[1]["op"] == "add" and ops[1]["photos"] == [PHOTOS[1]]


def test_new_search_with_same_photos_needs_a_new_confirmation(browser_page):
    page = browser_page
    cards = candidates()
    cards[0]["reading_c"] = 5
    load_sheet(page, cards, photos=PHOTOS, confirm=False)
    confirm(page, 0)
    page.locator(".walk-area--words").fill("New synthetic search facts")
    page.get_by_role("button", name="walk.sheet.find_again", exact=True).click()
    page.locator(".walk-found__card").first.click()
    assert not box(page, 0).locator("[data-photo-confirm]").is_checked()
    assert page.get_by_role("button", name="Save", exact=True).is_disabled()
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
    page.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_function("ops.length === 1")
    assert page.evaluate("ops[0].photos") == PHOTOS
    assert page.evaluate("ops[0].photo_assignment") is None
