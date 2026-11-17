"""Selected findings and human evidence survive the real browser draft boundary."""

# ruff: noqa: F811
from __future__ import annotations

import pytest
from playwright.sync_api import expect
from test_web_proofread_browser import ROOT, browser_page  # noqa: F401
from test_web_walk_candidate_identity_browser import load_sheet, row_for_zone
from test_web_walk_photo_assignment_browser import PHOTOS, box, candidates, confirm, save_two


@pytest.fixture(autouse=True)
def no_browser_errors(browser_page):
    errors = []
    browser_page.on("pageerror", lambda error: errors.append(str(error)))
    yield
    assert not errors, errors


def storage_boundary(page):
    # Retain only the synthetic HTTP/photo adapters; localStorage is production.
    page.evaluate("""() => {
      window.draftBoundary = Object.assign({}, DecimusWalk);
      delete draftBoundary.local;
    }""")
    page.add_script_tag(path=str(ROOT / "src/web/static/walk-core.js"))
    page.evaluate("Object.assign(DecimusWalk, draftBoundary)")


def begin(page, *, cards=None, width=390):
    page.set_viewport_size({"width": width, "height": 844})
    page.route(
        "https://draft.invalid/**",
        lambda route: route.fulfill(status=200, content_type="text/html", body="<html></html>"),
    )
    page.goto("https://draft.invalid/walk")
    load_sheet(page, cards or candidates(), photos=PHOTOS, confirm=False)
    storage_boundary(page)
    row_for_zone(page, "Zone B").locator(".walk-found__also").click()
    confirm(page, 0)
    confirm(page, 1)


def styles(page):
    for css in ("dodo-ds.css", "decimus-domain.css", "walk.css", "walk-record.css", "walk-ux.css"):
        page.add_style_tag(path=str(ROOT / "src/web/static" / css))


def reopen(page, *, reload=False, mutate=""):
    if reload:
        page.reload()
        load_sheet(page, candidates(), photos=PHOTOS, confirm=False, choose=False)
        storage_boundary(page)
    page.evaluate("DecimusWalk.sheet.close(true)")
    if mutate:
        page.evaluate(mutate)
    page.evaluate("DecimusWalk.sheet.open({hint:'zone_a'})")
    styles(page)


def check_classes(page):
    for check in page.locator("[data-class-check]").all():
        if check.is_enabled():
            check.click()


@pytest.mark.parametrize("width", [390, 1440])
@pytest.mark.parametrize("reload", [False, True])
def test_selected_findings_keep_separate_confirmed_photos_and_human_facts(
    browser_page, width, reload
):
    page = browser_page
    begin(page, width=width)
    page.locator("[data-finding-text]").fill("Auditor primary observation")
    page.locator("[data-extra-text]").fill("Auditor additional observation")
    page.locator(".walk-class-review__facts").first.fill("Auditor additional fact")
    check_classes(page)
    expect(page.get_by_role("button", name="Save 2", exact=True)).to_be_enabled()
    reopen(page, reload=reload)
    assert page.get_by_text("walk.sheet.restored", exact=True).is_visible()
    assert (
        row_for_zone(page, "Zone B").locator(".walk-found__also").get_attribute("aria-pressed")
        == "true"
    )
    for index in range(2):
        assert box(page, index).locator(f'[data-frame-index="{index}"]').is_checked()
        assert not box(page, index).locator(f'[data-frame-index="{1 - index}"]').is_checked()
        assert box(page, index).locator("[data-photo-confirm]").is_checked()
    assert page.locator("[data-finding-text]").input_value() == "Auditor primary observation"
    assert page.locator("[data-extra-text]").input_value() == "Auditor additional observation"
    # Model output is never revived as a confirmed class by a stored draft.
    expect(page.get_by_role("button", name="Save 2", exact=True)).to_be_disabled()
    assert page.evaluate("ops") == []
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    check_classes(page)
    operations = save_two(page)
    assert [op["zone"] for op in operations] == ["zone_a", "zone_b"]
    assert [op["photos"] for op in operations] == [[PHOTOS[0]], [PHOTOS[1]]]
    assert [op["text"] for op in operations] == [
        "Auditor primary observation",
        "Auditor additional observation",
    ]
    assert operations[1]["words"] == "Auditor additional fact"
    assert page.evaluate("localStorage.getItem('synthetic_draft')") is None


def test_scoped_manual_classes_survive_and_removing_extra_returns_to_single_flow(browser_page):
    page = browser_page
    begin(page)
    for panel in page.locator("[data-class-review]").all():
        panel.locator("[data-class-manual]").click()
        panel.locator('[data-manual-class="D1"]').click()
    calls = page.evaluate("levelCalls.length")
    reopen(page, reload=True)
    expect(page.get_by_role("button", name="Save 2", exact=True)).to_be_enabled()
    assert page.evaluate("levelCalls.length") == 0
    assert calls > 0
    row_for_zone(page, "Zone B").locator(".walk-found__also").click()
    assert page.locator("[data-photo-assignment]").count() == 0
    expect(page.get_by_role("button", name="Save", exact=True)).to_be_enabled()
    # Closing after deselection cannot revive the former additional record.
    reopen(page)
    assert page.locator("[data-photo-assignment]").count() == 0
    assert page.locator('.walk-found__also[aria-pressed="true"]').count() == 0
    check_classes(page)
    page.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_function("ops.length === 1 && !document.querySelector('.walk-sheet')")
    assert page.evaluate("ops[0].photos") == PHOTOS
    assert page.evaluate("ops[0].photo_assignment") is None


