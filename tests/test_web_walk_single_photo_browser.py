"""Одна выбранная запись не превращается в распределение фото между вариантами модели."""

# ruff: noqa: F811
from __future__ import annotations

import pytest
from playwright.sync_api import expect
from test_web_proofread_browser import ROOT, browser_page  # noqa: F401
from test_web_walk_candidate_identity_browser import card, load_sheet, row_for_zone

PHOTOS = ["synthetic-first-ref", "synthetic-second-ref"]


@pytest.mark.parametrize("photos", [[PHOTOS[0]], PHOTOS])
@pytest.mark.parametrize("chosen", [0, 1])
def test_one_selected_finding_uses_uploaded_photos_without_second_confirmation(
    browser_page, photos, chosen
):
    page = browser_page
    page.set_viewport_size({"width": 390, "height": 844})
    proposals = [
        {
            **card(zone, words),
            "frame_indices": [0],
            "frame_count": len(photos),
            "frame_refs": photos,
        }
        for zone, words in [("zone_a", "Synthetic A"), ("zone_b", "Synthetic B")]
    ]
    load_sheet(page, proposals, photos=photos, confirm=False)
    if chosen:
        row_for_zone(page, "Zone B").locator(".walk-found__card").click()
    for css in ("dodo-ds.css", "decimus-domain.css", "walk.css", "walk-record.css", "walk-ux.css"):
        page.add_style_tag(path=str(ROOT / "src/web/static" / css))
    assert page.locator("[data-photo-assignment]").count() == 0
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    save = page.get_by_role("button", name="Save", exact=True)
    expect(save).to_be_enabled()
    save.click()
    page.wait_for_function("ops.length === 1 && !document.querySelector('.walk-sheet')")
    op = page.evaluate("ops[0]")
    assert op["photos"] == photos
    assert op["zone"] == ("zone_b" if chosen else "zone_a")
    assert op["photo_assignment"] is None


def test_selecting_then_removing_an_extra_restores_simple_single_finding(browser_page):
    page = browser_page
    load_sheet(
        page,
        [card("zone_a", "Synthetic A"), card("zone_b", "Synthetic B")],
        photos=PHOTOS,
        confirm=False,
    )
    extra = row_for_zone(page, "Zone B").locator(".walk-found__also")
    expect(extra).to_be_enabled()
    extra.click()
    assert page.locator("[data-photo-assignment]").count() == 2
    expect(page.get_by_role("button", name="Save 2", exact=True)).to_be_disabled()
    row_for_zone(page, "Zone B").locator(".walk-found__also").click()
    assert page.locator("[data-photo-assignment]").count() == 0
    save = page.get_by_role("button", name="Save", exact=True)
    expect(save).to_be_enabled()
    save.click()
    page.wait_for_function("ops.length === 1")
    assert page.evaluate("ops[0].photos") == PHOTOS


def test_unselected_alternatives_do_not_get_photo_assignment_controls(browser_page):
    page = browser_page
    items = [
        {
            "code": code,
            "q": "Synthetic item " + code,
            "process": "Synthetic",
            "levels": ["D1"],
            "zones": ["zone_a"],
            "measure": False,
        }
        for code in ["SYN01", "SYN02", "SYN03"]
    ]
    proposals = [
        {**card("zone_a", "Synthetic fact " + i["code"]), "code": i["code"]} for i in items
    ]
    load_sheet(page, proposals, photos=[PHOTOS[0]], items=items, confirm=False)
    assert page.locator("[data-photo-assignment]").count() == 0
    page.locator(".walk-found__row").filter(has_text="Synthetic item SYN02").locator(
        ".walk-found__also"
    ).click()
    assert page.locator("[data-photo-assignment]").evaluate_all(
        "boxes => boxes.map(box => box.dataset.photoAssignment)"
    ) == ["SYN01", "SYN02"]
    expect(page.get_by_role("button", name="Save 2", exact=True)).to_be_disabled()
