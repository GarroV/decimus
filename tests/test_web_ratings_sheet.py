"""Блок «Таблица контроля» на «Загрузках» и кнопка «Забрать сейчас» (D464).

Видят и нажимают контроль и админ УК (те же, что загружают файлы); остальным адрес
отвечает 403. Страница рендерится настоящая, данные подменены. Сбой забора виден
строкой, а не тишиной — на обоих языках.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from flask.testing import FlaskClient
from web_harness import войти, подменить_двери, собрать

from src.db import ratings_sync as state
from src.db.errors import RatingsError
from src.ratings import sheet_sync
from src.web import ratings as screen
from src.web import ratings_sheet
from src.web.texts import TEXTS

ORIGIN = {"Origin": "http://localhost"}
КНОПКА = "Забрать сейчас"
В_12_ЧАСОВ = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)


def _лист(
    tab: str, outcome: str, *, note: str | None = None, counts: Any = None
) -> state.SyncState:
    return state.SyncState(tab, В_12_ЧАСОВ, outcome, "a" * 64, None, note, counts)


@pytest.fixture
def экран(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Настоящий шаблон «Загрузок»; состояние забора — в словаре, адрес таблицы задан."""
    данные: dict[str, Any] = {"состояние": (), "открытая": None, "заявки": []}
    monkeypatch.setenv(sheet_sync.SHEET_ID_VAR, "a" * 30)
    monkeypatch.setattr(screen.read, "countries", lambda: ())
    monkeypatch.setattr(screen.read, "imports", lambda: ())
    monkeypatch.setattr(screen.read, "open_issues", lambda: ())
    monkeypatch.setattr(screen.read, "hard_rules", lambda: ())
    monkeypatch.setattr(screen.read, "settings", dict)
    monkeypatch.setattr(screen.read, "layout_rows", lambda: ())
    monkeypatch.setattr(state, "states", lambda: данные["состояние"])
    monkeypatch.setattr(state, "open_request", lambda: данные["открытая"])

    def поставить(*, by: str) -> tuple[state.SyncRequest, bool]:
        if данные["открытая"] is not None:
            return данные["открытая"], False
        данные["открытая"] = state.SyncRequest(1, В_12_ЧАСОВ, by)
        данные["заявки"].append(by)
        return данные["открытая"], True

    monkeypatch.setattr(state, "request_sync", поставить)
    return данные


def _клиент(
    monkeypatch: pytest.MonkeyPatch, tenant: str, role: str, ui_lang: str = "ru"
) -> Iterator[FlaskClient]:
    подменить_двери(monkeypatch, tenant=tenant, role=role)
    with собрать(tenant=tenant, ui_lang=ui_lang).test_client() as client:
        assert войти(client).status_code == 302
        yield client


def test_без_адреса_таблицы_блок_говорит_что_забор_выключен(
    monkeypatch: pytest.MonkeyPatch, экран: Any
) -> None:
    monkeypatch.delenv(sheet_sync.SHEET_ID_VAR)
    for client in _клиент(monkeypatch, "HQ", "control"):
        текст = client.get("/ratings/imports").get_data(as_text=True)
        assert "самозабор выключен" in текст and КНОПКА not in текст


def test_ещё_не_забирали_кнопка_есть(monkeypatch: pytest.MonkeyPatch, экран: Any) -> None:
    for client in _клиент(monkeypatch, "HQ", "admin"):
        текст = client.get("/ratings/imports").get_data(as_text=True)
        assert "Таблицу ещё не забирали" in текст and КНОПКА in текст
        assert 'action="/ratings/sheet-sync' in текст


def test_итог_по_листам_время_счётчики_и_причина_сбоя(
    monkeypatch: pytest.MonkeyPatch, экран: Any
) -> None:
    экран["состояние"] = (
        _лист("base-scores", "loaded", counts=(5, 2, 100, 1)),
        _лист("base-collection", "unchanged"),
        _лист("base-rs-violations", "failed", note="closed: таблица закрыта"),
    )
    for client in _клиент(monkeypatch, "HQ", "control"):
        текст = client.get("/ratings/imports").get_data(as_text=True)
    assert "Последний заход по таблице: 13.10.2026 12:00" in текст
    assert "5 · 2 · 100 · 1" in текст and "без изменений" in текст
    assert "Не удалось забрать листов: 1 из 3" in текст
    assert "таблица закрыта: вместо листа пришла страница входа" in текст


