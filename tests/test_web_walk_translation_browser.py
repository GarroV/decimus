"""Late translations must not write into another form/run or replace newer input."""

# ruff: noqa: F811
from __future__ import annotations

import pytest
from test_web_proofread_browser import ROOT, browser_page  # noqa: F401


def load_translation(page):
    page.set_content(
        '<main id="walk"><div id="form"><textarea id="words">Original</textarea></div></main>'
    )
    page.add_script_tag(path=str(ROOT / "src/web/static/walk-core.js"))
    page.evaluate("""() => {
      const W=DecimusWalk;
      W.state.data={run_id:'first',translate_lang:'en'};
      W.tx=key=>key; W.haptic=kind=>(window.haptics||=[]).push(kind);
      W.post=()=>new Promise((resolve,reject)=>{
        window.resolveTranslation=resolve;window.rejectTranslation=reject;
      });
      window.currentDraft='Original';
      document.querySelector('#words').addEventListener('input',event=>{
        window.currentDraft=event.target.value;
      });
    }""")
    page.add_script_tag(path=str(ROOT / "src/web/static/walk-translate.js"))
    page.evaluate("""document.querySelector('#form').appendChild(
      DecimusWalk.translateBar(document.querySelector('#words')))""")
    page.locator(".walk-translate__go").click()


@pytest.mark.parametrize("change", ["disconnected", "run", "input", "language"])
def test_delayed_translation_does_not_replace_newer_context(browser_page, change):
    page = browser_page
    load_translation(page)
    page.evaluate(
        """change=>{
      if(change==='disconnected'){
        document.querySelector('#form').replaceChildren();
        currentDraft='New form';
      }else if(change==='run'){
        DecimusWalk.state.data.run_id='replacement';currentDraft='New run';
      }else if(change==='language'){
        DecimusWalk.state.data.translate_lang='ru';currentDraft='New language';
      }else{
        const field=document.querySelector('#words');field.value='Manual correction';
        field.dispatchEvent(new Event('input',{bubbles:true}));
      }
      window.before=currentDraft;
      resolveTranslation({ok:true,body:{text:'Old translation'}});
    }""",
        change,
    )
    page.evaluate("async () => await new Promise(resolve => setTimeout(resolve, 0))")
    assert page.evaluate("currentDraft") == page.evaluate("before")
    assert page.evaluate("(window.haptics||[]).length") == 0
    if change == "input":
        assert page.locator("#words").input_value() == "Manual correction"
        assert not page.locator("#words").evaluate("field=>field.readOnly")


def test_current_translation_and_explicit_undo_still_work(browser_page):
    page = browser_page
    load_translation(page)
    page.evaluate("resolveTranslation({ok:true,body:{text:'Translated'}})")
    page.wait_for_function("currentDraft==='Translated'")
    page.locator(".walk-translate__undo").click()
    assert page.locator("#words").input_value() == "Original"
    assert page.evaluate("currentDraft") == "Original"
