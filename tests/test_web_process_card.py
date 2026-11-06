# ruff: noqa: F811 — фикстура стенда приходит импортом из test_web_app
"""Карточка проверки в режиме процессов (D714, прототип).

Процессы — главный итог: статус (OK / обнулён), потеря, нарушения свёрнуты по
пункту с зонами-адресами. Зоны — только адреса, своей потери не показывают.
Проверка в зонном режиме выглядит как прежде.
"""

from __future__ import annotations

from typing import Any

import pytest
from flask.testing import FlaskClient
from test_web_app import карточка, стенд, шапка  # noqa: F401

from src.db.models import FindingRow
from src.web import inspections as data
from src.web.texts import t


def _зона(code: str, name: str, counts: dict[str, int]) -> dict[str, Any]:
    return {
        "code": code,
        "name_ru": name,
        "name_en": name,
        "share": 20.0,
        "counts": counts,
        "loss": 0.0,
        "left": 20.0,
        "zeroed": False,
    }


def _запись(row: Any, n: int, code: str, level: str, zone: str, text: str) -> FindingRow:
    return FindingRow(
        id=f"f{n}",
        inspection_id=row.id,
        unit_name=row.unit_name,
        inspection_date=row.inspection_date,
        n=n,
        code=code,
        level=level,
        zone=zone,
        zone_unusual=False,
        source="comment",
        lang="ru",
        text=text,
        comment=None,
    )


def _процессы() -> dict[str, Any]:
    return {
        "PRODUCT": {
            "code": "PRODUCT",
            "name_ru": "Работа с продуктом",
            "name_en": "Product handling",
            "scored": True,
            "model": "process",
            "zeroed": True,
            "D1": 1,
            "D2": 0,
            "D3": 1,
            "loss": 10.0,
            "items": [
                {
                    "qid": "PRD10",
                    "level": "D3",
                    "repeat": False,
                    "zones": ["KITCHEN", "STORE", "HALL"],
                    "findings": [1, 2, 3],
                    "lead": 1,
                    "counted": True,
                    "cost": 0.0,
                },
                {
                    "qid": "PRD06",
                    "level": "D1",
                    "repeat": False,
                    "zones": ["KITCHEN"],
                    "findings": [4],
                    "lead": 4,
                    "counted": False,
                    "cost": 0.0,
                },
            ],
        },
        "CLEAN": {
            "code": "CLEAN",
            "name_ru": "Чистота",
            "name_en": "Cleanliness",
            "scored": True,
            "model": "process",
            "zeroed": False,
            "D1": 0,
            "D2": 0,
            "D3": 0,
            "loss": 0.0,
            "items": [],
        },
    }


def test_процессы_главный_итог_зоны_адреса(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def поля(строка: Any) -> dict[str, Any]:
        return {
            "deductions": 10.0,
            "counts": {"D1": 0, "D3": 1},
            "by_process": _процессы(),
            "by_zone": {
                "KITCHEN": _зона("KITCHEN", "Кухня", {"D3": 1, "D1": 1}),
                "STORE": _зона("STORE", "Склад", {"D3": 1}),
                "HALL": _зона("HALL", "Зал", {"D3": 1}),
            },
            "findings": (
                _запись(строка, 1, "PRD10", "D3", "KITCHEN", "Просрочка в холодильнике"),
                _запись(строка, 2, "PRD10", "D3", "STORE", "Просрочка на складе"),
                _запись(строка, 3, "PRD10", "D3", "HALL", "Просрочка на витрине"),
                _запись(строка, 4, "PRD06", "D1", "KITCHEN", "Нет маркировки"),
            ),
        }

    страница = _открыть_с(стенд, monkeypatch, поля)

    assert t("card.proc.title", "ru") in страница
    assert t("card.zones.title", "ru") not in страница, "у зоны в режиме процессов потери нет"
    assert страница.count(t("card.proc.zeroed", "ru") + " · D3") == 1, (
        "один D3 на процесс — одна метка"
    )
    assert t("card.proc.found", "ru", zones="Кухня, Склад, Зал") in страница
    assert t("card.proc.absorbed", "ru") in страница
    assert t("card.proc.ok", "ru") in страница
    assert t("card.zones.addr.title", "ru") in страница
    assert t("card.findings.by_zone", "ru") in страница


def _открыть_с(стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch, поля: Any) -> str:
    строка = шапка(pct=90.0)
    monkeypatch.setattr(data, "load_card", lambda *_a, **_k: карточка(строка, **поля(строка)))
    monkeypatch.setattr(data, "load_moves", lambda *_a, **_k: ())
    return стенд.get(f"/inspections/{строка.id}?lang=ru").get_data(as_text=True)


def test_зонная_проверка_выглядит_как_прежде(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    страница = _открыть_с(стенд, monkeypatch, lambda _s: {})

    assert t("card.zones.title", "ru") in страница
    assert t("card.proc.title", "ru") not in страница
