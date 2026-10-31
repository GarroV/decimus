"""Chrome DOM → real Flask/domain split, no listening server or external services.

Run: PYTHONPATH=.:tests python tests/browser/walk_split_smoke.py --chrome /path/to/Chrome
"""

from __future__ import annotations

import argparse
import json
import logging
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from bot_harness import bound_only
from playwright.sync_api import sync_playwright
from pytest import MonkeyPatch
from test_web_walk import АУДИТОР, ТОКЕН, _приложение
from test_web_walk_write import ДРУГОЙ_JPEG, Клиент, _нарушение

from src.domain import get_state, score, start_inspection
from src.web import walk, walk_access, walk_write

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--chrome", required=True)
args = parser.parse_args()
logging.disable(logging.WARNING)

with (
    tempfile.TemporaryDirectory(prefix="decimus-split-smoke-") as temporary,
    MonkeyPatch.context() as mp,
):
    mp.setenv("AUDIT_DATA_DIR", str(ROOT / "tests/methodology"))
    mp.setenv("STATE_DIR", str(Path(temporary) / "state"))
    mp.delenv("MCP_CHECKLIST_STORE", raising=False)
    mp.delenv("DATABASE_URL", raising=False)
    mp.chdir(temporary)
    mp.setattr(walk.queries, "previous_findings", lambda **_: None)
    mp.setattr(walk_access.bot_links, "standing", bound_only(АУДИТОР))
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=args.chrome, headless=True)
        for width, lang in [(1440, "ru"), (390, "en")]:
            start_inspection(
                АУДИТОР, unit="Synthetic", kind="planned", report_lang=lang, ui_lang=lang
            )
            client = Клиент(_приложение(mp, TELEGRAM_BOT_TOKEN=ТОКЕН).test_client())
            a, b = client.ссылка(), client.ссылка(ДРУГОЙ_JPEG)
            assert (
                client.запись(
                    **_нарушение(a, photos=[a, b], text="Synthetic combined source")
                ).status_code
                == 200
            )
            data = client.c.post(
                walk.DATA_PATH, data=client.init, content_type="text/plain"
            ).get_json()
            source = next(row for zone in data["zones"] for row in zone["recorded"])
            page = browser.new_page(viewport={"width": width, "height": 900})
            attempts = []

            def route(request_route, _request, *, client=client, attempts=attempts):
                request = request_route.request
                path = urlsplit(request.url).path
                if path == "/":
                    request_route.fulfill(
                        content_type="text/html",
                        body="""<html><body><div id="walk"
                      data-finding="/tg/walk/finding"
                      data-photo-view="/tg/walk/photo/view"></div></body></html>""",
                    )
                    return
                response = client.c.post(
                    path,
                    data=request.post_data_buffer,
                    content_type=request.headers.get("content-type"),
                    headers={"X-Telegram-Init-Data": client.init},
                )
                if path == walk_write.FINDING_PATH:
                    attempts.append(json.loads(request.post_data))
                    assert response.status_code == 200, response.get_json()
                    if len(attempts) == 1:  # successful server commit, lost response to the phone
                        request_route.fulfill(
                            status=503,
                            content_type="application/json",
                            body='{"message":"synthetic lost reply"}',
                        )
                        return
                request_route.fulfill(
                    status=response.status_code,
                    body=response.get_data(),
                    content_type=response.content_type,
                )

            page.route("https://split.test/**", route)

            def boot(page=page, data=data, source=source):
                page.goto("https://split.test/")
                page.add_script_tag(content=(ROOT / "src/web/static/walk-core.js").read_text())
                page.evaluate(
                    "(body)=>{DecimusWalk.state.data=body;DecimusWalk.apply=body=>{DecimusWalk.state.data=body;};}",
                    data,
                )
                page.add_script_tag(content=(ROOT / "src/web/static/walk-photo.js").read_text())
                page.add_script_tag(content=(ROOT / "src/web/static/walk-split.js").read_text())
                page.evaluate("(source)=>DecimusWalk.split.open(source)", source)

            boot()
            page.wait_for_function(
                'document.querySelectorAll("img").length >= 2 && '
                'Array.from(document.querySelectorAll("img")).every(img=>img.naturalWidth>0)'
            )
            for i, code in enumerate(["CLN05", "CLN06"]):
                part = page.locator("fieldset").nth(i)
                assert part.locator("textarea").nth(0).input_value() == ""
                assert part.locator("input[type=checkbox]:checked").count() == 0
                part.locator("select").nth(0).select_option(code)
                part = page.locator("fieldset").nth(i)
                part.locator("select").nth(1).select_option("D1")
                part.locator("select").nth(2).select_option("hot_kitchen")
                part.locator("textarea").nth(0).fill("Synthetic child " + str(i + 1))
                part.locator("input[type=checkbox]").nth(i + 1).check()
            # An explicitly shared frame needs an additional consent, never auto-copy.
            page.locator("fieldset").nth(1).locator("input[type=checkbox]").nth(1).check()
            page.reload()
            boot()
            assert (
                page.locator("fieldset").nth(0).locator("textarea").nth(0).input_value()
                == "Synthetic child 1"
            )
            assert (
                page.locator("fieldset").nth(1).locator("input[type=checkbox]:checked").count() == 2
            )
            review = data["texts"]["walk.split.review"]
            confirm = data["texts"]["walk.split.confirm"]
            page.get_by_role("button", name=review, exact=True).click()
            page.get_by_role("button", name=confirm, exact=True).click()
            assert attempts == []
            checks = page.locator("input[type=checkbox]")
            checks.nth(1).check()
            page.get_by_role("button", name=confirm, exact=True).click()
            assert attempts == []
            page.locator("input[type=checkbox]").nth(0).check()
            page.locator("input[type=checkbox]").nth(1).check()
            page.get_by_role("button", name=confirm, exact=True).click()
            page.wait_for_selector("text=synthetic lost reply")
            assert len(get_state(АУДИТОР).finding_history) == 1
            page.locator("input[type=checkbox]").nth(0).check()
            page.locator("input[type=checkbox]").nth(1).check()
            page.get_by_role("button", name=confirm, exact=True).click()
            page.wait_for_function("!DecimusWalk.split.isOpen()")
            assert len(attempts) == 2 and attempts[0] == attempts[1]
            current = get_state(АУДИТОР)
            assert len(current.findings) == 2 and len(current.finding_history) == 1
            assert [child.photos for child in current.findings] == [[a], [b, a]]
            assert score(АУДИТОР).counts["D1"] == 2
            assert (
                page.evaluate(
                    "(key)=>DecimusWalk.local.get(key)", data["key"] + "_split_" + str(source["n"])
                )
                is None
            )
            page.evaluate("document.body.appendChild(DecimusWalk.split.historyPanel())")
            page.locator("details summary").click()
            assert "Synthetic combined source" in page.locator("details").inner_text()
            assert "Synthetic child 1" in page.locator("details").inner_text()
            print(
                f"{lang} {width}: blank parts, explicit photos/shared consent, reload, "
                "lost reply retry, real engine/state/history: PASS"
            )
            page.close()
        browser.close()