@pytest.mark.parametrize("invalid", ["run", "edition", "key", "schema", "zone"])
def test_selection_from_another_context_is_not_revived(browser_page, invalid):
    page = browser_page
    begin(page)
    mutate = {
        "run": "DecimusWalk.state.data.run_id='another-run'",
        "edition": "DecimusWalk.state.data.checklist_version='another-edition'",
        "key": (
            "const d=DecimusWalk.local.get('synthetic_draft');d.selection.key='another_draft';"
            "DecimusWalk.local.set('synthetic_draft',d)"
        ),
        "schema": (
            "const d=DecimusWalk.local.get('synthetic_draft');d.selection.version=0;"
            "DecimusWalk.local.set('synthetic_draft',d)"
        ),
        "zone": "DecimusWalk.state.data.zones.pop()",
    }[invalid]
    reopen(page, mutate="() => {" + mutate + "}")
    assert page.locator("[data-photo-assignment]").count() == 0
    assert page.locator('.walk-found__also[aria-pressed="true"]').count() == 0
    assert page.get_by_role("button", name="Save 2", exact=True).count() == 0
    assert page.evaluate("ops") == []


@pytest.mark.parametrize("changed", ["photos", "words"])
def test_changed_draft_evidence_keeps_selection_but_requires_fresh_photo_review(
    browser_page, changed
):
    page = browser_page
    begin(page)
    mutate = """() => {
      const W=DecimusWalk,d=W.local.get('synthetic_draft');
      CHANGE
      W.local.set('synthetic_draft',d);
    }""".replace(
        "CHANGE",
        "d.photos=[d.photos[1]];" if changed == "photos" else "d.words='Changed human facts';",
    )
    reopen(page, mutate=mutate)
    assert (
        row_for_zone(page, "Zone B").locator(".walk-found__also").get_attribute("aria-pressed")
        == "true"
    )
    assert page.locator("[data-photo-confirm]:checked").count() == 0
    assert page.locator("[data-frame-index]:checked").count() == 0
    assert page.get_by_text("walk.sheet.found_stale", exact=False).is_visible()
    assert page.get_by_role("button", name="Save", exact=True).is_disabled()
    assert page.evaluate("ops") == []
    if changed == "photos":
        # A selection snapshot cannot manufacture a removed/expired photo receipt.
        assert page.get_by_role("button", name="Remove frame 1", exact=True).count() == 0


def test_partly_reviewed_photo_mapping_does_not_become_confirmed_on_reload(browser_page):
    page = browser_page
    begin(page)
    box(page, 1).locator('[data-frame-index="1"]').uncheck()
    box(page, 1).locator('[data-frame-index="0"]').check()
    reopen(page, reload=True)
    assert box(page, 0).locator("[data-photo-confirm]").is_checked()
    assert box(page, 1).locator('[data-frame-index="0"]').is_checked()
    assert not box(page, 1).locator('[data-frame-index="1"]').is_checked()
    assert not box(page, 1).locator("[data-photo-confirm]").is_checked()
    expect(page.get_by_role("button", name="Save 2", exact=True)).to_be_disabled()
    check_classes(page)
    expect(page.get_by_role("button", name="Save 2", exact=True)).to_be_disabled()
    confirm(page, 1)
    operations = save_two(page)
    assert [op["photos"] for op in operations] == [[PHOTOS[0]], [PHOTOS[0]]]


def test_closed_form_model_reply_cannot_complete_restored_reviews(browser_page):
    page = browser_page
    begin(page)
    page.evaluate("window.deferLevels=true")
    check_classes(page)
    page.wait_for_function("levelPending.length===2")
    reopen(page)
    page.evaluate("levelReply(0);levelReply(1)")
    expect(page.get_by_role("button", name="Save 2", exact=True)).to_be_disabled()
    assert (
        page.locator("[data-class-feedback]")
        .filter(has_text="walk.sheet.class_review.proposed")
        .count()
        == 0
    )
    assert page.evaluate("ops") == []
    page.evaluate("window.deferLevels=false")
    check_classes(page)
    operations = save_two(page)
    assert [op["photos"] for op in operations] == [[PHOTOS[0]], [PHOTOS[1]]]


