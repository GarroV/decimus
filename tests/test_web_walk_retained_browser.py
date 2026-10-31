"""Chromium UI + real Flask endpoints through request interception, no server."""

from __future__ import annotations

import io
import json
from urllib.parse import urlsplit

import pytest
from PIL import Image
from test_web_walk import АУДИТОР
from test_web_walk_ux_browser import STATIC, page  # noqa: F401
from test_web_walk_write import Клиент, клиент  # noqa: F401

from src.domain import edit_finding, get_state
from src.web import walk_auth


def bridge(browser, client, *, fault=None):
    requests = []
    faults = fault or {}
    attrs = {
        "endpoint": walk_auth.DATA_PATH,
        "photo": walk_auth.PHOTO_PATH,
        "photo-view": walk_auth.PHOTO_VIEW_PATH,
        "finding": walk_auth.FINDING_PATH,
        "level": walk_auth.LEVEL_PATH,
        "info": walk_auth.INFO_PATH,
        "app": walk_auth.APP_PATH,
    }
    html = (
        '<html><body><main id="walk" '
        + " ".join(f'data-{key}="{value}"' for key, value in attrs.items())
        + "></main></body></html>"
    )

    def route(request_route):
        request = request_route.request
        path = urlsplit(request.url).path
        if path == "/":
            request_route.fulfill(content_type="text/html", body=html)
            return
        if not path.startswith("/tg/walk"):
            request_route.fulfill(status=404, body="")
            return
        if path == walk_auth.LEVEL_PATH:
            request_route.fulfill(
                status=503,
                content_type="application/json",
                body=json.dumps({"error": "unavailable", "status": "unavailable"}),
            )
            return  # Manual-class QA never calls a provider.
        raw = request.post_data_buffer
        body = (
            json.loads(raw)
            if raw and request.headers.get("content-type", "").startswith("application/json")
            else {}
        )
        assert body.get("op") not in ("finish", "finish_submit"), "No outbound finish in QA"
        if path == walk_auth.FINDING_PATH:
            requests.append(body)
            if body.get("code") == faults.get("fail_code") and not faults.get("failed"):
                faults["failed"] = True
                request_route.fulfill(
                    status=503,
                    content_type="application/json",
                    body=json.dumps({"message": "Synthetic C failure"}),
                )
                return
        headers = {
            key: value
            for key, value in request.headers.items()
            if key in ("content-type", "x-telegram-init-data", "x-walk-run-id")
        }
        response = client.c.open(path, method=request.method, data=raw, headers=headers)
        if (
            path == walk_auth.FINDING_PATH
            and body.get("code") == faults.get("lost_code")
            and not faults.get("lost")
        ):
            assert response.status_code == 200, response.get_json()
            faults["lost"] = True
            request_route.fulfill(
                status=503,
                content_type="application/json",
                body=json.dumps({"message": "Synthetic lost success reply"}),
            )
            return
        request_route.fulfill(
            status=response.status_code, content_type=response.content_type, body=response.data
        )

    browser.route("https://walk.test/**", route)
    browser.add_init_script(
        "window.Telegram={WebApp:{initData:"
        + json.dumps(client.init)
        + ",isVersionAtLeast:()=>false}}"
    )
    browser.goto("https://walk.test/")
    return requests


def bootstrap(browser, *, sheet=False):
    for css in ("dodo-ds.css", "walk.css", "walk-record.css", "walk-menu.css", "walk-ux.css"):
        browser.add_style_tag(path=str(STATIC / css))
    browser.add_script_tag(path=str(STATIC / "walk-core.js"))
    browser.evaluate("""async()=>{const W=DecimusWalk;window.online=false;
      Object.defineProperty(navigator,'onLine',{configurable:true,get:()=>online});
      W.state.data=(await W.post(W.urls.data,{})).body;
      W.apply=body=>W.state.data=body;W.haptic=()=>{};W.toast=()=>{};
      W.voiceBar=()=>null;W.translateBar=()=>null;
    }""")
    browser.add_script_tag(path=str(STATIC / "walk-photo.js"))
    browser.add_script_tag(path=str(STATIC / "walk-offline.js"))
    if sheet:
        browser.add_script_tag(path=str(STATIC / "walk-menu.js"))
        browser.add_script_tag(path=str(STATIC / "walk-class-review.js"))
        source = (
            (STATIC / "walk-sheet.js")
            .read_text()
            .replace(
                "W.sheet = {",
                "W.testSubmit={submit:submit,form:()=>f,pick:pick,setZone:setZone}; W.sheet = {",
            )
        )
        browser.add_script_tag(content=source)
        browser.evaluate("DecimusWalk.sheet.open({mode:'violation',zone:'hot_kitchen'})")
    else:
        browser.evaluate("DecimusWalk.finish={ask:()=>{throw Error('No chat sending in QA');}}")
        browser.add_script_tag(path=str(STATIC / "walk-finish-photos.js"))
        browser.add_script_tag(path=str(STATIC / "walk-finish-native.js"))
        browser.evaluate("DecimusWalk.finish.ask()")
    browser.evaluate("DecimusWalk.offline.start()")


