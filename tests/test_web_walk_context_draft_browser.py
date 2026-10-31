"""Contextual measurement drafts keep each physical zone's actual IDB evidence."""

from __future__ import annotations

import pytest

# ruff: noqa: F811
from test_web_walk_retained_browser import bootstrap, bridge, picture
from test_web_walk_ux_browser import STATIC, page  # noqa: F401
from test_web_walk_write import Клиент, клиент  # noqa: F401


def navigation(page):
    source = (
        (STATIC / "walk.js")
        .read_text()
        .replace(
            "  theme();\n  load();\n})();", "  W.qaNavigation={renderStage:renderStage};\n})();"
        )
    )
    page.evaluate("""()=>{const W=DecimusWalk;W.sheet.close(true);window.qaApply=W.apply;
      Object.assign(W.tg,{ready:()=>{},expand:()=>{},onEvent:()=>{}});
    }""")
    page.add_script_tag(content=source)
    page.evaluate("""()=>{const W=DecimusWalk;W.apply=qaApply;W.unseenBlock=()=>null;
      W.finish={ask:()=>{throw Error('No finish in QA');}};
      ['dining','hot_kitchen'].forEach(code=>{const zone=W.state.data.zones.find(z=>z.code===code);
        const node=W.qaNavigation.renderStage(zone);node.dataset.qaZone=code;
        document.body.appendChild(node);});
    }""")


def open_zone(page, zone):
    label = page.evaluate("DecimusWalk.tx('walk.zone.measure_here')")
    page.locator(f'[data-qa-zone="{zone}"]').get_by_role("button", name=label, exact=True).click()


def add_packet(page, number, text):
    page.evaluate("""()=>{const W=DecimusWalk;
      const item=W.state.data.items.find(i=>i.measure&&!i.zones.length);
      W.testSubmit.pick(item.code);}
    """)
    page.locator("[data-finding-text]").fill(text)
    page.locator(".walk-pick--gallery input").set_input_files(picture(number))
    page.evaluate("online=true;DecimusWalk.offline.kick()")
    page.wait_for_function("()=>DecimusWalk.testSubmit.form().photos.some(p=>p.state==='done')")
    return page.evaluate("""()=>{const f=DecimusWalk.testSubmit.form();
      return {key:f.draftKey,ref:f.photos[0].ref};}
    """)


@pytest.mark.parametrize("fault_kind", ["failure", "lost_reply"])
def test_other_explicit_zone_does_not_adopt_previous_measurement_packet(
    page, клиент: Клиент, fault_kind
):
    faults = {"failed": False, "lost": False}
    requests = bridge(page, клиент, fault=faults)
    bootstrap(page, sheet=True)
    navigation(page)
    open_zone(page, "dining")
    packet = add_packet(page, 1, "Human measurement A")
    assert клиент.показ(packet["ref"]).status_code == 404
    page.evaluate("DecimusWalk.sheet.close(true)")
    open_zone(page, "hot_kitchen")
    actual = page.evaluate("""()=>{const f=DecimusWalk.testSubmit.form();
      return {zone:f.zone,text:f.text,photos:f.photos.map(p=>p.ref),source:f.zoneSource};}
    """)
    assert actual == {"zone": "hot_kitchen", "text": "", "photos": [], "source": "pick"}
    rows = page.evaluate(
        "key=>DecimusWalk.offline.list(key).then(rows=>rows.map(r=>({ref:r.uploaded_ref,bytes:r.bytes})))",
        packet["key"],
    )
    assert len(rows) == 1 and rows[0]["ref"] == packet["ref"] and rows[0]["bytes"] > 0
    packet_b = add_packet(page, 2, "Human measurement B")
    assert packet_b["key"] != packet["key"] and packet_b["ref"] != packet["ref"]
    page.reload()
    bootstrap(page, sheet=True)
    navigation(page)
    open_zone(page, "dining")
    restored_packet(page, packet, "Human measurement A", "dining")
    page.evaluate("DecimusWalk.sheet.close(true)")
    open_zone(page, "hot_kitchen")
    restored_packet(page, packet_b, "Human measurement B", "hot_kitchen")
    label = page.evaluate("DecimusWalk.tx('walk.sheet.save')")
    code = page.evaluate("DecimusWalk.testSubmit.form().code")
    faults["fail_code" if fault_kind == "failure" else "lost_code"] = code
    page.get_by_role("button", name=label, exact=True).click()
    page.wait_for_function(
        "()=>{const f=DecimusWalk.testSubmit.form();return f&&!f.saving&&f.error;}"
    )
    assert (
        page.evaluate("key=>DecimusWalk.offline.list(key).then(rows=>rows.length)", packet_b["key"])
        == 1
    )
    page.get_by_role("button", name=label, exact=True).click()
    page.wait_for_function("()=>!DecimusWalk.sheet.isOpen()")
    assert len(requests) == (2 if fault_kind == "failure" else 1)
    assert (
        page.evaluate("key=>DecimusWalk.offline.list(key).then(rows=>rows.length)", packet_b["key"])
        == 0
    )
    assert (
        page.evaluate("key=>DecimusWalk.offline.list(key).then(rows=>rows.length)", packet["key"])
        == 1
    )
    assert клиент.показ(packet["ref"]).status_code == 404
    assert клиент.показ(packet_b["ref"]).status_code == 200
    open_zone(page, "dining")
    restored_packet(page, packet, "Human measurement A", "dining")
    page.get_by_role("button", name=label, exact=True).click()
    page.wait_for_function("()=>!DecimusWalk.sheet.isOpen()")
    assert (
        page.evaluate("key=>DecimusWalk.offline.list(key).then(rows=>rows.length)", packet["key"])
        == 0
    )
    assert клиент.показ(packet["ref"]).status_code == 200


