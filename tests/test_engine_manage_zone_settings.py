"""T313: долю существующей зоны и её название правит команда, а не текстовый редактор.

Завести зону движок умел с самого начала, настроить — нет: доля менялась только
оптом (`--equal-shares`), а название не менялось вовсе. То есть «гибкая
настройка чек-листа» кончалась ровно там, где начинается вес зоны в оценке —
«где нам важнее» (разбор T302, дыра 3).

Две вещи, которые здесь закреплены и важнее удобства.

**Доля — цена ответа.** Доли входят в расчёт оценки и складываются в 100 %.
Поэтому команда правит ТОЛЬКО названные зоны и не раздаёт освободившееся за
управляющую компанию (то же правило, что у T112), а после правки говорит, сошлась
сумма или нет. Отсюда и форма: доли задаются набором сразу, потому что одна
доля в отрыве от остальных сумму разваливает, а методику с несошедшейся суммой
движок считать откажется.

**Переименование меняет имя, но не код.** Сущности связаны кодами; код зоны
стоит в колонке `zones` у пунктов чек-листа, в записанных проверках и в картах.
Переименование, тронувшее код, рассыпало бы эти ссылки молча.
"""

from __future__ import annotations

import csv
import hashlib
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import ROOT, Run, run_engine

MANAGE = ROOT / "engine" / "manage.py"


def читать_зоны(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def доли(path: Path) -> dict[str, str]:
    return {r["code"]: r["share_pct"] for r in читать_зоны(path)}


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()  # noqa: S324 — сверка файла, не защита


@pytest.fixture
def manage(data_copy: Path, workdir: Path) -> Callable[..., Run]:
    def call(*args: str) -> Run:
        return run_engine(MANAGE, *args, cwd=workdir, env_extra={"CHECKLIST_DIR": str(data_copy)})

    return call


@pytest.fixture
def зоны(data_copy: Path) -> Path:
    return data_copy / "zones.csv"


# --- доля существующей зоны ---------------------------------------------------


def test_названные_доли_меняются_а_остальные_не_трогаются(
    manage: Callable[..., Run], зоны: Path
) -> None:
    """Ровно то, ради чего просят настройку: кухня тяжелее фасада."""
    было = доли(зоны)

    r = manage("zone-share", "--shares=hot_kitchen=20,facade=5,dining=5")
    assert r.code == 0, r.text

    стало = доли(зоны)
    assert float(стало["hot_kitchen"]) == 20.0
    assert float(стало["facade"]) == 5.0
    assert float(стало["dining"]) == 5.0
    нетронутые = {k: v for k, v in стало.items() if k not in ("hot_kitchen", "facade", "dining")}
    assert нетронутые == {
        k: v for k, v in было.items() if k not in ("hot_kitchen", "facade", "dining")
    }, "доли зон, которых правка не называла, переписаны"


def test_сошедшаяся_сумма_названа_словами(manage: Callable[..., Run]) -> None:
    """Сумма 10+10+... = 100 сохранена: сказать об этом обязаны, иначе человек
    узнает о состоянии долей только на расчёте."""
    r = manage("zone-share", "--shares=hot_kitchen=20,facade=5,dining=5")

    assert "100" in r.text, f"итог по долям не назван: {r.text!r}"


def test_несошедшаяся_сумма_названа_и_движок_такую_методику_не_считает(
    manage: Callable[..., Run], data_copy: Path, workdir: Path
) -> None:
    """Правка одной доли в отрыве от остальных ломает сумму — и это видно сразу."""
    r = manage("zone-share", "--shares=hot_kitchen=25")
    assert r.code == 0, r.text
    assert "115" in r.text, f"несошедшаяся сумма не названа: {r.text!r}"

    отказ = run_engine(
        ROOT / "engine" / "audit.py",
        "zones",
        cwd=workdir,
        env_extra={"CHECKLIST_DIR": str(data_copy)},
    )
    assert отказ.code != 0, "движок посчитал методику с суммой долей 115%"


def test_неизвестная_зона_это_отказ_и_файл_не_тронут(
    manage: Callable[..., Run], зоны: Path
) -> None:
    было = md5(зоны)

    r = manage("zone-share", "--shares=terrace=5")

    assert r.code != 0, "доля записана зоне, которой нет"
    assert "terrace" in r.text
    assert md5(зоны) == было, "файл зон тронут при отказе"


@pytest.mark.parametrize("набор", ["hot_kitchen=много", "hot_kitchen=-5", "hot_kitchen", ""])
def test_негодная_доля_это_отказ_и_файл_не_тронут(
    manage: Callable[..., Run], зоны: Path, набор: str
) -> None:
    было = md5(зоны)

    r = manage("zone-share", f"--shares={набор}")

    assert r.code != 0, f"набор «{набор}» принят"
    assert md5(зоны) == было, "файл зон тронут при отказе"


def test_одна_зона_названа_дважды_это_отказ(manage: Callable[..., Run], зоны: Path) -> None:
    """Две доли одной зоне — это не правка, а вопрос «какая из них», и отвечать
    на него за управляющую компанию нельзя."""
    было = md5(зоны)

    r = manage("zone-share", "--shares=hot_kitchen=20,hot_kitchen=15")

    assert r.code != 0
    assert md5(зоны) == было


def test_чужие_колонки_переживают_правку_доли(
    manage: Callable[..., Run], зоны: Path, data_copy: Path
) -> None:
    """Колонки управляющей компании сверх известных движку не теряются (T109)."""
    строки = читать_зоны(зоны)
    поля = [*строки[0].keys(), "владелец_зоны"]
    for i, r in enumerate(строки):
        r["владелец_зоны"] = f"смена-{i}"
    with зоны.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=поля)
        w.writeheader()
        w.writerows(строки)

    assert manage("zone-share", "--shares=hot_kitchen=20,facade=5,dining=5").code == 0

    стало = читать_зоны(зоны)
    assert [r.get("владелец_зоны") for r in стало] == [f"смена-{i}" for i in range(len(строки))]


