"""Скачивание листа общей таблицы (D464): настройка, закрытая таблица, коды ответа.

Сеть не трогаем: `urlopen` подменён. Закрытая таблица Google отдаёт страницу входа с
кодом 200 — это главный тихий отказ, поэтому он проверяется отдельно.
"""

from __future__ import annotations

import urllib.error
from collections.abc import Callable
from email.message import Message
from io import BytesIO
from typing import Any

import pytest

from src.ratings import sheet_sync
from src.ratings.sheet_sync import SyncError

SHEET = "a" * 30


class _Response(BytesIO):
    def __init__(self, body: bytes, content_type: str) -> None:
        super().__init__(body)
        self.headers = Message()
        self.headers["Content-Type"] = content_type

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def _serve(monkeypatch: pytest.MonkeyPatch, answer: Callable[[Any], Any]) -> list[str]:
    asked: list[str] = []

    def urlopen(request: Any, timeout: float) -> Any:
        asked.append(request.full_url)
        return answer(request)

    monkeypatch.setattr(sheet_sync.urllib.request, "urlopen", urlopen)
    return asked


def test_лист_скачивается_по_адресу_и_номеру(monkeypatch: pytest.MonkeyPatch) -> None:
    asked = _serve(monkeypatch, lambda _: _Response(b"a,b\r\n1,2\r\n", "text/csv; charset=utf-8"))
    assert sheet_sync.fetch_sheet(SHEET, 42) == b"a,b\r\n1,2\r\n"
    assert asked == [f"https://docs.google.com/spreadsheets/d/{SHEET}/export?format=csv&gid=42"]


def test_закрытая_таблица_страница_входа_с_кодом_200(monkeypatch: pytest.MonkeyPatch) -> None:
    _serve(monkeypatch, lambda _: _Response(b"<!DOCTYPE html><html>", "text/html"))
    with pytest.raises(SyncError) as err:
        sheet_sync.fetch_sheet(SHEET, 0)
    assert err.value.code == sheet_sync.ERR_CLOSED


def test_html_под_видом_csv_тоже_закрытая(monkeypatch: pytest.MonkeyPatch) -> None:
    _serve(monkeypatch, lambda _: _Response(b"  <html>", "text/csv"))
    with pytest.raises(SyncError) as err:
        sheet_sync.fetch_sheet(SHEET, 0)
    assert err.value.code == sheet_sync.ERR_CLOSED


@pytest.mark.parametrize("code", [403, 404, 500])
def test_код_ответа_не_200_причина_с_кодом(monkeypatch: pytest.MonkeyPatch, code: int) -> None:
    def refuse(request: Any) -> Any:
        raise urllib.error.HTTPError(request.full_url, code, "x", Message(), None)

    _serve(monkeypatch, refuse)
    with pytest.raises(SyncError, match=str(code)) as err:
        sheet_sync.fetch_sheet(SHEET, 0)
    assert err.value.code == sheet_sync.ERR_HTTP


def test_нет_связи_причина_сеть(monkeypatch: pytest.MonkeyPatch) -> None:
    def down(_: Any) -> Any:
        raise urllib.error.URLError("нет сети")

    _serve(monkeypatch, down)
    with pytest.raises(SyncError) as err:
        sheet_sync.fetch_sheet(SHEET, 0)
    assert err.value.code == sheet_sync.ERR_NETWORK


def test_лист_больше_предела_отказ(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sheet_sync, "MAX_SHEET_BYTES", 10)
    _serve(monkeypatch, lambda _: _Response(b"x" * 11, "text/csv"))
    with pytest.raises(SyncError) as err:
        sheet_sync.fetch_sheet(SHEET, 0)
    assert err.value.code == sheet_sync.ERR_TOO_BIG


def test_настройка_не_задана_и_негодная() -> None:
    assert sheet_sync.sheet_id({}) is None
    assert sheet_sync.sheet_id({"RATINGS_SHEET_ID": "  "}) is None
    assert sheet_sync.sheet_id({"RATINGS_SHEET_ID": f" {SHEET} "}) == SHEET
    for bad in ("короткий", "a" * 30 + "/../x", "a" * 30 + "?x=1"):
        with pytest.raises(SyncError) as err:
            sheet_sync.sheet_id({"RATINGS_SHEET_ID": bad})
        assert err.value.code == sheet_sync.ERR_BAD_ID


def test_без_настройки_забор_отказывает_до_сети() -> None:
    with pytest.raises(SyncError) as err:
        sheet_sync.run(env={}, fetch=lambda *_: pytest.fail("в сеть ходить нельзя"))
    assert err.value.code == sheet_sync.ERR_NOT_CONFIGURED
