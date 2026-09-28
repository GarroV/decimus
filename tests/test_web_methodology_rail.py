"""D221: колонка чек-листов — порядок, число пунктов, метка «бот».

Хранилище настоящее (файлы на `tmp_path`), как в соседнем наборе экранов
чек-листов: порядок и число пунктов приходят из двери перечня, а не выдумываются.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from mcp_checklist_harness import build_edition

from src.web import methodology as method


@pytest.fixture
def хранилище(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> method.Store:
    методика = tmp_path / "живая-методика"
    build_edition(методика, name="imf", day="2026-09-01")
    monkeypatch.setenv(method.STORE_VAR, str(tmp_path / "хранилище"))
    monkeypatch.setenv(method.DATA_VAR, str(методика))
    store = method.load_store().store
    assert store is not None
    return store


def test_колонка_в_работе_раньше_черновиков_снятые_в_конце(хранилище: method.Store) -> None:
    # Arrange — в проде bizdev; черновик «rnd» и снятый «old».
    method.checklists_overview(хранилище)
    for код, имя in (("rnd", "Аудит РНД"), ("old", "Старый")):
        method.create_checklist(
            хранилище, tenant="default", author="t", code=код, name_ru=имя, name_en=имя
        )
    method.set_checklist_state(
        хранилище, tenant="default", author="t", code="old", state=method.RETIRED
    )

    # Act
    строки = method.checklist_rail(хранилище)

    # Assert
    assert [r.code for r in строки] == ["bizdev", "rnd", "old"]
    assert [r.in_bot for r in строки] == [True, False, False]
    assert строки[0].items and строки[0].items > 0
    # Черновик рождается изданием из бланка: пунктов с нарушением у него ноль.
    assert строки[1].items == 0


def test_битый_чек_лист_не_роняет_колонку(хранилище: method.Store) -> None:
    """Испорченные ставки одного чек-листа — «—» в его строке, а не 500 всего экрана."""
    method.checklists_overview(хранилище)
    method.create_checklist(
        хранилище, tenant="default", author="t", code="rnd", name_ru="РНД", name_en="RnD"
    )
    for ставки in (хранилище.root / "hq" / "rnd").rglob("scoring.json"):
        ставки.write_text("{ не json", encoding="utf-8")

    строки = {r.code: r for r in method.checklist_rail(хранилище)}

    assert строки["rnd"].items is None
    assert строки["bizdev"].items and строки["bizdev"].items > 0