# --- переименование зоны ------------------------------------------------------


def test_переименование_меняет_имена_и_не_трогает_код_и_долю(
    manage: Callable[..., Run], зоны: Path
) -> None:
    было = доли(зоны)

    r = manage("zone-rename", "hot_kitchen", "--name-ru=Пекарский участок", "--name-en=Bake line")
    assert r.code == 0, r.text

    строки = {r["code"]: r for r in читать_зоны(зоны)}
    assert "hot_kitchen" in строки, "код зоны изменён переименованием"
    assert строки["hot_kitchen"]["name_ru"] == "Пекарский участок"
    assert строки["hot_kitchen"]["name_en"] == "Bake line"
    assert доли(зоны) == было, "переименование тронуло доли"


def test_переименование_на_одном_языке_не_стирает_второй(
    manage: Callable[..., Run], зоны: Path
) -> None:
    было = {r["code"]: r["name_en"] for r in читать_зоны(зоны)}

    assert manage("zone-rename", "hot_kitchen", "--name-ru=Пекарский участок").code == 0

    assert {r["code"]: r["name_en"] for r in читать_зоны(зоны)} == было


def test_переименование_не_трогает_ссылки_на_зону_в_чек_листе(
    manage: Callable[..., Run], data_copy: Path
) -> None:
    """Пункты связаны с зоной кодом; переименование обязано оставить их целыми."""
    чек_лист = data_copy / "checklist.csv"
    было = чек_лист.read_bytes()

    assert manage("zone-rename", "hot_kitchen", "--name-ru=Пекарский участок").code == 0

    assert чек_лист.read_bytes() == было


def test_переименование_неизвестной_зоны_это_отказ(manage: Callable[..., Run], зоны: Path) -> None:
    было = md5(зоны)

    r = manage("zone-rename", "terrace", "--name-ru=Терраса")

    assert r.code != 0
    assert "terrace" in r.text
    assert md5(зоны) == было


def test_переименование_без_единого_имени_это_отказ(manage: Callable[..., Run], зоны: Path) -> None:
    """Вызов без имён — не «оставить как есть», а потерянная правка: сказать об
    этом обязаны, а не молча ответить «готово»."""
    было = md5(зоны)

    r = manage("zone-rename", "hot_kitchen")

    assert r.code != 0
    assert md5(зоны) == было


def test_пустое_имя_это_отказ(manage: Callable[..., Run], зоны: Path) -> None:
    было = md5(зоны)

    r = manage("zone-rename", "hot_kitchen", "--name-ru=   ")

    assert r.code != 0
    assert md5(зоны) == было
