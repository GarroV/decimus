"""Плитки раздела «Рейтинги» (D585): хард-нарушения — два столбца по десять строк,
дальше «Показать ещё»; `?open=` раскрывает названную плитку; агрегаторы — своя
плитка. Страница рендерится настоящая, данные подменены."""

from __future__ import annotations

import re
from collections.abc import Iterator

import pytest
from flask.testing import FlaskClient
from web_harness import войти, подменить_двери, собрать

from src.db.ratings_read import CountryRow
from src.ratings import compare as rcompare
from src.ratings import layout as rl
from src.ratings import report
from src.ratings import risk_sources as rsrc
from src.ratings.periods import month_period
from src.ratings.summary import CountryLine, ViolationBlock, ViolationFact
from src.web import ratings as screen
from src.web import ratings_tiles
from src.web.ratings_risk import CombinedRisk


def _факты(n: int) -> tuple[ViolationFact, ...]:
    return tuple(
        ViolationFact(f"u{i}", f"Пиццерия {i}", "RS", f"Нарушение {i}", None, "hard", 1)
        for i in range(n)
    )


def _страница(monkeypatch: pytest.MonkeyPatch, нарушений: int) -> None:
    период = month_period(2026, 9)
    есть_данные = ViolationBlock(3, 3, 1.0, ())
    сводка = report.Summary(
        selection=report.Selection(report.GROUP_IMF, None, период),
        countries=("RS",),
        groups=(),
        lines=(),
        total=CountryLine("", 91.0, 88.0, None, None),
        previous=None,
        rko_cluster=есть_данные,
        rko_by_country={},
        rs_cluster=есть_данные,
        rs_by_country={},
        rs_top=(),
        rs_bottom=(),
        rs_hard=_факты(нарушений),
        rko_top=(),
        rko_bottom=(),
        rko_hard=(),
        risk=(),
        risk_short=(),
        thresholds={"top_threshold": 80.0, "risk_threshold": 70.0, "risk_periods": 3.0},
        last_loaded={},
    )
    страна = CountryRow("RS", "Сербия", "Serbia", None, True, "CEE")
    monkeypatch.setattr(
        screen.report,
        "select",
        lambda *_a, **_k: (сводка.selection, report.Choices((), (страна,), ())),
    )
    monkeypatch.setattr(screen.report, "build", lambda _s: сводка)
    monkeypatch.setattr(screen.rcompare, "build", lambda *_a: rcompare.Comparison((), ()))
    monkeypatch.setattr(screen.read, "layout_rows", lambda: ())
    monkeypatch.setattr(screen.read, "period_months", lambda: ())
    monkeypatch.setattr(screen.read, "rko_periods", lambda: ())
    monkeypatch.setattr(screen, "_maps", lambda *_a: None)
    monkeypatch.setattr(screen, "_aggs", lambda *_a: None)
    monkeypatch.setattr(screen, "_unit_maps", lambda _u: {})
    monkeypatch.setattr(screen, "_agg_failures", lambda: ())
    monkeypatch.setattr(screen, "_agg_pending", lambda: None)
    monkeypatch.setattr(screen.ratings_risk, "build", lambda *_a, **_k: CombinedRisk((), ()))
    monkeypatch.setattr(screen.ratings_freshness, "read_rows", lambda now: ())


def _клиент(monkeypatch: pytest.MonkeyPatch, ui_lang: str = "ru") -> Iterator[FlaskClient]:
    подменить_двери(monkeypatch, tenant="HQ", role="admin")
    with собрать(tenant="HQ", ui_lang=ui_lang).test_client() as client:
        assert войти(client).status_code == 302
        yield client


def _получить(monkeypatch: pytest.MonkeyPatch, нарушений: int, адрес: str = "/ratings") -> str:
    _страница(monkeypatch, нарушений)
    for client in _клиент(monkeypatch):
        return client.get(адрес).get_data(as_text=True)
    raise AssertionError("клиент не создан")


def _столбцы(html: str) -> list[int]:
    """Сколько строк в каждом столбце хард-нарушений, в порядке на странице."""
    return [len(re.findall(r"<li class=\"rt-hard__row\"", col)) for col in _тела(html)]


def _тела(html: str) -> list[str]:
    return re.findall(r'<ol class="rt-hard__col"[^>]*>(.*?)</ol>', html, flags=re.S)


def test_хард_нарушения_режутся_на_столбцы_по_десять(monkeypatch: pytest.MonkeyPatch) -> None:
    html = _получить(monkeypatch, 25)

    assert _столбцы(html) == [10, 10, 5]
    assert 'start="1"' in html and 'start="11"' in html and 'start="21"' in html
    # первый столбец — строки 0–9, второй — 10–19, а не вперемешку
    левый, правый = _тела(html)[:2]
    assert "Нарушение 0<" in левый and "Нарушение 9<" in левый and "Нарушение 10<" not in левый
    assert "Нарушение 10<" in правый and "Нарушение 19<" in правый


