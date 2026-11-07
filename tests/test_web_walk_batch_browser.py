"""Batch entry of issues in the walk: Chromium, synthetic data, no network."""

# ruff: noqa: F811

from __future__ import annotations

import io

import pytest
from PIL import Image
from test_web_walk_ux_browser import STATIC, page  # noqa: F401

TEXTS = {
    "walk.batch.save_ready": "Save all ready ({n})",
    "walk.batch.retry": "Search again",
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
    "walk.batch.line": "Issue {n}",
    "walk.batch.add_line": "+ another issue on this photo",
    "walk.batch.line_find": "Find the item",
    "walk.batch.saved": "Saved",
    "walk.batch.item_ok": "The item is correct",
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
      // A reply is either one server line (wrapped into a card) or a whole card with `lines`.
      const card=(c,r)=>{
        if(r.lines) return {id:c.id,status:'ok',...r};
        if(r.status==='unavailable'||r.status==='busy')
          return {id:c.id,status:r.status,message:r.message,lines:[]};
        return {id:c.id,status:'ok',lines:[{...r,id:c.line||c.id+'-1',words:c.words}]};};
      W.post=async(url,body)=>{asked.push(body);
        const cards=body.cards.map((c,i)=>card(c,replies[i]));
        return {ok:true,status:200,body:{run_id:'r',cards}};};
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


def test_busy_model_shows_the_message_and_offers_search_again(page):
    busy = {"id": "c1", "status": "busy", "message": "Synthetic busy message", "lines": []}
    start(page, [busy])
    add_photos(page, 1)
    page.locator("[data-batch-find]").click()
    page.wait_for_selector("[data-batch-card].is-doubt")

    assert "Synthetic busy message" in page.locator("[data-batch-card]").inner_text()
    retry = page.get_by_role("button", name=TEXTS["walk.batch.retry"])
    assert retry.is_visible(), "a busy card can be searched again without re-adding the photo"
    retry.click()
    page.wait_for_function("window.asked.length === 2")
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
    """A long unbroken word (wording, comment, item name) wraps, not widens."""
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


# ── several issues on one photo (D713) ───────────────────────────────────────


def line(line_id, code, zone, class_, words, **extra):
    """One server line of a card (what `walk_batch._line` answers)."""
    return {**found(line_id, code, zone, "screen", class_), "words": words, **extra}


def card_with(*lines):
    return {"lines": list(lines)}


def test_split_comment_gives_a_line_per_defect_each_saved_as_its_own_record(page):
    start(
        page,
        [
            card_with(
                line("c1-1", "ITM1", "zone_a", READY_D2, "floor is dirty"),
                line("c1-2", "ITM2", "zone_b", verdict("ready", "D1"), "door does not close"),
            )
        ],
    )
    add_photos(page, 1)
    page.locator("[data-batch-words]").fill("floor is dirty, door does not close")
    page.locator("[data-batch-find]").click()
    page.wait_for_selector("[data-batch-line]")

    assert page.locator("[data-batch-line]").count() == 2
    assert page.locator("[data-batch-card]").count() == 1, "one photo, one card"
    # The limit of 5 counts photos: two issues on one photo leave room for four more.
    assert page.locator("[data-batch-input]").count() == 1
    assert page.locator("[data-batch-save]").inner_text() == "Save all ready (2)"

    page.locator("[data-batch-save]").click()
    page.wait_for_function("written.length === 2")
    first, second = written(page)
    assert (first["code"], first["words"], second["code"], second["words"]) == (
        "ITM1",
        "floor is dirty",
        "ITM2",
        "door does not close",
    )
    assert first["photos"] == second["photos"] and len(first["photos"]) == 1, (
        "the same photo goes to every record of the card"
    )
    assert page.locator("[data-batch-save]").is_disabled(), "nothing is saved twice"


def test_photo_only_card_lists_every_violation_and_each_needs_its_approval(page):
    lines = [
        line(f"c1-{n}", code, "zone_a", READY_D2, "", photo_only=True, wording=f"Seen {n}")
        for n, code in ((1, "ITM1"), (2, "ITM2"), (3, "ITM1"))
    ]
    lines[1]["zone"] = lines[2]["zone"] = "zone_b"  # zone_a has a repeat question for ITM2
    start(page, [card_with(*lines)])
    add_photos(page, 1)
    page.locator("[data-batch-find]").click()
    page.wait_for_selector("[data-batch-line]")

    assert page.locator("[data-batch-line]").count() == 3
    assert page.locator("[data-batch-seen]").count() == 3
    assert page.locator("[data-batch-save]").is_disabled(), "no line is approved yet"

    page.locator("[data-batch-item-ok]").nth(0).click()
    page.locator("[data-batch-item-ok]").nth(1).click()
    assert page.locator("[data-batch-save]").inner_text() == "Save all ready (2)"
    page.locator("[data-batch-save]").click()
    page.wait_for_function("written.length === 2")
    assert [w["text"] for w in written(page)] == ["Seen 1", "Seen 2"]
    assert all(w["words"] == "" for w in written(page))
    assert page.locator("[data-batch-line]:not(.is-saved)").count() == 1
    assert page.locator("[data-batch-save]").is_disabled(), "the unapproved line stays unsaved"


def test_text_lines_need_no_approval_button(page):
    start(page, [card_with(line("c1-1", "ITM1", "zone_a", READY_D2, "dirty shelf"))])
    add_photos(page, 1)
    page.locator("[data-batch-find]").click()
    page.wait_for_selector("[data-batch-line]")

    assert page.locator("[data-batch-item-ok]").count() == 0
    assert page.locator("[data-batch-save]").is_enabled(), "a text card behaves as before"


def test_a_line_can_be_removed_and_is_then_not_saved(page):
    start(
        page,
        [
            card_with(
                line("c1-1", "ITM1", "zone_a", READY_D2, "one thing"),
                line("c1-2", "ITM2", "zone_b", verdict("ready", "D1"), "other thing"),
            )
        ],
    )
    add_photos(page, 1)
    page.locator("[data-batch-find]").click()
    page.wait_for_selector("[data-batch-line]")

    page.locator("[data-batch-line-drop]").nth(0).click()
    page.locator("[data-batch-save]").click()
    page.wait_for_function("written.length === 1")
    assert [w["code"] for w in written(page)] == ["ITM2"]


def test_another_issue_on_this_photo_adds_a_manual_line_searched_by_its_own_words(page):
    start(page, [line("c1-1", "ITM1", "zone_a", READY_D2, "dirty shelf")])
    add_photos(page, 1)
    page.locator("[data-batch-find]").click()
    page.wait_for_selector("[data-batch-add-line]")

    page.locator("[data-batch-add-line]").click()
    assert page.locator("[data-batch-line-find]").is_disabled(), "no words, nothing to search"
    page.evaluate(
        """()=>{const first=asked[0].cards[0];
        DecimusWalk.post=async(url,body)=>{asked.push(body);
          const c=body.cards[0];
          return {ok:true,status:200,body:{run_id:'r',cards:[{id:c.id,status:'ok',lines:[
            {id:c.line,status:'found',code:'ITM2',zone:'zone_b',zone_source:'words',
             zone_options:['zone_b'],words:c.words,candidates:[{code:'ITM2'}],
             suggested:{code:'ITM2',level:'D1',zone:'zone_b',confidence:.7},
             class:{status:'ready',level:'D1',provisional_level:null,need_fact:'',reason:''}}]}]}};}}"""
    )
    page.locator("[data-batch-line-words]").fill("cracked lid")
    page.locator("[data-batch-line-find]").click()
    page.wait_for_function("document.querySelectorAll('[data-batch-line].is-ready').length === 2")

    sent = page.evaluate("asked[asked.length-1].cards[0]")
    assert sent["words"] == "cracked lid" and sent["line"], "only this line is searched"
    assert len(sent["photos"]) == 1, "the photo goes with it"
    page.locator("[data-batch-save]").click()
    page.wait_for_function("written.length === 2")
    assert [w["code"] for w in written(page)] == ["ITM1", "ITM2"]
    assert written(page)[0]["photos"] == written(page)[1]["photos"]


def test_repeat_question_is_asked_for_each_line_separately(page):
    start(
        page,
        [
            card_with(
                line("c1-1", "ITM2", "zone_a", verdict("ready", "D1"), "first"),
                line("c1-2", "ITM1", "zone_a", verdict("ready", "D1"), "second"),
            )
        ],
    )
    page.evaluate(
        """()=>DecimusWalk.state.data.zones[0].previous.push(
          {code:'ITM1',level:'D1',text:'Old two',again:false})"""
    )
    add_photos(page, 1)
    page.locator("[data-batch-find]").click()
    page.wait_for_selector("[data-batch-repeat]")

    assert page.locator("[data-batch-repeat]").count() == 2
    assert page.locator("[data-batch-save]").is_disabled(), "neither question is answered"
    page.locator("[data-batch-repeat-yes]").nth(0).click()
    assert page.locator("[data-batch-save]").inner_text() == "Save all ready (1)"
    page.locator("[data-batch-repeat-no]").nth(1).click()
    page.locator("[data-batch-save]").click()
    page.wait_for_function("written.length === 2")
    assert [(w["code"], w["repeat"]) for w in written(page)] == [("ITM2", True), ("ITM1", False)]


def test_already_recorded_question_is_asked_per_line_with_the_earlier_photo(page):
    start(
        page,
        [
            card_with(
                line("c1-1", "ITM1", "zone_a", READY_D2, "dirty shelf"),
                line("c1-2", "ITM2", "zone_b", verdict("ready", "D1"), "other"),
            )
        ],
        recorded=[RECORDED],
    )
    add_photos(page, 1)
    page.locator("[data-batch-find]").click()
    page.wait_for_selector("[data-batch-same]")

    assert page.locator("[data-batch-same]").count() == 1, "only the line that matches asks"
    assert page.locator("[data-batch-same] img.walk-thumb__img").count() == 1
    assert page.locator("[data-batch-save]").inner_text() == "Save all ready (1)"


def test_a_card_with_several_lines_does_not_widen_the_sheet_at_360px(page):
    page.set_viewport_size({"width": 360, "height": 740})
    lines = [
        line(
            f"c1-{n}",
            code,
            "zone_a",
            READY_D2,
            LONG_WORD,
            photo_only=n == 3,
            wording=LONG_WORD,
        )
        for n, code in ((1, "ITM1"), (2, "ITM2"), (3, "ITM1"))
    ]
    start(page, [card_with(*lines)], recorded=[{**RECORDED, "words": LONG_WORD}])
    page.evaluate(
        """w=>{const D=DecimusWalk.state.data;
        D.items.forEach(i=>{i.q=w; i.label=w;}); D.zones[1].title=w;}""",
        LONG_WORD,
    )
    add_photos(page, 1)
    page.locator("[data-batch-words]").fill(LONG_WORD + " " + LONG_WORD)
    page.locator("[data-batch-find]").click()
    page.wait_for_selector("[data-batch-line]")
    page.locator("[data-batch-add-line]").click()

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


def test_single_form_opens_with_the_photos_of_the_record_just_saved(page):
    """«Another item from this photo»: a new record opens with the same photos attached."""
    page.evaluate(
        """()=>{
      const W=DecimusWalk;
      W.state.data={run_id:'r',checklist_version:'v',key:'k',texts:{},item_aliases:{},
        items:[],zones:[{code:'zone_a',title:'A',recorded:[],previous:[]}]};
      window.shown=[];
      W.photo={block:(photos)=>{shown.push(photos.map(p=>[p.ref,p.state]));return W.el('div');},
        closeCamera:()=>false};
      W.offline={available:()=>false,recovery:async()=>[]};
      W.voiceBar=W.translateBar=()=>null; W.local.drop=()=>{};
      W.post=()=>Promise.resolve({ok:true,body:{candidates:[]}});
    }"""
    )
    for name in ("walk-menu.js", "walk-class-review.js", "walk-sheet.js"):
        page.add_script_tag(path=str(STATIC / name))
    page.evaluate(
        "DecimusWalk.sheet.open({mode:'violation',hint:'zone_a',photos:['walk:aaa','walk:bbb']})"
    )

    assert page.evaluate("shown[shown.length-1]") == [["walk:aaa", "done"], ["walk:bbb", "done"]]


def test_zone_changed_by_hand_survives_finding_the_card_again(page):
    """Brasov-1, 06.11.2026: the auditor changed the zone, then edited the words — the card was
    found again and the screen's zone came back. The hand-picked zone now rides with the card."""
    start(page, [found("c1", "ITM1", "zone_a", "screen", NOT_ESTABLISHED)])
    add_photos(page, 1)
    page.locator("[data-batch-words]").first.fill("broken board")
    page.locator("[data-batch-find]").click()
    page.wait_for_function("asked.length === 1 && !document.querySelector('.is-finding')")

    page.get_by_text("walk.batch.zone_change").first.click()
    page.get_by_text("Dining").last.click()
    page.wait_for_function("asked.length === 2")
    assert page.evaluate("asked[1].cards[0].zone") == "zone_b"

    page.locator("[data-batch-words]").first.fill("broken board, three of them")
    page.get_by_text("Search again").first.click()
    page.wait_for_function("asked.length === 3")
    assert page.evaluate("asked[2].cards[0].card_zone") == "zone_b"


def test_recorded_text_is_the_model_wording_not_the_raw_words(page):
    """06.11.2026: batch records went into an English report in Russian — the raw words were
    saved as the recorded text, and auto-translation (D443) only translates the comment. The
    recorded text is the model's wording (checklist language), as in the single-record form."""
    line = found("c1", "ITM1", "zone_a", "screen", READY_D2)
    line["wording"] = "Synthetic model wording."
    start(page, [line])
    add_photos(page, 1)
    page.locator("[data-batch-words]").first.fill("синтетические слова аудитора")
    page.locator("[data-batch-find]").click()
    page.wait_for_selector("[data-batch-save]:not([disabled])")
    page.locator("[data-batch-save]").click()
    page.wait_for_function("written.length === 1")
    saved = written(page)[0]
    assert saved["text"] == "Synthetic model wording."
    assert saved["comment"] == "", "the wording already restates the words"
    assert saved["words"] == "синтетические слова аудитора"


def test_without_model_wording_the_words_go_to_the_comment(page):
    line = found("c1", "ITM1", "zone_a", "screen", READY_D2)
    line["wording"] = None
    start(page, [line])
    add_photos(page, 1)
    page.locator("[data-batch-words]").first.fill("синтетическая заметка")
    page.locator("[data-batch-find]").click()
    page.wait_for_selector("[data-batch-save]:not([disabled])")
    page.locator("[data-batch-save]").click()
    page.wait_for_function("written.length === 1")
    saved = written(page)[0]
    # A comment is what auto-translation translates.
    assert saved["comment"] == "синтетическая заметка"
    assert saved["text"] != "синтетическая заметка"
