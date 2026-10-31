"""Explicit locations survive point selection; contextual measurements use real Flask writes."""

from __future__ import annotations

import pytest

# ruff: noqa: F811
from test_web_walk import АУДИТОР
from test_web_walk_retained_browser import bootstrap, bridge, picture
from test_web_walk_ux_browser import STATIC, page  # noqa: F401
from test_web_walk_write import Клиент, клиент  # noqa: F401

from src.domain import get_state


def test_physical_pick_is_scoped_to_selection_and_never_overwrites_raw_model_zone(
    page, клиент: Клиент
):
    bridge(page, клиент)
    bootstrap(page, sheet=True)
    got = page.evaluate("""()=>{const W=DecimusWalk;const T=W.testSubmit;
      window.first={code:'CLN01',zone:'facade',resolution:{zone:'facade',source:'model'}};
      T.pick('CLN01',first);
      const firstPick={zone:T.form().zone,source:T.form().zoneSource,raw:first.zone};
      T.setZone('dining','pick');T.pick('CLN01',first);
      const repeated={zone:T.form().zone,source:T.form().zoneSource,raw:first.zone};
      const second={code:'CLN01',zone:'facade',resolution:{zone:'facade',source:'model'}};
      T.pick('CLN01',second);
      const switched={zone:T.form().zone,source:T.form().zoneSource,raw:second.zone};
      T.pick('CLN01',first);
      const restored={zone:T.form().zone,source:T.form().zoneSource,raw:first.zone};
      T.pick('CLN03');
      const manual={zone:T.form().zone,source:T.form().zoneSource};
      return {firstPick,repeated,switched,restored,manual};
    }""")
    assert got["firstPick"] == {"zone": "hot_kitchen", "source": "pick", "raw": "facade"}
    assert (
        got["repeated"] == got["restored"] == {"zone": "dining", "source": "pick", "raw": "facade"}
    )
    assert got["switched"] == {"zone": "facade", "source": "model", "raw": "facade"}
    assert got["manual"] == {"zone": "dining", "source": "pick"}


def test_screen_hint_remains_soft_before_point_choice(page, клиент: Клиент):
    bridge(page, клиент)
    bootstrap(page, sheet=True)
    result = page.evaluate("""()=>{const W=DecimusWalk;W.sheet.close(true);
      W.sheet.open({mode:'violation',hint:'dining'});
      W.testSubmit.pick('CLN01',{code:'CLN01',zone:'facade',resolution:{zone:'facade',source:'model'}});
      return {zone:W.testSubmit.form().zone,source:W.testSubmit.form().zoneSource};
    }""")
    assert result == {"zone": "facade", "source": "model"}


def test_contextual_measurement_uses_active_catalogue_and_saves_in_physical_zone(
    page, клиент: Клиент
):
    requests = bridge(page, клиент)
    bootstrap(page, sheet=True)
    page.evaluate("DecimusWalk.sheet.close(true)")
    source = (
        (STATIC / "walk.js")
        .read_text()
        .replace(
            "  theme();\n  load();\n})();",
            "  W.qaNavigation={renderStage:renderStage};\n})();",
        )
    )
    page.evaluate("Object.assign(DecimusWalk.tg,{ready:()=>{},expand:()=>{},onEvent:()=>{}})")
    page.evaluate("()=>{window.qaApply=DecimusWalk.apply;}")
    page.add_script_tag(content=source)
    page.evaluate("()=>{DecimusWalk.apply=qaApply;}")
    page.evaluate("""()=>{const W=DecimusWalk;W.unseenBlock=()=>null;
      W.finish={ask:()=>{throw Error('No finish QA');}};
      const zone=W.state.data.zones.find(z=>z.code==='dining');
      document.body.appendChild(W.qaNavigation.renderStage(zone));
    }""")
    label = page.evaluate("DecimusWalk.tx('walk.zone.measure_here')")
    page.get_by_role("button", name=label, exact=True).click()
    assert page.evaluate("DecimusWalk.testSubmit.form().zoneSource") == "pick"
    code = page.evaluate("""()=>{const W=DecimusWalk;
      const i=W.state.data.items.find(i=>i.measure&&!i.zones.length);
      W.testSubmit.pick(i.code);return i.code;
    }""")
    assert page.evaluate("DecimusWalk.testSubmit.form().zone") == "dining"
    page.locator("[data-finding-text]").fill("Synthetic measured equipment at counter")
    page.locator(".walk-pick--gallery input").set_input_files(picture(1))
    page.evaluate("online=true;DecimusWalk.offline.kick()")
    page.wait_for_function("()=>DecimusWalk.testSubmit.form().photos.some(p=>p.state==='done')")
    label = page.evaluate("DecimusWalk.tx('walk.sheet.save')")
    page.get_by_role("button", name=label, exact=True).click()
    page.wait_for_function("()=>!DecimusWalk.sheet.isOpen()")
    saved = get_state(АУДИТОР).findings
    assert len(saved) == 1 and saved[0].zone == "dining" and saved[0].code == code
    assert saved[0].level == "D0"
    assert [(body["code"], body["zone"]) for body in requests] == [(code, "dining")]


@pytest.mark.parametrize("explicit", [True, False])
def test_first_search_response_preserves_only_an_explicit_physical_context(
    page, клиент: Клиент, explicit
):
    bridge(page, клиент)
    bootstrap(page, sheet=True)
    page.evaluate(
        """explicit=>{const W=DecimusWalk;W.sheet.close(true);
      W.sheet.open({mode:'violation',hint:'dining'});
      if(explicit)W.testSubmit.setZone('dining','pick');
      W.urls.suggest='/qa-suggest';
    }""",
        explicit,
    )
    page.route(
        "https://walk.test/qa-suggest",
        lambda route: route.fulfill(
            json={
                "via": "model",
                "candidates": [
                    {
                        "code": "CLN01",
                        "level": "D1",
                        "zone": "facade",
                        "wording": "Synthetic proposal",
                        "confidence": 0.9,
                        "resolution": {"zone": "facade", "source": "model", "options": ["facade"]},
                    }
                ],
            }
        ),
    )
    page.locator(".walk-pick--gallery input").set_input_files(picture(1))
    page.evaluate("online=true;DecimusWalk.offline.kick()")
    page.wait_for_function("()=>DecimusWalk.testSubmit.form().photos.some(p=>p.state==='done')")
    page.locator(".walk-mark--find").click()
    page.locator(".walk-found__card").click()
    assert page.evaluate("DecimusWalk.testSubmit.form().zone") == (
        "dining" if explicit else "facade"
    )
    assert page.evaluate("DecimusWalk.testSubmit.form().picked.zone") == "facade"
