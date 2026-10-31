"""Real Chromium IndexedDB/reload with native info photos, no local or remote server."""

from __future__ import annotations

import base64
import io

import pytest
from PIL import Image
from test_web_walk_ux_browser import STATIC, page  # noqa: F401

from src.web.texts_walk import WALK_TEXTS


def bootstrap(browser, *, code="INF08", kind="text", value="", fail_status=False):
    for css in ("dodo-ds.css", "walk.css", "walk-record.css", "walk-menu.css", "walk-ux.css"):
        browser.add_style_tag(path=str(STATIC / css))
    browser.add_script_tag(path=str(STATIC / "walk-core.js"))
    photo = io.BytesIO()
    Image.new("RGB", (40, 30), (100, 140, 200)).save(photo, "JPEG")
    browser.evaluate(
        """({texts,jpeg,code,kind,value,failStatus}) => {
          const W=DecimusWalk;
          window.online=false; window.infoBodies=[]; window.failInitialStatus=failStatus;
          Object.defineProperty(navigator,'onLine',{configurable:true,get:()=>online});
          W.state.data={key:'photo-visit',run_id:'photo-run',unit:'Synthetic unit',
            date:'2026-10-31',state:'active',lang:'ru',texts,app:{me:42},
            zones:[],items:[],info:[{code,kind,q:'Synthetic info question',value,photos:[]}]};
          W.apply=body=>W.state.data=body; W.haptic=()=>{};W.toast=()=>{};
          W.urls={app:'/app',info:'/info',photo:'/photo',photoView:'/photo-view'};
          W.finish={ask:()=>{throw Error('Unexpected chat fallback');}};
          W.post=(url,body)=>{
            if(body.op==='finish_status'&&failInitialStatus){failInitialStatus=false;
              return Promise.reject(Error('Synthetic offline status'));}
            if(url==='/photo-view')return Promise.resolve({ok:true,body:new Blob([
              Uint8Array.from(atob(jpeg),c=>c.charCodeAt(0))],{type:'image/jpeg'})});
            if(url==='/info'){
              infoBodies.push(body);
              const field=W.state.data.info.find(field=>field.code===body.code);
              if(field.kind!=='text'&&!body.value)return Promise.resolve({ok:false,
                body:{message:'A real date or boolean answer is required'}});
              field.value=body.value;
              field.photos=[...field.photos,...body.photos.map(ref=>({ref,own:true}))];
              return Promise.resolve({ok:true,body:W.state.data});
            }
            if(body.op==='finish_review')return Promise.resolve({ok:true,body:{
              run_id:'photo-run',revision:'photo-revision',data:W.state.data,
              summary:{pct:100,grade:'A',label:'Synthetic',total:0,counts:{}},
              report_langs:[{code:'ru',label:'Русский'}]}});
            return Promise.resolve({ok:true,body:{status:'ready'}});
          };
        }""",
        {
            "texts": {key: value["ru"] for key, value in WALK_TEXTS.items()},
            "jpeg": base64.b64encode(photo.getvalue()).decode(),
            "code": code,
            "kind": kind,
            "value": value,
            "failStatus": fail_status,
        },
    )
    browser.add_script_tag(path=str(STATIC / "walk-photo.js"))
    browser.evaluate("""() => {
      DecimusWalk.photo.compress=blob=>Promise.resolve(blob);
      DecimusWalk.photo.upload=(blob,run)=>{
        if(run!=='photo-run')throw Error('Wrong captured run');
        const n=Number(localStorage.getItem('qa-upload-count')||0)+1;
        localStorage.setItem('qa-upload-count',String(n));
        return Promise.resolve('walk:'+String(n).padStart(64,'0'));
      };
    }""")
    browser.add_script_tag(path=str(STATIC / "walk-offline.js"))
    browser.add_script_tag(path=str(STATIC / "walk-finish-photos.js"))
    browser.add_script_tag(path=str(STATIC / "walk-finish-native.js"))
    browser.evaluate("DecimusWalk.offline.start();DecimusWalk.finish.ask()")
    browser.wait_for_selector(".walk-finish-photos input[type=file]")
    return photo.getvalue()


