"""Карточка проверки: вопросы информационной части и выдача PDF (D204, #317).

Замечание владельца 28.09: «не ясно что да? что нет? какие вопросы то были?»
и «не вижу возможности скачать пдф с проверкой». Здесь проверяется то, что
видит человек: вопрос стоит рядом с ответом, кнопка есть только при
сохранённом отчёте, и файл отдаётся тем, что лежит в хранилище.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from flask.testing import FlaskClient
from test_web_app import ТЕНАНТ, карточка, шапка
from web_harness import войти, подменить_двери, собрать

from src.db.errors import StorageError
from src.db.models import InfoRow
from src.db.previews import FindingShots
from src.db.reports import ReportRef
from src.report.info_titles import FOUND, NOT_AT_HAND
from src.web import inspections as data

ПРОВЕРКА = "11111111-1111-1111-1111-111111111111"
ОТЧЁТ = b"%PDF-1.7\nreport of this very inspection\n%%EOF\n"
ССЫЛКА = ReportRef(
    storage_path=f"s3://inspection-frames/inspections/{ПРОВЕРКА}/reports/abc.pdf",
    content_type="application/pdf",
    size_bytes=len(ОТЧЁТ),
    created_at=datetime(2026, 9, 27, tzinfo=UTC),
)
ПОЛЯ = (InfoRow(code="INF03", text="Да"), InfoRow(code="INF04", text="Нет"))
ВОПРОСЫ = {"INF03": "Is the team stable?"}


def _стенд(monkeypatch: pytest.MonkeyPatch, *, report: ReportRef | None) -> Iterator[FlaskClient]:
    monkeypatch.setattr(data, "retraction_available", lambda: False)
    monkeypatch.setattr(data, "load_card", lambda *_a, **_k: карточка(шапка(), info=ПОЛЯ))
    monkeypatch.setattr(data, "load_moves", lambda *_a, **_k: ())
    monkeypatch.setattr(data, "load_report", lambda *_a, **_k: report)
    monkeypatch.setattr(
        data,
        "ensure_report",
        lambda detail, **kwargs: data.load_report(detail.inspection.id, **kwargs),
    )
    monkeypatch.setattr(data, "report_bytes", lambda _ref: ОТЧЁТ)
    monkeypatch.setattr(data, "load_previews", lambda *_a, **_k: {})
    monkeypatch.setattr(data.info_titles, "titles", lambda *_a, **_k: (ВОПРОСЫ, FOUND))
    подменить_двери(monkeypatch, tenant=ТЕНАНТ)
    with собрать(tenant=ТЕНАНТ).test_client() as client:
        assert войти(client).status_code == 302
        yield client


@pytest.fixture
def с_отчётом(monkeypatch: pytest.MonkeyPatch) -> Iterator[FlaskClient]:
    yield from _стенд(monkeypatch, report=ССЫЛКА)


@pytest.fixture
def без_отчёта(monkeypatch: pytest.MonkeyPatch) -> Iterator[FlaskClient]:
    yield from _стенд(monkeypatch, report=None)


def test_вопрос_стоит_рядом_с_ответом(с_отчётом: FlaskClient) -> None:
    html = с_отчётом.get(f"/inspections/{ПРОВЕРКА}?lang=en").get_data(as_text=True)
    вопрос = html.index("Is the team stable?")
    # Ответ идёт сразу за своим вопросом, а не отдельным столбиком кодов.
    assert вопрос < html.index("Да", вопрос) < html.index("INF04")


def test_вопроса_нет_в_методике_сказано_словами(с_отчётом: FlaskClient) -> None:
    html = с_отчётом.get(f"/inspections/{ПРОВЕРКА}?lang=en").get_data(as_text=True)
    assert "The question wording is not in this inspection&#39;s methodology" in html


def test_нет_методики_версии_сказано_и_вопросы_не_подставлены(
    с_отчётом: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(data.info_titles, "titles", lambda *_a, **_k: ({}, NOT_AT_HAND))
    html = с_отчётом.get(f"/inspections/{ПРОВЕРКА}?lang=en").get_data(as_text=True)
    assert "is not on the server" in html
    assert "Is the team stable?" not in html


def test_кнопка_pdf_есть_при_сохранённом_отчёте(с_отчётом: FlaskClient) -> None:
    html = с_отчётом.get(f"/inspections/{ПРОВЕРКА}?lang=en").get_data(as_text=True)
    assert f"/inspections/{ПРОВЕРКА}/report" in html
    # D554: значок — «скачать» (стрелка над полкой), а не лист, похожий на «документ».
    кнопка = html.split(f"/inspections/{ПРОВЕРКА}/report", 1)[1].split("</a>", 1)[0]
    assert "M10 3.5v9M6.5 9l3.5 3.5L13.5 9M4 16.5h12" in кнопка


def test_кнопки_pdf_нет_без_отчёта_и_сказано_почему(без_отчёта: FlaskClient) -> None:
    html = без_отчёта.get(f"/inspections/{ПРОВЕРКА}?lang=en").get_data(as_text=True)
    assert f"/inspections/{ПРОВЕРКА}/report" not in html
    assert "PDF is not stored" in html


def test_отчёт_отдаётся_файлом_тем_самым(с_отчётом: FlaskClient) -> None:
    ответ = с_отчётом.get(f"/inspections/{ПРОВЕРКА}/report")
    assert ответ.status_code == 200
    assert ответ.mimetype == "application/pdf"
    assert ответ.data == ОТЧЁТ
    заголовок = ответ.headers["Content-Disposition"]
    assert заголовок.startswith("attachment")
    assert "2026-09-18.pdf" in заголовок


def test_нет_отчёта_404_и_причина(без_отчёта: FlaskClient) -> None:
    ответ = без_отчёта.get(f"/inspections/{ПРОВЕРКА}/report?lang=en")
    assert ответ.status_code == 404
    assert "PDF is not stored" in ответ.get_data(as_text=True)


def test_хранилище_отказало_503_а_не_пустой_файл(
    с_отчётом: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def отказ(_ref: ReportRef) -> bytes:
        raise StorageError("storage down")

    monkeypatch.setattr(data, "report_bytes", отказ)
    ответ = с_отчётом.get(f"/inspections/{ПРОВЕРКА}/report?lang=en")
    assert ответ.status_code == 503
    assert "could not be served" in ответ.get_data(as_text=True)


def test_чужой_проверки_нет_и_файла_нет(
    с_отчётом: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(data, "load_card", lambda *_a, **_k: None)
    ответ = с_отчётом.get(f"/inspections/{ПРОВЕРКА}/report")
    assert ответ.status_code == 404
    assert ответ.data != ОТЧЁТ


КАДР = "22222222-2222-2222-2222-222222222222"
КОПИЯ = b"\xff\xd8\xff preview jpeg bytes"


def _с_кадрами(monkeypatch: pytest.MonkeyPatch, клиент: FlaskClient, находка: str) -> None:
    monkeypatch.setattr(
        data, "load_previews", lambda *_a, **_k: {находка: FindingShots(shown=(КАДР,), missing=0)}
    )


def test_запись_с_кадрами_раскрывается_и_показывает_копию(
    с_отчётом: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    находка = карточка(шапка()).findings[0].id
    _с_кадрами(monkeypatch, с_отчётом, находка)
    html = с_отчётом.get(f"/inspections/{ПРОВЕРКА}?lang=en").get_data(as_text=True)
    assert "find-row--photos" in html
    assert f"/inspections/{ПРОВЕРКА}/photos/{КАДР}" in html
    assert "Photos: 1" in html


def test_кадр_записи_раскрывается_на_месте_а_не_в_новой_вкладке(
    с_отчётом: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D534: ссылка на кадр без target=_blank, со скриптом раскрытия."""
    находка = карточка(шапка()).findings[0].id
    _с_кадрами(monkeypatch, с_отчётом, находка)
    html = с_отчётом.get(f"/inspections/{ПРОВЕРКА}?lang=en").get_data(as_text=True)
    ссылки = re.findall(r"<a [^>]*/photos/[^>]*>", html)
    assert ссылки and all("data-zoom" in a and "_blank" not in a for a in ссылки)
    assert "photo-zoom.js" in html


