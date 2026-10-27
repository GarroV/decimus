"""Кнопка «Обновить сейчас» у блока агрегаторов (D420): видят контроль и админ УК,
нажатие ставит ту же заявку, что Claude; остальным кнопки нет, адрес набранный
руками отвечает 403. Страница рендерится настоящая, данные подменены."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from flask.testing import FlaskClient
from web_harness import войти, подменить_двери, собрать

from src.db import agg_store
from src.db.agg_store import UpdateRequest
from src.db.errors import RatingsError
from src.db.ratings_read import CountryRow
from src.ratings import compare as rcompare
from src.ratings import report
from src.ratings.aggregators import queue
from src.ratings.periods import month_period
from src.ratings.summary import CountryLine, ViolationBlock
from src.web import ratings as screen
from src.web.ratings_risk import CombinedRisk
from src.web.texts import TEXTS

ORIGIN = {"Origin": "http://localhost"}
КНОПКА = "Обновить сейчас"
КНОПКА_EN = "Update now"


def _заявка(by: str = "anna") -> UpdateRequest:
    return UpdateRequest(1, datetime(2026, 10, 12, 9, 30, tzinfo=UTC), by, (), None, None, None)


@pytest.fixture
def страница(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Настоящий шаблон «Рейтингов» над пустой сводкой; состояние заявки — в словаре."""
    состояние: dict[str, Any] = {"открытая": None, "заявки": []}
    период = month_period(2026, 9)
    страна = CountryRow("RS", "Сербия", "Serbia", None, True, "CEE")
    пустой = ViolationBlock(0, 0, None, ())
    сводка = report.Summary(
        selection=report.Selection(report.GROUP_IMF, None, период),
        countries=("RS",),
        groups=(),
        lines=(),
        total=CountryLine("", None, None, None, None),
        previous=None,
        rko_cluster=пустой,
        rko_by_country={},
        rs_cluster=пустой,
        rs_by_country={},
        rs_top=(),
        rs_bottom=(),
        rs_hard=(),
        rko_top=(),
        rko_bottom=(),
        rko_hard=(),
        risk=(),
        risk_short=(),
        thresholds={"top_threshold": 80.0, "risk_threshold": 70.0, "risk_periods": 3.0},
        last_loaded={},
    )
    monkeypatch.setattr(
        screen.report,
        "select",
        lambda *_a, **_k: (
            сводка.selection,
            report.Choices((), (страна,), ()),
        ),
    )
    monkeypatch.setattr(screen.report, "build", lambda _s: сводка)
    monkeypatch.setattr(screen.rcompare, "build", lambda *_a: rcompare.Comparison((), ()))
    monkeypatch.setattr(screen.read, "layout_rows", lambda: (("aggregators", 0, True),))
    monkeypatch.setattr(screen.read, "period_months", lambda: ())
    monkeypatch.setattr(screen.read, "rko_periods", lambda: ())
    monkeypatch.setattr(screen, "_maps", lambda *_a: None)
    monkeypatch.setattr(screen, "_aggs", lambda *_a: None)
    monkeypatch.setattr(screen, "_unit_maps", lambda _u: {})
    monkeypatch.setattr(screen.ratings_freshness, "build", lambda *_a, **_k: None)
    # Плитка «Стабильно ниже порога» (D658) читает базу сама — здесь не нужна.
    monkeypatch.setattr(screen.ratings_risk, "build", lambda *_a, **_k: CombinedRisk((), ()))
    monkeypatch.setattr(agg_store, "load_states", lambda: ())
    monkeypatch.setattr(agg_store, "open_request", lambda: состояние["открытая"])

    def поставить(names: Any, *, by: str) -> tuple[UpdateRequest, bool]:
        if состояние["открытая"] is not None:
            return состояние["открытая"], False
        состояние["открытая"] = _заявка(by)
        состояние["заявки"].append((tuple(names), by))
        return состояние["открытая"], True

    monkeypatch.setattr(agg_store, "request_update", поставить)
    return состояние


def _клиенты(
    monkeypatch: pytest.MonkeyPatch, tenant: str, role: str, ui_lang: str = "ru"
) -> Iterator[FlaskClient]:
    подменить_двери(monkeypatch, tenant=tenant, role=role)
    with собрать(tenant=tenant, ui_lang=ui_lang).test_client() as client:
        assert войти(client).status_code == 302
        yield client


