"""«Агрегаторы» и «Карты» (D660): причина словами у каждой пиццерии без точки, раскрытие
страны, плитки по площадкам, привязка по ссылке на месте. Правила причин — чистые, без базы;
страница рендерится настоящая над собранным охватом."""

from __future__ import annotations

import re
from datetime import date

import pytest
from ratings_page import клиент, подготовить, получить

from src.db.agg_store import UnitRow
from src.ratings import coverage
from src.ratings.aggregators import summary as ragg
from src.web import ratings as screen
from src.web import ratings_platforms as rp

СЕГОДНЯ = date(2026, 10, 27)


def _unit(dodo_id: str, name: str, country: str = "RO") -> UnitRow:
    return UnitRow(dodo_id, country, name, 44.4, 26.1, True, None, СЕГОДНЯ)


def _ряд(unit: UnitRow, **клетки: coverage.Cell) -> coverage.Row:
    return coverage.Row(unit, False, клетки)


СВЕЖАЯ = coverage.Cell(coverage.SCORE, 9.1, 10, СЕГОДНЯ, False)
СТАРАЯ = coverage.Cell(coverage.SCORE, 98.0, 100, date(2026, 10, 10), True)
НЕТ_ТОЧКИ = coverage.Cell(coverage.MISSING)
БЕЗ_ОЦЕНОК = coverage.Cell(coverage.UNRATED)
НЕТ_В_СТРАНЕ = coverage.Cell(coverage.ABSENT)


def test_причины_у_пиццерии_без_точки_словами_кодами(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rp.collect, "PAUSED", (type("M", (), {"KEY": "yandex_eda"}),))
    строки = [
        _ряд(_unit("a", "А"), wolt=СВЕЖАЯ, glovo=СВЕЖАЯ, yandex_eda=НЕТ_В_СТРАНЕ),
        _ряд(_unit("b", "Б"), wolt=НЕТ_ТОЧКИ, glovo=БЕЗ_ОЦЕНОК, yandex_eda=НЕТ_ТОЧКИ),
        _ряд(_unit("c", "В"), wolt=СВЕЖАЯ, glovo=СТАРАЯ, yandex_eda=НЕТ_В_СТРАНЕ),
    ]

    gaps = rp._gaps(строки, ("wolt", "glovo", "yandex_eda"))

    assert [g.unit.name for g in gaps] == ["Б", "В"]  # у «А» всё на месте и ничего лишнего
    assert [(r.platform, r.code) for r in gaps[0].reasons] == [
        ("wolt", rp.UNLINKED),
        ("glovo", rp.UNRATED),
        ("yandex_eda", rp.PAUSED),
    ]
    assert [(r.platform, r.code, r.on_date) for r in gaps[1].reasons] == [
        ("glovo", rp.STALE, date(2026, 10, 10))
    ]


def _охват() -> rp.AggView:
    румыния = [
        _ряд(_unit("a", "Бухарест-1"), wolt=СВЕЖАЯ, glovo=НЕТ_ТОЧКИ),
        _ряд(_unit("b", "Бухарест-2"), wolt=БЕЗ_ОЦЕНОК, glovo=СВЕЖАЯ),
    ]
    польша = [_ряд(_unit("c", "Варшава-1", "PL"), wolt=НЕТ_В_СТРАНЕ, glovo=СТАРАЯ)]
    оценки = {"wolt": ragg.AggScore(9.1, 10, 120, 1), "glovo": ragg.AggScore(97.5, 100, 800, 1)}
    return rp.AggView(
        platforms=("wolt", "glovo"),
        tiles=(
            rp.Tile("wolt", оценки["wolt"], 2, 2),
            rp.Tile("glovo", оценки["glovo"], 2, 3),
        ),
        countries=(
            rp.CountryBlock("RO", оценки, tuple(румыния)),
            rp.CountryBlock("PL", {}, tuple(польша)),
        ),
        gaps=rp._gaps([*румыния, *польша], ("wolt", "glovo")),
        as_of=СЕГОДНЯ,
        later=False,
    )


def _агрегаторы(monkeypatch: pytest.MonkeyPatch, адрес: str = "/ratings/agg") -> str:
    подготовить(monkeypatch)
    monkeypatch.setattr(screen.ratings_platforms, "build_agg", lambda *_a, **_k: _охват())
    return получить(monkeypatch, адрес)


