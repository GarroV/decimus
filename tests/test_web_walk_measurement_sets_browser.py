"""Product/line editing in static CFT DOM; synthetic responses, no server or LLM."""

# ruff: noqa: F811
from __future__ import annotations

import pytest
from test_web_proofread_browser import ROOT, browser_page  # noqa: F401
from test_web_walk_class_review_browser import choose, load, resolve


def setup(page):
    load(page)
    page.add_script_tag(path=str(ROOT / "src/web/static/walk-measurement-sets.js"))
    page.evaluate("""() => {
      const W=DecimusWalk;
      const revision='a'.repeat(64);
      const source=(n,zone,extra={})=>({n,zone,revision,code:'INF10',level:'D0',
        text:'Synthetic product reading '+n,words:'Human source facts',comment:'',
        reading_c:6,photos:[{ref:'synthetic-ref',own:false}],...extra});
      W.state.data.measurement_sets=[];
      W.state.data.zones[0].recorded=[source(1,'zone_a'),source(2,'zone_a'),
        source(4,'zone_a',{level:'D1'}),source(5,'zone_a',{reading_c:null})];
      W.state.data.zones[1].recorded=[source(3,'zone_b')];
      window.groupCalls=[];window.groupVersion=1;window.scopeVersion=1;
      const storage=new Map();
      W.local={get:k=>storage.has(k)?JSON.parse(storage.get(k)):null,
        set:(k,v)=>storage.set(k,JSON.stringify(v)),drop:k=>storage.delete(k)};
      const post=W.post;
      W.apply=body=>{W.state.data=body;};
      W.post=(url,body,...args)=>{
        if(url==='data')return Promise.resolve({ok:true,body:structuredClone(W.state.data)});
        if(body.op==='edit') {
          ops.push(structuredClone(body));
          return Promise.resolve({ok:true,body:structuredClone(W.state.data)});
        }
        if(body.op!=='measurement_set')return post(url,body,...args);
        groupCalls.push(structuredClone(body));
        if(window.refuseGroup)return Promise.resolve({ok:false,
          body:{message:'Synthetic set conflict'}});
        const value=structuredClone(body.measurement_set);
        let groups=W.state.data.measurement_sets.filter(g=>g.id!==value.id);
        if(!body.delete)groups.push({...value,revision:String(++groupVersion).padStart(64,'0'),stale:false});
        return Promise.resolve({ok:true,body:{...structuredClone(W.state.data),
          measurement_sets:groups}});
      };
      const result=window.levelResult;
      window.levelResult=(body,extra={})=>result(body,{
        ...(body.measurement_set_id?{measurement_context:{set_id:body.measurement_set_id,
          set_revision:body.measurement_set_revision,scope_hash:String(scopeVersion).padStart(64,'0')}}:{}),...extra});
    }""")
    choose(page, 0)
    resolve(page)


def manager(page):
    return page.locator('[data-measurement-manager="SYN01"]')


def create(page, *, label="Synthetic Line A", facts="Synthetic chilled product, observed now"):
    box = manager(page)
    box.locator("summary").click()
    box.get_by_role("button", name="walk.measurement.create", exact=True).click()
    box.get_by_role("textbox", name="walk.measurement.line", exact=True).fill(label)
    box.get_by_role("textbox", name="walk.measurement.product", exact=True).fill(
        "Synthetic product A"
    )
    box.get_by_role("textbox", name="walk.measurement.facts", exact=True).fill(facts)
    box.locator('[data-measurement-source="1"]').check()
    box.get_by_text("walk.measurement.confirm_product", exact=True).locator("..").locator(
        "input"
    ).check()
    box.locator("[data-measurement-confirm-set]").check()
    return box


def save_set(page):
    manager(page).get_by_role("button", name="walk.measurement.save", exact=True).click()
    page.wait_for_function(
        "groupCalls.length > 0 && DecimusWalk.state.data.measurement_sets.length > 0"
    )


def reselect_zone(page):
    # The selected card is a noninteractive <div>; its zone menu is the real
    # automatic class-review trigger (setZone -> requestClass).
    page.get_by_role("button", name="walk.sheet.zone: Zone A", exact=True).first.click()
    page.evaluate("menu.onPick('zone_a')")


def check_class(page, index=1, **result):
    page.locator("[data-class-check]").click()
    page.wait_for_function(f"levelCalls.length === {index + 1}")
    resolve(page, index, **result)


