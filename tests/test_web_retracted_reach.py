"""Снятые проверки видит только сторона УК (D516, #580).

Партнёр не получает их ни в реестре, ни в карточке — даже при заданном
подключении администратора истории: снятые проверки УК его страны и причины
снятия ему не адресованы.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.db.reach import Reach
from src.web import inspections as data

ID = "11111111-1111-1111-1111-111111111111"


def _зовы(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    зовы: list[dict[str, Any]] = []

    def список(**kw: Any) -> list[Any]:
        зовы.append(kw)
        return []

    def карточка(_id: str, **kw: Any) -> None:
        зовы.append(kw)

    monkeypatch.setattr(data, "retraction_available", lambda: True)
    monkeypatch.setattr(data.queries, "list_inspections", список)
    monkeypatch.setattr(data.queries, "get_inspection", карточка)
    return зовы


@pytest.mark.parametrize(("tenant", "видит"), [("HQ", True), ("GE", False)])
def test_снятые_в_реестре_и_карточке_только_у_ук(
    monkeypatch: pytest.MonkeyPatch, tenant: str, видит: bool
) -> None:
    зовы = _зовы(monkeypatch)
    охват = Reach(tenant=tenant, tenants=None, countries=None)

    реестр = data.load_registry(reach=охват, limit=10)
    data.load_card(ID, reach=охват)

    assert реестр.retracted_visible is видит
    история, карточка = зовы[1], зовы[2]
    assert bool(история.get("include_retracted")) is видит
    assert bool(карточка.get("include_retracted")) is видит
