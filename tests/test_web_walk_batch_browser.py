"""Batch entry of issues in the walk (prototype): Chromium, synthetic data, no network."""

# ruff: noqa: F811

from __future__ import annotations

import io

import pytest
from PIL import Image
from test_web_walk_ux_browser import STATIC, page  # noqa: F401

TEXTS = {
    "walk.batch.save_ready": "Save all ready ({n})",
    "walk.batch.zone": "Zone: {zone}",
    "walk.batch.zone_words": "named in the comment",
    "walk.batch.zone_screen": "zone not named - the current one",
    "walk.batch.prev": "Last time, {date}: {text}",
    "walk.batch.prev_yes": "Yes, a repeat",
    "walk.batch.prev_no": "No, a different one",
    "walk.sheet.class_review.record_deviation": "Record as a deviation",
}


def item(code, levels):
    return {
        "code": code,
        "label": code,
        "q": f"Synthetic wording {code}",
        "process": "p",
        "levels": levels,
        "measure": False,
    }


ITEMS = [item("ITM1", ["D1", "D2"]), item("ITM2", ["D1"])]


def verdict(status, level=None):
    return {
        "status": status,
        "level": level,
        "provisional_level": None,
        "need_fact": "" if status == "ready" else None,
        "reason": "",
    }


READY_D2 = verdict("ready", "D2")
NOT_ESTABLISHED = verdict("not_established")


def found(card_id, code, zone, source, class_):
    return {
        "id": card_id,
        "status": "found",
        "code": code,
        "zone": zone,
        "zone_source": source,
        "zone_options": [zone],
        "wording": "W",
        "candidates": [{"code": code}],
        "via": "model",
        "suggested": {"code": code, "level": "D1", "zone": zone, "confidence": 0.8},
        "class": class_,
    }


def png() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (8, 8), "gray").save(out, "PNG")
    return out.getvalue()


def start(page, replies):
    """Open the sheet on `zone_a` with `replies` as the server's answer to «Find items»."""
    page.set_default_timeout(4000)
    page.evaluate(
        """({texts, items, replies})=>{
      const W=DecimusWalk;
      W.state.data={state:'active',run_id:'r',key:'k',texts,items,
        previous:{date:'2026-09-16',count:1},
        zones:[{code:'zone_a',title:'Cold prep',recorded:[],
                previous:[{code:'ITM2',level:'D1',text:'Old wording',again:false}]},
               {code:'zone_b',title:'Dining',recorded:[],previous:[]}]};
      W.tx=(key,params)=>{let s=texts[key]||key;
        Object.keys(params||{}).forEach(p=>{s=s.split('{'+p+'}').join(params[p])}); return s;};
      W.offline={available:()=>false,register:()=>()=>{},remove(){},kick(){},watch(){}};
      W.voiceBar=null; W.haptic=()=>{}; W.toast=()=>{}; W.apply=()=>{};
      window.written=[]; window.asked=[];
      W.post=async(url,body)=>{asked.push(body);
        return {ok:true,status:200,body:{run_id:'r',cards:body.cards.map((c,i)=>replies[i])}};};
      W.api.write=async(url,body)=>{written.push(body);
        return {ok:true,status:200,body:{run_id:'r'}};};
      W.urls.batch='/batch'; W.urls.finding='/finding';
    }""",
        {"texts": TEXTS, "items": ITEMS, "replies": replies},
    )
    page.add_style_tag(path=str(STATIC / "walk-batch.css"))
    page.add_script_tag(path=str(STATIC / "walk-menu.js"))
    page.add_script_tag(path=str(STATIC / "walk-photo.js"))
    page.add_script_tag(path=str(STATIC / "walk-batch.js"))
    page.evaluate("DecimusWalk.photo.upload=async()=>'walk:'+Math.random().toString(16).slice(2)")
    page.evaluate("DecimusWalk.batch.open('zone_a')")


def add_photos(page, count):
    files = [{"name": f"p{i}.png", "mimeType": "image/png", "buffer": png()} for i in range(count)]
    page.set_input_files("[data-batch-input]", files)
    page.wait_for_function(
        f"document.querySelectorAll('[data-batch-card]').length === {count}"
        " && !document.querySelector('.walk-strip__cell.is-uploading')"
    )


def written(page):
    return page.evaluate("written")