def test_info_photo_packet_survives_real_indexeddb_reload_and_saves_without_caption(page):  # noqa: F811
    page.route(
        "https://info.test/**",
        lambda route: route.fulfill(
            content_type="text/html", body='<html><body><main id="walk"></main></body></html>'
        ),
    )
    page.goto("https://info.test/")
    jpeg = bootstrap(page)
    gallery = page.locator(".walk-finish-photos .walk-pick--gallery input")
    gallery.set_input_files(
        [
            {"name": "one.jpg", "mimeType": "image/jpeg", "buffer": jpeg},
            {"name": "two.jpg", "mimeType": "image/jpeg", "buffer": jpeg},
        ]
    )
    page.wait_for_function(
        "async()=> (await DecimusWalk.offline.list('photo-visit_info_INF08')).length===2"
    )
    assert page.evaluate("Number(localStorage.getItem('qa-upload-count')||0)") == 0
    page.reload()
    bootstrap(page)
    assert page.locator(".walk-finish-photos .walk-strip__cell").count() == 2
    page.evaluate("online=true;DecimusWalk.offline.kick()")
    page.wait_for_function("()=>DecimusWalk.finish.photos.refs('INF08').length===2")
    assert page.evaluate("Number(localStorage.getItem('qa-upload-count'))") == 2
    page.get_by_role("button", name="Проверить итог", exact=True).click()
    page.wait_for_selector("#finish-consent")
    bodies = page.evaluate("infoBodies")
    assert len(bodies) == 1
    assert bodies[0]["code"] == "INF08" and bodies[0]["value"] == ""
    assert len(bodies[0]["photos"]) == 2 and bodies[0]["run_id"] == "photo-run"
    assert page.locator("#finish-skip").count() == 0
    assert "Ответ фотографиями" in page.locator(".walk-finish__answer").inner_text()
    assert page.locator(".walk-finish__answer .walk-picks").count() == 0
    page.wait_for_function(
        "()=>[...document.querySelectorAll('.walk-thumb__img')].every(img=>img.naturalWidth>0)"
    )
    assert page.locator(".walk-finish__answer img").count() == 2


def test_attached_photos_do_not_disappear_when_date_is_missing(page):  # noqa: F811
    page.route(
        "https://info.test/**",
        lambda route: route.fulfill(
            content_type="text/html", body='<html><body><main id="walk"></main></body></html>'
        ),
    )
    page.goto("https://info.test/")
    jpeg = bootstrap(page, code="INF07", kind="date")
    page.evaluate("online=true")
    page.locator(".walk-finish-photos .walk-pick--gallery input").set_input_files(
        {"name": "date.jpg", "mimeType": "image/jpeg", "buffer": jpeg}
    )
    page.wait_for_function("()=>DecimusWalk.finish.photos.refs('INF07').length===1")
    page.get_by_role("button", name="Проверить итог", exact=True).click()
    page.wait_for_function(
        "document.querySelector('.walk-finish__error').textContent.includes('отмените вложение')"
    )
    assert page.locator("#finish-field-INF07").input_value() == ""
    assert page.evaluate("DecimusWalk.finish.photos.refs('INF07').length") == 1
    assert page.evaluate("DecimusWalk.local.get('photo-visit_info_INF07').photos.length") == 1
    assert page.locator("#finish-consent").count() == 0
    assert page.evaluate("infoBodies.length") == 0
    page.locator("#finish-field-INF07").fill("2026-10-31")
    page.get_by_role("button", name="Проверить итог", exact=True).click()
    page.wait_for_selector("#finish-consent")
    assert page.evaluate("infoBodies[0].value") == "2026-10-31"
    assert len(page.evaluate("infoBodies[0].photos")) == 1


def test_removing_unconfirmed_photo_during_compression_does_not_reappear(page):  # noqa: F811
    page.route(
        "https://info.test/**",
        lambda route: route.fulfill(
            content_type="text/html", body='<html><body><main id="walk"></main></body></html>'
        ),
    )
    page.goto("https://info.test/")
    jpeg = bootstrap(page)
    page.evaluate(
        "() => { DecimusWalk.photo.compress=blob=>new Promise("
        "resolve=>window.finishCompress=()=>resolve(blob)); }"
    )
    page.locator(".walk-finish-photos .walk-pick--gallery input").set_input_files(
        {"name": "cancelled.jpg", "mimeType": "image/jpeg", "buffer": jpeg}
    )
    page.wait_for_selector(".walk-finish-photos .walk-strip__remove")
    page.locator(".walk-finish-photos .walk-strip__remove").click()
    page.evaluate("finishCompress()")
    page.wait_for_function("()=>!DecimusWalk.finish.photos.pending()")
    assert page.locator(".walk-finish-photos .walk-strip__cell").count() == 0
    assert (
        page.evaluate("DecimusWalk.offline.list('photo-visit_info_INF08').then(rows=>rows.length)")
        == 0
    )
    assert page.evaluate("Number(localStorage.getItem('qa-upload-count')||0)") == 0