@pytest.mark.parametrize("expired", [False, True])
def test_receipt_restore_finishes_before_save_and_never_resurrects_expired_upload(
    browser_page, expired
):
    page = browser_page
    begin(page)
    for panel in page.locator("[data-class-review]").all():
        panel.locator("[data-class-manual]").click()
        panel.locator('[data-manual-class="D1"]').click()
    page.evaluate("DecimusWalk.sheet.close(true)")
    page.add_script_tag(path=str(ROOT / "src/web/static/walk-offline.js"))
    page.evaluate(
        """async expired => {
      const W=DecimusWalk, now=Date.now;
      if (expired) Date.now=()=>now()-4*24*60*60*1000;
      await W.offline.put('synthetic_draft','violation',
        new Blob(['pending synthetic bytes']),W.state.data.run_id);
      Date.now=now;
      W.photo.upload=()=>new Promise(()=>{});
      W.photo.remember=()=>{};
      const list=W.offline.list;
      W.offline.list=key=>list(key).then(rows=>new Promise(resolve=>{
        window.finishReceiptRestore=()=>{W.offline.list=list;resolve(rows);};
      }));
    }""",
        expired,
    )
    # Rebind the real offline callbacks to a fresh production sheet closure.
    page.add_script_tag(path=str(ROOT / "src/web/static/walk-sheet.js"))
    page.evaluate("DecimusWalk.sheet.open({hint:'zone_a'})")
    styles(page)
    expect(page.get_by_role("button", name="Save 2", exact=True)).to_be_disabled()
    page.wait_for_function("typeof finishReceiptRestore==='function'")
    page.evaluate("finishReceiptRestore()")
    if expired:
        expect(page.get_by_role("button", name="Save 2", exact=True)).to_be_enabled()
        assert page.get_by_role("button", name="Remove frame 2", exact=True).count() == 0
        operations = save_two(page)
        assert [op["photos"] for op in operations] == [[PHOTOS[0]], [PHOTOS[1]]]
    else:
        expect(page.get_by_role("button", name="Remove frame 2", exact=True)).to_be_visible()
        expect(page.get_by_role("button", name="Save 2", exact=True)).to_be_disabled()
        assert page.evaluate("ops") == []


def test_reselected_primary_and_explicit_human_zone_keep_their_own_photo_identity(browser_page):
    page = browser_page
    proposals = candidates()
    proposals[0]["resolution"] = {"zone": None, "source": "ask", "options": ["zone_a", "zone_b"]}
    begin(page, cards=proposals)
    page.locator(".walk-where").get_by_role("button", name="Zone A", exact=True).click()
    row_for_zone(page, "Zone B").locator(".walk-found__card").click()
    row_for_zone(page, "Zone A").locator(".walk-found__also").click()
    confirm(page, 0)
    confirm(page, 1)
    reopen(page, reload=True)
    assert (
        row_for_zone(page, "Zone A").locator(".walk-found__also").get_attribute("aria-pressed")
        == "true"
    )
    check_classes(page)
    operations = save_two(page)
    assert [op["zone"] for op in operations] == ["zone_b", "zone_a"]
    assert [op["photos"] for op in operations] == [[PHOTOS[1]], [PHOTOS[0]]]
    assert [op["suggested"]["zone"] for op in operations] == ["raw-model-zone", "raw-model-zone"]


def test_additional_clarification_chain_survives_without_importing_its_old_class(browser_page):
    page = browser_page
    begin(page)
    page.evaluate("window.deferLevels=true")
    page.locator("[data-class-check]").first.click()
    page.wait_for_function("levelPending.length===1")
    page.evaluate(
        "levelReply(0,{status:'needs_fact',level:null,need_fact:'Synthetic additional question?'})"
    )
    page.locator(".walk-class-review__facts").first.fill("Auditor additional answer")
    page.locator("[data-class-check]").first.click()
    page.wait_for_function("levelPending.length===2")
    page.evaluate("levelReply(1)")
    reopen(page, reload=True)
    expect(page.get_by_role("button", name="Save 2", exact=True)).to_be_disabled()
    check_classes(page)
    operations = save_two(page)
    assert operations[1]["words"] == "Auditor additional answer"
    assert operations[1]["class_context"]["clarifications"] == [
        {"question": "Synthetic additional question?", "answer": "Auditor additional answer"}
    ]
    assert operations[0].get("class_context") is None


def test_manual_primary_and_selected_additional_record_restore_as_two_findings(browser_page):
    page = browser_page
    begin(page)
    page.add_script_tag(path=str(ROOT / "src/web/static/walk-menu.js"))
    page.evaluate("DecimusWalk.menu.search=opts=>window.manualMenu=opts")
    page.get_by_role("button", name="walk.sheet.pick_manual", exact=True).click()
    page.evaluate("manualMenu.onPick('SYN01')")
    box(page, 0).locator('[data-frame-index="0"]').check()
    confirm(page, 0)
    reopen(page, reload=True)
    assert page.locator('.walk-found__also[aria-pressed="true"]').count() == 1
    assert page.locator("[data-photo-confirm]:checked").count() == 2
    check_classes(page)
    operations = save_two(page)
    assert [op["zone"] for op in operations] == ["zone_a", "zone_b"]
    assert [op["photos"] for op in operations] == [[PHOTOS[0]], [PHOTOS[1]]]