def test_плитки_по_площадкам_и_таблица_страна_на_площадку(monkeypatch: pytest.MonkeyPatch) -> None:
    html = _агрегаторы(monkeypatch)

    assert re.findall(r'<div class="pk-tile__label">(.*?)</div>', html) == ["Wolt", "Glovo"]
    assert "привязано 2 из 2" in html and "привязано 2 из 3" in html
    assert "9.1<span" in html and "97.5%" in html  # оценка — в родной шкале площадки
    румыния = re.search(r'<tbody class="rt-group[^"]*" data-country="RO">(.*?)</tbody>', html, re.S)
    assert румыния
    assert "Бухарест-1" in румыния.group(1) and "Бухарест-2" in румыния.group(1)
    assert "пиццерий: 1" in румыния.group(1)  # сколько привязано у страны


def test_страна_раскрывается_сервером_по_адресу_без_скрипта(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    закрыта = _агрегаторы(monkeypatch)
    открыта = _агрегаторы(monkeypatch, "/ratings/agg?country=RO")

    assert 'class="rt-group" data-country="RO"' in закрыта
    assert 'class="rt-group is-open" data-country="RO"' in открыта
    assert 'class="rt-group" data-country="PL"' in открыта  # раскрыта одна, остальные нет
    assert 'aria-expanded="true"' in открыта and 'aria-expanded="true"' not in закрыта
    # открытая страна едет в ссылки фильтров: пересчёт не сворачивает её
    assert "&amp;country=RO" in открыта.split('id="rt-bar-form"')[1].split("</form>")[0]


def test_чего_не_хватает_причина_словами_у_каждой_пиццерии(monkeypatch: pytest.MonkeyPatch) -> None:
    html = _агрегаторы(monkeypatch)

    блок = html.split('<h2 class="pk-block__title">Чего не хватает</h2>')[1]
    assert "Glovo: не привязана — точка рядом с пиццерией не нашлась" in блок
    assert "Wolt: точка привязана, оценок у неё ещё нет" in блок
    assert "Glovo: оценка не обновляется с 10.10.2026" in блок
    assert "Бухарест-1" in блок and "Варшава-1" in блок


def test_привязка_по_ссылке_видна_управляющему_там_же(monkeypatch: pytest.MonkeyPatch) -> None:
    html = _агрегаторы(monkeypatch)

    assert 'action="/ratings/coverage/link?' in html
    assert 'name="aggregator" value="glovo"' in html  # у Бухарест-1 нет Glovo — форма есть
    assert html.count('name="dodo_id"') == 1  # там, где не хватает точки, а не у каждой строки


def test_без_права_формы_привязки_нет(monkeypatch: pytest.MonkeyPatch) -> None:
    подготовить(monkeypatch)
    monkeypatch.setattr(screen.ratings_platforms, "build_agg", lambda *_a, **_k: _охват())
    for c in клиент(monkeypatch, tenant="GE"):
        html = c.get("/ratings/agg").get_data(as_text=True)
    assert "Чего не хватает" in html and "coverage/link" not in html


def test_база_не_ответила_агрегаторы_говорят_об_этом(monkeypatch: pytest.MonkeyPatch) -> None:
    подготовить(monkeypatch)
    html = получить(monkeypatch, "/ratings/agg")  # `build_agg` в заглушке отдаёт None

    assert 'class="rt-empty"' in html and "Чего не хватает" not in html


def test_карты_пиццерии_на_google_и_яндексе(monkeypatch: pytest.MonkeyPatch) -> None:
    подготовить(monkeypatch)
    охват = coverage.Coverage(
        platforms=(
            coverage.Platform("2", coverage.KIND_MAP),
            coverage.Platform("1", coverage.KIND_MAP),
        ),
        rows=(
            _ряд(
                _unit("a", "Бухарест-1"),
                **{"2": coverage.Cell(coverage.SCORE, 4.7, 5, СЕГОДНЯ, False), "1": НЕТ_ТОЧКИ},
            ),
        ),
        new=0,
        unlinked=0,
    )
    monkeypatch.setattr(screen.ratings_platforms, "build_maps", lambda *_a, **_k: охват)
    html = получить(monkeypatch, "/ratings/maps")

    assert "Пиццерии на картах" in html and "Бухарест-1" in html
    assert "4.70" in html and ">Google<" in html and ">Яндекс<" in html
