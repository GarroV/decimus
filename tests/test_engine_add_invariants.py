"""T013: уникальность пары «пункт + зона» и сквозные номера записей.

Оба инварианта из `docs/02-domain.md`: нарушение уникально по паре «пункт +
зона», а номера аудитор называет вслух — переиспользовать их нельзя.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from conftest import Run


def state_of(workdir: Path) -> dict:
    return json.loads((workdir / "inspection.json").read_text(encoding="utf-8"))


def numbers(workdir: Path) -> list[int]:
    return [f["n"] for f in state_of(workdir)["findings"]]


def старая_запись(n: int, qid: str, zone: str) -> dict:
    """Запись из боевого файла, собранного до появления счётчика."""
    return {
        "n": n,
        "qid": qid,
        "level": "D1",
        "zone": zone,
        "photos": [],
        "comment": "",
        "evidence": "старая запись",
    }


def положить_старое_состояние(workdir: Path, записи: list[dict]) -> None:
    """Состояние прошлого поколения: записи есть, ключа `seq` нет вовсе."""
    st = state_of(workdir)
    st["findings"] = записи
    st.pop("seq", None)
    (workdir / "inspection.json").write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")


def test_повторный_add_той_же_пары_отклоняется(started: Callable[..., Run], workdir: Path) -> None:
    started("add", "--qid", "CLN06", "--level", "D1", "--zone", "hot_kitchen")
    r = started("add", "--qid", "CLN06", "--level", "D1", "--zone", "hot_kitchen")
    assert r.code != 0, "второй такой же add обязан быть отклонён"
    assert numbers(workdir) == [1], "вторая запись всё-таки создана — оценка просядет дважды"


def test_отказ_называет_номер_существующей_записи(started: Callable[..., Run]) -> None:
    """Класс берём другой допустимый: отказ должен быть именно про дубль пары."""
    started("add", "--qid", "PRD09", "--level", "D1", "--zone", "fridge")
    r = started("add", "--qid", "PRD09", "--level", "D2", "--zone", "fridge")
    assert r.code != 0
    assert "#1" in r.text, f"аудитору не сказали, какая запись уже есть: {r.text!r}"


def test_тот_же_пункт_в_другой_зоне_это_отдельное_нарушение(
    started: Callable[..., Run], workdir: Path
) -> None:
    started("add", "--qid", "CLN06", "--level", "D1", "--zone", "hot_kitchen")
    r = started("add", "--qid", "CLN06", "--level", "D1", "--zone", "cold_kitchen")
    assert r.code == 0, r.text
    assert numbers(workdir) == [1, 2]


def test_номера_не_переиспользуются_после_удаления_последней(
    started: Callable[..., Run], workdir: Path
) -> None:
    started("add", "--qid", "CLN06", "--level", "D1", "--zone", "hot_kitchen")
    started("add", "--qid", "CLN06", "--level", "D1", "--zone", "dining")
    started("drop", "2")
    r = started("add", "--qid", "CLN06", "--level", "D1", "--zone", "dough")
    assert r.code == 0, r.text
    assert numbers(workdir) == [1, 3], "номер удалённой записи выдан повторно"


def test_номера_не_переиспользуются_после_удаления_всех(
    started: Callable[..., Run], workdir: Path
) -> None:
    started("add", "--qid", "CLN05", "--level", "D1", "--zone", "hot_kitchen")
    started("drop", "1")
    started("add", "--qid", "CLN05", "--level", "D1", "--zone", "hot_kitchen")
    assert numbers(workdir) == [2], "после опустошения счётчик начался заново"


def test_счётчик_поднимается_от_старого_состояния_без_него(
    started: Callable[..., Run], workdir: Path
) -> None:
    """Боевые `inspection.json` собраны до появления счётчика — они не должны ломаться."""
    положить_старое_состояние(
        workdir,
        [старая_запись(1, "CLN05", "hot_kitchen"), старая_запись(4, "CLN06", "dining")],
    )
    r = started("add", "--qid", "CLN06", "--level", "D1", "--zone", "dough")
    assert r.code == 0, r.text
    assert numbers(workdir) == [1, 4, 5], "счётчик не подхватил максимум из старого состояния"


def test_снятие_в_старом_состоянии_не_возвращает_номер_записи(
    started: Callable[..., Run], workdir: Path
) -> None:
    """T295: номер звучит вслух и уходит партнёру — после снятия он не выдаётся заново.

    Счётчик подхватывался максимумом ЖИВЫХ записей, а `drop` этот максимум
    уносит: в файле старого поколения (ключа `seq` нет) следующая запись
    получала номер только что снятой. Ссылка «нарушение #3» в письме партнёру
    после этого вела на другое нарушение.
    """
    положить_старое_состояние(
        workdir,
        [
            старая_запись(1, "CLN05", "hot_kitchen"),
            старая_запись(2, "CLN06", "dining"),
            старая_запись(3, "CLN06", "dough"),
        ],
    )
    assert started("drop", "3").code == 0

    r = started("add", "--qid", "CLN06", "--level", "D1", "--zone", "cold_kitchen")

    assert r.code == 0, r.text
    assert numbers(workdir) == [1, 2, 4], "номер снятой записи выдан повторно"
    assert "#4" in r.text, f"аудитору назван чужой номер: {r.text!r}"


def test_счётчик_старого_состояния_идёт_от_выданных_номеров_а_не_от_длины_списка(
    started: Callable[..., Run], workdir: Path
) -> None:
    """Снятых записей в списке нет, но их номера уже прозвучали.

    Старый файл, где живыми остались #1, #2 и #7: номера с третьего по шестой
    выданы и сняты раньше. После снятия всех трёх список пуст, и счёт от длины
    списка начал бы проверку заново — с номера, который партнёр уже видел.
    """
    положить_старое_состояние(
        workdir,
        [
            старая_запись(1, "CLN05", "hot_kitchen"),
            старая_запись(2, "CLN06", "dining"),
            старая_запись(7, "CLN06", "dough"),
        ],
    )
    for n in ("7", "2", "1"):
        assert started("drop", n).code == 0

    r = started("add", "--qid", "CLN05", "--level", "D1", "--zone", "hot_kitchen")

    assert r.code == 0, r.text
    assert numbers(workdir) == [8], "опустошённая проверка начала нумерацию заново"


def test_init_обнуляет_счётчик_новой_проверки(
    started: Callable[..., Run], audit: Callable[..., Run], workdir: Path
) -> None:
    started("add", "--qid", "CLN05", "--level", "D1", "--zone", "hot_kitchen")
    audit("init", "--unit", "Другая", "--date", "2026-08-22")
    audit("add", "--qid", "CLN05", "--level", "D1", "--zone", "hot_kitchen")
    assert numbers(workdir) == [1], "новая проверка началась не с первого номера"
