"""Граница пространств в вебе (волна 1, #340; Review Focus 5).

Партнёру чужая проверка — 404 тем же ответом, что несуществующая. УК читает
проверку партнёра (D283), но запись по ней — снятие, перенос, письмо — отказ
403, и дверь записи не зовётся. Чтение получает охват вошедшего, запись — его
пространство, а не тенант стенда.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from web_harness import СВОЙ, войти, подменить_двери, собрать

from src.db.reach import Reach
from src.web import auth
from src.web import inspections as data
from src.web.app import MoveError, RetractionError

ЧУЖАЯ = "11111111-1111-1111-1111-111111111111"
НЕТ = "22222222-0000-0000-0000-000000000000"
КАДР = "33333333-3333-3333-3333-333333333333"
ЗАПИСЬ = [
    f"/inspections/{ЧУЖАЯ}/retract",
    f"/inspections/{ЧУЖАЯ}/move",
    f"/inspections/{ЧУЖАЯ}/letter/save",
    f"/inspections/{ЧУЖАЯ}/letter/draft",
]
#: Снятие и перенос партнёру закрыты целиком (D341): 403 ещё до чтения
#: проверки, поэтому своя, чужая и несуществующая снаружи неразличимы.
ЗАДНИМ_ЧИСЛОМ = (f"/inspections/{ЧУЖАЯ}/retract", f"/inspections/{ЧУЖАЯ}/move")
ОХВАТ_GE = Reach("GE", None, ("GE",))


@pytest.fixture
def двери(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Any]]:
    """Чтение отвечает «такой нет»; запись запоминает, с чем её позвали."""
    зовы: list[tuple[str, Any]] = []

    def нет(имя: str) -> Any:
        def дверь(*_a: Any, **k: Any) -> None:
            зовы.append((имя, k.get("reach")))

        return дверь

    def отказ(имя: str, ошибка: type[Exception]) -> Any:
        def дверь(*_a: Any, **k: Any) -> None:
            зовы.append((имя, k.get("tenant")))
            raise ошибка("проверка не найдена")

        return дверь

    for имя in ("load_card", "load_report", "preview_bytes"):
        monkeypatch.setattr(data, имя, нет(имя))
    monkeypatch.setattr(data, "retract_card", отказ("retract_card", RetractionError))
    monkeypatch.setattr(data, "move_card", отказ("move_card", MoveError))
    monkeypatch.setattr(data, "retraction_available", lambda: True)
    # Администратор: снятие и перенос у аудитора отказывают 403 ещё до двери.
    подменить_двери(monkeypatch, tenant="GE", role="admin")
    monkeypatch.setattr(auth, "reach_of", lambda t: ОХВАТ_GE if t == "GE" else Reach(t, None, None))
    return зовы


@pytest.mark.parametrize(
    ("метод", "адрес"),
    [
        ("get", f"/inspections/{ЧУЖАЯ}"),
        ("get", f"/inspections/{ЧУЖАЯ}/report"),
        ("get", f"/inspections/{ЧУЖАЯ}/photos/{КАДР}"),
        ("get", f"/inspections/{ЧУЖАЯ}/letter"),
    ]
    + [("post", a) for a in ЗАПИСЬ if a not in ЗАДНИМ_ЧИСЛОМ],
)
def test_партнёру_чужая_проверка_не_найдена(
    двери: list[tuple[str, Any]], метод: str, адрес: str
) -> None:
    # Стенд — УК: тенант стенда не должен доезжать ни до одной двери.
    with собрать(tenant="HQ").test_client() as client:
        войти(client)
        ответ = getattr(client, метод)(адрес, headers={"Origin": СВОЙ}, data={"reason": "x"})
    assert ответ.status_code == 404, ответ.data[:300]
    assert двери, "ни одна дверь чтения не позвана — проверка не дошла до границы"
    for имя, чем in двери:
        assert чем in (ОХВАТ_GE, "GE"), (имя, чем)
    assert not [имя for имя, _ in двери if имя in ("retract_card", "move_card")]


@pytest.mark.parametrize("адрес", ЗАДНИМ_ЧИСЛОМ)
def test_партнёру_снятие_и_перенос_закрыты_до_чтения(
    двери: list[tuple[str, Any]], адрес: str
) -> None:
    with собрать(tenant="HQ").test_client() as client:
        войти(client)
        ответ = client.post(адрес, headers={"Origin": СВОЙ}, data={"reason": "x"})
    assert ответ.status_code == 403, ответ.data[:300]
    assert двери == [], "партнёру снятие и перенос закрыты до любой двери (D341)"


def test_ответ_на_чужую_такой_же_как_на_несуществующую(двери: list[tuple[str, Any]]) -> None:
    with собрать(tenant="HQ").test_client() as client:
        войти(client)
        чужая = client.get(f"/inspections/{ЧУЖАЯ}")
        нет = client.get(f"/inspections/{НЕТ}")
    assert (чужая.status_code, чужая.data.replace(ЧУЖАЯ.encode(), b"")) == (
        нет.status_code,
        нет.data.replace(НЕТ.encode(), b""),
    )


@pytest.fixture
def уК_у_партнёра(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Вошёл админ УК; проверка в его охвате, но принадлежит пространству GE."""
    карточка = SimpleNamespace(inspection=SimpleNamespace(tenant_code="GE", id=ЧУЖАЯ))
    monkeypatch.setattr(data, "load_card", lambda *_a, **_k: карточка)
    monkeypatch.setattr(data, "retraction_available", lambda: True)
    записи: list[Any] = []
    for имя in ("retract_card", "move_card", "remember_letter"):
        monkeypatch.setattr(data, имя, lambda *a, _имя=имя, **k: записи.append((_имя, k)))
    подменить_двери(monkeypatch, tenant="HQ", role="admin")
    return записи


@pytest.mark.parametrize("адрес", ЗАПИСЬ)
def test_уК_читает_проверку_партнёра_но_запись_отказывает(
    уК_у_партнёра: list[Any], адрес: str
) -> None:
    with собрать(tenant="HQ").test_client() as client:
        войти(client)
        ответ = client.post(адрес, headers={"Origin": СВОЙ}, data={"reason": "x", "text": "письмо"})
    assert ответ.status_code == 403, ответ.data[:300]
    assert уК_у_партнёра == [], "дверь записи вызвана по проверке чужого пространства"
