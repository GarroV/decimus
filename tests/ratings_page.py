"""Общая подготовка для тестов разделов «Рейтингов» (D660): настоящая страница, данные подменены.

Сводка, периоды, охват и зона риска читают базу — здесь их места заняты заглушками,
а считать их не нужно: проверяется показ и устройство страницы. Заглушки собирают
вызовы: «раздел считает только своё» проверяется по ним.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Any

import pytest
from flask.testing import FlaskClient
from web_harness import войти, подменить_двери, собрать

from src.db import customer_ratings, ratings_violations
from src.db.ratings_read import CountryRow
from src.ratings import compare as rcompare
from src.ratings import report
from src.ratings.periods import month_period
from src.ratings.summary import CountryLine, UnitScore, ViolationBlock, ViolationFact
from src.web import ratings as screen
from src.web.ratings_risk import CombinedRisk

ПУСТОЙ = ViolationBlock(0, 0, None, ())
ЕСТЬ_ДАННЫЕ = ViolationBlock(3, 3, 1.0, ())


def факты(n: int) -> tuple[ViolationFact, ...]:
    return tuple(
        ViolationFact(f"u{i}", f"Пиццерия {i}", "RS", f"Нарушение {i}", None, "hard", 1)
        for i in range(n)
    )


def сводка(**поля: Any) -> report.Summary:
    """Сводка одной страны за сентябрь; `поля` переопределяют любое поле."""
    база = report.Summary(
        selection=report.Selection(report.GROUP_IMF, None, month_period(2026, 9)),
        countries=("RS",),
        groups=(),
        lines=(CountryLine("RS", 91.0, 88.0, 0.4, -1.2),),
        total=CountryLine("", 91.0, 88.0, 0.4, -1.2),
        previous=None,
        rko_cluster=ЕСТЬ_ДАННЫЕ,
        rko_by_country={"RS": ЕСТЬ_ДАННЫЕ},
        rs_cluster=ЕСТЬ_ДАННЫЕ,
        rs_by_country={"RS": ЕСТЬ_ДАННЫЕ},
        rs_top=(UnitScore("u1", "Пиццерия-Верх", "RS", 97.0, 1.0),),
        rs_bottom=(UnitScore("u2", "Пиццерия-Низ", "RS", 70.0, None),),
        rs_hard=(),
        rko_top=(),
        rko_bottom=(),
        rko_hard=(),
        risk=(),
        risk_short=(),
        thresholds={"top_threshold": 80.0, "risk_threshold": 70.0, "risk_periods": 3.0},
        last_loaded={},
        rs_units={"RS": 4},
        rko_units={"RS": 3},
    )
    return replace(база, **поля)


def подготовить(
    monkeypatch: pytest.MonkeyPatch, данные: report.Summary | None = None
) -> dict[str, list[Any]]:
    """Подменить чтение базы; вернуть журнал вызовов (`build`, `compare`, `agg`, `maps`)."""
    monkeypatch.setattr(customer_ratings, "monthly", lambda *_args: [])
    monkeypatch.setattr(customer_ratings, "loads", lambda *_args: [])
    monkeypatch.setattr(customer_ratings, "latest_month", lambda *_args: None)
    итог = данные or сводка()
    вызовы: dict[str, list[Any]] = {"build": [], "compare": [], "agg": [], "maps": []}
    страна = CountryRow("RS", "Сербия", "Serbia", None, True, "CEE")

    def оценки(*, countries: Any, begin: date, **_kw: Any) -> list[tuple[Any, ...]]:
        """Сохранённые оценки: новый source builder читает ту же синтетическую выборку."""
        rows = []
        previous = begin < итог.selection.period.begin
        for kind in ("rs", "rko"):
            counts = итог.rs_units if kind == "rs" else итог.rko_units
            for line in итог.lines:
                mean = line.rs if kind == "rs" else line.rko
                delta = line.rs_delta if kind == "rs" else line.rko_delta
                # Отсутствующий итог в fixture означает отсутствие оценок источника.
                total = итог.total.rs if kind == "rs" else итог.total.rko
                if line.country not in countries or mean is None or total is None:
                    continue
                n = counts.get(line.country, 0)
                if not n:
                    continue
                scores = [mean] * n
                names = [f"Пиццерия {i}" for i in range(n)]
                if kind == "rs" and n >= 3:
                    scores = [97.0, 70.0] + [(mean * n - 167.0) / (n - 2)] * (n - 2)
                    names[:2] = ["Пиццерия-Верх", "Пиццерия-Низ"]
                for i, score in enumerate(scores):
                    rows.append(
                        (
                            f"{kind}-u{i}",
                            names[i],
                            line.country,
                            kind,
                            1,
                            begin,
                            score - (delta or 0) if previous else score,
                            begin,
                        )
                    )
        return rows

    def нарушения(kind: str, countries: Any, period: Any) -> tuple[Any, ...]:
        block = итог.rs_cluster if kind == "rs" else итог.rko_cluster
        if not block.total or "RS" not in countries:
            return ()
        return (
            ratings_violations.Occurrence(
                1,
                kind,
                "u1",
                "Пиццерия 1",
                "RS",
                "Синтетическое нарушение",
                None,
                "violation",
                None,
                block.total,
                None,
                None,
                None,
                datetime(2026, 9, 1, tzinfo=UTC),
            ),
        )

    def собрать_сводку(_selection: Any, **kw: Any) -> report.Summary:
        вызовы["build"].append(kw)
        return итог

    def сравнить(*_a: Any) -> rcompare.Comparison:
        вызовы["compare"].append(1)
        return rcompare.Comparison((), ())

    def отбор(args: Any, **_k: Any) -> tuple[report.Selection, report.Choices]:
        """Срез — из адреса, как у настоящего `select`; период — сентябрь."""
        группа = args.get("group", report.GROUP_IMF)
        значение = args.get("value") or None
        выбор = report.Selection(группа, значение, итог.selection.period)
        return выбор, report.Choices((), (страна,), ())

    monkeypatch.setattr(screen.report, "select", отбор)
    monkeypatch.setattr(screen.report, "build", собрать_сводку)
    monkeypatch.setattr(screen.report, "build_groups", lambda *_a: ((), None))
    monkeypatch.setattr(screen.rcompare, "build", сравнить)
    monkeypatch.setattr(screen.read, "period_months", lambda: ())
    monkeypatch.setattr(screen.read, "rko_periods", lambda: ())
    monkeypatch.setattr(screen.read, "source_rating_periods", lambda **_kw: ())
    monkeypatch.setattr(screen.read, "score_facts", оценки)
    monkeypatch.setattr(ratings_violations, "facts", нарушения)
    monkeypatch.setattr(
        ratings_violations,
        "checkup_coverage",
        lambda *_a: ratings_violations.CheckupCoverage(0, None),
    )
    monkeypatch.setattr(screen, "_maps", lambda *_a: None)
    monkeypatch.setattr(screen, "_unit_maps", lambda _u: {})
    monkeypatch.setattr(screen, "_registry_units", lambda _c: None)
    monkeypatch.setattr(screen, "_agg_failures", lambda: ())
    monkeypatch.setattr(screen, "_agg_pending", lambda: None)
    monkeypatch.setattr(screen.ratings_risk, "build", lambda *_a, **_k: CombinedRisk((), ()))
    monkeypatch.setattr(screen.ratings_freshness, "read_rows", lambda now: ())

    def охват_агрегаторов(*_a: Any, **_k: Any) -> None:
        вызовы["agg"].append(1)

    def охват_карт(*_a: Any, **_k: Any) -> None:
        вызовы["maps"].append(1)

    monkeypatch.setattr(screen.ratings_platforms, "build_agg", охват_агрегаторов)
    monkeypatch.setattr(screen.ratings_platforms, "build_maps", охват_карт)
    return вызовы


def клиент(
    monkeypatch: pytest.MonkeyPatch, ui_lang: str = "ru", *, tenant: str = "HQ", role: str = "admin"
) -> Iterator[FlaskClient]:
    подменить_двери(monkeypatch, tenant=tenant, role=role)
    with собрать(tenant=tenant, ui_lang=ui_lang).test_client() as c:
        assert войти(c).status_code == 302
        yield c


def получить(
    monkeypatch: pytest.MonkeyPatch,
    адрес: str = "/ratings",
    *,
    ui_lang: str = "ru",
    tenant: str = "HQ",
) -> str:
    for c in клиент(monkeypatch, ui_lang, tenant=tenant):
        return c.get(адрес).get_data(as_text=True)
    raise AssertionError("клиент не создан")
