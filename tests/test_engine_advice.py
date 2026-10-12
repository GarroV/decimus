"""Рекомендация без нарушения (D201, #375) и общая заметка (D314) в движке.

Рекомендация — класс `R`: совет команде у пункта, без вычета и срока, пару
«пункт + зона» не занимает. Общая заметка — тот же класс у служебного кода
`NOTE`: совет не про пункт, уходит в конец отчёта, в «Заметки проверяющего».
Цена проверки от них не меняется ни на сотую — это ядро (оценка), поэтому
тесты здесь, а не прогоном экрана.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from conftest import Run


def state_of(workdir: Path) -> dict:
    return json.loads((workdir / "inspection.json").read_text(encoding="utf-8"))


def score(started: Callable[..., Run]) -> dict:
    r = started("score", "--json")
    assert r.code == 0, r.text
    return json.loads(r.out)


def add(started: Callable[..., Run], qid: str, level: str, zone: str, text: str = "") -> Run:
    args = ["add", "--qid", qid, "--level", level, "--zone", zone]
    if text:
        args += ["--evidence", text]
    return started(*args)


def test_рекомендация_у_пункта_нарушения_принимается_без_фото(
    started: Callable[..., Run], workdir: Path
) -> None:
    r = add(started, "CLN06", "R", "hot_kitchen", "Смазать петли крышки линии.")
    assert r.code == 0, r.text
    f = state_of(workdir)["findings"][0]
    assert (f["qid"], f["level"], f["photos"]) == ("CLN06", "R", [])


def test_рекомендация_без_текста_отклоняется(started: Callable[..., Run]) -> None:
    r = add(started, "CLN06", "R", "hot_kitchen")
    assert r.code != 0, "рекомендация без слов — пустая строка в отчёте партнёру"


def test_рекомендация_у_замера_отклоняется(started: Callable[..., Run]) -> None:
    r = add(started, "INF09", "R", "hot_kitchen", "что-то")
    assert r.code != 0, "у замера нечего рекомендовать: он не нарушение"


def test_рекомендация_не_меняет_оценку(started: Callable[..., Run]) -> None:
    add(started, "CLN06", "D1", "hot_kitchen", "нагар")
    до = score(started)
    add(started, "PRD06", "R", "cold_kitchen", "Крышки держать у линии.")
    add(started, "NOTE", "R", "dining", "Очередь у кассы из-за одного терминала.")
    после = score(started)
    assert после["pct"] == до["pct"] and после["grade"] == до["grade"]
    assert после["counts"] == до["counts"], "рекомендация попала в счётчики классов"


def test_рекомендация_не_занимает_пару_и_не_блокируется_ей(
    started: Callable[..., Run], workdir: Path
) -> None:
    assert add(started, "CLN06", "R", "hot_kitchen", "совет").code == 0
    r = add(started, "CLN06", "D1", "hot_kitchen", "нарушение")
    assert r.code == 0, f"рекомендация заняла пару у нарушения: {r.text}"
    assert add(started, "CLN06", "R", "hot_kitchen", "второй совет").code == 0
    assert len(state_of(workdir)["findings"]) == 3


def test_у_рекомендации_нет_срока_устранения(started: Callable[..., Run]) -> None:
    add(started, "CLN06", "R", "hot_kitchen", "совет")
    f = score(started)["findings"][0]
    assert f["days"] == 0 and not f["due"]


def test_общая_заметка_не_требует_пункта_методики(
    started: Callable[..., Run], workdir: Path
) -> None:
    r = add(started, "NOTE", "R", "dining", "Очередь у кассы.")
    assert r.code == 0, r.text
    assert state_of(workdir)["findings"][0]["qid"] == "NOTE"


def test_NOTE_только_рекомендацией(started: Callable[..., Run]) -> None:
    r = add(started, "NOTE", "D1", "dining", "x")
    assert r.code != 0, "служебный код NOTE не может стать нарушением с вычетом"


def test_рекомендацию_нельзя_превратить_в_нарушение_правкой(started: Callable[..., Run]) -> None:
    add(started, "CLN06", "R", "hot_kitchen", "совет")
    r = started("edit", "--n", "1", "--level", "D1")
    assert r.code != 0, "правка класса молча сделала совет вычетом"


def test_нарушение_нельзя_превратить_в_рекомендацию_правкой(started: Callable[..., Run]) -> None:
    add(started, "CLN06", "D1", "hot_kitchen", "нагар")
    r = started("edit", "--n", "1", "--level", "R")
    assert r.code != 0, "правка класса молча сняла вычет"


def test_правка_текста_рекомендации_проходит(started: Callable[..., Run], workdir: Path) -> None:
    add(started, "CLN06", "R", "hot_kitchen", "совет")
    r = started("edit", "--n", "1", "--evidence", "другой совет")
    assert r.code == 0, r.text
    assert state_of(workdir)["findings"][0]["evidence"] == "другой совет"


def test_отчёт_печатает_рекомендацию_в_зоне_а_заметку_в_конце(
    started: Callable[..., Run], report: Callable[..., Run]
) -> None:
    add(started, "CLN06", "R", "hot_kitchen", "Смазать петли крышки линии.")
    add(started, "NOTE", "R", "dining", "Очередь у кассы из-за одного терминала.")
    r = report("html")
    assert r.code == 0, r.text
    html = r.out
    совет = html.index("Смазать петли крышки линии.")
    заметка = html.index("Очередь у кассы из-за одного терминала.")
    assert "Заметки проверяющего" in html
    assert совет < html.index("Заметки проверяющего") < заметка
    assert "Приложение" not in html[:совет], "рекомендация уехала в приложение"
    assert "Устранить до" not in html[совет : совет + 400], "у рекомендации напечатан срок"
