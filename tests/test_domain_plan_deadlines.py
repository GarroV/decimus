"""Срок строки электронного плана — ядро: партнёр читает его как факт (шаг 2 эпика #1168).

Срок строки = начало отсчёта + дни пункта методики, но не больше потолка класса;
D3 — немедленно. Числа живут только в методике: тесты берут их оттуда же или
сверяют с тем, что насчитал движок при сборке отчёта.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

import pytest
from conftest import TEST_DATA, Run

from src.domain.config import DATA_FILES
from src.domain.errors import ConfigError
from src.domain.plan_due import (
    Deadlines,
    effective_row_due,
    load_deadlines,
    plan_due_days,
    plan_due_on,
    row_due_on,
)
from src.domain.version import compose

START = date(2026, 10, 1)


def _книга(**kw: int) -> Deadlines:
    return Deadlines(max_days={"D1": 14, "D2": 10, "D3": 0}, item_days=dict(kw))


class TestДниСтроки:
    def test_дни_пункта_если_меньше_потолка(self) -> None:
        assert _книга(A=5).days_for("A", "D1") == 5

    def test_потолок_класса_режет_дни_пункта(self) -> None:
        assert _книга(A=14).days_for("A", "D2") == 10

    def test_D3_немедленно_сколько_бы_ни_было_дней_у_пункта(self) -> None:
        книга = _книга(A=14)
        assert книга.days_for("A", "D3") == 0
        assert row_due_on(START, 0) == START

    def test_пункта_нет_в_методике_берётся_потолок_класса(self) -> None:
        assert _книга().days_for("НЕТ", "D1") == 14

    def test_класса_нет_в_потолках_берутся_дни_пункта(self) -> None:
        assert Deadlines(max_days={}, item_days={"A": 7}).days_for("A", "D2") == 7

    def test_ни_пункта_ни_класса_это_отказ(self) -> None:
        with pytest.raises(ConfigError, match="не определить"):
            Deadlines(max_days={}, item_days={}).days_for("A", "D2")

    def test_отрицательные_дни_это_отказ(self) -> None:
        with pytest.raises(ConfigError):
            row_due_on(START, -1)


class TestСрокВЭтуДату:
    def test_срок_строки_это_начало_плюс_дни(self) -> None:
        assert row_due_on(START, 5) == date(2026, 10, 6)

    def test_срок_ответа_планом_из_методики(self, domain_env: Path) -> None:
        assert plan_due_on(START) == START + timedelta(days=plan_due_days())


class TestДействующийСрок:
    def test_без_своего_срока_положенный(self) -> None:
        assert effective_row_due(START, 5, None, None) == date(2026, 10, 6)

    def test_партнёр_может_раньше(self) -> None:
        assert effective_row_due(START, 5, date(2026, 10, 3), None) == date(2026, 10, 3)

    def test_позже_положенного_партнёр_не_ставит(self) -> None:
        assert effective_row_due(START, 5, date(2026, 10, 20), None) == date(2026, 10, 6)

    def test_сдвиг_начала_пересчитывает_положенный_срок(self) -> None:
        assert effective_row_due(date(2026, 10, 10), 5, None, None) == date(2026, 10, 15)

    def test_перенос_с_согласием_не_двигается_с_началом(self) -> None:
        перенос = date(2026, 11, 1)
        assert effective_row_due(date(2026, 10, 10), 5, date(2026, 10, 12), перенос) == перенос


class TestИзМетодики:
    def test_читаются_дни_пунктов_и_потолки(self, domain_env: Path) -> None:
        книга = load_deadlines(compose(TEST_DATA, DATA_FILES))
        assert set(книга.max_days) == {"D1", "D2", "D3"}
        assert book_days(книга, "PRD03") == 5

    def test_потолок_берётся_из_методики_а_не_из_кода(
        self, domain_env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        копия = tmp_path / "m"
        shutil.copytree(TEST_DATA, копия)
        файл = копия / "scoring.json"
        ставки = json.loads(файл.read_text(encoding="utf-8"))
        ставки["deadlines"]["max_days"]["D1"] = 2
        файл.write_text(json.dumps(ставки), encoding="utf-8")
        monkeypatch.setenv("AUDIT_DATA_DIR", str(копия))
        книга = load_deadlines(compose(копия, DATA_FILES))
        assert книга.days_for("PRD03", "D1") == 2

    def test_методика_без_потолков_это_отказ(
        self, domain_env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        копия = tmp_path / "m"
        shutil.copytree(TEST_DATA, копия)
        файл = копия / "scoring.json"
        ставки = json.loads(файл.read_text(encoding="utf-8"))
        del ставки["deadlines"]
        файл.write_text(json.dumps(ставки), encoding="utf-8")
        monkeypatch.setenv("AUDIT_DATA_DIR", str(копия))
        with pytest.raises(ConfigError, match="max_days"):
            load_deadlines(compose(копия, DATA_FILES))

    @pytest.mark.parametrize(
        ("qid", "level", "zone"),
        [
            ("PRD03", "D1", "hot_kitchen"),
            ("PRD02", "D2", "hot_kitchen"),
            ("PRD06", "D1", "hot_kitchen"),
            ("PRD04", "D3", "cold_kitchen"),
            ("PRD01", "D1", "cold_kitchen"),
        ],
    )
    def test_совпадает_с_движком(
        self,
        qid: str,
        level: str,
        zone: str,
        domain_env: Path,
        started: Callable[..., Run],
    ) -> None:
        assert started("add", "--qid", qid, "--level", level, "--zone", zone).code == 0
        r = started("score", "--json")
        assert r.code == 0, r.text
        запись = next(i for i in json.loads(r.text)["findings"] if i["qid"] == qid)
        книга = load_deadlines(compose(TEST_DATA, DATA_FILES))
        assert книга.days_for(qid, level) == запись["days"]


def book_days(книга: Deadlines, код: str) -> int:
    return книга.item_days[код]
