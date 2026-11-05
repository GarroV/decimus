"""Item search by words and the not-established dead end; synthetic data, no network."""

# ruff: noqa: F811
from __future__ import annotations

import pytest
from test_web_proofread_browser import browser_page  # noqa: F401
from test_web_walk_candidate_identity_browser import card, load_sheet
from test_web_walk_class_review_browser import ITEMS, choose, load, resolve
from test_web_walk_ux_browser import STATIC, page  # noqa: F401

CATALOGUE = [
    ("CLN01", "Прилежащий газон, территория замусорены", "Порядок"),
    ("CLN02", "Фасад здания поврежден", "Здание"),
    ("CLN03", "Территория склада не убрана", "Порядок"),
    ("CLN04", "Мойка загрязнена", "Порядок"),
    ("CLN05", "<img src=x onerror=window.pwned=1> Грязь", "Порядок"),
]
ALIASES = {"CLN04": ["помойка воняет"], "CLN02": ["разбитая плитка у входа"]}
TEXTS = {"walk.sheet.search_via": "via «{phrase}»", "walk.sheet.search_empty": "nothing"}


def open_search(page, aliases=ALIASES):
    page.set_default_timeout(3000)
    page.evaluate(
        """({catalogue,aliases,texts})=>{
      const W=DecimusWalk;
      W.state.data={run_id:'r',checklist_version:'v',key:'k',texts,item_aliases:aliases,
        items:catalogue.map(([code,q,process])=>({code,q,label:q,process,levels:['D1'],
          measure:false,zones:['zone_a']})),
        zones:[{code:'zone_a',title:'A',recorded:[],previous:[]}]};
      W.photo={block:()=>W.el('div'),closeCamera:()=>false};
      W.offline={available:()=>false,recovery:async()=>[]};
      W.voiceBar=W.translateBar=()=>null; W.local.drop=()=>{};
      W.post=()=>Promise.resolve({ok:true,body:{candidates:[]}});
      W.tx=(key,params)=>{let s=texts[key]||key;
        Object.keys(params||{}).forEach(p=>{s=s.split('{'+p+'}').join(params[p])}); return s;};
    }""",
        {"catalogue": CATALOGUE, "aliases": aliases, "texts": TEXTS},
    )
    page.add_script_tag(path=str(STATIC / "walk-menu.js"))
    page.add_script_tag(path=str(STATIC / "walk-class-review.js"))
    page.add_script_tag(path=str(STATIC / "walk-sheet.js"))
    page.evaluate("DecimusWalk.sheet.open({mode:'violation',hint:'zone_a'})")
    page.get_by_role("button", name="walk.sheet.pick_manual", exact=True).click()


def codes(page):
    return page.locator(".walk-option__code").all_text_contents()


def test_words_match_word_starts_in_any_case(page):
    open_search(page)
    page.locator(".walk-search").fill("прилеж газ")
    assert codes(page) == ["Прилежащий газон, территория замусорены"]
    page.locator(".walk-search").fill("ПРИЛЕЖ ГАЗ")
    assert codes(page) == ["Прилежащий газон, территория замусорены"]
    page.locator(".walk-search").fill("фасад поврежд")
    assert codes(page) == ["Фасад здания поврежден"]


def test_yo_and_ye_are_the_same_letter(page):
    open_search(page)
    page.locator(".walk-search").fill("повреждён")
    assert codes(page) == ["Фасад здания поврежден"]


def test_every_word_is_required_and_mid_word_is_not_a_match(page):
    open_search(page)
    page.locator(".walk-search").fill("фасад склада")
    assert codes(page) == []
    page.locator(".walk-search").fill("мойк")
    assert codes(page) == ["Мойка загрязнена"]  # not «помойка» from the dictionary: word start only


def test_item_starting_with_the_first_word_ranks_first(page):
    open_search(page)
    page.locator(".walk-search").fill("тер")
    assert codes(page) == ["Территория склада не убрана", "Прилежащий газон, территория замусорены"]


def test_matched_word_starts_are_highlighted(page):
    open_search(page)
    page.locator(".walk-search").fill("прилеж газ")
    assert page.locator(".walk-option__text mark").all_text_contents() == ["Прилеж", "газ"]


def test_label_is_text_never_markup(page):
    open_search(page)
    page.locator(".walk-search").fill("грязь")
    assert codes(page) == ["<img src=x onerror=window.pwned=1> Грязь"]
    assert page.locator(".walk-menu img").count() == 0
    assert page.evaluate("window.pwned") is None
    assert page.locator(".walk-option__text mark").all_text_contents() == ["Грязь"]