@pytest.mark.parametrize(("tenant", "role"), [("HQ", "control"), ("HQ", "admin")])
def test_кнопка_есть_у_контроля_и_админа_уК(
    monkeypatch: pytest.MonkeyPatch, страница: Any, tenant: str, role: str
) -> None:
    for client in _клиенты(monkeypatch, tenant, role):
        текст = client.get("/ratings").get_data(as_text=True)
        assert КНОПКА in текст and 'action="/ratings/aggregators/update' in текст


@pytest.mark.parametrize(
    ("tenant", "role"), [("GE", "admin"), ("GE", "auditor"), ("HQ", "auditor")]
)
def test_у_остальных_кнопки_нет_и_адрес_закрыт(
    monkeypatch: pytest.MonkeyPatch, страница: Any, tenant: str, role: str
) -> None:
    for client in _клиенты(monkeypatch, tenant, role):
        assert КНОПКА not in client.get("/ratings").get_data(as_text=True)
        ответ = client.post("/ratings/aggregators/update", headers=ORIGIN)
        assert ответ.status_code == 403
    assert страница["заявки"] == []


def test_нажатие_ставит_заявку_от_имени_учётки_и_возвращает_на_сводку(
    monkeypatch: pytest.MonkeyPatch, страница: Any
) -> None:
    for client in _клиенты(monkeypatch, "HQ", "control"):
        ответ = client.post(
            "/ratings/aggregators/update?group=country&value=RS&period=2026-09", headers=ORIGIN
        )
        assert ответ.status_code == 303
        куда = ответ.headers["Location"]
        assert куда.startswith("/ratings?") and "agg=queued" in куда
        assert "group=country" in куда and "period=2026-09" in куда  # срез не потерян
        после = client.get(куда).get_data(as_text=True)
    ((имена, кто),) = страница["заявки"]
    assert имена == () and кто  # все агрегаторы, автор — логин учётки
    assert "Заявка принята" in после
    # заявка стоит — вместо кнопки строка «в очереди», второй раз не просят
    assert КНОПКА not in после and "Обновление в очереди с 12.10.2026" in после


def test_повторное_нажатие_не_плодит_вторую(monkeypatch: pytest.MonkeyPatch, страница: Any) -> None:
    for client in _клиенты(monkeypatch, "HQ", "control"):
        client.post("/ratings/aggregators/update", headers=ORIGIN)
        ответ = client.post("/ratings/aggregators/update", headers=ORIGIN)
        assert "agg=already" in ответ.headers["Location"]
        assert "уже в очереди" in client.get(ответ.headers["Location"]).get_data(as_text=True)
    assert len(страница["заявки"]) == 1


def test_база_не_приняла_заявку_страница_говорит_об_этом(
    monkeypatch: pytest.MonkeyPatch, страница: Any
) -> None:
    def отказ(*_a: Any, **_k: Any) -> Any:
        raise RatingsError("база отказала")

    monkeypatch.setattr(agg_store, "request_update", отказ)
    for client in _клиенты(monkeypatch, "HQ", "control"):
        ответ = client.post("/ratings/aggregators/update", headers=ORIGIN)
        assert "agg=db_down" in ответ.headers["Location"]
        assert "База не приняла заявку" in client.get(ответ.headers["Location"]).get_data(
            as_text=True
        )


def test_чужой_origin_отказ(monkeypatch: pytest.MonkeyPatch, страница: Any) -> None:
    for client in _клиенты(monkeypatch, "HQ", "control"):
        ответ = client.post(
            "/ratings/aggregators/update", headers={"Origin": "https://evil.example"}
        )
        assert ответ.status_code == 403
    assert страница["заявки"] == []


def test_кнопка_на_английском(monkeypatch: pytest.MonkeyPatch, страница: Any) -> None:
    for client in _клиенты(monkeypatch, "HQ", "control", ui_lang="en"):
        текст = client.get("/ratings").get_data(as_text=True)
        assert КНОПКА_EN in текст and КНОПКА not in текст


def test_тексты_заявки_на_обоих_языках() -> None:
    ключи = [k for k in TEXTS if k.startswith("ratings.agg.update")]
    assert len(ключи) == 6
    for ключ in ключи:
        assert set(TEXTS[ключ]) >= {"ru", "en"}, ключ


def test_заявка_веба_и_claude_одна_и_та_же_функция() -> None:
    """Кнопка зовёт `queue.ask` — ту же, что инструмент MCP: правила очереди не двоятся."""
    ask: Callable[..., Any] = queue.ask
    assert screen.agg_queue.ask is ask
