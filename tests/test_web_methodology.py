"""T320: дверь блока `web` к хранилищу версий методики (`src/web/methodology.py`).

Здесь проверяется ровно то, что принадлежит ДВЕРИ, а не хранилищу и не
движку — оба уже проверены своими наборами (`tests/test_mcp_checklist_store.py`,
`engine`). Главное утверждение задачи: правка с экрана — это новая версия,
а не правка действующей методики, и публикация — отдельный, осознанный шаг.

Боевая методика в этих тестах — уже ИЗДАННАЯ (`build_edition`, а не
`build_methodology`): `add_item`/`edit_item` у двери `web`, в отличие от двери
`mcp`, не принимают имя набора вовсе и полагаются на то, что оно унаследовано
от предыдущего издания (D050, `src/mcp/checklist._resolve_name`). На
неизданной методике первая же правка отказала бы с «нет имени набора» —
и это было бы отказом оснастки, а не тем свойством, которое проверяет тест.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from mcp_checklist_harness import build_edition

from src.mcp.checklist import Store, read_journal
from src.web import methodology as method
from src.web.errors import MethodologyRefused

ТЕНАНТ = "укашка"
АВТОР = "director"


def _слепок(каталог: Path) -> dict[str, str]:
    """Содержимое каталога по файлам — чтобы поймать правку боевой методики."""
    return {
        путь.name: hashlib.sha256(путь.read_bytes()).hexdigest()
        for путь in sorted(каталог.iterdir())
        if путь.is_file()
    }


@pytest.fixture
def методика(tmp_path: Path) -> Path:
    """Боевая методика — уже изданная (D050): дверь `web` имя набора не придумывает."""
    where = tmp_path / "живая-методика"
    build_edition(where, name="imf", day="2026-09-01")
    return where


@pytest.fixture
def хранилище(tmp_path: Path, методика: Path) -> Store:
    return Store(root=tmp_path / "хранилище", live=методика)


def _завести_пробу(store: Store, **переопределения: object) -> method.Edit:
    """Общий сценарий: завести пункт «Проба» — тем, чем сторожатся сразу
    несколько проверок, чтобы не гонять движок лишний раз одной и той же правкой."""
    поля: dict[str, object] = dict(
        process="Проба",
        question_ru="Проба пера",
        levels="D1",
        zones="fridge",
        days="5",
        criteria="D1: проба",
    )
    поля.update(переопределения)
    return method.add_item(store, tenant=ТЕНАНТ, author=АВТОР, **поля)  # type: ignore[arg-type]


# --- боевая методика не трогается, правка не публикует -----------------------


def test_правка_не_трогает_боевую_методику(хранилище: Store, методика: Path) -> None:
    было = _слепок(методика)
    исходная = method.latest_version(хранилище)

    правка = _завести_пробу(хранилище)

    assert _слепок(методика) == было, "правка изменила файлы боевой методики"
    assert правка.version != исходная


def test_правка_не_публикует(хранилище: Store) -> None:
    """Главное утверждение задачи: версия появляется на каждую правку, а
    действующей становится только публикацией — отдельным шагом (D049)."""
    действующая_до = method.published_version(хранилище)

    правка = _завести_пробу(хранилище)

    assert method.published_version(хранилище) == действующая_до
    assert method.latest_version(хранилище) == правка.version
    assert правка.version != действующая_до


# --- публикация — отдельный шаг -----------------------------------------------


def test_публикация_переставляет_действующую_версию(tmp_path: Path, методика: Path) -> None:
    """Публикация работает, когда `AUDIT_DATA_DIR` — сам указатель хранилища."""
    подготовка = Store(root=tmp_path / "хранилище", live=методика)
    правка = _завести_пробу(подготовка)
    рабочее = Store(root=подготовка.root, live=подготовка.root / "current")

    опубликована = method.publish_version(рабочее, tenant=ТЕНАНТ, version=правка.version)

    assert опубликована == правка.version
    assert method.published_version(рабочее) == правка.version


def test_публикация_на_обычный_каталог_отказывает(хранилище: Store) -> None:
    """Публикация, которой движок не увидит, — молчаливый сбой худшего вида:
    отказ обязан называть переменную, которую нужно поправить."""
    правка = _завести_пробу(хранилище)

    with pytest.raises(MethodologyRefused) as отказ:
        method.publish_version(хранилище, tenant=ТЕНАНТ, version=правка.version)

    assert method.DATA_VAR in str(отказ.value)


# --- отказ движка — это отказ, а не тихий успех -------------------------------


def test_отказ_движка_это_отказ_а_не_молчаливый_успех(хранилище: Store) -> None:
    """Класса «D9» не существует — движок обязан отказать на `validate`."""
    свежая_до = method.latest_version(хранилище)

    with pytest.raises(MethodologyRefused) as отказ:
        method.edit_item(хранилище, tenant=ТЕНАНТ, author=АВТОР, code="CLN01", levels="D9")

    assert str(отказ.value)
    assert method.latest_version(хранилище) == свежая_до, "версия записана, хотя движок отказал"


def test_непонятный_срок_это_отказ_а_не_тихий_ноль(хранилище: Store) -> None:
    """Нулевой срок печатается партнёру как «устранить немедленно» — подставить
    его вместо непонятного ввода значило бы решить за УК, каким будет предписание."""
    свежая_до = method.latest_version(хранилище)

    with pytest.raises(MethodologyRefused) as отказ:
        method.edit_item(хранилище, tenant=ТЕНАНТ, author=АВТОР, code="CLN01", days="скоро")

    assert "немедленно" in str(отказ.value)
    assert method.latest_version(хранилище) == свежая_до


# --- пустое поле формы значит «не трогать» ------------------------------------


def test_пустое_поле_формы_не_стирает_остальные(хранилище: Store) -> None:
    до = method.load_item(хранилище, tenant=ТЕНАНТ, code="CLN01")["item"]

    правка = method.edit_item(
        хранилище,
        tenant=ТЕНАНТ,
        author=АВТОР,
        code="CLN01",
        question_ru="новая формулировка",
        process=None,
        levels=None,
        zones=None,
    )
    после = method.load_item(хранилище, tenant=ТЕНАНТ, code="CLN01", version=правка.version)["item"]

    assert после["question_ru"] == "новая формулировка"
    assert после["levels"] == до["levels"], "пустое поле стёрло классы, хотя его не трогали"
    assert после["zones"] == до["zones"], "пустое поле стёрло зоны, хотя его не трогали"


# --- журнал помнит подпись -----------------------------------------------------


def test_подпись_правки_попадает_в_журнал(хранилище: Store) -> None:
    """Через год по журналу обязано быть видно: правка пришла с экрана и от кого."""
    _завести_пробу(хранилище, note="повод")

    принятые = [e for e in read_journal(хранилище) if e.get("outcome") == "accepted"]
    последняя = принятые[-1]
    assert str(последняя["note"]).startswith("web:director")


# --- выключение и возврат своими именами --------------------------------------


def test_выключение_и_возврат_дают_новые_версии(хранилище: Store) -> None:
    свежая_0 = method.latest_version(хранилище)

    выключено = method.disable_item(хранилище, tenant=ТЕНАНТ, author=АВТОР, code="CLN01")
    пункт_off = method.load_item(хранилище, tenant=ТЕНАНТ, code="CLN01", version=выключено.version)[
        "item"
    ]
    assert пункт_off["kind"] == "off"
    assert выключено.version != свежая_0

    восстановлено = method.restore_item(хранилище, tenant=ТЕНАНТ, author=АВТОР, code="CLN01")
    пункт_on = method.load_item(
        хранилище, tenant=ТЕНАНТ, code="CLN01", version=восстановлено.version
    )["item"]
    assert пункт_on["kind"] == "violation"
    assert восстановлено.version != выключено.version


# --- ненастроенное хранилище называет незаданные переменные -------------------


def test_ненастроенное_хранилище_называет_переменные() -> None:
    ничего_нет = method.load_store({})
    assert ничего_нет.ready is False
    assert set(ничего_нет.missing) == {method.STORE_VAR, method.DATA_VAR}

    только_хранилище = method.load_store({method.STORE_VAR: "/x"})
    assert только_хранилище.missing == (method.DATA_VAR,)


# --- состав по умолчанию — свежая записанная версия ---------------------------


def test_состав_по_умолчанию_свежая_версия_а_не_действующая(хранилище: Store) -> None:
    правка = _завести_пробу(хранилище)

    состав = method.load_composition(хранилище, tenant=ТЕНАНТ)

    assert состав.version == правка.version
    assert состав.unpublished is True
