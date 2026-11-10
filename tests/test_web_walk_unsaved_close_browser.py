"""Closing an unsaved record (D745): no explanatory phrase, two buttons, the places with unsaved input are
outlined, «Keep editing» clears the outline and puts the focus in the first of them.

Real `walk-sheet.js`, synthetic data, no server. Chromium and WebKit. Set WALK_SHOT_DIR to also save screenshots.
"""

# ruff: noqa: E501
from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from conftest import chromium_executable

from src.web.texts_walk import WALK_TEXTS

playwright = pytest.importorskip("playwright.sync_api")
STATIC = Path(__file__).resolve().parents[1] / "src/web/static"
CSS = (
    "dodo-ds.css",
    "decimus-domain.css",
    "walk.css",
    "walk-record.css",
    "walk-ux.css",
    "walk-menu.css",
)


def launch(pw, engine):
    if engine == "webkit":
        executable = os.environ.get("PW_WEBKIT_EXECUTABLE")
        return pw.webkit.launch(
            headless=True, **({"executable_path": executable} if executable else {})
        )
    return pw.chromium.launch(
        executable_path=chromium_executable(pw.chromium.executable_path), headless=True
    )


@pytest.fixture(params=["chromium", "webkit"])
def page(request) -> Iterator:
    with playwright.sync_playwright() as pw:
        browser = launch(pw, request.param)
        page = browser.new_page(viewport={"width": 390, "height": 844}, has_touch=True)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.set_content('<html><body><main id="walk"></main></body></html>')
        for css in CSS:
            page.add_style_tag(path=str(STATIC / css))
        page.add_script_tag(path=str(STATIC / "walk-core.js"))
        yield page
        browser.close()
        assert not errors, errors


def open_record(page, lang):
    texts = {k: v[lang] for k, v in WALK_TEXTS.items()}
    page.evaluate(
        """texts=>{const W=DecimusWalk;
      W.state.data={run_id:'r',checklist_version:'v',key:'k',texts,item_aliases:{},
        items:[{code:'CLN01',q:'Hood filters are clean',label:'Order 1',process:'p',levels:['D1','D2'],measure:false,zones:['zone_a']}],
        zones:[{code:'zone_a',title:'Kitchen',recorded:[],previous:[]}]};
      W.state.open='zone_a';
      W.photo={block:()=>W.el('div'),closeCamera:()=>false,capture(){}};
      W.offline={available:()=>false,recovery:async()=>[]};
      W.voiceBar=W.translateBar=()=>null; W.local.drop=()=>{};
      W.post=()=>Promise.resolve({ok:true,body:{candidates:[]}});
      W.tx=(key,params)=>{let s=texts[key]||key;
        Object.keys(params||{}).forEach(p=>{s=s.split('{'+p+'}').join(params[p])}); return s;};
    }""",
        texts,
    )
    for script in ("walk-menu.js", "walk-class-review.js", "walk-sheet.js"):
        page.add_script_tag(path=str(STATIC / script))
    page.evaluate("DecimusWalk.sheet.open({mode:'violation',hint:'zone_a'})")


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_close_fork_outlines_unsaved_field_and_keep_editing_returns_to_it(page, lang):
    open_record(page, lang)
    texts = {k: v[lang] for k, v in WALK_TEXTS.items()}
    words = page.locator(".walk-area--words")
    words.fill("burnt residue on the lid")
    page.locator(".walk-sheet__back").click()

    foot = page.locator(".walk-sheet__foot")
    assert foot.locator("p").count() == 0, "no explanatory phrase in the fork"
    assert foot.locator("button").all_text_contents() == [
        texts["walk.sheet.discard_yes"],
        texts["walk.sheet.discard_keep"],
    ]
    assert "walk-unsaved" in (words.get_attribute("class") or ""), "the unsaved field is outlined"
    outline = words.evaluate(
        "n=>getComputedStyle(n).outlineStyle+' '+getComputedStyle(n).outlineWidth"
    )
    assert outline == "solid 2px", outline
    assert page.locator(".walk-unsaved").count() == 1, "only the field with input is outlined"
    shots = os.environ.get("WALK_SHOT_DIR")
    if shots:
        Path(shots).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=f"{shots}/unsaved-close-{lang}.png")

    foot.get_by_role("button", name=texts["walk.sheet.discard_keep"], exact=True).click()
    assert page.locator(".walk-unsaved").count() == 0, "keep editing clears the outline"
    assert page.locator(".walk-sheet__foot button.walk-btn--danger-quiet").count() == 0
    assert page.evaluate("document.activeElement.className").split()[0] == "walk-area"
    assert page.evaluate("document.activeElement === document.querySelector('.walk-area--words')")

    page.locator(".walk-sheet__back").click()
    page.get_by_role("button", name=texts["walk.sheet.discard_yes"], exact=True).click()
    assert not page.evaluate("DecimusWalk.sheet.isOpen()"), "close without saving closes the sheet"