def test_three_cards_one_not_established_recorded_as_deviation_then_saved(page):
    start(
        page,
        [
            found("c1", "ITM1", "zone_b", "words", READY_D2),
            found("c2", "ITM2", "zone_a", "screen", NOT_ESTABLISHED),
            found("c3", "ITM1", "zone_a", "screen", READY_D2),
        ],
    )
    add_photos(page, 3)
    for i, words in enumerate(["Dining: no label", "dirty shelf", "cracked lid"]):
        page.locator("[data-batch-words]").nth(i).fill(words)

    page.locator("[data-batch-find]").click()
    page.wait_for_selector("[data-batch-save]")

    # Only the ready cards are counted; the not-established one waits for a decision.
    assert page.locator("[data-batch-save]").inner_text() == "Save all ready (2)"
    assert page.locator("[data-batch-record]").count() == 1
    zones = page.locator("[data-batch-zone]").all_inner_texts()
    assert "named in the comment" in zones[0] and "Dining" in zones[0]
    assert "zone not named - the current one" in zones[1]
    sent = page.evaluate("asked[0].cards.map(c => c.words)")
    assert sent == ["Dining: no label", "dirty shelf", "cracked lid"]

    # «Record as a deviation»: the item has one class, so it is taken; the item was an issue
    # last time, so the repeat question blocks saving until the person answers.
    page.locator("[data-batch-record]").click()
    assert page.locator("[data-batch-repeat]").count() == 1
    assert page.locator("[data-batch-save]").inner_text() == "Save all ready (2)"
    page.locator("[data-batch-save]").click()
    page.wait_for_function("written.length === 2")
    assert [(w["code"], w["zone"], w["level"]) for w in written(page)] == [
        ("ITM1", "zone_b", "D2"),
        ("ITM1", "zone_a", "D2"),
    ]
    assert all(w["repeat"] is False for w in written(page)), "a repeat is never set by the system"
    assert all(w["op"] == "add" and w["photos"] for w in written(page))

    page.locator("[data-batch-repeat-no]").click()
    assert page.locator("[data-batch-save]").inner_text() == "Save all ready (1)"
    page.locator("[data-batch-save]").click()
    page.wait_for_function("written.length === 3")
    manual = written(page)[2]
    assert (manual["code"], manual["level"], manual["class_status"], manual["repeat"]) == (
        "ITM2",
        "D1",
        "manual",
        False,
    )
    assert manual["words"] == "dirty shelf"


def test_repeat_is_set_only_by_the_person(page):
    start(page, [found("c1", "ITM2", "zone_a", "screen", verdict("ready", "D1"))])
    add_photos(page, 1)
    page.locator("[data-batch-find]").click()
    page.wait_for_selector("[data-batch-repeat]")

    assert "Old wording" in page.locator("[data-batch-repeat]").inner_text()
    assert page.locator("[data-batch-save]").is_disabled(), "the question is not answered yet"
    assert written(page) == []

    page.locator("[data-batch-repeat-yes]").click()
    page.locator("[data-batch-save]").click()
    page.wait_for_function("written.length === 1")
    assert written(page)[0]["repeat"] is True


def test_changing_the_comment_after_search_requires_searching_again(page):
    start(page, [found("c1", "ITM1", "zone_a", "screen", READY_D2)])
    add_photos(page, 1)
    page.locator("[data-batch-find]").click()
    page.wait_for_selector("[data-batch-save]")
    assert page.locator("[data-batch-save]").is_enabled()

    page.locator("[data-batch-words]").fill("something else")

    assert page.locator("[data-batch-save]").is_disabled(), "a stale class is not saved silently"
    assert written(page) == []


@pytest.mark.parametrize("status", ["no_item", "unavailable", "need_zone", "measure", "no_facts"])
def test_cards_without_a_decision_are_never_saved(page, status):
    reply = {
        "id": "c1",
        "status": status,
        "code": "ITM1",
        "zone": None,
        "zone_source": "ask",
        "candidates": [],
        "message": "Synthetic failure",
    }
    start(page, [reply])
    add_photos(page, 1)
    page.locator("[data-batch-find]").click()
    page.wait_for_selector("[data-batch-card].is-doubt")

    assert page.locator("[data-batch-save]").is_disabled()
    assert written(page) == []
