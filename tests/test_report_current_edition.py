"""#1619: где искать перевод методики, которого нет в издании самой проверки.

`current_edition_dir` отвечает «какое издание чек-листа сейчас действует». Движок берёт
оттуда недостающие слова на языке печати (`tests/test_engine_text_fallback.py`).
"""

from __future__ import annotations

from pathlib import Path

from src.report.engine_call import current_edition_dir


def _published(root: Path, space: str, code: str, edition: str) -> Path:
    versions = root / space / code / "versions" / edition
    versions.mkdir(parents=True)
    (root / space / code / "current").symlink_to(Path("versions") / edition)
    return versions


def test_свой_чек_лист_тенанта_берётся_раньше_эталона(tmp_path: Path) -> None:
    своё = _published(tmp_path, "ge", "own", "e2")
    _published(tmp_path, "hq", "own", "e9")
    assert current_edition_dir(tmp_path, None, tenant="GE", code="own") == своё.resolve()


def test_у_партнёра_нет_своей_копии_берётся_эталон_ук(tmp_path: Path) -> None:
    эталон = _published(tmp_path, "hq", "bizdev", "e5")
    assert current_edition_dir(tmp_path, None, tenant="GE", code="bizdev") == эталон.resolve()


def test_хранилища_нет_для_основного_чек_листа_это_боевая_методика(tmp_path: Path) -> None:
    live = tmp_path / "data"
    live.mkdir()
    assert current_edition_dir(None, live, tenant="HQ", code="bizdev") == live


def test_чужой_чек_лист_без_хранилища_ничего_не_находит(tmp_path: Path) -> None:
    live = tmp_path / "data"
    live.mkdir()
    assert current_edition_dir(None, live, tenant="HQ", code="rnd") is None


def test_негодный_код_тенанта_не_ломает_отчёт(tmp_path: Path) -> None:
    assert current_edition_dir(tmp_path, None, tenant="../x", code="bizdev") is None