def test_unavailable_photo_storage_is_explicit_and_keeps_in_memory_retry(page):  # noqa: F811
    page.route(
        "https://info.test/**",
        lambda route: route.fulfill(
            content_type="text/html", body='<html><body><main id="walk"></main></body></html>'
        ),
    )
    page.goto("https://info.test/")
    jpeg = bootstrap(page)
    page.evaluate("DecimusWalk.offline.available=()=>false")
    page.locator(".walk-finish-photos .walk-pick--gallery input").set_input_files(
        {"name": "retry.jpg", "mimeType": "image/jpeg", "buffer": jpeg}
    )
    page.wait_for_selector(".walk-finish-photos .walk-form__note")
    assert (
        "Не закрывайте форму" in page.locator(".walk-finish-photos .walk-form__note").inner_text()
    )
    assert page.evaluate("DecimusWalk.finish.photos.pending()")
    page.evaluate("DecimusWalk.offline.available=()=>true;online=true")
    page.locator(".walk-finish-photos .walk-strip__retry").click()
    page.wait_for_function("()=>DecimusWalk.finish.photos.refs('INF08').length===1")
    assert page.evaluate("Number(localStorage.getItem('qa-upload-count'))") == 1


def test_duplicate_upload_reference_does_not_leave_a_waiting_ghost(page):  # noqa: F811
    page.route(
        "https://info.test/**",
        lambda route: route.fulfill(
            content_type="text/html", body='<html><body><main id="walk"></main></body></html>'
        ),
    )
    page.goto("https://info.test/")
    jpeg = bootstrap(page)
    page.evaluate(
        "online=true;DecimusWalk.photo.upload=()=>Promise.resolve('walk:'+('a'.repeat(64)))"
    )
    page.locator(".walk-finish-photos .walk-pick--gallery input").set_input_files(
        [
            {"name": "same-one.jpg", "mimeType": "image/jpeg", "buffer": jpeg},
            {"name": "same-two.jpg", "mimeType": "image/jpeg", "buffer": jpeg},
        ]
    )
    page.wait_for_function(
        """async()=> {
          const rows=await DecimusWalk.offline.list('photo-visit_info_INF08');
          return rows.length===0 && DecimusWalk.finish.photos.refs('INF08').length===1 &&
            !DecimusWalk.finish.photos.pending();
        }"""
    )
    assert page.locator(".walk-finish-photos .walk-strip__cell").count() == 1


@pytest.mark.parametrize(
    "code,kind,value,expected",
    [
        ("INF03", "yes_no", "Да", "yes"),
        ("INF07", "date", "31.10.2026", "2026-10-31"),
    ],
)
def test_photos_append_to_an_existing_typed_answer_without_reentering_it(
    page,  # noqa: F811
    code,
    kind,
    value,
    expected,
):
    page.route(
        "https://info.test/**",
        lambda route: route.fulfill(
            content_type="text/html", body='<html><body><main id="walk"></main></body></html>'
        ),
    )
    page.goto("https://info.test/")
    jpeg = bootstrap(page, code=code, kind=kind, value=value)
    page.evaluate("online=true")
    page.locator(".walk-finish-photos .walk-pick--gallery input").set_input_files(
        {"name": "extra.jpg", "mimeType": "image/jpeg", "buffer": jpeg}
    )
    page.wait_for_function("code=>DecimusWalk.finish.photos.refs(code).length===1", arg=code)
    page.get_by_role("button", name="Проверить итог", exact=True).click()
    page.wait_for_selector("#finish-consent")
    assert page.evaluate("infoBodies[0].value") == expected
    assert len(page.evaluate("infoBodies[0].photos")) == 1


def test_initial_status_network_failure_still_preserves_the_info_form(page):  # noqa: F811
    page.route(
        "https://info.test/**",
        lambda route: route.fulfill(
            content_type="text/html", body='<html><body><main id="walk"></main></body></html>'
        ),
    )
    page.goto("https://info.test/")
    bootstrap(page, fail_status=True)
    assert "Synthetic offline status" in page.locator(".walk-finish__error").inner_text()
    page.locator("#finish-field-INF08").fill("Caption retained after status failure")
    page.get_by_role("button", name="Проверить итог", exact=True).click()
    page.wait_for_selector("#finish-report-lang")
    assert (
        page.locator("#finish-field-INF08").input_value() == "Caption retained after status failure"
    )
    page.get_by_role("button", name="Проверить итог", exact=True).click()
    page.wait_for_selector("#finish-consent")
    assert page.evaluate("infoBodies[0].value") == "Caption retained after status failure"
