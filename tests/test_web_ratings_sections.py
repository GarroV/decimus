"""Разделы «Рейтингов» (D660): подменю в общей навигации, адрес `/ratings/<раздел>`, срез
и период едут между разделами, раздел считает только своё. Страница рендерится
настоящая, данные подменены (`ratings_page`)."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime

import pytest
from ratings_page import ПУСТОЙ, клиент, подготовить, получить, сводка, факты

from src.db.errors import RatingsError
from src.ratings import freshness as fresh
from src.ratings import risk_sources as rsrc
from src.ratings.summary import CountryLine
from src.web import ratings as screen
from src.web import ratings_nav
from src.web.ratings_risk import CombinedRisk

РАЗДЕЛЫ = (
    "overview",
    "rs",
    "rko",
    "clients",
    "maps",
    "agg",
    "risk",
    "violations",
    "compare",
    "inspections",
)
ЗАЯВЛЕНИЕ = {"Origin": "http://localhost"}


def _подменю(html: str) -> list[tuple[str, bool]]:
    """Пункты подменю в порядке на странице: (раздел из адреса, текущий ли)."""
    блок = re.search(r'<nav class="sidenav__sub".*?</nav>', html, flags=re.S)
    assert блок, "подменю нет на странице"
    пункты = re.findall(r'<a class="sidenav__subitem([^"]*)" href="/ratings/(\w+)\?', блок.group(0))
    return [(раздел, "is-on" in классы) for классы, раздел in пункты]


def _заголовок(html: str) -> str:
    найден = re.search(r'<h1 class="rt-head__title">(.*?)</h1>', html)
    assert найден
    return найден.group(1)


def test_подменю_в_заданном_порядке_и_голый_адрес_открывает_обзор(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    подготовить(monkeypatch)
    html = получить(monkeypatch)

    assert _подменю(html) == [(k, k == "overview") for k in РАЗДЕЛЫ]
    assert _заголовок(html) == screen.t("ratings.sec.overview", "ru")


@pytest.mark.parametrize(
    ("раздел", "название"),
    [
        ("overview", screen.t("ratings.sec.overview", "ru")),
        ("violations", screen.t("ratings.sec.violations", "ru")),
        ("rs", "Рейтинг стандартов (РС)"),
        ("rko", "Рейтинг клиентского опыта (РКО)"),
        ("clients", "Оценки клиентов"),
        ("maps", "Карты"),
        ("agg", "Агрегаторы"),
        ("risk", "Пиццерии в зоне риска"),
        ("compare", "Девелоперы и страны"),
    ],
)
def test_раздел_по_адресу_открывается_и_подсвечен_в_подменю(
    monkeypatch: pytest.MonkeyPatch, раздел: str, название: str
) -> None:
    подготовить(monkeypatch)
    html = получить(monkeypatch, f"/ratings/{раздел}")

    assert _заголовок(html) == название
    assert _подменю(html) == [(k, k == раздел) for k in РАЗДЕЛЫ]


def test_у_не_ук_нет_девелоперов_и_стран_ни_в_подменю_ни_по_адресу(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    вызовы = подготовить(monkeypatch)
    for c in клиент(monkeypatch, tenant="GE"):
        рс = c.get("/ratings").get_data(as_text=True)
        assert [k for k, _ in _подменю(рс)] == [k for k in РАЗДЕЛЫ if k != "compare"]
        assert c.get("/ratings/compare").status_code == 404
    assert вызовы["compare"] == []  # чужие страны не считались вовсе


def test_незнакомый_раздел_и_старый_open_не_ломают_страницу(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    подготовить(monkeypatch)
    for c in клиент(monkeypatch):
        assert c.get("/ratings/zzz").status_code == 404
        # `?open=` из закладок молча игнорируется: открывается РС, как голый адрес
        html = c.get("/ratings?open=risk").get_data(as_text=True)
        assert _заголовок(html) == screen.t("ratings.sec.overview", "ru")


def test_срез_и_период_едут_в_подменю_и_в_фильтры_того_же_раздела(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    подготовить(monkeypatch)
    html = получить(monkeypatch, "/ratings/rko?group=country&value=RS&period=2026-09&lang=ru")

    for раздел in РАЗДЕЛЫ:
        assert re.search(
            rf'href="/ratings/{раздел}\?group=country&amp;value=RS&amp;period=2026-09', html
        ), раздел
    # выбор среза — адрес того же раздела, а не общий `/ratings`
    срезы = re.findall(r'<option value="([^"]+)"[^>]*>(?:Весь IMF|Кластер|Страна)', html)
    assert срезы and all(p.startswith("/ratings/rko?group=") for p in срезы)
    # форма отбора шлёт туда же
    assert 'id="rt-bar-form" data-rt-auto method="get" action="/ratings/rko"' in html


def test_выбор_раздела_на_телефоне_список_со_всеми_пунктами(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    подготовить(monkeypatch)
    html = получить(monkeypatch, "/ratings/maps")

    список = re.search(
        r'<select class="pickselect" data-pick-nav data-rt-nav.*?</select>', html, re.S
    )
    assert список
    assert re.findall(r'<option value="/ratings/(\w+)\?', список.group(0)) == list(РАЗДЕЛЫ)
    assert re.search(r'value="/ratings/maps\?[^"]*" selected', список.group(0))


def test_плиток_ярусов_и_редактора_компоновки_больше_нет(monkeypatch: pytest.MonkeyPatch) -> None:
    подготовить(monkeypatch)
    html = получить(monkeypatch)

    assert "rt-tile" not in html and "rt-tiers" not in html and "data-tile" not in html
    for c in клиент(monkeypatch):
        assert c.post("/ratings/layout", headers=ЗАЯВЛЕНИЕ).status_code in (404, 405)


def test_старая_страница_охвата_ведёт_в_агрегаторы(monkeypatch: pytest.MonkeyPatch) -> None:
    подготовить(monkeypatch)
    for c in клиент(monkeypatch):
        ответ = c.get("/ratings/coverage?country=TR&lang=en&junk=1")
        assert ответ.status_code == 302
        assert ответ.headers["Location"] == "/ratings/agg?country=TR&lang=en"


def test_раздел_считает_только_своё(monkeypatch: pytest.MonkeyPatch) -> None:
    вызовы = подготовить(monkeypatch)
    for c in клиент(monkeypatch):
        c.get("/ratings/rs")
        assert вызовы["build"] == [
            {"kinds": ("rs",), "with_risk": False, "only": ("RS",)}
        ]  # РКО и риск не читались
        c.get("/ratings/rko")
        assert вызовы["build"][-1] == {"kinds": ("rko",), "with_risk": False, "only": ("RS",)}
        c.get("/ratings/risk")
        assert вызовы["build"][-1] == {"kinds": (), "with_risk": True, "only": ("RS",)}
        собрано = len(вызовы["build"])
        for раздел in ("agg", "maps", "compare", "clients"):
            c.get(f"/ratings/{раздел}")
        assert len(вызовы["build"]) == собрано  # полная сводка этим разделам не нужна
    assert len(вызовы["agg"]) == 1 and len(вызовы["maps"]) == 1 and len(вызовы["compare"]) == 1


def test_хард_нарушения_режутся_на_столбцы_по_десять(monkeypatch: pytest.MonkeyPatch) -> None:
    подготовить(monkeypatch, сводка(rs_hard=факты(25)))
    html = получить(monkeypatch, "/ratings/rs")

    столбцы = re.findall(r'<ol class="rt-hard__col"[^>]*>(.*?)</ol>', html, flags=re.S)
    assert [len(re.findall(r'<li class="rt-hard__row"', c)) for c in столбцы] == [10, 10, 5]
    assert 'start="1"' in html and 'start="11"' in html and 'start="21"' in html
    левый, правый = столбцы[:2]
    assert "Нарушение 0<" in левый and "Нарушение 9<" in левый and "Нарушение 10<" not in левый
    assert "Нарушение 10<" in правый and "Нарушение 19<" in правый


def test_хард_в_разделе_только_своего_источника(monkeypatch: pytest.MonkeyPatch) -> None:
    подготовить(monkeypatch, сводка(rs_hard=факты(2), rko_hard=факты(1)))

    рс = получить(monkeypatch, "/ratings/rs")
    рко = получить(monkeypatch, "/ratings/rko")

    assert len(re.findall(r'<li class="rt-hard__row"', рс)) == 2
    assert len(re.findall(r'<li class="rt-hard__row"', рко)) == 1


def test_показать_ещё_только_когда_строк_больше_двадцати(monkeypatch: pytest.MonkeyPatch) -> None:
    подготовить(monkeypatch, сводка(rs_hard=факты(25)))
    много = получить(monkeypatch, "/ratings/rs")
    assert "rt-hard__more" in много and ">Показать ещё (5)<" in много
    assert "Show more" not in много  # язык экрана — русский
    подготовить(monkeypatch, сводка(rs_hard=факты(20)))
    assert "rt-hard__more" not in получить(monkeypatch, "/ratings/rs")


def test_показать_ещё_на_английском(monkeypatch: pytest.MonkeyPatch) -> None:
    подготовить(monkeypatch, сводка(rs_hard=факты(25)))
    assert "Show more (5)" in получить(monkeypatch, "/ratings/rs?lang=en", ui_lang="en")


def _пиццерий_с_оценкой(html: str) -> str:
    """Число в плитке «Пиццерий с оценкой» (подписи «пиццерий: N» у «Средней» больше нет, D767)."""
    m = re.search(r"С оценкой.*?pk-tile__value\">\s*(\d+)\s*<", html, re.S)
    assert m
    return m.group(1)


def test_рс_плитки_страны_топ_и_боттом_из_сводки(monkeypatch: pytest.MonkeyPatch) -> None:
    подготовить(monkeypatch, сводка(rs_hard=факты(2)))
    html = получить(monkeypatch, "/ratings/rs")

    метки = re.findall(r'<div class="pk-tile__label">(.*?)</div>', html)
    assert метки == ["Средняя", "Нарушений", "Хард", "С оценкой"]
    assert _пиццерий_с_оценкой(html) == "4"  # из `rs_units`
    assert "пиццерий: 4" not in html
    assert "пиццерий с хардом: 2" in html
    строка = re.search(r'<th scope="row"><a[^>]*>Сербия</a></th>(.*?)</tr>', html, re.S)
    assert строка
    ячейки = re.findall(r'<td class="num">(.*?)</td>', строка.group(1), re.S)
    assert [re.sub(r"<[^>]+>", "", x).strip() for x in ячейки] == ["91.0", "▲+0.4", "3", "2", "4"]
    assert "Пиццерия-Верх" in html and "Пиццерия-Низ" in html


def test_рко_берёт_свои_числа_а_не_рс(monkeypatch: pytest.MonkeyPatch) -> None:
    подготовить(monkeypatch)
    html = получить(monkeypatch, "/ratings/rko")

    assert "88.0" in html and "91.0" not in html
    assert _пиццерий_с_оценкой(html) == "3" and "Пиццерия-Верх" not in html


def test_сохранённые_оценки_остаются_при_недоступных_api_периодах(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    подготовить(monkeypatch)

    def unavailable(**_kw: object) -> None:
        raise RatingsError("synthetic unavailable source windows")

    monkeypatch.setattr(screen.read, "source_rating_periods", unavailable)
    html = получить(monkeypatch, "/ratings/rs")
    assert _заголовок(html) == "Рейтинг стандартов (РС)"
    assert "91.0" in html and _пиццерий_с_оценкой(html) == "4"
    assert "Пиццерия-Верх" in html and "Пиццерия-Низ" in html
    # Synthetic sheet dates must never become actual Dodo IS period cards.
    assert "data-source-period=" not in html


def test_непрочитанные_детальные_нарушения_не_выдаются_за_ноль(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    подготовить(monkeypatch, сводка(rs_hard=факты(2)))

    def unavailable(*_args: object) -> None:
        raise RatingsError("synthetic unavailable detailed violations")

    monkeypatch.setattr(screen.violations_view.read, "facts", unavailable)
    html = получить(monkeypatch, "/ratings/rs")
    row = re.search(r'<th scope="row"><a[^>]*>Сербия</a></th>(.*?)</tr>', html, re.S)
    assert row
    cells = re.findall(r'<td class="num">(.*?)</td>', row.group(1), re.S)
    assert [re.sub(r"<[^>]+>", "", x).strip() for x in cells] == ["91.0", "▲+0.4", "—", "—", "4"]
    # Already loaded summary hard details are still available independently.
    assert len(re.findall(r'<li class="rt-hard__row"', html)) == 2


def test_без_проверок_плиток_нет_а_честная_плашка(monkeypatch: pytest.MonkeyPatch) -> None:
    подготовить(
        monkeypatch,
        сводка(
            rko_cluster=ПУСТОЙ,
            rko_by_country={},
            rko_top=(),
            rko_bottom=(),
            total=CountryLine("", None, None, None, None),
        ),
    )
    html = получить(monkeypatch, "/ratings/rko")

    assert 'class="rt-empty"' in html
    assert 'class="pk-tile"' not in html


def test_клиенты_честная_пустая_плашка(monkeypatch: pytest.MonkeyPatch) -> None:
    подготовить(monkeypatch)
    html = получить(monkeypatch, "/ratings/clients")

    assert "За выбранный период нет полных месяцев с оценками клиентов" in html
    assert "появятся после подключения" not in html


def test_общий_список_риска_называет_источники_словами(monkeypatch: pytest.MonkeyPatch) -> None:
    ряд = rsrc.RiskRow(
        "u1",
        "Стара-Загора-1",
        "BG",
        (rsrc.Source("rko", (83.0, 83.5, 84.0)), rsrc.Source("wolt", (8.5, 8.6, 8.7, 8.8))),
    )
    подготовить(monkeypatch)
    monkeypatch.setattr(screen.ratings_risk, "build", lambda *_a, **_k: CombinedRisk((ряд,), ()))
    html = получить(monkeypatch, "/ratings/risk")

    assert "Стара-Загора-1" in html
    assert re.search(r'<b class="rt-risk-source__name">РКО</b>', html)
    assert re.search(r'<b class="rt-risk-source__name">Wolt</b>', html)
    assert 'aria-label="Wolt: 8.5, 8.6, 8.7, 8.8"' in html
    assert 'aria-label="РКО: 83.0, 83.5, 84.0"' in html
    assert "rt-sparkline__line" in html and "▲" in html


def test_точка_свежести_в_подменю_и_строка_в_шапке(monkeypatch: pytest.MonkeyPatch) -> None:
    подготовить(monkeypatch)
    rows = (
        fresh.Row(
            "rs",
            fresh.Status.FRESH,
            begin_on=date(2026, 10, 16),
            end_on=date(2026, 10, 31),
            arrived=datetime(2026, 10, 27, 11, 17, tzinfo=UTC),
        ),
        fresh.Row("maps", fresh.Status.LAG, arrived=datetime(2026, 10, 25, 8, 0, tzinfo=UTC)),
    )
    monkeypatch.setattr(screen.ratings_freshness, "read_rows", lambda now: rows)
    html = получить(monkeypatch, "/ratings/rs")

    блок = re.search(r'<nav class="sidenav__sub".*?</nav>', html, flags=re.S)
    assert блок
    assert re.search(r'РС\)</span><i class="rt-fdot rt-fdot--fresh"', блок.group(0))
    assert re.search(r'Карты</span><i class="rt-fdot rt-fdot--lag"', блок.group(0))
    assert "Оценки клиентов</span><i" not in блок.group(0)  # у клиентов источника нет — точки нет
    assert "Данные за 16–31.10, пришли 27.10 11:17" in html


def test_подменю_постоянно_но_скрипт_рейтингов_не_включён_на_других_страницах(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    подготовить(monkeypatch)
    for c in клиент(monkeypatch):
        html = c.get("/inspections").get_data(as_text=True)
        assert "sidenav__sub" in html
        assert "data-nav-ratings-toggle" in html
        assert "data-rt-subnav" not in html
        assert "data-rt-nav" not in html


def test_видимость_разделов_по_пространству() -> None:
    assert ratings_nav.visible(True, inspections=True) == ratings_nav.SECTIONS
    assert "compare" not in ratings_nav.visible(False)
    assert ratings_nav.DEFAULT == "overview"


def test_точка_раздела_без_своего_источника_берёт_худший_из_его_частей() -> None:
    from src.web import ratings_freshness as rf

    строки = (
        fresh.Row("rs", fresh.Status.FRESH),
        fresh.Row("rko", fresh.Status.LAG),
        fresh.Row("agg", fresh.Status.STALE, "wolt"),
        fresh.Row("agg", fresh.Status.FRESH, "glovo"),
    )

    assert rf.section_status(строки, "risk") == "stale"  # РС, РКО и площадки: худшая красная
    assert rf.section_status(строки, "compare") == "lag"  # РС и РКО
    assert rf.section_status(строки, "rs") == "fresh"
    assert rf.section_status(строки, "clients") is None  # источника ещё нет — точки нет
    assert rf.section_status((), "agg") is None


def test_таблица_свежести_зоны_риска_без_лишних_источников_и_площадки_одной_строкой() -> None:
    from src.web import ratings_freshness as rf

    строки = (
        fresh.Row("rs", fresh.Status.FRESH, begin_on=date(2026, 10, 16), end_on=date(2026, 10, 31)),
        fresh.Row("rko", fresh.Status.FRESH),
        fresh.Row("sheet", fresh.Status.FRESH),
        fresh.Row("maps", fresh.Status.FRESH),
        fresh.Row(
            "agg", fresh.Status.FRESH, "glovo", arrived=datetime(2026, 10, 27, 9, 0, tzinfo=UTC)
        ),
        fresh.Row(
            "agg", fresh.Status.LAG, "wolt", arrived=datetime(2026, 10, 25, 7, 30, tzinfo=UTC)
        ),
    )
    names = {"glovo": "Glovo", "wolt": "Wolt"}

    risk = rf.lines_of(строки, "ru", names, "risk")
    full = rf.lines_of(строки, "ru", names)

    assert risk is not None and full is not None
    assert [x.name for x in risk.lines] == ["РС", "РКО", "Площадки доставки (2)"]
    assert (risk.lines[-1].status, risk.lines[-1].arrived) == ("lag", "25.10 07:30")
    assert risk.worst == "lag"
    assert len(full.lines) == 6  # у остальных разделов таблица прежняя


def test_зона_риска_называется_по_новому_и_объясняет_источники_под_вопросом(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    подготовить(monkeypatch)
    monkeypatch.setattr(screen.ratings_risk, "build", lambda *_a, **_k: CombinedRisk((), ()))
    ru = получить(monkeypatch, "/ratings/risk")
    en = получить(monkeypatch, "/ratings/risk?lang=en")

    assert "Стабильно ниже порога" not in ru and "Consistently below" not in en
    assert "Пиццерия попадает сюда, если хотя бы в одном источнике" in ru
    assert "РС и РКО — средняя ниже" in ru and "Наши проверки — оценка ниже" in ru
    assert "Pizzerias at risk" in en and "A pizzeria is listed here if" in en


def test_строка_шапки_у_сборов_называет_самый_ранний_приход() -> None:
    from src.web import ratings_freshness as rf

    строки = (
        fresh.Row(
            "agg", fresh.Status.FRESH, "glovo", arrived=datetime(2026, 10, 27, 9, 0, tzinfo=UTC)
        ),
        fresh.Row(
            "agg", fresh.Status.LAG, "wolt", arrived=datetime(2026, 10, 25, 7, 30, tzinfo=UTC)
        ),
    )

    assert rf.section_line(строки, "agg", "ru") == "Загружено 25.10 07:30"
    assert rf.section_line(строки, "agg", "en") == "Loaded 25.10 07:30"
    assert rf.section_line(строки, "risk", "ru") is None  # у этих разделов своей даты нет
    assert rf.section_line((fresh.Row("rs", fresh.Status.STALE),), "rs", "ru") == "Оценок ещё нет"


@pytest.mark.parametrize("lang", ["ru", "en"])
@pytest.mark.parametrize("key", РАЗДЕЛЫ)
def test_work_sections_have_no_business_settings(
    monkeypatch: pytest.MonkeyPatch, lang: str, key: str
) -> None:
    подготовить(monkeypatch)
    response = получить(monkeypatch, f"/ratings/{key}?lang={lang}")
    main = re.search(r"<main\b[^>]*>(.*?)</main>", response, flags=re.S)
    assert main is not None
    assert screen.t("ratings.manage", lang) not in main.group(1)
    assert not re.search(r'<a\b[^>]*href="[^"]*/administration', main.group(1))
    # Only the personal country preference may write from a work screen.
    post_actions = re.findall(r'<form\b[^>]*method="post"[^>]*action="([^"]+)"', main.group(1))
    assert post_actions == ["/country/filter"]


def test_нет_дат_периодов_одна_тихая_строка_без_блока(monkeypatch: pytest.MonkeyPatch) -> None:
    подготовить(monkeypatch)
    html = получить(monkeypatch, "/ratings/rs")
    # Заглушка — абзац без рамки блока; блока «rt-periods» без плиток нет.
    if "data-source-period=" not in html:
        assert 'class="rt-periods-empty"' in html and 'class="rt-periods"' not in html
