# ruff: noqa: F811 — фикстура стенда приходит импортом из test_web_app
"""Карточка объясняет букву и оценку (D490): причина рядом с буквой, «Расшифровка» под ней.

Ответ движка здесь настоящий: `compute` из `engine/audit.py` по набору находок,
подменён только вызов подпроцесса. Так проверяется и то, что экран кладёт на
страницу, и то, что он берёт это у движка, а не считает сам.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from typing import Any

import pytest
from flask.testing import FlaskClient
from test_web_app import карточка, стенд, шапка  # noqa: F401

from src.report.explain import Explained
from src.web import grade_explain
from src.web import inspections as data

ПОВЕРХНОСТИ = ("/inspections/{id}", "/inspections?inspection={id}")
ДВИЖОК = Path(__file__).resolve().parents[1] / "engine" / "audit.py"


def _правило(grade: str, **условие: float) -> dict[str, Any]:
    return {"grade": grade, "if": условие, "label_ru": grade, "label_en": grade}


CFG: dict[str, Any] = {
    "start_pct": 100.0,
    "penalty": {"D1": 0.5, "D2": 2.0},
    "repeat_multiplier": 2.0,
    "d3": {"mode": "zero_zone_share", "skip_other_violations_in_d3_zone": True},
    "deadlines": {"max_days": {"D1": 14, "D2": 10, "D3": 0}},
    "grades": {
        "rules": [
            _правило("D", min_d3=1),
            _правило("C", min_d2=2),
            _правило("C", pct_below=90.0),
            _правило("A", pct_at_least=95.0, max_d2=0),
            _правило("B", pct_at_least=90.0, max_d2=1),
        ],
        "fallback": {"grade": "C", "label_ru": "C", "label_en": "C"},
    },
}
ЗОНЫ = [
    {"code": "HOT", "name_ru": "Цех Альфа", "name_en": "Alpha shop", "share_pct": 10.0},
    {"code": "DINING", "name_ru": "Зал", "name_en": "Dining room", "share_pct": 10.0},
    {"code": "FRIDGE", "name_ru": "Холодильная", "name_en": "Fridge", "share_pct": 10.0},
]


def _посчитать(*находки: tuple[str, str, bool]) -> dict[str, Any]:
    spec = importlib.util.spec_from_file_location("audit_web_explain", ДВИЖОК)
    assert spec and spec.loader
    движок = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(движок)
    записи = [
        {"n": n, "qid": f"Q{n:02d}", "level": lvl, "zone": zone, "repeat": rep}
        for n, (lvl, zone, rep) in enumerate(находки, 1)
    ]
    return движок.compute({"meta": {"date": "2026-10-14"}, "findings": записи}, [], ЗОНЫ, CFG)


def _открыть(
    стенд: FlaskClient,
    monkeypatch: pytest.MonkeyPatch,
    адрес: str,
    res: dict[str, Any],
    *,
    exact: bool = True,
    **шапка_полей: Any,
) -> str:
    строка = шапка(pct=res["pct"], grade=res["grade"], **шапка_полей)
    by_zone = {
        code: {**z, "code": code, "left": z["score"], "counts": {}}
        for code, z in res["zones"].items()
    }
    detail = карточка(строка, counts=res["counts"], by_zone=by_zone, deductions=res["deductions"])
    разбивка = {**res["breakdown"], "exact": res["breakdown"]["exact"] and exact}
    monkeypatch.setattr(data, "load_card", lambda *_a, **_k: detail)
    monkeypatch.setattr(data, "load_moves", lambda *_a, **_k: ())
    monkeypatch.setattr(data, "load_units", lambda **_k: (("u-1", строка.unit_name),))
    monkeypatch.setattr(data, "load_registry", lambda **_: data.Registry((строка,), True, ()))
    monkeypatch.setattr(
        grade_explain.explain_engine,
        "explain",
        lambda *_a, **_k: Explained(grade_rule=res["grade_rule"], breakdown=разбивка),
    )
    return стенд.get(адрес.format(id=строка.id)).get_data(as_text=True)


def _строки(страница: str) -> list[str]:
    блок = re.search(r'<ul class="explain">(.*?)</ul>', страница, re.S)
    assert блок, "нет блока «Расшифровка»"
    return re.findall(r"<li>(.*?)</li>", блок.group(1))


def _причина(страница: str) -> str:
    найдено = re.search(r'class="meta grade-reason"><span>(.*?)</span>', страница)
    assert найдено, "нет строки причины буквы"
    return найдено.group(1)


# D1 x10 (5 в зале, 5 в холодильной), D2 x2 (одно в холодильной, одно в зоне с D3), D3 x1.
БАТУМИ = (
    *[("D1", "DINING" if n < 5 else "FRIDGE", False) for n in range(10)],
    ("D2", "FRIDGE", False),
    ("D2", "HOT", False),
    ("D3", "HOT", False),
)


@pytest.mark.parametrize("адрес", ПОВЕРХНОСТИ)
def test_у_D3_причина_буквы_названа_и_расшифровка_сходится_с_итогом(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch, адрес: str
) -> None:
    res = _посчитать(*БАТУМИ)

    страница = _открыть(стенд, monkeypatch, адрес, res)

    assert _причина(страница) == "D — критическое нарушение (D3)"
    строки = _строки(страница)
    assert строки == [
        "D1 × 10 — −5%",
        "D2 × 1 — −2%",
        "D3 в зоне «Цех Альфа» — зона обнулена, −10%",
        "Не снижали балл (зона уже обнулена D3): D2 × 1",
        "Итог — 83%",
    ]
    # D533: строки «Старт — 100%» нет ни в одной поверхности.
    assert "Старт" not in " ".join(строки)
    # Вычеты в строках плюс итог дают старт: экран не показывает цифр, что не сходятся.
    вычеты = [float(x.replace(",", ".")) for x in re.findall(r"−([\d,]+)%", " ".join(строки))]
    assert 100.0 - sum(вычеты) == res["pct"]


@pytest.mark.parametrize("адрес", ПОВЕРХНОСТИ)
def test_у_B_с_D2_причина_называет_D2_а_с_низким_баллом_порог_A(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch, адрес: str
) -> None:
    с_d2 = _посчитать(("D2", "DINING", False))  # 98 %: не A из-за D2
    assert _причина(_открыть(стенд, monkeypatch, адрес, с_d2)) == "B — есть нарушение D2"

    низкий = _посчитать(*[("D1", "DINING", False)] * 16)  # 92 % без D2: не A из-за балла
    assert (низкий["grade"], низкий["pct"]) == ("B", 92.0)
    assert _причина(_открыть(стенд, monkeypatch, адрес, низкий)) == "B — балл ниже 95%"


def test_повтор_показан_отдельной_строкой(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    res = _посчитать(("D1", "DINING", True), ("D1", "FRIDGE", False))

    страница = _открыть(стенд, monkeypatch, "/inspections/{id}", res)

    assert "D1 повтор × 1 — −1%" in _строки(страница)
    assert "D1 × 1 — −0,5%" in _строки(страница)


def test_если_строки_не_сходятся_остаются_вычеты_по_зонам_без_строк_по_классам(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    res = _посчитать(*БАТУМИ)

    страница = _открыть(стенд, monkeypatch, "/inspections/{id}", res, exact=False)

    строки = _строки(страница)
    assert not any("D1 ×" in s for s in строки), строки
    assert строки[-1] == "Итог — 83%"
    assert "Цех Альфа — −10%" in строки


def test_у_исторической_проверки_ни_причины_ни_расшифровки(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    res = _посчитать(*БАТУМИ)

    страница = _открыть(стенд, monkeypatch, "/inspections/{id}", res, origin="legacy")

    assert "grade-reason" not in страница
    assert 'class="explain"' not in страница
