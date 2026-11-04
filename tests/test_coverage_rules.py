"""Правила проверки покрытия данных рейтингов «страна × источник» (D704, D706, #1444).

Ядро: ошибка молчалива — пустой источник или дыра, не замеченные проверкой, выглядят как
«всё хорошо». Без базы и сети: факты собираются руками.
"""

from __future__ import annotations

import re

from src.domain import coverage_rules as rules
from src.domain.coverage_rules import Fact

AGGREGATORS = (
    "wolt", "glovo", "bolt_food", "chowdeck", "trendyol_go", "yemeksepeti",
    "pyszne_pl", "yandex_eda", "migros_yemek",
)  # fmt: skip


def _fact(**kw: object) -> Fact:
    base = {"country": "SI", "source": rules.SRC_RS, "base": 10, "covered": 10, "ever": 10}
    return Fact(**{**base, **kw})  # type: ignore[arg-type]


def test_полное_покрытие_свежее_не_дыра() -> None:
    assert rules.judge(_fact(age_days=1, max_age_days=7)) is None


def test_пустой_источник_красный() -> None:
    f = rules.judge(_fact(covered=0, ever=0))
    assert f is not None and (f.level, f.reason) == (rules.RED, rules.EMPTY)


def test_страна_без_пиццерий_в_базе_ничего_не_ждёт() -> None:
    assert rules.judge(_fact(base=0, covered=0, ever=0)) is None


def test_покрытие_ровно_80_процентов_не_дыра_79_жёлтое() -> None:
    assert rules.judge(_fact(base=10, covered=8)) is None
    f = rules.judge(_fact(base=100, covered=79))
    assert f is not None and (f.level, f.reason) == (rules.YELLOW, rules.LOW)
    assert f.share == 0.79


def test_данные_старше_порога_жёлтые_ровно_на_пороге_нет() -> None:
    assert rules.judge(_fact(age_days=7, max_age_days=7)) is None
    f = rules.judge(_fact(age_days=8, max_age_days=7))
    assert f is not None and (f.level, f.reason) == (rules.YELLOW, rules.STALE)


def test_устаревшее_важнее_низкого_покрытия() -> None:
    f = rules.judge(_fact(covered=1, age_days=30, max_age_days=7))
    assert f is not None and f.reason == rules.STALE


def test_красное_важнее_жёлтого() -> None:
    f = rules.judge(_fact(covered=0, ever=0, age_days=30, max_age_days=7))
    assert f is not None and f.reason == rules.EMPTY


def test_агрегатор_не_заведён_для_страны_не_дыра() -> None:
    assert rules.judge(_fact(enrolled=False, covered=0, ever=0)) is None


def test_агрегатор_заведён_но_точек_нет_красный() -> None:
    f = rules.judge(_fact(source="agg_wolt", enrolled=True, covered=0, ever=0))
    assert f is not None and (f.level, f.reason) == (rules.RED, rules.EMPTY)


def test_вход_dodo_is_не_подключён_красный_и_отдельная_причина() -> None:
    f = rules.judge(_fact(source=rules.SRC_KR, connected=False, covered=0, ever=0))
    assert f is not None and (f.level, f.reason) == (rules.RED, rules.NOT_CONNECTED)


def test_нет_одного_из_двух_месяцев_жёлтое() -> None:
    f = rules.judge(_fact(source=rules.SRC_KR, missing=(rules.PREVIOUS,)))
    assert f is not None and (f.level, f.reason) == (rules.YELLOW, rules.MISSING_PREVIOUS)
    f = rules.judge(_fact(source=rules.SRC_KR, missing=(rules.CURRENT,)))
    assert f is not None and f.reason == rules.MISSING_CURRENT


def test_judge_all_отдаёт_только_дыры_в_стабильном_порядке() -> None:
    facts = [
        _fact(country="SI"),
        _fact(country="RS", covered=0, ever=0),
        _fact(country="AT", source=rules.SRC_RKO, covered=0, ever=0),
    ]
    found = rules.judge_all(facts)
    assert [(f.country, f.source) for f in found] == [("AT", "rko"), ("RS", "rs")]


def test_код_состояния_подходит_ограничению_таблицы_оповещений() -> None:
    pattern = re.compile(r"^[a-z_]{1,40}(:[A-Z]{2})?$")  # health.alerts.code, миграция 0099
    keys = [rules.SRC_RS, rules.SRC_RKO, rules.SRC_KR, rules.SRC_GOOGLE, rules.SRC_YANDEX]
    keys += [rules.agg_source(a) for a in AGGREGATORS]
    assert all(pattern.match(rules.state_code(k, "SI")) for k in keys)
