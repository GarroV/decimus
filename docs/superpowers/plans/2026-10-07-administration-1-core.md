# Администрирование, блок 1: ядро прав — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** одна проверка прав `can(человек, действие, пространство_объекта, автор_объекта)` — граница пространств в коде и матрица «роль × действие» в базе — стоит на каждом пишущем маршруте веба, каждой команде бота и каждом пишущем инструменте MCP. У действий над проверкой ячейка матрицы — «нет / свои / все» (D311), и проверка помнит учётку, которая её занесла. Роли по умолчанию заведены миграцией, учётки перенесены, действия УК в пространстве партнёра пишутся в журнал той же транзакцией. Поведение для людей не меняется, кроме отличий таблицы ролей спеки, D310 и D311.

**Architecture:** каталог действий и `can` — чистый модуль `src/domain/permissions.py` (без базы, тестируется таблицей). Права роли — словарь «код действия → охват» (`all` или `own`; нет строки — нет права); `own` допустим только у действий над проверкой. Роли и права — таблицы `roles`, `role_permissions` (миграция `0038`); права роли приезжают вместе с опознанием (сессия веба, привязка бота) одним запросом, поэтому снятое право действует со следующего запроса. Автор проверки — колонка `inspections.created_by` (миграция `0040`): бот кладёт учётку привязки в состояние проверки при старте, слив пишет её в базу. Веб: декоратор `guard.action(...)` объявляет код на маршруте, `before_request` спрашивает `can` для маршрутов своего пространства, маршрут с объектом (проверка, человек) зовёт `guard.permit(код, пространство_объекта, object_author=...)` сам, а `after_request` роняет пишущий маршрут, который объявил объект и не спросил. Журнал `cross_space_actions` (миграция `0039`) пишется функцией `cross_space.record(conn, запись)` на том же подключении, которым дверь делает действие, до коммита. Бот: внутренняя мидлварь роутера `ActionMiddleware(код)`. MCP: у `ToolSpec` поле `action`, права токена в блоке 1 — мост из того, что уже открывает окружение (`MCP_CHECKLIST_TENANTS`, `MCP_RETRACTION_TOKENS`); роли токенам — блок 3. Пространство объекта для `can` в MCP берётся из самого объекта (спека): у правки методики — из пространства, куда `_aimed` навёл хранилище, у снятия — из строки проверки (`retraction.object_tenant`). Старые роли `admin`/`auditor` на время блока живут псевдонимами: мост ролей (Task 3) переводит их по пространству везде, где сегодня сравнивают строку роли, и уходит в Task 10–11.

**Tech Stack:** Python 3.12, Flask, aiogram 3, psycopg 3, PostgreSQL (миграции SQL раннером `src/db/migrate.py`), pytest.

**Spec:** docs/superpowers/specs/2026-10-07-administration-design.md (с решениями D310, D311 из `docs/furca/decisions.md`)

## Global Constraints

