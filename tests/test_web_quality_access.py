"""«Качество»: проверки decimus видит не каждый (D420) и откуда берутся РКО и РС.

Те же подмены чтений, что в `tests/test_web_quality.py`.
"""

# ruff: noqa: F811
from __future__ import annotations

from datetime import date
from decimal import Decimal as D

import pytest
from flask.testing import FlaskClient
from test_web_quality import PL1, _client, ук, чтения  # noqa: F401

from src.db import dodois_metrics, quality_read


def test_control_does_not_see_inspections_or_es(
    monkeypatch: pytest.MonkeyPatch, чтения: None
) -> None:
    """Контроль не видит проверки decimus: ни ЭС, ни колонки проверки, ни самого чтения."""
    asked: list[object] = []

    def audits(reach: object, countries: object, month: object) -> dict[str, D]:
        asked.append(month)
        return {PL1: D("90")}

    monkeypatch.setattr(quality_read, "audit_pcts", audits)
    for client in _client(monkeypatch, role="control"):
        html = client.get("/quality?country=PL&month=2026-09").get_data(as_text=True)
        assert "Warsaw-1" in html and "ЛКО" in html
        assert "Эталон стандартов" not in html and "Проверка decimus" not in html
        assert "ЭС" not in html
        assert not asked
        assert "ЭС" not in client.get("/quality?month=2026-09").get_data(as_text=True)


def test_admin_sees_audit_and_es(ук: FlaskClient) -> None:
    html = ук.get("/quality?country=PL&month=2026-09").get_data(as_text=True)
    assert "Эталон стандартов" in html and "Проверка decimus" in html


def test_dodois_rating_periods_win_over_the_control_sheet(
    monkeypatch: pytest.MonkeyPatch, ук: FlaskClient
) -> None:
    def periods(code: str, month: date) -> list[dodois_metrics.UnitRatingPeriod]:
        if code != "PL":
            return []
        return [
            dodois_metrics.UnitRatingPeriod(
                PL1, "rko", date(2026, 9, 1), date(2026, 9, 7), D("100"), None, 10
            ),
            dodois_metrics.UnitRatingPeriod(
                PL1, "rko", date(2026, 9, 8), date(2026, 9, 14), D("98"), None, 12
            ),
        ]

    monkeypatch.setattr(dodois_metrics, "unit_rating_periods", periods)
    html = ук.get("/quality?country=PL&month=2026-09").get_data(as_text=True)
    # у Krakow-1 периодов Dodo IS нет — для него таблица контроля, источник смешанный
    assert "РКО и РС: Dodo IS, где есть" in html
    assert ">99.0<" in html  # РКО: среднее недель Dodo IS, а не 90.9 из таблицы
    assert ">11.0<" in html  # проверок в неделю: среднее по неделям Dodo IS
