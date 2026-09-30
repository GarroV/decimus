"""Волна 1 (#340): бот предлагает чек-листы пространства аудитора и эталон УК (D285)."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from src.domain import get_state, list_items, start_inspection, sync_checklist_version
from src.domain.bot_checklists import available
from src.domain.config import check_environment
from src.domain.errors import DomainError
from src.domain.tenants import HQ_TENANT
from src.mcp.checklist import Store, apply_change, current_version, publish
from src.mcp.checklists import create, set_bot_access, set_state

CHAT = 7401
СЕГОДНЯ = date(2026, 9, 30)


def _открыть(store: Store, *, tenant: str, в_бот: bool = True) -> None:
    create(store, tenant=tenant, name_ru=store.code, name_en=store.code, today=СЕГОДНЯ)
    правка = apply_change(
        store,
        tenant=tenant,
        tool="add_checklist_item",
        command="add",
        options={
            "id": "X01",
            "process": "Проба",
            "question-ru": "Проба",
            "levels": "D1",
            "zones": "all",
            "days": 5,
            "criteria": "D1: проба",
        },
        today=СЕГОДНЯ,
    )
    assert правка.accepted and правка.version is not None, правка
    publish(store, tenant=tenant, version=правка.version)
    set_state(store, tenant=tenant, state="active")
    set_bot_access(store, tenant=tenant, on=в_бот)


@pytest.fixture
def хранилище(data_copy: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Store:
    monkeypatch.setenv("AUDIT_DATA_DIR", str(data_copy))
    monkeypatch.setenv("STATE_DIR", str(tmp_path / "state"))
    monkeypatch.chdir(tmp_path)
    store = Store(root=tmp_path / "хранилище", live=data_copy)
    current_version(store)
    # Второй эталон, который УК своему боту НЕ открыла: партнёру он виден (D285).
    _открыть(replace(store, code="hq2"), tenant=HQ_TENANT, в_бот=False)
    _открыть(replace(store, space="ge", code="own"), tenant="GE")
    _открыть(replace(store, space="am", code="rnd"), tenant="AM")
    monkeypatch.setenv("MCP_CHECKLIST_STORE", str(store.root))
    return store


def test_партнёр_видит_все_годные_эталоны_и_свои(хранилище: Store) -> None:
    видно = {(c.space, c.code) for c in available(check_environment(), tenant="GE")}
    assert видно == {("hq", "bizdev"), ("hq", "hq2"), ("ge", "own")}


def test_уК_видит_свои_открытые_и_не_видит_партнёров(хранилище: Store) -> None:
    видно = {(c.space, c.code) for c in available(check_environment(), tenant=HQ_TENANT)}
    assert видно == {("hq", "bizdev")}


def test_чужой_код_не_стартует_проверку(хранилище: Store) -> None:
    with pytest.raises(DomainError, match="больше не открыт"):
        start_inspection(
            CHAT,
            unit="Тестовая",
            kind="planned",
            report_lang="ru",
            tenant="GE",
            checklist_code="rnd",
        )
    assert get_state(CHAT) is None


def test_проверка_партнёра_пишется_в_его_тенант(хранилище: Store) -> None:
    start_inspection(
        CHAT, unit="Тестовая", kind="planned", report_lang="ru", tenant="GE", checklist_code="own"
    )
    состояние = get_state(CHAT)
    assert состояние is not None
    assert (состояние.tenant, состояние.checklist_code) == ("GE", "own")


def test_перевод_проверки_партнёра_ищет_в_его_пространстве(хранилище: Store) -> None:
    """`sync_checklist_version` партнёра ищет действующее издание в ЕГО
    пространстве, не в `hq` (D285, Review Н4): код партнёра там не лежит, и
    отказ на пустом месте останавливал бы перевод проверки, которую партнёр
    ведёт совершенно законно.
    """
    start_inspection(
        CHAT, unit="Тестовая", kind="planned", report_lang="ru", tenant="GE", checklist_code="own"
    )
    own = replace(хранилище, space="ge", code="own")
    правка = apply_change(
        own,
        tenant="GE",
        tool="add_checklist_item",
        command="add",
        options={
            "id": "X02",
            "process": "Проба 2",
            "question-ru": "Проба 2",
            "levels": "D1",
            "zones": "all",
            "days": 5,
            "criteria": "D1: проба",
        },
        today=СЕГОДНЯ,
    )
    assert правка.accepted and правка.version is not None, правка
    publish(own, tenant="GE", version=правка.version)

    состояние = sync_checklist_version(CHAT)

    assert состояние.checklist_code == "own"
    assert {i.code for i in list_items(chat_id=CHAT)} == {"X01", "X02"}, (
        "перевод не подхватил новое издание пространства партнёра — source_for искал в hq вместо ge"
    )
