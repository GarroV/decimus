# Экран «Страна», волна 1 — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Раздел «Страна» в веб-админке: пиццерии выбранной страны с раскрытием истории проверок, что системно болит, фильтры на экране; клик по городу и точке на «Обзоре» ведёт сюда.

**Architecture:** Никакого нового подсчёта. Экран страны — это `overview.load()` с отбором `country=<код>` плюс выборка истории одной точки из того же снимка. Данные — новый модуль `src/web/country.py`; маршрут регистрируется в `src/web/app.py` рядом с «Обзором» (`_register_country`), потому что пользуется его помощниками (`_pick`, `_url`, `_lang`); шаблон — `src/web/templates/country/index.html` на классах «Обзора».

**Tech Stack:** Python 3, Flask, Jinja2, pytest (`tests/web_harness.py`), ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-09-30-country-and-prescriptions-design.md` (волна 1). Решения: D260, D262, D264, D277, D278.

## Global Constraints

- Ни одной цифры собственного производства: проценты, буквы, потери — как записал движок (`CLAUDE.md`, «Оценку не считать заново»).
- Страна, город, пиццерия в адресе — коды и id, не формулировки (конституция, принцип 5).
- Каждая строка интерфейса — ключом в `src/web/texts.py`, на `ru` и `en`.
- Внутренние ссылки — только через `url(path)` шаблона / `_url(endpoint)` (живёт под `WEB_URL_PREFIX`).
- Экран показывает то, что есть (D217): блоков предписаний, экшн-планов и плана проверок в этой волне нет вовсе — ни заглушкой, ни пустой рамкой.
- Действий УК на экране страны нет (D264). Кнопка «Назначить проверку» с «Обзора» снимается (D260), в раздел действий УК она придёт в волне 2.
- Регрессия движка: `make regress` (belgrade-1 97.5% A 5×D1, belgrade-2 97.0% A 6×D1) — не должна сдвинуться.
- Параллельно идёт #461 (облик форм под Swarm, ветка `feat/forma-swarm`) и правит `overview/index.html` и стили. Перед задачей 4 — `git fetch && git rebase origin/main`; если #461 уже влит, классы брать из него.

## Review Focus

1. **Мусорный код страны в адресе** (`/country/xx`, `/country/ge`, `/country/<script>`) — регистр приводится к верхнему, чужое сужается в пустоту и экран говорит словами «в этой стране нет проверок за период», не 500. Тест — задача 3.
2. **`?unit=` чужой или несуществующей точки** (id точки другой страны, мусор) — ничего не раскрыто, страница 200. Тест — задача 1 и задача 3.
3. **Точка без страны в справочнике** — на «Обзоре» строка ведёт в карточку точки, как сегодня, а не в `/country/` с пустым кодом. Тест — задача 4.
4. **Раскрытие строки сохраняет фильтры** — период и буква остаются в адресе раскрытой строки. Тест — задача 3.
5. **Переключение языка сохраняет страну и точку** — ссылки несут `lang`, раскрытая строка остаётся раскрытой. Тест — задача 3.

---

### Task 1: Данные экрана страны

**Files:**
- Create: `src/web/country.py`
- Test: `tests/test_web_country_data.py`

**Interfaces:**
- Consumes: `src.web.overview.load(*, tenant, limit, selection, today=None) -> Overview`, `Overview.unit_ids: dict[str, str]` (имя → id), `Overview.inspections: tuple[InspectionRow, ...]` (по дате убыванием), `src.db.queries.unit_geography(*, tenant) -> dict[str, tuple[str, str]]` (имя → (страна, город)).
- Produces:
  - `country.CountryView` (frozen dataclass): `code: str`, `snapshot: Overview`, `unit_id: str`, `unit_name: str`, `history: tuple[InspectionRow, ...]`.
  - `country.normalize_code(raw: str) -> str` — два символа латиницы верхним регистром или `""`.
  - `country.load(*, tenant: str, limit: int, code: str, selection: Selection, unit_id: str = "", today: date | None = None) -> CountryView`.
  - `country.countries(*, tenant: str) -> tuple[tuple[str, int], ...]` — (код страны, число точек), крупные сверху, без пустого кода.

- [ ] **Step 1: Write the failing test**

```python
"""Данные экрана «Страна»: снимок «Обзора» с отбором по стране и история одной точки."""

from __future__ import annotations

from dataclasses import replace

import pytest
from test_web_overview import ПУСТО, строка

from src.web import country as cn
from src.web import overview as ov


def test_код_страны_приводится_к_верхнему_и_мусор_отбрасывается() -> None:
    assert cn.normalize_code(" ge ") == "GE"
    assert cn.normalize_code("GEO") == ""
    assert cn.normalize_code("<s") == ""
    assert cn.normalize_code("") == ""