- Сущности связываются **кодами, никогда формулировками**: код действия (`inspection.retract`), код роли (`hq_admin`), охват права (`own`/`all`) — ключи; подписи ролей — колонки `name_ru`/`name_en`. Ни одна проверка не сравнивает подпись.
- **Язык — параметр, никогда не константа.** Каждый новый текст для человека заводится на ru и en тем же коммитом (`src/web/texts.py`, `src/bot/texts.py`); тесты текстов (`tests/test_web_texts.py`, `tests/test_bot_texts*.py`) остаются зелёными.
- **Оценку не считать заново.** Блок движок не трогает; автор проверки в отпечаток слива не входит. Регрессия: `make regress` → `belgrade-1` 97.5%, A, 5×D1; `belgrade-2` 97.0%, A, 6×D1. Разошлось — регрессия, а не «другая версия».
- **Модель предлагает, фиксирует человек** — блок этого не касается; ни одна запись не попадает в отчёт без аудитора, как и раньше.
- **Роли по умолчанию и перенос — по таблице спеки с поправками D310 и D311** (`admin`/`auditor` × `HQ`/страна → `hq_admin`/`hq_staff`/`country_admin`/`country_staff`). Других отличий от сегодняшнего поведения быть не должно.
- **Граница пространств — только в `can`**, не в матрице: страна не трогает объект УК и чужую страну никогда; `unit.create`, `space.manage`, `roles.manage` у роли страны не действуют ни при каком праве. Охват `own` границу не расширяет: «свои» страны — только в её пространстве.
- **«Свои» = проверку занесла учётка этого человека** (`inspections.created_by = учётка`). Проверка без автора (старая, или занесённая без привязки бота) под «свои» не попадает никогда.
- **Новая пишущая операция без кода в каталоге — дефект**, его ловят тесты полноты (Task 12 — веб, Task 13 — бот, Task 14 — MCP).
- **Блок 1 не трогает**: экран «Администрирование» (блок 2), токен ↔ учётку, фильтр `tools/list`, отказ `forbidden`, уход `MCP_TOKENS`/`MCP_CHECKLIST_TENANTS`/`MCP_RETRACTION_TOKENS`/`BOT_MCP_OWNER_ID`, `mcp_admins`, `/mcp_add`/`/mcp_revoke`/`/mcp_who` (блок 3); снятие заведения пиццерии из бота (#527).
- **Тесты базы — на тестовой базе MUSPELHEIM, не на Postgres Mac** (D212). `.env` рабочей копии ведёт `DATABASE_ADMIN_URL` на `127.0.0.1:55432` — это туннель `localhost:55432 → muspelheim:15432`. Перед прогоном: `nc -z 127.0.0.1 55432 && echo туннель-жив`; молчит — `launchctl kickstart -k gui/$(id -u)/io.garva.mac-stands-tunnel` и повтор. Переключаться молча на `localhost:5432` нельзя; без туннеля никак — спросить владельца.
- **Между задачами весь набор тестов зелёный** (решение координатора по предполётной сверке 07.10.2026). Ни одна задача не оставляет «ожидаемо красное до Task N»: что ломает её изменение, она чинит сама, тем же коммитом. Перед пушем каждой задачи, которая трогает `src/db/web_access.py`, `src/web/` или `tests/web_harness.py`, — ещё `.venv/bin/pytest tests/test_web_*.py -q`.
- **Точечный прогон** файла: `make test-honest ARGS="tests/<файл>.py -q -rs"` (цель экспортирует `DATABASE_URL`, `DATABASE_APP_PASSWORD`, `DATABASE_RETRACTION_PASSWORD` из `.env`). В выводе не должно быть строк `SKIPPED` у тестов с базой: пропуск = туннель или окружение, это не зелёный прогон.
- **Полный прогон** перед сдачей: `make check` (ставит `AUDIT_REQUIRE_DATA=1`: пропуск тестов базы роняет прогон, #207) и `make regress`.
- **Значения секретов не читать и не печатать**: строки `.env` берёт `Makefile`; в командах плана нет ни одного `cat .env`.
- **Коммит и пуш после каждой задачи**, `git add` только поимённо (никаких `-a` и `.`), сообщение в формате `type: описание`, последней строкой `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Ветка — текущая рабочая ветка блока, не `main`.
- **Раскатка** блока на живой продукт — только по явному «да» владельца в разговоре и в ночное окно 23:00–06:59 (скилл `deploy-window`); пуш в ветку, с которой собирается прод, тоже раскатка.
- **Миграции:** следующие номера `0038`, `0039`, `0040`; раннер сам оборачивает файл в транзакцию (`begin/commit` не писать); отпечаток каждой новой миграции записывается в `tests/test_db_migrations_frozen.py` тем же коммитом; права ролей — в `tests/test_db_migrate_roles.py` (`APP_TABLE_GRANTS`, `ADMIN_TABLE_GRANTS`); функции-триггеры — `set search_path = pg_catalog, public, pg_temp` (как `0033`).

## Review Focus

- **Право сняли, а сессия старая:** права роли читаются в `resolve_session` на каждом запросе, не на входе. Тест — Task 6, `test_снятое_право_действует_со_следующей_сверки_сессии`.
- **Действие откатилось, а строка журнала осталась (или наоборот):** журнал пишется тем же подключением до коммита двери. Тест — Task 9, `test_отказ_двери_не_оставляет_журнала`.
- **Маршрут объявил объект и не спросил `can`** (или спросил о действии над проверкой, не передав автора): запись прошла бы без границы или без «свои». Тесты — Task 7, `test_маршрут_с_объектом_без_permit_падает_500` и `test_действие_над_проверкой_без_автора_падает_500`.
- **Проверка без автора** (залита до `0040` или занесена без привязки бота): сотрудник с правом «свои» получает отказ, админ — нет; пустой автор не совпадает с учёткой без `id`. Тесты — Task 2, строки «неизвестен» таблицы; Task 5, `test_проверка_без_учётки_ложится_без_автора`; Task 10, `test_сотрудник_уК_не_снимает_проверку_без_автора`.
- **Человек бота без привязки и старый код `default`** (путь совместимости `ALLOWED_TELEGRAM_IDS`/`roster.json`, `MCP_TOKENS` стендов): роли в базе нет, а проверку он вести обязан; `default` значит `HQ`, а не «чужое пространство». Тесты — Task 13, `test_путь_совместимости_получает_права_hq_staff`; Task 1, `test_старый_код_уК_приводится`; Task 14, `test_мост_с_тенантом_default_правит_как_уК`.
- **MCP пишет мимо пространства объекта** (наведение `_aimed` или чтение строки снятия однажды выпустят вызов из пространства токена): `can` спрашивается и над самим объектом. Тесты — Task 14, `test_правка_методики_наведённая_в_эталон_закрыта_партнёру`, `test_снятие_проверки_чужого_пространства_закрыто`.

## Расхождения со спекой

Каждое — отдельной строкой, с тем, как план поступает.

1. **Расхождение со спекой: в каталоге нет кода для подтверждения проверки на приёмке** (`POST /inspections/<id>/accept`, D199). План заводит код `inspection.accept` — действие над проверкой (`own`/`all`).
2. **Расхождение со спекой: в каталоге нет кода для правки записи проверки на приёмке** (`POST /inspections/<id>/findings/<fid>/revise`). Спека в «За рамками» называет правку завершённого отчёта несуществующей, но правка черновика на приёмке есть. План заводит код `inspection.revise` — действие над проверкой.
3. **Решено D311 (было расхождение: `hq_staff` получал снятие, перенос, подтверждение и правку всех проверок).** Действия над проверкой — `inspection.retract`, `inspection.move`, `inspection.accept`, `inspection.revise`, `inspection.letter` — в матрице несут охват: `hq_staff` и `country_staff` — `own`, `hq_admin` и `country_admin` — `all`. Расхождение с таблицей спеки, принятое владельцем: `country_staff` получает снятие, перенос, подтверждение и правку **своих** проверок (в таблице спеки их не было), а письмо — только по своим (в таблице было по всем своего пространства).
4. **Решено D310 (было расхождение: `hq_staff` терял заведение пиццерий).** `unit.create` по умолчанию у `hq_admin` и `hq_staff`; бот на старте проверки заводит пиццерию как сейчас, снятие этого пути — #527, не блок 1.
5. **Решено D311 (было расхождение: заведение чек-листа партнёром).** Админ страны заводит и правит свои чек-листы в своём пространстве: отказ D283 в `checklists_create` снимается, дверь заводит чек-лист только в пространстве вошедшего (`space_of(tenant)`), граница — слой 1.
6. **Расхождение со спекой: правка методики партнёра человеком УК.** Методика лежит файлами, журнал «в одной транзакции» с правкой файла невозможен. План оставляет дверь методики своей (`may_write`: правка только в своём пространстве) — УК в методику партнёра в блоке 1 не пишет.
7. **Расхождение со спекой: команды бота без пишущей операции.** `/help`, `/lang` (личная настройка языка), `/version`, `/stops` (чтение, круг админов) и запасной обработчик кода в каталоге не получают; тест полноты держит их явным списком исключений с причиной. `/mcp_add`, `/mcp_revoke`, `/mcp_who` до блока 3 закрываются тем же `mcp.connect`, что `/mcp`, поверх круга `mcp_admins`.
8. **Расхождение со спекой (порядок блоков): админ страны заводит людей (D307) — не в блоке 1.** Экран людей до блока 2 остаётся открыт только УК (мост в маршрутах «Пользователей»), иначе админ страны получил бы перечень людей всех пространств. Правило «назначить или снять админа страны — только `space.manage`» блок 2 обязан добавить вместе со снятием моста.
9. **Расхождение со спекой (уточнение D311): что считается «действием над проверкой».** Сверено по каталогу: объект — конкретная проверка только у пяти кодов из п. 3. `inspection.conduct` создаёт новую проверку (объекта ещё нет); `prescription.manage`, `prescription.reply`, `plan.manage`, `plan.submit` действуют над предписанием и планом действий (разделы УК и партнёра, D264); остальные — над методикой, людьми, пространствами. У них охват всегда `all`.

## Открытые вопросы владельцу

- **В4.** Человек бота **без привязки** к учётке веба (путь совместимости `ALLOWED_TELEGRAM_IDS`/`roster.json`) заносит проверки **без автора**: по D311 они не попадают ни под чьи «свои», их снимает, переносит, подтверждает и правит только админ. Так и оставить до перевода всех на привязку, или до этого считать автором кого-то ещё? План делает «без автора» (закрыто по умолчанию).

## Задачи

### Task 1: Каталог действий и `can`

**Files:**
- Create: `src/domain/permissions.py`
- Test: `tests/test_permissions_can.py`

**Interfaces:**
- Consumes: `src.domain.tenants.HQ_TENANT: str`, `src.domain.tenants.canonical_tenant(code: str) -> str`.
- Produces:
  - `Action(code: str, group: str, hq_only: bool = False, on_inspection: bool = False)` — frozen dataclass.
  - `ACTIONS: tuple[Action, ...]`, `ACTION_CODES: frozenset[str]`, `HQ_ONLY_ACTIONS: frozenset[str]`, `INSPECTION_OBJECT_ACTIONS: frozenset[str]`.
  - `REACH_OWN = "own"`, `REACH_ALL = "all"`; `Grants = Mapping[str, str]` — код действия → охват.
  - `RULE_OK = "ok"`, `RULE_MATRIX = "matrix"`, `RULE_HQ_ONLY = "hq_only"`, `RULE_HQ_OBJECT = "hq_object"`, `RULE_FOREIGN_SPACE = "foreign_space"`, `RULE_NOT_AUTHOR = "not_author"`.
  - `Actor(tenant: str, role: str | None, grants: Grants, user_id: str | None = None)` — frozen dataclass.
  - `Decision(allowed: bool, rule: str)` — frozen dataclass, `__bool__` → `allowed`.
  - `class UnknownAction(ValueError)`; `class AuthorNotGiven` и его единственный экземпляр `AUTHOR_NOT_GIVEN`.
  - `require_action(code: str) -> Action` — действие каталога по коду или `UnknownAction` с кодом в тексте. Единственное место проверки кода: его зовут `can`, `cross_space.entry_for` (Task 4), `guard.action` (Task 7), `ToolSpec.__post_init__` (Task 14).
  - `can(actor: Actor, action: str, object_tenant: str, *, object_author: str | None | AuthorNotGiven = AUTHOR_NOT_GIVEN) -> Decision` — у действия над проверкой автор обязателен (`None` — неизвестен), иначе `ValueError`.

- [ ] **Step 1: Написать падающий тест**

```python
# tests/test_permissions_can.py
"""Ядро прав: граница пространств и охват «свои/все» (спека «Администрирование», D304, D306, D311).

Ядро (права доступа) — тестами вперёд. Граница не настраивается: никакое
право не даёт стране тронуть объект УК, чужую страну или действие «только УК».
«Свои» — только проверка, которую занесла учётка этого человека.
"""

from __future__ import annotations

import pytest

from src.domain.permissions import (
    ACTION_CODES,
    HQ_ONLY_ACTIONS,
    INSPECTION_OBJECT_ACTIONS,
    REACH_ALL,
    REACH_OWN,
    RULE_FOREIGN_SPACE,
    RULE_HQ_OBJECT,
    RULE_HQ_ONLY,
    RULE_MATRIX,
    RULE_NOT_AUTHOR,
    RULE_OK,
    Actor,
    UnknownAction,
    can,
    require_action,
)

ВСЁ = {код: REACH_ALL for код in ACTION_CODES}


def уК(grants: dict[str, str] = ВСЁ, tenant: str = "HQ") -> Actor:
    return Actor(tenant=tenant, role="hq_admin", grants=grants, user_id="u-hq")


def страна(tenant: str = "GE", grants: dict[str, str] = ВСЁ) -> Actor:
    return Actor(tenant=tenant, role="country_admin", grants=grants, user_id="u-ge")


def test_каталог_ровно_по_спеке_и_два_кода_расхождений() -> None:
    assert ACTION_CODES == {
        "inspection.conduct", "inspection.retract", "inspection.move", "inspection.accept",
        "inspection.revise", "inspection.letter", "prescription.manage", "prescription.reply",
        "plan.manage", "plan.submit", "checklist.edit", "checklist.publish",
        "checklist.manage", "phrases.manage", "people.manage", "mcp.connect",
        "unit.create", "space.manage", "roles.manage",
    }


def test_только_уК_ровно_три_действия() -> None:
    assert HQ_ONLY_ACTIONS == {"unit.create", "space.manage", "roles.manage"}


def test_действия_над_проверкой_ровно_пять() -> None:
    assert INSPECTION_OBJECT_ACTIONS == {
        "inspection.retract", "inspection.move", "inspection.accept",
        "inspection.revise", "inspection.letter",
    }


def test_уК_действует_в_пространстве_партнёра() -> None:
    решение = can(уК(), "inspection.retract", "GE", object_author=None)
    assert решение.allowed and решение.rule == RULE_OK


def test_страна_не_трогает_объект_уК_даже_с_правом() -> None:
    решение = can(страна(), "checklist.edit", "HQ")
    assert not решение.allowed and решение.rule == RULE_HQ_OBJECT


def test_страна_не_трогает_чужую_страну() -> None:
    решение = can(страна("GE"), "inspection.retract", "AM", object_author="u-ge")
    assert not решение.allowed and решение.rule == RULE_FOREIGN_SPACE


@pytest.mark.parametrize("код", sorted(HQ_ONLY_ACTIONS))
def test_действие_только_уК_стране_не_даёт_никакое_право(код: str) -> None:
    решение = can(страна(), код, "GE")
    assert not решение.allowed and решение.rule == RULE_HQ_ONLY


def test_без_права_отказ_матрицы_и_у_уК() -> None:
    решение = can(уК(grants={}), "inspection.retract", "HQ", object_author="u-hq")
    assert not решение.allowed and решение.rule == RULE_MATRIX


@pytest.mark.parametrize(
    ("автор", "можно", "правило"),
    [("u-hq", True, RULE_OK), ("u-other", False, RULE_NOT_AUTHOR), (None, False, RULE_NOT_AUTHOR)],
)
def test_охват_свои_только_для_своей_проверки(автор: str | None, можно: bool, правило: str) -> None:
    человек = уК(grants={"inspection.retract": REACH_OWN})
    решение = can(человек, "inspection.retract", "HQ", object_author=автор)
    assert (решение.allowed, решение.rule) == (можно, правило)


def test_свои_без_учётки_не_совпадают_с_пустым_автором() -> None:
    человек = Actor(tenant="HQ", role="hq_staff", grants={"inspection.move": REACH_OWN})
    assert not can(человек, "inspection.move", "HQ", object_author="")


def test_действие_над_проверкой_без_автора_это_ошибка_кода() -> None:
    with pytest.raises(ValueError, match="автор"):
        can(уК(), "inspection.retract", "HQ")


def test_неизвестный_охват_это_отказ_матрицы() -> None:
    решение = can(уК(grants={"checklist.edit": "some"}), "checklist.edit", "HQ")
    assert not решение.allowed and решение.rule == RULE_MATRIX


def test_старый_код_уК_приводится() -> None:
    assert can(уК(tenant="default"), "unit.create", "HQ").allowed


def test_неизвестное_действие_это_ошибка_кода() -> None:
    with pytest.raises(UnknownAction, match="inspection.delete"):
        can(уК(), "inspection.delete", "HQ")


def test_действие_каталога_находится_по_коду() -> None:
    assert require_action("inspection.move").on_inspection
    assert require_action("unit.create").hq_only
    with pytest.raises(UnknownAction, match="inspection.delete"):
        require_action("inspection.delete")


def test_пустое_пространство_объекта_это_ошибка_кода() -> None:
    with pytest.raises(ValueError, match="пространство"):
        can(уК(), "checklist.edit", "  ")


def test_отказ_ложен_в_условии() -> None:
    assert not can(страна(), "checklist.edit", "HQ")
```

- [ ] **Step 2: Прогнать — ожидается FAIL**

Run: `.venv/bin/pytest tests/test_permissions_can.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.domain.permissions'`.

- [ ] **Step 3: Минимальная реализация**

```python
# src/domain/permissions.py
"""Каталог действий и проверка прав `can` (спека «Администрирование», D304, D306, D307, D311).

Решение принимается двумя слоями, и отказ первого второй не переопределяет:

1. **Граница** (код, не настраивается): человек УК действует в любом
   пространстве; человек страны — только в своём; объект УК страна не меняет
   никогда; действия «только УК» роли страны не выдаются никаким правом.
2. **Матрица** (настраивает админ УК): есть ли у роли право и с каким охватом.
   У действий над проверкой охват — «свои» (`own`: проверку занесла учётка
   этого человека) или «все» (`all`); у остальных — только `all`.

Код действия — ключ, подписи переводятся отдельно. Новая пишущая операция
получает код здесь в момент появления: это часть её готовности.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .tenants import HQ_TENANT, canonical_tenant


@dataclass(frozen=True)
class Action:
    """Одна пишущая операция каталога."""

    code: str
    group: str
    #: Действие только УК: роли страны не выдаётся никаким правом (слой 1).
    hq_only: bool = False
    #: Объект — конкретная проверка: право несёт охват «свои/все» (D311).
    on_inspection: bool = False


ACTIONS: tuple[Action, ...] = (
    Action("inspection.conduct", "inspection"),
    Action("inspection.retract", "inspection", on_inspection=True),
    Action("inspection.move", "inspection", on_inspection=True),
    Action("inspection.accept", "inspection", on_inspection=True),
    Action("inspection.revise", "inspection", on_inspection=True),
    Action("inspection.letter", "inspection", on_inspection=True),
    Action("prescription.manage", "prescription"),
    Action("prescription.reply", "prescription"),
    Action("plan.manage", "plan"),
    Action("plan.submit", "plan"),
    Action("checklist.edit", "checklist"),
    Action("checklist.publish", "checklist"),
    Action("checklist.manage", "checklist"),
    Action("phrases.manage", "phrases"),
    Action("people.manage", "people"),
    Action("mcp.connect", "mcp"),
    Action("unit.create", "unit", hq_only=True),
    Action("space.manage", "space", hq_only=True),
    Action("roles.manage", "roles", hq_only=True),
)

ACTION_CODES: frozenset[str] = frozenset(a.code for a in ACTIONS)
HQ_ONLY_ACTIONS: frozenset[str] = frozenset(a.code for a in ACTIONS if a.hq_only)
INSPECTION_OBJECT_ACTIONS: frozenset[str] = frozenset(a.code for a in ACTIONS if a.on_inspection)
_BY_CODE: Mapping[str, Action] = {a.code: a for a in ACTIONS}

REACH_OWN = "own"
REACH_ALL = "all"

#: Права роли: код действия → охват. Нет ключа — нет права.
Grants = Mapping[str, str]

RULE_OK = "ok"
RULE_MATRIX = "matrix"
RULE_HQ_ONLY = "hq_only"
RULE_HQ_OBJECT = "hq_object"
RULE_FOREIGN_SPACE = "foreign_space"
RULE_NOT_AUTHOR = "not_author"


class UnknownAction(ValueError):
    """Код действия не из каталога — ошибка кода, а не отказ человеку."""


def require_action(code: str) -> Action:
    """Действие каталога по коду. Единственная проверка кода на весь проект."""
    действие = _BY_CODE.get(code)
    if действие is None:
        raise UnknownAction(f"Действия «{code}» нет в каталоге src/domain/permissions.py")
    return действие


class AuthorNotGiven:
    """Метка «автора объекта не передали» — отличается от `None` («автор неизвестен»)."""


AUTHOR_NOT_GIVEN = AuthorNotGiven()


@dataclass(frozen=True)
class Actor:
    """Кто действует: пространство, роль и права роли на момент запроса."""

    tenant: str
    #: Код роли; `None` — права не из роли (мост MCP до блока 3).
    role: str | None
    grants: Grants
    #: Учётка веба: по ней опознаются «свои» проверки и пишется журнал.
    user_id: str | None = None


@dataclass(frozen=True)
class Decision:
    """Ответ `can`: можно ли и каким правилом это решено."""

    allowed: bool
    rule: str

    def __bool__(self) -> bool:
        return self.allowed


def _required_tenant(code: str, *, what: str) -> str:
    приведённый = canonical_tenant(code or "")
    if not приведённый:
        raise ValueError(f"Не задано {what}: без него граница пространств не решается")
    return приведённый


def _boundary(кто: str, action: str, чьё: str) -> str | None:
    """Слой 1: правило отказа границы или `None`, если граница пропускает."""
    if кто == HQ_TENANT:
        return None
    if action in HQ_ONLY_ACTIONS:
        return RULE_HQ_ONLY
    if чьё == HQ_TENANT:
        return RULE_HQ_OBJECT
    if чьё != кто:
        return RULE_FOREIGN_SPACE
    return None


def can(
    actor: Actor,
    action: str,
    object_tenant: str,
    *,
    object_author: str | None | AuthorNotGiven = AUTHOR_NOT_GIVEN,
) -> Decision:
    """Может ли `actor` сделать `action` над объектом пространства `object_tenant`.

    У действия над проверкой `object_author` обязателен: учётка, занёсшая
    проверку, или `None`, если она неизвестна. Забытый автор — ошибка кода:
    молча считать его «чужим» значило бы прятать пропуск в отказах людям.
    """
    require_action(action)
    if action in INSPECTION_OBJECT_ACTIONS and isinstance(object_author, AuthorNotGiven):
        raise ValueError(f"«{action}» — действие над проверкой: передайте автора объекта")
    кто = _required_tenant(actor.tenant, what="пространство человека")
    чьё = _required_tenant(object_tenant, what="пространство объекта")
    отказ_границы = _boundary(кто, action, чьё)
    if отказ_границы is not None:
        return Decision(False, отказ_границы)
    охват = actor.grants.get(action)
    if охват == REACH_ALL:
        return Decision(True, RULE_OK)
    if охват == REACH_OWN and action in INSPECTION_OBJECT_ACTIONS:
        свой = bool(actor.user_id) and object_author == actor.user_id
        return Decision(True, RULE_OK) if свой else Decision(False, RULE_NOT_AUTHOR)
    return Decision(False, RULE_MATRIX)
```

- [ ] **Step 4: Прогнать — ожидается PASS**

Run: `.venv/bin/pytest tests/test_permissions_can.py -q && .venv/bin/ruff check src/domain/permissions.py tests/test_permissions_can.py && .venv/bin/mypy`
Expected: все тесты PASS, ruff и mypy без ошибок.

- [ ] **Step 5: Коммит и пуш**

```bash
git add src/domain/permissions.py tests/test_permissions_can.py
git commit -m "feat: каталог действий и can — граница пространств и охват свои/все

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

### Task 2: Роли по умолчанию, перевод старых ролей, проверка матрицы

**Files:**
- Modify: `src/domain/permissions.py` (дописать после `can`)
- Test: `tests/test_permissions_table.py`

**Interfaces:**
- Consumes: всё из Task 1.
- Produces:
  - `SCOPE_HQ = "hq"`, `SCOPE_COUNTRY = "country"`.
  - `ROLE_HQ_ADMIN = "hq_admin"`, `ROLE_HQ_STAFF = "hq_staff"`, `ROLE_COUNTRY_ADMIN = "country_admin"`, `ROLE_COUNTRY_STAFF = "country_staff"`.
  - `ROLE_SCOPES: Mapping[str, str]` — код роли → охват роли.
  - `DEFAULT_MATRIX: Mapping[str, Grants]` — код роли → права по умолчанию.
  - `LEGACY_ROLE_ADMIN = "admin"`, `LEGACY_ROLE_AUDITOR = "auditor"`.
  - `scope_of_tenant(tenant: str) -> str`.
  - `canonical_role(role: str, tenant: str) -> str` — старое `admin`/`auditor` → новый код по пространству; прочее — как есть.
  - `validate_matrix(matrix: Mapping[str, Grants], scopes: Mapping[str, str]) -> list[str]` — нарушения словами, пусто — годна.

- [ ] **Step 1: Написать падающий тест**

```python
# tests/test_permissions_table.py
"""Таблица «роль × действие × пространство человека × пространство объекта × автор → да/нет».

Таблица ролей переписана здесь руками из спеки с поправками D310 и D311, а не
взята из кода: иначе тест сверял бы `DEFAULT_MATRIX` с самим собой. Проверка
таблицы прогоняется и на заведомо сломанной матрице, и на заведомо сломанном
`can` — она обязана покраснеть и назвать нарушенное правило (`testing.md`).

Оракул `ожидание()` — копия правил спеки, а не кода: его сходство с
`permissions._boundary` ожидаемо, а расхождение — дефект одного из двух.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

import pytest

from src.domain.permissions import (
    DEFAULT_MATRIX,
    RULE_MATRIX,
    RULE_OK,
    ROLE_SCOPES,
    Actor,
    Decision,
    canonical_role,
    can,
    validate_matrix,
)

ВСЕ = frozenset(
    {
        "inspection.conduct", "inspection.retract", "inspection.move", "inspection.accept",
        "inspection.revise", "inspection.letter", "prescription.manage", "prescription.reply",
        "plan.manage", "plan.submit", "checklist.edit", "checklist.publish",
        "checklist.manage", "phrases.manage", "people.manage", "mcp.connect",
        "unit.create", "space.manage", "roles.manage",
    }
)
ТОЛЬКО_УК = frozenset({"unit.create", "space.manage", "roles.manage"})
НАД_ПРОВЕРКОЙ = frozenset(
    {"inspection.retract", "inspection.move", "inspection.accept", "inspection.revise",
     "inspection.letter"}
)


def _все(коды: frozenset[str]) -> dict[str, str]:
    return {код: "all" for код in коды}


СВОИ = {код: "own" for код in НАД_ПРОВЕРКОЙ}
СПЕКА: dict[str, dict[str, str]] = {
    "hq_admin": _все(ВСЕ),
    # D310: unit.create у сотрудника УК остаётся; D311: над проверкой — свои.
    "hq_staff": {**_все(ВСЕ - {"people.manage", "space.manage", "roles.manage"}), **СВОИ},
    "country_admin": _все(ВСЕ - ТОЛЬКО_УК),
    "country_staff": {
        **_все(frozenset({"inspection.conduct", "prescription.reply", "plan.submit",
                          "mcp.connect"})),
        **СВОИ,
    },
}
ПРОСТРАНСТВО = {"hq_admin": "HQ", "hq_staff": "HQ", "country_admin": "GE", "country_staff": "GE"}
ОБЪЕКТЫ = ("HQ", "GE", "AM")
АВТОРЫ = ("я", "другой", "неизвестен")

Решатель = Callable[..., Decision]


def _учётка(роль: str) -> str:
    return f"u-{роль}"


def _автор(роль: str, кто: str) -> str | None:
    return {"я": _учётка(роль), "другой": "u-other", "неизвестен": None}[кто]


def ожидание(роль: str, действие: str, объект: str, автор: str) -> tuple[bool, str]:
    кто = ПРОСТРАНСТВО[роль]
    if кто != "HQ":
        if действие in ТОЛЬКО_УК:
            return False, "hq_only"
        if объект == "HQ":
            return False, "hq_object"
        if объект != кто:
            return False, "foreign_space"
    охват = СПЕКА[роль].get(действие)
    if охват is None:
        return False, "matrix"
    if охват == "own" and автор != "я":
        return False, "not_author"
    return True, "ok"


def _строки(действие: str) -> tuple[str, ...]:
    return АВТОРЫ if действие in НАД_ПРОВЕРКОЙ else ("—",)


def сверить(решать: Решатель, матрица: Mapping[str, Mapping[str, str]]) -> list[str]:
    нарушения: list[str] = []
    for роль, кто in ПРОСТРАНСТВО.items():
        человек = Actor(tenant=кто, role=роль, grants=матрица[роль], user_id=_учётка(роль))
        for действие in sorted(ВСЕ):
            for объект in ОБЪЕКТЫ:
                for автор in _строки(действие):
                    можно, правило = ожидание(роль, действие, объект, автор)
                    if действие in НАД_ПРОВЕРКОЙ:
                        вышло = решать(человек, действие, объект, object_author=_автор(роль, автор))
                    else:
                        вышло = решать(человек, действие, объект)
                    if вышло.allowed != можно:
                        нарушения.append(
                            f"{роль} × {действие} × {объект} × {автор}: ожидалось "
                            f"{'да' if можно else 'нет'} ({правило}), вышло "
                            f"{'да' if вышло.allowed else 'нет'} ({вышло.rule})"
                        )
    return нарушения


def _сломать(роль: str, **права: str) -> dict[str, Mapping[str, str]]:
    return {**DEFAULT_MATRIX, роль: {**DEFAULT_MATRIX[роль], **права}}


def test_матрица_по_умолчанию_равна_таблице_спеки() -> None:
    assert {р: dict(п) for р, п in DEFAULT_MATRIX.items()} == СПЕКА
    assert dict(ROLE_SCOPES) == {
        "hq_admin": "hq", "hq_staff": "hq", "country_admin": "country", "country_staff": "country",
    }


def test_таблица_прав_ролей_по_умолчанию() -> None:
    assert сверить(can, DEFAULT_MATRIX) == []


def test_сломанная_матрица_не_пробивает_границу() -> None:
    сломанная = _сломать("country_staff", **{"checklist.edit": "all"})
    assert сверить(can, сломанная) == [
        "country_staff × checklist.edit × GE × —: ожидалось нет (matrix), вышло да (ok)"
    ]


def test_сломанный_охват_свои_называет_каждую_чужую_проверку() -> None:
    сломанная = _сломать("hq_staff", **{"inspection.retract": "all"})
    assert сверить(can, сломанная) == [
        f"hq_staff × inspection.retract × {объект} × {автор}: ожидалось нет (not_author), "
        f"вышло да (ok)"
        for объект in ОБЪЕКТЫ
        for автор in ("другой", "неизвестен")
    ]


def test_проверка_таблицы_ловит_can_без_автора() -> None:
    def автор_всегда_свой(человек: Actor, действие: str, объект: str, **_: object) -> Decision:
        return can(человек, действие, объект, object_author=человек.user_id)

    нарушения = сверить(автор_всегда_свой, DEFAULT_MATRIX)
    assert "country_staff × inspection.move × GE × неизвестен: ожидалось нет (not_author), вышло да (ok)" in нарушения


def test_проверка_таблицы_ловит_снятую_границу() -> None:
    def без_границы(человек: Actor, действие: str, _объект: str, **_: object) -> Decision:
        if действие in человек.grants:
            return Decision(True, RULE_OK)
        return Decision(False, RULE_MATRIX)

    нарушения = сверить(без_границы, _сломать("country_staff", **{"checklist.edit": "all"}))
    assert "country_staff × checklist.edit × HQ × —: ожидалось нет (hq_object), вышло да (ok)" in нарушения
    assert any("(foreign_space)" in н for н in нарушения)


def test_матрица_по_умолчанию_годна() -> None:
    assert validate_matrix(DEFAULT_MATRIX, ROLE_SCOPES) == []


def test_проверка_матрицы_называет_только_уК_у_роли_страны() -> None:
    assert validate_matrix(_сломать("country_admin", **{"unit.create": "all"}), ROLE_SCOPES) == [
        "country_admin: unit.create — действие только УК (hq_only)"
    ]


def test_проверка_матрицы_называет_свои_не_над_проверкой() -> None:
    assert validate_matrix(_сломать("hq_staff", **{"checklist.edit": "own"}), ROLE_SCOPES) == [
        "hq_staff: checklist.edit — охват «own» только у действий над проверкой"
    ]


def test_проверка_матрицы_называет_незнакомый_охват() -> None:
    assert validate_matrix(_сломать("hq_staff", **{"mcp.connect": "some"}), ROLE_SCOPES) == [
        "hq_staff: mcp.connect — охват «some» не из own/all"
    ]


def test_проверка_матрицы_называет_код_не_из_каталога() -> None:
    assert validate_matrix(_сломать("hq_staff", **{"inspection.delete": "all"}), ROLE_SCOPES) == [
        "hq_staff: inspection.delete — нет в каталоге действий"
    ]


def test_проверка_матрицы_называет_роль_без_охвата() -> None:
    assert validate_matrix({"ghost": {}}, ROLE_SCOPES) == ["ghost: у роли нет охвата"]


@pytest.mark.parametrize(
    ("старая", "пространство", "новая"),
    [
        ("admin", "HQ", "hq_admin"),
        ("auditor", "HQ", "hq_staff"),
        ("auditor", "default", "hq_staff"),
        ("admin", "GE", "country_admin"),
        ("auditor", "GE", "country_staff"),
        ("hq_staff", "HQ", "hq_staff"),
        ("country_auditor_plus", "GE", "country_auditor_plus"),
    ],
)
def test_старая_роль_переводится_по_пространству(старая: str, пространство: str, новая: str) -> None:
    assert canonical_role(старая, пространство) == новая


def test_пустая_роль_это_ошибка_кода() -> None:
    with pytest.raises(ValueError, match="роль"):
        canonical_role(" ", "HQ")
```

- [ ] **Step 2: Прогнать — ожидается FAIL**

Run: `.venv/bin/pytest tests/test_permissions_table.py -q`
Expected: FAIL — `ImportError: cannot import name 'DEFAULT_MATRIX' from 'src.domain.permissions'`.

- [ ] **Step 3: Минимальная реализация** — дописать в конец `src/domain/permissions.py`:

```python
SCOPE_HQ = "hq"
SCOPE_COUNTRY = "country"

ROLE_HQ_ADMIN = "hq_admin"
ROLE_HQ_STAFF = "hq_staff"
ROLE_COUNTRY_ADMIN = "country_admin"
ROLE_COUNTRY_STAFF = "country_staff"

#: Охват ролей по умолчанию. Заведённые админом УК роли (блок 2) несут охват в
#: строке `roles.scope`, а не здесь.
ROLE_SCOPES: Mapping[str, str] = {
    ROLE_HQ_ADMIN: SCOPE_HQ,
    ROLE_HQ_STAFF: SCOPE_HQ,
    ROLE_COUNTRY_ADMIN: SCOPE_COUNTRY,
    ROLE_COUNTRY_STAFF: SCOPE_COUNTRY,
}


def _all(codes: frozenset[str]) -> dict[str, str]:
    return {код: REACH_ALL for код in codes}


#: Сотрудник правит только проверки, которые занёс сам (D311).
_OWN_INSPECTIONS: Mapping[str, str] = {код: REACH_OWN for код in INSPECTION_OBJECT_ACTIONS}

#: Права по умолчанию — таблица спеки с поправками D310 (`unit.create` у
#: `hq_staff`) и D311 (охват «свои» у сотрудников). Засев `0038` сверяется с
#: ней тестом (`tests/test_db_roles_migration.py`), а не копируется руками.
DEFAULT_MATRIX: Mapping[str, Grants] = {
    ROLE_HQ_ADMIN: _all(ACTION_CODES),
    ROLE_HQ_STAFF: {
        **_all(ACTION_CODES - {"people.manage", "space.manage", "roles.manage"}),
        **_OWN_INSPECTIONS,
    },
    ROLE_COUNTRY_ADMIN: _all(ACTION_CODES - HQ_ONLY_ACTIONS),
    ROLE_COUNTRY_STAFF: {
        **_all(frozenset({"inspection.conduct", "prescription.reply", "plan.submit",
                          "mcp.connect"})),
        **_OWN_INSPECTIONS,
    },
}

#: Роли учёток до спеки «Администрирование» (`0020`). Живут в командах стендов
#: (`make web-user ... role <логин> admin`) и в тестах; переводятся на входе.
LEGACY_ROLE_ADMIN = "admin"
LEGACY_ROLE_AUDITOR = "auditor"
_LEGACY: Mapping[tuple[str, str], str] = {
    (LEGACY_ROLE_ADMIN, SCOPE_HQ): ROLE_HQ_ADMIN,
    (LEGACY_ROLE_AUDITOR, SCOPE_HQ): ROLE_HQ_STAFF,
    (LEGACY_ROLE_ADMIN, SCOPE_COUNTRY): ROLE_COUNTRY_ADMIN,
    (LEGACY_ROLE_AUDITOR, SCOPE_COUNTRY): ROLE_COUNTRY_STAFF,
}


def scope_of_tenant(tenant: str) -> str:
    """Охват ролей пространства: у УК — роли УК, у страны — роли страны."""
    return SCOPE_HQ if _required_tenant(tenant, what="пространство") == HQ_TENANT else SCOPE_COUNTRY


def canonical_role(role: str, tenant: str) -> str:
    """Код роли: старое `admin`/`auditor` переводится по пространству, прочее — как есть."""
    код = (role or "").strip()
    if not код:
        raise ValueError("Не задана роль учётки")
    return _LEGACY.get((код, scope_of_tenant(tenant)), код)


def _grant_problem(роль: str, охват_роли: str, код: str, охват: str) -> str | None:
    if код not in ACTION_CODES:
        return f"{роль}: {код} — нет в каталоге действий"
    if охват not in (REACH_OWN, REACH_ALL):
        return f"{роль}: {код} — охват «{охват}» не из own/all"
    if охват == REACH_OWN and код not in INSPECTION_OBJECT_ACTIONS:
        return f"{роль}: {код} — охват «own» только у действий над проверкой"
    if охват_роли == SCOPE_COUNTRY and код in HQ_ONLY_ACTIONS:
        return f"{роль}: {код} — действие только УК ({RULE_HQ_ONLY})"
    return None


def validate_matrix(matrix: Mapping[str, Grants], scopes: Mapping[str, str]) -> list[str]:
    """Нарушения матрицы словами: код или охват не из каталога, «только УК» у страны."""
    нарушения: list[str] = []
    for роль in sorted(matrix):
        охват_роли = scopes.get(роль)
        if охват_роли is None:
            нарушения.append(f"{роль}: у роли нет охвата")
            continue
        for код in sorted(matrix[роль]):
            беда = _grant_problem(роль, охват_роли, код, matrix[роль][код])
            if беда is not None:
                нарушения.append(беда)
    return нарушения
```

- [ ] **Step 4: Прогнать — ожидается PASS**

Run: `.venv/bin/pytest tests/test_permissions_can.py tests/test_permissions_table.py -q && .venv/bin/ruff check src/domain tests/test_permissions_table.py && .venv/bin/mypy`
Expected: PASS; ruff, mypy чистые.

- [ ] **Step 5: Коммит и пуш**

```bash
git add src/domain/permissions.py tests/test_permissions_table.py
git commit -m "feat: роли по умолчанию (D310, D311) и таблица прав с прогоном на сломанной матрице

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

### Task 3: Миграция `0038`: роли, права ролей с охватом, перенос учёток

**Files:**
- Create: `src/db/migrations/0038_roles.sql`
- Create: `tests/test_db_roles_migration.py`
- Modify: `tests/test_db_migrations_frozen.py` (словарь `ОТПЕЧАТКИ`, после строки `"0037_prescriptions.sql"`, ~строка 164)
- Modify: `tests/test_db_migrate_roles.py` (`APP_TABLE_GRANTS` ~строка 168, `ADMIN_TABLE_GRANTS` ~строка 274)
- Modify: `docs/furca/blocks/db.md` (раздел «API-контракт», после блока про учётки ~строка 67), `docs/08-deploy.md` (новый раздел `### 8.14` после `### 8.13`), `docs/12-web-admin.md` (команды `make web-user`, ~строки 328–333)
- Modify (мост ролей — без него с наката `0038` админ-действия веба и учётки в тестах ломаются до Task 10–11): `src/db/web_access.py` (`ROLES` ~233, `_checked_role` ~425, `create_account` ~476, `reassign_role` ~554), `src/web/accounts.py` (реэкспорт, ~20–45), `src/web/people.py` (`change_role` ~56–62), `src/web/app.py` (`_hq_admin_only` ~1435, `_admin_only` ~1452), `src/web/templates/base.html` (~141), `src/web/texts.py` (рядом с `nav.role.*` ~56 и `users.role.*` ~952), `tools/web_user.py` (~183, `choices=ROLES`)
- Modify: `tests/test_db_web_access.py` (ожидания ролей ~433–471; вставки без роли ~97, ~242, ~255)

**Interfaces:**
- Consumes: `DEFAULT_MATRIX`, `ROLE_SCOPES` (Task 2) — только в тесте; `canonical_role`, `ROLE_SCOPES`, `LEGACY_ROLE_ADMIN`, `LEGACY_ROLE_AUDITOR`, `ROLE_HQ_ADMIN`, `ROLE_COUNTRY_ADMIN` (Task 2) — в мосте ролей; `db_harness.empty_database`, `src.db.migrate.apply_migrations(dsn, *, directory)`, `src.db.migrate.MIGRATIONS_DIR`, `src.db.web_access.password_hash(password) -> str`.
- Produces (схема): `roles(code PK, scope, name_ru, name_en, created_at)`; `role_permissions(role_code FK, action_code, reach ∈ {own, all}, PK(role_code, action_code))`, `own` только у пяти действий над проверкой (ограничение `role_permissions_own_on_inspection`); `web_users.role` → FK `web_users_role_fkey`; триггер `web_users_role_scope` (`check_violation`, `constraint = 'web_users_role_scope'`); `select` на `roles`, `role_permissions` ролям `dodo_audit_app` и `dodo_audit_admin`.
- Produces (мост ролей, живёт до Task 11): `web_access.ROLES = tuple(ROLE_SCOPES)` (четыре кода), `web_access.LEGACY_ROLES = (ROLE_AUDITOR, ROLE_ADMIN)`; `_checked_role(role: str, tenant: str) -> str` (код по `canonical_role`, вне `ROLES` — `AccessError("Роль «…» не заведена. Есть: …")`); `accounts.LEGACY_ROLES`; `app._is_admin(account) -> bool`, `app._is_hq_admin(account) -> bool`; ключи текстов `nav.role.<код>`, `users.role.<код>` для четырёх кодов (ru/en).

- [ ] **Step 1: Написать падающий тест**

```python
# tests/test_db_roles_migration.py
"""Миграция `0038`: роли по умолчанию и перенос учёток (спека «Администрирование», D310, D311).

Ядро (права): каждая текущая учётка получает роль по таблице переноса, засев
совпадает с `DEFAULT_MATRIX`, роль чужого охвата не ложится никому.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from conftest import requires_db
from db_harness import empty_database

psycopg = pytest.importorskip("psycopg")

from src.db.migrate import MIGRATIONS_DIR, apply_migrations  # noqa: E402
from src.db.web_access import password_hash  # noqa: E402
from src.domain.permissions import DEFAULT_MATRIX, ROLE_SCOPES  # noqa: E402

pytestmark = requires_db

МИГРАЦИЯ = "0038_roles.sql"
ХЕШ = password_hash("пароль-для-переноса")


def _каталог(tmp_path: Path, *, включая: bool) -> Path:
    каталог = tmp_path / ("по" if включая else "до")
    каталог.mkdir()
    for файл in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if файл.name < МИГРАЦИЯ or (включая and файл.name == МИГРАЦИЯ):
            shutil.copy(файл, каталог / файл.name)
    return каталог


def test_каждая_учётка_получает_роль_по_таблице(tmp_path: Path) -> None:
    with empty_database() as dsn:
        apply_migrations(dsn, directory=_каталог(tmp_path, включая=False))
        with psycopg.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("insert into tenants (code) values ('GE')")
            for tenant, login, role in (
                ("HQ", "hq-admin", "admin"),
                ("HQ", "hq-auditor", "auditor"),
                ("GE", "ge-admin", "admin"),
                ("GE", "ge-auditor", "auditor"),
            ):
                cur.execute(
                    "insert into web_users (tenant_code, login, password_hash, role) "
                    "values (%s, %s, %s, %s)",
                    (tenant, login, ХЕШ, role),
                )
        assert apply_migrations(dsn, directory=_каталог(tmp_path, включая=True)) == [МИГРАЦИЯ]
        with psycopg.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("select login, role from web_users order by login")
            assert cur.fetchall() == [
                ("ge-admin", "country_admin"),
                ("ge-auditor", "country_staff"),
                ("hq-admin", "hq_admin"),
                ("hq-auditor", "hq_staff"),
            ]


def test_засев_ролей_равен_матрице_по_умолчанию(pg_dsn: str) -> None:
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute("select code, scope from roles")
        assert dict(cur.fetchall()) == dict(ROLE_SCOPES)
        cur.execute("select role_code, action_code, reach from role_permissions")
        засев: dict[str, dict[str, str]] = {}
        for роль, код, охват in cur.fetchall():
            засев.setdefault(роль, {})[код] = охват
        assert засев == {р: dict(п) for р, п in DEFAULT_MATRIX.items()}


def test_свои_не_ложатся_на_действие_не_над_проверкой(pg_dsn: str) -> None:
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        with pytest.raises(psycopg.errors.CheckViolation) as отказ:
            cur.execute(
                "update role_permissions set reach = 'own' "
                "where role_code = 'hq_staff' and action_code = 'checklist.edit'"
            )
        assert отказ.value.diag.constraint_name == "role_permissions_own_on_inspection"


def test_роль_чужого_охвата_не_ложится(pg_dsn: str) -> None:
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute("insert into tenants (code) values ('GE')")
        with pytest.raises(psycopg.errors.CheckViolation) as отказ:
            cur.execute(
                "insert into web_users (tenant_code, login, password_hash, role) "
                "values ('GE', 'ge-intruder', %s, 'hq_admin')",
                (ХЕШ,),
            )
        assert отказ.value.diag.constraint_name == "web_users_role_scope"


def test_незаведённая_роль_не_ложится(pg_dsn: str) -> None:
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            cur.execute(
                "insert into web_users (tenant_code, login, password_hash, role) "
                "values ('HQ', 'hq-ghost', %s, 'admin')",
                (ХЕШ,),
            )


def test_смена_пространства_проверяет_охват_роли(pg_dsn: str) -> None:
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute("insert into tenants (code) values ('GE')")
        cur.execute(
            "insert into web_users (tenant_code, login, password_hash, role) "
            "values ('HQ', 'hq-mover', %s, 'hq_staff')",
            (ХЕШ,),
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            cur.execute("update web_users set tenant_code = 'GE' where login = 'hq-mover'")
```

Дописать в `tests/test_db_migrations_frozen.py`, словарь `ОТПЕЧАТКИ`, после `"0037_prescriptions.sql"` — строку с отпечатком, который печатает команда Step 4:

```python
    # Роли и права ролей (спека «Администрирование», блок 1). Заведена вместе с файлом.
    "0038_roles.sql": ("sql1:<значение из Step 4>"),
```

Дописать в `tests/test_db_migrate_roles.py`:

```python
# в APP_TABLE_GRANTS, после строки "country_recipients": {"SELECT"},
    # Роли и права ролей (`0038`): приложение их только читает — права роли
    # приезжают вместе с опознанием. Пишет их экран админа УК (блок 2).
    "roles": {"SELECT"},
    "role_permissions": {"SELECT"},
# в ADMIN_TABLE_GRANTS, после строки "country_recipients": {"SELECT"},
    # Роли (`0038`): триггер охвата роли читает `roles` под ролью того, кто
    # заводит учётку, — без чтения заведение отказало бы нехваткой прав.
    "roles": {"SELECT"},
    "role_permissions": {"SELECT"},
```

- [ ] **Step 2: Прогнать — ожидается FAIL**

Run: `nc -z 127.0.0.1 55432 && make test-honest ARGS="tests/test_db_roles_migration.py tests/test_db_migrate_roles.py -q -rs"`
Expected: FAIL — `assert [] == ['0038_roles.sql']`, `relation "roles" does not exist`; в `test_db_migrate_roles.py` лишние таблицы в ожидании. Строк `SKIPPED` нет.

- [ ] **Step 3: Минимальная реализация**

```sql
-- 0038_roles.sql
--
-- Роли с матрицей «роль × действие» (спека «Администрирование», D306, D309-D311).
--
-- Человеку назначается роль, права роли определяют, что она может. Граница
-- пространств правами не задаётся: её держит `can` в коде
-- (`src/domain/permissions.py`), здесь — только охват роли (УК или страна).
--
-- ОХВАТ ПРАВА (D311). У действий над проверкой право несёт охват: `own` —
-- только проверки, которые занесла учётка человека, `all` — все проверки, до
-- которых пускает граница. У прочих действий — только `all`. Нет строки — нет
-- права.
--
-- ПЕРЕНОС. Роли учёток до этой миграции — `admin`/`auditor` (`0020`). Они
-- переводятся по пространству учётки ровно по таблице спеки:
--   HQ × admin → hq_admin, HQ × auditor → hq_staff,
--   страна × admin → country_admin, страна × auditor → country_staff.
--
-- ЗАСЕВ — таблица спеки с D310 (`unit.create` у `hq_staff`) и D311 (сотрудникам
-- над проверкой — `own`); с кодом (`DEFAULT_MATRIX`) его сверяет
-- `tests/test_db_roles_migration.py`.
--
-- Раннер оборачивает файл в одну транзакцию сам — begin/commit здесь не нужны.

create table roles (
    code text primary key check (code ~ '^[a-z][a-z0-9_]{1,39}$'),
    scope text not null check (scope in ('hq', 'country')),
    name_ru text not null check (length(btrim(name_ru)) between 1 and 80),
    name_en text not null check (length(btrim(name_en)) between 1 and 80),
    created_at timestamptz not null default now()
);

create table role_permissions (
    role_code text not null references roles (code) on delete cascade,
    action_code text not null check (action_code ~ '^[a-z]+\.[a-z_]+$'),
    reach text not null default 'all' check (reach in ('own', 'all')),
    primary key (role_code, action_code),
    constraint role_permissions_own_on_inspection check (
        reach = 'all' or action_code in (
            'inspection.retract', 'inspection.move', 'inspection.accept',
            'inspection.revise', 'inspection.letter'
        )
    )
);

insert into roles (code, scope, name_ru, name_en) values
    ('hq_admin', 'hq', 'Админ УК', 'HQ admin'),
    ('hq_staff', 'hq', 'Сотрудник УК', 'HQ staff'),
    ('country_admin', 'country', 'Админ страны', 'Country admin'),
    ('country_staff', 'country', 'Сотрудник страны', 'Country staff');

insert into role_permissions (role_code, action_code, reach)
select 'hq_admin', код, 'all' from unnest(array[
    'inspection.conduct', 'inspection.retract', 'inspection.move', 'inspection.accept',
    'inspection.revise', 'inspection.letter', 'prescription.manage', 'prescription.reply',
    'plan.manage', 'plan.submit', 'checklist.edit', 'checklist.publish', 'checklist.manage',
    'phrases.manage', 'people.manage', 'mcp.connect', 'unit.create', 'space.manage',
    'roles.manage'
]) as код
union all
select 'hq_staff', код, 'all' from unnest(array[
    'inspection.conduct', 'prescription.manage', 'prescription.reply', 'plan.manage',
    'plan.submit', 'checklist.edit', 'checklist.publish', 'checklist.manage',
    'phrases.manage', 'mcp.connect', 'unit.create'
]) as код
union all
select 'country_admin', код, 'all' from unnest(array[
    'inspection.conduct', 'inspection.retract', 'inspection.move', 'inspection.accept',
    'inspection.revise', 'inspection.letter', 'prescription.manage', 'prescription.reply',
    'plan.manage', 'plan.submit', 'checklist.edit', 'checklist.publish', 'checklist.manage',
    'phrases.manage', 'people.manage', 'mcp.connect'
]) as код
union all
select 'country_staff', код, 'all' from unnest(array[
    'inspection.conduct', 'prescription.reply', 'plan.submit', 'mcp.connect'
]) as код
union all
select роль, код, 'own'
  from unnest(array['hq_staff', 'country_staff']) as роль
 cross join unnest(array[
    'inspection.retract', 'inspection.move', 'inspection.accept', 'inspection.revise',
    'inspection.letter'
]) as код;

-- Прежнее ограничение `0020` знает только admin/auditor — снимается до переноса.
alter table web_users drop constraint web_users_role_check;
alter table web_users alter column role drop default;

update web_users
   set role = case
       when tenant_code = 'HQ' and role = 'admin' then 'hq_admin'
       when tenant_code = 'HQ' then 'hq_staff'
       when role = 'admin' then 'country_admin'
       else 'country_staff'
   end;

alter table web_users
    add constraint web_users_role_fkey foreign key (role) references roles (code);

comment on column web_users.role is
    'Код роли (roles.code): что человеку можно — правами role_permissions. '
    'Роль УК — только у людей HQ, роль страны — только у людей страны '
    '(триггер web_users_role_scope). Чью историю видно, решает tenant_code.';

-- Охват роли сверяется со строкой учётки: роль УК у партнёра — отказ. Внешний
-- ключ этого не выразит: условие смотрит в две таблицы.
create function web_users_role_scope() returns trigger
    language plpgsql
    set search_path = pg_catalog, public, pg_temp
as $$
declare
    охват text;
begin
    -- Пустую роль ловит `not null`, незаведённую — внешний ключ: каждый отказ
    -- называет свою причину. Триггер BEFORE стреляет раньше обоих, и без этой
    -- строки он отвечал бы «не для пространства» на опечатку в роли, а тесты
    -- прочих ограничений строки зеленели бы его отказом, а не своим.
    if new.role is null or not exists (select 1 from roles where code = new.role) then
        return new;
    end if;
    select scope into охват from roles where code = new.role;
    if охват is distinct from (case when new.tenant_code = 'HQ' then 'hq' else 'country' end) then
        raise exception 'Роль % не для пространства %', new.role, new.tenant_code
            using errcode = 'check_violation', constraint = 'web_users_role_scope';
    end if;
    return new;
end;
$$;

create trigger web_users_role_scope
    before insert or update of role, tenant_code on web_users
    for each row execute function web_users_role_scope();

grant select on roles, role_permissions to dodo_audit_app, dodo_audit_admin;
```

**Мост ролей.** С наката `0038` в базе лежат новые коды, а веб сравнивает строку роли с `"admin"` (`_admin_only`, `_hq_admin_only`), двери учёток пишут `admin`/`auditor` (их отвергнет внешний ключ), шаблоны ищут подписи `users.role.<роль>`. Мост переводит старое имя по пространству там, где его сравнивают, и принимает оба вида на входе. Двойник учётки веба (`tests/web_harness.py`) до Task 7 отдаёт старые имена — мост понимает и их.

`src/db/web_access.py` — блок ролей (~строки 228–233) заменить:

```python
from src.domain.permissions import (
    LEGACY_ROLE_ADMIN,
    LEGACY_ROLE_AUDITOR,
    ROLE_SCOPES,
    canonical_role,
)

#: Старые имена ролей (`0020`) — псевдонимы: команды стендов, формы и тесты
#: зовут `admin`/`auditor`, перевод по пространству — `canonical_role`.
ROLE_AUDITOR = LEGACY_ROLE_AUDITOR
ROLE_ADMIN = LEGACY_ROLE_ADMIN
LEGACY_ROLES: tuple[str, ...] = (ROLE_AUDITOR, ROLE_ADMIN)
#: Коды ролей по умолчанию (`0038`). Мост до Task 11: там выбор роли берётся
#: из таблицы `roles`, а этот перечень уходит.
ROLES: tuple[str, ...] = tuple(ROLE_SCOPES)
```

и `_checked_role` (~425):

```python
def _checked_role(role: str, tenant: str) -> str:
    """Код роли: старое имя переводится по пространству, незнакомое — отказ."""
    try:
        код = canonical_role(role, tenant)
    except ValueError as exc:
        raise AccessError("Роль не задана") from exc
    if код not in ROLES:
        raise AccessError(f"Роль «{role}» не заведена. Есть: {', '.join(ROLES)}")
    return код
```

В `create_account` — `роль = _checked_role(role, tenant)`; в `reassign_role` — `роль = _checked_role(role, tenant)`.

`src/web/accounts.py`: в импорт из `src.db.web_access` и в `__all__` добавить `LEGACY_ROLES`.

`src/web/people.py`, `change_role` — первая проверка:

```python
    if role not in accounts.ROLES and role not in accounts.LEGACY_ROLES:
        return Outcome("role.unknown", 400)
```

`src/web/app.py` (импорт `from src.domain.permissions import ROLE_COUNTRY_ADMIN, ROLE_HQ_ADMIN, canonical_role`):

```python
def _is_admin(account: Any) -> bool:
    """Мост ролей (до Task 10): админ УК или админ страны — по коду или старому имени."""
    return canonical_role(account.role, account.tenant) in (ROLE_HQ_ADMIN, ROLE_COUNTRY_ADMIN)


def _is_hq_admin(account: Any) -> bool:
    """Мост ролей (до Task 11): админ УК — по коду или старому имени."""
    return canonical_role(account.role, account.tenant) == ROLE_HQ_ADMIN
```

В `_hq_admin_only` условие `вошедший.role == accounts.ROLE_ADMIN and canonical_tenant(вошедший.tenant) == HQ_TENANT` → `_is_hq_admin(вошедший)`; в `_admin_only` `вошедший.role == accounts.ROLE_ADMIN` → `_is_admin(вошедший)`.

`src/web/texts.py` — рядом с `nav.role.admin`/`nav.role.auditor` и рядом с `users.role.admin`/`users.role.auditor` (старые ключи остаются до Task 11: их зовёт двойник учётки до Task 7 и строки перечня со старой ролью):

```python
    "nav.role.hq_admin": {"ru": "Админ", "en": "Admin"},
    "nav.role.hq_staff": {"ru": "Аудитор", "en": "Auditor"},
    "nav.role.country_admin": {"ru": "Админ", "en": "Admin"},
    "nav.role.country_staff": {"ru": "Аудитор", "en": "Auditor"},
```

```python
    "users.role.hq_admin": {"ru": "И управление людьми", "en": "Also manages people"},
    "users.role.hq_staff": {"ru": "Работа с проверками", "en": "Inspections only"},
    "users.role.country_admin": {"ru": "И управление людьми", "en": "Also manages people"},
    "users.role.country_staff": {"ru": "Работа с проверками", "en": "Inspections only"},
```

`src/web/templates/base.html` ~141: `{{ t('nav.role.admin') if account.role == 'admin' else t('nav.role.auditor') }}` → `{{ t('nav.role.' ~ account.role) }}`.

`tools/web_user.py` ~183: `choices=ROLES` → `choices=(*ROLES, *LEGACY_ROLES)`, импорт `LEGACY_ROLES` из `src.db.web_access`; `help` — «код роли (hq_admin, hq_staff, country_admin, country_staff) или старое admin/auditor».

`tests/test_db_web_access.py` (`ТЕНАНТ = "rs"` — пространство страны), импорт `from src.domain.permissions import ROLE_COUNTRY_ADMIN, ROLE_COUNTRY_STAFF`:
- `test_заведённая_учётка_по_умолчанию_не_админ` (~433, ~438): `== ROLE_AUDITOR` → `== ROLE_COUNTRY_STAFF`;
- `test_роль_назначается_и_видна_вошедшему` (~447, ~451): `== ROLE_ADMIN` → `== ROLE_COUNTRY_ADMIN` (назначение по-прежнему `role=ROLE_ADMIN` — псевдоним);
- `test_смена_роли_называет_прежнюю` (~458–462): `== ROLE_AUDITOR` → `== ROLE_COUNTRY_STAFF`, `== ROLE_ADMIN` → `== ROLE_COUNTRY_ADMIN` (в обоих `assert reassign_role(...)` и в последнем `опознанная.role`);
- `test_роль_чужого_тенанта_не_назначается` (~471): `== ROLE_AUDITOR` → `== ROLE_COUNTRY_STAFF`;
- вставки без роли (~97, ~242, ~255): список колонок `(tenant_code, login, password_hash, role)`, значение роли `'country_staff'` — иначе после снятия умолчания роли они ловят `not null`, а не ограничение, которое называют.

- [ ] **Step 4: Отпечаток в список и прогон — ожидается PASS**

Run: `.venv/bin/python -c "from src.db.migrate import discover_migrations as d; print([m.checksum for m in d() if m.filename == '0038_roles.sql'][0])"` — вписать выведенное значение в строку `"0038_roles.sql"` в `tests/test_db_migrations_frozen.py`.
Run: `make test-honest ARGS="tests/test_db_roles_migration.py tests/test_db_migrate_roles.py tests/test_db_migrations_frozen.py tests/test_db_web_access.py tests/test_db_web_own_password.py tests/test_db_web_unlock.py tests/test_db_bot_links.py tests/test_db_no_implicit_spaces.py tests/test_db_password_bounds.py -q -rs"`
Expected: PASS, `SKIPPED` нет.
Run: `.venv/bin/pytest tests/test_web_*.py -q`
Expected: PASS — двойник отдаёт старые имена, мост их понимает.
Отрицательный прогон триггера: в `0038_roles.sql` временно убрать строку `if new.role is null or not exists ...` с её `end if;`, прогнать `test_незаведённая_роль_не_ложится` → FAIL `CheckViolation`; вернуть (`git diff src/db/migrations/0038_roles.sql` — только своя правка), PASS.

- [ ] **Step 5: Документация тем же коммитом**

`docs/furca/blocks/db.md`, раздел «API-контракт», после строк про учётки (~строка 67):

```
# роли и права ролей (0038, спека «Администрирование», D310, D311) — roles, role_permissions
#   roles(code, scope ∈ {hq, country}, name_ru, name_en): роль относится к УК или к стране
#   role_permissions(role_code, action_code, reach ∈ {own, all}): право роли на действие;
#   own — только проверки, занесённые учёткой человека, и только у пяти действий над
#   проверкой (role_permissions_own_on_inspection); нет строки — нет права
#   коды — каталог src/domain/permissions.py (ACTIONS); граница пространств — в can
#   web_users.role → roles.code; роль УК только у людей HQ, роль страны только у людей
#   страны (триггер web_users_role_scope, check_violation)
#   засев — DEFAULT_MATRIX, перенос admin/auditor × HQ/страна → 4 роли
```

`docs/12-web-admin.md`, строки команд (~330) — строку `role director admin` заменить:

```
make web-user ARGS="role director hq_admin --tenant HQ"   # первый админ стенда (старое «admin» тоже понимается)
```

и строка под блоком команд: «Роли — коды `hq_admin`, `hq_staff`, `country_admin`, `country_staff` (`src/domain/permissions.py`); роль УК — только людям `HQ`, роль страны — только людям страны.»

`docs/08-deploy.md` — новый раздел после `### 8.13`:

```markdown
### 8.14. Раскатка ядра прав, блок 1 «Администрирование»

1. **Миграция `0038_roles.sql`** — таблицы `roles`, `role_permissions`, четыре роли по
   умолчанию, перенос `web_users.role`: `HQ × admin → hq_admin`, `HQ × auditor → hq_staff`,
   `страна × admin → country_admin`, `страна × auditor → country_staff`. Перед накатом
   посмотреть, кто что получит: `make web-user ARGS="list --tenant <код>"` на целевой базе по
   каждому пространству (коды — `select code from tenants`; без `--tenant` и `WEB_TENANT`
   команда отказывает).
2. **Миграция `0039_cross_space_actions.sql`** — пустой журнал действий УК у партнёра.
3. **Миграция `0040_inspection_author.sql`** — колонка `inspections.created_by`. У проверок,
   залитых до неё, автора нет: их снимают, переносят, подтверждают и правят только админы
   (D311). Автор появляется у проверок, начатых в боте человеком с привязкой к учётке.
4. Команда `make web-user ARGS="role <логин> <роль> --tenant <код>"` принимает коды
   `hq_admin`, `hq_staff`, `country_admin`, `country_staff`; старые `admin`/`auditor`
   переводятся по пространству учётки.
5. Переменные окружения не меняются: MCP в блоке 1 работает по прежним
   `MCP_TOKENS`, `MCP_CHECKLIST_TENANTS`, `MCP_RETRACTION_TOKENS`.
6. После наката: `make web-user ARGS="list --tenant <код>"` по каждому пространству — у каждой
   учётки код роли по таблице переноса.
```

- [ ] **Step 6: Коммит и пуш**

```bash
git add src/db/migrations/0038_roles.sql tests/test_db_roles_migration.py tests/test_db_migrations_frozen.py tests/test_db_migrate_roles.py tests/test_db_web_access.py src/db/web_access.py src/web/accounts.py src/web/people.py src/web/app.py src/web/templates/base.html src/web/texts.py tools/web_user.py docs/furca/blocks/db.md docs/08-deploy.md docs/12-web-admin.md
git commit -m "feat: миграция 0038 — роли, права ролей с охватом, перенос учёток, мост ролей

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

### Task 4: Миграция `0039` и журнал действий УК у партнёра

**Files:**
- Create: `src/db/migrations/0039_cross_space_actions.sql`
- Create: `src/db/cross_space.py`
- Create: `tests/test_db_cross_space.py`
- Modify: `tests/test_db_migrations_frozen.py` (строка `"0039_cross_space_actions.sql"`), `tests/test_db_migrate_roles.py` (`APP_TABLE_GRANTS`, `ADMIN_TABLE_GRANTS`)
- Modify: `docs/furca/blocks/db.md` (после блока ролей из Task 3)

**Interfaces:**
- Consumes: `Actor`, `UnknownAction`, `require_action` (Task 1); `canonical_tenant`; `db_harness.завести_пространства`.
- Produces:
  - `Entry(actor_web_user_id: str, actor_tenant: str, object_tenant: str, action_code: str, object_ref: str)` — frozen dataclass.
  - `entry_for(actor: Actor, *, object_tenant: str, action: str, object_ref: str) -> Entry | None` — `None`, когда пространство одно.
  - `record(conn: psycopg.Connection[Any], entry: Entry | None) -> None` — пишет на переданном подключении, не коммитит.
  - Схема: `cross_space_actions(id identity, at, actor_web_user_id → web_users, actor_tenant = 'HQ', object_tenant <> 'HQ', action_code, object_ref)`; `select, insert` ролям `dodo_audit_app` (правка на приёмке и письмо идут ролью приложения) и `dodo_audit_admin`.

- [ ] **Step 1: Написать падающий тест**

```python
# tests/test_db_cross_space.py
"""Журнал действий человека УК в пространстве партнёра (спека «Администрирование», D017).

Запись ложится тем же подключением, что и действие, и только при его коммите.
"""

from __future__ import annotations

import pytest
from conftest import requires_db
from db_harness import завести_пространства

psycopg = pytest.importorskip("psycopg")

from src.db.cross_space import Entry, entry_for, record  # noqa: E402
from src.db.web_access import password_hash  # noqa: E402
from src.domain.permissions import Actor, UnknownAction  # noqa: E402

pytestmark = requires_db


def _учётка_уК(pg_dsn: str) -> str:
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "insert into web_users (tenant_code, login, password_hash, role) "
            "values ('HQ', 'hq-journal', %s, 'hq_admin') returning id",
            (password_hash("пароль-журнала"),),
        )
        строка = cur.fetchone()
    assert строка is not None
    return str(строка[0])


def _уК(user_id: str | None = "u-1") -> Actor:
    return Actor(tenant="HQ", role="hq_admin", grants={}, user_id=user_id)


def test_своё_пространство_журнала_не_требует() -> None:
    assert entry_for(_уК(), object_tenant="HQ", action="inspection.retract", object_ref="x") is None


def test_чужое_пространство_даёт_запись() -> None:
    запись = entry_for(_уК(), object_tenant="GE", action="inspection.retract", object_ref="inspection:1")
    assert запись == Entry("u-1", "HQ", "GE", "inspection.retract", "inspection:1")


def test_запись_без_учётки_это_ошибка_кода() -> None:
    with pytest.raises(ValueError, match="учётк"):
        entry_for(_уК(None), object_tenant="GE", action="inspection.retract", object_ref="x")


def test_код_не_из_каталога_это_ошибка_кода() -> None:
    with pytest.raises(UnknownAction):
        entry_for(_уК(), object_tenant="GE", action="inspection.delete", object_ref="x")


def test_запись_ложится_только_с_коммитом(pg_dsn: str, db_env: str) -> None:
    завести_пространства(pg_dsn, "GE")
    кто = _учётка_уК(pg_dsn)
    with psycopg.connect(db_env) as conn:
        record(conn, Entry(кто, "HQ", "GE", "inspection.retract", "inspection:откат"))
        conn.rollback()
    with psycopg.connect(db_env) as conn:
        record(conn, Entry(кто, "HQ", "GE", "inspection.retract", "inspection:коммит"))
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute("select object_ref from cross_space_actions order by id")
        assert cur.fetchall() == [("inspection:коммит",)]


def test_схема_не_принимает_действие_партнёра(pg_dsn: str) -> None:
    завести_пространства(pg_dsn, "GE")
    кто = _учётка_уК(pg_dsn)
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        with pytest.raises(psycopg.errors.CheckViolation):
            cur.execute(
                "insert into cross_space_actions "
                "(actor_web_user_id, actor_tenant, object_tenant, action_code, object_ref) "
                "values (%s, 'GE', 'HQ', 'inspection.retract', 'x')",
                (кто,),
            )


def test_роль_приложения_журнал_не_правит(pg_dsn: str, db_env: str) -> None:
    завести_пространства(pg_dsn, "GE")
    кто = _учётка_уК(pg_dsn)
    with psycopg.connect(db_env) as conn:
        record(conn, Entry(кто, "HQ", "GE", "inspection.move", "inspection:1"))
    with psycopg.connect(db_env) as conn, conn.cursor() as cur:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute("delete from cross_space_actions")
```

Дописать в `tests/test_db_migrate_roles.py`:

```python
# APP_TABLE_GRANTS — после "role_permissions":
    # Журнал действий УК у партнёра (`0039`): приложение дописывает (правка
    # на приёмке и письмо идут его ролью), но не правит и не стирает.
    "cross_space_actions": {"SELECT", "INSERT"},
# ADMIN_TABLE_GRANTS — после "role_permissions":
    # Журнал (`0039`): снятие, перенос, приёмка и правка людей идут этой ролью.
    "cross_space_actions": {"SELECT", "INSERT"},
```

- [ ] **Step 2: Прогнать — ожидается FAIL**

Run: `make test-honest ARGS="tests/test_db_cross_space.py tests/test_db_migrate_roles.py -q -rs"`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.db.cross_space'`.

- [ ] **Step 3: Минимальная реализация**

```sql
-- 0039_cross_space_actions.sql
--
-- Журнал действий человека УК в пространстве партнёра (спека «Администрирование»).
-- Данные принадлежат владельцу пространства (D017): УК в них действует (D304),
-- и каждое такое действие оставляет строку «кто, что, когда, в чьём пространстве».
--
-- Пишется ТЕМ ЖЕ подключением, что и действие, до его коммита
-- (`src/db/cross_space.py: record`): откатилось действие — откатилась строка.
-- Журнал только дописывается: update и delete не выданы никому.
--
-- Раннер оборачивает файл в одну транзакцию сам — begin/commit здесь не нужны.

create table cross_space_actions (
    id bigint generated always as identity primary key,
    at timestamptz not null default now(),
    actor_web_user_id uuid not null references web_users (id),
    actor_tenant text not null references tenants (code) check (actor_tenant = 'HQ'),
    object_tenant text not null references tenants (code) check (object_tenant <> 'HQ'),
    action_code text not null check (action_code ~ '^[a-z]+\.[a-z_]+$'),
    object_ref text not null check (length(btrim(object_ref)) between 1 and 200)
);

create index cross_space_actions_object_idx on cross_space_actions (object_tenant, at desc);

grant select, insert on cross_space_actions to dodo_audit_app, dodo_audit_admin;
```

```python
# src/db/cross_space.py
"""Журнал действий человека УК в пространстве партнёра (спека «Администрирование»).

`record` пишет на ПЕРЕДАННОМ подключении и не коммитит: дверь действия зовёт
его до своего коммита, и строка журнала живёт ровно столько, сколько само
действие. Своего подключения здесь нет намеренно — второе подключение
закоммитило бы журнал отдельно от действия.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import psycopg

from src.domain.permissions import Actor, require_action
from src.domain.tenants import canonical_tenant

_INSERT_SQL = """
    insert into cross_space_actions
        (actor_web_user_id, actor_tenant, object_tenant, action_code, object_ref)
    values (%s, %s, %s, %s, %s)
"""


@dataclass(frozen=True)
class Entry:
    """Строка журнала: кто, из какого пространства, в чьём, что и над чем."""

    actor_web_user_id: str
    actor_tenant: str
    object_tenant: str
    action_code: str
    object_ref: str


def entry_for(actor: Actor, *, object_tenant: str, action: str, object_ref: str) -> Entry | None:
    """Строка журнала для действия — или `None`, если пространство своё.

    Пишет её вызывающий — и только если действие СОСТОЯЛОСЬ (строка сменилась):
    холостой вызов следа «кто, что, когда» не оставляет.
    """
    require_action(action)
    кто = canonical_tenant(actor.tenant)
    чьё = canonical_tenant(object_tenant)
    if кто == чьё:
        return None
    if not actor.user_id:
        raise ValueError(
            "Действие в чужом пространстве без учётки: журналу некого записать. "
            "Так действует только человек УК с учёткой веба"
        )
    return Entry(actor.user_id, кто, чьё, action, object_ref)


def record(conn: psycopg.Connection[Any], entry: Entry | None) -> None:
    """Дописать строку журнала на подключении действия. `None` — писать нечего."""
    if entry is None:
        return
    with conn.cursor() as cur:
        cur.execute(
            _INSERT_SQL,
            (
                entry.actor_web_user_id,
                entry.actor_tenant,
                entry.object_tenant,
                entry.action_code,
                entry.object_ref,
            ),
        )
```

Отпечаток `0039` вписать в `ОТПЕЧАТКИ` той же командой, что в Task 3 Step 4 (имя файла `0039_cross_space_actions.sql`), со строкой-комментарием «Журнал действий УК у партнёра (блок 1). Заведена вместе с файлом.».

- [ ] **Step 4: Прогнать — ожидается PASS**

Run: `make test-honest ARGS="tests/test_db_cross_space.py tests/test_db_migrate_roles.py tests/test_db_migrations_frozen.py -q -rs"`
Expected: PASS, `SKIPPED` нет.

- [ ] **Step 5: Документация** — `docs/furca/blocks/db.md`, после блока ролей:

```
# журнал действий УК у партнёра (0039) — src/db/cross_space.py
#   entry_for(actor, *, object_tenant, action, object_ref) -> Entry | None (своё — None)
#   record(conn, entry): пишет на подключении ДВЕРИ ДЕЙСТВИЯ до её коммита и только
#   если действие состоялось (холостое — без строки); своего
#   подключения нет — иначе журнал коммитился бы отдельно от действия
#   cross_space_actions: actor_tenant = 'HQ', object_tenant <> 'HQ'; только select+insert
```

- [ ] **Step 6: Коммит и пуш**

```bash
git add src/db/migrations/0039_cross_space_actions.sql src/db/cross_space.py tests/test_db_cross_space.py tests/test_db_migrations_frozen.py tests/test_db_migrate_roles.py docs/furca/blocks/db.md
git commit -m "feat: журнал действий УК в пространстве партнёра

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

### Task 5: Проверка помнит учётку, которая её занесла (D311)

Проверка создаётся в боте (`src/bot/routers/start.py` → `domain.start_inspection`, состояние чата), а в базу ложится сливом (`src/db/push.py: push_inspection`, `_INSERT_INSPECTION_SQL`). Автор едет тем же путём: поле состояния → колонка `inspections.created_by`. Здесь — домен и база; бот передаёт учётку в Task 13.

**Files:**
- Create: `src/db/migrations/0040_inspection_author.sql`
- Modify: `src/domain/models.py` — `Inspection` (~строки 174–194): поле `author_user_id` после `auditor`
- Modify: `src/domain/state.py` — `start_inspection` (~524–540, параметр; блок ~605–615, ключ `author_user_id`), чтение состояния (~486–508)
- Modify: `src/db/push.py` — `_INSERT_INSPECTION_SQL` (~57–70), параметры вставки (~368–392)
- Modify: `src/db/models.py` — `InspectionRow` (~после `accepted_by`): поле `created_by`
- Modify: `src/db/queries.py` — три шаблона (строки 85, 117, 158: `i.created_by` сразу после `i.accepted_by`), `_row_to_inspection` (~307)
- Modify: `tests/db_harness.py` — `слить_проверку` (~267): параметр `author_user_id`
- Modify: `tests/test_db_migrations_frozen.py` (строка `"0040_inspection_author.sql"`)
- Create: `tests/test_db_inspection_author.py`
- Modify: `docs/furca/blocks/db.md` (после блока журнала)

**Interfaces:**
- Consumes: `db_harness.слить_проверку`, `db_harness.точка_пространства`, `src.db.queries.get_inspection(inspection_id, *, reach, include_retracted=False, include_on_review=False)`, `src.db.reach.reach_of(tenant)`, `src.db.fingerprint.compute_fingerprint`.
- Produces:
  - Схема: `inspections.created_by uuid null references web_users(id)`.
  - `Inspection.author_user_id: str = ""` (пусто — автора нет).
  - `start_inspection(..., author_user_id: str = "") -> Inspection`.
  - `InspectionRow.created_by: str = ""` (пусто — автора нет).
  - `слить_проверку(*, unit, tenant, chat_id=None, text=..., date=None, accept=True, author_user_id="") -> str`.

- [ ] **Step 1: Написать падающий тест**

```python
# tests/test_db_inspection_author.py
"""Проверка помнит учётку, которая её занесла (D311): «свои» решаются по ней."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import requires_db
from db_harness import слить_проверку

psycopg = pytest.importorskip("psycopg")

from src.db.queries import get_inspection  # noqa: E402
from src.db.reach import reach_of  # noqa: E402
from src.db.web_access import password_hash  # noqa: E402
from src.domain import get_state, start_inspection  # noqa: E402

pytestmark = requires_db
ТОЧКА = "Белград-автор"


def _учётка(pg_dsn: str) -> str:
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "insert into web_users (tenant_code, login, password_hash, role) "
            "values ('HQ', 'hq-author', %s, 'hq_staff') returning id",
            (password_hash("пароль-автора-1"),),
        )
        строка = cur.fetchone()
    assert строка is not None
    return str(строка[0])


def test_автор_едет_из_состояния_в_базу(domain_env: Path, db_env: str, pg_dsn: str) -> None:
    кто = _учётка(pg_dsn)
    ident = слить_проверку(unit=ТОЧКА, tenant="HQ", author_user_id=кто, accept=False)
    карточка = get_inspection(ident, reach=reach_of("HQ"), include_on_review=True)
    assert карточка is not None and карточка.inspection.created_by == кто


def test_проверка_без_учётки_ложится_без_автора(domain_env: Path, db_env: str, pg_dsn: str) -> None:
    ident = слить_проверку(unit=ТОЧКА, tenant="HQ", accept=False)
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute("select created_by from inspections where id = %s", (ident,))
        assert cur.fetchone() == (None,)
    карточка = get_inspection(ident, reach=reach_of("HQ"), include_on_review=True)
    assert карточка is not None and карточка.inspection.created_by == ""


def test_автор_сохраняется_в_состоянии_чата(domain_env: Path) -> None:
    start_inspection(
        9100, unit=ТОЧКА, kind="planned", report_lang="ru", tenant="HQ", author_user_id="u-77"
    )
    состояние = get_state(9100)
    assert состояние is not None and состояние.author_user_id == "u-77"


def test_автор_не_входит_в_отпечаток(domain_env: Path, db_env: str, pg_dsn: str) -> None:
    кто = _учётка(pg_dsn)
    первая = слить_проверку(unit=ТОЧКА, tenant="HQ", chat_id=9101, accept=False)
    вторая = слить_проверку(unit=ТОЧКА, tenant="HQ", chat_id=9101, author_user_id=кто, accept=False)
    assert первая == вторая
```

- [ ] **Step 2: Прогнать — ожидается FAIL**

Run: `make test-honest ARGS="tests/test_db_inspection_author.py -q -rs"`
Expected: FAIL — `TypeError: слить_проверку() got an unexpected keyword argument 'author_user_id'`.

- [ ] **Step 3: Минимальная реализация**

```sql
-- 0040_inspection_author.sql
--
-- Учётка, которая занесла проверку (D311): сотрудник правит только «свои»
-- проверки — те, что занесла его учётка. Пишется сливом из состояния проверки,
-- куда бот кладёт учётку привязки при старте.
--
-- Колонка допускает пустоту: у проверок, залитых до неё, и у начатых без
-- привязки бота к учётке автора нет, и под «свои» они не попадают никогда —
-- их правит админ. В отпечаток слива автор не входит: повторный слив той же
-- проверки остаётся той же строкой.
--
-- Раннер оборачивает файл в одну транзакцию сам — begin/commit здесь не нужны.

alter table inspections add column created_by uuid references web_users (id);

comment on column inspections.created_by is
    'Учётка веба, занёсшая проверку (D311): по ней решается охват «свои». '
    'null — автор неизвестен (до 0040 или без привязки бота): только для «все».';
```

Права не меняются: у `dodo_audit_app` уже есть `insert` на `inspections` целиком (`APP_TABLE_GRANTS`), а чтение администратора — табличное `select`. Отпечаток `0040` вписать в `ОТПЕЧАТКИ` командой Task 3 Step 4 (имя `0040_inspection_author.sql`, комментарий «Автор проверки (D311). Заведена вместе с файлом.»).

`src/domain/models.py`, `Inspection`, после `auditor: str = ""`:

```python
    #: Учётка веба, которая занесла проверку (D311). Пусто — автора нет
    #: (бот без привязки): под «свои» такая проверка не попадает.
    author_user_id: str = ""
```

`src/domain/state.py`: в `start_inspection` параметр `author_user_id: str = ""` после `checklist_code`; в словарь `block` — `"author_user_id": author_user_id.strip(),`; в чтении состояния — `author_user_id=str(block.get("author_user_id") or ""),` после `auditor=...`.

`src/db/push.py`: в `_INSERT_INSPECTION_SQL` колонка `created_by` перед `status` и значение `%(created_by)s` перед `'draft'`; в параметры вставки — `"created_by": inspection.author_user_id or None,` (пустая строка — `null`, а не ошибка формата `uuid`). `src/db/fingerprint.py` не трогается.

`src/db/models.py`, `InspectionRow`, после `accepted_by`:

```python
    #: Учётка, занёсшая проверку (D311, `0040`). Пусто — автор неизвестен.
    created_by: str = ""
```

`src/db/queries.py`: в трёх шаблонах `i.status, i.accepted_at, i.accepted_by` → `i.status, i.accepted_at, i.accepted_by, i.created_by` (в шаблоне карточки запятая перед `i.deductions` остаётся; разбор карточки берёт `deductions` по имени колонки, `_detail_parts`, и сдвиг его не задевает). В `_row_to_inspection` после `accepted_by=...`:

```python
        # Автор (D311, `0040`) — последним, по той же причине, что код чек-листа.
        created_by=str(row[22] or ""),
```

`tests/db_harness.py`, `слить_проверку`: параметр `author_user_id: str = ""`, вызов `start_inspection(чат, unit=unit, kind="planned", report_lang="ru", tenant=tenant, date=date, author_user_id=author_user_id)`.

- [ ] **Step 4: Прогнать — ожидается PASS; соседи слива и чтения**

Run: `make test-honest ARGS="tests/test_db_inspection_author.py tests/test_db_push.py tests/test_db_reads_tenant.py tests/test_db_migrations_frozen.py tests/test_domain_state.py -q -rs"`
Expected: PASS, `SKIPPED` нет. Красный в разборе строк (`row[...]`) — регрессия сдвига, разбирать.

- [ ] **Step 5: Документация** — `docs/furca/blocks/db.md`, после блока журнала:

```
# автор проверки (0040, D311): inspections.created_by → web_users(id), null — неизвестен
#   пишется сливом из состояния (Inspection.author_user_id, ставит бот при старте по
#   привязке); в отпечаток не входит; InspectionRow.created_by ("" — неизвестен)
```

- [ ] **Step 6: Коммит и пуш**

```bash
git add src/db/migrations/0040_inspection_author.sql src/domain/models.py src/domain/state.py src/db/push.py src/db/models.py src/db/queries.py tests/db_harness.py tests/test_db_migrations_frozen.py tests/test_db_inspection_author.py docs/furca/blocks/db.md
git commit -m "feat: проверка помнит учётку, которая её занесла (D311)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

### Task 6: Двери учёток знают роль и права

**Files:**
- Create: `src/db/roles.py`
- Modify: `src/db/web_access.py` — `Account` (~236–248), SQL `_SELECT_USER_SQL` (~111), `_SELECT_USER_BY_EMAIL_SQL` (~196), `_RESOLVE_SESSION_SQL` (~211), `_checked_role` (мост Task 3), `create_account` (~476), `reassign_role` (~554), `find_by_email` (~679), `authenticate` (~706), `resolve_session` (~748)
- Modify: `tools/web_user.py` (~строка 183: `choices=(*ROLES, *LEGACY_ROLES)` из Task 3 снимается — роли решает таблица `roles`)
- Create: `tests/test_db_roles_door.py`
- Modify: `docs/furca/blocks/db.md` (после блока ролей Task 3)

**Interfaces:**
- Consumes: `canonical_role`, `Grants` (Tasks 1–2); таблицы `0038`; мост ролей Task 3 (`ROLES`, `LEGACY_ROLES`, `_checked_role`); `src.db.reading.reading(зачем)`.
- Produces:
  - `src/db/roles.py`: `Role(code: str, scope: str, name_ru: str, name_en: str, grants: Grants)`; `list_roles() -> tuple[Role, ...]`; `grants_of(role_code: str) -> Grants`; `grants_column(role_expr: str) -> str` — подзапрос «права роли одной колонкой jsonb» для SQL опознания (веб — здесь, бот — Task 13); `grants_from_row(value: object) -> Grants` — разбор этой колонки.
  - `Account(id: str, login: str, tenant: str, role: str = "", grants: Grants = <пусто>, role_name_ru: str = "", role_name_en: str = "")`.
  - `web_access.ROLES`, `web_access.LEGACY_ROLES` остаются (мост Task 3) до Task 11; `_checked_role(role, tenant)` больше не сверяет с `ROLES` — заведена ли роль, решает внешний ключ.
  - `create_account(...)`, `reassign_role(...)` принимают новый код или старый псевдоним; роль чужого охвата → `AccessError("Роль «…» не для пространства «…»")`, незаведённая → `AccessError("Роль «…» не заведена")`.

- [ ] **Step 1: Написать падающий тест**

```python
# tests/test_db_roles_door.py
"""Права роли приезжают вместе с опознанием — и действуют со следующей сверки."""

from __future__ import annotations

import pytest
from conftest import requires_db
from db_harness import завести_пространства

psycopg = pytest.importorskip("psycopg")

from src.db.errors import AccessError  # noqa: E402
from src.db.roles import grants_of, list_roles  # noqa: E402
from src.db.web_access import (  # noqa: E402
    authenticate,
    create_account,
    open_session,
    reassign_role,
    resolve_session,
)
from src.domain.permissions import DEFAULT_MATRIX  # noqa: E402

pytestmark = requires_db
ПАРОЛЬ = "очень-длинный-пароль"


@pytest.fixture
def обе_роли(pg_dsn: str, db_env: str, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("DATABASE_ADMIN_URL", pg_dsn)
    завести_пространства(pg_dsn, "GE")
    return pg_dsn


def test_старая_роль_переводится_на_заведении(обе_роли: str) -> None:
    учётка = create_account("ge-boss", tenant="GE", password=ПАРОЛЬ, role="admin")
    assert учётка.role == "country_admin"


def test_вход_приносит_права_с_охватом_и_имя_роли(обе_роли: str) -> None:
    create_account("hq-staff", tenant="HQ", password=ПАРОЛЬ, role="hq_staff")
    вошёл = authenticate("hq-staff", ПАРОЛЬ)
    assert вошёл is not None
    assert dict(вошёл.grants) == dict(DEFAULT_MATRIX["hq_staff"])
    assert вошёл.grants["inspection.retract"] == "own"
    assert (вошёл.role_name_ru, вошёл.role_name_en) == ("Сотрудник УК", "HQ staff")


def test_снятое_право_действует_со_следующей_сверки_сессии(обе_роли: str) -> None:
    учётка = create_account("hq-boss", tenant="HQ", password=ПАРОЛЬ, role="hq_admin")
    сессия = open_session(учётка)
    with psycopg.connect(обе_роли) as conn:
        conn.execute(
            "delete from role_permissions where role_code = 'hq_admin' "
            "and action_code = 'inspection.retract'"
        )
    после = resolve_session(сессия.token)
    assert после is not None and "inspection.retract" not in после.grants


def test_роль_чужого_охвата_названа(обе_роли: str) -> None:
    with pytest.raises(AccessError, match="не для пространства «GE»"):
        create_account("ge-intruder", tenant="GE", password=ПАРОЛЬ, role="hq_admin")


def test_незаведённая_роль_названа(обе_роли: str) -> None:
    create_account("ge-worker", tenant="GE", password=ПАРОЛЬ)
    with pytest.raises(AccessError, match="«ghost» не заведена"):
        reassign_role("ge-worker", tenant="GE", role="ghost")


def test_перечень_ролей_и_права_роли(обе_роли: str) -> None:
    assert {р.code: р.scope for р in list_roles()} == {
        "hq_admin": "hq", "hq_staff": "hq", "country_admin": "country", "country_staff": "country",
    }
    assert dict(grants_of("country_staff")) == dict(DEFAULT_MATRIX["country_staff"])
    assert dict(grants_of("ghost")) == {}
```

- [ ] **Step 2: Прогнать — ожидается FAIL**

Run: `make test-honest ARGS="tests/test_db_roles_door.py -q -rs"`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.db.roles'`.

- [ ] **Step 3: Минимальная реализация**

```python
# src/db/roles.py
"""Роли и их права — чтение ролью приложения (спека «Администрирование», `0038`).

Здесь же — единственный подзапрос «права роли одной колонкой» и его разбор: их
зовут SQL опознания веба (`web_access`) и бота (`bot_links`, Task 13). Три копии
подзапроса разошлись бы на первой правке схемы прав.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from src.domain.permissions import Grants

from .reading import reading


def grants_column(role_expr: str) -> str:
    """Подзапрос «права роли `role_expr` одной колонкой jsonb» (код действия → охват).

    `role_expr` — выражение SQL из кода модуля (`"u.role"`, `"r.code"`), не ввод
    человека: в текст запроса он попадает как есть.
    """
    return (
        "(select coalesce(jsonb_object_agg(p.action_code, p.reach), '{}'::jsonb) "
        f"from role_permissions p where p.role_code = {role_expr})"  # noqa: S608
    )


def grants_from_row(value: object) -> Grants:
    """Колонка `grants_column` → права роли. Не словарь — ошибка схемы, а не «прав нет»."""
    if not isinstance(value, Mapping):
        raise TypeError(f"Права роли ожидались объектом jsonb, пришло {type(value).__name__}")
    return MappingProxyType({str(код): str(охват) for код, охват in value.items()})


_LIST_SQL = f"""
    select r.code, r.scope, r.name_ru, r.name_en, {grants_column("r.code")}
      from roles r
     order by r.scope, r.code
"""  # noqa: S608 — подзапрос собран из константы модуля

_GRANTS_SQL = "select action_code, reach from role_permissions where role_code = %s"


@dataclass(frozen=True)
class Role:
    """Роль так, как её показывают и проверяют: код, охват, подписи, права."""

    code: str
    scope: str
    name_ru: str
    name_en: str
    grants: Grants


def list_roles() -> tuple[Role, ...]:
    """Все роли с правами — для выбора роли на экране людей."""
    with reading("роли") as conn, conn.cursor() as cur:
        cur.execute(_LIST_SQL)
        return tuple(
            Role(str(r[0]), str(r[1]), str(r[2]), str(r[3]), grants_from_row(r[4]))
            for r in cur.fetchall()
        )


def grants_of(role_code: str) -> Grants:
    """Права роли. Незаведённая роль — пусто: закрыто по умолчанию."""
    with reading("права роли") as conn, conn.cursor() as cur:
        cur.execute(_GRANTS_SQL, (role_code,))
        return MappingProxyType({str(код): str(охват) for код, охват in cur.fetchall()})
```

`src/db/web_access.py` — `Account` заменить (константы ролей и `ROLES`/`LEGACY_ROLES` — из моста Task 3, не трогать):

```python
from types import MappingProxyType

from src.domain.permissions import Grants

from .roles import grants_column, grants_from_row

#: Ограничение охвата роли в схеме (`0038`): его имя различает «роль чужого
#: охвата» и прочие отказы проверки.
_ROLE_SCOPE_CONSTRAINT = "web_users_role_scope"
_NO_GRANTS: Grants = MappingProxyType({})


@dataclass(frozen=True)
class Account:
    """Учётка так, как её видят страницы: кто вошёл, его роль и права роли."""

    id: str
    login: str
    tenant: str
    #: Код роли (`roles.code`). Приезжает вместе с опознанием одним запросом.
    role: str = ""
    #: Права роли на момент запроса: код действия → охват (`own`/`all`).
    grants: Grants = _NO_GRANTS
    role_name_ru: str = ""
    role_name_en: str = ""
```

SQL опознания — у трёх запросов одинаковые первые семь колонок, пароль — последним у `_SELECT_USER_SQL`:

```python
_GRANTS_OF_USER = grants_column("u.role")

_SELECT_USER_SQL = f"""
    select u.id, u.login, u.tenant_code, u.role, r.name_ru, r.name_en, {_GRANTS_OF_USER},
           u.password_hash
      from web_users u join roles r on r.code = u.role
     where u.login = %s and u.disabled_at is null
"""  # noqa: S608 — подзапрос собран из константы модуля

_SELECT_USER_BY_EMAIL_SQL = f"""
    select u.id, u.login, u.tenant_code, u.role, r.name_ru, r.name_en, {_GRANTS_OF_USER}
      from web_users u join roles r on r.code = u.role
     where u.email = %s and u.disabled_at is null
"""  # noqa: S608 — подзапрос собран из константы модуля

_RESOLVE_SESSION_SQL = f"""
    select u.id, u.login, u.tenant_code, u.role, r.name_ru, r.name_en, {_GRANTS_OF_USER}
      from web_sessions s
      join web_users u on u.id = s.user_id
      join roles r on r.code = u.role
     where s.fingerprint = %s
       and s.closed_at is null
       and s.expires_at > now()
       and u.disabled_at is null
"""  # noqa: S608 — подзапрос собран из константы модуля


def _account(row: tuple[Any, ...]) -> Account:
    """Строка опознания → учётка. Первые семь колонок одинаковы у трёх запросов."""
    return Account(
        id=str(row[0]),
        login=str(row[1]),
        tenant=str(row[2]),
        role=str(row[3]),
        role_name_ru=str(row[4]),
        role_name_en=str(row[5]),
        grants=grants_from_row(row[6]),
    )


def _checked_role(role: str, tenant: str) -> str:
    """Код роли: старое имя переводится по пространству. Заведена ли — решает схема (FK)."""
    try:
        return canonical_role(role, tenant)
    except ValueError as exc:
        raise AccessError("Роль не задана") from exc


def _role_refusal(exc: psycopg.Error, *, role: str, tenant: str) -> AccessError | None:
    """Отказ схемы про роль — словами; прочие отказы — `None` (решает вызывающий)."""
    if isinstance(exc, psycopg.errors.ForeignKeyViolation):
        return AccessError(f"Роль «{role}» не заведена")
    if isinstance(exc, psycopg.errors.CheckViolation) and (
        exc.diag.constraint_name == _ROLE_SCOPE_CONSTRAINT
    ):
        return AccessError(f"Роль «{role}» не для пространства «{tenant}»")
    return None
```

`create_account`: в `try` вокруг `cur.execute(_INSERT_USER_SQL, ...)` после ветки `UniqueViolation` добавить:

```python
        except (psycopg.errors.ForeignKeyViolation, psycopg.errors.CheckViolation) as exc:
            отказ = _role_refusal(exc, role=роль, tenant=tenant)
            if отказ is None:
                raise
            raise отказ from exc
```

`reassign_role`: вызов `cur.execute(_SET_ROLE_SQL, ...)` обернуть тем же `try/except`. `authenticate`, `find_by_email`, `resolve_session`: возвращать `_account(row)` (у `authenticate` хеш — `row[7]`: `password_matches(password, str(row[7]))`).

`tools/web_user.py` ~183: `роль.add_argument("role", help="код роли (hq_admin, hq_staff, country_admin, country_staff) или старое admin/auditor")` — без `choices`; импорт `ROLES`, `LEGACY_ROLES` убрать, если больше не используются.

- [ ] **Step 4: Прогнать — ожидается PASS; соседи учёток и веб**

Run: `make test-honest ARGS="tests/test_db_roles_door.py tests/test_db_web_access.py tests/test_db_web_own_password.py tests/test_db_web_unlock.py tests/test_db_bot_links.py tests/test_db_no_implicit_spaces.py tests/test_db_password_bounds.py -q -rs"`
Expected: PASS, `SKIPPED` нет — ожидания ролей уже переведены в Task 3; `test_незаведённая_роль_отвергается_а_не_ложится_в_базу` проходит отказом внешнего ключа (`_role_refusal`). Любой красный — регрессия.
Run: `.venv/bin/pytest tests/test_web_*.py -q` → PASS (мост ролей Task 3 держит веб; двойник учётки ещё без прав).

- [ ] **Step 5: Документация** — `docs/furca/blocks/db.md`, после блока ролей Task 3:

```
# двери ролей — src/db/roles.py (роль приложения): list_roles() -> tuple[Role, ...],
#   grants_of(role_code) -> Grants (незаведённая — пусто); grants_column(role_expr) —
#   единственный подзапрос «права роли колонкой jsonb», grants_from_row — его разбор
# опознание (authenticate, find_by_email, resolve_session) отдаёт Account с role,
#   role_name_ru/en и grants — одним запросом на каждый запрос страницы
```

- [ ] **Step 6: Коммит и пуш**

```bash
git add src/db/roles.py src/db/web_access.py tools/web_user.py tests/test_db_roles_door.py docs/furca/blocks/db.md
git commit -m "feat: роль и права роли приезжают вместе с опознанием

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

### Task 7: Заслон прав веба

**Files:**
- Create: `src/web/guard.py`
- Modify: `src/web/auth.py` — `current_actor()` после `current_reach()` (~строка 175)
- Modify: `src/web/app.py` — `create_app`: `guard.install(app)` сразу после `_install_hq_gate(app)` (~строка 123)
- Modify: `tests/web_harness.py` — константа `УЧЁТКА` рядом с `СВОЙ` (~строка 43), `Учётка.__init__` (~строки 47–53)
- Create: `tests/test_web_guard.py`

**Interfaces:**
- Consumes: `can`, `Actor`, `INSPECTION_OBJECT_ACTIONS`, `AUTHOR_NOT_GIVEN`, `AuthorNotGiven`, `require_action`, `canonical_role`, `DEFAULT_MATRIX` (Tasks 1–2); `Account.grants` (Task 6); `auth.current_account`, `auth.current_tenant`, `auth.OPEN_ENDPOINTS`.
- Produces:
  - `auth.current_actor() -> Actor`.
  - `guard.action(*codes: str, object_in_route: bool = False) -> Callable[[F], F]` — действие над проверкой требует `object_in_route=True`.
  - `guard.permit(code: str, object_tenant: str, *, object_author: str | None | AuthorNotGiven = AUTHOR_NOT_GIVEN) -> tuple[str, int] | None` — `None` можно, иначе страница 403.
  - `guard.mark_own() -> None`.
  - `guard.forbidden() -> tuple[str, int]` — страница отказа 403; единственное место её сборки для заслона прав (Tasks 10, 11 зовут её, а не `render_template` заново).
  - `guard.install(app: Flask) -> None`.
  - `guard.uncovered(app: Flask) -> list[str]`.
  - `guard.ACTIONS_ATTR`, `guard.EXEMPT_ENDPOINTS: Mapping[str, str]`, `guard.WRITING_GETS: frozenset[str]`.
  - `web_harness.УЧЁТКА: str` — id учётки двойника (автор «своей» проверки в тестах Tasks 10–11).

- [ ] **Step 1: Написать падающий тест**

```python
# tests/test_web_guard.py
"""Заслон прав веба: пишущий маршрут объявляет код и спрашивает can."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from flask import Flask
from flask.testing import FlaskClient
from web_harness import СВОЙ, войти, подменить_двери, собрать

from src.web import guard


def _стенд(monkeypatch: pytest.MonkeyPatch, *, tenant: str, role: str) -> Flask:
    подменить_двери(monkeypatch, tenant=tenant, role=role)
    app = собрать(tenant="HQ")
    # `собрать` ставит TESTING=True, и Flask пробрасывает исключение вида и
    # `after_request` в тестовый клиент. Здесь проверяется ответ продукта — 500,
    # каким его увидит человек, — поэтому проброс выключен.
    app.config["PROPAGATE_EXCEPTIONS"] = False

    @app.post("/_t/own")
    @guard.action("checklist.edit")
    def _own() -> str:
        return "ok"

    @app.post("/_t/object/<tenant>/<author>")
    @guard.action("inspection.retract", object_in_route=True)
    def _object(tenant: str, author: str) -> str | tuple[str, int]:
        автор = None if author == "none" else author
        отказ = guard.permit("inspection.retract", tenant, object_author=автор)
        return отказ if отказ is not None else "ok"

    @app.post("/_t/no-author")
    @guard.action("inspection.retract", object_in_route=True)
    def _no_author() -> str | tuple[str, int]:
        отказ = guard.permit("inspection.retract", "HQ")
        return отказ if отказ is not None else "ok"

    @app.post("/_t/forgot")
    @guard.action("inspection.retract", object_in_route=True)
    def _forgot() -> str:
        return "записал без границы"

    @app.post("/_t/bare")
    def _bare() -> str:
        return "без кода"

    return app


@pytest.fixture
def вошедший(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> Iterator[FlaskClient]:
    tenant, role = request.param
    with _стенд(monkeypatch, tenant=tenant, role=role).test_client() as client:
        assert войти(client).status_code == 302
        yield client


def _post(client: FlaskClient, путь: str) -> int:
    return client.post(путь, headers={"Origin": СВОЙ}).status_code


МОЙ = "22222222-2222-2222-2222-222222222222"


@pytest.mark.parametrize("вошедший", [("GE", "auditor")], indirect=True)
def test_сотрудник_страны_не_правит_методику(вошедший: FlaskClient) -> None:
    assert _post(вошедший, "/_t/own") == 403


@pytest.mark.parametrize("вошедший", [("GE", "admin")], indirect=True)
def test_админ_страны_правит_свою_методику(вошедший: FlaskClient) -> None:
    assert _post(вошедший, "/_t/own") == 200


@pytest.mark.parametrize("вошедший", [("HQ", "admin")], indirect=True)
def test_уК_действует_над_объектом_партнёра(вошедший: FlaskClient) -> None:
    assert _post(вошедший, "/_t/object/GE/none") == 200


@pytest.mark.parametrize("вошедший", [("GE", "admin")], indirect=True)
def test_страна_не_действует_над_объектом_уК(вошедший: FlaskClient) -> None:
    assert _post(вошедший, f"/_t/object/HQ/{МОЙ}") == 403


@pytest.mark.parametrize("вошедший", [("HQ", "auditor")], indirect=True)
def test_сотрудник_уК_действует_только_над_своим(вошедший: FlaskClient) -> None:
    assert _post(вошедший, f"/_t/object/HQ/{МОЙ}") == 200
    assert _post(вошедший, "/_t/object/HQ/u-other") == 403
    assert _post(вошедший, "/_t/object/HQ/none") == 403


@pytest.mark.parametrize("вошедший", [("HQ", "admin")], indirect=True)
def test_маршрут_с_объектом_без_permit_падает_500(вошедший: FlaskClient) -> None:
    assert _post(вошедший, "/_t/forgot") == 500


@pytest.mark.parametrize("вошедший", [("HQ", "admin")], indirect=True)
def test_действие_над_проверкой_без_автора_падает_500(вошедший: FlaskClient) -> None:
    assert _post(вошедший, "/_t/no-author") == 500


def test_незнакомый_код_падает_на_объявлении() -> None:
    with pytest.raises(ValueError, match="inspection.delete"):
        guard.action("inspection.delete")


def test_действие_над_проверкой_требует_объекта_в_маршруте() -> None:
    with pytest.raises(ValueError, match="object_in_route"):
        guard.action("inspection.move")


def test_полнота_называет_маршрут_без_кода(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _стенд(monkeypatch, tenant="HQ", role="admin")
    assert "_bare (/_t/bare)" in guard.uncovered(app)
    assert not any(строка.startswith("_own ") for строка in guard.uncovered(app))
```

- [ ] **Step 2: Прогнать — ожидается FAIL**

Run: `.venv/bin/pytest tests/test_web_guard.py -q`
Expected: FAIL — `ImportError: cannot import name 'guard' from 'src.web'`.

- [ ] **Step 3: Минимальная реализация**

`tests/web_harness.py`, `Учётка.__init__` — права роли из матрицы по умолчанию, как их отдала бы база:

```python
from src.domain.permissions import DEFAULT_MATRIX, canonical_role

#: Учётка двойника — её же тесты ставят автором проверки (D311).
УЧЁТКА = "22222222-2222-2222-2222-222222222222"

    def __init__(self, login: str = ЛОГИН, tenant: str = "default", role: str = "auditor") -> None:
        self.id = УЧЁТКА
        self.login = login
        self.tenant = tenant
        # Роль по умолчанию — САМАЯ УЗКАЯ, как и в базе. Старое имя роли
        # переводится по пространству так же, как его переводит миграция `0038`.
        self.role = canonical_role(role, tenant)
        self.grants = dict(DEFAULT_MATRIX.get(self.role, {}))
        self.role_name_ru = self.role
        self.role_name_en = self.role
```

`src/web/auth.py` (импорт `from src.domain.permissions import Actor`):

```python
def current_actor() -> Actor:
    """Вошедший как субъект прав: пространство, роль и права роли этого запроса."""
    account = current_account()
    if account is None:
        raise RuntimeError("current_actor() вызван без вошедшего: маршрут прошёл мимо заслона")
    return Actor(
        tenant=current_tenant(),
        role=account.role,
        grants=account.grants,
        user_id=account.id,
    )
```

```python
# src/web/guard.py
"""Заслон прав веба (спека «Администрирование»): каждый пишущий маршрут — через `can`.

Маршрут объявляет код действия декоратором `action`. Маршрут своего
пространства проверяется целиком до входа (`before_request`). Маршрут, чей
объект может лежать в чужом пространстве или принадлежать другому автору
(`object_in_route=True`), сам зовёт `permit(код, пространство_объекта,
object_author=...)` — пространство и автор берутся из объекта, а не из формы.
Забыл позвать — пишущий запрос падает 500 (`after_request`): запись без границы
громче, чем тихая.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Any, TypeVar

from flask import Flask, current_app, g, render_template, request
from werkzeug.wrappers import Response

from src.domain.permissions import (
    AUTHOR_NOT_GIVEN,
    INSPECTION_OBJECT_ACTIONS,
    AuthorNotGiven,
    can,
    require_action,
)

from . import auth

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

ACTIONS_ATTR = "required_actions"
OBJECT_IN_ROUTE_ATTR = "object_in_route"
WRITING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

#: GET, который пишет: возврат от Google кладёт письмо и отправляет предписание.
WRITING_GETS = frozenset({"google_mail_callback"})

#: Пишущие маршруты без кода каталога — со своей причиной.
EXEMPT_ENDPOINTS: Mapping[str, str] = {
    "logout": "выход закрывает свою сессию",
    "own_password": "свой пароль — у себя, без доступа к остальному (спека)",
    "bot_link": "ссылка привязки — всегда своей учётке (D286)",
}

_PERMITTED = "action_permitted"


def action(*codes: str, object_in_route: bool = False) -> Callable[[F], F]:
    """Объявить код действия маршрута. Ошибка объявления — при сборке приложения."""
    if not codes:
        raise ValueError("Маршрут без кода действия: заслону нечего спрашивать")
    for код in codes:
        require_action(код)
    if not object_in_route and (len(codes) > 1 or codes[0] in INSPECTION_OBJECT_ACTIONS):
        raise ValueError(
            "Несколько кодов или действие над проверкой — объект решает маршрут: "
            "object_in_route=True"
        )

    def mark(view: F) -> F:
        setattr(view, ACTIONS_ATTR, codes)
        setattr(view, OBJECT_IN_ROUTE_ATTR, object_in_route)
        return view

    return mark


def _view() -> Any:
    return current_app.view_functions.get(request.endpoint or "")


def forbidden() -> tuple[str, int]:
    """Страница отказа 403 — одна на весь заслон прав."""
    return render_template("users/forbidden.html"), 403


def permit(
    code: str,
    object_tenant: str,
    *,
    object_author: str | None | AuthorNotGiven = AUTHOR_NOT_GIVEN,
) -> tuple[str, int] | None:
    """Спросить `can` о вошедшем. `None` — можно; иначе страница отказа 403."""
    объявлено = getattr(_view(), ACTIONS_ATTR, ())
    if code not in объявлено:
        raise RuntimeError(
            f"Маршрут {request.endpoint} спрашивает «{code}», а объявил {объявлено}"
        )
    решение = can(auth.current_actor(), code, object_tenant, object_author=object_author)
    setattr(g, _PERMITTED, True)
    if решение.allowed:
        return None
    logger.info(
        "права: отказ %s %s над %s (%s)", request.endpoint, code, object_tenant, решение.rule
    )
    return forbidden()


def mark_own() -> None:
    """Маршрут с объектом действует над своим (своя привязка): граница не нужна."""
    setattr(g, _PERMITTED, True)


def install(app: Flask) -> None:
    """Повесить заслон. Ставится ПОСЛЕ заслона входа: без вошедшего сюда не доходят."""

    @app.before_request
    def _права() -> tuple[str, int] | None:
        if request.endpoint in auth.OPEN_ENDPOINTS or auth.current_account() is None:
            return None
        view = app.view_functions.get(request.endpoint or "")
        коды = getattr(view, ACTIONS_ATTR, ())
        if not коды or getattr(view, OBJECT_IN_ROUTE_ATTR, False):
            return None
        return permit(коды[0], auth.current_tenant())

    @app.after_request
    def _спросил_ли(response: Response) -> Response:
        view = app.view_functions.get(request.endpoint or "")
        if request.method not in WRITING_METHODS:
            return response
        if not getattr(view, OBJECT_IN_ROUTE_ATTR, False):
            return response
        if response.status_code >= 400 or getattr(g, _PERMITTED, False):
            return response
        raise RuntimeError(
            f"Маршрут {request.endpoint} объявил объект и не спросил can: "
            f"запись прошла без границы"
        )


def uncovered(app: Flask) -> list[str]:
    """Пишущие маршруты без кода каталога и без причины-исключения — `эндпоинт (путь)`."""
    непокрытые: list[str] = []
    for rule in app.url_map.iter_rules():
        if rule.endpoint in auth.OPEN_ENDPOINTS or rule.endpoint in EXEMPT_ENDPOINTS:
            continue
        пишет = bool((rule.methods or set()) & WRITING_METHODS) or rule.endpoint in WRITING_GETS
        if not пишет:
            continue
        if not getattr(app.view_functions[rule.endpoint], ACTIONS_ATTR, ()):
            непокрытые.append(f"{rule.endpoint} ({rule.rule})")
    return sorted(непокрытые)
```

В `src/web/app.py` (`create_app`): `from . import guard` и строка `guard.install(app)` после `_install_hq_gate(app)`.

- [ ] **Step 4: Прогнать — ожидается PASS; прогнать весь веб**

Run: `.venv/bin/pytest tests/test_web_guard.py -q` → PASS.
Run: `.venv/bin/pytest tests/test_web_*.py -q`
Expected: зелёное — ни один настоящий маршрут ещё не объявил код, заслон их не трогает; двойник учётки теперь отдаёт коды ролей (`hq_admin`, …), и их понимает мост ролей Task 3 (`_is_admin`, `_is_hq_admin`, подписи `nav.role.<код>`, `users.role.<код>`). Красное — разобрать, это регрессия от двойника.

- [ ] **Step 5: Коммит и пуш**

```bash
git add src/web/guard.py src/web/auth.py src/web/app.py tests/web_harness.py tests/test_web_guard.py
git commit -m "feat: заслон прав веба — код действия на маршруте и can

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

### Task 8: Веб — маршруты своего пространства через `can`; чек-листы страны (D311)

Маршруты, которые пишут только в пространство вошедшего (двери берут `tenant=auth.current_tenant()` или держат страну триггером базы). Объект всегда своего пространства, поэтому код проверяется целиком в `before_request`.

| Эндпоинт | Код |
|---|---|
| `methodology_add`, `methodology_edit`, `methodology_disable`, `methodology_restore`, `methodology_zone_add`, `methodology_zone_shares`, `methodology_zone_rename`, `methodology_zone_remove`, `methodology_route`, `methodology_scoring` | `checklist.edit` |
| `methodology_publish` | `checklist.publish` |
| `checklists_create`, `checklists_state`, `methodology_bot`, `checklists_apply` | `checklist.manage` |
| `rx_create`, `rx_update`, `rx_send`, `rx_close` | `prescription.manage` |
| `order_reply` | `prescription.reply` |
| `actions_review`, `actions_due`, `actions_new` | `plan.manage` |
| `plans_upload` | `plan.submit` |
| `unit_create` | `unit.create` (`object_in_route=True`: объект — справочник УК, пространство `HQ`; прежний 404 партнёру сохраняется) |

**Files:**
- Modify: `src/web/app.py` — декоратор `@guard.action(...)` под каждым `@app.post` методики (~строки 1642–1846) и чек-листов (~1897–2023); в `checklists_create` (~1904–1910) снять отказ «Чек-листы заводит УК (D283)»
- Modify: `src/web/prescriptions.py` (~строки 184, 224, 244, 253, 491), `src/web/action_plans.py` (~219, 239, 255, 305)
- Modify: `src/web/unit_add.py` — `may_add_in` (~строка 45), `can_add_here` (~57), маршрут `unit_create` (~120)
- Create: `tests/test_web_permissions_routes.py`
- Modify: `tests/test_web_checklists_screen.py` (ожидание отказа партнёру при заведении → заведение в своём пространстве), `tests/test_web_methodology_spaces.py` (сотрудник страны правит методику → 403), `tests/test_web_unit_add.py` (`test_страна_вне_охвата_закрыта`, ~строки 101–106: `may_add_in` принимает `Actor`)
- Modify: `docs/12-web-admin.md` — новый подраздел «Права на действия» после «Вход: кто вообще видит эти страницы» (~строка 315)

**Interfaces:**
- Consumes: `guard.action`, `guard.permit` (Task 7); `auth.current_actor`, `can`; `src.web.methodology.create_checklist(store, *, tenant, author, code, name_ru, name_en)` — уже заводит в `space_of(tenant)`.
- Produces: `unit_add.may_add_in(actor: Actor, reach: Reach, code: str) -> bool` (вместо `tenant: str` первым параметром).

- [ ] **Step 1: Написать падающий тест**

```python
# tests/test_web_permissions_routes.py
"""Маршруты своего пространства спрашивают can — по таблице ролей (D310, D311)."""

from __future__ import annotations

from typing import Any

import pytest
from flask.testing import FlaskClient
from web_harness import СВОЙ, войти, подменить_двери, собрать

from src.web import guard
from src.web import methodology as method

МЕТОДИКА = ("/admin/items", "/admin/zones", "/admin/route", "/admin/scoring", "/admin/publish")


def _клиент(monkeypatch: pytest.MonkeyPatch, *, tenant: str, role: str) -> FlaskClient:
    подменить_двери(monkeypatch, tenant=tenant, role=role)
    client = собрать(tenant="HQ").test_client()
    assert войти(client).status_code == 302
    return client


@pytest.mark.parametrize("путь", МЕТОДИКА)
def test_сотрудник_страны_не_правит_методику(monkeypatch: pytest.MonkeyPatch, путь: str) -> None:
    клиент = _клиент(monkeypatch, tenant="GE", role="auditor")
    assert клиент.post(путь, headers={"Origin": СВОЙ}).status_code == 403


@pytest.mark.parametrize("путь", МЕТОДИКА)
def test_сотрудник_уК_правит_методику(monkeypatch: pytest.MonkeyPatch, путь: str) -> None:
    # Хранилище методики не задано (autouse-фикстура conftest): заслон пропустил,
    # и вид ответил своей страницей «не настроено» — 200, а не отказ.
    клиент = _клиент(monkeypatch, tenant="HQ", role="auditor")
    assert клиент.post(путь, headers={"Origin": СВОЙ}).status_code == 200


def test_админ_страны_заводит_чек_лист_в_своём_пространстве(monkeypatch: pytest.MonkeyPatch) -> None:
    заведено: list[dict[str, Any]] = []

    def завести(_store: Any, **kw: Any) -> Any:
        заведено.append(kw)
        return type("Заведён", (), {"code": kw["code"]})()

    monkeypatch.setattr(method, "load_store", lambda: type("С", (), {"store": object()})())
    monkeypatch.setattr(method, "create_checklist", завести)
    # После заведения вид рисует перечень (`_render_checklists`) — он читает
    # хранилище, а здесь вместо него заглушка.
    monkeypatch.setattr(method, "checklists_overview", lambda *_a, **_k: [])
    клиент = _клиент(monkeypatch, tenant="GE", role="admin")
    ответ = клиент.post(
        "/admin/checklists",
        data={"code": "ge_audit", "name_ru": "Аудит GE", "name_en": "GE audit"},
        headers={"Origin": СВОЙ},
    )
    assert ответ.status_code == 200
    assert [з["tenant"] for з in заведено] == ["GE"]


def test_сотрудник_страны_чек_лист_не_заводит(monkeypatch: pytest.MonkeyPatch) -> None:
    клиент = _клиент(monkeypatch, tenant="GE", role="auditor")
    ответ = клиент.post("/admin/checklists", data={"code": "x"}, headers={"Origin": СВОЙ})
    assert ответ.status_code == 403


def test_маршруты_своего_пространства_объявили_код() -> None:
    app = собрать(tenant="HQ")
    ожидание = {
        "methodology_add": ("checklist.edit",),
        "methodology_publish": ("checklist.publish",),
        "checklists_create": ("checklist.manage",),
        "methodology_bot": ("checklist.manage",),
        "rx_send": ("prescription.manage",),
        "order_reply": ("prescription.reply",),
        "actions_new": ("plan.manage",),
        "plans_upload": ("plan.submit",),
        "unit_create": ("unit.create",),
    }
    for эндпоинт, коды in ожидание.items():
        assert getattr(app.view_functions[эндпоинт], guard.ACTIONS_ATTR, ()) == коды, эндпоинт
```

- [ ] **Step 2: Прогнать — ожидается FAIL**

Run: `.venv/bin/pytest tests/test_web_permissions_routes.py -q`
Expected: FAIL — сотрудник страны получает не 403; админ страны получает отказ «Чек-листы заводит УК»; у эндпоинтов нет `required_actions`.

- [ ] **Step 3: Минимальная реализация**

Каждому эндпоинту из таблицы — декоратор строкой ниже `@app.post(...)`, например:

```python
    @app.post(f"{путь}/items")
    @guard.action("checklist.edit")
    def methodology_add() -> str:
```

`checklists_create`: удалить блок `if auth.current_tenant() != HQ_TENANT: ... отказ_заведения ...` целиком; комментарий над вызовом `method.create_checklist` заменить на: «Пространство — вошедшего (D311): админ страны заводит свои чек-листы у себя; чужое пространство дверь не принимает (`space_of(tenant)`), право — `checklist.manage` в заслоне.» Ключ текста `methodology.etalon_readonly` остаётся, если на него есть другие ссылки (`grep -n "etalon_readonly" src`); иначе удалить его из `src/web/texts.py` на обоих языках.

В `src/web/prescriptions.py` и `src/web/action_plans.py` — импорт `from . import guard`, декоратор под `@app.post(...)`. Существующие `_require_hq()` и `is_hq()` остаются. Партнёру 404 на `rx_*` и `actions_*` по-прежнему отвечает заслон раздела `actions` (`hq_only`, `_install_hq_gate`, D264) — он стоит раньше заслона прав; `order_reply` и `plans_upload` живут в разделах партнёра, их пропускает раздел, а решает `can`.

`src/web/unit_add.py`:

```python
from src.domain.permissions import Actor, can

from . import guard


def may_add_in(actor: Actor, reach: Reach, code: str) -> bool:
    """Может ли вошедший завести пиццерию в стране `code`: право, словарь сети, охват.

    Объект — справочник пиццерий; он один и принадлежит УК (D284), поэтому
    пространство объекта для `can` — `HQ_TENANT`.
    """
    if not can(actor, "unit.create", HQ_TENANT) or code not in COUNTRIES:
        return False
    return reach.countries is None or code in reach.countries


def can_add_here(code: str) -> bool:
    """Показывать ли вход «Добавить пиццерию» на экране страны `code`."""
    return bool(code) and may_add_in(auth.current_actor(), auth.current_reach(), code)
```

Маршрут `unit_create` (`unit_add.py` ~120): декоратор `@guard.action("unit.create", object_in_route=True)` под `@app.post(путь, endpoint="unit_create")`; тело начинается так:

```python
        страна = _gate(code)
        # Объект — справочник УК: пиццерия ложится с `tenant=HQ_TENANT` (ниже).
        отказ = guard.permit("unit.create", HQ_TENANT)
        if отказ is not None:
            return отказ
        refuse_foreign_origin()
```

`_gate` (404 вне права, словаря или охвата) уже зовёт `can_add_here` → `may_add_in(auth.current_actor(), ...)`; GET `unit_new` идёт через тот же `_gate`. Импорт `may_add_units` из `unit_add.py` убрать (`HQ_TENANT` там уже импортирован).

`tests/test_web_unit_add.py`, `test_страна_вне_охвата_закрыта` (импорт `from src.domain.permissions import DEFAULT_MATRIX, Actor`):

```python
def test_страна_вне_охвата_закрыта() -> None:
    уК = Actor(tenant="HQ", role="hq_staff", grants=DEFAULT_MATRIX["hq_staff"])
    страна = Actor(tenant="RS", role="country_admin", grants=DEFAULT_MATRIX["country_admin"])
    узкий = Reach("HQ", None, ("GE",))
    assert unit_add.may_add_in(уК, узкий, "GE")
    assert not unit_add.may_add_in(уК, узкий, "RS")
    assert unit_add.may_add_in(уК, Reach("HQ", None, None), "RS")
    assert not unit_add.may_add_in(страна, Reach("RS", None, None), "RS")
```

- [ ] **Step 4: Прогнать — ожидается PASS; веб целиком**

Run: `.venv/bin/pytest tests/test_web_permissions_routes.py -q` → PASS.
Run: `.venv/bin/pytest tests/test_web_*.py -q`
Expected: до правки красны только ожидания, что сотрудник страны правит методику (`tests/test_web_methodology_spaces.py`) — переписать на 403 (зафиксированное отличие спеки), и что партнёру отказано в заведении чек-листа (`tests/test_web_checklists_screen.py`) — переписать на заведение в своём пространстве (D311); `tests/test_web_unit_add.py` переписан выше. Заведение пиццерий сотрудником УК не меняется (D310). Любой другой красный — регрессия. После правки — PASS целиком.
Run: `make test-honest ARGS="tests/test_mcp_checklists.py -q -rs"` — дверь `lists_door.create` заводит чек-лист партнёра в его пространстве (тот же путь, что у MCP); красное — дверь не принимает партнёра, разбирать до коммита.

- [ ] **Step 5: Документация** — `docs/12-web-admin.md`, новый подраздел:

```markdown
## Права на действия (спека «Администрирование», блок 1)

Каждый пишущий адрес объявляет код действия (`src/web/guard.py: action`), и до
выполнения его спрашивает `can` (`src/domain/permissions.py`): граница пространств
в коде, право — в матрице роли (`role_permissions`). Каталог кодов — `ACTIONS`
в том же модуле; пишущие адреса без кода перечисляет `guard.uncovered`, и тест
полноты веба держит этот перечень пустым. Отказ — страница 403; адреса раздела «только УК»
по-прежнему отвечают партнёру 404 (D264). Роли по умолчанию: сотрудник страны методику
не правит; админ страны заводит и правит свои чек-листы у себя (D311); пиццерии заводят
люди УК (D310). Действия над проверкой — снять, перенести, подтвердить, поправить,
письмо — у сотрудников только над своими проверками, у админов — над всеми (D311).
```

- [ ] **Step 6: Коммит и пуш**

```bash
git add src/web/app.py src/web/prescriptions.py src/web/action_plans.py src/web/unit_add.py tests/test_web_permissions_routes.py tests/test_web_checklists_screen.py tests/test_web_methodology_spaces.py tests/test_web_unit_add.py docs/12-web-admin.md
git commit -m "feat: маршруты своего пространства спрашивают can; чек-листы страны (D311)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

(Файлы тестов, ожидания которых переписаны в Step 4, и `src/web/texts.py`, если ключ удалён, — добавить поимённо.)

### Task 9: Журнал в дверях проверок

Двери снятия, приёмки, переноса, правки на приёмке и письма принимают необязательную запись журнала и пишут её своим подключением до своего коммита — и только если действие состоялось.

**Files:**
- Modify: `src/db/retract.py` — `_mark_retracted` (~строки 144–195: параметр `journal`, запись до `conn.commit()`), `retract_inspection` (~275–325)
- Modify: `src/db/accept.py` — `accept_inspection` (~52–80)
- Modify: `src/db/move.py` — `move_inspection` (~90–127)
- Modify: `src/db/revise.py` — `revise_finding` (~98–125)
- Modify: `src/db/letters.py` — `save_letter` (~56–100)
- Modify: `src/web/inspections.py` — `accept_card` (~228), `retract_card` (~237), `move_card` (~285), `remember_letter` (~340): пробросить `journal`
- Modify: `src/web/revision.py` — `revise_card` (~53–120): пробросить `journal` в `revise.revise_finding` (~107)
- Create: `tests/test_db_cross_space_doors.py`

**Interfaces:**
- Consumes: `cross_space.Entry`, `cross_space.record` (Task 4); `db_harness.слить_проверку`, `привязать_пространства`, `точка_пространства`, `set_retraction_env`.
- Produces (новый keyword-only параметр `journal: Entry | None = None` у каждой):
  - `retract_inspection(inspection_id, *, tenant, reason, storage=None, journal=None) -> Retraction`; `_mark_retracted(conn, inspection_id, *, tenant, reason, journal=None)`
  - `accept_inspection(inspection_id, *, tenant, actor, journal=None) -> None`
  - `move_inspection(inspection_id, *, tenant, new_date, new_unit_id, reason, actor, journal=None) -> bool`
  - `revise_finding(inspection_id, finding_id, *, ..., journal=None)` (прочие параметры — как сейчас)
  - `save_letter(inspection_id, *, tenant, body, lang, saved_by, journal=None) -> SavedLetter`
  - `inspections.retract_card(..., journal=None)`, `accept_card(..., journal=None)`, `move_card(..., journal=None)`, `remember_letter(..., journal=None)`; `revision.revise_card(..., journal=None)`.

- [ ] **Step 1: Написать падающий тест**

```python
# tests/test_db_cross_space_doors.py
"""Действие УК над проверкой партнёра и строка журнала — одной транзакцией."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import requires_db
from db_harness import (
    привязать_пространства,
    set_retraction_env,
    слить_проверку,
    точка_пространства,
)

psycopg = pytest.importorskip("psycopg")

from src.db import retract  # noqa: E402
from src.db.cross_space import Entry  # noqa: E402
from src.db.errors import RetractionError  # noqa: E402
from src.db.retract import retract_inspection  # noqa: E402
from src.db.web_access import password_hash  # noqa: E402

pytestmark = requires_db
ТОЧКА = "Тбилиси-1"


@pytest.fixture
def retraction_env(db_env: str, monkeypatch: pytest.MonkeyPatch) -> str:
    return set_retraction_env(db_env, monkeypatch)


def _учётка_уК(pg_dsn: str) -> str:
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "insert into web_users (tenant_code, login, password_hash, role) "
            "values ('HQ', 'hq-doors', %s, 'hq_admin') returning id",
            (password_hash("пароль-дверей-1"),),
        )
        строка = cur.fetchone()
    assert строка is not None
    return str(строка[0])


def _журнал(pg_dsn: str) -> list[tuple[str, str, str]]:
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute("select object_tenant, action_code, object_ref from cross_space_actions")
        return [(str(a), str(b), str(c)) for a, b, c in cur.fetchall()]


def _проверка_партнёра(pg_dsn: str) -> tuple[str, str]:
    привязать_пространства(pg_dsn, "GE")
    точка_пространства(ТОЧКА, tenant="GE")
    return слить_проверку(unit=ТОЧКА, tenant="GE"), _учётка_уК(pg_dsn)


def test_снятие_проверки_партнёра_пишет_журнал(
    domain_env: Path, pg_dsn: str, retraction_env: str
) -> None:
    ident, кто = _проверка_партнёра(pg_dsn)
    retract_inspection(
        ident,
        tenant="GE",
        reason="УК сняла ошибочную",
        journal=Entry(кто, "HQ", "GE", "inspection.retract", f"inspection:{ident}"),
    )
    assert _журнал(pg_dsn) == [("GE", "inspection.retract", f"inspection:{ident}")]


def test_отказ_двери_не_оставляет_журнала(
    domain_env: Path, pg_dsn: str, retraction_env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Дверь падает ПОСЛЕ записи журнала — и строка уходит вместе с пометкой."""
    ident, кто = _проверка_партнёра(pg_dsn)
    # Запрос отметки времени идёт после `record`: его поломка роняет транзакцию,
    # в которой журнал уже записан. Отказ раньше записи этого бы не проверил.
    monkeypatch.setattr(
        retract, "_SELECT_RETRACTED_AT_SQL", "select нет_такой_колонки where %s is not null"
    )
    with pytest.raises(RetractionError):
        retract_inspection(
            ident,
            tenant="GE",
            reason="упадёт после журнала",
            journal=Entry(кто, "HQ", "GE", "inspection.retract", f"inspection:{ident}"),
        )
    assert _журнал(pg_dsn) == []


def test_повторное_снятие_журнал_не_дублирует(
    domain_env: Path, pg_dsn: str, retraction_env: str
) -> None:
    ident, кто = _проверка_партнёра(pg_dsn)
    запись = Entry(кто, "HQ", "GE", "inspection.retract", f"inspection:{ident}")
    retract_inspection(ident, tenant="GE", reason="первый вызов", journal=запись)
    retract_inspection(ident, tenant="GE", reason="повтор доделывает уборку", journal=запись)
    assert len(_журнал(pg_dsn)) == 1
```

- [ ] **Step 2: Прогнать — ожидается FAIL**

Run: `make test-honest ARGS="tests/test_db_cross_space_doors.py -q -rs"`
Expected: FAIL — `TypeError: retract_inspection() got an unexpected keyword argument 'journal'`.

- [ ] **Step 3: Минимальная реализация**

`src/db/retract.py` (импорт `from .cross_space import Entry, record`). `_mark_retracted` получает `journal: Entry | None = None` последним keyword-параметром; строка журнала — сразу после проверки `cur.rowcount != 1` и до `_SELECT_RETRACTED_AT_SQL`, то есть внутри той транзакции, которую функция сама коммитит. На ветке «уже снята» (`if снята is not None: return ...`) журнал не пишется — действие не состоялось:

```python
        cur.execute(_RETRACT_SQL, {"id": inspection_id, "reason": reason})
        if cur.rowcount != 1:
            raise RetractionError(...)  # текст как сейчас
        # Журнал — в ТОЙ ЖЕ транзакции, что пометка, до её коммита ниже
        # (спека «Администрирование»): откатилась пометка — откатилась строка.
        # Повторный вызов на уже снятой выходит раньше и строки не дублирует.
        record(conn, journal)
        cur.execute(_SELECT_RETRACTED_AT_SQL, (inspection_id,))
```

`retract_inspection`: параметр `journal: Entry | None = None` после `storage`; вызов — `_mark_retracted(conn, ident, tenant=tenant_code, reason=записанная_причина, journal=journal)`.

`src/db/accept.py`: параметр `journal: Entry | None = None`; `record(conn, journal)` между `_open_plan_request(conn, ident, автор)` и `conn.commit()` (`_apply` при неудаче бросает `AcceptError` — до записи не доходит).
`src/db/move.py`: параметр `journal`; после `изменено = _apply(...)` — `if изменено: record(conn, journal)`, затем `conn.commit()` (перенос «всё уже так» следа не оставляет).
`src/db/revise.py`: параметр `journal`; `record(conn, journal)` сразу после `_apply(conn, ...)` и до `conn.commit()` внутри `with psycopg.connect(check_environment().dsn) as conn`.
`src/db/letters.py`: параметр `journal`; `record(conn, journal)` после проверки `if row is None: raise PushError(...)` (внутри `with conn.cursor()` или сразу за ним) и до `conn.commit()`.
`src/web/inspections.py`: `accept_card`, `retract_card`, `move_card`, `remember_letter` получают `journal: Entry | None = None` (импорт `from src.db.cross_space import Entry`) и передают его в дверь без изменений. `src/web/revision.py`: `revise_card(..., journal: Entry | None = None)` передаёт `journal=journal` в `revise.revise_finding(...)`.

- [ ] **Step 4: Прогнать — ожидается PASS; двери целиком**

Run: `make test-honest ARGS="tests/test_db_cross_space_doors.py tests/test_db_retraction.py tests/test_db_accept.py tests/test_db_move.py tests/test_db_revise.py tests/test_db_letters.py -q -rs"`
Expected: PASS, `SKIPPED` нет — прежние наборы дверей не задеты (параметр необязательный).
Отрицательный прогон: в `_mark_retracted` перенести `record(conn, journal)` после `conn.commit()` → `test_отказ_двери_не_оставляет_журнала` FAIL (строка журнала осталась); вернуть, PASS.
Run: `.venv/bin/pytest tests/test_web_*.py -q` → PASS (обёртки получили необязательный параметр).

- [ ] **Step 5: Коммит и пуш**

```bash
git add src/db/retract.py src/db/accept.py src/db/move.py src/db/revise.py src/db/letters.py src/web/inspections.py src/web/revision.py tests/test_db_cross_space_doors.py
git commit -m "feat: двери проверок пишут журнал действий УК своей транзакцией

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

### Task 10: Веб — действия над проверкой: пространство и автор из проверки, УК у партнёра с журналом

| Эндпоинт | Код | Пространство / автор объекта |
|---|---|---|
| `do_retract` | `inspection.retract` | `detail.inspection.tenant_code` / `detail.inspection.created_by` |
| `do_accept` | `inspection.accept` | то же |
| `do_revise` | `inspection.revise` | то же |
| `do_move` | `inspection.move` | то же |
| `save_letter` | `inspection.letter` | то же |
| `letter_draft` | `inspection.letter` | то же |
| `google_mail_callback` | `inspection.letter` (письмо) / `prescription.manage` (предписание, объект `HQ`) | проверка письма / `HQ` |

Возврат от Google по письму в базу не пишет (черновик в Gmail собирается из уже зафиксированного письма), поэтому журнала у него нет — только `permit`. Ветка предписания спрашивает право в `prescriptions._finish_gmail` после `is_hq()`: партнёру этот адрес по-прежнему отвечает 404 (D264), а не 403.

**Files:**
- Modify: `src/web/guard.py` — дописать `inspection_author`, `inspection_journal`
- Modify: `src/web/app.py` — `_refuse_unless_own` (~1399) заменить на `_permit_on_inspection`; новый `_may`; маршруты `save_letter` (~987), `do_retract` (~1288), `do_accept` (~1308), `do_revise` (~1333), `do_move` (~1362); страница письма `letter` (~976: `own=`); `_render_card` (~1467–1600); удалить `_admin_only` (~1452)
- Modify: `src/web/templates/inspections/card.html` — кнопка письма (~59: `{% if own %}` → `{% if may_letter %}`), плашка приёмки (~92)
- Modify: `src/web/texts.py` — ключ `accept.not_yours` (ru/en) рядом с `accept.foreign` (~475)
- Modify: `src/web/letter_draft.py` — `letter_draft` (~161), `google_mail_callback` (~232)
- Modify: `src/web/prescriptions.py` — `_finish_gmail` (~288)
- Create: `tests/test_web_inspection_rights.py`
- Modify: `tests/test_web_spaces_boundary.py` (фикстура `уК_у_партнёра` ~99, тест ~112), `tests/test_web_acceptance.py` (~155, ~265), `tests/test_web_app.py` (~386), `tests/test_web_letter.py` (~75), `tests/test_web_letter_draft.py` (`карточка` ~39, тест ~231)

**Interfaces:**
- Consumes: `guard.action`, `guard.permit`, `guard.forbidden`, `web_harness.УЧЁТКА` (Task 7); `auth.current_actor`; `cross_space.entry_for`, `cross_space.Entry` (Task 4); `InspectionRow.created_by` (Task 5); `journal` у обёрток `inspections` и `revision.revise_card` (Task 9).
- Produces:
  - `guard.inspection_author(detail: Any) -> str | None` — автор проверки; `None` — неизвестен.
  - `guard.inspection_journal(detail: Any, code: str) -> Entry | None` — строка журнала, если пространство проверки чужое.
  - `app._permit_on_inspection(inspection_id: str, code: str) -> tuple[Any | None, tuple[str, int] | None]`.
  - `app._may(code: str, detail: Any) -> bool`.
  - Шаблон карточки получает `may_letter`.

- [ ] **Step 1: Написать падающий тест**

```python
# tests/test_web_inspection_rights.py
"""Действия над проверкой: пространство и автор — из самой проверки (D304, D311)."""

from __future__ import annotations

from typing import Any

import pytest
from flask.testing import FlaskClient
from test_web_app import карточка, шапка
from web_harness import СВОЙ, УЧЁТКА, войти, подменить_двери, собрать

from src.db.retract import Retraction
from src.web import inspections as data

ПРОВЕРКА = "11111111-1111-1111-1111-111111111111"
ДРУГОЙ = "33333333-3333-3333-3333-333333333333"


@pytest.fixture
def зовы(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    записано: list[dict[str, Any]] = []

    def снять(inspection_id: str, **kw: Any) -> Retraction:
        записано.append({"id": inspection_id, **kw})
        return Retraction(
            inspection_id=inspection_id,
            reason=kw["reason"],
            retracted_at="2026-10-07T10:00:00+00:00",
            photos_purged=0,
        )

    monkeypatch.setattr(data, "retract_card", снять)
    monkeypatch.setattr(data, "retraction_available", lambda: True)
    monkeypatch.setattr(data, "load_moves", lambda *_a, **_k: ())
    monkeypatch.setattr(data, "load_units", lambda **_: ())
    return записано


def _клиент(
    monkeypatch: pytest.MonkeyPatch, *, tenant: str, role: str, чья: str, автор: str = ""
) -> FlaskClient:
    подменить_двери(monkeypatch, tenant=tenant, role=role)
    деталь = карточка(шапка(id=ПРОВЕРКА, tenant_code=чья, created_by=автор))
    monkeypatch.setattr(data, "load_card", lambda *_a, **_k: деталь)
    client = собрать(tenant=tenant).test_client()
    assert войти(client).status_code == 302
    return client


def _снять(client: FlaskClient) -> int:
    return client.post(
        f"/inspections/{ПРОВЕРКА}/retract", data={"reason": "ошибка"}, headers={"Origin": СВОЙ}
    ).status_code


def test_админ_уК_снимает_проверку_партнёра_и_пишет_журнал(
    monkeypatch: pytest.MonkeyPatch, зовы: list[dict[str, Any]]
) -> None:
    клиент = _клиент(monkeypatch, tenant="HQ", role="admin", чья="GE")
    assert _снять(клиент) == 200
    (вызов,) = зовы
    assert вызов["tenant"] == "GE"
    assert вызов["journal"].action_code == "inspection.retract"
    assert вызов["journal"].object_tenant == "GE"
    assert вызов["journal"].object_ref == f"inspection:{ПРОВЕРКА}"


def test_своя_проверка_журнала_не_пишет(
    monkeypatch: pytest.MonkeyPatch, зовы: list[dict[str, Any]]
) -> None:
    клиент = _клиент(monkeypatch, tenant="GE", role="admin", чья="GE")
    assert _снять(клиент) == 200
    assert зовы[0]["journal"] is None


def test_админ_страны_не_снимает_проверку_уК(
    monkeypatch: pytest.MonkeyPatch, зовы: list[dict[str, Any]]
) -> None:
    клиент = _клиент(monkeypatch, tenant="GE", role="admin", чья="HQ", автор=УЧЁТКА)
    assert _снять(клиент) == 403
    assert зовы == []


def test_сотрудник_страны_снимает_свою(
    monkeypatch: pytest.MonkeyPatch, зовы: list[dict[str, Any]]
) -> None:
    клиент = _клиент(monkeypatch, tenant="GE", role="auditor", чья="GE", автор=УЧЁТКА)
    assert _снять(клиент) == 200
    assert зовы[0]["journal"] is None


def test_сотрудник_страны_не_снимает_чужую(
    monkeypatch: pytest.MonkeyPatch, зовы: list[dict[str, Any]]
) -> None:
    клиент = _клиент(monkeypatch, tenant="GE", role="auditor", чья="GE", автор=ДРУГОЙ)
    assert _снять(клиент) == 403
    assert зовы == []


def test_сотрудник_уК_снимает_свою_у_партнёра_с_журналом(
    monkeypatch: pytest.MonkeyPatch, зовы: list[dict[str, Any]]
) -> None:
    клиент = _клиент(monkeypatch, tenant="HQ", role="auditor", чья="GE", автор=УЧЁТКА)
    assert _снять(клиент) == 200
    assert зовы[0]["journal"].object_tenant == "GE"


def test_сотрудник_уК_не_снимает_проверку_без_автора(
    monkeypatch: pytest.MonkeyPatch, зовы: list[dict[str, Any]]
) -> None:
    клиент = _клиент(monkeypatch, tenant="HQ", role="auditor", чья="HQ", автор="")
    assert _снять(клиент) == 403
    assert зовы == []


def test_админ_уК_снимает_проверку_без_автора(
    monkeypatch: pytest.MonkeyPatch, зовы: list[dict[str, Any]]
) -> None:
    клиент = _клиент(monkeypatch, tenant="HQ", role="admin", чья="HQ", автор="")
    assert _снять(клиент) == 200
    assert зовы[0]["journal"] is None


@pytest.mark.parametrize(
    ("role", "автор", "видны"),
    [("admin", "", True), ("auditor", УЧЁТКА, True), ("auditor", ДРУГОЙ, False)],
)
def test_кнопки_карточки_отвечают_как_маршрут(
    monkeypatch: pytest.MonkeyPatch,
    зовы: list[dict[str, Any]],
    role: str,
    автор: str,
    видны: bool,
) -> None:
    клиент = _клиент(monkeypatch, tenant="GE", role=role, чья="GE", автор=автор)
    страница = клиент.get(f"/inspections/{ПРОВЕРКА}").get_data(as_text=True)
    for действие in ("/retract", "/move", "/letter"):
        assert (действие in страница) is видны, действие
```

- [ ] **Step 2: Прогнать — ожидается FAIL**

Run: `.venv/bin/pytest tests/test_web_inspection_rights.py -q`
Expected: FAIL — админ УК над проверкой `GE` получает 403 (сегодняшний `_refuse_unless_own`), сотрудник получает 403 и на своей (`_admin_only`), у вызова нет `journal`.

- [ ] **Step 3: Минимальная реализация**

`src/web/guard.py` — дописать (импорт `from src.db.cross_space import Entry, entry_for`):

```python
def inspection_author(detail: Any) -> str | None:
    """Учётка, занёсшая проверку; `None` — автор неизвестен (D311)."""
    return detail.inspection.created_by or None


def inspection_journal(detail: Any, code: str) -> Entry | None:
    """Строка журнала, если вошедший действует над проверкой чужого пространства."""
    return entry_for(
        auth.current_actor(),
        object_tenant=detail.inspection.tenant_code,
        action=code,
        object_ref=f"inspection:{detail.inspection.id}",
    )
```

`src/web/app.py` (импорт `from src.domain.permissions import can`; `guard` импортирован в Task 7) — вместо `_refuse_unless_own` и `_admin_only`:

```python
def _permit_on_inspection(
    inspection_id: str, code: str
) -> tuple[Any | None, tuple[str, int] | None]:
    """Проверка в охвате и право на действие над ней — пространство и автор из неё.

    Вне охвата — 404, как у несуществующей: «нет» и «не видно» неразличимы.
    Видимую, но недоступную для действия — 403: делать вид, что её нет, — загадка.
    """
    detail = data.load_card(inspection_id, reach=auth.current_reach())
    if detail is None:
        return None, (render_template("inspections/not_found.html"), 404)
    отказ = guard.permit(
        code, detail.inspection.tenant_code, object_author=guard.inspection_author(detail)
    )
    if отказ is not None:
        return None, отказ
    return detail, None


def _may(code: str, detail: Any) -> bool:
    """Показывать ли кнопку действия — тот же ответ, что даст маршрут."""
    return can(
        auth.current_actor(),
        code,
        detail.inspection.tenant_code,
        object_author=guard.inspection_author(detail),
    ).allowed
```

`do_retract` целиком:

```python
    @app.post(f"{section('registry').path}/<inspection_id>/retract")
    @guard.action("inspection.retract", object_in_route=True)
    def do_retract(inspection_id: str) -> FlaskResponse | str | tuple[str, int]:
        refuse_foreign_origin()
        detail, отказ = _permit_on_inspection(inspection_id, "inspection.retract")
        if отказ is not None:
            return отказ
        reason = (request.form.get("reason") or "").strip()
        notice: str | None = None
        failure: str | None = None
        try:
            done = data.retract_card(
                inspection_id,
                tenant=detail.inspection.tenant_code,
                reason=reason,
                journal=guard.inspection_journal(detail, "inspection.retract"),
            )
        except RetractionError as exc:
            failure = t("retract.failed", _lang(conf), reason=str(exc))
        else:
            notice = t("retract.done", _lang(conf), photos=done.photos_purged)
        return _render_card(inspection_id, conf=conf, notice=notice, failure=failure)
```

`do_accept`, `do_revise`, `do_move` — то же строение: декоратор `@guard.action("<код>", object_in_route=True)` под `@app.post(...)`; первые строки тела — `refuse_foreign_origin()`, затем `detail, отказ = _permit_on_inspection(inspection_id, "<код>")` и `if отказ is not None: return отказ` (строки `отказ = _admin_only()` и `чужая = _refuse_unless_own(...)` удаляются); в вызове двери `tenant=auth.current_tenant()` → `tenant=detail.inspection.tenant_code` и добавляется `journal=guard.inspection_journal(detail, "<код>")`:
- `do_accept`: `data.accept_card(inspection_id, tenant=detail.inspection.tenant_code, actor=..., journal=guard.inspection_journal(detail, "inspection.accept"))`;
- `do_revise`: `revision.revise_card(inspection_id, finding_id, tenant=detail.inspection.tenant_code, lang=..., code=..., level=..., zone=..., text=..., journal=guard.inspection_journal(detail, "inspection.revise"))` — `revise_card` отказывает, если `tenant` не совпал с пространством проверки, поэтому пространство вошедшего сюда больше не передаётся;
- `do_move`: `data.move_card(inspection_id, tenant=detail.inspection.tenant_code, new_date=..., new_unit_id=..., reason=..., actor=..., journal=guard.inspection_journal(detail, "inspection.move"))`.

Докстринги маршрутов «Админ своего пространства (D283)» / «Только администратор» → «Право — `can` (D304, D311)».

`save_letter`: декоратор `@guard.action("inspection.letter", object_in_route=True)`; после `refuse_foreign_origin()` строки `detail = data.load_card(...)`, `if detail is None: ...404`, `if not _own(detail): ...403` заменяются на

```python
        detail, отказ = _permit_on_inspection(inspection_id, "inspection.letter")
        if отказ is not None:
            return отказ
```

и вызов двери —

```python
            data.remember_letter(
                inspection_id,
                tenant=detail.inspection.tenant_code,
                body=текст,
                lang=письмо_на,
                saved_by="—" if вошедший is None else вошедший.login,
                journal=guard.inspection_journal(detail, "inspection.letter"),
            )
```

Страница письма (`letter`, ~976): `own=_own(detail)` → `own=_may("inspection.letter", detail)` — форма письма показывается тому, чью запись примет маршрут.

`_render_card`: строку `админ = _admin_only() is None` удалить; `своя = _own(detail)` остаётся (план действий УК и плашка приёмки); флаги кнопок:

```python
    можно_переносить = (
        _may("inspection.move", detail)
        and история_известна
        and data.retraction_available()
        and not detail.inspection.retracted
        and not detail.inspection.on_review
    )
    # Подтверждать и править — ровно до подтверждения (D199, D200); кто — решает
    # `can` (D304, D311), у каждого действия своё право.
    ждёт_приёмки = (
        data.retraction_available()
        and detail.inspection.on_review
        and not detail.inspection.retracted
    )
```

и в `render_template(...)`:

```python
        may_accept=ждёт_приёмки and _may("inspection.accept", detail),
        may_revise=ждёт_приёмки and _may("inspection.revise", detail),
        ...
        may_retract=data.retraction_available()
        and _may("inspection.retract", detail)
        and not detail.inspection.on_review,
        may_letter=_may("inspection.letter", detail),
        own=своя,
```

(`можно_подтвердить` и его комментарий удаляются.) Функции `_admin_only`, `_refuse_unless_own` и `_is_admin` (мост Task 3: её звал только `_admin_only`) удалить; из импорта `src.domain.permissions` убрать `ROLE_COUNTRY_ADMIN` (`ROLE_HQ_ADMIN` и `canonical_role` нужны `_is_hq_admin` до Task 11). `make dead` подтвердит, что вызовов не осталось.

`src/web/templates/inspections/card.html`:
- ~57–59: комментарий и условие кнопки письма —
  ```jinja
      {# Письмо партнёру — запись по проверке: кнопка у того, чью запись примет
         маршрут (`can`, D304, D311). #}
      {% if may_letter %}
  ```
- ~92: плашка приёмки —
  ```jinja
        <div class="note__text">{% if may_accept %}{{ t('accept.banner.text') }}{% elif own %}{{ t('accept.not_yours') }}{% else %}{{ t('accept.foreign') }}{% endif %}</div>
  ```

`src/web/texts.py`, рядом с `accept.foreign`:

```python
    "accept.not_yours": {
        "ru": "Подтверждает проверку тот, кто её провёл, или администратор пространства.",
        "en": "The inspection is confirmed by the person who conducted it or by the space admin.",
    },
```

`src/web/letter_draft.py` (импорт `from . import guard`):

- `letter_draft`: декоратор `@guard.action("inspection.letter", object_in_route=True)` под `@app.post(...)`; блок `if not auth.is_own(detail.inspection.tenant_code): ... 403` заменить на
  ```python
        отказ = guard.permit(
            "inspection.letter",
            detail.inspection.tenant_code,
            object_author=guard.inspection_author(detail),
        )
        if отказ is not None:
            return отказ
  ```
  и в `data.remember_letter(...)`: `tenant=detail.inspection.tenant_code` и `journal=guard.inspection_journal(detail, "inspection.letter")`.
- `google_mail_callback`: декоратор `@guard.action("inspection.letter", "prescription.manage", object_in_route=True)` под `@app.get(...)`; блок `if not auth.is_own(...)` в ветке письма — та же замена на `guard.permit("inspection.letter", ...)` (без журнала: ветка в базу не пишет).

`src/web/prescriptions.py`, `_finish_gmail`, сразу после блока `if not is_hq(): abort(404)` (импорты: `make_response` — в строку `from flask import ...`, `from src.domain.tenants import HQ_TENANT`; `guard` импортирован в Task 8):

```python
    отказ = guard.permit("prescription.manage", HQ_TENANT)
    if отказ is not None:
        return make_response(*отказ)
```

Тесты, ожидания которых меняет D304/D311 (переписать в этой же задаче, каждое со ссылкой на решение):
- `tests/test_web_spaces_boundary.py`, фикстура `уК_у_партнёра`: `role="admin"` → `role="auditor"`, двойник карточки — `SimpleNamespace(tenant_code="GE", id=ЧУЖАЯ, created_by="")`, докстринг «Вошёл сотрудник УК; проверка в его охвате, пространства GE, автора нет (D311)»; тест переименовать в `test_сотрудник_уК_читает_проверку_партнёра_но_запись_отказывает`. Админа УК у партнёра теперь покрывает `test_web_inspection_rights.py` (D304).
- `tests/test_web_acceptance.py`: у `test_ждущая_чужого_пространства_только_на_чтение` и `test_запись_чужого_пространства_не_исправляется` снять `@админ` (вошедший — сотрудник УК, автора у проверки нет: 403 и нет кнопок, D311); докстринг первого — «Сотрудник УК видит ждущую партнёра без своего авторства: лист есть, кнопок приёмки и правки нет (D311)».
- `tests/test_web_app.py`, `test_действия_записи_только_у_проверки_своего_пространства`: снять `@админ`, параметры `("пространство", "автор", "свои_действия"), [(ТЕНАНТ, УЧЁТКА, True), ("GE", "", False)]`, карточка `шапка(tenant_code=пространство, created_by=автор)`, докстринг — «Сотрудник УК: действия — над своей проверкой (D311); чужая у партнёра — только чтение»; импорт `УЧЁТКА` из `web_harness`.
- `tests/test_web_letter.py` (~75): `карточка(шапка())` → `карточка(шапка(created_by=УЧЁТКА))` — вошедший двойник — сотрудник, письмо пишет по своей (D311); импорт `УЧЁТКА`.
- `tests/test_web_letter_draft.py`: в `карточка()` добавить `created_by=УЧЁТКА` (импорт из `web_harness`); `test_у_проверки_чужого_пространства_нет_кнопок_записи_письма` — параметры `("пространство", "автор", "видны"), [(ТЕНАНТ, УЧЁТКА, True), ("GE", "", False), ("GE", УЧЁТКА, True)]`, в `replace(своя.inspection, tenant_code=пространство, created_by=автор)`; третий случай — D311: свою проверку у партнёра сотрудник УК ведёт и дальше (с журналом).

- [ ] **Step 4: Прогнать — ожидается PASS; веб целиком**

Run: `.venv/bin/pytest tests/test_web_inspection_rights.py -q` → PASS.
Run: `.venv/bin/pytest tests/test_web_*.py -q` → зелёное. Красное вне перечисленных в Step 3 наборов — регрессия: разобрать, а не переписывать ожидание.
Run: `make lint types dead`

Негативный прогон: в `_permit_on_inspection` временно передать `object_author=None` — `test_сотрудник_страны_снимает_свою` и `test_сотрудник_уК_снимает_свою_у_партнёра_с_журналом` должны упасть с 403; вернуть.

- [ ] **Step 5: Коммит и пуш**

```bash
git add src/web/guard.py src/web/app.py src/web/letter_draft.py src/web/prescriptions.py \
  src/web/texts.py src/web/templates/inspections/card.html \
  tests/test_web_inspection_rights.py tests/test_web_spaces_boundary.py tests/test_web_acceptance.py \
  tests/test_web_app.py tests/test_web_letter.py tests/test_web_letter_draft.py
git commit -m "feat: действия над проверкой — пространство и автор из проверки, УК у партнёра с журналом

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

### Task 11: Веб — люди через `can`, журнал, роли из базы; мост ролей снимается

| Эндпоинт | Код | Пространство объекта |
|---|---|---|
| `user_role`, `user_email`, `add_user`, `disable_user` | `people.manage` | пространство из формы (сверено с заведёнными) |
| `bot_unlink` | `people.manage` | пространство учётки, чья привязка; своя — `guard.mark_own()` |

Мост до блока 2: экран людей открыт только людям УК (иначе админ страны получил бы перечень всех пространств). Матрица отвечает на «может ли» — `hq_staff` по-прежнему не управляет никем.

Здесь же снимается мост ролей Task 3: `web_access.ROLES`, `web_access.LEGACY_ROLES`, `app._is_hq_admin`, `app._hq_admin_only`, ключи `nav.role.*` и `users.role.<код роли>`. Старые имена `ROLE_AUDITOR`/`ROLE_ADMIN` остаются только входом, который `_checked_role` переводит по пространству (`add` без роли заводит самую узкую роль пространства).

**Files:**
- Modify: `src/web/app.py` — `_hq_admin_only` (~1435) и `_is_hq_admin` (мост Task 3) удалить, вместо них `_people_permit(target_tenant)` и `_people_journal(target_tenant, login)`; `_страница_учёток` (~1045–1105: `управляет`, `roles=accounts.ROLES` → `role_options`, `role_names`); `bot_unlink` (~1142), `_правка_человека` (~1186), `user_role` (~1209), `user_email` (~1224), `add_user` (~1239), `disable_user` (~1263)
- Modify: `src/web/people.py` — `change_role` (~56), `change_email` (~82)
- Modify: `src/web/accounts.py` — `add`, `disable`, `reassign_role`, `set_email` (параметр `journal`); из импорта и `__all__` убрать `ROLES`, `LEGACY_ROLES`
- Modify: `src/db/web_access.py` — удалить `ROLES`, `LEGACY_ROLES`; `create_account` (~476), `disable_account` (~532), `reassign_role` (~554), `set_email` (~647) — параметр `journal`
- Modify: `src/db/bot_links.py` — `unbind` (~218)
- Modify: `src/web/templates/users/index.html` (~120, ~203–210, ~284–286), `src/web/templates/base.html` (~141)
- Modify: `src/web/texts.py` — удалить `nav.role.admin`, `nav.role.auditor`, `nav.role.hq_admin`, `nav.role.hq_staff`, `nav.role.country_admin`, `nav.role.country_staff`, `users.role.admin`, `users.role.auditor`, `users.role.hq_admin`, `users.role.hq_staff`, `users.role.country_admin`, `users.role.country_staff`; добавить `users.role.scope`, `users.roles.hq`, `users.roles.country` (ru/en)
- Create: `tests/test_web_people_rights.py`
- Modify: `tests/test_web_users_access.py`, `tests/test_web_users.py` (роль из формы — новые коды; подменённые двери принимают `journal`)
- Modify: `docs/12-web-admin.md` — строка таблицы «Назначить человеку роль…» (~49)

**Interfaces:**
- Consumes: `guard.permit`, `guard.mark_own`, `guard.forbidden` (Task 7); `entry_for`, `record`, `Entry` (Task 4); `roles.list_roles() -> tuple[Role, ...]` (Task 6); `scope_of_tenant` (Task 2); `Account.role_name_ru`, `Account.role_name_en` (Task 6).
- Produces:
  - `app._people_permit(target_tenant: str) -> tuple[str, int] | None`, `app._people_journal(target_tenant: str, login: str) -> Entry | None`.
  - `people.change_role(*, login, tenant, role, actor_login, actor_tenant, known: Mapping[str, str], journal: Entry | None = None) -> Outcome` — `known`: код роли → охват роли; неизвестная → `Outcome("role.unknown", 400)`, чужой охват → `Outcome("role.scope", 400)`.
  - `people.change_email(*, login, tenant, email, actor_login, actor_tenant, journal: Entry | None = None) -> Outcome`.
  - `accounts.add(login, *, tenant, role=ROLE_AUDITOR, journal=None) -> Added`, `accounts.disable(login, *, tenant, journal=None) -> bool`, `accounts.reassign_role(login, *, tenant, role, journal=None) -> str | None`, `accounts.set_email(login, *, tenant, email, journal=None) -> bool`.
  - `web_access.create_account(..., journal=None)`, `disable_account(..., journal=None)`, `reassign_role(..., journal=None)`, `set_email(..., journal=None)`, `bot_links.unbind(user_id, *, journal=None)` — строка журнала пишется только если действие состоялось.

- [ ] **Step 1: Написать падающий тест**

```python
# tests/test_web_people_rights.py
"""Люди: people.manage через can, роль из ролей пространства, УК у партнёра — в журнал."""

from __future__ import annotations

from typing import Any

import pytest
from flask.testing import FlaskClient
from web_harness import СВОЙ, войти, подменить_двери, собрать

from src.db import roles as roles_door
from src.db.roles import Role
from src.web import accounts, people
from src.web.texts import TEXTS

РОЛИ = (
    Role("hq_admin", "hq", "Админ УК", "HQ admin", {}),
    Role("hq_staff", "hq", "Сотрудник УК", "HQ staff", {}),
    Role("country_admin", "country", "Админ страны", "Country admin", {}),
    Role("country_staff", "country", "Сотрудник страны", "Country staff", {}),
)
ОХВАТЫ = {р.code: р.scope for р in РОЛИ}


@pytest.fixture
def зовы(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    записано: list[dict[str, Any]] = []

    def роль(login: str, **kw: Any) -> str:
        записано.append({"login": login, **kw})
        return "country_staff"

    monkeypatch.setattr(accounts, "reassign_role", роль)
    monkeypatch.setattr(accounts, "spaces", lambda: ("GE", "HQ"))
    monkeypatch.setattr(accounts, "everyone", lambda **_: ())
    monkeypatch.setattr(roles_door, "list_roles", lambda: РОЛИ)
    return записано


def _клиент(monkeypatch: pytest.MonkeyPatch, *, tenant: str, role: str) -> FlaskClient:
    подменить_двери(monkeypatch, tenant=tenant, role=role)
    client = собрать(tenant=tenant).test_client()
    assert войти(client).status_code == 302
    return client


def _назначить(client: FlaskClient, роль: str, где: str = "GE") -> int:
    return client.post(
        "/users/role", data={"login": "anna", "tenant": где, "role": роль}, headers={"Origin": СВОЙ}
    ).status_code


def test_админ_уК_назначает_роль_страны_и_пишет_журнал(
    monkeypatch: pytest.MonkeyPatch, зовы: list[dict[str, Any]]
) -> None:
    клиент = _клиент(monkeypatch, tenant="HQ", role="admin")
    assert _назначить(клиент, "country_admin") == 200
    (вызов,) = зовы
    assert вызов["role"] == "country_admin"
    assert вызов["journal"].object_tenant == "GE"
    assert вызов["journal"].object_ref == "web_user:anna"


def test_правка_человека_УК_журнала_не_пишет(
    monkeypatch: pytest.MonkeyPatch, зовы: list[dict[str, Any]]
) -> None:
    клиент = _клиент(monkeypatch, tenant="HQ", role="admin")
    assert _назначить(клиент, "hq_staff", где="HQ") == 200
    assert зовы[0]["journal"] is None


def test_роль_уК_человеку_страны_не_назначается(
    monkeypatch: pytest.MonkeyPatch, зовы: list[dict[str, Any]]
) -> None:
    клиент = _клиент(monkeypatch, tenant="HQ", role="admin")
    assert _назначить(клиент, "hq_admin") == 400
    assert зовы == []


def test_сотрудник_уК_людьми_не_управляет(
    monkeypatch: pytest.MonkeyPatch, зовы: list[dict[str, Any]]
) -> None:
    клиент = _клиент(monkeypatch, tenant="HQ", role="auditor")
    assert _назначить(клиент, "country_staff") == 403
    assert зовы == []


def test_админ_страны_до_блока_2_людьми_не_управляет(
    monkeypatch: pytest.MonkeyPatch, зовы: list[dict[str, Any]]
) -> None:
    клиент = _клиент(monkeypatch, tenant="GE", role="admin")
    assert _назначить(клиент, "country_staff") == 403
    assert зовы == []


def test_чужой_охват_отказывает_до_двери() -> None:
    исход = people.change_role(
        login="anna",
        tenant="GE",
        role="hq_staff",
        actor_login="boss",
        actor_tenant="HQ",
        known=ОХВАТЫ,
    )
    assert исход == people.Outcome("role.scope", 400)
    assert set(TEXTS[f"users.{исход.key}"]) == {"ru", "en"}


def test_мост_ролей_снят() -> None:
    assert not hasattr(accounts, "ROLES")
    assert not hasattr(accounts, "LEGACY_ROLES")
    assert not [ключ for ключ in TEXTS if ключ.startswith("nav.role.")]
```

- [ ] **Step 2: Прогнать — ожидается FAIL**

Run: `.venv/bin/pytest tests/test_web_people_rights.py -q`
Expected: FAIL — `change_role() got an unexpected keyword argument 'known'`, у вызова нет `journal`, `accounts.ROLES` ещё есть, ключи `nav.role.*` ещё есть.

- [ ] **Step 3: Минимальная реализация**

`src/web/app.py` (импорты `from collections.abc import Mapping`, `from src.db import roles as roles_door`, `from src.db.cross_space import Entry, entry_for`, `from src.domain.permissions import can, scope_of_tenant`; `ROLE_HQ_ADMIN` и `canonical_role` из этого импорта убрать — их звал только `_is_hq_admin`) — вместо `_hq_admin_only` и `_is_hq_admin`:

```python
def _people_permit(target_tenant: str) -> tuple[str, int] | None:
    """Правка людей: мост до блока 2 (экран — только УК) и `people.manage` над пространством.

    Админ страны получил бы через экран перечень людей всех пространств — до
    блока 2 (свои люди страны) экран правки ему закрыт целиком.
    """
    if canonical_tenant(auth.current_tenant()) != HQ_TENANT:
        return guard.forbidden()
    return guard.permit("people.manage", target_tenant)


def _people_journal(target_tenant: str, login: str) -> Entry | None:
    """Строка журнала, если человек УК правит человека партнёра."""
    return entry_for(
        auth.current_actor(),
        object_tenant=target_tenant,
        action="people.manage",
        object_ref=f"web_user:{login.strip().lower()}",
    )
```

`_правка_человека` и маршруты правки:

```python
    def _правка_человека(
        действие: Callable[[str, str], people.Outcome],
    ) -> FlaskResponse | tuple[str, int]:
        """Общее у правки роли и почты: происхождение, пространство из формы, право.

        Пространство — из строки учётки в перечне, сверенное с заведёнными:
        человека правят там, где он живёт, а не в пространстве админа.
        """
        refuse_foreign_origin()
        логин = (request.form.get("login") or "").strip()
        try:
            пространство = _пространство_из_формы()
        except DbError:
            return _страница_учёток(edit=people.Outcome("edit.failed", 503), code=503)
        if пространство is None or not логин:
            return _страница_учёток(edit=people.Outcome("edit.space", 400), code=400)
        отказ = _people_permit(пространство)
        if отказ is not None:
            return отказ
        исход = действие(логин, пространство)
        return _страница_учёток(edit=исход, code=исход.status)

    @app.post(f"{users_path}/role")
    @guard.action("people.manage", object_in_route=True)
    def user_role() -> FlaskResponse | tuple[str, int]:
        """Назначить роль человеку (#399): роль из ролей его пространства; свою — нельзя."""
        вошедший = auth.current_account()
        роль = (request.form.get("role") or "").strip()
        return _правка_человека(
            lambda логин, пространство: people.change_role(
                login=логин,
                tenant=пространство,
                role=роль,
                actor_login=вошедший.login if вошедший else "",
                actor_tenant=вошедший.tenant if вошедший else "",
                known=известные,
                journal=_people_journal(пространство, логин),
            )
            if (известные := _known_roles()) is not None
            else people.Outcome("role.failed", 503)
        )
```

Роли пространства читаются из базы до `people.change_role`, и её `except DbError` отказ этого чтения не ловит. Поэтому — функция модуля и ветка в лямбде:

```python
def _known_roles() -> Mapping[str, str] | None:
    """Код роли → охват роли из таблицы `roles`; `None` — база не ответила."""
    try:
        return {р.code: р.scope for р in roles_door.list_roles()}
    except DbError:
        return None
```

В `user_role` лямбда зовёт `известные = _known_roles()` и при `None` возвращает `people.Outcome("role.failed", 503)`, иначе `people.change_role(..., known=известные, journal=...)`.

`user_email` — тот же декоратор, в вызов `people.change_email(...)` добавить `journal=_people_journal(пространство, логин)`.

`add_user` и `disable_user` — декоратор `@guard.action("people.manage", object_in_route=True)`; строки `отказ = _hq_admin_only()` / `if отказ is not None: return отказ` удаляются; сразу после того, как пространство из формы прочитано и не `None`, — `отказ = _people_permit(пространство)` и `if отказ is not None: return отказ`; двери получают `journal=_people_journal(пространство, логин)` (`accounts.add(..., journal=...)`, `accounts.disable(..., journal=...)`). `refuse_foreign_origin()` остаётся там, где стоит сейчас, — до чтения формы.

`bot_unlink`:

```python
    @app.post(f"{users_path}/bot-unlink")
    @guard.action("people.manage", object_in_route=True)
    def bot_unlink() -> FlaskResponse | tuple[str, int]:
        """Отвязать бота: свою привязку — каждый, чужую — по `people.manage` над её пространством."""
        refuse_foreign_origin()
        вошедший = auth.current_account()
        if вошедший is None:
            raise RuntimeError("отвязка бота без вошедшего: маршрут прошёл мимо заслона")
        чей = (request.form.get("user_id") or "").strip() or вошедший.id
        журнал: Entry | None = None
        if чей == вошедший.id:
            guard.mark_own()
        else:
            try:
                учётка = next((у for у in accounts.everyone(tenant=None) if у.id == чей), None)
            except DbError:
                return _страница_учёток(outcome="bot_unlink_failed", code=503)
            if учётка is None:
                return _страница_учёток(outcome="bot_unlink_missing", code=400)
            отказ = _people_permit(учётка.tenant)
            if отказ is not None:
                return отказ
            журнал = _people_journal(учётка.tenant, учётка.login)
        try:
            отвязано = bot_links.unbind(чей, journal=журнал)
        except DbError:
            return _страница_учёток(outcome="bot_unlink_failed", code=503)
        return _страница_учёток(outcome="bot_unlinked" if отвязано else "bot_unlink_missing")
```

`_страница_учёток`: `управляет = _hq_admin_only() is None` →

```python
        управляет = (
            canonical_tenant(auth.current_tenant()) == HQ_TENANT
            and can(auth.current_actor(), "people.manage", HQ_TENANT).allowed
        )
```

вместо `roles=accounts.ROLES` (`lang = _lang(conf)`; чтение ролей — внутри того же `try`, что перечень людей, отказ базы → `перечень_известен = False`, `роли = ()`):

```python
        роли = roles_door.list_roles() if управляет else ()
        подписи = {р.code: (р.name_en if lang == "en" else р.name_ru) for р in роли}
        варианты = {
            охват: tuple(р.code for р in роли if р.scope == охват) for охват in ("hq", "country")
        }
```

в шаблон — `role_names=подписи`, `role_options=варианты`, `scope_of=scope_of_tenant`.

`src/web/people.py` (импорты `from collections.abc import Mapping`, `from src.db.cross_space import Entry`, `from src.domain.permissions import scope_of_tenant`):

```python
def change_role(
    *,
    login: str,
    tenant: str,
    role: str,
    actor_login: str,
    actor_tenant: str,
    known: Mapping[str, str],
    journal: Entry | None = None,
) -> Outcome:
    """Назначить роль из ролей пространства. Свою — нельзя: снять с себя админа значит закрыть экран людей."""
    охват = known.get(role)
    if охват is None:
        return Outcome("role.unknown", 400)
    if охват != scope_of_tenant(tenant):
        return Outcome("role.scope", 400)
    if is_self(login=login, tenant=tenant, actor_login=actor_login, actor_tenant=actor_tenant):
        return Outcome("role.self", 400)
    try:
        прежняя = accounts.reassign_role(login, tenant=tenant, role=role, journal=journal)
    except DbError:
        return Outcome("role.failed", 503)
```

Хвост функции после `прежняя = ...` (`edit.missing`, запись в журнал приложения, `Outcome("role.ok", 200)`) — как сейчас. `change_email` — параметр `journal: Entry | None = None`, вызов `accounts.set_email(login, tenant=tenant, email=почта or None, journal=journal)`.

`src/web/accounts.py`: `add(login, *, tenant, role=ROLE_AUDITOR, journal=None)` → `create_account(..., role=role, journal=journal)`; `disable(login, *, tenant, journal=None)` → `disable_account(login, tenant=tenant, journal=journal)`; `reassign_role` и `set_email` модуль реэкспортирует из `src.db.web_access` как есть (`__all__`) — параметр `journal` приходит вместе с дверью, обёрток не нужно. `ROLES`, `LEGACY_ROLES` — из импорта и `__all__` убрать.

Двери `src/db/web_access.py` (импорт `from .cross_space import Entry, record`) — строка журнала только если действие состоялось, на том же подключении, до выхода из `with _managing(...)`:
- `create_account`: после `row = cur.fetchone()` — `record(conn, journal)`.
- `reassign_role`: `строка = cur.fetchone()`, затем `if строка is not None: record(conn, journal)`.
- `set_email`: перед `return True` внутри `with` — `record(conn, journal)`.
- `disable_account`: `отключено = cur.rowcount > 0`, `if отключено: record(conn, journal)`, `return отключено`.
- `ROLES` и `LEGACY_ROLES` удалить; `_checked_role` (Task 6) их не зовёт.

`src/db/bot_links.py`:

```python
def unbind(user_id: str, *, journal: Entry | None = None) -> bool:
    with _connected("отвязать бота") as conn, conn.cursor() as cur:
        cur.execute(_UNBIND_USER_SQL, (user_id,))
        отвязано = cur.rowcount > 0
        if отвязано:
            record(conn, journal)
        return отвязано
```

(докстринг `unbind` — оставить сегодняшний; импорт `from .cross_space import Entry, record`.)

`src/web/texts.py` — удалить двенадцать ключей из Files; добавить:

```python
    "users.role.scope": {
        "ru": "Эта роль не для пространства человека: УК — роли УК, стране — роли страны.",
        "en": "This role does not fit the person's space: HQ takes HQ roles, a country takes country roles.",
    },
    "users.roles.hq": {"ru": "Роли УК", "en": "HQ roles"},
    "users.roles.country": {"ru": "Роли страны", "en": "Country roles"},
```

`src/web/templates/users/index.html`:
- ~120: `{{ t('users.role.' ~ account.role) }}` → `{{ account.role_name_en if lang == 'en' else account.role_name_ru }}`;
- ~203–205:
  ```jinja
                      {% for код in role_options[scope_of(человек.tenant)] %}
                        <option value="{{ код }}"{% if код == человек.role %} selected{% endif %}>{{ role_names[код] }}</option>
                      {% endfor %}
  ```
- ~210: `{{ t('users.role.' ~ человек.role) }}` → `{{ role_names.get(человек.role, человек.role) }}`;
- ~284–286:
  ```jinja
          <optgroup label="{{ t('users.roles.hq') }}">
            {% for код in role_options['hq'] %}<option value="{{ код }}">{{ role_names[код] }}</option>{% endfor %}
          </optgroup>
          <optgroup label="{{ t('users.roles.country') }}">
            {% for код in role_options['country'] %}<option value="{{ код }}">{{ role_names[код] }}</option>{% endfor %}
          </optgroup>
  ```
  Внешний ключ проверяет только, что роль заведена, а не что она того же охвата. Поэтому `add_user` после `_people_permit` сверяет охват так же, как `change_role`:
  ```python
        роль = request.form.get("role") or accounts.ROLE_AUDITOR
        известные = _known_roles()
        if известные is None:
            return _страница_учёток(outcome="add_failed", code=503)
        if роль != accounts.ROLE_AUDITOR and известные.get(роль) != scope_of_tenant(пространство):
            return _страница_учёток(outcome="add_failed", code=400)
  ```
  (`ROLE_AUDITOR` — пустой выбор: `_checked_role` переводит его в самую узкую роль пространства.)

`src/web/templates/base.html` ~141: `<small>{{ t('nav.role.' ~ account.role) }}</small>` → `<small>{{ account.role_name_en if lang == 'en' else account.role_name_ru }}</small>`.

- [ ] **Step 4: Прогнать — ожидается PASS; веб и двери**

Run: `.venv/bin/pytest tests/test_web_people_rights.py -q` → PASS.
Run: `.venv/bin/pytest tests/test_web_*.py -q` → зелёное после замены в `tests/test_web_users_access.py` и `tests/test_web_users.py` ролей формы `admin`/`auditor` на коды (`country_admin`/`country_staff` для `GE`, `hq_admin`/`hq_staff` для `HQ`), подмены `roles_door.list_roles` четырьмя ролями и подменённых `reassign_role`/`disable`/`set_email`, принимающих `journal`. Красное вне этих двух наборов — регрессия.
Run: `make test-honest ARGS="tests/test_db_web_access.py tests/test_db_bot_links.py tests/test_db_cross_space.py -q -rs"` → PASS, `SKIPPED` нет.
Run: `make lint types dead` → чисто (`_hq_admin_only`, `_is_hq_admin`, `ROLES`, `LEGACY_ROLES` вызовов не имеют).

Негативный прогон: в `reassign_role` временно писать `record(conn, journal)` до проверки `строка is not None` — тест двери «правка несуществующей учётки журнала не пишет» в `tests/test_db_web_access.py` (дописать: `reassign_role("нет-такого", tenant="GE", role="country_staff", journal=Entry(...))` → `None`, строк в `cross_space_actions` нет) должен упасть; вернуть.

- [ ] **Step 5: Документация** — `docs/12-web-admin.md`, строка ~49:

```
| Назначить человеку роль (из ролей его пространства: УК — `hq_admin`/`hq_staff`, страна — `country_admin`/`country_staff`) и задать или снять почту для входа через Google — человек УК с правом `people.manage`, людям любого пространства; правка человека партнёра пишется в журнал `cross_space_actions`. До блока 2 админ страны не правит никого | `/users` → `POST /users/role`, `POST /users/email` | `src/web/people.py` → `src/db/web_access.py: reassign_role`, `set_email` |
```

- [ ] **Step 6: Коммит и пуш**

```bash
git add src/web/app.py src/web/people.py src/web/accounts.py src/db/web_access.py src/db/bot_links.py \
  src/web/templates/users/index.html src/web/templates/base.html src/web/texts.py \
  tests/test_web_people_rights.py tests/test_web_users_access.py tests/test_web_users.py \
  tests/test_db_web_access.py docs/12-web-admin.md
git commit -m "feat: правка людей через can, роли пространства из базы, журнал УК; мост ролей снят

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

### Task 12: Веб — тест полноты на настоящем приложении

**Files:**
- Create: `tests/test_web_action_coverage.py`

**Interfaces:**
- Consumes: `guard.uncovered`, `guard.ACTIONS_ATTR`, `guard.EXEMPT_ENDPOINTS`, `guard.WRITING_GETS` (Task 7); `web_harness.собрать`.
- Produces: тест полноты веба (закрывает #271 со стороны прав).

- [ ] **Step 1: Написать тест**

```python
# tests/test_web_action_coverage.py
"""Каждый пишущий маршрут веба проходит через can с кодом каталога (спека, «Проверка»)."""

from __future__ import annotations

from web_harness import собрать

from src.domain.permissions import ACTION_CODES
from src.web import guard


def test_нет_пишущих_маршрутов_без_кода() -> None:
    assert guard.uncovered(собрать(tenant="HQ")) == []


#: Действия каталога, у которых в вебе нет маршрута: проверку ведёт бот,
#: фразы и подключение MCP — свои поверхности, пространства и роли — блоки 2–3.
#: Новое действие в каталоге без маршрута веба — сюда осознанно, со строкой причины.
БЕЗ_ВЕБА = frozenset(
    {"inspection.conduct", "phrases.manage", "mcp.connect", "space.manage", "roles.manage"}
)


def test_каждое_действие_каталога_либо_на_маршруте_либо_названо() -> None:
    app = собрать(tenant="HQ")
    коды = {
        код
        for view in app.view_functions.values()
        for код in getattr(view, guard.ACTIONS_ATTR, ())
    }
    assert ACTION_CODES - коды == БЕЗ_ВЕБА


def test_исключения_существуют_как_маршруты() -> None:
    app = собрать(tenant="HQ")
    assert set(guard.EXEMPT_ENDPOINTS) <= set(app.view_functions)
    assert guard.WRITING_GETS <= set(app.view_functions)


def test_проверка_полноты_ловит_новый_маршрут_без_кода() -> None:
    app = собрать(tenant="HQ")

    @app.post("/_новый")
    def _новый() -> str:
        return "забыли код"

    assert guard.uncovered(app) == ["_новый (/_новый)"]
```

- [ ] **Step 2: Прогнать**

Run: `.venv/bin/pytest tests/test_web_action_coverage.py -q`
Expected: PASS (Tasks 8, 10, 11 сделаны). Код каталога, объявленный маршрутом, но не из каталога, роняет `guard.action` ещё при сборке (`require_action`, Task 1), поэтому отдельной проверки «коды ⊆ каталог» нет. FAIL `test_каждое_действие_каталога_либо_на_маршруте_либо_названо` называет разницу множеств: действие потеряло маршрут — вернуть декоратор; новое действие без веба — дописать в `БЕЗ_ВЕБА` с причиной. FAIL `test_нет_пишущих_маршрутов_без_кода` перечисляет эндпоинты без кода: каждому — код по таблицам Tasks 8, 10, 11, либо строка в `guard.EXEMPT_ENDPOINTS` с причиной, если операция личная.

- [ ] **Step 3: Отрицательный прогон**

Снять декоратор `@guard.action("checklist.edit")` у `methodology_add` в `src/web/app.py`, прогнать `PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest tests/test_web_action_coverage.py -q`.
Expected: FAIL `test_нет_пишущих_маршрутов_без_кода` с текстом `methodology_add (/admin/items)`. Второй отрицательный прогон: снять `@guard.action("plan.submit")` у `plans_upload` — `test_каждое_действие_каталога_либо_на_маршруте_либо_названо` падает с `{'plan.submit'}` в разнице. Вернуть декораторы (`git diff src/web/app.py` пуст), прогнать снова — PASS.

- [ ] **Step 4: Коммит и пуш**

```bash
git add tests/test_web_action_coverage.py
git commit -m "test: полнота прав веба — каждый пишущий маршрут с кодом каталога

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

### Task 13: Бот — роль в привязке, автор проверки, заслон роутеров, тест полноты

| Роутер | Код |
|---|---|
| `start`, `edit`, `records`, `resend`, `finish`, `info`, `record`, `correct`, `material` | `inspection.conduct` |
| `mcp` | `mcp.connect` (поверх круга `mcp_admins`, который остаётся до блока 3) |
| `help`, `lang`, `version`, `stops`, `fallback` | исключения: чтение или личная настройка (расхождение 7) |

Заведение пиццерии на старте проверки работает как сейчас (D310): `can(actor, "unit.create", space)` даёт «да» людям УК и путь совместимости (`hq_staff`), «нет» — людям страны, ровно как `may_add_units`. Снятие этого пути — #527.

**Files:**
- Modify: `src/db/bot_links.py` — `Binding` (~99), все четыре запроса привязки: `_RESOLVE_BY_TELEGRAM_SQL` (~61), `_RESOLVE_BY_USER_SQL` (~66), `_STANDING_SQL` (~74), `_LIVE_BINDINGS_SQL` (~83); `_binding(row)`, `standing` (~196: индекс `live`)
- Modify: `src/bot/access.py` — `ACTOR_KEY`, `_grants_from_db`, `AccessMiddleware._space_of` → `_actor_of`, `__call__` (~144–206); новые `ActionMiddleware`, `guard_router`, `uncovered_routers`, `EXEMPT_ROUTERS`
- Modify: `src/bot/app.py` — `build_dispatcher` (~201–243): роутеры через `guard_router`
- Modify: `src/bot/routers/start.py` — `may_add_units(space)` (~363, ~392) → `can(actor, "unit.create", space)`; вызов `domain.start_inspection` (~539–565): `author_user_id`
- Modify: `src/bot/unit_pick.py` (~26), `src/domain/tenants.py` (~25) — `may_add_units` удалить; ссылки на неё в докстрингах `src/web/unit_add.py` (~6) и `src/db/directory.py` (~362) → `can(..., "unit.create", ...)` (Task 8 уже снял вызов в `unit_add.may_add_in`)
- Modify (удалить тесты `may_add_units` — поведение держат таблица прав Task 2 и `can`): `tests/test_domain_unit_new.py` — `test_заводит_только_уК` (~67–69) и импорт (~13); `tests/test_bot_start_space.py` — `test_партнёр_не_заводит_пиццерию` (~60–63)
- Modify: `src/bot/texts.py` — `access.forbidden` (ru/en)
- Modify: `tests/conftest.py` — фикстура `_бот_без_базы_не_знает_привязок` (~345)
- Create: `tests/test_bot_action_coverage.py`
- Modify: тесты, строящие `Binding(...)`: `tests/test_bot_access.py`, `tests/test_bot_start_router.py`, `tests/test_bot_start_space.py`, `tests/test_web_bot_link.py` — добавить `role=`, `grants=` (перед правкой повторить `grep -rln "Binding(" tests`: список на 07.10.2026)
- Modify: `docs/furca/blocks/bot.md` (раздел «Что блок предоставляет», после `Binding`)

**Interfaces:**
- Consumes: `Actor`, `can`, `DEFAULT_MATRIX`, `ROLE_HQ_STAFF`, `Grants` (Tasks 1–2); `roles.grants_of`, `roles.grants_column`, `roles.grants_from_row` (Task 6); `start_inspection(..., author_user_id=...)` (Task 5).
- Produces:
  - `Binding(telegram_id, user_id, login, tenant, bound_at, role: str = "", grants: Grants = <пусто>)`.
  - `access.ACTOR_KEY = "actor"`; обработчики принимают `actor: Actor`.
  - `access.ActionMiddleware(action: str)`; `access.guard_router(router: Router, action: str) -> Router`; `access.EXEMPT_ROUTERS: Mapping[str, str]`; `access.uncovered_routers(dispatcher: Dispatcher) -> list[str]`.

- [ ] **Step 1: Написать падающий тест**

```python
# tests/test_bot_action_coverage.py
"""Бот: каждая команда проходит через can; человек без привязки — сотрудник УК."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from aiogram import Router
from aiogram.types import Chat, Message, User
from bot_harness import make_bot

from src.bot.access import (
    ACTOR_KEY,
    AccessMiddleware,
    ActionMiddleware,
    BindingCache,
    guard_router,
    uncovered_routers,
)
from src.bot.app import build_dispatcher
from src.bot.config import BotSettings
from src.db.bot_links import Binding, Standing
from src.domain.permissions import DEFAULT_MATRIX, Actor

НАСТРОЙКИ = BotSettings(token="123456:TEST", allowed_ids=frozenset({501}), mode="polling")


def _msg(user_id: int) -> Message:
    bot, _ = make_bot()
    return Message(
        message_id=1,
        date=datetime.now(UTC),
        chat=Chat(id=user_id, type="private"),
        from_user=User(id=user_id, is_bot=False, first_name="Т"),
        text="/finish",
    ).as_(bot)


async def _данные(mw: AccessMiddleware, user_id: int) -> dict[str, Any] | None:
    увидено: list[dict[str, Any]] = []

    async def handler(_e: Any, data: dict[str, Any]) -> None:
        увидено.append(dict(data))

    await mw(handler, _msg(user_id), {})
    return увидено[0] if увидено else None


@pytest.mark.asyncio
async def test_путь_совместимости_получает_права_hq_staff() -> None:
    mw = AccessMiddleware(frozenset({501}), bindings=None, roster=None)
    данные = await _данные(mw, 501)
    assert данные is not None
    человек: Actor = данные[ACTOR_KEY]
    assert (человек.tenant, человек.role, человек.user_id) == ("HQ", "hq_staff", None)
    assert dict(человек.grants) == dict(DEFAULT_MATRIX["hq_staff"])


@pytest.mark.asyncio
async def test_привязка_приносит_роль_права_и_учётку() -> None:
    привязка = Binding(
        telegram_id=502, user_id="u-502", login="anna", tenant="GE", bound_at=datetime.now(UTC),
        role="country_staff", grants=DEFAULT_MATRIX["country_staff"],
    )
    кэш = BindingCache(standing=lambda _tg: Standing.live(привязка))
    данные = await _данные(AccessMiddleware(frozenset(), bindings=кэш, roster=None), 502)
    assert данные is not None
    assert (данные[ACTOR_KEY].role, данные[ACTOR_KEY].user_id) == ("country_staff", "u-502")


@pytest.mark.asyncio
async def test_без_права_обработчик_не_зовётся() -> None:
    вызван: list[bool] = []

    async def handler(_e: Any, _d: dict[str, Any]) -> None:
        вызван.append(True)

    человек = Actor(tenant="GE", role="ghost", grants={})
    await ActionMiddleware("inspection.conduct")(handler, _msg(503), {ACTOR_KEY: человек, "space": "GE"})
    assert вызван == []


def test_каждый_роутер_с_кодом_или_в_исключениях() -> None:
    assert uncovered_routers(build_dispatcher(НАСТРОЙКИ)) == []


def test_полнота_ловит_роутер_без_кода() -> None:
    dp = build_dispatcher(НАСТРОЙКИ)
    dp.include_router(Router(name="новый"))
    assert uncovered_routers(dp) == ["новый"]


def test_guard_router_ставит_заслон_на_сообщения_и_кнопки() -> None:
    роутер = guard_router(Router(name="t"), "inspection.conduct")
    assert any(isinstance(m, ActionMiddleware) for m in роутер.message.middleware)
    assert any(isinstance(m, ActionMiddleware) for m in роутер.callback_query.middleware)
```

Дописать в `tests/test_bot_start_space.py` (набор старта проверки; хелперы `feed`, `make_bot` из `bot_harness` уже используются там) тест автора: привязанный человек проходит мастер, и `domain.start_inspection` получает `author_user_id` его учётки; человек пути совместимости — пустую строку. Подменить `src.bot.routers.start.domain.start_inspection` записывающей функцией и проверить `записано[0]["author_user_id"] == "u-502"` и `== ""` соответственно (`test_старт_проверки_пишет_автора_привязки`, `test_старт_без_привязки_без_автора`).

- [ ] **Step 2: Прогнать — ожидается FAIL**

Run: `.venv/bin/pytest tests/test_bot_action_coverage.py tests/test_bot_start_space.py -q`
Expected: FAIL — `ImportError: cannot import name 'ACTOR_KEY' from 'src.bot.access'`.

- [ ] **Step 3: Минимальная реализация**

`src/db/bot_links.py` (импорты `from types import MappingProxyType`, `from src.domain.permissions import Grants`, `from .roles import grants_column, grants_from_row`): `Binding` дописать поля `role: str = ""` и `grants: Grants = MappingProxyType({})`. Права роли — тем же подзапросом, что у сессии веба (Task 6), одна строка на все четыре запроса:

```python
#: Колонки привязки: учётка, её роль и права роли — одним запросом (спека: права
#: приезжают вместе с опознанием).
_BINDING_COLUMNS = (
    f"b.telegram_id, u.id, u.login, u.tenant_code, b.bound_at, u.role, {grants_column('u.role')}"
)
_RESOLVE_BY_TELEGRAM_SQL = f"""
    select {_BINDING_COLUMNS}
      from bot_bindings b join web_users u on u.id = b.user_id
     where b.unbound_at is null and u.disabled_at is null and b.telegram_id = %s
"""  # noqa: S608 — колонки собраны из констант модуля
```

`_RESOLVE_BY_USER_SQL`, `_STANDING_SQL`, `_LIVE_BINDINGS_SQL` — так же: `select {_BINDING_COLUMNS}` вместо перечня колонок, f-строка с тем же `noqa`; у `_STANDING_SQL` признак `live` остаётся последней колонкой (`select {_BINDING_COLUMNS},\n (b.unbound_at is null and u.disabled_at is null) as live`), поэтому в `standing` `row[5]` → `row[7]`. `_binding(row)` дописывает `role=str(row[5])`, `grants=grants_from_row(row[6])`.

`src/bot/access.py`:

```python
from aiogram import Dispatcher, Router

from src.domain.permissions import DEFAULT_MATRIX, ROLE_HQ_STAFF, Actor, Grants, can

#: Ключ субъекта прав в `data` апдейта.
ACTOR_KEY = "actor"

#: Роутеры без пишущей операции — с причиной (расхождение 7 плана блока 1).
EXEMPT_ROUTERS: Mapping[str, str] = {
    "help": "справка — чтение",
    "lang": "язык интерфейса — личная настройка",
    "version": "версия — чтение",
    "stops": "счётчик отказов — чтение, круг админов",
    "fallback": "ответ на непонятное — без записи",
}

_GUARD_ATTR = "required_action"


def _grants_from_db(role: str) -> Grants:
    """Права роли пути совместимости из базы; база молчит — права по умолчанию.

    Путь совместимости (`ALLOWED_TELEGRAM_IDS`, `roster.json`) работает и без
    базы — так задумано (D233). Отказ базы здесь не закрывает бот, а даёт права
    `hq_staff` из `DEFAULT_MATRIX` — их же засевает `0038` — и пишет
    предупреждение. Отдельной функцией модуля — её подменяют тесты бота без базы.
    """
    from src.db.errors import DbError
    from src.db.roles import grants_of

    try:
        return grants_of(role)
    except DbError:
        logger.warning("права роли %s из базы не прочитаны — беру права по умолчанию", role)
        return DEFAULT_MATRIX[ROLE_HQ_STAFF]
```

`AccessMiddleware._space_of` переименовать в `_actor_of(user_id) -> Actor | None`: живая привязка → `Actor(tenant=canonical_tenant(b.tenant), role=b.role, grants=b.grants, user_id=b.user_id)`; путь совместимости → `Actor(tenant=HQ_TENANT, role=ROLE_HQ_STAFF, grants=_grants_from_db(ROLE_HQ_STAFF))` (учётки нет: `user_id=None`, проверки такого человека ложатся без автора); прочие ветки — `None`, как сейчас. В `__call__`: `actor = await asyncio.to_thread(self._actor_of, user_id)`; `data[SPACE_KEY] = actor.tenant`; `data[ACTOR_KEY] = actor`.

```python
class ActionMiddleware(BaseMiddleware):
    """Внутренняя мидлварь роутера: обработчик зовётся, только если роль может действие."""

    def __init__(self, action: str) -> None:
        self.action = action

    async def __call__(
        self, handler: Handler, event: TelegramObject, data: dict[str, Any]
    ) -> Any:
        человек = data.get(ACTOR_KEY)
        if not isinstance(человек, Actor) or not can(человек, self.action, человек.tenant):
            logger.info("права бота: отказ %s для %s", self.action, getattr(человек, "tenant", None))
            await _refuse(event, "access.forbidden")
            return None
        return await handler(event, data)


def guard_router(router: Router, action: str) -> Router:
    """Поставить заслон действия на сообщения и кнопки роутера."""
    заслон = ActionMiddleware(action)
    router.message.middleware(заслон)
    router.callback_query.middleware(заслон)
    setattr(router, _GUARD_ATTR, action)
    return router


def uncovered_routers(dispatcher: Dispatcher) -> list[str]:
    """Роутеры без заслона действия и без причины-исключения — по именам."""
    return sorted(
        r.name
        for r in dispatcher.sub_routers
        if not getattr(r, _GUARD_ATTR, None) and r.name not in EXEMPT_ROUTERS
    )
```

Отказ — и на сообщение, и на кнопку: `_answer` (~217) отвечает только сообщениям, а заслон стоит и на `callback_query`. Помощник по образцу отказа чужого пространства (~265–269), и тот отказ переводится на него же:

```python
async def _refuse(event: TelegramObject, key: str) -> None:
    """Отказ на языке чата: кнопке — всплывающим окном, сообщению — ответом."""
    chat = _chat_of(event)
    if chat is None:
        return
    текст = t(key, chat_ui_lang(chat.id))
    if isinstance(event, CallbackQuery):
        await event.answer(текст, show_alert=True)
    elif isinstance(event, Message):
        await event.answer(текст)
```

`src/bot/app.py`, `build_dispatcher`: каждый `dispatcher.include_router(build_X_router(...))` для роутеров из таблицы — `dispatcher.include_router(guard_router(build_X_router(...), "inspection.conduct"))`; `mcp` — `guard_router(build_mcp_router(settings), "mcp.connect")`. Имена роутеров (`Router(name=...)` в `src/bot`, на 07.10.2026): `correct`, `edit`, `fallback`, `finish`, `help`, `info`, `lang`, `material`, `mcp`, `record`, `records`, `resend`, `start`, `stops`, `version` — пятнадцать, совпадают с таблицей задачи; новое имя покажет `test_каждый_роутер_с_кодом_или_в_исключениях`.

`src/bot/routers/start.py`: обработчики, где стоит `may_add_units(space)`, принимают `actor: Actor`; условие → `if not can(actor, "unit.create", space):` (текст отказа `start.unit_new_partner` тот же). Обработчик выбора языка, который зовёт `domain.start_inspection`, принимает `actor: Actor` и передаёт после `checklist_code=...`:

```python
                # Учётка, которая заносит проверку (D311): по ней «свои». Без
                # привязки (путь совместимости) автора нет — проверку правит админ.
                author_user_id=actor.user_id or "",
```

`src/bot/unit_pick.py`: убрать реэкспорт `may_add_units`. `src/domain/tenants.py`: удалить `may_add_units`. Удалить `tests/test_domain_unit_new.py::test_заводит_только_уК` с импортом и `tests/test_bot_start_space.py::test_партнёр_не_заводит_пиццерию`; докстринги `unit_add.py` (~6) и `directory.py` (~362) — ссылка на `can(..., "unit.create", ...)`. Проверка: `grep -rn "may_add_units" src tests` пуст.

`src/bot/texts.py`:

```python
    "access.forbidden": {
        "ru": "Этого вашей роли не разрешено. Права выдаёт администратор в вебе.",
        "en": "Your role is not allowed to do this. An administrator grants rights in the web app.",
    },
```

`tests/conftest.py`, в фикстуре `_бот_без_базы_не_знает_привязок` — вторая подмена:

```python
    from src.domain.permissions import DEFAULT_MATRIX

    monkeypatch.setattr(
        "src.bot.access._grants_from_db", lambda role: DEFAULT_MATRIX.get(role, {})
    )
```

Тесты с `Binding(...)` без роли (четыре файла из Files) — добавить `role="hq_staff", grants=DEFAULT_MATRIX["hq_staff"]` для `HQ` и `role="country_staff", grants=DEFAULT_MATRIX["country_staff"]` для страны.

- [ ] **Step 4: Прогнать — ожидается PASS; бот целиком**

Run: `.venv/bin/pytest tests/test_bot_action_coverage.py tests/test_bot_*.py -q`
Expected: PASS без переписывания прежних ожиданий: заведение пиццерии в боте не меняется (D310). Любой красный — регрессия.
Run: `make test-honest ARGS="tests/test_db_bot_links.py -q -rs"` → PASS, `SKIPPED` нет.

- [ ] **Step 5: Отрицательный прогон** — убрать `guard_router(...)` вокруг `build_finish_router(store)` в `src/bot/app.py`, `PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest tests/test_bot_action_coverage.py -q` → FAIL с именем роутера `finish`; вернуть, `git diff src/bot/app.py` без этой правки, PASS.

- [ ] **Step 6: Документация** — `docs/furca/blocks/bot.md`, после описания `Binding`:

```
# Binding(..., role, grants): роль учётки и её права (код → own/all) — тем же запросом
# access.ACTOR_KEY → Actor(tenant, role, grants, user_id) в data апдейта; путь
#   совместимости (ALLOWED_TELEGRAM_IDS, roster.json) — Actor(HQ, hq_staff, права hq_staff,
#   без учётки)
# старт проверки: author_user_id = учётка привязки (D311); без привязки — пусто, проверка
#   ложится без автора и под «свои» не попадает
# guard_router(router, action): внутренняя мидлварь ActionMiddleware — обработчик
#   зовётся, только если can(actor, action, actor.tenant); отказ — access.forbidden
# Коды роутеров: inspection.conduct — start, edit, records, resend, finish, info, record,
#   correct, material; mcp.connect — mcp (поверх круга mcp_admins до блока 3);
#   исключения — access.EXEMPT_ROUTERS. Полноту держит tests/test_bot_action_coverage.py
# заведение пиццерии на старте — can(actor, "unit.create", space): люди УК (D310),
#   временный путь до #527
```

- [ ] **Step 7: Коммит и пуш**

```bash
git add src/db/bot_links.py src/bot/access.py src/bot/app.py src/bot/routers/start.py src/bot/unit_pick.py \
  src/domain/tenants.py src/web/unit_add.py src/db/directory.py src/bot/texts.py \
  tests/conftest.py tests/test_bot_action_coverage.py tests/test_bot_start_space.py \
  tests/test_domain_unit_new.py tests/test_bot_access.py tests/test_bot_start_router.py \
  tests/test_web_bot_link.py docs/furca/blocks/bot.md
git commit -m "feat: бот — роль в привязке, автор проверки и can на каждом роутере

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

### Task 14: MCP — код действия у инструмента, мост прав из окружения, пространство из объекта

| Инструменты | Код |
|---|---|
| `add_checklist_item`, `edit_checklist_item`, `remove_checklist_item`, `restore_checklist_item`, `add_zone`, `remove_zone`, `set_zone_shares`, `rename_zone`, `set_route`, `set_scoring`, `add_photo_cue`, `edit_photo_cue`, `set_photo_cue_zone`, `remove_photo_cue` | `checklist.edit` |
| `publish_checklist_version` | `checklist.publish` |
| `create_checklist`, `rename_checklist`, `set_checklist_state`, `set_checklist_bot_access`, `apply_checklist` | `checklist.manage` |
| `retract_learned_phrase`, `repoint_learned_phrase` | `phrases.manage` |
| `retract_inspection` | `inspection.retract` |
| остальные (чтение, в том числе `inspection_letter`) | нет кода |

Мост блока 1: права токена = то, что уже открывает окружение, с охватом `all`. Хранилище правки методики передано (`MCP_CHECKLIST_TENANTS`) → `checklist.edit`, `checklist.publish`, `checklist.manage`, `phrases.manage`; `may_retract` (`MCP_RETRACTION_TOKENS`) → `inspection.retract`. У токена нет учётки, поэтому охват «свои» мосту недоступен; автор объекта передаётся как `None` (неизвестен) — при охвате `all` он не нужен. Тексты отказа прежние (`CHECKLIST_CLOSED`, `RETRACTION_CLOSED`).

Граница в два шага (спека: пространство объекта — из самого объекта):
1. **У входа**, до разбора аргументов, — есть ли у токена право вообще: `can(человек, spec.action, человек.tenant)`. Сохраняет сегодняшний порядок: закрытое снятие отвечает `RETRACTION_CLOSED` раньше, чем жалобой на аргументы.
2. **У объекта**, внутри того же перехвата, что вызов обработчика, — `can(человек, spec.action, пространство_объекта)`. У методики пространство объекта — то, куда `_aimed` навёл хранилище (`_space_tenant`); у снятия — пространство строки проверки (`retraction.object_tenant`). Сегодня `_aimed` и `own_reach` и так не выпускают запись из пространства токена; второй шаг делает это решением `can`, а не свойством двух функций, и ловит их будущую поломку.

**Files:**
- Modify: `src/mcp/catalogue.py` — `ToolSpec` (~66–116: поле `action` и `__post_init__`), записи инструментов из таблицы (поле `action=...`)
- Modify: `src/mcp/rpc.py` — `_bridge_actor`, `_space_tenant`, `_object_tenant`; `_call_tool` (~317–352)
- Modify: `src/mcp/retraction.py` — `object_tenant` (после `_detail`, ~130)
- Create: `tests/test_mcp_action_coverage.py`
- Modify: `docs/furca/blocks/mcp.md` — раздел «Откуда берётся арендатор» (~55)

**Interfaces:**
- Consumes: `can`, `Actor`, `require_action`, `UnknownAction`, `REACH_ALL` (Task 1); `canonical_tenant`, `HQ_TENANT`; `checklist_layout.space_of`, `DEFAULT_SPACE`; `retraction._detail`, `tools._require_inspection_id`.
- Produces:
  - `ToolSpec.action: str | None = None` (незнакомый код → `UnknownAction` при сборке каталога, через `require_action`).
  - `rpc._bridge_actor(*, tenant: str, checklist: Store | None, may_retract: bool) -> Actor`.
  - `rpc._space_tenant(store: Store, *, tenant: str) -> str` — пространство наведённого хранилища как код тенанта; чужое — `RuntimeError`.
  - `rpc._object_tenant(spec: ToolSpec, store: Store | None, arguments: Mapping[str, Any], *, tenant: str) -> str | None` — `None`: объекта нет, «не найдена» отвечает обработчик.
  - `retraction.object_tenant(ident: str, *, tenant: str) -> str | None`.
  - Сигнатура `rpc.handle(...)` не меняется.

- [ ] **Step 1: Написать падающий тест**

```python
# tests/test_mcp_action_coverage.py
"""MCP: каждый пишущий инструмент объявляет код каталога и проходит через can."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from src.domain.permissions import UnknownAction
from src.mcp import retraction, rpc
from src.mcp.catalogue import KIND_CHECKLIST, KIND_RETRACTION, TOOLS, ToolSpec

КОДЫ = {
    **{
        имя: "checklist.edit"
        for имя in (
            "add_checklist_item", "edit_checklist_item", "remove_checklist_item",
            "restore_checklist_item", "add_zone", "remove_zone", "set_zone_shares",
            "rename_zone", "set_route", "set_scoring", "add_photo_cue", "edit_photo_cue",
            "set_photo_cue_zone", "remove_photo_cue",
        )
    },
    "publish_checklist_version": "checklist.publish",
    **{
        имя: "checklist.manage"
        for имя in ("create_checklist", "rename_checklist", "set_checklist_state",
                    "set_checklist_bot_access", "apply_checklist")
    },
    "retract_learned_phrase": "phrases.manage",
    "repoint_learned_phrase": "phrases.manage",
    "retract_inspection": "inspection.retract",
}
СНЯТИЕ = {
    "id": "11111111-1111-1111-1111-111111111111",
    "reason": "дубль",
    "confirm_unit": "Batumi-1",
    "confirm_date": "2026-10-01",
}


def _пишет(spec: ToolSpec) -> bool:
    return spec.kind == KIND_RETRACTION or (spec.kind == KIND_CHECKLIST and spec.writes)


def _вызов(имя: str, аргументы: dict[str, Any], **транспорт: Any) -> str:
    ответ = rpc.handle(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": имя, "arguments": аргументы}},
        **транспорт,
    )
    assert ответ is not None
    return str(ответ["result"])


def test_коды_инструментов_по_таблице() -> None:
    assert {s.name: s.action for s in TOOLS if s.action is not None} == КОДЫ


def test_каждый_пишущий_с_кодом_а_читающий_без() -> None:
    for spec in TOOLS:
        assert (spec.action is not None) == _пишет(spec), spec.name


def test_незнакомый_код_падает_при_сборке() -> None:
    with pytest.raises(UnknownAction):
        ToolSpec(name="x", description="", input_schema={}, handler=lambda **_: {}, action="x.y")


def test_мост_без_права_снятия_отказывает_прежним_текстом() -> None:
    assert rpc.RETRACTION_CLOSED in _вызов("retract_inspection", СНЯТИЕ, tenant="GE")


def test_мост_с_тенантом_default_правит_как_уК() -> None:
    человек = rpc._bridge_actor(tenant="default", checklist=None, may_retract=True)
    assert человек.tenant == "HQ"
    assert dict(человек.grants) == {"inspection.retract": "all"}


def test_снятие_проверки_чужого_пространства_закрыто(monkeypatch: pytest.MonkeyPatch) -> None:
    def не_звать(**_: Any) -> dict[str, object]:
        raise AssertionError("до снятия дойти не должно")

    monkeypatch.setattr(retraction, "object_tenant", lambda *_a, **_k: "HQ")
    monkeypatch.setattr(retraction, "_retract", не_звать)
    assert rpc.RETRACTION_CLOSED in _вызов(
        "retract_inspection", СНЯТИЕ, tenant="GE", may_retract=True
    )


def test_правка_методики_наведённая_в_эталон_закрыта_партнёру(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(rpc, "_check_arguments", lambda *_a: None)
    monkeypatch.setattr(rpc, "_aimed", lambda *_a, **_k: SimpleNamespace(space="hq"))
    assert rpc.CHECKLIST_CLOSED in _вызов("add_zone", {}, tenant="GE", checklist=object())


def test_пространство_хранилища_как_тенант() -> None:
    assert rpc._space_tenant(SimpleNamespace(space="ge"), tenant="GE") == "GE"
    assert rpc._space_tenant(SimpleNamespace(space="hq"), tenant="GE") == "HQ"
    with pytest.raises(RuntimeError):
        rpc._space_tenant(SimpleNamespace(space="am"), tenant="GE")
```

- [ ] **Step 2: Прогнать — ожидается FAIL**

Run: `.venv/bin/pytest tests/test_mcp_action_coverage.py -q`
Expected: FAIL — `AttributeError: 'ToolSpec' object has no attribute 'action'`.

- [ ] **Step 3: Минимальная реализация**

`src/mcp/catalogue.py`, в `ToolSpec` после `writes` (импорт `from src.domain.permissions import require_action`):

```python
    #: Код действия каталога прав (`src/domain/permissions.py`) — у каждого
    #: пишущего инструмента; у читающего его нет. Полноту держит
    #: `tests/test_mcp_action_coverage.py`.
    action: str | None = None

    def __post_init__(self) -> None:
        if self.action is not None:
            require_action(self.action)
```

и в каждую запись из таблицы — `action="..."`.

`src/mcp/retraction.py`, после `_detail`:

```python
def object_tenant(ident: str, *, tenant: str) -> str | None:
    """Пространство проверки, которую называет вызов, — для `can` у входа (спека).

    Читается той же дорогой, что и снятие (`_detail`): чего снятие не увидит,
    того нет и здесь — `None`, и «не найдена» отвечает сам инструмент.
    """
    строка = _detail(_require_inspection_id(ident), tenant=tenant)
    return None if строка is None else строка.tenant_code
```

`src/mcp/rpc.py` (импорты `from collections.abc import Mapping`, `from src.domain.permissions import REACH_ALL, Actor, can`, `from src.domain.tenants import HQ_TENANT, canonical_tenant`, `from . import retraction`):

```python
#: Права методики, которые мост блока 1 выдаёт вместе с хранилищем правки.
_CHECKLIST_GRANTS = ("checklist.edit", "checklist.publish", "checklist.manage", "phrases.manage")


def _bridge_actor(*, tenant: str, checklist: Store | None, may_retract: bool) -> Actor:
    """Права токена в блоке 1 — ровно то, что уже открывает окружение (до ролей блока 3)."""
    права = {код: REACH_ALL for код in _CHECKLIST_GRANTS} if checklist is not None else {}
    if may_retract:
        права = {**права, "inspection.retract": REACH_ALL}
    return Actor(tenant=canonical_tenant(tenant), role=None, grants=права)


def _space_tenant(store: Store, *, tenant: str) -> str:
    """Пространство, куда `_aimed` навёл хранилище, — как код тенанта для `can`."""
    if store.space == space_of(tenant):
        return canonical_tenant(tenant)
    if store.space == DEFAULT_SPACE:
        return HQ_TENANT
    raise RuntimeError(
        f"хранилище наведено в пространство {store.space}, а токен — {tenant}: граница MCP нарушена"
    )


def _object_tenant(
    spec: ToolSpec, store: Store | None, arguments: Mapping[str, Any], *, tenant: str
) -> str | None:
    """Пространство объекта вызова — из самого объекта. `None` — объекта нет."""
    if spec.kind == KIND_RETRACTION:
        return retraction.object_tenant(str(arguments.get("id") or ""), tenant=tenant)
    if store is None:
        raise RuntimeError(f"инструмент {spec.name} объявил действие, а хранилища не получил")
    return _space_tenant(store, tenant=tenant)
```

В `_call_tool`:
- строки
  ```python
      if spec.kind == KIND_RETRACTION and not may_retract:
          return _tool_text(RETRACTION_CLOSED, failed=True)
  ```
  заменить на
  ```python
      человек = _bridge_actor(tenant=tenant, checklist=checklist, may_retract=may_retract)
      закрыто = RETRACTION_CLOSED if spec.kind == KIND_RETRACTION else CHECKLIST_CLOSED
      # Шаг 1: право вообще — до разбора аргументов, как и прежний заслон.
      if spec.action is not None and not can(
          человек, spec.action, человек.tenant, object_author=None
      ):
          return _tool_text(закрыто, failed=True)
  ```
- внутри `try`, между `прочее = ...` и `payload = spec.handler(...)`:
  ```python
          # Шаг 2: пространство объекта — из самого объекта (спека): куда навёл
          # `_aimed`, или чья строка проверки. `None` — объекта нет, ответит обработчик.
          if spec.action is not None:
              чьё = _object_tenant(spec, прочее.get("store"), arguments, tenant=tenant)
              if чьё is not None and not can(
                  человек, spec.action, чьё, object_author=None
              ):
                  return _tool_text(закрыто, failed=True)
  ```

Заслоны `KIND_CHECKLIST and checklist is None` и `KIND_CHECKLIST_SOURCE and source is None` остаются: они закрывают и чтение методики. `RuntimeError` из `_object_tenant` ловит широкий перехват ниже и отвечает отказом записи — граница не пропускает вызов и при поломке наведения.

- [ ] **Step 4: Прогнать — ожидается PASS; MCP целиком**

Run: `.venv/bin/pytest tests/test_mcp_action_coverage.py tests/test_mcp_*.py -q` → PASS (прежние наборы зелёные — тексты отказа те же).
Run: `make test-honest ARGS="tests/test_mcp_retraction.py tests/test_mcp_retraction_access.py -q -rs"` → PASS, `SKIPPED` нет: живое снятие проходит оба шага (`object_tenant` читает ту же строку, что `_detail`).

- [ ] **Step 5: Отрицательные прогоны**
- Убрать `action="checklist.edit"` у `add_zone`, `PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest tests/test_mcp_action_coverage.py -q` → FAIL с именем `add_zone`; вернуть.
- В шаге 2 `_call_tool` временно заменить `чьё` на `человек.tenant` → `test_снятие_проверки_чужого_пространства_закрыто` и `test_правка_методики_наведённая_в_эталон_закрыта_партнёру` падают; вернуть, PASS.

- [ ] **Step 6: Документация** — `docs/furca/blocks/mcp.md`, в «Откуда берётся арендатор»:

```markdown
**Права инструментов (спека «Администрирование», блок 1).** У каждого пишущего
инструмента — код действия (`ToolSpec.action`), и вызов идёт через `can`
(`src/domain/permissions.py`) дважды: у входа — есть ли у токена право вообще, у
объекта — над пространством самого объекта: куда `_aimed` навёл хранилище методики
(`rpc._space_tenant`) или чья строка проверки (`retraction.object_tenant`). До блока 3
права токена — мост из окружения с охватом «все»: хранилище правки методики
(`MCP_CHECKLIST_TENANTS`) даёт `checklist.edit`, `checklist.publish`, `checklist.manage`,
`phrases.manage`; `MCP_RETRACTION_TOKENS` — `inspection.retract`. У токена нет учётки,
поэтому охват «свои» (D311) ему недоступен. Тексты отказа прежние. Полноту держит
`tests/test_mcp_action_coverage.py`.
```

- [ ] **Step 7: Коммит и пуш**

```bash
git add src/mcp/catalogue.py src/mcp/rpc.py src/mcp/retraction.py tests/test_mcp_action_coverage.py docs/furca/blocks/mcp.md
git commit -m "feat: MCP — код действия у пишущих инструментов, can у входа и у объекта

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

### Task 15: Сдача блока — CHANGELOG, полный прогон, регрессия, смоук на стенде

**Files:**
- Modify: `CHANGELOG.md` (новая запись сверху)

**Interfaces:**
- Consumes: всё выше.
- Produces: запись журнала изменений; подтверждённые прогоны.

- [ ] **Step 1: Запись CHANGELOG** — сверху, под шапкой:

```markdown
## 2026-10-07 — ядро прав: роли, can, «свои» проверки и журнал действий УК у партнёра (блок 1 «Администрирование»)

Права теперь решает одна проверка `can` (`src/domain/permissions.py`): граница
пространств зашита в коде, а что может роль — права в базе (`roles`,
`role_permissions`, миграция `0038`). Каждый пишущий адрес веба, каждый роутер бота
и каждый пишущий инструмент MCP объявляет код действия и проходит через `can`;
полноту держат тесты. Учётки перенесены: админ и аудитор УК стали `hq_admin` и
`hq_staff`, админ и аудитор страны — `country_admin` и `country_staff`. Проверка
теперь помнит учётку, которая её занесла (миграция `0040`): сотрудники снимают,
переносят, подтверждают, правят и пишут письмо только по своим проверкам, админы —
по всем проверкам своего пространства, админ УК — по всем (D311); проверки без
автора (до этой версии и без привязки бота) правят админы. Человек УК действует над
проверками партнёра, и каждое такое действие пишется в журнал `cross_space_actions`
(миграция `0039`) той же транзакцией. Сотрудник страны больше не правит методику;
админ страны заводит свои чек-листы у себя (D311); пиццерии по-прежнему заводят люди
УК (D310). MCP работает по прежним переменным окружения и спрашивает `can` у входа и
над пространством самого объекта; роли токенам — блок 3.
Экран «Администрирование» — блок 2. Раскатка — `docs/08-deploy.md`, §8.14.
```

- [ ] **Step 2: Полный прогон**

Run: `nc -z 127.0.0.1 55432 && echo туннель-жив && make check`
Expected: `fmt lint types test dead bounds` зелёные; сторож полноты (`AUDIT_REQUIRE_DATA=1`) не жалуется на пропуски.

- [ ] **Step 3: Регрессия движка**

Run: `make regress`
Expected: `belgrade-1` 97.5%, A, D1 = 5; `belgrade-2` 97%, A, D1 = 6.

- [ ] **Step 4: Смоук на тестовом стенде MUSPELHEIM** (скилл `muspelheim`; стенд поднимается там, не на Mac)

Проверить запуском и записать в отчёт фактические ответы:
1. Накат `0038`, `0039`, `0040` на базе стенда; `make web-user ARGS="list --tenant <код>"` для каждого пространства стенда (`HQ` и каждого партнёра) — у каждой учётки код роли по таблице переноса.
2. Бот стенда: привязанный сотрудник УК начинает и сдаёт проверку → у строки `inspections` заполнен `created_by` (`select created_by is not null from inspections order by pushed_at desc limit 1`); аудитор без привязки (путь совместимости) начинает и сдаёт проверку как раньше, `created_by` пуст; заведение новой пиццерии на старте работает у человека УК (D310).
3. Вход в веб четырьмя ролями: сотрудник УК снимает свою проверку из п. 2 и получает 403 на проверке без автора; админ УК снимает проверку партнёра → строка в `cross_space_actions` (`select action_code, object_tenant, object_ref from cross_space_actions order by id desc limit 1`); сотрудник страны на «Методике» получает 403 на сохранение пункта; админ страны заводит чек-лист в своём пространстве и получает 403 на `/users/role`.
4. MCP стенда: токен из `MCP_TOKENS` с `MCP_CHECKLIST_TENANTS` правит методику своего пространства, без `MCP_RETRACTION_TOKENS` снятие отвечает прежним отказом; токен партнёра с правом снятия на проверке УК отвечает «не найдена» (её не видит `own_reach`), а не снимает.

Что проверить не удалось — назвать в отчёте прямо, не выдавать за проверенное.

- [ ] **Step 5: Коммит и пуш**

```bash
git add CHANGELOG.md
git commit -m "docs: CHANGELOG — ядро прав, блок 1 «Администрирование»

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

Раскатка на прод — отдельно, только по «да» владельца и в окно 23:00–06:59.

## Самопроверка плана

- **Покрытие спеки (только блок 1) с D310, D311:** таблицы `roles`, `role_permissions` (с охватом `own`/`all`), FK `web_users.role` — Task 3; `cross_space_actions` — Task 4; автор проверки (`inspections.created_by`, запись ботом через привязку, слив) — Tasks 5, 13; миграция ролей и перенос — Task 3; каталог и `can` двумя слоями с автором объекта — Tasks 1–2; таблица прав с измерением «автор = я / другой / неизвестен» и прогоны на сломанной матрице и сломанном `can` — Task 2; журнал в той же транзакции — Tasks 4, 9, 10, 11; веб на `can` — Tasks 7, 8, 10, 11; чек-листы страны (D311) — Task 8; бот — Task 13 (заведение пиццерии как сейчас, D310); MCP — Task 14; тест полноты веб/бот/MCP — Tasks 12, 13, 14; тест миграции «каждая учётка получает роль» — Task 3; доки `12-web-admin`, `blocks/db`, `blocks/bot`, `blocks/mcp`, `08-deploy`, CHANGELOG — Tasks 3, 4, 5, 6, 8, 11, 13, 14, 15. Вне блока 1 и не тронуто: экран «Администрирование», токен ↔ учётка, `tools/list`, `forbidden`, уход env-прав и `mcp_admins`, снятие заведения пиццерии из бота (#527). Пункт спеки «миграция: каждый живой токен сопоставлен или отозван» — блок 3.
- **Имена между задачами:** `Actor`, `Decision`, `Grants`, `require_action`, `can(..., object_author=)`, `AUTHOR_NOT_GIVEN`, `AuthorNotGiven`, `REACH_OWN`, `REACH_ALL`, `INSPECTION_OBJECT_ACTIONS`, `RULE_NOT_AUTHOR`, `DEFAULT_MATRIX`, `ROLE_SCOPES`, `canonical_role`, `scope_of_tenant`, `validate_matrix` (Tasks 1–2) → мост ролей `web_access.ROLES`, `LEGACY_ROLES`, `_checked_role(role, tenant)`, `app._is_admin`, `app._is_hq_admin` (Task 3; снимается в Tasks 10–11) → `Entry`, `entry_for`, `record` (Task 4) → `Inspection.author_user_id`, `start_inspection(..., author_user_id=)`, `InspectionRow.created_by`, `слить_проверку(..., author_user_id=)` (Task 5) → `Role`, `list_roles`, `grants_of`, `grants_column`, `grants_from_row`, `Account.grants`, `Account.role_name_ru`/`role_name_en` (Task 6) → `guard.action`, `guard.permit(..., object_author=)`, `guard.forbidden`, `guard.mark_own`, `guard.uncovered`, `auth.current_actor`, `web_harness.УЧЁТКА` (Task 7) → `journal=` у дверей проверок (Task 9) → `guard.inspection_author`, `guard.inspection_journal`, `_permit_on_inspection`, `_may`, `may_letter` (Task 10) → `_people_permit`, `_people_journal`, `_known_roles`, `change_role(..., known=, journal=)` (Task 11) → `ACTOR_KEY`, `ActionMiddleware`, `guard_router`, `uncovered_routers`, `_refuse`, `_grants_from_db` (Task 13; привязка — `grants_column`/`grants_from_row` Task 6) → `ToolSpec.action` (через `require_action`), `_bridge_actor`, `_space_tenant`, `_object_tenant`, `retraction.object_tenant` (Task 14).
- **Плейсхолдеры:** единственные подставляемые величины — отпечатки миграций в `ОТПЕЧАТКИ`; команда, которая их печатает, дана в Task 3 Step 4.
- **Review Focus:** каждой из шести строк соответствует названный тест в задаче-владельце (Tasks 6, 9, 7, 2/5/10, 13/1/14, 14).