def test_explicit_product_and_line_can_be_saved_without_saving_violation(browser_page):
    page = browser_page
    setup(page)
    box = create(page)
    assert box.locator('[data-measurement-source="2"]').count() == 1
    assert box.locator('[data-measurement-source="3"]').count() == 0
    assert box.locator('[data-measurement-source="4"]').count() == 0
    assert box.locator('[data-measurement-source="5"]').count() == 0
    save_set(page)
    assert page.evaluate("ops") == []
    group = page.evaluate("groupCalls[0].measurement_set")
    assert group["code"] == "SYN01" and group["zone"] == "zone_a"
    assert group["line_label"] == "Synthetic Line A" and group["confirmed"] is True
    assert len(group["products"]) == 1
    assert group["products"][0]["confirmed_product"] is True
    assert group["products"][0]["sources"] == [{"n": 1, "revision": "a" * 64}]
    assert page.get_by_role("button", name="Save", exact=True).is_disabled()
    assert page.evaluate("levelCalls.length") == 1  # Saving a group is not a class request.
    check_class(page, level="D2")
    assert page.evaluate("levelCalls[1].measurement_set_id") == group["id"]
    page.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_function("ops.length === 1")
    assert page.evaluate("ops[0].class_context.measurement_context") == {
        "set_id": group["id"],
        "set_revision": str(2).zfill(64),
        "scope_hash": str(1).zfill(64),
    }
    assert page.evaluate("ops[0].level") == "D2"


def test_repeated_readings_stay_one_product_and_cannot_count_again(browser_page):
    page = browser_page
    setup(page)
    box = create(page)
    first_id = page.evaluate(
        "DecimusWalk.measurementSets.slot({run_id:'synthetic-run',run_key:'other-namespace'},'SYN01','zone_a').draft"
    )
    # The same product receives two readings; adding an individual product is explicit.
    box.locator('[data-measurement-source="2"]').check()
    box.get_by_role("button", name="walk.measurement.add_product", exact=True).click()
    products = box.locator(".walk-measurements__product")
    assert products.count() == 2
    assert products.nth(1).locator('[data-measurement-source="1"]').is_disabled()
    assert products.nth(1).locator('[data-measurement-source="2"]').is_disabled()
    products.nth(1).get_by_role(
        "button", name="walk.measurement.remove_product", exact=True
    ).click()
    box.locator("[data-measurement-confirm-set]").check()
    save_set(page)
    product = page.evaluate("groupCalls[0].measurement_set.products[0]")
    assert len(product["sources"]) == 2
    assert len(page.evaluate("groupCalls[0].measurement_set.products")) == 1
    assert first_id is None  # A different namespace does not import this form's draft.


def test_stale_or_refused_write_retains_text_and_explicit_rebind_uses_current_revision(
    browser_page,
):
    page = browser_page
    setup(page)
    box = create(page)
    page.evaluate("window.refuseGroup=true")
    box.get_by_role("button", name="walk.measurement.save", exact=True).click()
    page.wait_for_function("groupCalls.length === 1")
    assert (
        box.get_by_role("textbox", name="walk.measurement.line", exact=True).input_value()
        == "Synthetic Line A"
    )
    assert "Synthetic set conflict" in box.inner_text()
    page.evaluate("""() => {
      refuseGroup=false;
      DecimusWalk.state.data.zones[0].recorded[0].revision='b'.repeat(64);
    }""")
    box.get_by_role("button", name="walk.measurement.save", exact=True).click()
    assert page.evaluate("groupCalls.length") == 1  # Stale source never silently rebound.
    box.get_by_role("button", name="walk.measurement.rebind", exact=True).click()
    box.locator("[data-measurement-confirm-set]").check()
    save_set(page)
    assert (
        page.evaluate("groupCalls[1].measurement_set.products[0].sources[0].revision") == "b" * 64
    )


@pytest.mark.parametrize("change", ["source", "unassigned_inventory", "other_line", "selected_set"])
def test_any_scope_change_invalidates_ready_and_late_reply(browser_page, change):
    page = browser_page
    setup(page)
    create(page)
    save_set(page)
    check_class(page)
    assert page.get_by_role("button", name="Save", exact=True).is_enabled()
    page.locator("[data-class-check]").click()
    page.wait_for_function("levelCalls.length === 3")
    page.evaluate(
        """change => {
      const d=DecimusWalk.state.data;
      if(change==='source')d.zones[0].recorded[0].revision='b'.repeat(64);
      if(change==='unassigned_inventory')d.zones[0].recorded[1].revision='b'.repeat(64);
      if(change==='selected_set')d.measurement_sets[0].revision='b'.repeat(64);
      if(change==='other_line')d.measurement_sets.push({...structuredClone(d.measurement_sets[0]),
        id:'f'.repeat(32),line_label:'Synthetic Line B',products:[]});
    }""",
        change,
    )
    resolve(page, 2, level="D2")
    reselect_zone(page)
    expected = 3 if change == "source" else 4
    assert page.evaluate("levelCalls.length") == expected
    assert page.get_by_role("button", name="Save", exact=True).is_disabled()
    assert page.evaluate("ops") == []