def test_страна_уходит_в_отбор_обзора(monkeypatch: pytest.MonkeyPatch) -> None:
    видели: dict[str, ov.Selection] = {}

    def снимок(**kw: object) -> ov.Overview:
        видели["selection"] = kw["selection"]  # type: ignore[assignment]
        return ПУСТО

    monkeypatch.setattr(cn.overview, "load", снимок)
    cn.load(tenant="HQ", limit=10, code="GE", selection=ov.Selection(period="d90", country="RS"))
    assert видели["selection"].country == "GE"
    assert видели["selection"].period == "d90"


def test_история_точки_из_того_же_снимка(monkeypatch: pytest.MonkeyPatch) -> None:
    первая = строка("Батуми-1", 90.0, "B")
    вторая = replace(строка("Батуми-1", 80.0, "C"), id="22222222-2222-3333-4444-000000000002")
    чужая = строка("Тбилиси-2", 95.5, "B")
    данные = replace(ПУСТО, inspections=(первая, чужая, вторая), unit_ids={"Батуми-1": "u-1", "Тбилиси-2": "u-2"})
    monkeypatch.setattr(cn.overview, "load", lambda **_: данные)
    вид = cn.load(tenant="HQ", limit=10, code="GE", selection=ov.Selection(), unit_id="u-1")
    assert вид.unit_name == "Батуми-1"
    assert [r.id for r in вид.history] == [первая.id, вторая.id]


def test_чужой_или_мусорный_unit_ничего_не_раскрывает(monkeypatch: pytest.MonkeyPatch) -> None:
    данные = replace(ПУСТО, inspections=(строка("Батуми-1", 90.0, "B"),), unit_ids={"Батуми-1": "u-1"})
    monkeypatch.setattr(cn.overview, "load", lambda **_: данные)
    for мусор in ("u-999", "<script>", ""):
        вид = cn.load(tenant="HQ", limit=10, code="GE", selection=ov.Selection(), unit_id=мусор)
        assert (вид.unit_id, вид.unit_name, вид.history) == ("", "", ())


