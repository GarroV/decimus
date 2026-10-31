"""Four semantic shortcuts use the synthetic cue lookup, without model calls."""

# ruff: noqa: F811
from __future__ import annotations

import pytest
from test_web_walk_search_tags import SYNTHETIC_CUES, synthetic_catalogue
from test_web_walk_ux_browser import STATIC, page  # noqa: F401

from src.recognize import cues
from src.web.texts_walk import WALK_TEXTS
from src.web.walk_search_tags import search_tags


def setup(page, monkeypatch, lang="en"):
    page.set_default_timeout(3000)
    monkeypatch.setattr(cues, "_read", lambda path, chat: SYNTHETIC_CUES)
    tags = search_tags(synthetic_catalogue(), chat_id=987)
    texts = {
        key: value[lang]
        for key, value in WALK_TEXTS.items()
        if key.startswith("walk.sheet.search_tag") or key == "walk.sheet.search_clear_tags"
    }
    page.evaluate(
        """({tags,texts})=>{
      const W=DecimusWalk;
      W.state.data={run_id:'synthetic-run',checklist_version:'synthetic-edition',key:'synthetic',texts,
        item_search_tags:tags,
        items:['AAA01','BBB02','CCC03','DDD04','EXT07','CLN99','FSB99'].map((code,i)=>({
          code,q:'Synthetic '+code,label:code,process:i===1?'Second process':'First process',
          levels:['D1'],measure:false,zones:[i===0?'zone_a':'zone_b']})),
        zones:[{code:'zone_a',title:'A',recorded:[],previous:[]},
               {code:'zone_b',title:'B',recorded:[],previous:[]}]};
      W.tx=key=>texts[key]||key;
      W.photo={block:()=>W.el('div'),closeCamera:()=>false};
      W.offline={available:()=>false,recovery:async()=>[]};
      W.voiceBar=W.translateBar=()=>null; W.local.drop=()=>{};
      window.writes=0; W.post=()=>{writes++;throw Error('unexpected network/model request')};
    }""",
        {"tags": tags, "texts": texts},
    )
    page.add_script_tag(path=str(STATIC / "walk-menu.js"))
    page.add_script_tag(path=str(STATIC / "walk-class-review.js"))
    page.add_script_tag(path=str(STATIC / "walk-sheet.js"))
    page.evaluate("DecimusWalk.sheet.open({mode:'violation',hint:'zone_a'})")
    page.get_by_role("button", name="walk.sheet.pick_manual", exact=True).click()


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_four_tags_show_only_data_owned_hits_without_picking_item_or_class(page, monkeypatch, lang):
    setup(page, monkeypatch, lang)
    mapping = {"dirty": "AAA01", "labels": "BBB02", "expired": "CCC03", "segregation": "DDD04"}
    assert page.locator("[data-search-tag]").all_text_contents() == [
        WALK_TEXTS["walk.sheet.search_tag." + tag][lang]
        for tag in ("dirty", "expired", "segregation", "labels")
    ]
    for tag, code in mapping.items():
        page.locator(f'[data-search-tag="{tag}"]').click()
        assert page.locator(".walk-option__code").all_text_contents() == [code]
        assert page.locator(".walk-menu").count() == 1
        assert page.locator("[data-class-review]").count() == 0
    assert page.evaluate("writes") == 0


def test_manual_query_survives_tag_and_clear_and_typing_leaves_process_explicit(page, monkeypatch):
    setup(page, monkeypatch)
    page.locator(".walk-search").fill("EXT07")
    assert page.locator(".walk-option__code").all_text_contents() == ["EXT07"]
    page.locator('[data-search-tag="labels"]').click()
    assert page.locator(".walk-search").input_value() == "EXT07"
    assert page.locator(".walk-option__code").all_text_contents() == ["BBB02"]
    page.locator('[data-search-tag="labels"]').click()
    assert page.locator(".walk-option__code").all_text_contents() == ["EXT07"]
    page.locator('[data-process-tag="Second process"]').click()
    page.locator('[data-search-tag="labels"]').click()
    assert page.locator(".walk-option__code").all_text_contents() == ["BBB02"]
    page.locator(".walk-search").fill("BBB02")
    assert page.locator('[data-search-tag="labels"]').get_attribute("aria-pressed") == "false"
    assert (
        page.locator('[data-process-tag="Second process"]').get_attribute("aria-pressed") == "true"
    )
    page.get_by_role("button", name="Clear filters", exact=True).click()
    assert page.locator(".walk-search").input_value() == "BBB02"
    page.locator(".walk-search").fill("")
    assert len(page.locator(".walk-option__code").all_text_contents()) == 7
    assert "CLN99" in page.locator(".walk-option__code").all_text_contents()
    assert page.evaluate("writes") == 0


def test_complete_catalogue_is_not_cut_at_sixty_and_zone_only_ranks(page, monkeypatch):
    setup(page, monkeypatch)
    page.keyboard.press("Escape")
    page.evaluate("""()=>{
      const W=DecimusWalk;
      W.state.data.items=Array.from({length:85},(_,i)=>({code:'SYN'+i,q:'Synthetic '+i,
        label:'Item '+i,process:'Process',measure:false,levels:['D1'],
        zones:[i===84?'zone_a':'zone_b']}));
    }""")
    page.get_by_role("button", name="walk.sheet.pick_manual", exact=True).click()
    assert page.locator(".walk-option__code").count() == 85
    assert page.locator(".walk-option__code").first.inner_text() == "Item 84"
    assert page.evaluate("writes") == 0