def picture(number):
    output = io.BytesIO()
    Image.new("RGB", (64, 48), (50 + number * 30, 120, 180)).save(output, "JPEG")
    return {"name": f"qa-{number}.jpg", "mimeType": "image/jpeg", "buffer": output.getvalue()}


def test_info_receipt_preview_survives_uploaded_reload_with_real_attached_only_photo_view(
    page,  # noqa: F811
    клиент: Клиент,  # noqa: F811
):
    bridge(page, клиент)
    bootstrap(page)
    page.wait_for_selector("#finish-field-INF08")
    row = page.locator("#finish-field-INF08").locator("xpath=..")
    row.locator(".walk-pick--gallery input").set_input_files([picture(1), picture(2)])
    key = get_state(АУДИТОР).run_id
    page.wait_for_function(
        "()=>DecimusWalk.offline.list(DecimusWalk.state.data.key+'_info_INF08').then(rows=>rows.length===2)"
    )
    page.evaluate("online=true;DecimusWalk.offline.kick()")
    page.wait_for_function("()=>DecimusWalk.finish.photos.refs('INF08').length===2")
    refs = page.evaluate("DecimusWalk.finish.photos.refs('INF08')")
    for ref in refs:
        assert клиент.показ(ref).status_code == 404
    page.reload()
    bootstrap(page)
    page.wait_for_selector("#finish-field-INF08")
    row = page.locator("#finish-field-INF08").locator("xpath=..")
    row.locator("img").first.wait_for()
    assert row.locator("img").count() == 2
    assert row.locator("img").evaluate_all('imgs=>imgs.every(img=>img.src.startsWith("blob:"))')
    page.wait_for_function(
        "()=>[...document.querySelectorAll('.walk-finish-photos img')]"
        ".every(img=>img.naturalWidth>0)"
    )
    page.locator("#finish-report-lang").select_option("ru")
    page.get_by_role("button", name="Проверить итог", exact=True).click()
    page.wait_for_selector("#finish-consent")
    assert get_state(АУДИТОР).run_id == key
    assert get_state(АУДИТОР).info["INF08"].text == ""
    assert set(get_state(АУДИТОР).info["INF08"].photos) == set(refs)
    for ref in refs:
        assert клиент.показ(ref).status_code == 200
    assert (
        page.evaluate(
            "DecimusWalk.offline.list(DecimusWalk.state.data.key+'_info_INF08').then(rows=>rows.length)"
        )
        == 0
    )