def test_список_стран_по_справочнику(monkeypatch: pytest.MonkeyPatch) -> None:
    гео = {"Батуми-1": ("GE", "batumi"), "Тбилиси-2": ("GE", "tbilisi"), "Белград-1": ("RS", "belgrade"), "Без-1": ("", "")}
    monkeypatch.setattr(cn.queries, "unit_geography", lambda **_: гео)
    assert cn.countries(tenant="HQ") == (("GE", 2), ("RS", 1))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTEST_ADDOPTS="tests/test_web_country_data.py" make test`
Expected: FAIL — `ImportError: cannot import name 'country' from 'src.web'`.

- [ ] **Step 3: Write minimal implementation**

```python
"""Экран «Страна»: снимок одной страны и история выбранной пиццерии (D260, D262).

НИЧЕГО НЕ СЧИТАЕТ САМ. Страна — это «Обзор» с отбором по стране: те же
запросы, те же цифры движка. Отдельный подсчёт здесь дал бы второй источник
одних и тех же чисел, и они разошлись бы с «Обзором» при первой правке.

История точки берётся из того же снимка, а не отдельным походом в базу:
снимок уже сужен периодом и отбором, и история обязана жить в том же срезе.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import date

from src.db import queries
from src.db.models import InspectionRow

from . import overview
from .overview import Overview, Selection

#: Код страны справочника — две латинские буквы (`GE`, `RS`).
_CODE = re.compile(r"[A-Z]{2}")


@dataclass(frozen=True)
class CountryView:
    """Всё, что показывает экран страны, одним снимком."""

    code: str
    snapshot: Overview
    #: Раскрытая точка. Пусто — ничего не раскрыто.
    unit_id: str = ""
    unit_name: str = ""
    #: Проверки раскрытой точки в срезе, свежие сверху.
    history: tuple[InspectionRow, ...] = ()


def normalize_code(raw: str) -> str:
    """Код страны из адреса. Непонятное — пустая строка, а не отказ."""
    code = raw.strip().upper()
    return code if _CODE.fullmatch(code) else ""


def load(
    *,
    tenant: str,
    limit: int,
    code: str,
    selection: Selection,
    unit_id: str = "",
    today: date | None = None,
) -> CountryView:
    """Снимок страны и, если попросили, история одной её точки."""
    snapshot = overview.load(
        tenant=tenant, limit=limit, selection=replace(selection, country=code), today=today
    )
    имя = next((name for name, uid in snapshot.unit_ids.items() if uid == unit_id and unit_id), "")
    history = tuple(row for row in snapshot.inspections if имя and row.unit_name == имя)
    if not history:
        return CountryView(code=code, snapshot=snapshot)
    return CountryView(code=code, snapshot=snapshot, unit_id=unit_id, unit_name=имя, history=history)


def countries(*, tenant: str) -> tuple[tuple[str, int], ...]:
    """Страны справочника с числом точек, крупные сверху. Точка без страны не считается."""
    счёт: dict[str, int] = {}
    for country, _city in queries.unit_geography(tenant=tenant).values():
        if country:
            счёт[country] = счёт.get(country, 0) + 1
    return tuple(sorted(счёт.items(), key=lambda пара: (-пара[1], пара[0])))
```

Примечание: точка без проверок в срезе не раскрывается (истории нет) — раскрывать пустоту незачем, строки такой точки в таблице тоже нет.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTEST_ADDOPTS="tests/test_web_country_data.py" make test`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/web/country.py tests/test_web_country_data.py
git commit -m "feat: данные экрана страны — снимок «Обзора» по стране и история точки (D260)"
```

---

### Task 2: Раздел «Страна» построен — реестр и тексты

**Files:**
- Modify: `src/web/sections.py` (строка `Section(key="country", ...)`: `built=True`)
- Modify: `src/web/app.py:65` (`SCREENS`)
- Modify: `tests/test_web_sections.py:35`
- Modify: `src/web/texts.py` (новые ключи `country.*`)

**Interfaces:**
- Produces: ключи текстов, которыми пользуется шаблон задачи 3 (список ниже — полный).

- [ ] **Step 1: Поменять ожидание теста реестра**

```python
def test_built_keys_are_the_built_screens() -> None:
    assert built_keys() == frozenset({"overview", "registry", "country", "admin", "users"})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTEST_ADDOPTS="tests/test_web_sections.py" make test`
Expected: FAIL — в `built_keys()` нет `country`.

- [ ] **Step 3: Пометить раздел и завести экран**

`src/web/sections.py`:

```python
    Section(key="country", path="/country", built=True, icon="globe"),
```

`src/web/app.py`:

```python
SCREENS = ("overview", "registry", "country", "admin", "users")
```

`src/web/texts.py` — добавить рядом с блоком `overview.*`:

```python
    "country.kicker": {"ru": "Страна", "en": "Country"},
    "country.choose.title": {"ru": "Выберите страну", "en": "Choose a country"},
    "country.choose.units": {"ru": "точек: {n}", "en": "units: {n}"},
    "country.choose.empty": {
        "ru": "В справочнике нет ни одной пиццерии со страной.",
        "en": "No pizzeria in the directory has a country.",
    },
    "country.summary": {
        "ru": "Проверок: {inspections} · средняя: {average} · не проверено точек: {unchecked}",
        "en": "Inspections: {inspections} · average: {average} · units not inspected: {unchecked}",
    },
    "country.units.title": {"ru": "Пиццерии страны", "en": "Pizzerias of the country"},
    "country.units.hint": {
        "ru": "Последняя проверка каждой точки. Нажмите строку — откроется история проверок.",
        "en": "Latest inspection of each unit. Click a row to open its inspection history.",
    },
    "country.units.empty": {
        "ru": "В этой стране за выбранный период проверок нет.",
        "en": "No inspections in this country for the selected period.",
    },
    "country.history.title": {"ru": "История проверок", "en": "Inspection history"},
    "country.history.latest": {"ru": "последняя", "en": "latest"},
    "country.history.card": {"ru": "Карточка пиццерии", "en": "Pizzeria card"},
    "country.history.close": {"ru": "Свернуть", "en": "Collapse"},
    "country.systemic.title": {"ru": "Что системно болит в стране", "en": "Systemic issues in the country"},
    "country.systemic.empty": {
        "ru": "Пунктов, нарушенных сразу в нескольких пиццериях, нет.",
        "en": "No item is violated in more than one pizzeria.",
    },
    "country.zones.title": {"ru": "Где страна теряет больше всего", "en": "Where the country loses most"},
    "country.zones.empty": {"ru": "Потерь по зонам за период нет.", "en": "No zone losses for the period."},
```

Если в `texts.py` есть проверка «ключ на обоих языках» (`tests/test_web_texts*.py`), она покрывает новые ключи сама.

- [ ] **Step 4: Run tests**

Run: `PYTEST_ADDOPTS="tests/test_web_sections.py tests/test_web_app.py" make test`
Expected: `test_web_sections` PASS. `test_web_app` на сборке приложения упадёт `SectionRegistryError` о `country` без экрана **или** о дубле маршрута `/country` — это ожидаемо до задачи 3; не коммитить до зелёного, задачи 2 и 3 коммитятся вместе.

---

### Task 3: Маршрут и шаблон экрана страны

**Files:**
- Modify: `src/web/app.py` (импорт `from . import country as country_data`; вызов `_register_country(app, conf)` сразу после `_register_overview`; новая функция `_register_country`)
- Create: `src/web/templates/country/index.html`
- Test: `tests/test_web_country.py`

**Interfaces:**
- Consumes: `country_data.load`, `country_data.countries`, `country_data.normalize_code`, `country_data.CountryView` (задача 1); `overview_data.Selection`, `overview_data.PERIODS`; `_pick`, `_url`, `_lang`, `REGISTRY_LIMIT` из `app.py`.
- Produces: эндпоинты `country_index` (`GET /country`) и `country` (`GET /country/<code>`); адрес раскрытой точки `/country/<code>?unit=<id>#unit-<id>` — им пользуется задача 4.

- [ ] **Step 1: Write the failing test**

```python
"""Экран «Страна»: пиццерии страны, раскрытие истории, фильтры в адресе."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace

import pytest
from flask.testing import FlaskClient
from test_web_app import ТЕНАНТ
from test_web_overview import снимок, строка
from web_harness import войти, подменить_двери, собрать

from src.web import app as app_mod
from src.web import country as cn


@pytest.fixture
def стенд(monkeypatch: pytest.MonkeyPatch) -> Iterator[FlaskClient]:
    подменить_двери(monkeypatch, tenant=ТЕНАНТ)
    with собрать(tenant=ТЕНАНТ).test_client() as client:
        assert войти(client).status_code == 302
        yield client


def данные() -> cn.CountryView:
    первая = строка("Батуми-1", 90.0, "B")
    return cn.CountryView(
        code="GE",
        snapshot=replace(снимок(inspections=(первая,)), unit_ids={"Батуми-1": "u-1"}, points=(), countries=(("GE", 1),)),
    )


def открыть(client: FlaskClient, monkeypatch: pytest.MonkeyPatch, вид: cn.CountryView, адрес: str) -> str:
    monkeypatch.setattr(app_mod.country_data, "load", lambda **_: вид)
    ответ = client.get(адрес)
    assert ответ.status_code == 200, ответ.status_code
    return ответ.get_data(as_text=True)


def test_экран_страны_называет_страну_словом(стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch) -> None:
    страница = открыть(стенд, monkeypatch, данные(), "/country/GE")
    assert "Грузия" in страница or "Georgia" in страница


def test_мусорный_код_страны_не_роняет_экран(стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch) -> None:
    видели: list[str] = []

    def load(**kw: object) -> cn.CountryView:
        видели.append(str(kw["code"]))
        return replace(данные(), code=str(kw["code"]))

    monkeypatch.setattr(app_mod.country_data, "load", load)
    assert стенд.get("/country/ge").status_code == 200
    assert стенд.get("/country/%3Cs%3E").status_code == 200
    assert видели == ["GE", ""]


def test_раскрытая_точка_показывает_историю_и_карточку(стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch) -> None:
    вид = данные()
    вид = replace(вид, unit_id="u-1", unit_name="Батуми-1", history=вид.snapshot.inspections)
    страница = открыть(стенд, monkeypatch, вид, "/country/GE?unit=u-1")
    assert 'id="unit-u-1"' in страница
    assert "/units/u-1" in страница
    assert f"/inspections/{вид.history[0].id}" in страница


def test_ссылки_строк_сохраняют_фильтры_и_язык(стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch) -> None:
    вид = данные()
    точка = app_mod.overview_data.PointRow(
        unit="Батуми-1", city="batumi", country="GE", inspection_id=вид.snapshot.inspections[0].id,
        when=вид.snapshot.inspections[0].inspection_date, grade="B", pct=90.0, delta=None,
        worst_zone_ru="", worst_zone_en="", critical=0,
    )
    вид = replace(вид, snapshot=replace(вид.snapshot, points=(точка,)))
    страница = открыть(стенд, monkeypatch, вид, "/country/GE?period=d90&grade=B&lang=en")
    assert "unit=u-1" in страница
    строка_ссылки = next(ч for ч in страница.split('"') if "unit=u-1" in ч)
    assert "period=d90" in строка_ссылки and "grade=B" in строка_ссылки and "lang=en" in строка_ссылки


def test_пустая_страна_говорит_словами(стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch) -> None:
    вид = replace(данные(), snapshot=replace(данные().snapshot, points=(), inspections=(), systemic=(), zone_losses=()))
    страница = открыть(стенд, monkeypatch, вид, "/country/GE")
    assert "проверок нет" in страница or "No inspections" in страница


def test_список_стран_с_одной_страной_сразу_ведёт_в_неё(стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_mod.country_data, "countries", lambda **_: (("GE", 3),))
    ответ = стенд.get("/country")
    assert ответ.status_code == 302
    assert ответ.headers["Location"].endswith("/country/GE")


def test_список_стран_показывает_все(стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_mod.country_data, "countries", lambda **_: (("GE", 3), ("RS", 2)))
    страница = стенд.get("/country").get_data(as_text=True)
    assert "/country/GE" in страница and "/country/RS" in страница
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTEST_ADDOPTS="tests/test_web_country.py" make test`
Expected: FAIL — `AttributeError: module 'src.web.app' has no attribute 'country_data'`.

- [ ] **Step 3: Маршрут**

В `src/web/app.py`, импорт рядом с `overview_data`:

```python
from . import country as country_data
```

В `create_app` после `_register_overview(app, conf)`:

```python
    _register_country(app, conf)
