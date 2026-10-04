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


def _завести(store: Store, *, tenant: str) -> None:
    """Только `create`: карточка рождается черновиком, с пустым бланком-изданием."""
    create(store, tenant=tenant, name_ru=store.code, name_en=store.code, today=СЕГОДНЯ)


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
    # Три негодных эталона (Review Important №1): у эталона флаг «в боте» не
    # проверяется вовсе (D285), и годность держится РОВНО на `bot_block`.
    # Регресс там (bot_block ушёл из ветки эталона или её переписали на ранний
    # `append`) не должен пройти партнёру пустой, черновой или снятый чек-лист
    # — движок посчитал бы по нему 100% без единого вопроса.
    пустой = replace(store, code="empty")
    _завести(пустой, tenant=HQ_TENANT)
    set_state(пустой, tenant=HQ_TENANT, state="active")
    set_bot_access(пустой, tenant=HQ_TENANT, on=False)
    _завести(replace(store, code="draft"), tenant=HQ_TENANT)
    снятый = replace(store, code="retired")
    _завести(снятый, tenant=HQ_TENANT)
    set_state(снятый, tenant=HQ_TENANT, state="retired")
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


def test_негодный_эталон_партнёру_не_виден(хранилище: Store) -> None:
    """Пустое издание, черновик и снятый эталон партнёру не показываются.

    Флаг «в боте» для эталона не проверяется вовсе (D285) — видимость держится
    ровно на `bot_block`. Если его уберут из ветки эталона (или перепишут её
    на ранний `append`, минуя заслон), это не заметит ни один из старых
    тестов: `hq2` и `bizdev` пункты имеют. Негативный прогон описан в отчёте.
    """
    видно = {(c.space, c.code) for c in available(check_environment(), tenant="GE")}
    assert ("hq", "empty") not in видно, "пустое издание эталона ушло партнёру"
    assert ("hq", "draft") not in видно, "черновик эталона ушёл партнёру"
    assert ("hq", "retired") not in видно, "снятый эталон ушёл партнёру"
    assert ("hq", "bizdev") in видно, "годный эталон не должен был пострадать от соседних"


def test_эталон_негодный_партнёру_не_стартует_проверку(хранилище: Store) -> None:
    """То же самое, но с другой стороны: `pick` не даёт начать по невидимому коду."""
    with pytest.raises(DomainError, match="не открыт"):
        start_inspection(
            CHAT,
            unit="Тестовая",
            kind="planned",
            report_lang="ru",
            tenant="GE",
            checklist_code="empty",
        )
    assert get_state(CHAT) is None


def test_перевод_проверки_по_эталону_ищет_в_hq(хранилище: Store) -> None:
    """Проверка партнёра, начатая ПО ЭТАЛОНУ, переводится через `hq`, не через своё.

    Зеркало к `test_перевод_проверки_партнёра_ищет_в_его_пространстве`: там код
    лежит у партнёра и не лежит в `hq`, здесь наоборот — код `hq2` есть только
    в `hq`, и `ge/hq2` не существует вовсе.
    """
    start_inspection(
        CHAT, unit="Тестовая", kind="planned", report_lang="ru", tenant="GE", checklist_code="hq2"
    )
    hq2 = replace(хранилище, code="hq2")
    правка = apply_change(
        hq2,
        tenant=HQ_TENANT,
        tool="add_checklist_item",
        command="add",
        options={
            "id": "X03",
            "process": "Проба 3",
            "question-ru": "Проба 3",
            "levels": "D1",
            "zones": "all",
            "days": 5,
            "criteria": "D1: проба",
        },
        today=СЕГОДНЯ,
    )
    assert правка.accepted and правка.version is not None, правка
    publish(hq2, tenant=HQ_TENANT, version=правка.version)

    состояние = sync_checklist_version(CHAT)

    assert состояние.checklist_code == "hq2"
    assert {i.code for i in list_items(chat_id=CHAT)} == {"X01", "X03"}, (
        "перевод не подхватил новое издание эталона — space_for искал в ge вместо hq"
    )


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