def restored_packet(page, packet, text, zone):
    page.wait_for_function(
        'ref=>DecimusWalk.testSubmit.form().photos.some(p=>p.ref===ref&&p.state==="done")',
        arg=packet["ref"],
    )
    assert page.evaluate("DecimusWalk.testSubmit.form().zone") == zone
    assert page.locator("[data-finding-text]").input_value() == text
    page.wait_for_function(
        '()=>[...document.querySelectorAll(".walk-sheet img")]'
        '.some(img=>img.src.startsWith("blob:")&&img.naturalWidth>0)'
    )
    assert page.evaluate("DecimusWalk.testSubmit.form().photos.filter(p=>p.ref).map(p=>p.ref)") == [
        packet["ref"]
    ]


def test_matching_legacy_global_measurement_keeps_original_receipt_namespace(page, клиент: Клиент):
    bridge(page, клиент)
    bootstrap(page, sheet=True)
    page.evaluate(
        "()=>{DecimusWalk.sheet.close(true);DecimusWalk.sheet.open({mode:'measure',zone:'dining'});}"
    )
    packet = add_packet(page, 1, "Legacy human measurement A")
    assert packet["key"].endswith("_draft")
    navigation(page)
    open_zone(page, "hot_kitchen")
    assert page.evaluate("DecimusWalk.testSubmit.form().zone") == "hot_kitchen"
    assert page.locator("[data-finding-text]").input_value() == ""  # No A text was imported.
    page.evaluate("DecimusWalk.sheet.close(true)")
    open_zone(page, "dining")
    restored_packet(page, packet, "Legacy human measurement A", "dining")
    assert page.evaluate("DecimusWalk.testSubmit.form().draftKey") == packet["key"]


def test_closed_pending_context_upload_stays_in_its_own_zone(page, клиент: Клиент):
    bridge(page, клиент)
    bootstrap(page, sheet=True)
    navigation(page)
    open_zone(page, "dining")
    page.evaluate("""()=>{const W=DecimusWalk;
      const item=W.state.data.items.find(i=>i.measure&&!i.zones.length);
      W.testSubmit.pick(item.code);}
    """)
    page.locator("[data-finding-text]").fill("Offline human measurement A")
    page.locator(".walk-pick--gallery input").set_input_files(picture(1))
    key_a = page.evaluate("DecimusWalk.testSubmit.form().draftKey")
    page.wait_for_function(
        "key=>DecimusWalk.offline.list(key).then(rows=>rows.length===1)", arg=key_a
    )
    page.evaluate("DecimusWalk.sheet.close(true)")
    open_zone(page, "hot_kitchen")
    packet_b = add_packet(page, 2, "Human measurement B")
    packet_a = page.evaluate(
        "key=>DecimusWalk.offline.list(key).then(rows=>({key,ref:rows[0].uploaded_ref,bytes:rows[0].bytes}))",
        key_a,
    )
    assert packet_a["ref"] and packet_a["bytes"] > 0
    assert page.evaluate("DecimusWalk.testSubmit.form().photos.filter(p=>p.ref).map(p=>p.ref)") == [
        packet_b["ref"]
    ]
    page.evaluate("DecimusWalk.sheet.close(true)")
    open_zone(page, "dining")
    restored_packet(page, packet_a, "Offline human measurement A", "dining")
    assert клиент.показ(packet_a["ref"]).status_code == 404


def navigate_from_form(page, zone):
    label = page.evaluate("DecimusWalk.tx('walk.sheet.context_other_zone')")
    page.get_by_role("button", name=label, exact=True).click()
    title = page.evaluate("code=>DecimusWalk.state.data.zones.find(z=>z.code===code).title", zone)
    page.locator(".walk-menu").get_by_role("button", name=title, exact=True).click()


