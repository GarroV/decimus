"""T342, T343: чек-лист заводится с нуля, и пустой к проду не применяется.

Ядро здесь — заслоны. Пустая методика проходит `validate`, `init` и `score` и
даёт партнёру 100% и высшую оценку, не задав ни одного вопроса (проверено
запуском 22.09.2026, #339): сбой выходит наружу не ошибкой, а хорошей новостью.
Поэтому проверяется не «функция отказала», а что именно она отказалась сделать
и какими словами объяснила.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pytest
from mcp_checklist_harness import build_methodology

from src.mcp.checklist import Store, apply_change, current_version, publish, read_journal
from src.mcp.checklist_layout import ACTIVE, CURRENT_LINK, DRAFT, RETIRED, applied, read_meta
from src.mcp.checklists import apply_to_production, create, overview, rename, set_state
from src.mcp.errors import ChecklistError

АРЕНДАТОР = "укашка"
СЕГОДНЯ = date(2026, 9, 22)


@pytest.fixture
def методика(tmp_path: Path) -> Path:
    return build_methodology(tmp_path / "живая-методика")


@pytest.fixture
def хранилище(tmp_path: Path, методика: Path) -> Store:
    """Хранилище с заведённым чек-листом по умолчанию — как на площадке."""
    store = Store(root=tmp_path / "хранилище", live=методика)
    current_version(store)
    return store


def _новый(хранилище: Store, *, code: str = "rnd") -> Store:
    from dataclasses import replace

    return replace(хранилище, code=code)


def test_чеклист_заводится_с_нуля_из_бланка(хранилище: Store) -> None:
    """Критерий приёмки владельца (D180): новый чек-лист заводится руками с
    нуля, а не копией существующего."""
    свой = _новый(хранилище)

    заведён = create(
        свой, tenant=АРЕНДАТОР, name_ru="Аудит РНД", name_en="RnD audit", today=СЕГОДНЯ
    )

    assert (заведён.code, заведён.state, заведён.in_production) == ("rnd", DRAFT, False)
    assert заведён.version is not None and заведён.version.startswith("rnd-2026-09-22-")
    assert (свой.home / "versions" / заведён.version / "checklist.csv").is_file()
    карточка = read_meta(свой)
    assert карточка is not None and карточка.name_ru == "Аудит РНД"


def test_заведение_не_трогает_соседний_чеклист(хранилище: Store, методика: Path) -> None:
    """Бланк — данные, и рождение нового чек-листа не касается ни изданий
    соседа, ни того, по чему считает движок."""
    было = current_version(хранилище)
    прод_было = applied(хранилище.root)

    create(_новый(хранилище), tenant=АРЕНДАТОР, name_ru="Аудит РНД", name_en="RnD", today=СЕГОДНЯ)

    assert current_version(хранилище) == было
    assert applied(хранилище.root) == прод_было


def test_пустой_чеклист_к_проду_не_применяется(хранилище: Store) -> None:
    """#339: методика без единого пункта считается без вопросов и даёт 100% и
    высшую оценку. Заслон стоит на применении, а не в `validate`: «вопросов 0»
    для черновика законно."""
    свой = _новый(хранилище)
    create(свой, tenant=АРЕНДАТОР, name_ru="Аудит РНД", name_en="RnD", today=СЕГОДНЯ)

    with pytest.raises(ChecklistError) as отказ:
        apply_to_production(свой, tenant=АРЕНДАТОР)

    сказано = str(отказ.value)
    assert "нет ни одного пункта" in сказано and "100%" in сказано
    assert applied(хранилище.root) == ("hq", "bizdev")


def test_чеклист_с_пунктом_применяется_и_меняет_то_что_читает_движок(хранилище: Store) -> None:
    """Сквозная проверка множественности: завели с нуля, дали пункт,
    опубликовали издание, применили — и `AUDIT_DATA_DIR` читает уже его."""
    свой = _новый(хранилище)
    create(свой, tenant=АРЕНДАТОР, name_ru="Аудит РНД", name_en="RnD", today=СЕГОДНЯ)
    правка = apply_change(
        свой,
        tenant=АРЕНДАТОР,
        tool="add_checklist_item",
        command="add",
        options={
            "id": "RND01",
            "process": "Проба",
            "question-ru": "Проба пера",
            "levels": "D1",
            "zones": "all",
            "days": 5,
            "criteria": "D1: проба",
        },
        today=СЕГОДНЯ,
    )
    assert правка.accepted and правка.version is not None
    publish(свой, tenant=АРЕНДАТОР, version=правка.version)

    итог = apply_to_production(свой, tenant=АРЕНДАТОР)

    assert (итог["applied"], итог["previous"], итог["items"]) == ("rnd", "bizdev", 1)
    assert applied(хранилище.root) == ("hq", "rnd")
    читает = хранилище.root / CURRENT_LINK
    assert "RND01" in (читает / "checklist.csv").read_text(encoding="utf-8")
    # Применение переводит черновик в работу: по нему уже считают проверки.
    карточка = read_meta(свой)
    assert карточка is not None and карточка.state == ACTIVE


def test_снятый_чеклист_к_проду_не_применяется(хранилище: Store) -> None:
    """Сняли потому, что считать по нему больше не следует."""
    set_state(хранилище, tenant=АРЕНДАТОР, state=DRAFT)
    свой = _новый(хранилище, code="rnd2")
    create(свой, tenant=АРЕНДАТОР, name_ru="Второй", name_en="Second", today=СЕГОДНЯ)
    set_state(свой, tenant=АРЕНДАТОР, state=RETIRED)

    with pytest.raises(ChecklistError) as отказ:
        apply_to_production(свой, tenant=АРЕНДАТОР)

    assert "снят" in str(отказ.value)


def test_применённый_к_проду_не_снимается(хранилище: Store) -> None:
    """Иначе продукт считал бы по снятой методике. Сначала применяется другой."""
    with pytest.raises(ChecklistError) as отказ:
        set_state(хранилище, tenant=АРЕНДАТОР, state=RETIRED)

    assert "применён к проду" in str(отказ.value)


def test_код_чеклиста_не_меняется_переименованием(хранилище: Store) -> None:
    """Названия — формулировка, код — связь с проверками в базе и со снимками
    изданий. Правится первое, второе не правится ничем."""
    свой = _новый(хранилище)
    create(свой, tenant=АРЕНДАТОР, name_ru="Было", name_en="Was", today=СЕГОДНЯ)

    стало = rename(свой, tenant=АРЕНДАТОР, name_ru="Стало", name_en="Now")

    assert (стало.code, стало.name_ru, стало.name_en) == ("rnd", "Стало", "Now")
    карточка = read_meta(свой)
    assert карточка is not None and карточка.code == "rnd"


def test_повторное_заведение_того_же_кода_это_отказ(хранилище: Store) -> None:
    """Молча лечь поверх существующего чек-листа значило бы потерять его
    издания и журнал."""
    свой = _новый(хранилище)
    create(свой, tenant=АРЕНДАТОР, name_ru="Аудит РНД", name_en="RnD", today=СЕГОДНЯ)

    with pytest.raises(ChecklistError) as отказ:
        create(свой, tenant=АРЕНДАТОР, name_ru="Другой", name_en="Other", today=СЕГОДНЯ)

    assert "уже есть" in str(отказ.value)


def test_заведение_без_одного_из_названий_это_отказ(хранилище: Store) -> None:
    """Язык продукта — параметр, а не константа: чек-лист без английского
    названия показать англоязычному человеку нечем."""
    with pytest.raises(ChecklistError) as отказ:
        create(_новый(хранилище), tenant=АРЕНДАТОР, name_ru="Только по-русски", name_en=" ")

    assert "оба названия" in str(отказ.value)


def test_негодный_код_чеклиста_это_отказ(хранилище: Store) -> None:
    """Код становится куском пути внутри хранилища."""
    with pytest.raises(ChecklistError):
        create(_новый(хранилище, code="../побег"), tenant=АРЕНДАТОР, name_ru="Х", name_en="X")


def test_перечень_показывает_кто_применён_к_проду(хранилище: Store) -> None:
    create(_новый(хранилище), tenant=АРЕНДАТОР, name_ru="Аудит РНД", name_en="RnD", today=СЕГОДНЯ)

    видно = {c.code: c for c in overview(хранилище)}

    assert set(видно) == {"bizdev", "rnd"}
    assert видно["bizdev"].in_production is True
    assert видно["rnd"].in_production is False
    assert видно["rnd"].state == DRAFT


def test_заведение_и_применение_видны_в_журнале_своего_чеклиста(хранилище: Store) -> None:
    """Журнал на чек-лист: «кто и что правил» читается по тому, который
    смотрят, и не тонет в соседних."""
    свой = _новый(хранилище)
    create(свой, tenant=АРЕНДАТОР, name_ru="Аудит РНД", name_en="RnD", today=СЕГОДНЯ)

    события = read_journal(свой)

    assert [с["tool"] for с in события] == ["create_checklist"]
    assert все_чужое_мимо(read_journal(хранилище))


def все_чужое_мимо(события: list[dict[str, object]]) -> bool:
    """В журнале соседа заведения нового чек-листа нет вовсе."""
    return all(с.get("tool") != "create_checklist" for с in события)


def test_применение_записано_журналом_и_переставило_указатель(хранилище: Store) -> None:
    """След применения обязан остаться: ролей нет (D182), и разбор «кто это
    сделал» держится на журнале."""
    свой = _новый(хранилище)
    create(свой, tenant=АРЕНДАТОР, name_ru="Аудит РНД", name_en="RnD", today=СЕГОДНЯ)
    правка = apply_change(
        свой,
        tenant=АРЕНДАТОР,
        tool="add_checklist_item",
        command="add",
        options={
            "id": "RND01",
            "process": "Проба",
            "question-ru": "Проба пера",
            "levels": "D1",
            "zones": "all",
            "days": 5,
            "criteria": "D1: проба",
        },
        today=СЕГОДНЯ,
    )
    assert правка.version is not None
    publish(свой, tenant=АРЕНДАТОР, version=правка.version)

    apply_to_production(свой, tenant=АРЕНДАТОР)

    последнее = read_journal(свой)[-1]
    assert последнее["tool"] == "apply_checklist"
    assert последнее["tenant"] == АРЕНДАТОР
    assert Path(os.readlink(хранилище.root / CURRENT_LINK)).parts[:2] == ("hq", "rnd")