def test_сбой_на_английском_без_русской_подробности(
    monkeypatch: pytest.MonkeyPatch, экран: Any
) -> None:
    экран["состояние"] = (_лист("base-scores", "failed", note="header: в файле нет колонок: Балл"),)
    for client in _клиент(monkeypatch, "HQ", "control", ui_lang="en"):
        текст = client.get("/ratings/imports").get_data(as_text=True)
    assert "Could not pull 1 of 1 sheets" in текст
    assert "the sheet header changed" in текст and "нет колонок" not in текст


def test_нажатие_ставит_заявку_и_возвращает_на_загрузки(
    monkeypatch: pytest.MonkeyPatch, экран: Any
) -> None:
    for client in _клиент(monkeypatch, "HQ", "control"):
        ответ = client.post("/ratings/sheet-sync", headers=ORIGIN)
        assert ответ.status_code == 303
        assert ответ.headers["Location"] == "/ratings/imports?sheet=queued"
        после = client.get(ответ.headers["Location"]).get_data(as_text=True)
    assert len(экран["заявки"]) == 1
    assert "Заявка принята" in после and "Заявка в очереди с 13.10.2026" in после
    assert КНОПКА not in после


def test_повторное_нажатие_не_плодит_вторую(monkeypatch: pytest.MonkeyPatch, экран: Any) -> None:
    for client in _клиент(monkeypatch, "HQ", "control"):
        client.post("/ratings/sheet-sync", headers=ORIGIN)
        ответ = client.post("/ratings/sheet-sync", headers=ORIGIN)
        assert ответ.headers["Location"].endswith("sheet=already")
    assert len(экран["заявки"]) == 1


def test_база_не_приняла_заявку_страница_говорит_об_этом(
    monkeypatch: pytest.MonkeyPatch, экран: Any
) -> None:
    def отказ(**_: Any) -> Any:
        raise RatingsError("база отказала")

    monkeypatch.setattr(state, "request_sync", отказ)
    for client in _клиент(monkeypatch, "HQ", "control"):
        ответ = client.post("/ratings/sheet-sync", headers=ORIGIN)
        assert ответ.headers["Location"].endswith("sheet=db_down")
        assert "База не приняла заявку" in client.get(ответ.headers["Location"]).get_data(
            as_text=True
        )


def test_состояние_не_прочиталось_блок_не_врёт(monkeypatch: pytest.MonkeyPatch, экран: Any) -> None:
    def отказ() -> Any:
        raise RatingsError("база отказала")

    monkeypatch.setattr(state, "states", отказ)
    for client in _клиент(monkeypatch, "HQ", "control"):
        текст = client.get("/ratings/imports").get_data(as_text=True)
    assert "Состояние забора таблицы не прочиталось" in текст and КНОПКА not in текст


@pytest.mark.parametrize(
    ("tenant", "role"), [("GE", "admin"), ("GE", "auditor"), ("HQ", "auditor")]
)
def test_остальным_адрес_закрыт(
    monkeypatch: pytest.MonkeyPatch, экран: Any, tenant: str, role: str
) -> None:
    for client in _клиент(monkeypatch, tenant, role):
        assert client.post("/ratings/sheet-sync", headers=ORIGIN).status_code == 403
    assert экран["заявки"] == []


def test_чужой_origin_отказ(monkeypatch: pytest.MonkeyPatch, экран: Any) -> None:
    for client in _клиент(monkeypatch, "HQ", "control"):
        ответ = client.post("/ratings/sheet-sync", headers={"Origin": "https://evil.example"})
        assert ответ.status_code == 403
    assert экран["заявки"] == []


def test_причина_без_кода_и_с_неизвестным_кодом() -> None:
    assert ratings_sheet.reason(None, "ru") is None
    assert ratings_sheet.reason("что-то странное", "en") == TEXTS["ratings.sheet.err.unknown"]["en"]


def test_тексты_блока_на_обоих_языках() -> None:
    ключи = [k for k in TEXTS if k.startswith("ratings.sheet.") or k == "ratings.channel.sync"]
    assert "ratings.sheet.now" in ключи
    for ключ in ключи:
        assert set(TEXTS[ключ]) >= {"ru", "en"}, ключ
    for код in (
        sheet_sync.ERR_CLOSED,
        sheet_sync.ERR_HTTP,
        sheet_sync.ERR_NETWORK,
        sheet_sync.ERR_TOO_BIG,
        sheet_sync.ERR_HEADER,
        sheet_sync.ERR_DB,
        sheet_sync.ERR_BAD_ID,
    ):
        assert f"ratings.sheet.err.{код}" in TEXTS, код
