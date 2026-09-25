"""T348: правка зон и их долей с экрана админки (`src/web/methodology.py`).

Набор намеренно короткий: здесь только острое — доля есть цена ответа, и
непонятный ввод не должен молча стать нулём, а правка долей не должна сама
становиться действующей. Всё остальное на этом экране видно открытием, и тест
о нём только повторял бы реализацию.

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

def test_ставка_не_число_это_отказ_а_не_тихий_ноль(хранилище: Store) -> None:
    """Ставка — цена нарушения: ноль вместо непонятного ввода обесценил бы класс."""
    with pytest.raises(MethodologyRefused) as отказ:
        method.set_scoring(хранилище, tenant=ТЕНАНТ, author=АВТОР, d1="подороже")

    assert "не число" in str(отказ.value)


def test_пустая_правка_ставок_не_заводит_версию(хранилище: Store) -> None:
    """Версия, ничем не отличающаяся от предыдущей, — мусор в истории методики."""
    было = method.latest_version(хранилище)

    with pytest.raises(MethodologyRefused):
        method.set_scoring(хранилище, tenant=ТЕНАНТ, author=АВТОР)

    assert method.latest_version(хранилище) == было
