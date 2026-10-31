"""Static DOM checks in Chromium: no server, network, methodology or real camera.

Set WALK_CHROME_BIN to run with Chrome for Testing installed outside Playwright.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

playwright = pytest.importorskip("playwright.sync_api")
STATIC = Path(__file__).resolve().parents[1] / "src/web/static"


@pytest.fixture
def page() -> Iterator:
    with playwright.sync_playwright() as pw:
        executable = os.environ.get("WALK_CHROME_BIN") or pw.chromium.executable_path
        if not Path(executable).exists():
            pytest.skip("Chromium unavailable; set WALK_CHROME_BIN")
        browser = pw.chromium.launch(executable_path=executable, headless=True)
        page = browser.new_page(viewport={"width": 390, "height": 844}, has_touch=True)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.set_content('<html><body><main id="walk"></main></body></html>')
        for css in (
            "dodo-ds.css",
            "decimus-domain.css",
            "walk.css",
            "walk-record.css",
            "walk-ux.css",
            "walk-menu.css",
        ):
            page.add_style_tag(path=str(STATIC / css))
        page.add_script_tag(path=str(STATIC / "walk-core.js"))
        page.evaluate("""() => {
          const W = DecimusWalk;
          W.tx = key => ({'walk.cl.hide':'Hide item', 'walk.cl.show':'Show item',
            'walk.camera.torch.on':'Torch on','walk.camera.torch.off':'Torch off',
            'walk.item.kind.info':'Information','walk.item.kind.violation':'Violation',
            'walk.item.kind.advice':'Recommendation'}[key] || key);
          W.state.data={key:'synthetic',items:[],zones:[]};
          W.state.marks={}; W.local={get:()=>null,set:()=>{}};
          W.storedGet=()=>{}; W.haptic=()=>{}; W.toast=()=>{};
        }""")
        yield page
        browser.close()
        assert not errors, errors


def test_checklist_swipe_is_reversible_without_record_writes(page):
    page.add_script_tag(path=str(STATIC / "walk-hints.js"))
    page.evaluate("""() => {
      const row=document.createElement('li');
      row.innerHTML='<button class="walk-cl__item is-recorded">'+
        '<span class="walk-cl__text">Synthetic item</span></button>';
      document.body.append(row); window.writes=0;
      DecimusWalk.post=()=>{writes++;};
      DecimusWalk.hints.decorateChecklist(row,{code:'TEST01',zone:'dining',recorded:true});
      window.zoneSwipes=0;
      document.addEventListener('touchend',()=>zoneSwipes++);
      window.swipe=(dx,dy=0)=>{
        row.dispatchEvent(new TouchEvent('touchstart',{bubbles:true,
          touches:[new Touch({identifier:1,target:row,clientX:200,clientY:100})]}));
        row.dispatchEvent(new TouchEvent('touchend',{bubbles:true,changedTouches:[
          new Touch({identifier:1,target:row,clientX:200+dx,clientY:100+dy})]}));
      };
    }""")
    page.evaluate("swipe(-100)")
    assert page.locator(".walk-cl__item").is_hidden()
    assert page.locator(".walk-cl__visibility").get_attribute("aria-expanded") == "false"
    assert page.evaluate("zoneSwipes") == 0
    page.evaluate("swipe(100)")
    assert page.locator(".walk-cl__item").is_visible()
    # Real keyboard interaction works independently from touch/click suppression.
    page.wait_for_timeout(650)
    page.locator(".walk-cl__visibility").focus()
    page.keyboard.press("Enter")
    assert page.locator(".walk-cl__item").is_hidden()
    page.keyboard.press("Space")
    assert page.locator(".walk-cl__item").is_visible()
    page.evaluate("swipe(-100,150)")
    assert page.locator(".walk-cl__item").is_visible()
    assert page.locator(".walk-cl__item").get_attribute("class") == "walk-cl__item is-recorded"
    assert page.evaluate("writes") == 0


def test_process_tags_only_filter_and_keep_manual_query(page):
    page.add_script_tag(path=str(STATIC / "walk-menu.js"))
    page.evaluate("""() => {
      window.picks=[];
      DecimusWalk.menu.search({title:'Items',placeholder:'Search',tags:['Cleanliness','Продукты'],
        list:q=>[{code:'Item 1',label:'Synthetic '+q,value:'TEST01',kind:'info'}],
        onPick:code=>picks.push(code)});
    }""")
    page.get_by_role("button", name="Продукты", exact=True).click()
    assert page.locator("input").input_value() == "Продукты"
    assert page.locator(".walk-option__text").inner_text() == "Synthetic Продукты"
    assert page.locator(".walk-item-kind--info").inner_text() == "Information"
    assert page.evaluate("picks") == []
    page.get_by_role("button", name="Продукты", exact=True).click()
    assert page.locator("input").input_value() == ""
    page.locator("input").fill("Custom")
    assert page.locator('[aria-pressed="true"]').count() == 0
    page.keyboard.press("Escape")
    assert page.locator(".walk-menu").count() == 0
    assert page.evaluate("picks") == []


def camera(page, supported=True, reject=False):
    page.evaluate(
        """({supported,reject}) => {
      window.constraints=[]; window.stops=0;
      const track={readyState:'live',getCapabilities:()=>({torch:supported}),
        addEventListener:()=>{},stop:()=>{stops++;track.readyState='ended';},
        applyConstraints:c=>{constraints.push(c);
          return reject||window.failTorch?Promise.reject(Error('unsupported')):Promise.resolve();}};
      const stream={getTracks:()=>[track],getVideoTracks:()=>[track]};
      Object.defineProperty(navigator,'mediaDevices',{configurable:true,value:{getUserMedia:()=>Promise.resolve(stream)}});
      Object.defineProperty(HTMLMediaElement.prototype,'srcObject',{configurable:true,set:()=>{}});
    }""",
        {"supported": supported, "reject": reject},
    )
    page.add_script_tag(path=str(STATIC / "walk-photo.js"))
    page.evaluate("document.body.append(DecimusWalk.photo.picker('Photo',()=>{}))")
    page.locator(".walk-pick--camera").click()
    page.wait_for_function("""() => {
        const note=document.querySelector('.walk-camera__torch-note');
        return note && (!document.querySelector('.walk-camera__torch').hidden || !note.hidden);
    }""")


@pytest.mark.parametrize("capability", [True, [False, True]])
def test_torch_live_track_toggle_and_pagehide_stop(page, capability):
    camera(page, supported=capability)
    button = page.locator(".walk-camera__torch")
    button.click()
    page.wait_for_function(
        "document.querySelector('.walk-camera__torch').getAttribute('aria-pressed')==='true'"
    )
    button.click()
    page.wait_for_function("constraints.length===2")
    assert page.evaluate("constraints.map(c=>c.advanced[0].torch)") == [True, False]
    page.evaluate("window.dispatchEvent(new Event('pagehide'))")
    assert page.evaluate("stops") == 1
    assert page.locator(".walk-camera").count() == 0


@pytest.mark.parametrize(
    "supported,reject", [(False, False), ([False], False), ([True], False), (True, True)]
)
def test_torch_unsupported_or_constraint_rejection_has_honest_fallback(page, supported, reject):
    camera(page, supported, reject)
    if reject:
        page.locator(".walk-camera__torch").click()
    page.wait_for_function("!document.querySelector('.walk-camera__torch-note').hidden")
    assert page.locator(".walk-camera__torch").is_hidden()
    assert page.locator(".walk-pick--gallery").count() == 1
    page.evaluate("DecimusWalk.photo.closeCamera()")
    assert page.evaluate("stops") == 1


def test_external_apple_camera_does_not_offer_track_torch(page):
    page.evaluate("""() => {
      Object.defineProperty(navigator,'userAgent',{configurable:true,value:'iPhone'});
    }""")
    page.add_script_tag(path=str(STATIC / "walk-photo.js"))
    page.evaluate("document.body.append(DecimusWalk.photo.picker('Photo',()=>{}))")
    assert page.locator('.walk-pick--camera input[capture="environment"]').count() == 1
    assert page.locator(".walk-camera__torch").count() == 0


def test_item_menu_uses_payload_process_and_kind_without_setting_class(page):
    page.evaluate("""() => {
      const W=DecimusWalk;
      W.state.data.zones=[{code:'dining',title:'Area',recorded:[],previous:[]}];
      W.state.data.items=[
        {code:'TEST01',q:'Synthetic reading',label:'Readings 1',process:'Readings',
          zones:['dining'],levels:['D0'],measure:true},
        {code:'TEST02',q:'Synthetic issue',label:'Cleanliness 2',process:'Cleanliness',
          zones:['dining'],levels:['D1','D2'],measure:false}];
      W.photo={block:()=>W.el('div'),closeCamera:()=>false};
      W.offline={available:()=>false}; W.voiceBar=()=>null; W.translateBar=()=>null;
      W.local.drop=()=>{};
    }""")
    page.add_script_tag(path=str(STATIC / "walk-menu.js"))
    page.add_script_tag(path=str(STATIC / "walk-sheet.js"))
    page.evaluate("DecimusWalk.sheet.open({mode:'measure',zone:'dining'})")
    page.get_by_role("button", name="walk.sheet.pick_item", exact=True).click()
    assert page.locator(".walk-search-tags__tag").all_text_contents() == ["Readings"]
    assert page.locator(".walk-item-kind--info").inner_text() == "Information"
    page.get_by_role("button", name="Readings", exact=True).click()
    assert page.locator(".walk-menu").count() == 1
    assert page.locator(".walk-choice").count() == 0
    page.keyboard.press("Escape")
    assert page.locator(".walk-choice").count() == 0


def test_torch_rejected_switch_off_releases_track(page):
    camera(page)
    page.locator(".walk-camera__torch").click()
    page.wait_for_function("document.querySelector('.walk-camera__torch').disabled===false")
    page.evaluate("window.failTorch=true")
    page.locator(".walk-camera__torch").click()
    page.wait_for_function("stops===1")
    assert page.locator(".walk-camera").count() == 0


def test_late_camera_permission_after_close_releases_track(page):
    page.evaluate("""() => {
      window.stops=0;
      const track={stop:()=>stops++};
      window.stream={getTracks:()=>[track]};
      Object.defineProperty(navigator,'mediaDevices',{configurable:true,value:{
        getUserMedia:()=>new Promise(resolve=>window.allowCamera=resolve)}});
    }""")
    page.add_script_tag(path=str(STATIC / "walk-photo.js"))
    page.evaluate("document.body.append(DecimusWalk.photo.picker('Photo',()=>{}))")
    page.locator(".walk-pick--camera").click()
    page.evaluate("DecimusWalk.photo.closeCamera(); allowCamera(stream)")
    page.wait_for_function("stops===1")
    assert page.locator(".walk-camera").count() == 0


def test_kind_labels_and_code_tokens_distinguish_information_and_violations(page):
    page.add_script_tag(path=str(STATIC / "walk-menu.js"))
    page.evaluate("""() => {
      DecimusWalk.menu.open({title:'Items',options:['info','violation','advice'].map(kind=>({
        kind,code:'Synthetic item',label:'Synthetic question',value:kind})),onPick:()=>{}});
    }""")
    assert page.locator(".walk-item-kind").all_text_contents() == [
        "Information",
        "Violation",
        "Recommendation",
    ]
    backgrounds = page.locator(".walk-option__code").evaluate_all(
        "nodes=>nodes.map(node=>getComputedStyle(node).backgroundColor)"
    )
    assert len(set(backgrounds)) == 3
