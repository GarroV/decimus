"""CFT edit/reload/recovery against real authenticated Flask writes; no listening server."""

# ruff: noqa: F811
from __future__ import annotations

from pathlib import Path

import pytest
from test_web_proofread_browser import browser_page  # noqa: F401
from test_web_walk import АУДИТОР
from test_web_walk_write import ДРУГОЙ_JPEG, Клиент, _нарушение, клиент  # noqa: F401

from src.domain import edit_finding, get_state
from src.web.texts_walk import WALK_TEXTS

STATIC = Path(__file__).resolve().parents[1] / "src/web/static"


def boot(page, client):
    a, b = client.ссылка(), client.ссылка(ДРУГОЙ_JPEG)
    data = client.запись(**_нарушение(a, photos=[a, b], text="Server original")).get_json()
    data["texts"] = {key: value["en"] for key, value in WALK_TEXTS.items()}

    def route(request):
        if request.request.url.endswith("/save"):
            reply = client.запись(**request.request.post_data_json)
            request.fulfill(
                status=reply.status_code, content_type="application/json", body=reply.data
            )
        else:
            request.fulfill(
                status=200,
                content_type="text/html",
                body="<html><body><div id='walk' data-finding='/save'></div></body></html>",
            )

    page.route("https://decimus.test/**", route)

    def load(payload=data):
        page.goto("https://decimus.test/fixture")
        page.add_script_tag(path=str(STATIC / "walk-core.js"))
        page.evaluate(
            """data => {
          const W=DecimusWalk;W.state.data=data;W.state.open='hot_kitchen';
          W.photo={block:()=>W.el('div'),closeCamera:()=>false};
          W.offline={available:()=>false,recovery:()=>Promise.resolve([])};
          W.voiceBar=W.translateBar=()=>null;W.menu={close:()=>{}};
          W.toast=W.apply=()=>{};
          W.post=(url,body)=>fetch(url,{method:'POST',
            headers:{'Content-Type':'application/json'},body:JSON.stringify(body)
          }).then(async r=>({ok:r.ok,body:await r.json()}));
        }""",
            payload,
        )
        page.add_script_tag(path=str(STATIC / "walk-edit-draft.js"))
        page.add_script_tag(path=str(STATIC / "walk-sheet.js"))
        page.evaluate(
            """() => {const W=DecimusWalk;
            window.record=W.state.data.zones.find(z=>z.code==='hot_kitchen').recorded[0];
            W.sheet.open({record:record,zone:'hot_kitchen'});}"""
        )

    return data, load


@pytest.mark.parametrize("viewport", [(390, 844), (1440, 1000)])
def test_edit_reload_and_atomic_save_history(browser_page, клиент: Клиент, viewport):
    page = browser_page
    page.set_viewport_size({"width": viewport[0], "height": viewport[1]})
    _data, load = boot(page, клиент)
    load()
    area = page.locator("textarea").first
    area.fill("Human revised text")
    load()
    assert page.locator("textarea").first.input_value() == "Human revised text"
    page.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_function("!DecimusWalk.sheet.isOpen()")
    state = get_state(АУДИТОР)
    assert state.findings[0].text == "Human revised text"
    assert len(state.finding_history) == 1
    assert state.finding_history[0]["before"]["text"] == "Server original"
    assert state.finding_history[0]["after"][0]["text"] == "Human revised text"
    assert (
        page.evaluate(
            'Object.keys(localStorage).filter(k=>k.includes("_edit_")&&!k.includes("_index_")).length'
        )
        == 0
    )


def test_changed_server_record_requires_readable_explicit_recovery(browser_page, клиент: Клиент):
    page = browser_page
    data, load = boot(page, клиент)
    load()
    page.locator("textarea").first.fill("Unsaved human edit")
    source = get_state(АУДИТОР).findings[0]
    edit_finding(АУДИТОР, source.n, text="New server version")
    # Fresh server response supplies the changed revision.
    fresh = клиент.запись(op="edit", n=source.n, comment="Fresh server comment").get_json()
    fresh["texts"] = data["texts"]
    load(fresh)
    assert page.locator("textarea").first.input_value() == "New server version"
    recovery = page.get_by_text("Saved edit of an earlier version", exact=True)
    assert recovery.is_visible()
    page.locator("details").last.locator("summary").click()
    assert page.get_by_text("Unsaved human edit", exact=True).is_visible()
    page.get_by_role("button", name="Restore edit and new photos", exact=True).click()
    assert page.locator("textarea").first.input_value() == "Unsaved human edit"
    assert get_state(АУДИТОР).findings[0].text == "New server version"