def test_context_form_navigation_names_its_intent_and_preserves_both_packets(page, клиент: Клиент):
    bridge(page, клиент)
    bootstrap(page, sheet=True)
    navigation(page)
    open_zone(page, "dining")
    packet_a = add_packet(page, 1, "Human measurement A")
    label = page.evaluate("DecimusWalk.tx('walk.sheet.context_other_zone')")
    assert label == "Перейти к замерам другой зоны"
    assert page.get_by_role("button", name=label, exact=True).count() == 1
    zone_title = page.evaluate("DecimusWalk.state.data.zones.find(z=>z.code==='dining').title")
    warning = page.evaluate("zone=>DecimusWalk.tx('walk.sheet.context_kept',{zone})", zone_title)
    assert page.get_by_text(warning, exact=True).is_visible()
    navigate_from_form(page, "hot_kitchen")
    assert page.evaluate("DecimusWalk.testSubmit.form().zone") == "hot_kitchen"
    assert page.locator("[data-finding-text]").input_value() == ""
    assert page.evaluate("DecimusWalk.testSubmit.form().photos.length") == 0
    packet_b = add_packet(page, 2, "Human measurement B")
    navigate_from_form(page, "dining")
    restored_packet(page, packet_a, "Human measurement A", "dining")
    assert (
        page.evaluate("key=>DecimusWalk.local.get(key).text", packet_b["key"])
        == "Human measurement B"
    )
    assert (
        page.evaluate("key=>DecimusWalk.offline.list(key).then(rows=>rows.length)", packet_b["key"])
        == 1
    )


def test_ordinary_measurement_zone_picker_still_moves_the_current_packet(page, клиент: Клиент):
    bridge(page, клиент)
    bootstrap(page, sheet=True)
    page.evaluate(
        "()=>{DecimusWalk.sheet.close(true);DecimusWalk.sheet.open({mode:'measure',zone:'dining'});}"
    )
    packet = add_packet(page, 1, "Current measurement to move")
    assert page.get_by_role("button", name="Перейти к замерам другой зоны", exact=True).count() == 0
    page.locator(".walk-ctx__pill--zone").click()
    title = page.evaluate("DecimusWalk.state.data.zones.find(z=>z.code==='hot_kitchen').title")
    page.locator(".walk-menu").get_by_role("button", name=title, exact=True).click()
    restored_packet(page, packet, "Current measurement to move", "hot_kitchen")
    assert page.evaluate("DecimusWalk.testSubmit.form().draftKey") == packet["key"]


def test_context_navigation_waits_until_new_frame_bytes_are_durable(page, клиент: Клиент):
    bridge(page, клиент)
    bootstrap(page, sheet=True)
    navigation(page)
    open_zone(page, "dining")
    page.evaluate("""()=>{const W=DecimusWalk;
      const item=W.state.data.items.find(i=>i.measure&&!i.zones.length);
      W.testSubmit.pick(item.code);const compress=W.photo.compress;
      W.photo.compress=file=>new Promise(resolve=>{
        window.releaseCompression=()=>compress(file).then(resolve);});}
    """)
    page.locator("[data-finding-text]").fill("Frame still compressing A")
    page.locator(".walk-pick--gallery input").set_input_files(picture(1))
    navigate_from_form(page, "hot_kitchen")
    assert page.evaluate("DecimusWalk.testSubmit.form().zone") == "dining"
    assert page.evaluate("DecimusWalk.testSubmit.form().photos.length") == 1
    page.evaluate("releaseCompression()")
    page.wait_for_function("()=>DecimusWalk.testSubmit.form().photos.some(p=>p.entryId)")
    navigate_from_form(page, "hot_kitchen")
    assert page.evaluate("DecimusWalk.testSubmit.form().photos.length") == 0
    navigate_from_form(page, "dining")
    assert page.locator("[data-finding-text]").input_value() == "Frame still compressing A"
    page.wait_for_function(
        '()=>[...document.querySelectorAll(".walk-sheet img")]'
        '.some(img=>img.naturalWidth>0&&img.src.startsWith("blob:"))'
    )


def test_context_navigation_waits_for_current_save_ack(page, клиент: Клиент):
    import json

    from src.web.walk_auth import FINDING_PATH

    bridge(page, клиент)
    bootstrap(page, sheet=True)
    navigation(page)
    open_zone(page, "dining")
    packet = add_packet(page, 1, "Human measurement awaiting acknowledgement")
    pending = []

    def hold(route):
        response = клиент.запись(**json.loads(route.request.post_data))
        assert response.status_code == 200, response.get_json()
        pending.append((route, response))

    page.route("https://walk.test" + FINDING_PATH, hold)
    label = page.evaluate("DecimusWalk.tx('walk.sheet.save')")
    page.get_by_role("button", name=label, exact=True).click()
    page.wait_for_function("()=>DecimusWalk.testSubmit.form().saving")
    navigate_from_form(page, "hot_kitchen")
    assert page.evaluate("DecimusWalk.testSubmit.form().zone") == "dining"
    route, response = pending[0]
    route.fulfill(
        status=response.status_code, content_type=response.content_type, body=response.data
    )
    page.wait_for_function("()=>!DecimusWalk.sheet.isOpen()")
    assert (
        page.evaluate("key=>DecimusWalk.offline.list(key).then(rows=>rows.length)", packet["key"])
        == 0
    )
