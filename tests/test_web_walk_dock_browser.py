"""The dock's split button («+ Issue» | «Several») fits at phone and desktop widths, both themes.

Real `walk.js` renders the dock; no server. Set WALK_SHOT_DIR to also save screenshots.
"""

# ruff: noqa: F811
from __future__ import annotations

import os
from pathlib import Path

import pytest
from test_web_walk_ux_browser import STATIC, page  # noqa: F401

from src.web.texts_walk import WALK_TEXTS

SIZES = [(390, 844), (360, 740), (1440, 900)]
LANGS = ["ru", "en"]


def mount(page, lang):
    texts = {key: entry[lang] for key, entry in WALK_TEXTS.items()}
    page.add_style_tag(path=str(STATIC / "walk-batch.css"))
    page.evaluate(
        """texts=>{const W=DecimusWalk;
      W.state.data={state:'active',run_id:'r',key:'k',lang:'ru',texts,items:[],previous:null,
        zones:[{code:'a',title:'A',recorded:[],previous:[]},{code:'b',title:'B',recorded:[],previous:[]}]};
      W.tx=(key,params)=>{let s=texts[key]||key;
        Object.keys(params||{}).forEach(p=>{s=s.split('{'+p+'}').join(params[p])}); return s;};
      W.state.marks={z:[],f:[]}; W.sheet={open(){},isOpen:()=>false,close(){}};
      W.finish={ask(){}}; W.unseenBlock=()=>null; W.batch={open(zone){window.opened=zone;}};
      Object.assign(W.tg||(W.tg={}),{ready(){},expand(){},onEvent(){},isVersionAtLeast:()=>false});
    }""",
        texts,
    )
    source = (
        (STATIC / "walk.js")
        .read_text()
        .replace("  theme();\n  load();\n})();", "  W.qaDock=renderDock;\n})();")
    )
    page.add_script_tag(content=source)
    page.evaluate("""()=>{const W=DecimusWalk;
      document.body.appendChild(W.qaDock(W.state.data.zones[0]));}""")


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize(("width", "height"), SIZES)
def test_split_button_and_next_stay_readable(page, width, height, theme, lang):
    page.set_viewport_size({"width": width, "height": height})
    page.evaluate(f"document.documentElement.setAttribute('data-theme','{theme}')")
    mount(page, lang)

    got = page.evaluate("""()=>{
      const box=s=>document.querySelector(s);
      const fits=n=>n.scrollWidth<=n.clientWidth+1;
      const r=n=>n.getBoundingClientRect();
      const main=box('.walk-dock__add--main'),several=box('.walk-dock__add--several'),
        next=box('.walk-dock__next'),split=box('.walk-dock__split'),row=box('.walk-dock__row');
      return {
        fits:[main,several,next].map(fits), height:[r(split).height,r(next).height],
        order:[r(main).right<=r(several).left+1, r(split).right<=r(next).left+1],
        rowFits:row.scrollWidth<=row.clientWidth+1, nextWidth:r(next).width,
        ratio:r(main).width/r(several).width, oneLine:several.querySelector('span').getBoundingClientRect().height<20,
        aria:several.getAttribute('aria-label'), label:several.textContent.trim(),
        icon:!!several.querySelector('svg'), mainText:main.textContent.trim(),
      };}""")

    assert got["fits"] == [True, True, True], got
    assert got["rowFits"] and got["order"] == [True, True], got
    assert abs(got["height"][0] - got["height"][1]) <= 1, "split is as tall as the next button"
    assert 1.8 <= got["ratio"] <= 2.2, "«+ Issue» takes 2/3 of the split, «Several» 1/3 (D749)"
    assert got["oneLine"], "icon and label of «Several» sit on one line"
    assert got["nextWidth"] >= 110, "«Осмотрено →» is not squeezed"
    assert got["icon"] and got["label"] == ("Несколько" if lang == "ru" else "Several")
    assert got["aria"] == (
        "Несколько нарушений с фото" if lang == "ru" else "Several issues with photos"
    )
    assert got["mainText"].startswith("+")

    page.locator("[data-batch-open]").click()
    assert page.evaluate("window.opened") == "a"
    shots = os.environ.get("WALK_SHOT_DIR")
    if shots:
        Path(shots).mkdir(parents=True, exist_ok=True)
        page.locator(".walk-dock").screenshot(path=f"{shots}/dock-{width}-{theme}-{lang}.png")