def test_edit_existing_violation_opts_into_group_review_without_duplicate_add(browser_page):
    page = browser_page
    setup(page)
    create(page)
    save_set(page)
    group_id = page.evaluate("DecimusWalk.state.data.measurement_sets[0].id")
    manager(page).get_by_role("combobox", name="walk.measurement.select", exact=True).select_option(
        ""
    )
    page.evaluate("""() => {
      const W=DecimusWalk;
      const record={n:99,revision:'c'.repeat(64),code:'SYN01',zone:'zone_a',level:'D1',
        text:'Synthetic existing finding',words:'Human source facts',comment:'',repeat:false,
        reading_c:null,photos:[{ref:'synthetic-ref',own:true}]};
      W.state.data.zones[0].recorded.push(record);
    }""")
    reselect_zone(page)
    page.get_by_role("button", name="walk.measurement.open_existing", exact=True).click()
    assert page.evaluate("ops") == []
    assert page.evaluate("levelCalls.length") == 1  # Opening an edit does not call a model.
    assert page.locator("[data-class-review]").count() == 0  # Existing manual edit is unchanged.
    manager(page).get_by_role("combobox", name="walk.measurement.select", exact=True).select_option(
        group_id
    )
    assert page.get_by_role("button", name="Save", exact=True).is_disabled()
    check_class(page, level="D2")
    page.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_function("ops.length === 1")
    operation = page.evaluate("ops[0]")
    assert operation["op"] == "edit" and operation["n"] == 99
    assert operation["level"] == "D2"
    assert operation["class_context"]["measurement_context"]["set_id"]


def test_delete_group_is_separate_from_findings_and_clears_selection(browser_page):
    page = browser_page
    setup(page)
    create(page)
    save_set(page)
    box = manager(page)
    box.get_by_role("button", name="walk.measurement.edit", exact=True).click()
    box.get_by_role("button", name="walk.measurement.delete", exact=True).click()
    page.wait_for_function(
        "groupCalls.length === 2 && !DecimusWalk.state.data.measurement_sets.length"
    )
    assert page.evaluate("groupCalls[1].delete") is True
    assert page.evaluate("ops") == []
    assert (
        box.get_by_role("combobox", name="walk.measurement.select", exact=True).input_value() == ""
    )


def test_editing_group_keeps_product_identity_and_requires_composition_confirmation(browser_page):
    page = browser_page
    setup(page)
    create(page)
    save_set(page)
    original_id = page.evaluate("groupCalls[0].measurement_set.products[0].id")
    check_class(page)
    box = manager(page)
    box.get_by_role("button", name="walk.measurement.edit", exact=True).click()
    box.get_by_role("textbox", name="walk.measurement.facts", exact=True).fill(
        "New human category/time"
    )
    assert not box.locator("[data-measurement-confirm-set]").is_checked()
    assert page.locator("[data-class-check]").is_disabled()
    assert page.get_by_role("button", name="Save", exact=True).is_disabled()
    box.locator("[data-measurement-confirm-set]").check()
    box.get_by_role("button", name="walk.measurement.save", exact=True).click()
    page.wait_for_function("groupCalls.length === 2")
    assert page.evaluate("groupCalls[1].measurement_set.products[0].id") == original_id
    assert (
        page.evaluate("groupCalls[1].measurement_set.products[0].facts")
        == "New human category/time"
    )
    assert page.evaluate("levelCalls.length") == 2
    assert page.get_by_role("button", name="Save", exact=True).is_disabled()


def test_enter_in_product_facts_does_not_save_the_finding(browser_page):
    page = browser_page
    setup(page)
    box = create(page)
    facts = box.get_by_role("textbox", name="walk.measurement.facts", exact=True)
    facts.press("End")
    facts.press("Enter")
    assert "\n" in facts.input_value()
    assert page.evaluate("ops") == []
    assert page.evaluate("groupCalls") == []
    assert page.locator(".walk-sheet").count() == 1


