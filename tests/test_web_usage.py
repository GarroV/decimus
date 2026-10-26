"""Экран «Расход модели» (D537): кто его видит и что на нём. База подменена на границе.

Права — ядро: расход видят главный админ и админ УК, всем остальным вкладки нет и адрес
отвечает 404, причём страница даже не спрашивает базу. Настоящее чтение с заслоном по
сессии — `tests/test_db_model_usage.py` (нужна живая база).
"""

from __future__ import annotations

import pytest
from web_harness import войти, подменить_двери, собрать

from src.db import model_usage
from src.db.errors import AccessError
from src.db.model_usage import UsageRow


def _вошедший(monkeypatch: pytest.MonkeyPatch, *, role: str, tenant: str = "HQ") -> object:
    подменить_двери(monkeypatch, tenant=tenant, role=role)
    client = собрать(tenant=tenant).test_client()
    assert войти(client).status_code == 302
    return client


def _строки() -> tuple[UsageRow, ...]:
    return (
        UsageRow("day", "2026-10-02", "", "gpt-5.6-sol", 3, 1, 2_000_000, 500_000, 0.0),
        UsageRow("kind", "recognize", "", "gpt-5.6-sol", 2, 0, 1_900_000, 400_000, 0.0),
        UsageRow("kind", "transcribe", "", "gpt-4o-mini-transcribe", 1, 1, 100_000, 100_000, 0.0),
        UsageRow("person", "u1", "anna", "gpt-5.6-sol", 3, 1, 2_000_000, 500_000, 0.0),
        UsageRow(
            "inspection",
            "8f1c2a34-1111-4222-8333-444455556666",
            "Тбилиси-1 · 2026-10-02",
            "gpt-5.6-sol",
            3,
            1,
            2_000_000,
            500_000,
            0.0,
        ),
        UsageRow("inspection", "run-abc", "", "gpt-5.6-sol", 1, 0, 10, 10, 0.0),
        UsageRow("person", "", "", "gpt-6-luna", 1, 0, 10, 10, 0.0),
    )


def _заглушка(monkeypatch: pytest.MonkeyPatch) -> list[tuple[object, ...]]:
    спросили: list[tuple[object, ...]] = []

    def _read(token: str, *, start: object = None, end: object = None) -> tuple[UsageRow, ...]:
        спросили.append((token, start, end))
        return _строки() if len(спросили) == 1 else ()

    monkeypatch.setattr(model_usage, "read", _read)
    return спросили


@pytest.mark.parametrize("роль", ["superadmin", "admin"])
def test_админ_ук_видит_расход_с_итогами_срезами_и_оценкой(
    monkeypatch: pytest.MonkeyPatch, роль: str
) -> None:
    client = _вошедший(monkeypatch, role=роль)
    спросили = _заглушка(monkeypatch)

    ответ = client.get("/administration?tab=usage&from=2026-10-01&to=2026-10-31")  # type: ignore[attr-defined]

    assert ответ.status_code == 200
    страница = ответ.get_data(as_text=True)
    assert "Расход модели" in страница
    assert "2 500 000" in страница, "итог токенов не показан"
    # 2.0M * $4 + 0.5M * $20 = $18
    assert "$18.00" in страница
    assert "оценка" in страница
    assert "Распознавание записи" in страница and "anna" in страница
    # Проверка названа пиццерией и датой и ведёт на карточку; сырых номеров на экране нет.
    assert "Тбилиси-1 · 2026-10-02" in страница
    assert 'href="/inspections/8f1c2a34-1111-4222-8333-444455556666' in страница
    assert "run-abc" not in страница and "проверка в боте, не сдана" in страница
    assert "вызов без человека" in страница
    assert "Расшифровка голосового" in страница
    assert 'href="/administration?tab=usage"' in страница, "вкладки в экране нет"
    # Текущий и прошлый период: два чтения, период уходит границами суток.
    assert len(спросили) == 2


def test_столбик_дня_несёт_подсказку_с_датой_токенами_вызовами_и_ценой(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _вошедший(monkeypatch, role="superadmin")
    _заглушка(monkeypatch)

    ответ = client.get("/administration?tab=usage&from=2026-10-01&to=2026-10-31")  # type: ignore[attr-defined]

    страница = ответ.get_data(as_text=True)
    assert страница.count('class="ubars__item') == 31
    assert 'tabindex="0"' in страница, "столбик не берёт фокус с клавиатуры"
    подсказка = страница.split('<b class="ubars__tipday">2 окт</b>', 1)[1].split("</li>", 1)[0]
    assert "2\xa0500\xa0000" in подсказка, "токенов дня в подсказке нет"
    assert "вход 2\xa0000\xa0000 · выход 500\xa0000" in подсказка
    assert "Вызовов: <b" in подсказка and ">3</b>" in подсказка
    assert "$18.00" in подсказка, "стоимости дня в подсказке нет"
    assert "нет вызовов" in страница, "у пустого дня подсказки нет"
    assert "наибольший день: 2,5 млн токенов" in страница, "ось без максимума"


@pytest.mark.parametrize(
    ("роль", "tenant"),
    [
        ("auditor", "HQ"),
        ("control", "HQ"),
        ("guest", "HQ"),
        ("developer", "HQ"),
        ("admin", "rs"),
        ("auditor", "rs"),
    ],
)
def test_остальным_вкладки_нет_адрес_404_база_не_спрошена(
    monkeypatch: pytest.MonkeyPatch, роль: str, tenant: str
) -> None:
    client = _вошедший(monkeypatch, role=роль, tenant=tenant)
    спросили = _заглушка(monkeypatch)

    ответ = client.get("/administration?tab=usage")  # type: ignore[attr-defined]
    главная = client.get("/administration?tab=people")  # type: ignore[attr-defined]

    assert ответ.status_code == 404
    assert спросили == [], "страница спросила расход у не-админа"
    assert "tab=usage" not in главная.get_data(as_text=True), "вкладка видна не админу УК"


def test_без_цены_модели_показаны_токены_без_суммы(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _вошедший(monkeypatch, role="superadmin")
    rows = (UsageRow("day", "2026-10-02", "", "неизвестная-модель", 1, 0, 1000, 10, 0.0),)
    monkeypatch.setattr(model_usage, "read", lambda token, **kw: rows)

    страница = client.get("/administration?tab=usage").get_data(as_text=True)  # type: ignore[attr-defined]

    assert "1 010" in страница
    assert "цены модели нет в прейскуранте" in страница


def test_пустой_период_говорит_что_вызовов_нет(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _вошедший(monkeypatch, role="superadmin")
    monkeypatch.setattr(model_usage, "read", lambda token, **kw: ())

    ответ = client.get("/administration?tab=usage")  # type: ignore[attr-defined]

    assert ответ.status_code == 200
    assert "За этот период вызовов нет" in ответ.get_data(as_text=True)


def test_сбой_базы_это_ошибка_а_не_пустота(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _вошедший(monkeypatch, role="superadmin")

    def упала(*_: object, **__: object) -> tuple[()]:
        raise AccessError("не удалось")

    monkeypatch.setattr(model_usage, "read", упала)

    ответ = client.get("/administration?tab=usage")  # type: ignore[attr-defined]

    assert ответ.status_code == 503
    assert "Расход не прочитан" in ответ.get_data(as_text=True)


def test_английский_интерфейс(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _вошедший(monkeypatch, role="superadmin")
    _заглушка(monkeypatch)

    страница = client.get("/administration?tab=usage&lang=en").get_data(as_text=True)  # type: ignore[attr-defined]

    assert "Model usage" in страница and "Recognising a record" in страница
    assert "estimate" in страница
