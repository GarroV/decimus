"""The zone screen is used on the move, one-handed: every button is at least 44px tall (48px for
the «Fixed / Not fixed» decisions), nothing overflows sideways at 390px, and the feed keeps only
what the auditor needs now — the checklist, measurements and recommendation sit behind one
«More in this zone» button, «Finish the inspection» lives in the all-zones sheet.

Real `walk.js` renders the pieces; no server. Set WALK_SHOT_DIR to also save a screenshot.
"""

# ruff: noqa: F811, E501
from __future__ import annotations

import os
from pathlib import Path

import pytest
from test_web_walk_ux_browser import STATIC, page  # noqa: F401

from src.web.texts_batch import BATCH_TEXTS
from src.web.texts_walk import WALK_TEXTS

CSS = ("walk-app.css", "walk-hints.css", "walk-batch.css")


def mount(page, lang):
    texts = {k: v[lang] for k, v in {**WALK_TEXTS, **BATCH_TEXTS}.items()}
    for css in CSS:
        page.add_style_tag(path=str(STATIC / css))
    page.evaluate(
        """texts=>{const W=DecimusWalk;
      W.tx=(key,params)=>{let s=texts[key]||key;
        Object.keys(params||{}).forEach(p=>{s=s.split('{'+p+'}').join(params[p])}); return s;};
      const zone=(code,title,previous,recorded)=>({code,title,previous,recorded,unseen:[],unseen_info:[]});
      const prev={code:'X1',level:'D2',text:'Dirty hood filters',again:false};
      W.state.data={state:'active',run_id:'r',key:'k',lang:'ru',sealed:false,unit:'Unit',date:'2026-11-09',
        texts,previous:{date:'2026-10-01',count:1},info:[],
        items:[{code:'X1',q:'Hood filters are clean',label:'Order 1',levels:['D1','D2'],zones:['a'],measure:false}],
        zones:[zone('a','Kitchen',[prev],[{n:1,code:'X1',level:'D1',text:'Grease',zone:'a',photos:[],repeat:false}]),
               zone('b','Hall',[],[]),zone('c','Storage',[],[])]};
      W.state.marks={z:[],f:[]}; W.state.open='a';
      W.sheet={open(){},isOpen:()=>false,close(){}}; W.finish={ask(){}}; W.batch={open(){}};
      W.unseenBlock=()=>null; W.hints={afterRender(){},decorateChecklist(){}};
      W.app={go(){},start(){},showsWalk:()=>true,render(){},syncBack(){}};
      Object.assign(W.tg||(W.tg={}),{ready(){},expand(){},onEvent(){},isVersionAtLeast:()=>false});
    }""",
        texts,
    )
    source = (
        (STATIC / "walk.js")
        .read_text()
        .replace(
            "  theme();\n  load();\n})();",
            "  W.qaZone={top:renderTop,sw:renderSwitch,stage:renderStage,dock:renderDock,sheet:renderZonesSheet};\n})();",
        )
    )
    page.add_script_tag(content=source)
    page.evaluate("""()=>{const W=DecimusWalk,q=W.qaZone,zs=W.state.data.zones,z=zs[0],r=document.getElementById('walk');
      document.body.className='walk'; r.className='walk__root';
      r.appendChild(q.top(zs)); r.appendChild(q.sw(zs,z)); r.appendChild(q.stage(z)); r.appendChild(q.dock(z));
      q.sheet(zs,z);}""")


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_zone_screen_tap_targets_and_feed(page, lang):
    mount(page, lang)
    page.locator(".walk-more > .walk-cl__head").click()
    page.wait_for_timeout(400)
    got = page.evaluate("""()=>{
      const small=[];
      document.querySelectorAll('#walk button, #walk-zones-sheet button, #walk .walk-cl__act').forEach(b=>{
        const r=b.getBoundingClientRect(); if(!r.width||!r.height) return;
        if(b.closest('.walk-zsheet__scrim')) return;
        const need=b.classList.contains('walk-fix')?48:44;
        if(r.height<need-0.5||r.width<44-0.5) small.push([b.className,Math.round(r.width),Math.round(r.height)]);
      });
      const more=document.querySelectorAll('.walk-more > .walk-cl__head');
      const feed=[...document.querySelectorAll('.walk-stage > *')].map(n=>n.className);
      return {small, more:more.length, moreText:more[0]&&more[0].textContent,
        feed, finishInStage:!!document.querySelector('.walk-stage .walk-link--quiet'),
        finishInSheet:!!document.querySelector('#walk-zones-sheet .walk-zsheet__finish'),
        overflow:document.documentElement.scrollWidth>document.documentElement.clientWidth};}""")
    assert got["small"] == [], got["small"]
    assert got["more"] == 1 and got["moreText"].startswith(
        "Ещё в зоне" if lang == "ru" else "More in this zone"
    ), got
    assert not got["finishInStage"] and got["finishInSheet"], got
    assert not got["overflow"], "no horizontal scroll at 390px"
    shots = os.environ.get("WALK_SHOT_DIR")
    if shots:
        Path(shots).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=f"{shots}/zone-{lang}.png", full_page=True)