```

Функция — сразу после `_register_overview`:

```python
def _register_country(app: Flask, conf: Settings) -> None:
    """Раздел «Страна»: работа с одной страной (D260, D262).

    Экран — «Обзор» с отбором по стране; своих подсчётов у него нет. Отбор
    живёт в адресе, как на «Обзоре»: ссылку на «Грузия, за 90 дней, Батуми-1
    раскрыта» отправляют коллеге, и он видит ровно это.
    """

    @app.get(section("country").path, endpoint="country_index")
    def country_index() -> Any:
        страны = country_data.countries(tenant=conf.tenant)
        if len(страны) == 1:
            return redirect(_url("country", code=страны[0][0], lang=_lang(conf)))
        return render_template("country/index.html", view=None, choices=страны, lang=_lang(conf))

    @app.get(section("country").path + "/<code>", endpoint="country")
    def country(code: str) -> str:
        язык = _lang(conf)
        код = country_data.normalize_code(code)
        selection = overview_data.Selection(
            city=request.args.get("city", "").strip()[:80],
            grade=request.args.get("grade", "").strip().upper()[:1],
            period=request.args.get("period", "all").strip()[:8],
            sort=request.args.get("sort", "score").strip()[:8],
        )
        вид = country_data.load(
            tenant=conf.tenant,
            limit=REGISTRY_LIMIT,
            code=код,
            selection=selection,
            unit_id=request.args.get("unit", "").strip()[:64],
        )

        def отбор(**изменения: str) -> str:
            """Адрес того же экрана с изменённым срезом; умолчания выпадают."""
            параметры = {
                "city": selection.city,
                "grade": selection.grade,
                "period": selection.period,
                "sort": selection.sort,
                "unit": вид.unit_id,
                "lang": язык,
                **изменения,
            }
            умолчания = {"period": "all", "sort": "score"}
            живые = {к: з for к, з in параметры.items() if з and умолчания.get(к) != з}
            return _url("country", code=код or "-", **живые)

        def раскрыть(unit_id: str) -> str:
            """Строка точки: раскрыть её, а раскрытую — свернуть. Якорь — к строке."""
            if unit_id == вид.unit_id:
                return отбор(unit="")
            return отбор(unit=unit_id) + f"#unit-{unit_id}"

        чипы = (
            _pick(
                label=t("overview.filter.city", язык),
                empty_title=t("overview.filter.all_cities", язык),
                current=selection.city,
                values=вид.snapshot.cities,
                href=lambda значение: отбор(city=значение, unit=""),
                title=lambda код_города: city_title(код_города, язык) or код_города,
            ),
            _pick(
                label=t("overview.filter.grade", язык),
                empty_title=t("overview.filter.all_grades", язык),
                current=selection.grade,
                values=вид.snapshot.grades,
                href=lambda значение: отбор(grade=значение, unit=""),
            ),
            _pick(
                label=t("overview.filter.period", язык),
                empty_title=t("overview.period.all", язык),
                current="" if selection.period == "all" else selection.period,
                values=tuple((к, None) for к in overview_data.PERIODS if к != "all"),
                href=lambda значение: отбор(period=значение or "all", unit=""),
                title=lambda к: t("overview.period." + к, язык),
            ),
        )
        return render_template(
            "country/index.html",
            view=вид,
            choices=country_data.countries(tenant=conf.tenant),
            picks=чипы,
            select_url=отбор,
            open_url=раскрыть,
            reset_url=_url("country", code=код or "-", lang=язык),
            registry_path=section("registry").path,
            grade_tone=view.grade_tone,
            level_tone=view.level_tone,
            item_titles=_item_titles(conf, язык),
            lang=язык,
        )
