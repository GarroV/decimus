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
    "walk.batch.photo_warn": "Cards without a comment: {n}.",
    "walk.batch.zone_words": "named in the comment",
    "walk.batch.zone_screen": "zone not named - the current one",
    "walk.batch.prev": "Last time, {date}: {text}",
    "walk.batch.prev_yes": "Yes, a repeat",
    "walk.batch.prev_no": "No, a different one",
    "walk.sheet.class_review.record_deviation": "Record as a deviation",
    "walk.batch.full": "No more than {n} photos in one batch.",
    "walk.batch.limit": "No more than {n} photos at a time.",
    "walk.batch.pick": "Pick photos",
    "walk.batch.pick_more": "Add more photos",
    "walk.batch.dup_recorded": "Already recorded (record #{n}).",
    "walk.batch.dup_ask": "Is it the same issue or a different one?",
    "walk.batch.dup_attach": "The same: add photos",
    "walk.batch.dup_other": "Different: record separately",
}

PIXEL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)
RECORDED = {
    "n": 7,
    "code": "ITM1",
    "zone": "zone_a",
    "level": "D2",
    "text": "Earlier wording",
    "words": "dirty shelf earlier",
    "photos": [{"ref": "walk:earlier", "own": True, "url": PIXEL}],
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


def start(page, replies, recorded=None):
    """Open the sheet on `zone_a` with `replies` as the server's answer to «Find items».

    `recorded` — findings already recorded in `zone_a` (what the screen data carries)."""
    page.set_default_timeout(4000)
    page.evaluate(
        """({texts, items, replies, recorded})=>{
      const W=DecimusWalk;
      W.state.data={state:'active',run_id:'r',key:'k',texts,items,
        previous:{date:'2026-09-16',count:1},
        zones:[{code:'zone_a',title:'Cold prep',recorded,
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
        {"texts": TEXTS, "items": ITEMS, "replies": replies, "recorded": recorded or []},
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


def photo_only(reply):
    return {**reply, "photo_only": True, "wording": "Synthetic seen wording"}


def test_photo_only_cards_warn_with_the_count_and_need_confirmation(page):
    start(
        page,
        [
            photo_only(found("c1", "ITM1", "zone_a", "screen", READY_D2)),
            found("c2", "ITM1", "zone_b", "screen", READY_D2),
        ],
    )
    add_photos(page, 2)
    page.locator("[data-batch-words]").nth(1).fill("has a comment")

    assert "1" in page.locator("[data-batch-photo-warn]").inner_text()
    page.locator("[data-batch-find]").click()
    page.wait_for_selector("[data-batch-seen]")

    seen = page.locator("[data-batch-seen]")
    assert seen.input_value() == "Synthetic seen wording"
    assert page.locator("[data-batch-save]").inner_text() == "Save all ready (1)"
    assert written(page) == []

    # Editing the explanation does not make the card ready: the item must be approved.
    seen.fill("Synthetic corrected wording")
    assert page.locator("[data-batch-save]").inner_text() == "Save all ready (1)"
    page.locator("[data-batch-item-ok]").click()
    assert page.locator("[data-batch-save]").inner_text() == "Save all ready (2)"
    page.locator("[data-batch-save]").click()
    page.wait_for_function("written.length === 2")
    assert written(page)[0]["text"] == "Synthetic corrected wording"
    assert written(page)[0]["words"] == ""


def test_photo_only_card_is_saved_only_after_the_item_is_approved(page):
    start(page, [photo_only(found("c1", "ITM1", "zone_a", "screen", READY_D2))])
    add_photos(page, 1)
    page.locator("[data-batch-find]").click()
    page.wait_for_selector("[data-batch-item-ok]")
    assert page.locator("[data-batch-save]").is_disabled()
    page.locator("[data-batch-seen]").fill("Synthetic edited text")
    assert page.locator("[data-batch-save]").is_disabled(), "text edit is not an approval"

    page.locator("[data-batch-item-ok]").click()
    page.locator("[data-batch-save]").click()
    page.wait_for_function("written.length === 1")
    assert written(page)[0]["text"] == "Synthetic edited text"


def test_photo_only_card_without_an_issue_asks_for_words(page):
    reply = {"id": "c1", "status": "no_item", "candidates": [], "photo_only": True}
    start(page, [reply])
    add_photos(page, 1)
    page.locator("[data-batch-find]").click()
    page.wait_for_selector("[data-batch-card].is-doubt")

    assert "walk.batch.photo_none" in page.locator("[data-batch-card]").inner_text()
    assert page.locator("[data-batch-save]").is_disabled()


def test_a_sixth_photo_cannot_be_added_and_the_limit_is_said(page):
    start(page, [])
    add_photos(page, 5)

    assert page.locator("[data-batch-card]").count() == 5
    assert page.locator("[data-batch-input]").count() == 0, "no way to add a sixth"
    assert "No more than 5" in page.locator("[data-batch-full]").inner_text()


def test_six_files_at_once_add_only_five_cards(page):
    start(page, [])
    files = [{"name": f"p{i}.png", "mimeType": "image/png", "buffer": png()} for i in range(6)]
    page.set_input_files("[data-batch-input]", files)
    page.wait_for_function("document.querySelectorAll('[data-batch-card]').length === 5")

    assert page.locator("[data-batch-card]").count() == 5


def test_already_recorded_asks_same_or_different_and_shows_the_earlier_photo(page):
    start(page, [found("c1", "ITM1", "zone_a", "screen", READY_D2)], recorded=[RECORDED])
    add_photos(page, 1)
    page.locator("[data-batch-find]").click()
    page.wait_for_selector("[data-batch-same]")

    asked = page.locator("[data-batch-same]")
    assert asked.locator("img.walk-thumb__img").count() == 1, "the earlier photo is shown"
    assert "dirty shelf earlier" in asked.inner_text(), "and its words"
    assert "same issue or a different" in asked.inner_text()
    assert page.locator("[data-batch-save]").is_disabled(), "not saved until the person answers"

    page.locator("[data-batch-same-no]").click()
    page.locator("[data-batch-save]").click()
    page.wait_for_function("written.length === 1")
    assert [(w["op"], w["code"], w["zone"]) for w in written(page)] == [("add", "ITM1", "zone_a")]


def test_already_recorded_same_issue_attaches_the_photos_to_the_record(page):
    start(page, [found("c1", "ITM1", "zone_a", "screen", READY_D2)], recorded=[RECORDED])
    add_photos(page, 1)
    page.locator("[data-batch-find]").click()
    page.wait_for_selector("[data-batch-same-yes]")

    page.locator("[data-batch-same-yes]").click()
    page.wait_for_function("written.length === 1")
    assert [(w["op"], w["n"]) for w in written(page)] == [("attach", 7)]


LONG_WORD = "Unbroken" + "wordwithoutspaces" * 8 + "_0123456789"


def test_five_cards_with_long_words_do_not_widen_the_sheet_at_360px(page):
    """A long unbroken word (wording, earlier comment, item name) wraps instead of widening the sheet."""
    page.set_viewport_size({"width": 360, "height": 740})
    replies = [
        found("c1", "ITM2", "zone_a", "screen", READY_D2),
        found("c2", "ITM1", "zone_a", "screen", READY_D2),
        found("c3", "ITM1", "zone_b", "words", NOT_ESTABLISHED),
        photo_only(found("c4", "ITM1", "zone_a", "screen", READY_D2)),
        found("c5", "ITM2", "zone_b", "screen", verdict("needs_fact")),
    ]
    replies[4]["class"]["need_fact"] = f"Which {LONG_WORD} was it?"
    replies[3]["wording"] = LONG_WORD
    start(page, replies, recorded=[{**RECORDED, "words": LONG_WORD, "text": LONG_WORD}])
    page.evaluate(
        """w=>{const D=DecimusWalk.state.data;
        D.items.forEach(i=>{i.q=w; i.label=w;});
        D.zones[0].previous[0].text=w; D.zones[1].title=w;}""",
        LONG_WORD,
    )
    add_photos(page, 5)
    for i in range(5):
        page.locator("[data-batch-words]").nth(i).fill(LONG_WORD + " " + LONG_WORD)
    page.locator("[data-batch-find]").click()
    page.wait_for_selector("[data-batch-save]")

    got = page.evaluate(
        """()=>{const body=document.querySelector('.walk-batch .walk-sheet__body');
        const vw=innerWidth;
        const wide=[...document.querySelectorAll('.walk-batch *')].filter(e=>{
          const r=e.getBoundingClientRect(); return r.width && (r.right>vw+0.5||r.left<-0.5)})
          .map(e=>e.tagName+'.'+e.className);
        const doc=Math.max(document.documentElement.scrollWidth, document.body.scrollWidth);
        return {doc, vw, body:[body.scrollWidth, body.clientWidth], wide}}"""
    )
    assert got["doc"] <= got["vw"], got
    assert got["body"][0] <= got["body"][1], got
    assert got["wide"] == [], got


def test_after_the_search_the_list_starts_at_the_first_card(page):
    start(page, [found(f"c{i}", "ITM1", "zone_a", "screen", READY_D2) for i in range(1, 6)])
    add_photos(page, 5)
    page.evaluate("document.querySelector('.walk-sheet__body').scrollTop = 1e6")
    page.locator("[data-batch-find]").click()
    page.wait_for_selector("[data-batch-save]")

    top = page.evaluate(
        """()=>document.querySelector('[data-batch-card]').getBoundingClientRect().top
        - document.querySelector('.walk-sheet__body').getBoundingClientRect().top"""
    )
    assert 0 <= top <= 16, "the first card is at the top of the list, not scrolled away"
