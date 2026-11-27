"""Language dropdown consumers preserve the active inspection and settings route."""

# ruff: noqa: F811
from __future__ import annotations

import pytest
from test_web_walk_ux_browser import STATIC, page  # noqa: F401


def mount(page, route):
    page.evaluate("""() => {
      const W = DecimusWalk;
      W.state.data = {state:'active',run_id:'synthetic-run',key:'synthetic',lang:'ru',
        unit:'Synthetic unit',items:[],zones:[],technical:{state:'pending'},
        app:{langs:[{code:'ru',label:'Русский'},{code:'en',label:'English'}]}};
      W.urls.app = '/tg/walk/app';
      W.post = (url,body) => {
        window.languageWrites = (window.languageWrites||[]).concat([{url,body}]);
        return window.failLanguage ? Promise.resolve({ok:false,body:{message:'Unavailable'}})
          : Promise.resolve({ok:true,body:{...W.state.data,lang:body.lang}});
      };
      W.render = () => {W.root.replaceChildren(); W.app.render(W.root);};
      W.apply = body => {W.state.data=body; W.render();};
    }""")
    page.add_script_tag(path=str(STATIC / "walk-hints.js"))
    page.add_script_tag(path=str(STATIC / "walk-app.js"))
    page.evaluate("route=>DecimusWalk.app.go(route)", route)


@pytest.mark.parametrize("route", ["home", "settings"])
def test_language_choice_keeps_inspection_and_route(page, route):
    mount(page, route)
    select = page.locator('select[aria-label="walk.app.lang"]')
    assert select.locator("option").all_inner_texts() == ["RU", "EN"]
    select.select_option("en")
    page.wait_for_function("DecimusWalk.state.data.lang==='en'")
    assert page.evaluate("languageWrites") == [
        {"url": "/tg/walk/app", "body": {"op": "lang", "lang": "en"}}
    ]
    assert page.evaluate("DecimusWalk.state.data.run_id") == "synthetic-run"
    assert page.evaluate("DecimusWalk.state.data.technical.state") == "pending"
    assert page.evaluate("DecimusWalk.app.route") == route
    assert page.locator('select[aria-label="walk.app.lang"]').input_value() == "en"


def test_language_failure_restores_current_choice(page):
    mount(page, "settings")
    page.evaluate("window.failLanguage=true")
    select = page.locator('select[aria-label="walk.app.lang"]')
    select.select_option("en")
    page.wait_for_function("document.querySelector('select[data-hint=lang]').value==='ru'")
    assert page.evaluate("DecimusWalk.state.data.lang") == "ru"
    assert page.evaluate("DecimusWalk.app.busy") is False


def test_hint_choice_keeps_language_and_remains_selected_after_render(page):
    mount(page, "settings")
    select = page.locator('select[aria-label="walk.app.hints"]')
    select.select_option("1")
    assert page.locator('select[aria-label="walk.app.hints"]').input_value() == "1"
    page.locator('select[aria-label="walk.app.hints"]').select_option("0")
    assert page.locator('select[aria-label="walk.app.hints"]').input_value() == "0"
    assert page.evaluate("DecimusWalk.state.data.lang") == "ru"
    assert page.evaluate("window.languageWrites||[]") == []