def test_learned_phrase_finds_item_and_says_which_phrase(page):
    open_search(page)
    page.locator(".walk-search").fill("воняет")
    assert codes(page) == ["Мойка загрязнена"]
    assert page.locator(".walk-option__via").all_text_contents() == ["via «помойка воняет»"]
    page.locator(".walk-search").fill("плитка вход")
    assert codes(page) == ["Фасад здания поврежден"]


def test_own_text_match_carries_no_dictionary_caption(page):
    open_search(page)
    page.locator(".walk-search").fill("мойка")
    assert codes(page) == ["Мойка загрязнена"]
    assert page.locator(".walk-option__via").count() == 0


def test_without_dictionary_phrase_is_not_found(page):
    open_search(page, aliases={})
    page.locator(".walk-search").fill("воняет")
    assert codes(page) == []


def test_picking_a_found_item_selects_it(page):
    open_search(page)
    page.locator(".walk-search").fill("воняет")
    page.locator(".walk-option").first.click()
    assert page.locator(".walk-menu").count() == 0
    assert "Мойка загрязнена" in page.locator("#walk, body").first.inner_text()


# --- dead end: class not established ---------------------------------------


def not_established(page, *, items=None):
    if items is None:
        load(page)
    else:
        first = {**card("zone_a", "MODEL WORDING"), "level": "D2"}
        second = {**card("zone_b", "OTHER WORDING"), "code": "SYN02", "level": "D2"}
        load_sheet(
            page, [first, second], choose=False, confirm=False, items=items, defer_levels=True
        )
    choose(page, 0)
    page.wait_for_function("levelCalls.length === 1")
    resolve(page, status="not_established", level=None, provisional_level=None, need_fact=None)


def test_dead_end_shows_two_explicit_buttons_and_hides_the_small_manual_link(browser_page):
    page = browser_page
    not_established(page)
    assert page.locator("[data-class-record]").inner_text() == (
        "walk.sheet.class_review.record_deviation"
    )
    assert page.locator("[data-class-other-item]").count() == 1
    assert page.locator("[data-class-manual]").is_hidden()
    assert page.get_by_role("button", name="Save", exact=True).is_disabled()


def test_dead_end_is_gone_once_a_class_is_chosen(browser_page):
    page = browser_page
    not_established(page)
    page.locator("[data-class-record]").click()
    assert page.locator("[data-class-deadend]").count() == 0


def test_record_as_deviation_with_several_classes_opens_the_class_choice(browser_page):
    page = browser_page
    not_established(page)
    page.locator("[data-class-record]").click()
    assert page.locator("[data-manual-class]").count() == 2
    assert page.get_by_role("button", name="Save", exact=True).is_disabled()
    page.locator('[data-manual-class="D2"]').click()
    page.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_function("ops.length === 1")
    assert page.evaluate("ops[0].level") == "D2"


def test_record_as_deviation_with_one_class_sets_it_at_once(browser_page):
    page = browser_page
    one = [{**ITEMS[0], "levels": ["D1"]}, ITEMS[1]]
    not_established(page, items=one)
    page.locator("[data-class-record]").click()
    assert page.get_by_role("button", name="Save", exact=True).is_enabled()
    page.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_function("ops.length === 1")
    assert page.evaluate("ops[0].level") == "D1"


def test_other_item_opens_the_item_search(browser_page):
    page = browser_page
    not_established(page)
    page.add_script_tag(path=str(STATIC / "walk-menu.js"))  # the harness stubs the menu
    page.evaluate("() => { DecimusWalk.menu.search = o => { window.searchTitle = o.title; }; }")
    page.locator("[data-class-other-item]").click()
    assert page.evaluate("window.searchTitle") == "walk.sheet.item"


def test_facts_check_stays_as_secondary_action(browser_page):
    page = browser_page
    not_established(page)
    assert page.locator("[data-class-check]").is_visible()


@pytest.mark.parametrize("status", ["ready", "needs_fact"])
def test_other_states_have_no_dead_end_buttons(browser_page, status):
    page = browser_page
    load(page)
    choose(page, 0)
    page.wait_for_function("levelCalls.length === 1")
    resolve(page, status=status, level="D1" if status == "ready" else None, need_fact="Q?")
    assert page.locator("[data-class-deadend]").count() == 0
    assert page.locator("[data-class-manual]").is_visible()
