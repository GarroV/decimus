# Админка чек-листов, волна 2: раскладка — план

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** «Методика» становится экраном из двух частей: слева колонка чек-листов с блоком «Бот», справа правка выбранного; с адаптивом до телефона.

**Architecture:** Меняется только веб (`src/web`): данные колонки собираются из уже существующей двери перечня (`lists_door.overview`, `lists_door.summary`), разметка — обёрткой `.mx-shell` вокруг нынешнего экрана, заведение чек-листа — новой панелью `?panel=new` в том же слое, что панель пункта. Хранилище, MCP, бот и база не трогаются. Блок «Бот» в этой волне показывает то, что есть сегодня, — чек-лист, применённый к проду; настоящий доступ в боте — волна 3. Шапка чек-листа (правка названия на месте, дата издания, метка «в боте») в этой волне не меняется — она переезжает в волну 3 вместе с доступом в боте.

**Tech Stack:** Flask + Jinja, CSS на токенах `dodo-ds.css`, `methodology.js` без сборки, pytest + `tests/web_harness.py`.

**Spec:** `docs/superpowers/specs/2026-09-28-checklist-admin-design.md` (согласована, D227), раздел «Экран».

## Global Constraints

- Строки интерфейса — только через `src/web/texts.py`, обе локали `ru` и `en` одним коммитом (правило i18n проекта).
- Сущности связываются кодом чек-листа, показываются названием (CLAUDE.md проекта).
- Код чек-листа держится в КАЖДОМ адресе и действии экрана явно (#382, `_который_показан`).
- Оценка не считается в вебе ни в каком виде (контракт `engine-not-imported`, `tests/test_web_bounds.py`).
- Цвета, отступы, радиусы — токены (`var(--space-*)`, `var(--line)` …), без литералов.
- Ширины: колонка ≈ 18rem; точки перелома 1280px, 1024px, 52rem (832px — уже есть, телефон).
- Прямой речи владельца в коде не прибавляется (`tests/test_owner_quotes_no_new.py`).

## Review Focus

- Чек-лист с неопубликованным изданием или без `meta.json` — строка колонки не падает, число пунктов «—».
- Переход по чек-листу из колонки при открытой панели пункта — обычный переход страницы, панель закрыта, `?checklist=` новый, `?item=` сброшен.
- Колонка поверх подложки панели: клик по чек-листу в колонке при открытой панели ведёт на чек-лист, а не закрывает панель (≥1280px).
- `_действие` в `tests/test_web_checklists_screen.py` берёт первый `action="/admin/checklists…"` на странице — форма заведения рендерится ТОЛЬКО при `?panel=new`, иначе тесты перечня возьмут чужую форму.
- Телефон без `?checklist=` — первым экраном список; с `?checklist=` — чек-лист; горизонтальной прокрутки нет ни на одной ширине.

---

### Task 1: Строки колонки чек-листов

**Files:**
- Modify: `src/web/methodology.py` (рядом с `checklists_overview`, ~строка 716)
- Test: `tests/test_web_methodology_rail.py` (новый)

**Interfaces:**
- Consumes: `lists_door.overview(store) -> list[Overview]` (`src/mcp/checklists.py:136`, поля `space, code, name_ru, name_en, state, in_production, version`), `lists_door.summary(store) -> Summary | None` (`checklists.py:229`, поле `items: int`), `store_for(store, code)`.
- Produces: `RailRow` и `checklist_rail(store: Store) -> tuple[RailRow, ...]`.

- [ ] **Step 1: Failing test**

```python
"""D222: колонка чек-листов — порядок, число пунктов, метка «бот»."""
from __future__ import annotations

from pathlib import Path

from mcp_checklist_harness import build_edition  # тот же помощник, что у test_web_checklists_screen
from src.web import methodology as method


def test_колонка_в_работе_раньше_черновиков_снятые_в_конце(tmp_path: Path) -> None:
    store = build_edition(tmp_path)  # хранилище с bizdev в проде
    method.create_checklist(store, tenant="default", author="t", code="rnd", name_ru="РНД", name_en="RND")
    method.create_checklist(store, tenant="default", author="t", code="old", name_ru="Старый", name_en="Old")
    method.set_checklist_state(store, tenant="default", author="t", code="old", state="retired")

    rows = method.checklist_rail(store)

    assert [r.code for r in rows] == ["bizdev", "rnd", "old"]
    assert rows[0].in_bot is True and rows[1].in_bot is False
    assert rows[0].items and rows[0].items > 0
    assert rows[1].items is None  # черновик без опубликованного издания — «—», а не отказ
```

Имена `create_checklist` / `set_checklist_state` сверить с `src/web/methodology.py` (двери перечня под `_mount_checklists`, `app.py:1211, 1235`) и подставить фактические; помощник `build_edition` — из `tests/mcp_checklist_harness.py`.

- [ ] **Step 2:** `./.venv/bin/python -m pytest tests/test_web_methodology_rail.py -q` → FAIL: `checklist_rail` нет.

- [ ] **Step 3: Implementation** (в `src/web/methodology.py`)

```python
#: Порядок групп в колонке: годное к работе — сверху, снятое — свёрнуто внизу.
RAIL_ORDER = {ACTIVE: 0, DRAFT: 1, RETIRED: 2}


@dataclass(frozen=True)
class RailRow:
    """Строка колонки чек-листов (D222)."""

    code: str
    name_ru: str
    name_en: str
    state: str
    in_bot: bool          # волна 2: применён к проду; волна 3 заменит доступом в боте
    items: int | None     # пунктов с нарушением в опубликованном издании; None — издания нет


def checklist_rail(store: Store) -> tuple[RailRow, ...]:
    """Чек-листы для колонки, в порядке «в работе → черновики → снятые»."""
    строки = []
    for c in checklists_overview(store):
        try:
            сводка = lists_door.summary(for_code(store, c.code))
        except McpError:
            сводка = None
        строки.append(RailRow(c.code, c.name_ru, c.name_en, c.state, c.in_production,
                              сводка.items if сводка else None))
    return tuple(sorted(строки, key=lambda r: (RAIL_ORDER.get(r.state, 9), r.name_ru.casefold())))
```

(`ACTIVE`, `DRAFT`, `RETIRED` уже импортированы рядом с `CHECKLIST_STATES`, `methodology.py:693`; если нет — импортировать оттуда же, откуда берётся `CHECKLIST_STATES`.)

- [ ] **Step 4:** тот же прогон → PASS. Порча: убрать `sorted(...)` → тест краснеет; вернуть.
- [ ] **Step 5:** `git commit -m "feat(web): строки колонки чек-листов (D222)"`

---

### Task 2: Каркас экрана — колонка слева, правка справа

**Files:**
- Modify: `src/web/app.py` — `_render_methodology` (~1377–1537): передать `rail=method.checklist_rail(state.store)` и `picking=not request.args.get("checklist")`.
- Modify: `src/web/templates/methodology/index.html` — обернуть всё тело блока `body` (от `.mx-bar` до конца `section.mx-items`) в `<div class="mx-shell{% if picking %} mx-shell--pick{% endif %}"><aside class="mx-rail">…</aside><div class="mx-main">…</div></div>`; слой панели (`.mx-layer`) остаётся ВНЕ `.mx-shell`.
- Modify: `src/web/texts.py` — ключи ниже.
- Test: `tests/test_web_methodology_screen.py` (дописать).

**Interfaces:**
- Consumes: `checklist_rail`, `RailRow` (Task 1).
- Produces: разметка `aside.mx-rail`, `.mx-rail__bot`, `a.mx-rail__row[href]` (ссылка БЕЗ `data-mx-open` — переход страницы), `.mx-rail__row.is-on` у показанного, `details.mx-rail__retired` для снятых.

Колонка:

```jinja
<aside class="mx-rail" aria-label="{{ t('methodology.rail.title') }}">
  <div class="mx-rail__bot">
    <div class="mx-rail__head">{{ t('methodology.rail.bot') }}</div>
    {% set in_bot = rail | selectattr('in_bot') | list %}
    <div class="mx-rail__bot-list">{% for r in in_bot %}{{ r.name_ru if lang == 'ru' else (r.name_en or r.name_ru) }}{% if not loop.last %}, {% endif %}{% else %}{{ t('methodology.rail.bot_none') }}{% endfor %}</div>
    <a class="mx-rail__link" href="{{ url_for('checklists', lang=lang) }}">{{ t('methodology.rail.bot_manage') }}</a>
  </div>
  <div class="mx-rail__head row">{{ t('methodology.rail.title') }}
    <a class="btn btn--sm" href="{{ href(panel='new', item='') }}" data-mx-open>{{ t('methodology.rail.new') }}</a></div>
  {% for r in rail if r.state != 'retired' %}{{ rail_row(r) }}{% endfor %}
  {% set retired = rail | selectattr('state', 'equalto', 'retired') | list %}
  {% if retired %}<details class="mx-rail__retired mx-more"><summary>{{ t('methodology.rail.retired', count=retired|length) }}</summary>
    {% for r in retired %}{{ rail_row(r) }}{% endfor %}</details>{% endif %}
</aside>
```

Макрос `rail_row(r)`: `<a class="mx-rail__row{% if r.code == checklist_code %} is-on{% endif %}" href="{{ url_for('methodology', checklist=r.code, lang=lang) }}">` → имя, строка ниже `{{ r.items if r.items is not none else '—' }} · {{ t('checklists.state.' ~ r.state) }}{% if r.in_bot %} · {{ t('methodology.rail.bot_mark') }}{% endif %}`. Никаких `data-mx-item` в колонке (тест `test_web_methodology_screen.py:307` ищет `data-mx-item`).

Тексты (`ru` / `en`): `methodology.rail.title` «Чек-листы» / «Checklists»; `methodology.rail.bot` «Бот» / «Bot»; `methodology.rail.bot_none` «ни одного» / «none»; `methodology.rail.bot_manage` «Настроить» / «Manage»; `methodology.rail.new` «+ Новый» / «+ New»; `methodology.rail.retired` «Снятые ({count})» / «Retired ({count})»; `methodology.rail.bot_mark` «бот» / «bot».

- [ ] **Step 1: Failing tests** (в `tests/test_web_methodology_screen.py`, той же обвязкой, что соседние тесты файла)

```python
def test_колонка_называет_все_чек_листы_и_отмечает_показанный(стенд, хранилище) -> None:
    # хранилище: bizdev в проде + черновик rnd (как в test_web_checklists_screen)
    страница = стенд.get("/admin?checklist=rnd").get_data(as_text=True)
    колонка = страница.split('<aside class="mx-rail"', 1)[1].split("</aside>", 1)[0]
    assert 'href="/admin?checklist=bizdev' in колонка
    assert 'mx-rail__row is-on" href="/admin?checklist=rnd' in колонка
    assert "data-mx-open" not in колонка.split('class="mx-rail__head row"', 1)[1].replace(
        'href="/admin?checklist=rnd&amp;panel=new', "")  # только «+ Новый» открывает панель


def test_без_чек_листа_в_адресе_экран_помечен_выбором(стенд, хранилище) -> None:
    assert "mx-shell--pick" in стенд.get("/admin").get_data(as_text=True)
    assert "mx-shell--pick" not in стенд.get("/admin?checklist=bizdev").get_data(as_text=True)
```

Фикстуры `стенд`/`хранилище` — взять фактические из `tests/test_web_methodology_screen.py` (там же, где тест на `mx-drawer__code`); точную форму адреса `href(panel='new')` сверить по выводу — `href()` строит адрес с `checklist=` первым.

- [ ] **Step 2:** прогон → FAIL (нет `mx-rail`).
- [ ] **Step 3:** правки `app.py`, шаблона, текстов по описанию выше.
- [ ] **Step 4:** `./.venv/bin/python -m pytest tests/test_web_*.py -q` → всё зелёное (в том числе `test_web_checklists_screen.py:172` — на `/admin?checklist=rnd` нет `CLN01`: колонка кодов пунктов не показывает).
- [ ] **Step 5:** commit `feat(web): «Методика» — колонка чек-листов слева (D222)`.

---

### Task 3: Заведение чек-листа панелью справа

**Files:**
- Modify: `src/web/app.py` — `METHODOLOGY_PANELS = ("scoring", "versions", "new")` (~1374); маршрут `checklists_create` (`app.py:1211`) при успехе и `request.form.get("back") == "admin"` отвечает `redirect(url_for("methodology", checklist=заведён.code, lang=...))`, при отказе — `_render_methodology(conf, notice=None, failure=str(отказ), panel="new")`.
- Modify: `src/web/templates/methodology/index.html` — ветка `{% elif panel == 'new' %}` в `aside.mx-drawer`.
- Test: `tests/test_web_checklists_screen.py` (дописать).

Панель: заголовок `t('checklists.create.title')` (ключ уже есть на `/admin/checklists` — сверить в `texts.py:~834`), форма `method="post" action="{{ url_for('checklists_create') }}?lang={{ lang }}"` с полями `code`, `name_ru`, `name_en` (те же имена, что читает `checklists_create`), скрытое `back=admin`, кнопка `t('checklists.create.submit')`. Способ «копией своего» — не в этой волне (спека, «Заведение»: копия — волна 4 для партнёра; у УК копия своего — отдельной задачей, если владелец попросит).

- [ ] **Step 1: Failing tests**

```python
def test_панель_заведения_только_по_адресу(стенд, хранилище) -> None:
    assert 'name="name_ru"' not in стенд.get("/admin").get_data(as_text=True)
    assert 'name="name_ru"' in стенд.get("/admin?panel=new").get_data(as_text=True)


def test_заведение_с_экрана_методики_открывает_новый_чек_лист(стенд, хранилище) -> None:
    ответ = стенд.post("/admin/checklists", data={"code": "rnd2", "name_ru": "РНД-2",
                       "name_en": "RND-2", "back": "admin"}, headers=СВОЙ)
    assert ответ.status_code == 302
    assert "/admin?checklist=rnd2" in ответ.headers["Location"]
```

(`СВОЙ` — заголовок своего источника из `tests/web_harness.py`, его ждёт `refuse_foreign_origin`.)

- [ ] **Step 2:** FAIL. **Step 3:** реализация. **Step 4:** `tests/test_web_*.py` зелёные; порча — убрать `back`-ветку → второй тест краснеет. **Step 5:** commit `feat(web): новый чек-лист — панелью на экране «Методики» (D222)`.

---

### Task 4: Стили и адаптив

**Files:**
- Modify: `src/web/static/decimus-web.css` — блок после `.mx-bar` (~1015) и медиа-запросы в конце блока `mx-` (~1244).

```css
/* Колонка чек-листов слева, правка справа (D222). */
.mx-shell { display: grid; grid-template-columns: 18rem minmax(0, 1fr); gap: var(--space-7); align-items: start; }
.mx-rail {
  position: sticky; top: calc(var(--topbar-h) + var(--space-5));
  display: grid; gap: var(--space-2);
  max-height: calc(100vh - var(--topbar-h) - var(--space-9)); overflow: auto;
}
.mx-rail__bot { padding: var(--space-4); border: 1px solid var(--line); border-radius: var(--r-block); background: var(--surface-2); display: grid; gap: var(--space-2); margin-bottom: var(--space-4); }
.mx-rail__head { font-size: var(--fs-micro); letter-spacing: var(--tracking-micro); text-transform: uppercase; font-weight: var(--w-semibold); color: var(--ink-3); justify-content: space-between; align-items: center; }
.mx-rail__row { display: grid; gap: 2px; padding: var(--space-3) var(--space-4); border-radius: var(--r-control); color: var(--ink); text-decoration: none; }
.mx-rail__row:hover { background: var(--surface-2); text-decoration: none; }
.mx-rail__row.is-on { background: var(--accent-soft); box-shadow: inset 3px 0 0 var(--accent); }
.mx-rail__meta { font-size: var(--fs-micro); color: var(--ink-3); }
.mx-main { min-width: 0; }
/* Переключатель в шапке нужен, только пока колонки нет. */
.mx-shell .mx-switch .pick__caret { display: none; }
.mx-shell .mx-switch { pointer-events: none; }
/* Колонка — над подложкой панели: при открытом пункте по ней можно уйти в другой чек-лист. */
@media (min-width: 1280px) { .mx-rail { z-index: 62; } }
@media (max-width: 1279px) {
  .mx-shell { grid-template-columns: 12rem minmax(0, 1fr); }
  .mx-rail__meta { display: none; }
}
@media (max-width: 1023px) {
  .mx-shell { grid-template-columns: minmax(0, 1fr); }
  .mx-rail { display: none; }
  .mx-shell .mx-switch { pointer-events: auto; }
  .mx-shell .mx-switch .pick__caret { display: inline; }
}
@media (max-width: 52rem) {
  .mx-shell--pick .mx-rail { display: grid; position: static; max-height: none; }
  .mx-shell--pick .mx-main { display: none; }
}
```

Проверить, что `z-index: 62` колонки выше `.mx-scrim` (60) и что `position: sticky` + `z-index` на `.mx-rail` действительно поднимает её над фиксированной подложкой (стекинг-контекст `.shell`/`.page` — если нет, поднять `.mx-shell` `position: relative; z-index: 62` в том же медиа-запросе и оставить `.mx-drawer` 61 → поднять до 63). Решается осмотром, Task 5.

- [ ] **Step 1:** правка CSS. **Step 2:** `tests/test_web_*.py` зелёные (стили тестами не меряются). **Step 3:** commit `feat(web): колонка чек-листов — адаптив 1280/1024/телефон (D222)`.

---

### Task 5: Осмотр глазами и доки

**Files:**
- Modify: `docs/12-web-admin.md` — таблица возможностей (26–36: `/admin` теперь с колонкой и заведением панелью), «Что экран не показывает» (481–483), раздел «Чек-лист: список и панель справа» (526–583: колонка, блок «Бот», адаптив, панель заведения).

- [ ] **Step 1:** поднять стенд осмотра (`scratchpad/mxview/serve.py` из сессии 28.09, `VIEW_ROLE=admin VIEW_TENANT=demo`, порт 8399) и отдать осмотр субагенту с chrome-devtools на 1920, 1440, 1100, 900, 390 px. Проверить: колонка видна/узкая/скрыта по ширинам; клик по чек-листу в колонке при открытой панели пункта ведёт на чек-лист (≥1280); панель не закрывает колонку на ≥1280; телефон `/admin` — список, `/admin?checklist=bizdev` — чек-лист; `scrollWidth == clientWidth` на всех ширинах.
- [ ] **Step 2:** поправить найденное; повторить осмотр.
- [ ] **Step 3:** обновить `docs/12-web-admin.md` по списку выше; прогнать `make test` (тестовая база MUSPELHEIM, `.env` из основного клона — симлинком в worktree, D212).
- [ ] **Step 4:** commit `docs: «Методика» — колонка чек-листов и заведение панелью (D222)`; PR в `main`, выкатка — по «да» владельца.