```

Сверить с фактом перед вставкой: имена ключей `overview.filter.all_grades` и `overview.filter.city` / `all_cities` — посмотреть в `_register_overview` (строки ~396–425) и взять те же; если ключ буквы называется иначе — взять фактический. `redirect` уже импортирован в `app.py`? — `grep -n "^from flask import" src/web/app.py`, добавить при отсутствии. Пустой код страны отдаётся адресом `/country/-` — `normalize_code("-")` вернёт `""`, экран покажет «проверок нет».

- [ ] **Step 4: Шаблон**

`src/web/templates/country/index.html`:

```html
{#
  Экран «Страна» — работа с одной страной (D260, D262). Ни одного вычисления:
  всё приходит из `src/web/country.py`, который берёт цифры «Обзора».
  Блоков предписаний, экшн-планов и плана проверок здесь нет, пока их нет в
  продукте (D217) — они придут своими волнами спеки.
#}{% extends "base.html" %}
{% from "_pick.html" import pick %}
{% block title %}{{ t('section.country.title') }}{% endblock %}

{% block body %}
{% if view is none %}
  <div class="ov-head"><div class="ov-head__main">
    <div class="ov-head__kicker">{{ t('country.kicker') }}</div>
    <h1 class="ov-head__title">{{ t('country.choose.title') }}</h1>
  </div></div>
  <section class="ov-card">
    {% if choices %}
      <div class="ov-table">
        {% for code, n in choices %}
          <a class="ov-table__row" href="{{ url('/country/' ~ code) }}?lang={{ lang }}">
            <span class="ov-cell__name">{{ country_title(code) or code }}</span>
            <span class="ov-cell__muted">{{ t('country.choose.units', n=n) }}</span>
          </a>
        {% endfor %}
      </div>
    {% else %}
      <div class="ov-card__empty">{{ t('country.choose.empty') }}</div>
    {% endif %}
  </section>
{% else %}
  {% set data = view.snapshot %}
  <div class="ov-head">
    <div class="ov-head__main">
      <div class="ov-head__kicker">{{ t('country.kicker') }}</div>
      <h1 class="ov-head__title">{{ country_title(view.code) or view.code or '—' }}</h1>
      <div class="ov-card__hint">
        {{ t('country.summary',
             inspections=data.inspections|length,
             average=('—' if data.average is none else '%.1f'|format(data.average)),
             unchecked=data.unchecked) }}
      </div>
    </div>
  </div>

  <div class="ov-filters">
    <span class="ov-filters__label">{{ t('overview.filter.title') }}</span>
    {% for chip in picks %}{{ pick(chip) }}{% endfor %}
    <span class="ov-filters__gap"></span>
    <a class="ov-chip ov-chip--reset" href="{{ reset_url }}">{{ t('overview.filter.reset') }}</a>
  </div>

  <section class="ov-card">
    <div class="ov-card__title">{{ t('country.units.title') }}</div>
    <div class="ov-card__hint">{{ t('country.units.hint') }}</div>
    {% if data.points %}
      <div class="ov-table ov-table--points">
        <div class="ov-table__head">
          <span>{{ t('overview.points.unit') }}</span>
          <span>{{ t('overview.points.city') }}</span>
          <span class="ov-num">{{ t('overview.points.grade') }}</span>
          <span class="ov-num">{{ t('overview.points.score') }}</span>
          <span class="ov-num">{{ t('overview.points.delta') }}</span>
          <span>{{ t('overview.points.zone') }}</span>
          <span class="ov-num">{{ t('overview.points.date') }}</span>
        </div>
        {% for point in data.points %}
          {% set unit_id = data.unit_ids.get(point.unit, '') %}
          <a class="ov-table__row{% if unit_id and unit_id == view.unit_id %} is-open{% endif %}"
             {% if unit_id %}id="unit-{{ unit_id }}" href="{{ open_url(unit_id) }}"{% else %}href="{{ url(registry_path ~ '/' ~ point.inspection_id) }}?lang={{ lang }}"{% endif %}>
            <span class="ov-cell__name">{{ point.unit }}</span>
            <span class="ov-cell__muted">{{ city_title(point.city) or '—' }}</span>
            <span class="ov-num"><span class="grade tag {{ grade_tone(point.grade) }}">{{ point.grade }}</span></span>
            <span class="ov-num ov-num--strong">{{ '%.1f'|format(point.pct) }}</span>
            <span class="ov-num{% if point.delta is not none and point.delta < 0 %} ov-num--err{% endif %}">
              {{ '—' if point.delta is none else ('%+.1f'|format(point.delta)) }}
            </span>
            <span class="ov-cell__muted">{{ (point.worst_zone_ru if lang == 'ru' else point.worst_zone_en) or '—' }}</span>
            <span class="ov-num ov-cell__muted">{{ point.when }}</span>
          </a>
          {% if unit_id and unit_id == view.unit_id %}
            <div class="ov-history">
              <div class="ov-card__title">{{ t('country.history.title') }} · {{ view.unit_name }}</div>
              {% for row in view.history %}
                <a class="ov-row" href="{{ url(registry_path ~ '/' ~ row.id) }}?lang={{ lang }}">
                  <span class="ov-num ov-cell__muted">{{ row.inspection_date }}</span>
                  <span class="grade tag {{ grade_tone(row.grade) }}">{{ row.grade }}</span>
                  <span class="ov-num ov-num--strong">{{ '%.1f'|format(row.pct) }}</span>
                  {% if loop.first %}<span class="ov-cell__muted">{{ t('country.history.latest') }}</span>{% endif %}
                </a>
              {% endfor %}
              <a class="btn btn--sm" href="{{ url('/units/' ~ view.unit_id) }}?lang={{ lang }}">{{ t('country.history.card') }}</a>
              <a class="btn btn--sm" href="{{ open_url(view.unit_id) }}">{{ t('country.history.close') }}</a>
            </div>
          {% endif %}
        {% endfor %}
      </div>
    {% else %}
      <div class="ov-card__empty">{{ t('country.units.empty') }}</div>
    {% endif %}
  </section>

  <section class="ov-card">
    <div class="ov-card__title">{{ t('country.systemic.title') }}</div>
    {% if data.systemic %}
      {% for item in data.systemic %}
        <div class="ov-row">
          <span class="tag {{ level_tone(item.level) }}">{{ item.level }}</span>
          <span class="ov-cell__name">{{ item_titles.get(item.code, item.code) }}</span>
          <span class="ov-cell__muted">{{ item.code }} · {{ item.units }}</span>
        </div>
      {% endfor %}
    {% else %}
      <div class="ov-card__empty">{{ t('country.systemic.empty') }}</div>
    {% endif %}
  </section>

  <section class="ov-card">
    <div class="ov-card__title">{{ t('country.zones.title') }}</div>
    {% if data.zone_losses %}
      {% for zone in data.zone_losses %}
        <div class="ov-row">
          <span class="ov-cell__name">{{ zone.name_ru if lang == 'ru' else zone.name_en }}</span>
          <span class="ov-num">{{ '%.1f'|format(zone.loss) }}</span>
          <span class="ov-cell__muted">{{ '%.1f'|format(zone.share) }}%</span>
        </div>
      {% endfor %}
    {% else %}
      <div class="ov-card__empty">{{ t('country.zones.empty') }}</div>
    {% endif %}
  </section>
{% endif %}
{% endblock %}
```

Сверить `item_titles`: как «Обзор» показывает название пункта в системных нарушениях — `grep -n "item_titles" src/web/templates/overview/index.html` — и взять то же выражение, если оно отличается от `.get(code, code)`. Стиль `.ov-history` и `.is-open` — одна правка в стилях «Обзора» (`grep -rn "ov-table__row" src/web/static`): отступ слева, фон `var(--surface-2)` или ближайший токен линейки; если #461 влит — токен из него.

- [ ] **Step 5: Run tests**

Run: `PYTEST_ADDOPTS="tests/test_web_country.py tests/test_web_country_data.py tests/test_web_sections.py tests/test_web_app.py" make test`
Expected: всё PASS.

- [ ] **Step 6: Проверка заслона на сломанном входе**

Временно заменить в `country_data.load` `unit_id=unit_id` на `unit_id=""` в строке возврата (раскрытие не передаётся) и прогнать `tests/test_web_country.py::test_раскрытая_точка_показывает_историю_и_карточку` — тест обязан упасть на `id="unit-u-1"`. Вернуть правку, `git diff src/web/country.py` пуст.

- [ ] **Step 7: Commit**

```bash
git add src/web/app.py src/web/sections.py src/web/texts.py src/web/templates/country tests/test_web_country.py tests/test_web_sections.py src/web/static
git commit -m "feat: экран «Страна» — пиццерии страны, история точки, фильтры в адресе (D260, D262)"
```

---

### Task 4: «Обзор» ведёт в страну

**Files:**
- Modify: `src/web/templates/overview/index.html` (строка таблицы точек ~277; строка разбивки по городам ~90; кнопка «Назначить проверку» ~34)
- Modify: `src/web/app.py` (`_register_overview`: помощник `в_страну`, передать в шаблон)
- Test: `tests/test_web_overview.py`

**Interfaces:**
- Consumes: эндпоинт `country` (задача 3), адрес `/country/<code>?unit=<id>#unit-<id>`.
- Produces: —

- [ ] **Step 1: Write the failing test** (дописать в `tests/test_web_overview.py`)

```python
def точка(unit: str, country: str, city: str) -> ov.PointRow:
    return ov.PointRow(
        unit=unit, city=city, country=country, inspection_id="11111111-2222-3333-4444-000000000009",
        when=date(2026, 9, 20), grade="B", pct=90.0, delta=None, worst_zone_ru="", worst_zone_en="", critical=0,
    )


def test_точка_на_обзоре_ведёт_в_страну_с_раскрытой_точкой(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    данные = снимок(points=(точка("Батуми-1", "GE", "batumi"),), unit_ids={"Батуми-1": "u-1"})
    страница = показать(стенд, monkeypatch, данные)
    assert "/country/GE?" in страница and "unit=u-1" in страница


def test_точка_без_страны_ведёт_в_карточку_как_раньше(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    данные = снимок(points=(точка("Без-1", "", ""),), unit_ids={"Без-1": "u-9"})
    страница = показать(стенд, monkeypatch, данные)
    assert "/units/u-9" in страница
    assert "/country/?" not in страница and "/country/-" not in страница


def test_город_в_разбивке_ведёт_в_страну_с_городом(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    город = ov.CityRow(city="batumi", country="GE", units=1, inspections=1, average=90.0,
                       comparable=True, grades=(("B", 1),), critical=0)
    страница = показать(стенд, monkeypatch, снимок(breakdown=(город,)))
    assert "/country/GE?" in страница and "city=batumi" in страница


def test_назначить_проверку_на_обзоре_нет(стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch) -> None:
    страница = показать(стенд, monkeypatch, снимок())
    assert t_ru("overview.assign") not in страница
```

где `t_ru` — `lambda key: texts.t(key, "ru")` (импорт `from src.web.texts import t as _t`; `def t_ru(key: str) -> str: return _t(key, "ru")`). Если уже есть тест, требующий кнопку «Назначить проверку» на «Обзоре», — он удаляется: кнопка снята решением D260.

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTEST_ADDOPTS="tests/test_web_overview.py" make test`
Expected: 4 новых FAIL (ссылки ведут в `/units/` и в реестр, кнопка на месте).

- [ ] **Step 3: Помощник и шаблон**

В `_register_overview`, рядом с `в_реестр`:

```python
        def в_страну(country: str, **параметры: str) -> str:
            """Экран страны с этим срезом (D260). Период уезжает вместе с человеком."""
            живые = {
                "period": selection.period if selection.period != "all" else "",
                "lang": _lang(conf),
                **параметры,
            }
            return _url("country", code=country, **{к: з for к, з in живые.items() if з})
```

и в `render_template(...)`: `country_url=в_страну,`.

В шаблоне, строка точки:

```html
          {% set unit_id = unit_ids.get(point.unit) %}
          <a class="ov-table__row"
             href="{% if unit_id and point.country %}{{ country_url(point.country, unit=unit_id) }}#unit-{{ unit_id }}{% elif unit_id %}{{ url('/units/' ~ unit_id) }}{% else %}{{ url(registry_path ~ '/' ~ point.inspection_id) }}{% endif %}">
```

Строка разбивки — `href="{{ country_url(row.country, city=row.city) if row.country else registry_url(city=row.city) }}"`.

Кнопку `ov-head__cta` («Назначить проверку») удалить вместе с комментарием над ней; `plans_path` из `render_template` убрать, если больше не используется (`grep -n plans_path src/web/templates`).

Комментарии в шаблоне над строками переписать: строка точки ведёт в страну с раскрытой точкой (D260), без страны — в карточку.

- [ ] **Step 4: Run tests**

Run: `PYTEST_ADDOPTS="tests/test_web_overview.py tests/test_web_country.py" make test`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/web/app.py src/web/templates/overview/index.html tests/test_web_overview.py
git commit -m "feat: «Обзор» ведёт в страну — точка раскрыта, город выбран; «Назначить проверку» снята (D260)"
```

---

### Task 5: Проверка целиком, доки, смоук

**Files:**
- Modify: `CHANGELOG.md`, `docs/` — где перечислены разделы веба (`grep -rln "Страна\|/country" docs README.md`)
- Modify: реестр пользовательских материалов, если раздел в нём описан (`grep -rln "в разработке" docs`)

- [ ] **Step 1: Полный прогон**

Run: `make check` и `make regress`
Expected: зелёное; `regress` — belgrade-1 97.5% A 5×D1, belgrade-2 97.0% A 6×D1. Тесты базы требуют туннель `localhost:55432 → muspelheim:15432`; упал туннель — `launchctl kickstart -k gui/$(id -u)/io.garva.mac-stands-tunnel` и повтор. Пропущенное из-за окружения — назвать в отчёте, не считать зелёным.

- [ ] **Step 2: Доки**

`CHANGELOG.md` — запись за дату: «Раздел «Страна»: пиццерии страны с историей проверок, системные нарушения и потери по зонам, фильтры; клик по точке и городу на «Обзоре» ведёт в страну; кнопка «Назначить проверку» снята с «Обзора» до раздела действий УК (D260, D262, D264)». Каждое место в `docs/`, где «Страна» названа непостроенной, — исправить тем же коммитом.

- [ ] **Step 3: Смоук на стенде MUSPELHEIM**

Поднять ветку на стенде `mac-stands` (скилл `muspelheim`; на Маке стендов нет). Открыть `/overview` → клик по строке Батуми-1 → `/country/GE?unit=…#unit-…`, строка раскрыта, в истории есть последняя проверка, «Карточка пиццерии» открывается. Переключить язык — страна и раскрытие на месте. `/country/zz` — 200 и «проверок нет». Снимки экрана — через агента `norma`, в контекст главной сессии не читать.

- [ ] **Step 4: Commit и PR**

```bash
git add CHANGELOG.md docs
git commit -m "docs: раздел «Страна» построен — CHANGELOG и описание разделов"
git push -u origin HEAD
gh pr create --title "Экран «Страна», волна 1 (D260)" --body "…"
```

Раскатка — только по отдельному «да» владельца (скилл `deploy-window`).