def test_без_кадров_раскрытия_нет(с_отчётом: FlaskClient) -> None:
    html = с_отчётом.get(f"/inspections/{ПРОВЕРКА}?lang=en").get_data(as_text=True)
    assert "find-row--photos" not in html
    assert "Photos unavailable" not in html


def test_кадры_без_копии_названы_а_не_пропали(
    с_отчётом: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#422: кадры были, показать нечем — запись говорит об этом, а не выглядит пустой."""
    находка = карточка(шапка()).findings[0].id
    monkeypatch.setattr(
        data, "load_previews", lambda *_a, **_k: {находка: FindingShots(shown=(), missing=2)}
    )
    html = с_отчётом.get(f"/inspections/{ПРОВЕРКА}?lang=en").get_data(as_text=True)
    assert "Photos unavailable: 2" in html
    # Раскрывать нечего — раскрытия нет.
    assert "find-row--photos" not in html


def test_часть_кадров_без_копии_показана_рядом_с_остальными(
    с_отчётом: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    находка = карточка(шапка()).findings[0].id
    monkeypatch.setattr(
        data, "load_previews", lambda *_a, **_k: {находка: FindingShots(shown=(КАДР,), missing=1)}
    )
    html = с_отчётом.get(f"/inspections/{ПРОВЕРКА}?lang=ru").get_data(as_text=True)
    assert "find-row--photos" in html
    assert f"/inspections/{ПРОВЕРКА}/photos/{КАДР}" in html
    # Видно уже в свёрнутой строке, а не только под раскрытием.
    assert "Фото: 1 · недоступно: 1" in html


def test_копия_кадра_отдаётся_картинкой_и_не_в_общий_кэш(
    с_отчётом: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(data, "preview_bytes", lambda *_a, **_k: КОПИЯ)
    ответ = с_отчётом.get(f"/inspections/{ПРОВЕРКА}/photos/{КАДР}")
    assert ответ.status_code == 200
    assert ответ.mimetype == "image/jpeg"
    assert ответ.data == КОПИЯ
    assert ответ.headers["Cache-Control"].startswith("private")


def test_чужой_или_несуществующий_кадр_404(
    с_отчётом: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(data, "preview_bytes", lambda *_a, **_k: None)
    assert с_отчётом.get(f"/inspections/{ПРОВЕРКА}/photos/{КАДР}").status_code == 404
    # Не идентификатор — 404 до базы, а не отказ разбора в ней.
    assert с_отчётом.get(f"/inspections/{ПРОВЕРКА}/photos/../../etc").status_code == 404
    assert с_отчётом.get(f"/inspections/{ПРОВЕРКА}/photos/not-a-uuid").status_code == 404


def test_повторное_открытие_отчёта_не_читает_хранилище(
    с_отчётом: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#697: метка совпала — 304 без чтения файла; чтение хранилища ~300 мс."""
    первый = с_отчётом.get(f"/inspections/{ПРОВЕРКА}/report")
    метка = первый.headers["ETag"]
    assert первый.headers["Cache-Control"] == "private, no-cache"

    def нельзя(_ref: ReportRef) -> bytes:
        raise AssertionError("хранилище прочитано при совпавшей метке")

    monkeypatch.setattr(data, "report_bytes", нельзя)
    второй = с_отчётом.get(f"/inspections/{ПРОВЕРКА}/report", headers={"If-None-Match": метка})
    assert второй.status_code == 304
    assert второй.data == b""


def test_новый_отчёт_новая_метка(с_отчётом: FlaskClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Финальный отчёт после приёмки (D203) не прячется за меткой черновика."""
    метка = с_отчётом.get(f"/inspections/{ПРОВЕРКА}/report").headers["ETag"]
    новый = ReportRef(
        storage_path=f"s3://inspection-frames/inspections/{ПРОВЕРКА}/reports/def.pdf",
        content_type="application/pdf",
        size_bytes=len(ОТЧЁТ),
        created_at=datetime(2026, 9, 28, tzinfo=UTC),
    )
    monkeypatch.setattr(data, "load_report", lambda *_a, **_k: новый)
    ответ = с_отчётом.get(f"/inspections/{ПРОВЕРКА}/report", headers={"If-None-Match": метка})
    assert ответ.status_code == 200
    assert ответ.data == ОТЧЁТ
