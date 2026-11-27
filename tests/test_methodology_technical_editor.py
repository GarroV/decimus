"""Checkpoint edits retain editions and identity, and reject stale or unauthorized forms."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from threading import Barrier
from typing import Any

import pytest
from mcp_checklist_harness import build_edition
from web_harness import СВОЙ, войти, подменить_двери, собрать

from src.domain import get_state, start_inspection
from src.domain.state import finish_inspection
from src.domain.technical import TechnicalRefused, confirm, manifest, snapshot
from src.mcp.checklist import Store, current_version, read_journal, tip_version
from src.web import methodology as method
from src.web.errors import MethodologyRefused
from src.web.texts import t


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Store:
    data = tmp_path / "data"
    build_edition(data, name="editor", day="2026-11-01")
    initial = Store(root=tmp_path / "store", live=data)
    current_version(initial)
    working = replace(initial, live=initial.root / "current")
    monkeypatch.setenv("MCP_CHECKLIST_STORE", str(working.root))
    monkeypatch.setenv("AUDIT_DATA_DIR", str(working.live))
    return working


def fields(**overrides: Any) -> dict[str, Any]:
    return {
        "title_ru": "Контроль поверхности",
        "title_en": "Surface check",
        "guidance_ru": "Осмотреть поверхность",
        "guidance_en": "Inspect the surface",
        "applicability_ru": "При наличии",
        "applicability_en": "If present",
        "zones": ["fridge"],
        "countries": [],
        "required": True,
        "requires_photo": False,
        "enabled": True,
        "kind": "violation",
        **overrides,
    }


def save(
    store: Store, ident: str = "", expected: str | None = None, **overrides: Any
) -> method.Edit:
    return method.edit_technical(
        store,
        tenant="HQ",
        author="editor",
        code="CLN01",
        check_id=ident,
        expected_version=tip_version(store) if expected is None else expected,
        fields=fields(**overrides),
    )


def point(store: Store, version: str) -> dict[str, Any]:
    return method.load_technical(store, version=version, code="CLN01")[0]


def test_versions_pinning_disable_reenable_and_sealed_history(
    domain_env: Path,
    store: Store,
) -> None:
    original = current_version(store)
    first = save(store)
    ident = point(store, first.version)["id"]
    assert first.version != original
    assert current_version(store) == original
    assert manifest(store.live) == []
    method.publish_version(store, tenant="HQ", version=first.version)
    start_inspection(808, unit="Sample-1", kind="planned", report_lang="en", auditor="Editor")
    with pytest.raises(TechnicalRefused, match="pending"):
        run = get_state(808)
        assert run
        finish_inspection(808, run.run_id, datetime.now(UTC))

    disabled = save(store, ident, enabled=False)
    method.publish_version(store, tenant="HQ", version=disabled.version)
    assert manifest(store.live) == []
    assert point(store, disabled.version)["id"] == ident
    # Already running inspection uses the edition pinned before the edit.
    assert snapshot(808)["required_pending"] == 1
    run = get_state(808)
    assert run
    confirm(808, run_id=run.run_id, check_id=ident, zone="fridge", status="ok")
    finish_inspection(808, run.run_id, datetime.now(UTC))
    sealed = snapshot(808)
    restored = save(store, ident)
    assert restored.version not in {disabled.version, first.version}
    assert point(store, restored.version)["id"] == ident
    with pytest.raises(MethodologyRefused) as unchanged:
        save(store, ident)
    assert unchanged.value.key == "refusal.edit_changed_nothing"
    assert point(store, first.version)["title_en"] == "Surface check"
    method.publish_version(store, tenant="HQ", version=restored.version)
    assert snapshot(808) == sealed
    start_inspection(809, unit="Sample-1", kind="planned", report_lang="en", auditor="Editor")
    assert snapshot(809)["required_pending"] == 1


def test_concurrent_forms_one_wins_without_overwriting(store: Store) -> None:
    base = tip_version(store)
    ready = Barrier(2)

    def write(title: str) -> str:
        ready.wait()
        try:
            return save(store, expected=base, title_en=title).version
        except MethodologyRefused as exc:
            assert exc.key == "refusal.edit_stale"
            return "stale"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write, ["First", "Second"]))
    assert results.count("stale") == 1
    assert tip_version(store) == next(r for r in results if r != "stale")
    assert len(method.load_technical(store, version=tip_version(store), code="CLN01")) == 1


@pytest.mark.parametrize(
    "change", [{"zones": ["missing"]}, {"countries": ["SERBIA"]}, {"title_en": ""}]
)
def test_invalid_manifest_never_creates_a_version(store: Store, change: dict[str, Any]) -> None:
    base = tip_version(store)
    with pytest.raises(MethodologyRefused) as exc:
        save(store, **change)
    assert exc.value.key == "refusal.technical_invalid"
    assert tip_version(store) == base
    assert current_version(store) == base


class Forms(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.depth = 0
        self.nested = False
        self.technical = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "form":
            self.nested |= self.depth > 0
            self.depth += 1
            self.technical += "data-technical-form" in dict(attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag == "form":
            self.depth -= 1


def form_data(store: Store) -> dict[str, Any]:
    data = fields()
    data.update(expected_version=tip_version(store), check_id="", countries="RS, BY")
    for key in ("required", "enabled", "requires_photo"):
        data[key] = "1" if data[key] else "0"
    return data


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_card_form_saves_version_and_rejects_stale_post(
    store: Store,
    monkeypatch: pytest.MonkeyPatch,
    lang: str,
) -> None:
    подменить_двери(monkeypatch, tenant="HQ", role="admin")
    url = f"/admin/items/CLN01/technical?checklist=bizdev&lang={lang}"
    with собрать(tenant="HQ", ui_lang=lang).test_client() as client:
        войти(client)
        page = client.get(f"/admin?checklist=bizdev&item=CLN01&lang={lang}")
        parser = Forms()
        parser.feed(page.get_data(as_text=True))
        assert not parser.nested
        assert parser.technical == 1
        data = form_data(store)
        data["note"] = "Checkpoint configuration"
        original = current_version(store)
        result = client.post(url, data=data, headers={"Origin": СВОЙ})
        assert result.status_code == 200
        latest = tip_version(store)
        assert latest != original
        assert read_journal(store)[-1]["note"].endswith("Checkpoint configuration")
        saved_forms = Forms()
        saved_forms.feed(result.get_data(as_text=True))
        assert not saved_forms.nested
        assert saved_forms.technical == 2
        assert current_version(store) == original
        assert point(store, latest)["countries"] == ["RS", "BY"]
        assert t("methodology.saved", lang, version=latest) in result.get_data(as_text=True)
        stale = client.post(url, data=data, headers={"Origin": СВОЙ})
        assert t("refusal.edit_stale", lang) in stale.get_data(as_text=True)
        assert tip_version(store) == latest


@pytest.mark.parametrize(("tenant", "role"), [("HQ", "auditor"), ("AM", "admin")])
def test_readonly_and_foreign_cannot_edit(
    store: Store,
    monkeypatch: pytest.MonkeyPatch,
    tenant: str,
    role: str,
) -> None:
    save(store)
    before = read_journal(store)
    подменить_двери(monkeypatch, tenant=tenant, role=role)
    with собрать(tenant="HQ").test_client() as client:
        войти(client)
        page = client.get("/admin?checklist=bizdev&item=CLN01")
        assert b"data-technical-form" not in page.data
        result = client.post(
            "/admin/items/CLN01/technical?checklist=bizdev",
            data=form_data(store),
            headers={"Origin": СВОЙ},
        )
        assert result.status_code == 403
    assert read_journal(store) == before
