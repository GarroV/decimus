"""Real DOM smoke, no server. Run with PYTHONPATH=. and --chrome /path/to/Chrome.

Tests the recovery panel against a small browser adapter. Reopening the main
form is stubbed: restoration and run separation are covered by Node tests.
"""

import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright

from src.web.texts_walk import WALK_TEXTS

root = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--chrome", required=True, type=Path)
chrome = parser.parse_args().chrome
source = (root / "src/web/static/walk-sheet.js").read_text()
source = source.replace(
    "W.sheet = {", "W.test = {recoveryPanel, setForm: value => { f = value; }}; W.sheet = {"
)
source = source.replace("open({mode: copied.mode || current.mode});", "window.__reopened = true;")
with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=str(chrome), headless=True)
    for lang, viewport in [
        ("ru", {"width": 1440, "height": 900}),
        ("en", {"width": 390, "height": 844}),
    ]:
        page = browser.new_page(viewport=viewport)
        page.route(
            "https://draft.test/**",
            lambda r: r.fulfill(content_type="text/html", body="<html><body></body></html>"),
        )
        page.goto("https://draft.test/")
        page.evaluate(
            "texts => window.texts=texts", {key: values[lang] for key, values in WALK_TEXTS.items()}
        )
        page.add_script_tag(
            content="""
          window.__copies=[];
          var old={mode:'violation',words:'Старый черновик <script>',photos:['old-photo']};
          localStorage.setItem('old_draft',JSON.stringify(old));
          window.DecimusWalk={state:{data:{key:'new',legacy_key:'old',run_id:'new-run'}},
            tx:(key,vars)=>{var text=texts[key]||key;
              Object.keys(vars||{}).forEach(k=>{text=text.replace('{'+k+'}',vars[k]);});
              return text;},
            local:{get:key=>JSON.parse(localStorage.getItem(key)||'null'),set:(key,value)=>localStorage.setItem(key,JSON.stringify(value))},
            el:(tag,cls,text)=>{var node=document.createElement(tag);
              node.className=cls; if(text)node.textContent=text; return node;},
            button:(cls,text,run)=>{var node=document.createElement('button');
              node.className=cls;node.textContent=text;
              node.addEventListener('click',run);return node;},
            photo:{thumb:()=>{var img=document.createElement('img');
              img.alt='saved-photo';return img;}},
            offline:{recovery:async()=>[{id:'old-frame',mode:'violation',
              blob:new Blob(['bytes'],{type:'image/jpeg'})}],
                     put:async(...args)=>{__copies.push({key:args[0],run_id:args[3],
              bytes:await args[2].text()});}},toast(){}
          };
        """
        )
        page.add_script_tag(content=source)
        page.evaluate(
            """() => {var W=DecimusWalk;
              W.test.setForm({run_id:'new-run',draftKey:'new_draft',mode:'violation'});
              W.test.recoveryPanel(document.body);}"""
        )
        panel = page.locator("details")
        panel.wait_for()
        panel.locator("summary").click()
        assert panel.locator("pre").inner_text() == "Старый черновик <script>"
        assert panel.locator("img").count() == 2
        assert page.evaluate('localStorage.getItem("new_draft")') is None
        page.once("dialog", lambda dialog: dialog.dismiss())
        panel.locator("button").click()
        assert page.evaluate("__copies.length") == 0
        assert page.evaluate('localStorage.getItem("new_draft")') is None
        page.once("dialog", lambda dialog: dialog.accept())
        panel.locator("button").click()
        page.wait_for_function("window.__reopened === true")
        result = page.evaluate(
            """() => ({original:JSON.parse(localStorage.getItem('old_draft')),
              copied:JSON.parse(localStorage.getItem('new_draft')),frames:__copies})"""
        )
        assert result["original"]["photos"] == ["old-photo"] and "run_id" not in result["original"]
        assert (
            result["copied"]["run_id"] == "new-run"
            and result["copied"]["words"] == "Старый черновик <script>"
        )
        assert result["frames"] == [{"key": "new_draft", "run_id": "new-run", "bytes": "bytes"}]
        print(
            f"{lang} {viewport['width']}: DOM text/photo/blob preview, decline/confirm, "
            "copy identity, original retained: PASS"
        )
        page.evaluate("document.body.textContent=''; localStorage.clear();")
        marks_source = (root / "src/web/static/walk.js").read_text()
        marks_source = marks_source.replace(
            "function render() {", "function render() { window.__marksRendered=true; return;"
        )
        marks_source = marks_source.replace(
            "  function toggle(list, value) {",
            "  W.testMarks={loadMarks,renderMarksRecovery}; return; function toggle(list, value) {",
        )
        page.evaluate("""() => {
          var W=DecimusWalk;W.state.recoveryMarks=null;W.supports=()=>false;
          W.storedGet=(key,done)=>done(localStorage.getItem(key));
          localStorage.setItem('old',JSON.stringify({z:['hot_kitchen'],f:['CLN05']}));
        }""")
        page.add_script_tag(content=marks_source)
        page.evaluate("""() => {
          var W=DecimusWalk;
          W.testMarks.loadMarks(W.state.data,(marks,recovery)=>{
            W.state.marks=marks;W.state.recoveryMarks=recovery;
            document.body.appendChild(W.testMarks.renderMarksRecovery());
          });
        }""")
        panel = page.locator("details")
        panel.locator("summary").click()
        assert "hot_kitchen" in panel.locator("pre").inner_text()
        assert page.evaluate("DecimusWalk.state.marks.z.length") == 0
        page.once("dialog", lambda dialog: dialog.dismiss())
        panel.locator("button").click()
        assert page.evaluate('localStorage.getItem("new")') is None
        page.once("dialog", lambda dialog: dialog.accept())
        panel.locator("button").click()
        marks = page.evaluate('JSON.parse(localStorage.getItem("new"))')
        assert marks == {"z": ["hot_kitchen"], "f": ["CLN05"], "run_id": "new-run"}
        assert page.evaluate('JSON.parse(localStorage.getItem("old")).z[0]') == "hot_kitchen"
        print(
            f"{lang} {viewport['width']}: marks preview, decline/confirm, "
            "run identity, original retained: PASS"
        )
        page.close()
    browser.close()
