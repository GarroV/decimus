"""D191: повторное нарушение стоит вдвое.

Решение владельца 24.09.2026: если нарушение повторяет то, что было записано в
предыдущей проверке той же точки, вычет за него удваивается. Правило работает
В МОМЕНТ РАСЧЁТА конкретной проверки — прошлые проверки не пересчитываются.

Это ядро: ошибка здесь тихая и дорогая. Неверно удвоенный вычет — это не
падение, а правдоподобно неправильный процент в документе, который партнёр
читает как факт и по которому платит.

Признак повтора ставится НА ЗАПИСИ и фиксируется человеком. Движок считает
одну проверку и истории точки не видит: догадаться о повторе он не может, а
угадывать цену нельзя.
"""

from __future__ import annotations

import importlib.util
import json
from collections.abc import Callable
from pathlib import Path

from conftest import Run, requires_data

ДВИЖОК = Path(__file__).resolve().parents[1] / "engine" / "audit.py"


def движок() -> object:
    """Сам скрипт движка модулем — чтобы звать `compute()` напрямую."""
    spec = importlib.util.spec_from_file_location("audit_под_тестом", ДВИЖОК)
    assert spec and spec.loader
    модуль = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(модуль)
    return модуль


def оценка(started: Callable[..., Run]) -> dict:
    r = started("score", "--json")
    assert r.code == 0, r.text
    return json.loads(r.text)


class TestЦенаПовтора:
    def test_обычная_D2_стоит_ставку(self, started: Callable[..., Run]) -> None:
        assert started("add", "--qid", "PRD05", "--level", "D2", "--zone", "hot_kitchen").code == 0

        assert оценка(started)["deductions"] == 2.0

    def test_повторная_D2_стоит_вдвое(self, started: Callable[..., Run]) -> None:
        r = started(
            "add", "--qid", "PRD05", "--level", "D2", "--zone", "hot_kitchen", "--repeat"
        )
        assert r.code == 0, r.text

        assert оценка(started)["deductions"] == 4.0, "повтор посчитан по обычной ставке"

    def test_повторная_D1_стоит_вдвое(self, started: Callable[..., Run]) -> None:
        assert started(
            "add", "--qid", "PRD05", "--level", "D1", "--zone", "hot_kitchen", "--repeat"
        ).code == 0

        assert оценка(started)["deductions"] == 1.0

    def test_пометка_повтора_видна_в_записи(
        self, started: Callable[..., Run], workdir: Path
    ) -> None:
        # Человек, открывший файл проверки, обязан видеть, за что удвоено:
        # цифра, объяснение которой нигде не записано, спорна по определению.
        assert started(
            "add", "--qid", "PRD05", "--level", "D2", "--zone", "hot_kitchen", "--repeat"
        ).code == 0

        st = json.loads((workdir / "inspection.json").read_text(encoding="utf-8"))
        assert st["findings"][0].get("repeat") is True

    def test_без_пометки_цена_прежняя(
        self, started: Callable[..., Run], workdir: Path
    ) -> None:
        # Обратная сторона того же: записи без пометки дорожать не должны,
        # иначе правило задним числом переоценит всё записанное раньше.
        assert started("add", "--qid", "PRD05", "--level", "D2", "--zone", "hot_kitchen").code == 0

        st = json.loads((workdir / "inspection.json").read_text(encoding="utf-8"))
        assert st["findings"][0].get("repeat", False) is False
        assert оценка(started)["deductions"] == 2.0


class TestМножитель:
    """Множитель — ставка, и живёт он там же, где остальные ставки."""

    def cfg(self, **правки: object) -> dict:
        основа = {
            "start_pct": 100.0,
            "penalty": {"D1": 0.5, "D2": 2.0},
            "d3": {"mode": "zero_zone_share", "skip_other_violations_in_d3_zone": True},
            "deadlines": {"max_days": {"D1": 30, "D2": 14, "D3": 1}},
            "grades": {
                "rules": [
                    {"if": {"pct_at_least": 0.0}, "grade": "A", "label_ru": "—", "label_en": "—"}
                ]
            },
        }
        основа.update(правки)
        return основа

    def состояние(self, *, repeat: bool) -> dict:
        return {
            "meta": {"date": "2026-09-20"},
            "findings": [
                {"n": 1, "qid": "PRD05", "level": "D2", "zone": "hot_kitchen", "repeat": repeat}
            ],
        }

    def test_множитель_берётся_из_настроек_а_не_зашит(self) -> None:
        зоны = [
            {
                "code": "hot_kitchen",
                "name_ru": "Зона под тестом",
                "name_en": "Zone under test",
                "share_pct": 20.0,
            }
        ]

        res = движок().compute(  # type: ignore[attr-defined]
            self.состояние(repeat=True),
            [{"id": "PRD05", "days": 14}],
            зоны,
            self.cfg(repeat_multiplier=3.0),
        )

        assert res["deductions"] == 6.0, "множитель из настроек не применён"

    def test_без_множителя_в_настройках_цена_не_меняется(self) -> None:
        # Старый файл ставок без нового ключа обязан считать как раньше, а не
        # обнулить вычет или удвоить его молча.
        зоны = [
            {
                "code": "hot_kitchen",
                "name_ru": "Зона под тестом",
                "name_en": "Zone under test",
                "share_pct": 20.0,
            }
        ]

        res = движок().compute(  # type: ignore[attr-defined]
            self.состояние(repeat=True), [{"id": "PRD05", "days": 14}], зоны, self.cfg()
        )

        assert res["deductions"] == 2.0

    @requires_data
    def test_настоящие_ставки_проекта_знают_множитель(self) -> None:
        # Боевая методика лежит ВНЕ git (управляющая компания, публичный
        # репозиторий), поэтому проверка помечена маркером и на машине без
        # неё честно пропускается, а не выдаёт зелёное за непроверенное.
        ставки = json.loads(
            (Path(__file__).resolve().parents[1] / "data" / "scoring.json").read_text(
                encoding="utf-8"
            )
        )

        assert ставки.get("repeat_multiplier") == 2.0, "D191: повтор стоит вдвое"


class TestГраницы:
    def test_повтор_не_удваивает_обнулённую_зону(
        self, started: Callable[..., Run]
    ) -> None:
        # D3 сжигает долю зоны целиком. Удваивать тут нечего: доля зоны — не
        # вычет за запись, и умножение её на два выдало бы потерю больше, чем
        # зона вообще стоит.
        r = started("add", "--qid", "PRD05", "--level", "D3", "--zone", "hot_kitchen", "--repeat")
        assert r.code == 0, r.text

        разбивка = оценка(started)["zones"]["hot_kitchen"]
        assert разбивка["loss"] == разбивка["share"]

    def test_повтор_в_зоне_с_D3_не_считается_дважды(
        self, started: Callable[..., Run]
    ) -> None:
        # Записи в зоне с D3 в цену не идут вовсе (`skip_other_violations_in_d3_zone`).
        # Удвоение нуля обязано остаться нулём, а не воскресить запись.
        assert started("add", "--qid", "PRD05", "--level", "D3", "--zone", "hot_kitchen").code == 0
        assert started(
            "add", "--qid", "PRD09", "--level", "D2", "--zone", "hot_kitchen", "--repeat"
        ).code == 0

        разбивка = оценка(started)["zones"]["hot_kitchen"]
        assert разбивка["loss"] == разбивка["share"]
