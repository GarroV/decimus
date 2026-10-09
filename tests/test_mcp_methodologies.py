"""Справка о методиках ряда (D352, прежде T349/#337).

Сводка по сети и история точки — РЯДЫ, и проверки в них могут быть оценены
разными методиками. Оценка каждой верна по своей методике, усреднять и
ранжировать ряд законно; поле `methodologies` только говорит, на какие
методики ряд раскладывается.

Что здесь стережётся:

* правка формулировки новой группы не даёт — иначе справка дробилась бы на
  каждом издании;
* правка ставки даёт новую группу, а фраза при этом не запрещает усреднять;
* разные чек-листы — разные группы;
* издание без методики на машине остаётся в ряду своей группой.

Оценка не пересчитывается нигде: справка строится по тому, что записано у
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
from src.mcp import letters, methodologies

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

    итог = methodologies.of(
        [_проверка(version=первое), _проверка(version=первое, pct=91.0)], papers=_полка(tmp_path)
    )

    assert len(итог["groups"]) == 1
    assert итог["note"] == ""


def test_правка_формулировки_новой_группы_не_даёт(tmp_path: Path) -> None:
    """Издание сменилось, пункты и веса — нет: группа одна."""
    первое = _издание(tmp_path / "изд1", day="2026-09-01")
    _положить(tmp_path, tmp_path / "изд1", первое)

    второе = _издание(tmp_path / "изд2", day="2026-09-10", правка=_правка_формулировки)
    _положить(tmp_path, tmp_path / "изд2", второе)

    assert первое != второе, "издание обязано было смениться — иначе тест ничего не стережёт"

    итог = methodologies.of(
        [_проверка(version=первое), _проверка(version=второе)], papers=_полка(tmp_path)
    )

    assert len(итог["groups"]) == 1
    assert sorted(итог["groups"][0]["editions"]) == sorted([первое, второе])


# --- смена ставки — новая группа, но не запрет -------------------------------


def test_правка_ставки_даёт_группу_и_не_запрещает_усреднять(tmp_path: Path) -> None:
    """D352: оценки до и после правки ставки — каждая верна по своей методике.

    Справка называет две методики, но говорит, что усреднять и ранжировать
    по ним можно: агент не должен отказываться считать среднюю.
    """
    первое = _издание(tmp_path / "изд1", day="2026-09-01")
    _положить(tmp_path, tmp_path / "изд1", первое)

    второе = _издание(tmp_path / "изд2", day="2026-09-10", правка=_правка_ставки)
    _положить(tmp_path, tmp_path / "изд2", второе)

    итог = methodologies.of(
        [_проверка(version=первое), _проверка(version=второе)], papers=_полка(tmp_path)
    )

    assert len(итог["groups"]) == 2
    assert "comparable" not in итог, "признака сравнимости больше нет (D352)"
    assert "valid" in str(итог["note"])
    assert "meaningless" not in str(итог["note"])


def test_разные_чек_листы_разные_группы_даже_при_одинаковой_цене(tmp_path: Path) -> None:
    """Два чек-листа — разные наборы пунктов, и справка называет их порознь."""
    издание = _издание(tmp_path / "изд1", day="2026-09-01")
    _положить(tmp_path, tmp_path / "изд1", издание)
    _положить(tmp_path, tmp_path / "изд1", издание, code="rnd")

    итог = methodologies.of(
        [_проверка(version=издание), _проверка(version=издание, code="rnd")],
        papers=_полка(tmp_path),
    )

    assert len(итог["groups"]) == 2
    assert {г["checklist_code"] for г in итог["groups"]} == {"bizdev", "rnd"}


# --- издание без методики на машине ------------------------------------------


def test_издание_без_методики_остаётся_своей_группой(tmp_path: Path) -> None:
    """Снимка нет — форма неизвестна, но проверка из ряда не выпадает."""
    первое = _издание(tmp_path / "изд1", day="2026-09-01")
    _положить(tmp_path, tmp_path / "изд1", первое)

    итог = methodologies.of(
        [_проверка(version=первое), _проверка(version="ушедшее-2026-01-01-ffffffffffff")],
        papers=_полка(tmp_path),
    )

    assert len(итог["groups"]) == 2
    assert [г["scoring"] is None for г in итог["groups"]].count(True) == 1


def test_пустой_ряд_пустая_справка(tmp_path: Path) -> None:
    итог = methodologies.of([], papers=_полка(tmp_path))

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

    настоящая = methodologies.shape_of

    def счётчик(version: str, code: str, papers: letters.Papers) -> str | None:
        считано.append(version)
        return настоящая(version, code, papers)

    methodologies.of(
        [_проверка(version=издание, pct=float(i)) for i in range(20)],
        papers=_полка(tmp_path),
        shape=счётчик,
    )

    assert считано == [издание], "форма издания пересчитывалась на каждой строке ряда"
