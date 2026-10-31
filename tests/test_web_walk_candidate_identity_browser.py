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


def load_sheet(page, cards):
    page.set_default_timeout(3000)
    page.set_content(
        '<div id="walk" data-suggest="suggest" data-hint="hint" data-finding="finding"></div>'
    )
    page.add_script_tag(path=str(ROOT / "src/web/static/walk-core.js"))
    page.evaluate(
        """(cards) => {
      const W = window.DecimusWalk;
      window.cards = cards;
      window.ops = [];
      W.state.data = {
        key:'synthetic', run_id:'synthetic-run', lang:'en',
        texts:{'walk.sheet.save_n':'Save {n}', 'walk.sheet.save':'Save'},
        items:[{code:'SYN01', q:'Synthetic item', process:'Synthetic', levels:['D1'],
                zones:['zone_a','zone_b'], measure:false}],
        zones:[{code:'zone_a',title:'Zone A',recorded:[],previous:[]},
               {code:'zone_b',title:'Zone B',recorded:[],previous:[]}]
      };
      const draft = {run_id:'synthetic-run',mode:'violation', words:'Synthetic observation',photos:['synthetic-ref']};
      W.local = {get:()=>draft,set:()=>{},drop:()=>{}};
      W.photo = {block:()=>W.el('div'),closeCamera:()=>false};
      W.offline = {available:()=>false,recovery:async()=>[]};
      W.voiceBar = W.translateBar = ()=>null;
      W.menu = {close:()=>{},open:opts=>window.menu=opts};
      W.toast = W.apply = ()=>{};
      W.post = (url, body) => {
        if (url === 'suggest') {
          return Promise.resolve({ok:true, body:{via:'model',candidates:cards}});
        }
        if (url === 'hint') return Promise.resolve({ok:true, body:{candidates:[]}});
        ops.push(JSON.parse(JSON.stringify(body)));
        return Promise.resolve({ok:true,body:{}});
      };
    }""",
        cards,
    )
    page.add_script_tag(path=str(ROOT / "src/web/static/walk-sheet.js"))
    page.evaluate("DecimusWalk.sheet.open({hint:'zone_a'})")
    page.locator(".walk-mark--find").click()
    page.wait_for_selector(".walk-found__card.is-on")


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
