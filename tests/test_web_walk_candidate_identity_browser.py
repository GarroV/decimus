"""CFT static DOM: same item, distinct zones, and explicit resolution of unknown zones."""

# ruff: noqa: F811
from __future__ import annotations

from test_web_proofread_browser import ROOT, browser_page  # noqa: F401


def card(zone, text, raw="raw-model-zone"):
    return {
        "code": "SYN01",
        "level": "D1",
        "zone": raw,
        "wording": text,
        "confidence": 0.9,
        "reading_c": None,
        "flags": [],
        "resolution": {
            "zone": zone,
            "source": "model" if zone else "ask",
            "options": ["zone_a", "zone_b"],
        },
    }


def load_sheet(page, cards, photos=None, confirm=True, choose=True, items=None, defer_levels=False):
    page.set_default_timeout(3000)
    page.set_content(
        '<div id="walk" data-suggest="suggest" data-hint="hint" '
        'data-level="level" data-finding="finding"></div>'
    )
    page.add_script_tag(path=str(ROOT / "src/web/static/walk-core.js"))
    page.evaluate(
        """({cards, photos, items, deferLevels}) => {
      const W = window.DecimusWalk;
      window.cards = cards;
      window.ops = []; window.levelCalls=[]; window.levelPending=[];
      window.deferLevels=deferLevels;
      W.state.data = {
        key:'synthetic', run_id:'synthetic-run', checklist_version:'synthetic-edition', lang:'en',
        texts:{'walk.sheet.save_n':'Save {n}', 'walk.sheet.save':'Save'},
        items:items || [{code:'SYN01', q:'Synthetic item', process:'Synthetic', levels:['D1'],
                zones:['zone_a','zone_b'], measure:false}],
        zones:[{code:'zone_a',title:'Zone A',recorded:[],previous:[]},
               {code:'zone_b',title:'Zone B',recorded:[],previous:[]}]
      };
      const draft = {run_id:'synthetic-run',mode:'violation',
        words:'Synthetic observation',photos:photos};
      W.local = {get:()=>draft,
        set:(key,value)=>window.lastDraft=JSON.parse(JSON.stringify(value)),drop:()=>{}};
      W.photo = {block:(photos, opts)=>{
        const box = W.el('div');
        photos.forEach((photo, index)=>box.appendChild(
          W.button('test-remove-photo', 'Remove frame '+index, ()=>opts.onRemove(photo))));
        return box;
      },thumb:()=>W.el('span'),closeCamera:()=>false};
      W.offline = {available:()=>false,recovery:async()=>[]};
      W.voiceBar = W.translateBar = ()=>null;
      W.menu = {close:()=>{},open:opts=>window.menu=opts};
      W.toast = W.apply = ()=>{};
      window.levelResult = (body, extra={})=>Object.assign({
        status:'ready',level:'D1',provisional_level:null,need_fact:'',reason:'Synthetic criterion',
        run_id:body.run_id,checklist_version:body.checklist_version,code:body.code,zone:body.zone,
        selection_revision:body.selection_revision,facts_key:'synthetic-facts',criteria_hash:'synthetic-criteria',
        photo_refs:body.photos,facts_from:{words:!!body.words,confirmed_reading:!!body.reading_confirmed,photos:body.photos.length}
      },extra);
      window.levelReply = (index, extra={}, ok=true)=>{
        const request=levelPending[index];
        request.resolve({ok,body:levelResult(request.body,extra)});
      };
      W.post = (url, body) => {
        if (url === 'level') {
          levelCalls.push(JSON.parse(JSON.stringify(body)));
          if (window.deferLevels) return new Promise(resolve=>levelPending.push({body,resolve}));
          return Promise.resolve({ok:true,body:levelResult(body)});
        }
        if (url === 'suggest') {
          return Promise.resolve({ok:true, body:{via:'model',candidates:cards}});
        }
        if (url === 'hint') return Promise.resolve({ok:true, body:{candidates:[]}});
        ops.push(JSON.parse(JSON.stringify(body)));
        return Promise.resolve({ok:true,body:{}});
      };
    }""",
        {
            "cards": cards,
            "photos": photos or ["synthetic-ref"],
            "items": items,
            "deferLevels": defer_levels,
        },
    )
    page.add_script_tag(path=str(ROOT / "src/web/static/walk-class-review.js"))
    page.add_script_tag(path=str(ROOT / "src/web/static/walk-sheet.js"))
    page.evaluate("DecimusWalk.sheet.open({hint:'zone_a'})")
    page.locator(".walk-mark--find").click()
    page.wait_for_selector(".walk-found__card")
    if choose:
        page.locator(".walk-found__card").first.click()
    if confirm and choose:
        for index in range(page.locator("[data-photo-assignment]").count()):
            confirm_assignment(page, index)


