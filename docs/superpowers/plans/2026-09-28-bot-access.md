# Доступ чек-листов в бот (волна 3) — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Несколько чек-листов могут быть «доступны в боте» одновременно. Доступ настраивается одним блоком «Бот» на экране «Методика». Бот на старте проверки берёт доступные: один — не спрашивает, несколько — кнопки, ноль — прямо говорит.

**Architecture:** Флаг `in_bot` живёт в карточке чек-листа (`meta.json`) рядом с `state`. Карточка без флага наследует старый смысл: «в боте» тот, на кого смотрит указатель `<store>/current`. Так хранилища на проде не нужно мигрировать. Бот читает хранилище версий (том `methodology`, `:ro`) и снимает снимок издания выбранного чек-листа. Код чек-листа пишется в состояние проверки, и `edition.data_dir` находит снимок по паре «код + издание». Без `MCP_CHECKLIST_STORE` бот ведёт себя слово в слово как сегодня: один чек-лист `bizdev` из `AUDIT_DATA_DIR`.

**Tech Stack:** Python 3.12, Flask + Jinja (src/web), aiogram 3 (src/bot), pytest, docker compose.

**Spec:** `docs/superpowers/specs/2026-09-28-checklist-admin-design.md` — разделы «Панель „Бот“», «Бот», «Заслоны». Решения D221, D223, D227. Закрывает #430.

## Global Constraints

- Сущности связываются кодами, не формулировками (CLAUDE.md).
- Язык — параметр: все новые тексты в `src/web/texts.py` и `src/bot/texts*` на ru и en.
- Оценка только через движок; ставки и пороги в коде не дублировать.
- Регресс-сверка после изменений: `examples/belgrade-1` → 97.5%, A, 5×D1; `examples/belgrade-2` → 97.0%, A, 6×D1.
- Интерфейс — по эталону Swarm (D228): выдвижная панель справа для работы с элементами, строки списков — обычный текст.
- Раскатка — только по «да» владельца и в ночное окно (скилл `deploy-window`). Этот план заканчивается PR, не раскаткой.

## Review Focus

1. **Прод-хранилище без поля `in_bot`.** Первое открытие после выката обязано показать «в боте: Проверка бизнес-девелопера», как было, и бот обязан стартовать без вопроса. Тест: карточка без ключа + указатель `current` → `in_bot=True` ровно у него.
2. **Бот без смонтированного хранилища** (dev, демо, старая раскладка) стартует как сегодня. Тест: `checklist_store=None` → список из одного `bizdev`, источник `settings.data_dir`.
3. **Чек-лист сняли из бота, пока идёт проверка.** Проверка досчитывается по своему снимку. Тест: старт по `rnd`, флаг снят, `data_dir(chat)` отдаёт снимок `rnd`.
4. **Снимок недефолтного кода пропал.** Отказ с понятным текстом, а не тихий переход на методику `bizdev`. Тест: `data_dir` для `code != bizdev` без снимка поднимает `ChecklistVersionMismatch`.
5. **Гонка в боте: кнопка устаревшего списка.** Аудитор нажал чек-лист, который тем временем убрали из бота. Бот отвечает «этот чек-лист больше не доступен» и показывает свежий список. Тест на обработчик.

---

### Task 1: Флаг «в боте» в хранилище

**Files:**
- Modify: `src/mcp/checklist_layout.py` (`Meta`, `read_meta`, `write_meta`)
- Modify: `src/mcp/checklists.py` (`Overview.in_bot`, `overview()`, `_overview_of()`, новая `set_bot_access`)
- Test: `tests/test_mcp_checklists.py`

**Interfaces:**
- Produces: `Meta.in_bot: bool | None` (None — ключа нет в карточке); `Overview.in_bot: bool`; `set_bot_access(store: Store, tenant: str | None, *, on: bool, by: str | None) -> Overview`; отказ — `ChecklistError` с текстом «почему нельзя» одним предложением.

