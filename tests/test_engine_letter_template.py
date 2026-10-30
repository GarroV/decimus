"""Шаблон письма из админки (#977, #1130, этап 1б): движок собирает письмо по сохранённому тексту.

Ядро здесь — две границы. Первая: письмо по сохранённому тексту, равному встроенному, не
отличается от письма без шаблона, на всех трёх видах письма, обоих языках и обоих шаблонах
выбора (D664), — иначе включение шаблона молча поменяло бы письма партнёрам. Вторая: перечень
подстановок домена (`domain.letter_template.FIELDS`) совпадает с тем, что умеет движок, а
неизвестная подстановка отклоняется, а не уходит в письмо пустым местом.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import AUDIT, REPORT, Run, run_engine

from src.domain import letter_template as lt


@pytest.fixture
def прогон(workdir: Path, data_copy: Path) -> Callable[..., Run]:
    def call(script: Path, *args: str) -> Run:
        return run_engine(
            script, *args, cwd=workdir, state=workdir / "inspection.json", data_dir=data_copy
        )

    return call


def _начать(прогон: Callable[..., Run], вид: str) -> None:
    r = прогон(AUDIT, "init", "--unit", "Тестовая", "--auditor", "Тест", "--date", "2026-08-21")
    assert r.code == 0, r.text
    if вид == "empty":
        return
    уровень = "D2" if вид == "plan" else "D0"
    r = прогон(
        AUDIT,
        "add",
        "--qid",
        "PRD01" if вид == "plan" else "INF10",
        "--level",
        уровень,
        "--zone",
        "fridge",
        "--evidence",
        "Нет ярлыка",
    )
    assert r.code == 0, r.text


def _встроенное(прогон: Callable[..., Run]) -> dict[str, object]:
    r = прогон(REPORT, "letter-builtin")
    assert r.code == 0, r.text
    return json.loads(r.out)  # type: ignore[no-any-return]


def _письмо(прогон: Callable[..., Run], язык: str, шаблон: str, *extra: str) -> Run:
    return прогон(REPORT, "letter", "--lang", язык, "--template", шаблон, *extra)


def test_перечень_подстановок_домена_равен_движку(прогон: Callable[..., Run]) -> None:
    встроенное = _встроенное(прогон)
    assert tuple(встроенное["fields"]) == lt.FIELDS  # type: ignore[arg-type]
    тексты = встроенное["bodies"]
    assert set(тексты) == set(lt.SLOTS)  # type: ignore[arg-type]
    for слот in lt.SLOTS:
        assert set(тексты[слот]) == set(lt.LANGS)  # type: ignore[index]
        # Встроенный текст сам проходит ту проверку, которой домен встречает правки.
        for язык in lt.LANGS:
            assert lt.problem_of(тексты[слот][язык]) is None, (слот, язык)  # type: ignore[index]


@pytest.mark.parametrize("шаблон", ["1", "2"])
@pytest.mark.parametrize("язык", ["ru", "en"])
@pytest.mark.parametrize("вид", ["plan", "clean", "empty"])
def test_сохранённый_текст_равный_встроенному_даёт_то_же_письмо(
    прогон: Callable[..., Run], tmp_path: Path, вид: str, язык: str, шаблон: str
) -> None:
    _начать(прогон, вид)
    встроенное = _встроенное(прогон)["bodies"][вид][язык]  # type: ignore[index]
    файл = tmp_path / "bodies.json"
    файл.write_text(json.dumps({вид: встроенное}), encoding="utf-8")

    без = _письмо(прогон, язык, шаблон)
    с = _письмо(прогон, язык, шаблон, "--bodies-file", str(файл))

    assert без.code == 0 and с.code == 0, (без.text, с.text)
    assert с.out == без.out


def test_свой_текст_заменяет_встроенный_и_берёт_подстановки(
    прогон: Callable[..., Run], tmp_path: Path
) -> None:
    _начать(прогон, "plan")
    файл = tmp_path / "bodies.json"
    файл.write_text(json.dumps({"plan": "Привет, {unit}! Оценка {grade}, {pct}%."}), "utf-8")
    r = _письмо(прогон, "ru", "1", "--bodies-file", str(файл))
    assert r.code == 0, r.text
    assert r.out.startswith("Привет, Тестовая! Оценка "), r.out
    assert "Что зафиксировали" not in r.out, "встроенный текст слота не должен просочиться"


def test_слот_без_своего_текста_идёт_по_встроенному(
    прогон: Callable[..., Run], tmp_path: Path
) -> None:
    """Сохранён текст другого слота: письмо этого вида остаётся прежним."""
    _начать(прогон, "plan")
    файл = tmp_path / "bodies.json"
    файл.write_text(json.dumps({"empty": "Только для пустой проверки {unit}"}), "utf-8")
    без = _письмо(прогон, "ru", "1")
    с = _письмо(прогон, "ru", "1", "--bodies-file", str(файл))
    assert без.code == 0 and с.out == без.out


def test_все_подстановки_принимаются(прогон: Callable[..., Run], tmp_path: Path) -> None:
    _начать(прогон, "plan")
    файл = tmp_path / "bodies.json"
    тело = " ".join("{" + имя + "}" for имя in lt.FIELDS)
    файл.write_text(json.dumps({"plan": тело}), "utf-8")
    r = _письмо(прогон, "ru", "1", "--bodies-file", str(файл))
    assert r.code == 0, r.text
    assert "{" not in r.out


@pytest.mark.parametrize("тело", ["Привет {bogus}", "Оценка {grade:>10}", "Скобка { одна"])
def test_неизвестная_подстановка_отклоняется_а_не_уходит_пустой(
    прогон: Callable[..., Run], tmp_path: Path, тело: str
) -> None:
    _начать(прогон, "plan")
    файл = tmp_path / "bodies.json"
    файл.write_text(json.dumps({"plan": тело}), "utf-8")
    r = _письмо(прогон, "ru", "1", "--bodies-file", str(файл))
    assert r.code != 0
    assert "Шаблон письма" in r.text, r.text
    assert r.out == ""
