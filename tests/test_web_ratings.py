"""Раздел «Рейтинги»: видят все, загружают и правят только контроль и админ УК (D319, D327)."""

from __future__ import annotations

import io
from collections.abc import Callable, Iterator
from datetime import datetime
from typing import Any

import pytest
from flask.testing import FlaskClient
from web_harness import войти, подменить_двери, собрать

from src.db.ratings_read import REFUSED_SETTING, RatingsEditError
from src.ratings import importer
from src.ratings.model import ERR_MISSING_COLUMNS, RatingsFormatError
from src.web import ratings as screen

ORIGIN = {"Origin": "http://localhost"}


@pytest.fixture
def зовы(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    журнал: dict[str, list[Any]] = {"import": [], "imports": []}

    def грузить(data: bytes, **kw: Any) -> importer.ImportReport:
        журнал["import"].append((data, kw))
        return importer.ImportReport(1, "rs-checkups", "loaded", accepted=2)

    def загрузки(*_: Any, **kw: Any) -> str:
        журнал["imports"].append(kw)
        return f"<p>загрузки {kw.get('notice') or ''}{kw.get('failure') or ''}</p>"

    monkeypatch.setattr(screen, "import_file", грузить)
    monkeypatch.setattr(screen, "render_summary", lambda *a, **k: "<p>сводка</p>")
    monkeypatch.setattr(screen, "render_imports", загрузки)
    return журнал


def _стенд(
    monkeypatch: pytest.MonkeyPatch, tenant: str, role: str, ui_lang: str = "ru"
) -> Iterator[FlaskClient]:
    подменить_двери(monkeypatch, tenant=tenant, role=role)
    with собрать(tenant=tenant, ui_lang=ui_lang).test_client() as client:
        assert войти(client).status_code == 302
        yield client


@pytest.mark.parametrize(
    ("tenant", "role"),
    [("GE", "admin"), ("GE", "auditor"), ("HQ", "auditor"), ("HQ", "control"), ("HQ", "admin")],
)
def test_сводку_видят_все(
    monkeypatch: pytest.MonkeyPatch, зовы: Any, tenant: str, role: str
) -> None:
    for client in _стенд(monkeypatch, tenant, role):
        assert client.get("/ratings").status_code == 200


# Форма — фабрика (P12): Werkzeug закрывает файл после запроса, второй прогон
# параметра с тем же BytesIO упал бы на закрытом файле.
ПРАВЯЩИЕ: list[tuple[str, str, Callable[[], dict[str, Any]]]] = [
    ("get", "/ratings/imports", dict),
    ("post", "/ratings/import", lambda: {"file": (io.BytesIO(b"x"), "f.csv")}),
    ("post", "/ratings/countries", lambda: {"code": "RS", "developer": "X"}),
    (
        "post",
        "/ratings/hard-rules",
        lambda: {"rating_type": "rko", "match": "text", "pattern": "X"},
    ),
    ("post", "/ratings/hard-rules/1/delete", dict),
    ("post", "/ratings/settings", lambda: {"top_threshold": "80"}),
]


@pytest.mark.parametrize(
    ("tenant", "role"), [("GE", "admin"), ("GE", "auditor"), ("HQ", "auditor")]
)
@pytest.mark.parametrize(("method", "path", "form"), ПРАВЯЩИЕ)
def test_загрузка_и_справочники_закрыты(
    monkeypatch: pytest.MonkeyPatch,
    зовы: Any,
    tenant: str,
    role: str,
    method: str,
    path: str,
    form: Callable[[], dict[str, Any]],
) -> None:
    for client in _стенд(monkeypatch, tenant, role):
        ответ = getattr(client, method)(path, data=form(), headers=ORIGIN)
        assert ответ.status_code == 403
    assert зовы["import"] == []
    assert зовы["imports"] == []


@pytest.mark.parametrize("role", ["control", "admin"])
def test_контроль_и_админ_уК_загружают(
    monkeypatch: pytest.MonkeyPatch, зовы: Any, role: str
) -> None:
    for client in _стенд(monkeypatch, "HQ", role):
        ответ = client.post(
            "/ratings/import", data={"file": (io.BytesIO(b"abc"), "rs.csv")}, headers=ORIGIN
        )
        assert ответ.status_code == 200
        assert client.get("/ratings/imports").status_code == 200
    ((data, kw),) = зовы["import"]
    assert data == b"abc" and kw["channel"] == "web" and kw["file_name"] == "rs.csv"


def test_больше_25_мб_отказ_413(monkeypatch: pytest.MonkeyPatch, зовы: Any) -> None:
    monkeypatch.setattr(screen, "UPLOAD_MAX_BYTES", 10)
    for client in _стенд(monkeypatch, "HQ", "control"):
        ответ = client.post(
            "/ratings/import",
            data={"file": (io.BytesIO(b"x" * 100_000), "big.csv")},
            headers=ORIGIN,
        )
        assert ответ.status_code == 413
    assert зовы["import"] == []


def test_чужой_origin_отказ(monkeypatch: pytest.MonkeyPatch, зовы: Any) -> None:
    for client in _стенд(monkeypatch, "HQ", "control"):
        ответ = client.post(
            "/ratings/import",
            data={"file": (io.BytesIO(b"x"), "f.csv")},
            headers={"Origin": "https://evil.example"},
        )
        assert ответ.status_code == 403
    assert зовы["import"] == []


# --- причины отказа — на языке интерфейса (P15), повтор и части (P26, P27) ---


def test_отказ_разбора_на_английском_без_русского(
    monkeypatch: pytest.MonkeyPatch, зовы: Any
) -> None:
    def отказ(*_: Any, **__: Any) -> importer.ImportReport:
        raise RatingsFormatError(
            "В файле rs-checkups нет колонок: Пиццерия",
            ERR_MISSING_COLUMNS,
            format="rs-checkups",
            columns="Пиццерия",
        )

    monkeypatch.setattr(screen, "import_file", отказ)
    for client in _стенд(monkeypatch, "HQ", "control", ui_lang="en"):
        ответ = client.post(
            "/ratings/import", data={"file": (io.BytesIO(b"x"), "f.csv")}, headers=ORIGIN
        )
        assert ответ.status_code == 400
    (kw,) = зовы["imports"]
    assert kw["failure"] == "File rejected: the rs-checkups file lacks columns: Пиццерия."


def test_повтор_файла_уже_загружен_с_датой(monkeypatch: pytest.MonkeyPatch, зовы: Any) -> None:
    def дубль(*_: Any, **__: Any) -> importer.ImportReport:
        return importer.ImportReport(
            7, "snapshot", "duplicate", loaded_at=datetime(2026, 10, 1, 9, 30), label="часть 2 из 3"
        )

    monkeypatch.setattr(screen, "import_file", дубль)
    for lang, ждём in (("ru", "уже загружен 01.10.2026 09:30"), ("en", "uploaded on 01.10.2026")):
        for client in _стенд(monkeypatch, "HQ", "control", ui_lang=lang):
            client.post(
                "/ratings/import", data={"file": (io.BytesIO(b"x"), "s.json")}, headers=ORIGIN
            )
        assert ждём in зовы["imports"][-1]["notice"]


def test_часть_снимка_подписана_на_языке_интерфейса(
    monkeypatch: pytest.MonkeyPatch, зовы: Any
) -> None:
    def часть(*_: Any, **__: Any) -> importer.ImportReport:
        return importer.ImportReport(
            8, "snapshot", "loaded", accepted=3, label="часть 2 из 3", chunk_index=2, chunk_of=3
        )

    monkeypatch.setattr(screen, "import_file", часть)
    for client in _стенд(monkeypatch, "HQ", "control", ui_lang="en"):
        client.post("/ratings/import", data={"file": (io.BytesIO(b"x"), "s.json")}, headers=ORIGIN)
    notice = зовы["imports"][-1]["notice"]
    assert "rating snapshot (part 2 of 3)" in notice and "часть" not in notice


def test_отказ_справочника_по_коду(monkeypatch: pytest.MonkeyPatch, зовы: Any) -> None:
    def отказ(*_: Any, **__: Any) -> None:
        raise RatingsEditError("Порог — от 0 до 100", REFUSED_SETTING)

    monkeypatch.setattr(screen.read, "set_setting", отказ)
    for client in _стенд(monkeypatch, "HQ", "control", ui_lang="en"):
        ответ = client.post("/ratings/settings", data={"top_threshold": "150"}, headers=ORIGIN)
        assert ответ.status_code == 400
        ответ = client.post("/ratings/settings", data={"top_threshold": "abc"}, headers=ORIGIN)
        assert ответ.status_code == 400
    for kw in зовы["imports"]:
        assert kw["failure"].startswith("Not saved: a threshold is 0 to 100")


def test_каждый_код_отказа_есть_на_обоих_языках() -> None:
    """Каждый код причины из ядра и базы — ключ `texts_ratings` на ru и en (P15)."""
    from src.db import ratings_read
    from src.ratings import model
    from src.web.texts import TEXTS

    коды = (
        {f"ratings.error.{v}" for k, v in vars(model).items() if k.startswith("ERR_")}
        | {f"ratings.issue.{v}" for k, v in vars(model).items() if k.startswith("ISSUE_")}
        | {
            f"ratings.refused.{v}"
            for k, v in vars(ratings_read).items()
            if k.startswith("REFUSED_")
        }
        | {f"ratings.format.{v}" for v in model.FORMATS}
    )
    assert len(коды) == 10 + 4 + 7 + 5
    for ключ in коды:
        assert set(TEXTS.get(ключ, {})) >= {"ru", "en"}, ключ