- [ ] Тест: карточка без `in_bot`, указатель `current` на `hq/bizdev` → `overview()` отдаёт `in_bot=True` для bizdev и `False` для остальных.
- [ ] Тест: `set_bot_access(on=True)` для второго чек-листа в работе с изданием и нарушениями → оба `in_bot=True`, карточка первого получила явный `true` (фиксация наследованного значения при первой записи).
- [ ] Тест-заслоны (по одному на отказ, каждый проверен на сломанном вводе): черновик, снят, нет опубликованного издания, ноль пунктов-нарушений → `ChecklistError`, флаг не записан.
- [ ] Тест: `on=False` у последнего → разрешено, `in_bot=False` у всех (бот скажет «не по чему»).
- [ ] Реализация: заслоны вынести из `apply_to_production` в `_bot_ready(store) -> str | None` (текст отказа или None) и звать из обоих. `write_meta` пишет `in_bot`, только если он не None. При первом `set_bot_access` в хранилище, где ни у одной карточки нет ключа, всем известным карточкам проставить явное значение из наследованного, одной серией записей.
- [ ] `pytest tests/test_mcp_checklists.py -q` зелёный; commit `feat(mcp): флаг «доступен в боте» у нескольких чек-листов (волна 3)`.

### Task 2: Панель «Бот» и блок в колонке

**Files:**
- Modify: `src/web/methodology.py` (`RailRow.in_bot` ← `Overview.in_bot`; новая дверь `set_bot_access`)
- Modify: `src/web/app.py` (`POST /admin/bot/<code>`, `panel=bot` в `methodology`)
- Modify: `src/web/templates/methodology/index.html` (блок «Бот» в колонке, панель `panel == 'bot'`)
- Modify: `src/web/static/decimus-web.css`, `src/web/texts.py`
- Test: `tests/test_web_methodology_rail.py`, `tests/test_web_checklists_screen.py`

**Вид блока в колонке** (вместо «БОТ / имя / Настроить»):

```
┌ ДОСТУП В БОТЕ ────────────── 1 из 2 ┐
│ Аудиторы начинают проверку по:      │
│ ● Проверка бизнес-девелопера        │
│ [ Настроить доступ ]                │
└─────────────────────────────────────┘
```

Ноль — строка-предупреждение «Бот сейчас не даст начать проверку: ни один чек-лист не открыт». Строка чек-листа в колонке — значок бота вместо зелёного слова «бот».

**Панель справа** (`/admin?panel=bot`) — таблица всего доступа пространства: название · состояние · переключатель. Если переключить нельзя — вместо переключателя причина одним словом («черновик», «снят», «не опубликован», «нет пунктов»). Каждый переключатель — отдельная форма POST, и без скрипта всё работает.

- [ ] Тест: `/admin?panel=bot` рендерит строку на каждый чек-лист; у черновика нет формы, есть причина.
- [ ] Тест: `POST /admin/bot/<code>` с `on=1` → 303 на `/admin?panel=bot&checklist=…`, флаг записан, в журнале хранилища `web:<логин>`.
- [ ] Тест: POST для черновика → страница с текстом отказа, флаг не записан. POST без CSRF-метки → отказ (как у соседних форм).
- [ ] Тест: блок в колонке при нуле доступных показывает предупреждение.
- [ ] Реализация, тексты ru/en, стили на токенах ядра. Старая ссылка блока на `/admin/checklists` уходит.
- [ ] Глазами на стенде: 1440, 1024, 390 px — блок и панель читаются, переключатели нажимаются.
- [ ] commit `feat(web): блок и панель «Бот» — доступ чек-листов настраивается в одном месте (волна 3)`.

### Task 3: Домен — проверка знает свой чек-лист

**Files:**
- Modify: `src/domain/config.py` (`Settings.checklist_store: Path | None` из `MCP_CHECKLIST_STORE`)
- Create: `src/domain/bot_checklists.py`
- Modify: `src/domain/edition.py` (`keep(settings, code, source=None)`, `recorded_code`, `data_dir` по коду)
- Modify: `src/domain/state.py` (`start_inspection(..., checklist_code=None)`, блок `checklist_code`, сверка версии и перевод — по коду)
- Test: `tests/test_domain_bot_checklists.py`, `tests/test_domain_edition.py`

**Interfaces:**
- Produces: `BotChecklist(code: str, name_ru: str, name_en: str, source: Path)`; `available(settings) -> list[BotChecklist]`; `source_for(settings, code) -> Path` (без хранилища — `settings.data_dir`, только для `bizdev`; иначе `<store>/hq/<code>/current`); `start_inspection(chat_id, *, ..., checklist_code: str | None = None)`.

