# ruff: noqa: F811
"""#1370: real DOM behaviour in isolated CFT, with synthetic Flask HTML and no server."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright
from test_web_acceptance import _приёмка, админ, стенд  # noqa: F401

from src.db.previews import FindingShots
from src.web import inspections, review


def _лист(monkeypatch):
    items = tuple(
        {"id": code, "kind": "violation", "question_ru": title, "zones": "*"}
        for code, title in [("CLN02", "Пол"), ("CLN05", "Стена")]
    )
    zones = ({"code": "KITCHEN", "name_ru": "Кухня"},)
    monkeypatch.setattr(
        review,
        "load_sheet",
        lambda _h, **kw: review.build_sheet(items=items, zones=zones, lang=kw["lang"]),
    )


ROOT = Path(__file__).resolve().parents[1]
CFT = Path.home() / (
    ".cache/chrome-for-testing/chrome/mac_arm-154.0.8037.57/"
    "chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"
)


@pytest.fixture
def browser_page():
    if not CFT.is_file():
        pytest.skip("Chrome for Testing is not installed at the documented location")
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=str(CFT), headless=True)
        page = browser.new_page()
        page.route("**/*", lambda route: route.abort())
        yield page
        browser.close()


def load(page, html):
    html = re.sub(r"<script\b[^>]*src=[^>]*>\s*</script>", "", html)
    page.set_content(html, wait_until="domcontentloaded")
    page.add_script_tag(path=str(ROOT / "src/web/static/proofread.js"))
    page.add_script_tag(path=str(ROOT / "src/web/static/split.js"))
    page.evaluate("""() => {
      window.calls = 0;
      window.alerts = [];
      window.alert = message => alerts.push(message);
      window.fetch = (url, opts) => {
        if (!opts || opts.method !== 'POST') return Promise.resolve({ok:false});
        calls++;
        return new Promise((resolve, reject) => {
          window.failSave = () => reject(new Error('offline'));
          window.finishSave = html => resolve({ok:true, text:() => Promise.resolve(html)});
        });
      };
    }""")


@админ
@pytest.mark.parametrize("address", ["/inspections/x", "/inspections?inspection=x"])
def test_item_review_and_unsaved_accept(стенд, monkeypatch, browser_page, address):
    _приёмка(monkeypatch)
    _лист(monkeypatch)
    page = browser_page
    load(page, стенд.get(address).get_data(as_text=True))
    assert page.locator("form[data-proofread-form]").evaluate_all(
        "(forms) => forms.every(f => !Proofread.dirty(f))"
    )
    page.locator("[data-proofread-edit]").first.click()
    form = page.locator('form[data-proofread-form="edit"]').first
    old_text = form.locator("textarea[name=text]").input_value()
    form.locator("[data-ipick-open]").click()
    # Synthetic checklist has CLN02 and CLN05; choose a different valid item.
    code = form.locator("[data-ipick-value]").input_value()
    form.locator(".ipick__opt").evaluate_all(
        "(opts, code) => opts.find(o => o.dataset.code !== code).click()", code
    )
    assert form.locator("textarea[name=text]").input_value() == old_text
    assert form.locator("[data-code-review]").is_visible()
    assert not form.evaluate("(f) => f.checkValidity()")
    form.locator("textarea[name=text]").press("Enter")
    assert page.evaluate("calls") == 0
    form.locator("[name=code_text_reviewed]").check()
    assert form.locator("[name=code_text_reviewed]").evaluate("(el) => el.validity.valid")
    # Shift+Enter inserts a newline; IME never triggers a save.
    text = form.locator("textarea[name=text]")
    text.fill("Факт")
    text.press("End")
    text.press("Shift+Enter")
    assert text.input_value() == "Факт\n"
    assert text.evaluate(
        '(el) => el.dispatchEvent(new KeyboardEvent("keydown", {key:"Enter", isComposing:true, '
        "bubbles:true, cancelable:true}))"
    )
    assert not form.locator("[data-code-review]").is_visible()
    page.locator("[data-accept-guard]").evaluate(
        '(f) => f.dispatchEvent(new SubmitEvent("submit", {bubbles:true, cancelable:true}))'
    )
    assert page.evaluate("calls") == 0
    assert len(page.evaluate("alerts")) == 1


@админ
@pytest.mark.parametrize("failure", [False, True, "network"])
@pytest.mark.parametrize(
    "address, container", [("/inspections?inspection=x", ".spanel"), ("/inspections/x", ".icard")]
)
def test_preserves_other_drafts_and_files_during_save(
    стенд, monkeypatch, browser_page, failure, address, container
):
    _приёмка(monkeypatch)
    _лист(monkeypatch)
    page = browser_page
    monkeypatch.setattr(
        inspections,
        "load_previews",
        lambda *_a, **_k: {"f1": FindingShots(shown=("synthetic-existing",), missing=0)},
    )
    html = стенд.get(address).get_data(as_text=True)
    load(page, html)
    page.locator("[data-proofread-edit]").first.click()
    edit = page.locator('form[data-proofread-form="edit"]').first
    edit.locator("[name=text]").fill("Осознанная правка аудитора")
    edit.locator("[data-pshots-input]").set_input_files(
        {"name": "edit.png", "mimeType": "image/png", "buffer": b"synthetic edit"}
    )
    edit.locator("[data-pshot-remove]").check()

    page.locator("[data-proofread-add]").click()
    composer = page.locator('form[data-proofread-form="add"]')
    composer.locator("[name=text]").fill("Второй несохранённый факт")
    composer.locator("[data-pshots-input]").set_input_files(
        {"name": "synthetic.png", "mimeType": "image/png", "buffer": b"synthetic"}
    )
    # Set a valid classification to exercise snapshot restoration rather than validation.
    composer.locator(".ipick__opt").first.click()
    composer.locator("[data-lvls] input:not(:disabled)").first.check()
    edit.locator("button[type=submit]").click()
    assert page.evaluate("calls") == 1
    assert page.locator(container).evaluate("(p) => p.inert")
    page.locator("[data-accept-guard]").evaluate(
        '(f) => f.dispatchEvent(new SubmitEvent("submit", {bubbles:true, cancelable:true}))'
    )
    assert page.evaluate("calls") == 1
    response = html
    if failure is True:
        # Insert a genuine server refusal notice into the returned panel.
        response = re.sub(
            rf'(<[^>]+class="[^"]*{container[1:]}[^"]*"[^>]*>)',
            r'\1<div class="note note--error">Отказ</div>',
            response,
            count=1,
        )
    if failure == "network":
        page.evaluate("failSave()")
    else:
        page.evaluate("(html) => finishSave(html)", response)
    page.wait_for_function("(selector) => !document.querySelector(selector).inert", arg=container)
    composer = page.locator('form[data-proofread-form="add"]')
    assert composer.locator("[name=text]").input_value() == "Второй несохранённый факт"
    assert (
        composer.locator("[data-pshots-input]").evaluate("(el) => el.files[0].name")
        == "synthetic.png"
    )
    if failure:
        assert page.locator('form[data-proofread-form="edit"] [data-pshot-remove]').is_checked()
        assert (
            page.locator('form[data-proofread-form="edit"] [data-pshots-input]').evaluate(
                "(el) => el.files[0].name"
            )
            == "edit.png"
        )
        assert (
            page.locator('form[data-proofread-form="edit"] [name=text]').first.input_value()
            == "Осознанная правка аудитора"
        )
    page.locator("[data-accept-guard]").evaluate(
        '(f) => f.dispatchEvent(new SubmitEvent("submit", {bubbles:true, cancelable:true}))'
    )
    assert page.evaluate("calls") == 1


@админ
@pytest.mark.parametrize("address", ["/inspections/x", "/inspections?inspection=x"])
@pytest.mark.parametrize("field", ["text", "reading_c"])
def test_enter_submits_only_current_edit_and_keeps_photos(
    стенд, monkeypatch, browser_page, address, field
):
    from dataclasses import replace

    from test_web_acceptance import ТЕНАНТ
    from test_web_app import карточка, шапка

    _приёмка(monkeypatch)
    _лист(monkeypatch)
    detail = карточка(шапка(on_review=True, tenant_code=ТЕНАНТ))
    finding = replace(detail.findings[0], reading_c=4)
    monkeypatch.setattr(
        inspections, "load_card", lambda *args, **kw: replace(detail, findings=(finding,))
    )
    monkeypatch.setattr(
        inspections,
        "load_previews",
        lambda *args, **kw: {finding.id: FindingShots(shown=("synthetic-existing",), missing=0)},
    )
    page = browser_page
    load(page, стенд.get(address).get_data(as_text=True))
    page.evaluate("""() => {
      window.payloads = [];
      window.fetch = (url, opts) => {
        payloads.push({url, text:opts.body.get('text'), reading:opts.body.get('reading_c'),
          files:opts.body.getAll('photo').map(f=>f.name),
          removed:opts.body.getAll('remove_photo')});
        calls++;
        return new Promise(()=>{});
      };
    }""")
    page.locator("[data-proofread-edit]").first.click()
    form = page.locator('form[data-proofread-form="edit"]').first
    form.evaluate(
        "(f) => f.action = new URL(f.getAttribute('action'), 'https://proofread.test').href"
    )
    form.locator("[name=text]").fill("Current edited comment")
    form.locator("[name=reading_c]").fill("5")
    form.locator("[data-pshots-input]").set_input_files(
        {"name": "new.png", "mimeType": "image/png", "buffer": b"synthetic"}
    )
    form.locator("[data-pshot-remove]").check()
    form.locator("[name=" + field + "]").press("Enter")
    assert page.evaluate("calls") == 1
    (payload,) = page.evaluate("payloads")
    assert f"/findings/{finding.id}/revise" in payload["url"]
    assert payload["text"] == "Current edited comment"
    assert payload["reading"] == "5"
    assert payload["files"] == ["new.png"]
    assert payload["removed"] == ["synthetic-existing"]


@админ
@pytest.mark.parametrize("address", ["/inspections/x", "/inspections?inspection=x"])
def test_enter_reaches_flask_revision_without_http_server(
    стенд, monkeypatch, browser_page, address
):
    import mimetypes
    from urllib.parse import urlsplit

    from web_harness import войти

    from src.web import revision

    _приёмка(monkeypatch)
    _лист(monkeypatch)
    saved = []
    monkeypatch.setattr(
        revision, "revise_card", lambda ident, finding, **kw: saved.append((ident, finding, kw))
    )
    client = стенд.application.test_client()
    assert войти(client).status_code == 302
    page = browser_page

    def route(r):
        parsed = urlsplit(r.request.url)
        if parsed.path.startswith("/static/"):
            file = ROOT / "src/web/static" / parsed.path.removeprefix("/static/")
            if file.is_file():
                r.fulfill(
                    body=file.read_bytes(),
                    content_type=mimetypes.guess_type(str(file))[0] or "application/octet-stream",
                )
            else:
                r.fulfill(status=404, body="")
            return
        headers = {"Origin": "http://localhost"}
        for key in ("content-type", "x-panel"):
            if key in r.request.headers:
                headers[key] = r.request.headers[key]
        response = client.open(
            parsed.path + ("?" + parsed.query if parsed.query else ""),
            method=r.request.method,
            data=r.request.post_data_buffer,
            headers=headers,
        )
        r.fulfill(
            status=response.status_code, headers=dict(response.headers), body=response.get_data()
        )

    page.route("https://proofread.test/**", route)
    page.goto("https://proofread.test" + address)
    page.locator("[data-proofread-edit]").first.click()
    text = page.locator('form[data-proofread-form="edit"] textarea[name=text]').first
    text.fill("Explicit comment saved by Enter")
    text.press("Enter")
    page.wait_for_function("() => !document.querySelector('[data-proofread-busy]')")
    assert len(saved) == 1
    from test_web_app import шапка

    assert saved[0][0] == шапка().id
    assert saved[0][1] == "f1"
    assert saved[0][2]["text"] == "Explicit comment saved by Enter"


@админ
def test_enter_composer_and_ime_modifiers(стенд, monkeypatch, browser_page):
    _приёмка(monkeypatch)
    _лист(monkeypatch)
    page = browser_page
    load(page, стенд.get("/inspections/x").get_data(as_text=True))
    page.locator("[data-proofread-add]").click()
    form = page.locator('form[data-proofread-form="add"]')
    form.locator(".ipick__opt").first.click()
    form.locator("[data-lvls] input:not(:disabled)").first.check()
    text = form.locator("textarea[name=text]")
    text.fill("New comment")
    for extra in (
        {"isComposing": True},
        {"keyCode": 229},
        {"repeat": True},
        {"ctrlKey": True},
        {"altKey": True},
        {"metaKey": True},
    ):
        text.evaluate(
            "(el, extra) => el.dispatchEvent(new KeyboardEvent('keydown', "
            "{...extra, key:'Enter', bubbles:true, cancelable:true}))",
            extra,
        )
    assert page.evaluate("calls") == 0
    text.press("Shift+Enter")
    assert text.input_value() == "New comment\n"
    assert page.evaluate("calls") == 0
    text.press("Enter")
    assert page.evaluate("calls") == 1