def confirm_assignment(page, index, frames=(0,)):
    box = page.locator("[data-photo-assignment]").nth(index)
    for frame in frames:
        box.locator(f'[data-frame-index="{frame}"]').check()
    box.locator("[data-photo-confirm]").check()


def row_for_zone(page, zone):
    return page.locator(".walk-found__row").filter(
        has=page.locator(".walk-found__card", has_text=zone)
    )


def test_same_code_in_two_zones_is_saved_as_two_operations(browser_page):
    page = browser_page
    load_sheet(page, [card("zone_a", "Synthetic A"), card("zone_b", "Synthetic B")])
    # Make B primary, then retain A as a separate additional finding.
    row_for_zone(page, "Zone B").locator(".walk-found__card").click()
    row_for_zone(page, "Zone A").locator(".walk-found__also").click()
    page.get_by_role("button", name="Save 2", exact=True).click()
    page.wait_for_function("ops.length === 2")
    ops = page.evaluate("ops")
    assert [(op["code"], op["zone"]) for op in ops] == [("SYN01", "zone_b"), ("SYN01", "zone_a")]
    assert all(op["suggested"]["zone"] == "raw-model-zone" for op in ops)


def test_unknown_zone_never_inherits_primary_zone_and_does_not_erase_other_zone(browser_page):
    page = browser_page
    load_sheet(
        page,
        [
            card("zone_a", "Synthetic A"),
            card("zone_b", "Synthetic B"),
            card(None, "Synthetic unknown"),
        ],
    )
    unknown = row_for_zone(page, "walk.sheet.where")
    assert unknown.locator(".walk-found__also").is_disabled()
    row_for_zone(page, "Zone B").locator(".walk-found__also").click()
    unknown.locator(".walk-found__card").click()
    assert (
        row_for_zone(page, "Zone B").locator(".walk-found__also").get_attribute("aria-pressed")
        == "true"
    )
    assert page.get_by_role("button", name="Save 2", exact=True).is_disabled()
    # Explicit human choice resolves the unknown candidate; another zone survives.
    page.locator(".walk-where").get_by_role("button", name="Zone A", exact=True).click()
    page.get_by_role("button", name="Save 2", exact=True).click()
    page.wait_for_function("ops.length === 2")
    assert [op["zone"] for op in page.evaluate("ops")] == ["zone_a", "zone_b"]
    assert page.evaluate("cards[2].zone") == "raw-model-zone"


def test_explicitly_resolved_candidate_can_be_kept_when_primary_changes(browser_page):
    page = browser_page
    load_sheet(
        page,
        [
            card("zone_a", "Synthetic A"),
            card("zone_b", "Synthetic B"),
            card(None, "Synthetic explicitly resolved"),
        ],
    )
    row_for_zone(page, "walk.sheet.where").locator(".walk-found__card").click()
    page.locator(".walk-where").get_by_role("button", name="Zone A", exact=True).click()
    row_for_zone(page, "Zone B").locator(".walk-found__card").click()
    # The formerly unknown card keeps the auditor's explicit zone after switching.
    page.locator(".walk-found__row").last.locator(".walk-found__also").click()
    page.get_by_role("button", name="Save 2", exact=True).click()
    page.wait_for_function("ops.length === 2")
    ops = page.evaluate("ops")
    assert [op["zone"] for op in ops] == ["zone_b", "zone_a"]
    assert ops[1]["text"] == "Synthetic explicitly resolved"
    assert page.evaluate("cards[2].resolution.source") == "pick"
    assert page.evaluate("cards[2].zone") == "raw-model-zone"
