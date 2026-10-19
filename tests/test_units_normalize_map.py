"""D538: снятие дублей и ручная карта имён `make units-normalize` — по выгрузке CSV, без базы.

Запись в базу — `test_db_units_normalize.py`; здесь, что инструмент решает и от чего отказывается.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from src.domain.unit_match import plan
from tools.units_normalize import load_dir, main, plan_map, read_map, retire_blocked

КОД_Т1 = "aa" * 16
КОД_Б1 = "bb" * 16
ЧУЖОЙ = "cc" * 16


def _csv(путь: Path, колонки: list[str], строки: list[list[object]]) -> None:
    with путь.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(колонки)
        w.writerows(строки)


def _папка(tmp_path: Path, units: list[list[object]], usage: list[list[object]]) -> Path:
    _csv(tmp_path / "units.csv", ["id", "name", "code", "country", "city"], units)
    _csv(tmp_path / "aliases.csv", ["unit_id", "alias"], [])
    _csv(
        tmp_path / "profiles.csv",
        ["country_code", "name", "dodo_id", "city", "address"],
        [["GE", "Tbilisi-1", КОД_Т1, "Tbilisi", ""], ["RS", "Belgrade-1", КОД_Б1, "Belgrade", ""]],
    )
    _csv(tmp_path / "usage.csv", ["unit_id", "inspections", "moves", "other"], usage)
    return tmp_path


def _карта(путь: Path, строки: list[list[str]]) -> Path:
    _csv(путь, ["country", "old_name", "target_name", "dodo_id", "basis"], строки)
    return путь


def test_дубль_с_одной_историей_переносов_снимается_а_с_проверками_нет(tmp_path: Path) -> None:
    # Arrange — «Тбилиси-1» держит только история переносов, «Тбилиси-2» — ещё и проверка.
    папка = _папка(
        tmp_path,
        [["t1", "Tbilisi-1", КОД_Т1, "GE", "tbilisi"], ["c1", "Тбилиси-1", "", "", ""],
         ["t2", "Tbilisi-2", "", "GE", "tbilisi"], ["c2", "Тбилиси-2", "", "", ""]],
        [["c1", 0, 3, 0], ["c2", 1, 3, 0], ["t1", 5, 3, 0]],
    )  # fmt: skip
    units, index = load_dir(папка)

    # Act
    действия = {a.unit.id: a.kind for a in retire_blocked(plan(units, index))}

    # Assert
    assert действия["c1"] == "retire"
    assert действия["c2"] != "retire"


def test_без_флага_retire_дубль_остаётся_заблокированным(tmp_path: Path) -> None:
    папка = _папка(
        tmp_path,
        [["t1", "Tbilisi-1", КОД_Т1, "GE", "tbilisi"], ["c1", "Тбилиси-1", "", "", ""]],
        [["c1", 0, 3, 0], ["t1", 5, 3, 0]],
    )
    units, index = load_dir(папка)

    assert {a.unit.id: a.kind for a in plan(units, index)}["c1"] == "blocked"


def test_карта_переименовывает_и_вливает_и_отказывает(tmp_path: Path) -> None:
    # Arrange
    папка = _папка(
        tmp_path,
        [
            ["u1", "Тбилиси-1 сайт", "", "GE", ""],
            ["u2", "Dubravka", "", "RS", ""],
            ["t1", "Belgrade-1", КОД_Б1, "RS", ""],
            ["u3", "Центр", "", "RS", ""],
            ["u4", "Старая", ЧУЖОЙ, "RS", ""],
            ["u5", "Проверенная", "", "RS", ""],
        ],
        [["u5", 2, 0, 0]],
    )
    карта = _карта(
        tmp_path / "карта.csv",
        [
            ["GE", "Тбилиси-1 сайт", "Tbilisi-1", КОД_Т1, "id на сайте"],  # переименовать
            ["RS", "Dubravka", "Belgrade-1", КОД_Б1, "id на сайте"],  # влить в существующую
            ["RS", "Центр", "Belgrade-1", ЧУЖОЙ, "id на сайте"],  # код другой, чем у эталона
            ["RS", "Старая", "Belgrade-7", КОД_Б1, "id на сайте"],  # у точки другой код
            ["RS", "Проверенная", "Belgrade-8", "dd" * 16, "id на сайте"],  # есть проверки
        ],
    )
    units, index = load_dir(папка)

    # Act
    действия = plan_map(read_map(карта), units, index)

    # Assert
    итог = {a.unit.name: (a.kind, a.new_name, a.new_code) for a in действия}
    assert итог["Тбилиси-1 сайт"] == ("rename", "Tbilisi-1", КОД_Т1)
    assert итог["Dubravka"][0] == "merge"
    assert итог["Центр"][0] == "refused"
    assert итог["Старая"][0] == "refused"
    assert итог["Проверенная"][0] == "refused"


def test_вливание_в_цель_с_историей_переносов_снимает_а_не_удаляет(tmp_path: Path) -> None:
    папка = _папка(
        tmp_path,
        [["u2", "Dubravka", "", "RS", ""], ["t1", "Belgrade-1", КОД_Б1, "RS", ""]],
        [["u2", 0, 2, 0]],
    )
    карта = _карта(tmp_path / "к.csv", [["RS", "Dubravka", "Belgrade-1", КОД_Б1, "сайт"]])
    units, index = load_dir(папка)

    действия = plan_map(read_map(карта), units, index)

    assert [a.kind for a in действия] == ["retire"]


def test_выполненная_строка_карты_молча_пропускается(tmp_path: Path) -> None:
    # Идемпотентность: старого имени уже нет, точка с целевым именем и тем же кодом есть.
    папка = _папка(tmp_path, [["t1", "Tbilisi-1", КОД_Т1, "GE", ""]], [])
    карта = _карта(tmp_path / "к.csv", [["GE", "Тбилиси-1 сайт", "Tbilisi-1", КОД_Т1, "сайт"]])
    units, index = load_dir(папка)

    assert plan_map(read_map(карта), units, index) == []


def test_строка_без_старой_и_без_целевой_точки_отказ(tmp_path: Path) -> None:
    папка = _папка(tmp_path, [["t1", "Tbilisi-1", КОД_Т1, "GE", ""]], [])
    карта = _карта(tmp_path / "к.csv", [["GE", "Нет такой", "Tbilisi-5", "ee" * 16, "сайт"]])
    units, index = load_dir(папка)

    действия = plan_map(read_map(карта), units, index)

    assert [a.kind for a in действия] == ["refused"]


def test_сухой_прогон_по_выгрузке_ничего_не_пишет_и_печатает_план(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    папка = _папка(tmp_path, [["u1", "Тбилиси-1 сайт", "", "GE", ""]], [])
    карта = _карта(tmp_path / "к.csv", [["GE", "Тбилиси-1 сайт", "Tbilisi-1", КОД_Т1, "сайт"]])

    код = main(["--from-dir", str(папка), "--map", str(карта)])

    вывод = capsys.readouterr().out
    assert код == 0 and "Tbilisi-1" in вывод and "Сухой прогон" in вывод


def test_apply_без_копии_отказывает(tmp_path: Path) -> None:
    карта = _карта(tmp_path / "к.csv", [["GE", "Старая", "Tbilisi-1", КОД_Т1, "сайт"]])

    with pytest.raises(SystemExit):
        main(["--apply", "--map", str(карта)])