def start_measurement_edit(page):
    setup(page)
    create(page)
    save_set(page)
    page.add_script_tag(path=str(ROOT / "src/web/static/walk-edit-draft.js"))
    page.evaluate("""() => {
      const W=DecimusWalk;
      const record={n:99,revision:'c'.repeat(64),code:'SYN01',zone:'zone_a',level:'D1',
        text:'Synthetic existing finding',words:'Original human observation',
        comment:'',repeat:false,
        reading_c:null,photos:[{ref:'synthetic-ref',own:true}]};
      W.state.data.zones[0].recorded.push(record);
      W.sheet.close(true);W.sheet.open({record,zone:'zone_a'});
    }""")
    check_class(
        page, status="needs_fact", level=None, need_fact="Synthetic category/time question?"
    )
    page.locator(".walk-class-review__facts").fill("Human category/time answer")


def reopen_edit(page):
    page.evaluate("""() => {
      const W=DecimusWalk;
      W.sheet.close(true);
      const record=W.state.data.zones[0].recorded.find(r=>r.n===99);
      W.sheet.open({record,zone:'zone_a'});
    }""")


def test_edit_human_clarification_survives_close_reopen_without_cached_class(browser_page):
    page = browser_page
    start_measurement_edit(page)
    reopen_edit(page)
    assert page.locator(".walk-class-review__facts").input_value() == "Human category/time answer"
    assert page.get_by_role("button", name="Save", exact=True).is_disabled()
    assert page.evaluate("levelCalls.length") == 2
    check_class(page, 2, level="D2")
    assert page.evaluate("levelCalls[2].words") == "Original human observation"
    assert page.evaluate("levelCalls[2].clarifications") == [
        {"question": "Synthetic category/time question?", "answer": "Human category/time answer"}
    ]
    reopen_edit(page)
    assert page.locator(".walk-class-review__facts").input_value() == ""
    history = page.locator("[data-class-feedback] details").first
    history.locator("summary").click()
    assert "Human category/time answer" in history.inner_text()
    assert page.get_by_role("button", name="Save", exact=True).is_disabled()
    assert page.evaluate("levelCalls.length") == 3


@pytest.mark.parametrize("change", ["inventory", "selected_set", "target", "edition", "photos"])
def test_changed_edit_scope_preserves_human_answers_for_explicit_recovery_only(
    browser_page, change
):
    page = browser_page
    start_measurement_edit(page)
    page.evaluate(
        """change => {
      const d=DecimusWalk.state.data, target=d.zones[0].recorded.find(r=>r.n===99);
      if(change==='inventory')d.zones[0].recorded[1].revision='d'.repeat(64);
      if(change==='selected_set')d.measurement_sets[0].revision='d'.repeat(64);
      if(change==='target')target.revision='d'.repeat(64);
      if(change==='edition')d.checklist_version='synthetic-other-edition';
      if(change==='photos')target.photos=[{ref:'other-synthetic-ref',own:true}];
    }""",
        change,
    )
    reopen_edit(page)
    assert page.locator(".walk-class-review__facts").input_value() == ""
    assert page.get_by_role("button", name="Save", exact=True).is_disabled()
    assert page.evaluate("levelCalls.length") == 2
    if change == "target":
        recovery = page.get_by_role("heading", name="walk.edit.recovery", exact=True).locator("..")
        recovery.locator("summary").click()
        assert "Human category/time answer" in recovery.inner_text()
    else:
        recovery = page.locator("[data-class-feedback] details").first
        recovery.locator("summary").click()
        assert "Human category/time answer" in recovery.inner_text()
        recovery.get_by_role(
            "button", name="walk.sheet.class_review.use_saved_facts", exact=True
        ).click()
        assert (
            page.locator(".walk-class-review__facts").input_value() == "Human category/time answer"
        )
        assert page.get_by_role("button", name="Save", exact=True).is_disabled()


def test_external_target_change_rejects_pending_class_and_retains_edit_answer(browser_page):
    page = browser_page
    start_measurement_edit(page)
    page.locator("[data-class-check]").click()
    page.wait_for_function("levelCalls.length === 3")
    page.evaluate("""() => {
      DecimusWalk.state.data.zones[0].recorded.find(r=>r.n===99).revision='d'.repeat(64);
    }""")
    resolve(page, 2, level="D2")
    manager(page).get_by_role("button", name="walk.measurement.refresh", exact=True).click()
    page.wait_for_function(
        "document.querySelector('[data-class-feedback]').textContent.includes('walk.measurement.target_changed')"
    )
    assert page.locator(".walk-class-review__facts").input_value() == "Human category/time answer"
    assert page.locator("[data-class-check]").is_disabled()
    assert page.get_by_role("button", name="Save", exact=True).is_disabled()
    assert page.evaluate("levelCalls.length") == 3
    assert page.evaluate("ops") == []