@pytest.mark.parametrize("lost_reply", [False, True])
def test_partial_multi_save_reconciles_real_flask_before_explicit_retry(
    page,  # noqa: F811
    клиент: Клиент,  # noqa: F811
    lost_reply: bool,
):
    faults = {"lost_code": "CLN03"} if lost_reply else {"fail_code": "CLN05"}
    requests = bridge(page, клиент, fault=faults)
    bootstrap(page, sheet=True)
    page.locator(".walk-pick--gallery input").set_input_files([picture(1), picture(2), picture(3)])
    page.wait_for_function(
        "()=>DecimusWalk.offline.list(DecimusWalk.state.data.key+'_draft').then(rows=>rows.length===3)"
    )
    page.evaluate("online=true;DecimusWalk.offline.kick()")
    page.wait_for_function(
        "()=>DecimusWalk.testSubmit.form().photos.filter(p=>p.state==='done').length===3"
    )
    refs = page.evaluate("DecimusWalk.testSubmit.form().photos.map(p=>p.ref)")
    authorize_manual_classes(page, words="Source words kept")
    page.evaluate(
        """refs=>{const W=DecimusWalk;const f=W.testSubmit.form();
      f.words='Source words kept';
      window.plan=['CLN01','CLN03','CLN05'].map((code,index)=>({op:'add',code,
        zone:'hot_kitchen',level:manualLevels[code],text:'Synthetic '+['A','B','C'][index],
        words:f.words,comment:'',repeat:false,photos:[refs[index]],reading_c:null}));
      W.testSubmit.submit(plan);
    }""",
        refs,
    )
    page.wait_for_function(
        "()=>DecimusWalk.testSubmit.form()&&!DecimusWalk.testSubmit.form().saving"
    )
    assert len(get_state(АУДИТОР).findings) == 2
    before = len(requests)
    page.evaluate("DecimusWalk.testSubmit.submit(plan)")
    page.wait_for_function("()=>!DecimusWalk.sheet.isOpen()")
    assert [(body["op"], body.get("code")) for body in requests[before:]] == [("add", "CLN05")]
    assert len(get_state(АУДИТОР).findings) == 3
    assert (
        page.evaluate(
            "DecimusWalk.offline.list(DecimusWalk.state.data.key+'_draft').then(rows=>rows.length)"
        )
        == 0
    )


def authorize_manual_classes(browser, *, words="All original human words"):
    browser.locator(".walk-area--words").fill(words)
    browser.evaluate("window.manualLevels={}")
    for code in ("CLN01", "CLN03", "CLN05", "CLN01"):
        browser.evaluate(
            "code=>{DecimusWalk.testSubmit.pick(code);DecimusWalk.testSubmit.setZone('hot_kitchen','pick')}",
            code,
        )
        label = browser.evaluate("DecimusWalk.tx('walk.sheet.class_review.manual')")
        browser.get_by_role("button", name=label, exact=True).click()
        browser.locator('[data-manual-class="D1"]').click()
        browser.evaluate("code=>manualLevels[code]=DecimusWalk.testSubmit.form().level", code)
    assert browser.evaluate("Object.values(manualLevels).every(level=>level==='D1')")


def submit_plan(browser, count=3):
    browser.locator(".walk-pick--gallery input").set_input_files(
        [picture(index + 1) for index in range(count)]
    )
    browser.wait_for_function(
        'count=>DecimusWalk.offline.list(DecimusWalk.state.data.key+"_draft").then(rows=>rows.length===count)',
        arg=count,
    )
    browser.evaluate("online=true;DecimusWalk.offline.kick()")
    browser.wait_for_function(
        'count=>DecimusWalk.testSubmit.form().photos.filter(p=>p.state==="done").length===count',
        arg=count,
    )
    refs = browser.evaluate("DecimusWalk.testSubmit.form().photos.map(p=>p.ref)")
    authorize_manual_classes(browser)
    browser.evaluate(
        """refs=>{const W=DecimusWalk;const f=W.testSubmit.form();
      f.words='All original human words';
      const key=f.draftKey;f.savedClassFacts=[{
        code:'CLN05',zone:'hot_kitchen',answer:'Human fact retained',
        words:f.words,photos:[refs[2]]}];
      W.local.set(key,{...W.local.get(key),class_facts:f.savedClassFacts});
      window.plan=['CLN01','CLN03','CLN05'].map((code,index)=>({op:'add',code,
        zone:'hot_kitchen',level:manualLevels[code],text:'Synthetic '+['A','B','C'][index],
        words:f.words,comment:'',repeat:false,photos:[refs[index]],reading_c:null}));
      W.testSubmit.submit(plan);
    }""",
        refs,
    )
    return refs


def test_changed_authoritative_record_blocks_retry_and_preserves_remaining_bytes(
    page,  # noqa: F811
    клиент: Клиент,  # noqa: F811
):
    requests = bridge(page, клиент, fault={"fail_code": "CLN05"})
    bootstrap(page, sheet=True)
    refs = submit_plan(page)
    page.wait_for_function(
        "()=>DecimusWalk.testSubmit.form()&&!DecimusWalk.testSubmit.form().saving"
    )
    edit_finding(АУДИТОР, 2, text="Authoritative description changed elsewhere")
    before = len(requests)
    page.evaluate("DecimusWalk.testSubmit.submit(plan)")
    page.wait_for_function(
        '()=>(DecimusWalk.testSubmit.form().error||"" ).includes("Запись изменилась")'
    )
    assert len(requests) == before
    assert len(get_state(АУДИТОР).findings) == 2
    assert page.evaluate("DecimusWalk.testSubmit.form().words") == "All original human words"
    rows = page.evaluate(
        'DecimusWalk.offline.list(DecimusWalk.state.data.key+"_draft").then(rows=>rows.map(r=>({ref:r.uploaded_ref,bytes:r.bytes})))'
    )
    assert len(rows) == 1 and rows[0]["ref"] == refs[2] and rows[0]["bytes"] > 0


