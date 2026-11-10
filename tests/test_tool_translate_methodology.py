"""#1619: `tools/translate_methodology.py` — новое издание с турецкими колонками.

Модель подменена: здесь проверяется то, что делает инструмент вокруг неё. Что издание
принимает настоящий движок (`apply_edit` → `manage.py validate`, `init`, `score`), что коды и
числа не тронуты, что переведённое не затирается без `--force`, что класс в начале вопроса
не уходит модели и возвращается как был, и что упавшая модель не оставляет ни версии, ни записи.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path

import pytest
from mcp_checklist_harness import build_edition

from src.domain.models import REPORT_LANGS
from src.mcp.checklist import Store, read_items, read_journal, tip_version, versions
from tools import translate_methodology as tool

ДЕНЬ = date(2026, 9, 3)
ТЕНАНТ = "укашка"


class _Фальшивая:
    """Переводчик без модели: «[tr] оригинал», и список того, что ему показали."""

    def __init__(self) -> None:
        self.shown: list[tool.Item] = []

    def __call__(self, batch: Sequence[tool.Item], lang: str) -> Mapping[str, str]:
        self.shown.extend(batch)
        return {item.key: f"[{lang}] {item.ru}" for item in batch}


@pytest.fixture
def store(tmp_path: Path) -> Store:
    live = tmp_path / "live"
    build_edition(live, name="imf", day="2026-09-01")
    return Store(root=tmp_path / "store", live=live)


def _edit(store: Store, переводчик: tool.Translator, **kw: object) -> object:
    return tool.translate_edition(
        store,
        tenant=ТЕНАНТ,
        translate=переводчик,
        today=ДЕНЬ,
        **kw,  # type: ignore[arg-type]
    )


def test_турецкий_язык_заведён_в_продукте() -> None:
    assert "tr" in REPORT_LANGS


def test_издание_принимает_движок_и_колонки_заполнены(store: Store) -> None:
    результат = _edit(store, _Фальшивая())
    assert result_accepted(результат)
    пункты = read_items(store, version=tip_version(store))
    assert {p["id"]: p["question_tr"] for p in пункты} == {
        "CLN01": "[tr] Пол чистый",
        "CLN02": "[tr] Стены чистые",
    }
    assert all(p["process_tr"] == "[tr] Чистота" for p in пункты)
    зоны = read_items(store, version=tip_version(store), what="zones")
    assert {z["code"]: z["name_tr"] for z in зоны} == {
        "fridge": "[tr] Холодильник",
        "dough": "[tr] Тесто",
    }
    # Коды, классы, зоны, сроки и доли — как были.
    assert [p["levels"] for p in пункты] == ["D1;D2", "D1"]
    assert [z["share_pct"] for z in зоны] == ["50", "50"]
    cfg = json.loads(
        (store.home / tool.VERSIONS_DIR / tip_version(store) / "scoring.json").read_text("utf-8")
    )
    assert cfg["grades"]["rules"][0]["label_tr"] == "[tr] Критическое"
    assert cfg["grades"]["fallback"]["label_tr"] == "[tr] Ниже"
    assert cfg["deadlines"]["d3_note_tr"] == "[tr] немедленно"
    assert cfg["penalty"] == {"D1": 0.5, "D2": 2.0}


def result_accepted(результат: object) -> bool:
    return bool(getattr(результат, "accepted", False))


def test_процесс_уходит_модели_один_раз_а_не_на_каждую_строку(store: Store) -> None:
    фальшивая = _Фальшивая()
    _edit(store, фальшивая)
    assert [i.key for i in фальшивая.shown].count("process:Чистота") == 1


def test_переведённое_не_затирается_без_force(store: Store) -> None:
    _edit(store, _Фальшивая())
    второй = _Фальшивая()
    assert _edit(store, второй) is None, "переводить нечего — издания быть не должно"
    assert second_calls(второй) == 0
    assert len(versions(store)) == 2, "основа и одно переведённое издание"


def second_calls(переводчик: _Фальшивая) -> int:
    return len(переводчик.shown)


def test_force_переводит_заново(store: Store) -> None:
    _edit(store, _Фальшивая())

    def другой(batch: Sequence[tool.Item], lang: str) -> Mapping[str, str]:
        return {item.key: f"новое {item.ru}" for item in batch}

    результат = _edit(store, другой, force=True)
    assert result_accepted(результат)
    пункты = read_items(store, version=tip_version(store))
    assert {p["question_tr"] for p in пункты} == {"новое Пол чистый", "новое Стены чистые"}


def test_частично_переведённое_дополняется_и_существующее_остаётся(
    store: Store, tmp_path: Path
) -> None:
    _edit(store, _Фальшивая())
    версия = tip_version(store)
    файл = store.home / tool.VERSIONS_DIR / версия / "checklist.csv"
    # Пустая ячейка у одного пункта: именно её и переводит инструмент, соседа не трогает.
    строки = file_rows(файл)
    строки[1]["question_tr"] = ""
    plan = tool.make_plan(_copy_with(tmp_path, файл, строки, версия, store), "tr")
    assert [i.key for i in plan.todo] == ["question:CLN02"]


def file_rows(файл: Path) -> list[dict[str, str]]:
    return tool._read_csv(файл)[1]


def _copy_with(
    tmp_path: Path, файл: Path, строки: list[dict[str, str]], версия: str, store: Store
) -> Path:
    import shutil

    копия = tmp_path / "copy"
    shutil.copytree(store.home / tool.VERSIONS_DIR / версия, копия)
    поля = tool._read_csv(файл)[0]
    tool._write_csv(копия / "checklist.csv", поля, строки)
    return копия


def test_класс_в_начале_вопроса_не_уходит_модели_и_возвращается(tmp_path: Path) -> None:
    показано: list[str] = []

    class Ответ:
        def __init__(self, payload: dict[str, object]) -> None:
            self.payload = payload

    def фальшивая_модель(**kw: object) -> Ответ:
        вход = json.loads(str(kw["question"]))
        показано.extend(row["ru"] for row in вход)
        return Ответ({"items": [{"id": row["id"], "text": f"T:{row['ru']}"} for row in вход]})

    import src.recognize.client  # noqa: F401

    monkey = pytest.MonkeyPatch()
    monkey.setattr(tool, "ask_model", фальшивая_модель)
    try:
        run = tool.model_translator(settings=_Настройки())  # type: ignore[arg-type]
        ответ = run([tool.Item("question:A1", "(D1, D2) Пол чистый", "(D1, D2) Floor")], "tr")
    finally:
        monkey.undo()
    assert показано == ["Пол чистый"]
    assert ответ["question:A1"] == "(D1, D2) T:Пол чистый"


class _Настройки:
    merge_model = "fake"


def test_упавшая_модель_не_оставляет_ни_версии_ни_записи(store: Store) -> None:
    до = len(versions(store))

    def падает(batch: Sequence[tool.Item], lang: str) -> Mapping[str, str]:
        raise tool.TranslateError("нет связи")

    with pytest.raises(tool.TranslateError):
        _edit(store, падает)
    assert len(versions(store)) == до
    assert all(e.get("tool") != tool.TOOL_NAME for e in read_journal(store))


def test_пропущенный_моделью_перевод_это_отказ_а_не_дырка(store: Store) -> None:
    def неполная(batch: Sequence[tool.Item], lang: str) -> Mapping[str, str]:
        return {item.key: "x" for item in batch[:-1]}

    with pytest.raises(tool.TranslateError, match="не вернула перевод"):
        _edit(store, неполная)


def test_язык_оригинала_и_незнакомый_язык_отказ(store: Store) -> None:
    with pytest.raises(tool.TranslateError):
        _edit(store, _Фальшивая(), lang="ru")
    with pytest.raises(tool.TranslateError):
        _edit(store, _Фальшивая(), lang="xx")


def test_издание_которое_движок_отверг_не_появляется(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Порча зон (доли не сходятся) — движок отказывает, версии нет, журнал это помнит."""
    настоящая = tool._apply_texts

    def портит(candidate: Path, lang: str, texts: Mapping[str, str], *, force: bool) -> None:
        настоящая(candidate, lang, texts, force=force)
        поля, строки = tool._read_csv(candidate / "zones.csv")
        строки[0]["share_pct"] = "7"
        tool._write_csv(candidate / "zones.csv", поля, строки)

    monkeypatch.setattr(tool, "_apply_texts", портит)
    до = len(versions(store))
    результат = _edit(store, _Фальшивая())
    assert not result_accepted(результат)
    assert len(versions(store)) == до
    assert read_journal(store)[-1]["outcome"] == "refused"
