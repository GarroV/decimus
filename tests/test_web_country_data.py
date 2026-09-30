"""Данные экрана «Страна»: снимок «Обзора» с отбором по стране и история одной точки."""

from __future__ import annotations

from dataclasses import replace

import pytest
from test_web_overview import ПУСТО, строка

from src.web import country as cn
from src.web import overview as ov


def test_код_страны_приводится_к_верхнему_и_мусор_отбрасывается() -> None:
    assert cn.normalize_code(" ge ") == "GE"
    assert cn.normalize_code("GEO") == ""
    assert cn.normalize_code("<s") == ""
    assert cn.normalize_code("") == ""


def test_страна_уходит_в_отбор_обзора(monkeypatch: pytest.MonkeyPatch) -> None:
    видели: dict[str, ov.Selection] = {}

    def снимок(**kw: object) -> ov.Overview:
        видели["selection"] = kw["selection"]  # type: ignore[assignment]
        return ПУСТО

    monkeypatch.setattr(cn.overview, "load", снимок)
    cn.load(tenant="HQ", limit=10, code="GE", selection=ov.Selection(period="d90", country="RS"))
    assert видели["selection"].country == "GE"
    assert видели["selection"].period == "d90"


def test_история_точки_из_того_же_снимка(monkeypatch: pytest.MonkeyPatch) -> None:
    первая = строка("Батуми-1", 90.0, "B")
    вторая = replace(строка("Батуми-1", 80.0, "C"), id="22222222-2222-3333-4444-000000000002")
    чужая = строка("Тбилиси-2", 95.5, "B")
    данные = replace(
        ПУСТО, inspections=(первая, чужая, вторая), unit_ids={"Батуми-1": "u-1", "Тбилиси-2": "u-2"}
    )
    monkeypatch.setattr(cn.overview, "load", lambda **_: данные)
    вид = cn.load(tenant="HQ", limit=10, code="GE", selection=ov.Selection(), unit_id="u-1")
    assert вид.unit_name == "Батуми-1"
    assert [r.id for r in вид.history] == [первая.id, вторая.id]


def test_чужой_или_мусорный_unit_ничего_не_раскрывает(monkeypatch: pytest.MonkeyPatch) -> None:
    данные = replace(
        ПУСТО, inspections=(строка("Батуми-1", 90.0, "B"),), unit_ids={"Батуми-1": "u-1"}
    )
    monkeypatch.setattr(cn.overview, "load", lambda **_: данные)
    for мусор in ("u-999", "<script>", ""):
        вид = cn.load(tenant="HQ", limit=10, code="GE", selection=ov.Selection(), unit_id=мусор)
        assert (вид.unit_id, вид.unit_name, вид.history) == ("", "", ())


def test_список_стран_по_справочнику(monkeypatch: pytest.MonkeyPatch) -> None:
    гео = {
        "Батуми-1": ("GE", "batumi"),
        "Тбилиси-2": ("GE", "tbilisi"),
        "Белград-1": ("RS", "belgrade"),
        "Без-1": ("", ""),
    }
    monkeypatch.setattr(cn.queries, "unit_geography", lambda **_: гео)
    assert cn.countries(tenant="HQ") == (("GE", 2), ("RS", 1))
