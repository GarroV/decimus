"""Волна 1 (#340): граница пространств в хранилище методики.

Ядро — тихий переход в чужое пространство. Код чек-листа приходит снаружи, а
единый указатель прода смотрит в `hq`: любая дорога «по умолчанию» уводит
партнёра в эталон. Сторожится, В КАКОЕ пространство наведено хранилище.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest
from mcp_checklist_harness import build_methodology

from src.domain.tenants import HQ_TENANT
from src.mcp.checklist import Store, current_version, read_journal
from src.mcp.checklist_layout import (
    DEFAULT_SPACE,
    META_FILE,
    applied,
    bot_spaces,
    for_code,
    locate,
    may_write,
    read_spaces,
    space_of,
)
from src.mcp.checklists import apply_to_production, create, overview, set_bot_access
from src.mcp.errors import ChecklistError

СЕГОДНЯ = date(2026, 9, 30)


@pytest.fixture
def склад(tmp_path: Path) -> Store:
    """Эталон `hq/bizdev`, у партнёра GE свой `own`, у партнёра AM свой `rnd`."""
    store = Store(root=tmp_path / "хранилище", live=build_methodology(tmp_path / "методика"))
    current_version(store)
    assert applied(store.root) == (DEFAULT_SPACE, "bizdev")
    create(
        replace(store, space="ge", code="own"),
        tenant="GE",
        name_ru="Свой",
        name_en="Own",
        today=СЕГОДНЯ,
    )
    create(
        replace(store, space="am", code="rnd"),
        tenant="AM",
        name_ru="РНД",
        name_en="RnD",
        today=СЕГОДНЯ,
    )
    return store


def test_каталог_пространства_это_код_тенанта_строчными() -> None:
    assert space_of(HQ_TENANT) == DEFAULT_SPACE
    assert space_of("GE") == "ge"
    with pytest.raises(ChecklistError):
        space_of("../hq")


def test_старый_код_тенанта_УК_приводится_к_hq() -> None:
    """Review Н16: `MCP_TOKENS` не приводит `default` через `canonical_tenant` — приводим здесь."""
    assert space_of("default") == DEFAULT_SPACE


def test_бот_партнёра_смотрит_своё_и_эталон_бот_уК_только_эталон() -> None:
    assert bot_spaces(HQ_TENANT) == ("hq",)
    assert bot_spaces("GE") == ("ge", "hq")


def test_уК_читает_все_пространства_партнёр_только_своё(склад: Store) -> None:
    assert set(read_spaces(HQ_TENANT, склад.root)) == {"hq", "ge", "am"}
    assert read_spaces("GE", склад.root) == ("ge", "hq")


def test_чужой_код_неотличим_от_несуществующего(склад: Store) -> None:
    assert locate(склад, tenant="GE", code="rnd") is None
    assert locate(склад, tenant="GE", code="nothing") is None
    assert locate(склад, tenant="GE", code="rnd", space="am") is None


def test_партнёр_находит_эталон_и_своё(склад: Store) -> None:
    эталон = locate(склад, tenant="GE", code="bizdev")
    своё = locate(склад, tenant="GE", code="own")
    assert эталон is not None and (эталон.space, эталон.code) == ("hq", "bizdev")
    assert своё is not None and (своё.space, своё.code) == ("ge", "own")


def test_уК_открывает_чек_лист_партнёра_только_на_чтение(склад: Store) -> None:
    assert locate(склад, tenant=HQ_TENANT, code="own") is None, "без пространства — только эталон"
    чужое = locate(склад, tenant=HQ_TENANT, code="own", space="ge")
    assert чужое is not None and чужое.space == "ge"
    assert may_write(чужое, tenant=HQ_TENANT) is False


def test_без_кода_партнёр_получает_эталон_на_чтение(склад: Store) -> None:
    найдено = locate(склад, tenant="GE", code=None)
    assert найдено is not None and (найдено.space, найдено.code) == ("hq", "bizdev")
    assert may_write(найдено, tenant="GE") is False


def test_без_кода_не_подхватывает_код_прежде_наведённого_хранилища(склад: Store) -> None:
    """Review Н17: код прежнего вызова (`own`) не подставляется вместо эталонного."""
    наведено = replace(склад, space="ge", code="own")
    найдено = locate(наведено, tenant="GE", code=None)
    assert найдено is not None and (найдено.space, найдено.code) == ("hq", "bizdev")


def test_указатель_прода_не_уводит_в_чужое_пространство(склад: Store) -> None:
    """Review Focus 4."""
    assert for_code(replace(склад, space="ge"), None).space == "ge"


def test_правка_только_в_своём_пространстве(склад: Store) -> None:
    assert may_write(replace(склад, space="hq"), tenant=HQ_TENANT) is True
    assert may_write(replace(склад, space="ge"), tenant="GE") is True
    assert may_write(replace(склад, space="hq"), tenant="GE") is False
    assert may_write(replace(склад, space="am"), tenant="GE") is False


def test_перечень_сужается_до_названных_пространств(склад: Store) -> None:
    видно = {(c.space, c.code) for c in overview(склад, spaces=bot_spaces("GE"))}
    assert видно == {("hq", "bizdev"), ("ge", "own")}


def test_партнёр_не_применяет_к_проду(склад: Store) -> None:
    журнал = len(read_journal(replace(склад, space="hq", code="bizdev")))
    with pytest.raises(ChecklistError, match="только УК"):
        apply_to_production(replace(склад, space="ge", code="own"), tenant="GE")
    assert applied(склад.root) == ("hq", "bizdev")
    assert len(read_journal(replace(склад, space="hq", code="bizdev"))) == журнал


def test_код_эталона_не_заводится_в_пространстве_партнёра(склад: Store) -> None:
    with pytest.raises(ChecklistError, match="эталон"):
        create(
            replace(склад, space="ge", code="bizdev"),
            tenant="GE",
            name_ru="К",
            name_en="C",
            today=СЕГОДНЯ,
        )


def test_уК_не_заводит_код_занятый_партнёром(склад: Store) -> None:
    with pytest.raises(ChecklistError, match="занят"):
        create(
            replace(склад, space="hq", code="own"),
            tenant=HQ_TENANT,
            name_ru="С",
            name_en="O",
            today=СЕГОДНЯ,
        )


def test_отметка_в_боте_у_партнёра_не_трогает_карточки_ук(склад: Store) -> None:
    """Review Н18: `_settle_inherited` пишет карточки только своего пространства."""
    эталон = replace(склад, space="hq", code="bizdev")
    до = (эталон.home / META_FILE).read_text(encoding="utf-8")
    set_bot_access(replace(склад, space="ge", code="own"), tenant="GE", on=False)
    после = (эталон.home / META_FILE).read_text(encoding="utf-8")
    assert после == до


def test_нетронутое_пространство_партнёра_не_заводится_копией_боевой_методики(
    tmp_path: Path,
) -> None:
    """Снимок боевой методики — только первый чек-лист УК (D226: копии без правки нет)."""
    пусто = Store(root=tmp_path / "пусто", live=build_methodology(tmp_path / "м"), space="ge")
    with pytest.raises(ChecklistError):
        current_version(пусто)
    assert not (tmp_path / "пусто" / "ge").exists()
