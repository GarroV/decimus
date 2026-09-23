"""T349: ряд оценок говорит, где он разорван (#337).

Сводка по сети и история точки — это РЯДЫ: распределение букв, лучшая и худшая
проверка, оценки одной точки одна под другой. Пока признака нет, такой ряд
молча смешивает проверки, посчитанные по разным ценам, и выглядит совершенно
правдоподобно. Это худший вид ошибки: не падение, а цифра, которой верят.

Что здесь стережётся:

* правка формулировки ряд НЕ рвёт — иначе признак сработает на каждом издании
  и его перестанут читать;
* правка ставки или порога буквы рвёт — до и после неё оценки несравнимы;
* разные чек-листы несравнимы ВСЕГДА, даже если цены совпали: это разные
  наборы пунктов, и общая средняя по ним бессмысленна;
* издание, методики которого на машине нет, не выдаётся за сравнимое.

Оценка не пересчитывается нигде: признак строится по тому, что записано у
проверки (код чек-листа и издание), и по файлам методики этого издания.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from datetime import date
from pathlib import Path

from mcp_checklist_harness import build_edition

from src.db.models import InspectionRow
from src.domain.config import DATA_FILES
from src.domain.version import edition_of
from src.mcp import comparability, letters

СЕГОДНЯ = date(2026, 9, 23)


def _издание(каталог: Path, *, day: str, правка: Callable[[Path], None] | None = None) -> str:
    """Издание оснастки, при необходимости правленное.

    Правка идёт ПОСЛЕ раскладки: `build_edition` собирает методику заново и
    затёрла бы её. Имя издания считается по содержимому уже правленого
    каталога — той же формулой, которой оно штампуется в проверку.
    """
    build_edition(каталог, day=day)
    if правка is not None:
        правка(каталог)
    издание = edition_of(каталог, DATA_FILES)
    assert издание is not None
    return издание


def _правка_формулировки(каталог: Path) -> None:
    """Переиздание, меняющее только текст: цену оно не двигает."""
    путь = каталог / "criteria.md"
    путь.write_text(
        путь.read_text(encoding="utf-8") + "\nуточнение формулировки\n", encoding="utf-8"
    )


def _правка_ставки(каталог: Path) -> None:
    путь = каталог / "scoring.json"
    тело = json.loads(путь.read_text(encoding="utf-8"))
    тело["penalty"]["D1"] = float(тело["penalty"]["D1"]) * 3
    путь.write_text(json.dumps(тело, ensure_ascii=False), encoding="utf-8")


def _проверка(*, version: str, code: str = "bizdev", pct: float = 97.0) -> InspectionRow:
    return InspectionRow(
        id=f"{abs(hash((version, code, pct))):032x}"[:32],
        tenant_code="укашка",
        unit_name="Белград-1",
        chat_id=100500,
        kind="planned",
        inspection_date=СЕГОДНЯ,
        report_lang="ru",
        checklist_version=version,
        pct=pct,
        grade="A",
        findings_count=1,
        pushed_at="2026-09-23T18:00:00+02:00",
        checklist_code=code,
    )


def _полка(tmp_path: Path) -> letters.Papers:
    """Бумаги, у которых есть только полка снимков: так их видит сводка."""
    return letters.Papers(live=None, store=None, shelf=tmp_path / "state" / "methodology")


def _положить(tmp_path: Path, каталог: Path, издание: str, *, code: str = "bizdev") -> None:
    shutil.copytree(каталог, tmp_path / "state" / "methodology" / code / издание)


# --- ряд не рвётся там, где цена не менялась ----------------------------------


def test_одно_издание_ряд_целый(tmp_path: Path) -> None:
    первое = _издание(tmp_path / "изд1", day="2026-09-01")
    _положить(tmp_path, tmp_path / "изд1", первое)

    итог = comparability.of(
        [_проверка(version=первое), _проверка(version=первое, pct=91.0)], papers=_полка(tmp_path)
    )

    assert итог["comparable"] is True
    assert итог["unknown"] is False
    assert len(итог["groups"]) == 1


def test_правка_формулировки_ряд_не_рвёт(tmp_path: Path) -> None:
    """Издание сменилось, цена — нет. Ряд обязан остаться целым.

    Иначе признак срабатывает на опечатке в тексте пункта, и читатель сводки
    привыкает к предупреждению, которое ничего не значит.
    """
    первое = _издание(tmp_path / "изд1", day="2026-09-01")
    _положить(tmp_path, tmp_path / "изд1", первое)

    второе = _издание(tmp_path / "изд2", day="2026-09-10", правка=_правка_формулировки)
    _положить(tmp_path, tmp_path / "изд2", второе)

    assert первое != второе, "издание обязано было смениться — иначе тест ничего не стережёт"

    итог = comparability.of(
        [_проверка(version=первое), _проверка(version=второе)], papers=_полка(tmp_path)
    )

    assert итог["comparable"] is True
    assert len(итог["groups"]) == 1
    assert sorted(итог["groups"][0]["editions"]) == sorted([первое, второе])


# --- ряд рвётся там, где менялась цена ----------------------------------------


def test_правка_ставки_рвёт_ряд_и_это_сказано_словами(tmp_path: Path) -> None:
    """Главный случай задачи: проценты до и после правки несравнимы.

    Разрыв обязан быть виден читателю, а не выясняться расспросами, — поэтому
    проверяется и признак, и фраза, которую сводка о нём говорит.
    """
    первое = _издание(tmp_path / "изд1", day="2026-09-01")
    _положить(tmp_path, tmp_path / "изд1", первое)

    второе = _издание(tmp_path / "изд2", day="2026-09-10", правка=_правка_ставки)
    _положить(tmp_path, tmp_path / "изд2", второе)

    итог = comparability.of(
        [_проверка(version=первое), _проверка(version=второе)], papers=_полка(tmp_path)
    )

    assert итог["comparable"] is False
    assert len(итог["groups"]) == 2
    assert итог["note"], "разрыв ряда обязан быть назван словами, а не только флагом"


def test_разные_чек_листы_несравнимы_даже_при_одинаковой_цене(tmp_path: Path) -> None:
    """Два чек-листа могут случайно совпасть ценой — общей средней по ним всё равно нет.

    Это разные наборы пунктов и разные проверки по сути: девелоперский аудит и
    аудит РНД не складываются в один ряд оттого, что ставка вычета у них
    одинаковая.
    """
    издание = _издание(tmp_path / "изд1", day="2026-09-01")
    _положить(tmp_path, tmp_path / "изд1", издание)
    _положить(tmp_path, tmp_path / "изд1", издание, code="rnd")

    итог = comparability.of(
        [_проверка(version=издание), _проверка(version=издание, code="rnd")],
        papers=_полка(tmp_path),
    )

    assert итог["comparable"] is False
    assert len(итог["groups"]) == 2
    assert {г["checklist_code"] for г in итог["groups"]} == {"bizdev", "rnd"}


# --- чего не знаем, за сравнимое не выдаём ------------------------------------


def test_издание_без_методики_не_выдаётся_за_сравнимое(tmp_path: Path) -> None:
    """Снимка нет — цену не установить. Молчать об этом нельзя.

    Выдать незнание за сравнимость значило бы соврать ровно в ту сторону, ради
    которой задача и заведена: читатель увидел бы целый ряд там, где ряд может
    быть разорван.
    """
    первое = _издание(tmp_path / "изд1", day="2026-09-01")
    _положить(tmp_path, tmp_path / "изд1", первое)

    итог = comparability.of(
        [_проверка(version=первое), _проверка(version="ушедшее-2026-01-01-ffffffffffff")],
        papers=_полка(tmp_path),
    )

    assert итог["unknown"] is True
    assert итог["comparable"] is False
    assert итог["note"]


def test_ряд_целиком_без_методик_сравнимым_не_объявляется(tmp_path: Path) -> None:
    """Все издания ряда неизвестны — значит неизвестно и то, один ли он.

    Отрезок при этом один, и признак «групп больше одной» здесь не сработает.
    Молчаливое «сравнимо» в таком ряду — это ровно тот молчаливый сбой, ради
    которого задача заведена: читатель увидел бы целый ряд, про который никто
    ничего не проверял.
    """
    итог = comparability.of(
        [
            _проверка(version="ушедшее-2026-01-01-ffffffffffff"),
            _проверка(version="ушедшее-2026-02-01-eeeeeeeeeeee"),
        ],
        papers=_полка(tmp_path),
    )

    assert len(итог["groups"]) == 1, "отрезок обязан быть один — иначе тест стережёт не то"
    assert итог["unknown"] is True
    assert итог["comparable"] is False
    assert итог["note"]


def test_пустой_ряд_не_повод_для_тревоги(tmp_path: Path) -> None:
    """Сравнивать нечего — значит и разрыва нет; лишнее предупреждение обесценивает нужное."""
    итог = comparability.of([], papers=_полка(tmp_path))

    assert итог["comparable"] is True
    assert итог["unknown"] is False
    assert итог["groups"] == []
    assert итог["note"] == ""


def test_цена_издания_читается_один_раз_на_ряд(tmp_path: Path) -> None:
    """Сводка по сети читает сотни строк, изданий в них единицы.

    Считать форму на каждую строку значило бы перечитывать всю методику столько
    раз, сколько в периоде проверок, — и сводка упёрлась бы в диск на ровном
    месте.
    """
    издание = _издание(tmp_path / "изд1", day="2026-09-01")
    _положить(tmp_path, tmp_path / "изд1", издание)
    считано: list[str] = []

    настоящая = comparability.shape_of

    def счётчик(version: str, code: str, papers: letters.Papers) -> str | None:
        считано.append(version)
        return настоящая(version, code, papers)

    comparability.of(
        [_проверка(version=издание, pct=float(i)) for i in range(20)],
        papers=_полка(tmp_path),
        shape=счётчик,
    )

    assert считано == [издание], "форма издания пересчитывалась на каждой строке ряда"