def test_unassigned_material_keeps_receipt_words_and_scoped_human_facts_after_save(
    page,  # noqa: F811
    клиент: Клиент,  # noqa: F811
):
    bridge(page, клиент)
    bootstrap(page, sheet=True)
    refs = submit_plan(page, count=4)
    page.wait_for_function("()=>!DecimusWalk.sheet.isOpen()")
    draft = page.evaluate('DecimusWalk.local.get(DecimusWalk.state.data.key+"_draft")')
    assert draft["photos"] == [refs[3]] and draft["words"] == "All original human words"
    assert draft["code"] is None and draft["level"] is None and draft["text"] == ""
    assert draft["class_facts"][0]["answer"] == "Human fact retained"
    assert (
        page.evaluate(
            'DecimusWalk.offline.list(DecimusWalk.state.data.key+"_draft").then(rows=>rows.length)'
        )
        == 1
    )
    assert клиент.показ(refs[3]).status_code == 404
    page.reload()
    bootstrap(page, sheet=True)
    page.wait_for_function(
        '()=>DecimusWalk.testSubmit.form().photos.length===1&&DecimusWalk.testSubmit.form().photos[0].state==="done"'
    )
    assert page.evaluate("DecimusWalk.testSubmit.form().words") == "All original human words"
    page.wait_for_function(
        '()=>[...document.querySelectorAll(".walk-thumb__img")].every(img=>img.naturalWidth>0)'
    )
    assert len(get_state(АУДИТОР).findings) == 3


def test_lost_recommendation_reply_does_not_merge_an_identical_preexisting_record(
    page,  # noqa: F811
    клиент: Клиент,  # noqa: F811
):
    fault = {"lost_code": "CLN01", "lost": True}
    requests = bridge(page, клиент, fault=fault)
    bootstrap(page, sheet=True)
    page.evaluate("""async()=>{const W=DecimusWalk;window.plan=[{op:'add',code:'CLN01',
      zone:'hot_kitchen',level:'R',text:'Same human recommendation',words:'Human words',
      comment:'',repeat:false,photos:[],reading_c:null}];
      const res=await W.api.write(W.urls.finding,plan[0],W.state.data.run_id);
      if(!res.ok)throw Error(JSON.stringify(res.body));W.apply(res.body);
    }""")
    fault["lost"] = False
    page.evaluate("DecimusWalk.testSubmit.submit(plan)")
    page.wait_for_function("()=>!DecimusWalk.testSubmit.form().saving")
    assert len(get_state(АУДИТОР).findings) == 2
    before = len(requests)
    page.evaluate("DecimusWalk.testSubmit.submit(plan)")
    page.wait_for_function("()=>!DecimusWalk.sheet.isOpen()")
    assert len(requests) == before
    assert len(get_state(АУДИТОР).findings) == 2


def test_actual_manual_save_omits_absent_clarification_context(page, клиент: Клиент):  # noqa: F811
    requests = bridge(page, клиент)
    bootstrap(page, sheet=True)
    page.locator(".walk-pick--gallery input").set_input_files(picture(1))
    page.evaluate("online=true;DecimusWalk.offline.kick()")
    page.wait_for_function("()=>DecimusWalk.testSubmit.form().photos.some(p=>p.state==='done')")
    authorize_manual_classes(page)
    page.locator("[data-finding-text]").fill("Synthetic human-entered description")
    label = page.evaluate("DecimusWalk.tx('walk.sheet.save')")
    page.get_by_role("button", name=label, exact=True).click()
    page.wait_for_function("()=>!DecimusWalk.sheet.isOpen()")
    assert len(requests) == 1 and "class_context" not in requests[0]
    assert len(get_state(АУДИТОР).findings) == 1