- [ ] Тест: без хранилища `available()` → `[bizdev]` с `source == settings.data_dir`.
- [ ] Тест: хранилище с двумя `in_bot` и одним выключенным → два, по порядку названий; снятый не попадает, даже с флагом.
- [ ] Тест: `start_inspection(checklist_code="rnd")` → в блоке `checklist_code: "rnd"`, снимок на полке `rnd`, `data_dir(chat)` — этот снимок.
- [ ] Тест: старое состояние без `checklist_code` → код `bizdev`, поведение прежнее (регресс).
- [ ] Тест (Review Focus 4): `code="rnd"`, снимок удалён → `ChecklistVersionMismatch` с текстом.
- [ ] Реализация: `src/domain/bot_checklists.py` читает карточки через `src.mcp.checklist_layout` (`known`, `read_meta`, `applied`). В `checklist_layout` нет тяжёлых зависимостей — проверить `src/mcp/__init__.py`. Если импорт тянет сервер, перенести чтение карточки в `src/domain`, а `checklist_layout` сделать её потребителем.
- [ ] Регресс движка: две сверки из Global Constraints.
- [ ] commit `feat(domain): проверка помнит код чек-листа и идёт по его снимку (волна 3)`.

### Task 4: Бот — выбор чек-листа на старте

**Files:**
- Modify: `src/bot/states.py` (`StartFlow.waiting_checklist`)
- Modify: `src/bot/routers/start.py` (`on_new` → `_ask_checklist`; обработчик кнопки; `checklist_code` в FSM-данных → `start_inspection`)
- Modify: `src/bot/keyboards.py` (или где живут клавиатуры старта), тексты бота ru/en
- Test: `tests/test_bot_start_router.py`

- [ ] Тест: один доступный → сразу вопрос о пиццерии, код ушёл в `start_inspection`.
- [ ] Тест: два → кнопки с названиями на языке интерфейса; нажатие → вопрос о пиццерии.
- [ ] Тест: ноль → текст «начать проверку не по чему — чек-лист в бот открывает методист в админке», и мастер не идёт дальше.
- [ ] Тест (Review Focus 5): кнопка с кодом, которого уже нет среди доступных → «больше не доступен» + свежие кнопки.
- [ ] commit `feat(bot): выбор чек-листа на старте проверки (D221, волна 3)`.

### Task 5: Код чек-листа — в базу

**Files:**
- Modify: `src/db/push.py` (INSERT пишет `checklist_code` из состояния, а не из умолчания базы)
- Test: `tests/test_db_push*.py`

- [ ] Тест: проверка с `checklist_code="rnd"` → строка `inspections.checklist_code = 'rnd'`. Без кода в состоянии → `'bizdev'`.
- [ ] commit `feat(db): проверка пишет в базу свой чек-лист, а не умолчание`.

### Task 6: Раскладка контейнеров

**Files:**
- Modify: `docker-compose.yml` (сервис `bot`: том `methodology:/app/methodology:ro`, `MCP_CHECKLIST_STORE: /app/methodology`)
- Test: `tests/test_infra_compose.py`
- Modify: `docs/08-deploy.md`

- [ ] Тест: у `bot` есть том `methodology` только на чтение и переменная хранилища.
- [ ] Док: абзац про `MCP_CHECKLIST_STORE` в 08-deploy — бот теперь читает хранилище. Закрывает разрыв #430.
- [ ] commit `feat(infra): бот читает хранилище версий — публикация из админки доходит до проверок (#430)`.

### Task 7: Документация

- [ ] `docs/10-checklist-configuration.md` — «Чек-лист в хранилище не один»: указатель `current` больше не выбирает, по чему идут проверки, это делает флаг «в боте».
- [ ] `docs/12-web-admin.md` — таблица возможностей: блок и панель «Бот»; строки про «применить к проду».
- [ ] `docs/06-mvp-bot.md` — шаг выбора чек-листа в мастере старта.
- [ ] Скилл `keeping-docs-current`: сверка инвентарей (маршруты, env-переменные, тексты).
- [ ] commit `docs: доступ в бот — несколько чек-листов, выбор на старте (волна 3)`.
