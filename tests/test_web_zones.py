"""T348: правка зон и их долей с экрана админки (`src/web/methodology.py`).

Проверяется то, что принадлежит ДВЕРИ веба: разбор напечатанного человеком и
то, что правка остаётся правкой НОВОЙ версии. Сама арифметика долей и отказ на
несошедшейся сумме — свойство хранилища и движка, у них свои наборы; здесь
важно, что отказ доезжает до экрана отказом, а не тихим успехом.

Методика в этих тестах — уже изданная (`build_edition`): дверь `web` имени
набора не придумывает, на неизданной отказала бы оснастка, а не проверяемое
свойство (та же причина, что в `test_web_methodology.py`).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from mcp_checklist_harness import build_edition

from src.mcp.checklist import Store
from src.web import methodology as method
from src.web.errors import MethodologyRefused

ТЕНАНТ = "укашка"
АВТОР = "director"


@pytest.fixture
def методика(tmp_path: Path) -> Path:
    where = tmp_path / "живая-методика"
    build_edition(where, name="imf", day="2026-09-01")
    return where


@pytest.fixture
def хранилище(tmp_path: Path, методика: Path) -> Store:
    return Store(root=tmp_path / "хранилище", live=методика)


def _зоны(store: Store) -> list[str]:
    """Коды зон действующего состава — тест не завязывается на конкретную методику."""
    состав = method.load_composition(store, tenant=ТЕНАНТ)
    return [str(зона["code"]) for зона in состав.zones if зона.get("code")]


# --- разбор напечатанного: доля — цена ответа, а не оформление ----------------


def test_доля_не_число_это_отказ_а_не_тихий_ноль(хранилище: Store) -> None:
    """Ноль вместо непонятного ввода сделал бы зону бесплатной молча."""
    коды = _зоны(хранилище)

    with pytest.raises(MethodologyRefused) as отказ:
        method.set_zone_shares(
            хранилище, tenant=ТЕНАНТ, author=АВТОР, shares={коды[0]: "сколько-нибудь"}
        )

    assert "не число" in str(отказ.value)
    assert коды[0] in str(отказ.value), "отказ не называет зону, о которой речь"


def test_пустая_доля_это_отказ(хранилище: Store) -> None:
    коды = _зоны(хранилище)

    with pytest.raises(MethodologyRefused):
        method.set_zone_shares(хранилище, tenant=ТЕНАНТ, author=АВТОР, shares={коды[0]: ""})


def test_запятая_в_доле_принимается_наравне_с_точкой(хранилище: Store) -> None:
    """Человек печатает «33,3» — и это не повод отказать."""
    коды = _зоны(хранилище)
    поровну = 100 / len(коды)
    доли = {код: f"{поровну:.2f}".replace(".", ",") for код in коды}

    правка = method.set_zone_shares(хранилище, tenant=ТЕНАНТ, author=АВТОР, shares=доли)

    assert правка.version


# --- правка остаётся правкой новой версии ------------------------------------


def test_правка_долей_не_публикует(хранилище: Store) -> None:
    """Доли меняют цену ответа, поэтому действующей версия становится
    только публикацией — отдельным шагом (D049), как и всякая правка методики."""
    коды = _зоны(хранилище)
    действующая_до = method.published_version(хранилище)
    поровну = {код: f"{100 / len(коды):.4f}" for код in коды}

    правка = method.set_zone_shares(хранилище, tenant=ТЕНАНТ, author=АВТОР, shares=поровну)

    assert method.published_version(хранилище) == действующая_до
    assert method.latest_version(хранилище) == правка.version
    assert правка.version != действующая_до


def test_зона_заводится_новой_версией_и_попадает_в_состав(хранилище: Store) -> None:
    было = set(_зоны(хранилище))

    правка = method.add_zone(
        хранилище,
        tenant=ТЕНАНТ,
        author=АВТОР,
        code="terrace",
        name_ru="Терраса",
        name_en="Terrace",
        equal_shares=True,
    )

    стало = set(_зоны(хранилище))
    assert стало - было == {"terrace"}
    assert правка.version != method.published_version(хранилище)


def test_зона_переименовывается_а_код_остаётся(хранилище: Store) -> None:
    """Кодом зона связана с пунктами и с записанными проверками — он не меняется."""
    код = _зоны(хранилище)[0]

    method.rename_zone(хранилище, tenant=ТЕНАНТ, author=АВТОР, code=код, name_ru="Переназвана")

    состав = method.load_composition(хранилище, tenant=ТЕНАНТ)
    зона = next(з for з in состав.zones if з.get("code") == код)
    assert зона.get("name_ru") == "Переназвана"
    assert код in _зоны(хранилище)