def test_показать_ещё_есть_только_когда_строк_больше_двадцати(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    много = _получить(monkeypatch, 25)
    assert "<button" in много and "rt-hard__more" in много and ">Показать ещё (5)<" in много
    assert "Show more" not in много  # язык экрана — русский
    ровно = _получить(monkeypatch, 20)
    assert "rt-hard__more" not in ровно


def test_показать_ещё_на_английском(monkeypatch: pytest.MonkeyPatch) -> None:
    _страница(monkeypatch, 25)
    for client in _клиент(monkeypatch, "en"):
        assert "Show more (5)" in client.get("/ratings?lang=en").get_data(as_text=True)


def _плитка(html: str, key: str) -> str:
    найдено = re.search(rf'<article class="rt-tile[^"]*" data-tile="{key}">', html)
    assert найдено, f"плитки {key} нет на странице"
    return найдено.group(0)


def test_по_умолчанию_раскрыты_хард_нарушения(monkeypatch: pytest.MonkeyPatch) -> None:
    html = _получить(monkeypatch, 3)

    assert "is-open" in _плитка(html, "hard")
    assert "is-open" not in _плитка(html, "risk")
    assert len(re.findall(r'aria-expanded="true"', html)) == 1


def test_open_раскрывает_названную_плитку(monkeypatch: pytest.MonkeyPatch) -> None:
    html = _получить(monkeypatch, 3, "/ratings?open=risk")

    assert "is-open" in _плитка(html, "risk")
    assert "is-open" not in _плитка(html, "hard")
    раскрытая = re.search(r'id="rt-tb-risk"[^>]*aria-expanded="(\w+)"', html)
    assert раскрытая and раскрытая.group(1) == "true"
    свёрнутая = re.search(r'id="rt-tb-hard"[^>]*aria-expanded="(\w+)"', html)
    assert свёрнутая and свёрнутая.group(1) == "false"
    # ссылки периода и среза несут раскрытую плитку дальше
    assert "open=risk" in html


def test_open_none_сворачивает_всё_и_незнакомое_даёт_умолчание(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert 'aria-expanded="true"' not in _получить(monkeypatch, 3, "/ratings?open=none")
    assert "is-open" in _плитка(_получить(monkeypatch, 3, "/ratings?open=zzz"), "hard")


def test_агрегаторы_и_карты_отдельные_плитки(monkeypatch: pytest.MonkeyPatch) -> None:
    html = _получить(monkeypatch, 3)

    _плитка(html, "aggregators")
    _плитка(html, "maps")
    порядок = re.findall(r'<article class="rt-tile[^"]*" data-tile="(\w+)"', html)
    assert порядок.index("aggregators") < порядок.index("hard")  # выше нижних блоков


def test_каждый_блок_компоновки_есть_плиткой(monkeypatch: pytest.MonkeyPatch) -> None:
    html = _получить(monkeypatch, 3)

    assert set(re.findall(r'<article class="rt-tile[^"]*" data-tile="(\w+)"', html)) == set(
        rl.BLOCKS
    )


def test_open_key_выбирает_плитку() -> None:
    плитки = ("scores", "hard", "risk")
    assert ratings_tiles.open_key("risk", плитки) == "risk"
    assert ratings_tiles.open_key(None, плитки) == "hard"
    assert ratings_tiles.open_key("none", плитки) is None
    assert ratings_tiles.open_key("maps", плитки) == "hard"  # плитки нет на экране
    assert ratings_tiles.open_key(None, ("scores", "risk")) is None


def test_клиенты_плитка_с_честной_пустой_плашкой_и_ярусы(monkeypatch: pytest.MonkeyPatch) -> None:
    html = _получить(monkeypatch, 3)

    assert "Оценки клиентов из приложения появятся после подключения отзывов Dodo IS" in html
    ярусы = re.findall(
        r'<div class="rt-tiles rt-tiles--\d">(.*?)(?=<div class="rt-tiles rt-tiles--|\Z)',
        html,
        flags=re.S,
    )
    состав = [re.findall(r'data-tile="(\w+)"', ярус) for ярус in ярусы]
    assert состав == [
        ["scores", "violations", "top"],
        ["clients", "maps", "aggregators", "risk"],
        ["hard", "compare"],
    ]


def test_общий_список_риска_называет_источники_словами(monkeypatch: pytest.MonkeyPatch) -> None:
    ряд = rsrc.RiskRow(
        "u1",
        "Стара-Загора-1",
        "BG",
        (rsrc.Source("rko", (83.0, 83.5, 84.0)), rsrc.Source("wolt", (8.5, 8.6, 8.7, 8.8))),
    )
    _страница(monkeypatch, 3)
    monkeypatch.setattr(screen.ratings_risk, "build", lambda *_a, **_k: CombinedRisk((ряд,), ()))
    for client in _клиент(monkeypatch):
        html = client.get("/ratings?open=risk").get_data(as_text=True)

    assert "Стара-Загора-1" in html
    assert "<b>РКО</b>" in html and "<b>Wolt</b>" in html
    assert "8.5 → 8.6 → 8.7 → 8.8" in html