@pytest.mark.parametrize("changed_revision", [False, True])
@pytest.mark.parametrize("lost_reply", [False, True])
def test_edit_uploaded_draft_keeps_blob_after_reload_then_acks_atomic_save(
    browser_page, клиент: Клиент, changed_revision: bool, lost_reply: bool
):
    from test_web_walk_retained_browser import bootstrap, bridge, picture

    page = browser_page
    page.set_default_timeout(5000)
    first = клиент.ссылка()
    assert клиент.запись(**_нарушение(first, text="Before", reading_c=4)).status_code == 200
    requests = bridge(
        page, клиент, fault={"fail_code": "NEVER", "lost_code": None if lost_reply else "NEVER"}
    )

    def load():
        bootstrap(page, sheet=True)
        page.add_script_tag(path=str(STATIC / "walk-edit-draft.js"))
        page.evaluate("""() => {const W=DecimusWalk;W.sheet.close(true);
          const z=W.state.data.zones.find(z=>z.code==='hot_kitchen');
          W.sheet.open({record:z.recorded[0],zone:z.code});}""")

    load()
    page.locator(".walk-pick--gallery input").set_input_files(picture(2))
    page.wait_for_function(
        """()=>DecimusWalk.offline.list(DecimusWalk.testSubmit.form().draftKey).then(rows=>rows.length===1)"""
    )
    page.evaluate("online=true;DecimusWalk.offline.kick()")
    page.wait_for_function(
        "()=>DecimusWalk.testSubmit.form().photos.some(p=>p.fresh&&p.state==='done')"
    )
    ref = page.evaluate("DecimusWalk.testSubmit.form().photos.find(p=>p.fresh).ref")
    assert клиент.показ(ref).status_code == 404
    old_key = page.evaluate("DecimusWalk.testSubmit.form().draftKey")
    if changed_revision:
        edit_finding(АУДИТОР, 1, text="Changed server text")
    page.reload()
    load()
    if changed_revision:
        assert page.evaluate("DecimusWalk.testSubmit.form().photos.filter(p=>p.fresh).length") == 0
        page.get_by_text("Сохранённая правка прежней версии", exact=True).wait_for()
        page.locator("details").last.locator("summary").click()
        page.locator("details img").wait_for()
        page.get_by_role("button", name="Перенести правку и новые кадры", exact=True).click()
        page.reload()
        load()
    page.wait_for_function(
        "()=>DecimusWalk.testSubmit.form().photos.some(p=>p.fresh&&p.url&&p.state==='done')"
    )
    assert page.evaluate(
        "DecimusWalk.testSubmit.form().photos.find(p=>p.fresh).url.startsWith('blob:')"
    )
    page.wait_for_function(
        "Array.from(document.images).some(img=>img.src.startsWith('blob:')&&img.naturalWidth>0)"
    )
    page.locator("textarea").first.fill("After with retained photo")
    page.locator('input[inputmode="decimal"]').fill("0")
    page.get_by_role("button", name="Сохранить", exact=True).click()
    if lost_reply:
        page.wait_for_function(
            "DecimusWalk.testSubmit.form() && !DecimusWalk.testSubmit.form().saving"
        )
        assert (
            page.evaluate("key=>DecimusWalk.offline.list(key).then(rows=>rows.length)", old_key)
            == 1
        )
        if not changed_revision:
            page.reload()
            load()
            page.wait_for_function(
                "key=>DecimusWalk.offline.list(key).then(rows=>rows.length===0)", arg=old_key
            )
            assert not page.evaluate("DecimusWalk.testSubmit.form().editRecovery.length")
        page.get_by_role("button", name="Сохранить", exact=True).click()
    page.wait_for_function(
        "!DecimusWalk.testSubmit.form() || !DecimusWalk.testSubmit.form().saving"
    )
    assert not page.evaluate("DecimusWalk.sheet.isOpen()"), page.evaluate(
        "DecimusWalk.testSubmit.form().error"
    )
    assert [body["op"] for body in requests] == (
        ["edit", "edit"] if lost_reply and changed_revision else ["edit"]
    )
    if lost_reply and changed_revision:
        assert requests[0]["request_id"] == requests[1]["request_id"]
    state = get_state(АУДИТОР)
    assert state.findings[0].reading_c == 0
    assert state.findings[0].text == "After with retained photo"
    assert state.findings[0].photos == [first, ref]
    assert len(state.finding_history) == (2 if changed_revision else 1)
    assert клиент.показ(ref).status_code == 200
    assert page.evaluate("key=>DecimusWalk.offline.list(key).then(rows=>rows.length)", old_key) == 0
    assert page.evaluate("key=>localStorage.getItem(key)", old_key) is None
