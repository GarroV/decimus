# Администрирование, блок 1: ядро прав — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** одна проверка прав `can(человек, действие, пространство_объекта)` — граница пространств в коде и матрица «роль × действие» в базе — стоит на каждом пишущем маршруте веба, каждой команде бота и каждом пишущем инструменте MCP. Роли по умолчанию заведены миграцией, учётки перенесены, действия УК в пространстве партнёра пишутся в журнал той же транзакцией. Поведение для людей не меняется, кроме отличий, которые даёт таблица ролей спеки.

**Architecture:** каталог действий и `can` — чистый модуль `src/domain/permissions.py` (без базы, тестируется таблицей). Роли и галочки — таблицы `roles`, `role_permissions` (миграция `0038`); права роли приезжают вместе с опознанием (сессия веба, привязка бота) одним запросом, поэтому снятая галочка действует со следующего запроса. Веб: декоратор `guard.action(...)` объявляет код на маршруте, `before_request` спрашивает `can` для маршрутов своего пространства, маршрут с объектом чужого пространства зовёт `guard.permit(код, пространство_объекта)` сам, а `after_request` роняет пишущий маршрут, который объявил объект и не спросил. Журнал `cross_space_actions` (миграция `0039`) пишется функцией `cross_space.record(conn, запись)` на том же подключении, которым дверь делает действие, до коммита. Бот: внутренняя мидлварь роутера `ActionMiddleware(код)`. MCP: у `ToolSpec` поле `action`, права токена в блоке 1 — мост из того, что уже открывает окружение (`MCP_CHECKLIST_TENANTS`, `MCP_RETRACTION_TOKENS`); роли токенам — блок 3.

**Tech Stack:** Python 3.12, Flask, aiogram 3, psycopg 3, PostgreSQL (миграции SQL раннером `src/db/migrate.py`), pytest.

**Spec:** docs/superpowers/specs/2026-10-07-administration-design.md

## Global Constraints

- Сущности связываются **кодами, никогда формулировками**: код действия (`inspection.retract`) и код роли (`hq_admin`) — ключи; подписи ролей — колонки `name_ru`/`name_en`, подписи действий — тексты по ключу. Ни одна проверка не сравнивает подпись.
- **Язык — параметр, никогда не константа.** Каждый новый текст для человека заводится на ru и en тем же коммитом (`src/web/texts.py`, `src/bot/texts.py`); тест текстов (`tests/test_web_texts.py`, `tests/test_bot_texts*.py`) обязан оставаться зелёным.
- **Оценку не считать заново.** Блок движок не трогает. Регрессия: `make regress` → `belgrade-1` 97.5%, A, 5×D1; `belgrade-2` 97.0%, A, 6×D1. Разошлось — регрессия, а не «другая версия».
- **Модель предлагает, фиксирует человек** — блок этого не касается; ни одна запись не попадает в отчёт без аудитора, как и раньше.
- **Роли по умолчанию и перенос — ровно по таблице спеки** (`admin`/`auditor` × `HQ`/страна → `hq_admin`/`hq_staff`/`country_admin`/`country_staff`). Отличия от сегодняшнего поведения, которые даёт таблица, перечислены ниже в «Расхождения со спекой»; других отличий быть не должно.
- **Граница пространств — только в `can`**, не в галочках: страна не трогает объект УК и чужую страну никогда; `unit.create`, `space.manage`, `roles.manage` у роли страны не действуют ни при какой галочке.
- **Новая пишущая операция без кода в каталоге — дефект**, его ловят тесты полноты (Task 11 — веб, Task 12 — бот, Task 13 — MCP).
- **Блок 1 не трогает**: экран «Администрирование» (блок 2), токен ↔ учётку, фильтр `tools/list`, отказ `forbidden`, уход `MCP_TOKENS`/`MCP_CHECKLIST_TENANTS`/`MCP_RETRACTION_TOKENS`/`BOT_MCP_OWNER_ID`, `mcp_admins`, `/mcp_add`/`/mcp_revoke`/`/mcp_who` (блок 3).
- **Тесты базы — на тестовой базе MUSPELHEIM, не на Postgres Mac** (D212). `.env` рабочей копии ведёт `DATABASE_ADMIN_URL` на `127.0.0.1:55432` — это туннель `localhost:55432 → muspelheim:15432`. Перед прогоном: `nc -z 127.0.0.1 55432 && echo туннель-жив`; молчит — `launchctl kickstart -k gui/$(id -u)/io.garva.mac-stands-tunnel` и повтор. Переключаться молча на `localhost:5432` нельзя; без туннеля никак — спросить владельца.
- **Точечный прогон** файла: `make test-honest ARGS="tests/<файл>.py -q -rs"` (цель экспортирует `DATABASE_URL`, `DATABASE_APP_PASSWORD`, `DATABASE_RETRACTION_PASSWORD` из `.env`). В выводе не должно быть строк `SKIPPED` у тестов с базой: пропуск = туннель или окружение, это не зелёный прогон.
- **Полный прогон** перед сдачей: `make check` (ставит `AUDIT_REQUIRE_DATA=1`: пропуск тестов базы роняет прогон, #207) и `make regress`.
- **Значения секретов не читать и не печатать**: строки `.env` берёт `Makefile`; в командах плана нет ни одного `cat .env`.
- **Коммит и пуш после каждой задачи**, `git add` только поимённо (никаких `-a` и `.`), сообщение в формате `type: описание`, последней строкой `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Ветка — текущая рабочая ветка блока, не `main`.
- **Раскатка** блока на живой продукт — только по явному «да» владельца в разговоре и в ночное окно 23:00–06:59 (скилл `deploy-window`); пуш в ветку, с которой собирается прод, тоже раскатка.
- **Миграции:** следующие номера `0038`, `0039`; раннер сам оборачивает файл в транзакцию (`begin/commit` не писать); отпечаток каждой новой миграции записывается в `tests/test_db_migrations_frozen.py` тем же коммитом; права ролей — в `tests/test_db_migrate_roles.py` (`APP_TABLE_GRANTS`, `ADMIN_TABLE_GRANTS`); функции-триггеры — `set search_path = pg_catalog, public, pg_temp` (как `0033`).

## Review Focus

- **Галочку сняли, а сессия старая:** права роли читаются в `resolve_session` на каждом запросе, не на входе. Тест — Task 5, `test_снятая_галочка_действует_со_следующей_сверки_сессии`.
- **Действие откатилось, а строка журнала осталась (или наоборот):** журнал пишется тем же подключением до коммита двери. Тест — Task 8, `test_отказ_двери_не_оставляет_журнала` (снятие проверки партнёра, которой нет у этого пространства).
- **Маршрут объявил объект чужого пространства и не спросил `can`:** запись прошла бы без границы. Тест — Task 6, `test_маршрут_с_объектом_без_permit_падает_500`.
- **Старый код тенанта `default`** (файлы состояния бота, `MCP_TOKENS` стендов) попадает в `can` и должен значить `HQ`, а не «чужое пространство». Тесты — Task 1, `test_старый_код_уК_приводится`; Task 13, `test_мост_с_тенантом_default_правит_как_уК`.
- **Человеку бота без привязки** (путь совместимости `ALLOWED_TELEGRAM_IDS`/`roster.json`) роли в базе нет, а проверку он вести обязан. Тест — Task 12, `test_путь_совместимости_получает_права_hq_staff`.

## Расхождения со спекой

Каждое — отдельной строкой, с тем, как план поступает, пока владелец не скажет иначе.

1. **Расхождение со спекой: в каталоге нет кода для подтверждения проверки на приёмке** (`POST /inspections/<id>/accept`, D199, сегодня — только `admin`). План заводит код `inspection.accept`; по умолчанию он у `hq_admin`, `hq_staff`, `country_admin` (по правилу таблицы «все, кроме…»), не у `country_staff`.
2. **Расхождение со спекой: в каталоге нет кода для правки записи проверки на приёмке** (`POST /inspections/<id>/findings/<fid>/revise`, сегодня — только `admin`). Спека в «За рамками» называет правку завершённого отчёта несуществующей, но правка черновика на приёмке есть. План заводит код `inspection.revise` с теми же умолчаниями, что у `inspection.accept`.
3. **Расхождение со спекой: `hq_staff` получает снятие, перенос, подтверждение и правку на приёмке.** Сегодня это только `admin`; таблица спеки даёт `hq_staff` «всё, кроме четырёх», а текст спеки называет только три отличия. План следует таблице.
4. **Расхождение со спекой: `hq_staff` теряет заведение пиццерий** — и в вебе, и **в боте на старте проверки** (`src/bot/routers/start.py`, «новая пиццерия?»). Сегодня может любой человек УК (`may_add_units`). План следует таблице (`unit.create` у `hq_staff` нет).
5. **Расхождение со спекой: заведение чек-листа партнёром.** Каталог кладёт «создать» в `checklist.manage`, а его по умолчанию получает `country_admin`; сегодня маршрут отказывает любому партнёру (D283, `checklists_create`). План оставляет этот отказ двери как есть (строже матрицы) — поведение не меняется.
6. **Расхождение со спекой: правка методики партнёра человеком УК.** Методика лежит файлами, журнал «в одной транзакции» с правкой файла невозможен. План оставляет дверь методики своей (`may_write`: правка только в своём пространстве) — УК в методику партнёра в блоке 1 не пишет.
7. **Расхождение со спекой: команды бота без пишущей операции.** `/help`, `/lang` (личная настройка языка), `/version`, `/stops` (чтение, круг админов) и запасной обработчик кода в каталоге не получают; тест полноты держит их явным списком исключений с причиной. `/mcp_add`, `/mcp_revoke`, `/mcp_who` до блока 3 закрываются тем же `mcp.connect`, что `/mcp`, поверх круга `mcp_admins`.
8. **Расхождение со спекой (порядок блоков): админ страны заводит людей (D307) — не в блоке 1.** Экран людей до блока 2 остаётся открыт только УК (мост в маршрутах «Пользователей»), иначе админ страны получил бы перечень людей всех пространств. Правило «назначить или снять админа страны — только `space.manage`» блок 2 обязан добавить вместе со снятием моста.

## Открытые вопросы владельцу (до раскатки блока)

- **В1** (расхождение 4): сотрудник УК в боте на старте проверки перестаёт заводить новую пиццерию. Так и задумано, или `unit.create` по умолчанию у `hq_staff` оставить? Ответ меняет одну строку засева в `0038` — до того, как миграция применена где-либо.
- **В2** (расхождение 3): сотрудник УК начинает снимать, переносить, подтверждать и править проверки на приёмке. Так и задумано?
- **В3** (расхождение 5): админу страны открыть заведение своих чек-листов (D304: «правят то, что завели сами»), или пока оставить отказ?

## Задачи

### Task 1: Каталог действий и `can`

**Files:**
- Create: `src/domain/permissions.py`
- Test: `tests/test_permissions_can.py`

**Interfaces:**
- Consumes: `src.domain.tenants.HQ_TENANT: str`, `src.domain.tenants.canonical_tenant(code: str) -> str`.
- Produces:
  - `Action(code: str, group: str, hq_only: bool = False)` — frozen dataclass.
  - `ACTIONS: tuple[Action, ...]`, `ACTION_CODES: frozenset[str]`, `HQ_ONLY_ACTIONS: frozenset[str]`.
  - `RULE_OK = "ok"`, `RULE_MATRIX = "matrix"`, `RULE_HQ_ONLY = "hq_only"`, `RULE_HQ_OBJECT = "hq_object"`, `RULE_FOREIGN_SPACE = "foreign_space"`.
  - `Actor(tenant: str, role: str | None, grants: frozenset[str], user_id: str | None = None)` — frozen dataclass.
  - `Decision(allowed: bool, rule: str)` — frozen dataclass, `__bool__` → `allowed`.
  - `class UnknownAction(ValueError)`.
  - `can(actor: Actor, action: str, object_tenant: str) -> Decision`.

- [ ] **Step 1: Написать падающий тест**

```python
# tests/test_permissions_can.py
"""Ядро прав, слой 1 — граница пространств (спека «Администрирование», D304, D306).

Ядро (права доступа) — тестами вперёд. Граница не настраивается: никакая
галочка не даёт стране тронуть объект УК, чужую страну или действие «только УК».
"""

from __future__ import annotations

import pytest

from src.domain.permissions import (
    ACTION_CODES,
    HQ_ONLY_ACTIONS,
    RULE_FOREIGN_SPACE,
    RULE_HQ_OBJECT,
    RULE_HQ_ONLY,
    RULE_MATRIX,
    RULE_OK,
    Actor,
    UnknownAction,
    can,
)

ВСЁ = frozenset(ACTION_CODES)


def уК(grants: frozenset[str] = ВСЁ, tenant: str = "HQ") -> Actor:
    return Actor(tenant=tenant, role="hq_admin", grants=grants, user_id="u-hq")


def страна(tenant: str = "GE", grants: frozenset[str] = ВСЁ) -> Actor:
    return Actor(tenant=tenant, role="country_admin", grants=grants, user_id="u-ge")


def test_каталог_ровно_по_спеке_и_два_кода_расхождений() -> None:
    assert ACTION_CODES == {
        "inspection.conduct",
        "inspection.retract",
        "inspection.move",
        "inspection.accept",
        "inspection.revise",
        "inspection.letter",
        "prescription.manage",
        "prescription.reply",
        "plan.manage",
        "plan.submit",
        "checklist.edit",
        "checklist.publish",
        "checklist.manage",
        "phrases.manage",
        "people.manage",
        "mcp.connect",
        "unit.create",
        "space.manage",
        "roles.manage",
    }


def test_только_уК_ровно_три_действия() -> None:
    assert HQ_ONLY_ACTIONS == {"unit.create", "space.manage", "roles.manage"}


def test_уК_действует_в_пространстве_партнёра() -> None:
    решение = can(уК(), "inspection.retract", "GE")
    assert решение.allowed and решение.rule == RULE_OK


def test_страна_не_трогает_объект_уК_даже_с_галочкой() -> None:
    решение = can(страна(), "checklist.edit", "HQ")
    assert not решение.allowed and решение.rule == RULE_HQ_OBJECT


def test_страна_не_трогает_чужую_страну() -> None:
    решение = can(страна("GE"), "inspection.retract", "AM")
    assert not решение.allowed and решение.rule == RULE_FOREIGN_SPACE


@pytest.mark.parametrize("код", sorted(HQ_ONLY_ACTIONS))
def test_действие_только_уК_стране_не_даёт_никакая_галочка(код: str) -> None:
    решение = can(страна(), код, "GE")
    assert not решение.allowed and решение.rule == RULE_HQ_ONLY


def test_без_галочки_отказ_матрицы_и_у_уК() -> None:
    решение = can(уК(grants=frozenset()), "inspection.retract", "HQ")
    assert not решение.allowed and решение.rule == RULE_MATRIX


def test_старый_код_уК_приводится() -> None:
    решение = can(уК(tenant="default"), "unit.create", "HQ")
    assert решение.allowed


def test_неизвестное_действие_это_ошибка_кода() -> None:
    with pytest.raises(UnknownAction, match="inspection.delete"):
        can(уК(), "inspection.delete", "HQ")


def test_пустое_пространство_объекта_это_ошибка_кода() -> None:
    with pytest.raises(ValueError, match="пространство"):
        can(уК(), "inspection.retract", "  ")


def test_отказ_ложен_в_условии() -> None:
    assert not can(страна(), "checklist.edit", "HQ")
```

- [ ] **Step 2: Прогнать — ожидается FAIL**

Run: `.venv/bin/pytest tests/test_permissions_can.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.domain.permissions'`.

- [ ] **Step 3: Минимальная реализация**

```python
# src/domain/permissions.py
"""Каталог действий и проверка прав `can` (спека «Администрирование», D304, D306, D307).

Решение принимается двумя слоями, и отказ первого второй не переопределяет:

1. **Граница** (код, не настраивается): человек УК действует в любом
   пространстве; человек страны — только в своём; объект УК страна не меняет
   никогда; действия «только УК» роли страны не выдаются ни одной галочкой.
2. **Матрица** (настраивает админ УК): есть ли у роли человека право.

Код действия — ключ, подписи переводятся отдельно. Новая пишущая операция
получает код здесь в момент появления: это часть её готовности.
"""

from __future__ import annotations

from dataclasses import dataclass

from .tenants import HQ_TENANT, canonical_tenant


@dataclass(frozen=True)
class Action:
    """Одна пишущая операция каталога."""

    code: str
    group: str
    #: Действие только УК: роли страны не выдаётся ни одной галочкой (слой 1).
    hq_only: bool = False


ACTIONS: tuple[Action, ...] = (
    Action("inspection.conduct", "inspection"),
    Action("inspection.retract", "inspection"),
    Action("inspection.move", "inspection"),
    Action("inspection.accept", "inspection"),
    Action("inspection.revise", "inspection"),
    Action("inspection.letter", "inspection"),
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

RULE_OK = "ok"
RULE_MATRIX = "matrix"
RULE_HQ_ONLY = "hq_only"
RULE_HQ_OBJECT = "hq_object"
RULE_FOREIGN_SPACE = "foreign_space"


class UnknownAction(ValueError):
    """Код действия не из каталога — ошибка кода, а не отказ человеку."""


@dataclass(frozen=True)
class Actor:
    """Кто действует: пространство, роль и права роли на момент запроса."""

    tenant: str
    #: Код роли; `None` — права не из роли (мост MCP до блока 3).
    role: str | None
    grants: frozenset[str]
    #: Учётка веба — для журнала действий УК у партнёра.
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


def can(actor: Actor, action: str, object_tenant: str) -> Decision:
    """Может ли `actor` сделать `action` над объектом пространства `object_tenant`."""
    if action not in ACTION_CODES:
        raise UnknownAction(f"Действия «{action}» нет в каталоге src/domain/permissions.py")
    кто = _required_tenant(actor.tenant, what="пространство человека")
    чьё = _required_tenant(object_tenant, what="пространство объекта")
    if кто != HQ_TENANT:
        if action in HQ_ONLY_ACTIONS:
            return Decision(False, RULE_HQ_ONLY)
        if чьё == HQ_TENANT:
            return Decision(False, RULE_HQ_OBJECT)
        if чьё != кто:
            return Decision(False, RULE_FOREIGN_SPACE)
    if action not in actor.grants:
        return Decision(False, RULE_MATRIX)
    return Decision(True, RULE_OK)
```

- [ ] **Step 4: Прогнать — ожидается PASS**

Run: `.venv/bin/pytest tests/test_permissions_can.py -q && .venv/bin/ruff check src/domain/permissions.py tests/test_permissions_can.py && .venv/bin/mypy`
Expected: все тесты PASS, ruff и mypy без ошибок.

- [ ] **Step 5: Коммит и пуш**

```bash
git add src/domain/permissions.py tests/test_permissions_can.py
git commit -m "feat: каталог действий и can — граница пространств

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
  - `ROLE_SCOPES: Mapping[str, str]` — код роли → охват.
  - `DEFAULT_MATRIX: Mapping[str, frozenset[str]]` — код роли → права по умолчанию.
  - `LEGACY_ROLE_ADMIN = "admin"`, `LEGACY_ROLE_AUDITOR = "auditor"`.
  - `scope_of_tenant(tenant: str) -> str`.
  - `canonical_role(role: str, tenant: str) -> str` — старое `admin`/`auditor` → новый код по пространству; прочее — как есть.
  - `validate_matrix(matrix: Mapping[str, frozenset[str]], scopes: Mapping[str, str]) -> list[str]` — нарушения словами, пусто — годна.

- [ ] **Step 1: Написать падающий тест**

```python
# tests/test_permissions_table.py
"""Таблица «роль × действие × пространство человека × пространство объекта → да/нет».

Таблица ролей переписана здесь из спеки руками, а не взята из кода: иначе тест
сверял бы `DEFAULT_MATRIX` с самим собой. Проверка таблицы прогоняется и на
заведомо сломанной матрице, и на заведомо сломанном `can` — она обязана
покраснеть и назвать нарушенное правило (`testing.md`).
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

ВСЕ_ПО_СПЕКЕ = frozenset(
    {
        "inspection.conduct", "inspection.retract", "inspection.move", "inspection.accept",
        "inspection.revise", "inspection.letter", "prescription.manage", "prescription.reply",
        "plan.manage", "plan.submit", "checklist.edit", "checklist.publish",
        "checklist.manage", "phrases.manage", "people.manage", "mcp.connect",
        "unit.create", "space.manage", "roles.manage",
    }
)
ТОЛЬКО_УК = frozenset({"unit.create", "space.manage", "roles.manage"})
СПЕКА: dict[str, frozenset[str]] = {
    "hq_admin": ВСЕ_ПО_СПЕКЕ,
    "hq_staff": ВСЕ_ПО_СПЕКЕ - {"people.manage", "space.manage", "roles.manage", "unit.create"},
    "country_admin": ВСЕ_ПО_СПЕКЕ - ТОЛЬКО_УК,
    "country_staff": frozenset(
        {"inspection.conduct", "inspection.letter", "prescription.reply", "plan.submit",
         "mcp.connect"}
    ),
}
ПРОСТРАНСТВО = {"hq_admin": "HQ", "hq_staff": "HQ", "country_admin": "GE", "country_staff": "GE"}
ОБЪЕКТЫ = ("HQ", "GE", "AM")

Решатель = Callable[[Actor, str, str], Decision]


def ожидание(роль: str, действие: str, объект: str) -> tuple[bool, str]:
    кто = ПРОСТРАНСТВО[роль]
    if кто != "HQ":
        if действие in ТОЛЬКО_УК:
            return False, "hq_only"
        if объект == "HQ":
            return False, "hq_object"
        if объект != кто:
            return False, "foreign_space"
    return (True, "ok") if действие in СПЕКА[роль] else (False, "matrix")


def сверить(решать: Решатель, матрица: Mapping[str, frozenset[str]]) -> list[str]:
    нарушения: list[str] = []
    for роль, кто in ПРОСТРАНСТВО.items():
        человек = Actor(tenant=кто, role=роль, grants=матрица[роль])
        for действие in sorted(ВСЕ_ПО_СПЕКЕ):
            for объект in ОБЪЕКТЫ:
                можно, правило = ожидание(роль, действие, объект)
                вышло = решать(человек, действие, объект)
                if вышло.allowed != можно:
                    нарушения.append(
                        f"{роль} × {действие} × {объект}: ожидалось "
                        f"{'да' if можно else 'нет'} ({правило}), вышло "
                        f"{'да' if вышло.allowed else 'нет'} ({вышло.rule})"
                    )
    return нарушения


def test_матрица_по_умолчанию_равна_таблице_спеки() -> None:
    assert dict(DEFAULT_MATRIX) == СПЕКА
    assert dict(ROLE_SCOPES) == {
        "hq_admin": "hq", "hq_staff": "hq", "country_admin": "country", "country_staff": "country",
    }


def test_таблица_прав_ролей_по_умолчанию() -> None:
    assert сверить(can, DEFAULT_MATRIX) == []


def test_сломанная_матрица_не_пробивает_границу() -> None:
    сломанная = {**DEFAULT_MATRIX, "country_staff": DEFAULT_MATRIX["country_staff"] | {"checklist.edit"}}
    assert сверить(can, сломанная) == [
        "country_staff × checklist.edit × GE: ожидалось нет (matrix), вышло да (ok)"
    ]


def test_проверка_таблицы_ловит_снятую_границу() -> None:
    def без_границы(человек: Actor, действие: str, _объект: str) -> Decision:
        if действие in человек.grants:
            return Decision(True, RULE_OK)
        return Decision(False, RULE_MATRIX)

    сломанная = {**DEFAULT_MATRIX, "country_staff": DEFAULT_MATRIX["country_staff"] | {"checklist.edit"}}
    нарушения = сверить(без_границы, сломанная)
    assert "country_staff × checklist.edit × HQ: ожидалось нет (hq_object), вышло да (ok)" in нарушения
    assert any("(foreign_space)" in н for н in нарушения)


def test_матрица_по_умолчанию_годна() -> None:
    assert validate_matrix(DEFAULT_MATRIX, ROLE_SCOPES) == []


def test_проверка_матрицы_называет_только_уК_у_роли_страны() -> None:
    сломанная = {**DEFAULT_MATRIX, "country_admin": DEFAULT_MATRIX["country_admin"] | {"unit.create"}}
    assert validate_matrix(сломанная, ROLE_SCOPES) == [
        "country_admin: unit.create — действие только УК (hq_only)"
    ]


def test_проверка_матрицы_называет_код_не_из_каталога() -> None:
    сломанная = {**DEFAULT_MATRIX, "hq_staff": DEFAULT_MATRIX["hq_staff"] | {"inspection.delete"}}
    assert validate_matrix(сломанная, ROLE_SCOPES) == [
        "hq_staff: inspection.delete — нет в каталоге действий"
    ]


def test_проверка_матрицы_называет_роль_без_охвата() -> None:
    assert validate_matrix({"ghost": frozenset()}, ROLE_SCOPES) == ["ghost: у роли нет охвата"]


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

- [ ] **Step 3: Минимальная реализация** — дописать в конец `src/domain/permissions.py` (и добавить `from collections.abc import Mapping` к импортам):

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

#: Права по умолчанию — таблица спеки. Засев `0038` сверяется с ней тестом
#: (`tests/test_db_roles_migration.py`), а не копируется руками второй раз.
DEFAULT_MATRIX: Mapping[str, frozenset[str]] = {
    ROLE_HQ_ADMIN: ACTION_CODES,
    ROLE_HQ_STAFF: ACTION_CODES
    - {"people.manage", "space.manage", "roles.manage", "unit.create"},
    ROLE_COUNTRY_ADMIN: ACTION_CODES - HQ_ONLY_ACTIONS,
    ROLE_COUNTRY_STAFF: frozenset(
        {"inspection.conduct", "inspection.letter", "prescription.reply", "plan.submit",
         "mcp.connect"}
    ),
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


def validate_matrix(
    matrix: Mapping[str, frozenset[str]], scopes: Mapping[str, str]
) -> list[str]:
    """Нарушения матрицы словами: код не из каталога, «только УК» у роли страны."""
    нарушения: list[str] = []
    for роль in sorted(matrix):
        охват = scopes.get(роль)
        if охват is None:
            нарушения.append(f"{роль}: у роли нет охвата")
            continue
        for код in sorted(matrix[роль]):
            if код not in ACTION_CODES:
                нарушения.append(f"{роль}: {код} — нет в каталоге действий")
            elif охват == SCOPE_COUNTRY and код in HQ_ONLY_ACTIONS:
                нарушения.append(f"{роль}: {код} — действие только УК ({RULE_HQ_ONLY})")
    return нарушения
```

- [ ] **Step 4: Прогнать — ожидается PASS**

Run: `.venv/bin/pytest tests/test_permissions_can.py tests/test_permissions_table.py -q && .venv/bin/ruff check src/domain tests/test_permissions_table.py && .venv/bin/mypy`
Expected: PASS; ruff, mypy чистые.

- [ ] **Step 5: Коммит и пуш**

```bash
git add src/domain/permissions.py tests/test_permissions_table.py
git commit -m "feat: роли по умолчанию и таблица прав с проверкой на сломанной матрице

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

### Task 3: Миграция `0038`: роли, права ролей, перенос учёток

**Files:**
- Create: `src/db/migrations/0038_roles.sql`
- Create: `tests/test_db_roles_migration.py`
- Modify: `tests/test_db_migrations_frozen.py` (словарь `ОТПЕЧАТКИ`, после строки `"0037_prescriptions.sql"`, ~строка 164)
- Modify: `tests/test_db_migrate_roles.py` (`APP_TABLE_GRANTS` ~строка 168, `ADMIN_TABLE_GRANTS` ~строка 274)
- Modify: `docs/furca/blocks/db.md` (раздел «API-контракт», после блока про учётки ~строка 67), `docs/08-deploy.md` (новый раздел `### 8.14` после `### 8.13`)

**Interfaces:**
- Consumes: `DEFAULT_MATRIX`, `ROLE_SCOPES` (Task 2) — только в тесте; `db_harness.empty_database`, `db_harness.завести_пространства`, `src.db.migrate.apply_migrations(dsn, *, directory)`, `src.db.web_access.password_hash(password) -> str`.
- Produces (схема): `roles(code PK, scope, name_ru, name_en, created_at)`, `role_permissions(role_code FK, action_code, PK)`, `web_users.role` → FK `web_users_role_fkey` на `roles.code`, триггер `web_users_role_scope` (ошибка `check_violation` с `constraint = 'web_users_role_scope'`), права: `select` на `roles`, `role_permissions` ролям `dodo_audit_app` и `dodo_audit_admin`.

- [ ] **Step 1: Написать падающий тест**

```python
# tests/test_db_roles_migration.py
"""Миграция `0038`: роли по умолчанию и перенос учёток (спека «Администрирование»).

Ядро (права): каждая текущая учётка получает роль с теми же возможностями,
засев совпадает с таблицей спеки, роль чужого охвата не ложится никому.
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


def test_засев_ролей_равен_таблице_спеки(pg_dsn: str) -> None:
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute("select code, scope from roles")
        assert dict(cur.fetchall()) == dict(ROLE_SCOPES)
        cur.execute("select role_code, action_code from role_permissions")
        засев: dict[str, set[str]] = {}
        for роль, код in cur.fetchall():
            засев.setdefault(роль, set()).add(код)
        assert {р: frozenset(к) for р, к in засев.items()} == dict(DEFAULT_MATRIX)


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

Дописать в `tests/test_db_migrations_frozen.py`, словарь `ОТПЕЧАТКИ`, после `"0037_prescriptions.sql"` — строку с отпечатком (значение берётся в Step 4):

```python
    # Роли и права ролей (спека «Администрирование», блок 1). Заведена вместе с файлом.
    "0038_roles.sql": ("sql1:<отпечаток из Step 4>"),
```

Дописать в `tests/test_db_migrate_roles.py`:

```python
# в APP_TABLE_GRANTS, после строки "country_recipients": {"SELECT"},
    # Роли и галочки (`0038`): приложение их только читает — права роли
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

Run: `nc -z 127.0.0.1 55432 && make test-honest ARGS="tests/test_db_roles_migration.py tests/test_db_migrate_roles.py tests/test_db_migrations_frozen.py -q -rs"`
Expected: FAIL — в `test_db_roles_migration.py` `assert [] == ['0038_roles.sql']` и `relation "roles" does not exist`; в `test_db_migrate_roles.py` лишние таблицы в ожидании. Строк `SKIPPED` нет.

- [ ] **Step 3: Минимальная реализация**

```sql
-- 0038_roles.sql
--
-- Роли с матрицей «роль × действие» (спека «Администрирование», D306, D309).
--
-- Человеку назначается роль, галочки роли определяют, что она может. Граница
-- пространств галочками не задаётся: её держит `can` в коде
-- (`src/domain/permissions.py`), здесь — только охват роли (УК или страна).
--
-- ПЕРЕНОС. Роли учёток до этой миграции — `admin`/`auditor` (`0020`). Они
-- переводятся по пространству учётки ровно по таблице спеки:
--   HQ × admin → hq_admin, HQ × auditor → hq_staff,
--   страна × admin → country_admin, страна × auditor → country_staff.
--
-- ЗАСЕВ ПРАВ — таблица спеки; с кодом (`DEFAULT_MATRIX`) его сверяет
-- `tests/test_db_roles_migration.py`. Код действия проверяется по каталогу
-- приложения при записи (экран блока 2), в схеме — только форма кода.
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
    primary key (role_code, action_code)
);

insert into roles (code, scope, name_ru, name_en) values
    ('hq_admin', 'hq', 'Админ УК', 'HQ admin'),
    ('hq_staff', 'hq', 'Сотрудник УК', 'HQ staff'),
    ('country_admin', 'country', 'Админ страны', 'Country admin'),
    ('country_staff', 'country', 'Сотрудник страны', 'Country staff');

insert into role_permissions (role_code, action_code)
select 'hq_admin', код from unnest(array[
    'inspection.conduct', 'inspection.retract', 'inspection.move', 'inspection.accept',
    'inspection.revise', 'inspection.letter', 'prescription.manage', 'prescription.reply',
    'plan.manage', 'plan.submit', 'checklist.edit', 'checklist.publish', 'checklist.manage',
    'phrases.manage', 'people.manage', 'mcp.connect', 'unit.create', 'space.manage',
    'roles.manage'
]) as код
union all
select 'hq_staff', код from unnest(array[
    'inspection.conduct', 'inspection.retract', 'inspection.move', 'inspection.accept',
    'inspection.revise', 'inspection.letter', 'prescription.manage', 'prescription.reply',
    'plan.manage', 'plan.submit', 'checklist.edit', 'checklist.publish', 'checklist.manage',
    'phrases.manage', 'mcp.connect'
]) as код
union all
select 'country_admin', код from unnest(array[
    'inspection.conduct', 'inspection.retract', 'inspection.move', 'inspection.accept',
    'inspection.revise', 'inspection.letter', 'prescription.manage', 'prescription.reply',
    'plan.manage', 'plan.submit', 'checklist.edit', 'checklist.publish', 'checklist.manage',
    'phrases.manage', 'people.manage', 'mcp.connect'
]) as код
union all
select 'country_staff', код from unnest(array[
    'inspection.conduct', 'inspection.letter', 'prescription.reply', 'plan.submit',
    'mcp.connect'
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
    'Код роли (roles.code): что человеку можно — галочками role_permissions. '
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

- [ ] **Step 4: Отпечаток в список и прогон — ожидается PASS**

Run: `.venv/bin/python -c "from src.db.migrate import discover_migrations as d; print([m.checksum for m in d() if m.filename == '0038_roles.sql'][0])"` — вписать выведенное значение в строку `"0038_roles.sql"` в `tests/test_db_migrations_frozen.py`.
Run: `make test-honest ARGS="tests/test_db_roles_migration.py tests/test_db_migrate_roles.py tests/test_db_migrations_frozen.py -q -rs"`
Expected: PASS, `SKIPPED` нет. Красные `tests/test_db_web_access.py` и соседей, заводящих учётки с ролью `admin`/`auditor`, на этом шаге ожидаемы и чинятся в Task 5 — не трогать их здесь.

- [ ] **Step 5: Документация тем же коммитом**

`docs/furca/blocks/db.md`, раздел «API-контракт», после строк про учётки (~строка 67) — блок:

```
# роли и права ролей (0038, спека «Администрирование») — таблицы roles, role_permissions
#   roles(code, scope ∈ {hq, country}, name_ru, name_en): роль относится к УК или к стране
#   role_permissions(role_code, action_code): галочка «роль может действие»; коды —
#   каталог src/domain/permissions.py (ACTIONS), граница пространств — не здесь, а в can
#   web_users.role → roles.code; роль УК только у людей HQ, роль страны только у людей
#   страны (триггер web_users_role_scope, check_violation)
#   засев — таблица спеки (DEFAULT_MATRIX), перенос admin/auditor × HQ/страна → 4 роли
```

`docs/08-deploy.md` — новый раздел после `### 8.13`:

```markdown
### 8.14. Раскатка ядра прав, блок 1 «Администрирование»

1. **Миграция `0038_roles.sql`** — таблицы `roles`, `role_permissions`, четыре роли по
   умолчанию, перенос `web_users.role`: `HQ × admin → hq_admin`, `HQ × auditor → hq_staff`,
   `страна × admin → country_admin`, `страна × auditor → country_staff`. Перед накатом
   посмотреть, кто что получит: `make web-user ARGS="list"` на целевой базе.
2. **Миграция `0039_cross_space_actions.sql`** — пустой журнал действий УК у партнёра.
3. Команда `make web-user ARGS="role <логин> <роль> --tenant <код>"` принимает коды
   `hq_admin`, `hq_staff`, `country_admin`, `country_staff`; старые `admin`/`auditor`
   переводятся по пространству учётки.
4. Переменные окружения не меняются: MCP в блоке 1 работает по прежним
   `MCP_TOKENS`, `MCP_CHECKLIST_TENANTS`, `MCP_RETRACTION_TOKENS`.
```

- [ ] **Step 6: Коммит и пуш**

```bash
git add src/db/migrations/0038_roles.sql tests/test_db_roles_migration.py tests/test_db_migrations_frozen.py tests/test_db_migrate_roles.py docs/furca/blocks/db.md docs/08-deploy.md
git commit -m "feat: миграция 0038 — роли, права ролей, перенос учёток

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
- Consumes: `Actor`, `ACTION_CODES`, `UnknownAction` (Task 1); `canonical_tenant`.
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
    return Actor(tenant="HQ", role="hq_admin", grants=frozenset(), user_id=user_id)


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
    запись = Entry(кто, "HQ", "GE", "inspection.retract", "inspection:откат")
    with psycopg.connect(db_env) as conn:
        record(conn, запись)
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

from src.domain.permissions import ACTION_CODES, Actor, UnknownAction
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
    """Строка журнала для действия — или `None`, если пространство своё."""
    if action not in ACTION_CODES:
        raise UnknownAction(f"Действия «{action}» нет в каталоге src/domain/permissions.py")
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
#   record(conn, entry): пишет на подключении ДВЕРИ ДЕЙСТВИЯ до её коммита; своего
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

### Task 5: Двери учёток знают роль и права

**Files:**
- Create: `src/db/roles.py`
- Modify: `src/db/web_access.py` — константы ролей (~строки 228–233), `Account` (~236–248), SQL `_SELECT_USER_SQL` (~111), `_SELECT_USER_BY_EMAIL_SQL` (~196), `_RESOLVE_SESSION_SQL` (~211), `_checked_role` (~425), `create_account` (~476), `reassign_role` (~554), `find_by_email` (~679), `authenticate` (~706), `resolve_session` (~748)
- Modify: `src/web/accounts.py` (реэкспорт `ROLE_ADMIN`/`ROLE_AUDITOR`/`ROLES`, ~строки 20–45)
- Modify: `tools/web_user.py` (~строка 183, `choices=ROLES`)
- Create: `tests/test_db_roles_door.py`
- Modify: `tests/test_db_web_access.py` (ожидания ролей `admin`/`auditor` → новые коды)
- Modify: `docs/12-web-admin.md` (команды `make web-user`, ~строки 328–333)

**Interfaces:**
- Consumes: `canonical_role`, `scope_of_tenant` (Task 2); таблицы `0038`; `src.db.reading.reading(зачем)`.
- Produces:
  - `src/db/roles.py`: `Role(code: str, scope: str, name_ru: str, name_en: str, grants: frozenset[str])`; `list_roles() -> tuple[Role, ...]`; `grants_of(role_code: str) -> frozenset[str]`.
  - `Account(id: str, login: str, tenant: str, role: str = "", grants: frozenset[str] = frozenset(), role_name_ru: str = "", role_name_en: str = "")`.
  - `web_access.ROLE_ADMIN = LEGACY_ROLE_ADMIN`, `web_access.ROLE_AUDITOR = LEGACY_ROLE_AUDITOR` (старые имена — псевдонимы для команд стендов); `ROLES` удаляется.
  - `create_account(login, *, tenant, password, role=ROLE_AUDITOR) -> Account` и `reassign_role(login, *, tenant, role) -> str | None` принимают новый код или старый псевдоним; роль чужого охвата → `AccessError("Роль «…» не для пространства «…»")`, незаведённая → `AccessError("Роль «…» не заведена")`.

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


def test_вход_приносит_права_и_имя_роли(обе_роли: str) -> None:
    create_account("hq-staff", tenant="HQ", password=ПАРОЛЬ, role="hq_staff")
    вошёл = authenticate("hq-staff", ПАРОЛЬ)
    assert вошёл is not None
    assert вошёл.grants == DEFAULT_MATRIX["hq_staff"]
    assert (вошёл.role_name_ru, вошёл.role_name_en) == ("Сотрудник УК", "HQ staff")


def test_снятая_галочка_действует_со_следующей_сверки_сессии(обе_роли: str) -> None:
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
    assert grants_of("country_staff") == DEFAULT_MATRIX["country_staff"]
    assert grants_of("ghost") == frozenset()
```

- [ ] **Step 2: Прогнать — ожидается FAIL**

Run: `make test-honest ARGS="tests/test_db_roles_door.py -q -rs"`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.db.roles'`.

- [ ] **Step 3: Минимальная реализация**

```python
# src/db/roles.py
"""Роли и их права — чтение ролью приложения (спека «Администрирование», `0038`)."""

from __future__ import annotations

from dataclasses import dataclass

from .reading import reading

_LIST_SQL = """
    select r.code, r.scope, r.name_ru, r.name_en,
           array(select p.action_code from role_permissions p
                  where p.role_code = r.code order by 1)
      from roles r
     order by r.scope, r.code
"""

_GRANTS_SQL = "select action_code from role_permissions where role_code = %s"


@dataclass(frozen=True)
class Role:
    """Роль так, как её показывают и проверяют: код, охват, подписи, права."""

    code: str
    scope: str
    name_ru: str
    name_en: str
    grants: frozenset[str]


def list_roles() -> tuple[Role, ...]:
    """Все роли с правами — для выбора роли на экране людей."""
    with reading("роли") as conn, conn.cursor() as cur:
        cur.execute(_LIST_SQL)
        return tuple(
            Role(str(r[0]), str(r[1]), str(r[2]), str(r[3]), frozenset(r[4]))
            for r in cur.fetchall()
        )


def grants_of(role_code: str) -> frozenset[str]:
    """Права роли. Незаведённая роль — пусто: закрыто по умолчанию."""
    with reading("права роли") as conn, conn.cursor() as cur:
        cur.execute(_GRANTS_SQL, (role_code,))
        return frozenset(str(r[0]) for r in cur.fetchall())
```

`src/db/web_access.py` — заменить блок ролей и `Account`:

```python
from src.domain.permissions import LEGACY_ROLE_ADMIN, LEGACY_ROLE_AUDITOR, canonical_role

#: Старые имена ролей (`0020`) — псевдонимы: команды стендов и тесты зовут
#: `role ... admin`, перевод по пространству — `canonical_role`.
ROLE_AUDITOR = LEGACY_ROLE_AUDITOR
ROLE_ADMIN = LEGACY_ROLE_ADMIN

#: Ограничение охвата роли в схеме (`0038`): его имя различает «роль чужого
#: охвата» и прочие отказы проверки.
_ROLE_SCOPE_CONSTRAINT = "web_users_role_scope"


@dataclass(frozen=True)
class Account:
    """Учётка так, как её видят страницы: кто вошёл, его роль и права роли."""

    id: str
    login: str
    tenant: str
    #: Код роли (`roles.code`). Приезжает вместе с опознанием одним запросом.
    role: str = ""
    #: Права роли на момент запроса — галочки `role_permissions`.
    grants: frozenset[str] = frozenset()
    role_name_ru: str = ""
    role_name_en: str = ""
```

SQL опознания — три запроса получают одинаковый хвост колонок (`role`, подписи, права), пароль — последним у `_SELECT_USER_SQL`:

```python
_SELECT_USER_SQL = """
    select u.id, u.login, u.tenant_code, u.role, r.name_ru, r.name_en,
           array(select p.action_code from role_permissions p
                  where p.role_code = u.role order by 1),
           u.password_hash
      from web_users u join roles r on r.code = u.role
     where u.login = %s and u.disabled_at is null
"""

_SELECT_USER_BY_EMAIL_SQL = """
    select u.id, u.login, u.tenant_code, u.role, r.name_ru, r.name_en,
           array(select p.action_code from role_permissions p
                  where p.role_code = u.role order by 1)
      from web_users u join roles r on r.code = u.role
     where u.email = %s and u.disabled_at is null
"""

_RESOLVE_SESSION_SQL = """
    select u.id, u.login, u.tenant_code, u.role, r.name_ru, r.name_en,
           array(select p.action_code from role_permissions p
                  where p.role_code = u.role order by 1)
      from web_sessions s
      join web_users u on u.id = s.user_id
      join roles r on r.code = u.role
     where s.fingerprint = %s
       and s.closed_at is null
       and s.expires_at > now()
       and u.disabled_at is null
"""


def _account(row: tuple[Any, ...]) -> Account:
    """Строка опознания → учётка. Первые семь колонок одинаковы у трёх запросов."""
    return Account(
        id=str(row[0]),
        login=str(row[1]),
        tenant=str(row[2]),
        role=str(row[3]),
        role_name_ru=str(row[4]),
        role_name_en=str(row[5]),
        grants=frozenset(row[6]),
    )


def _checked_role(role: str, tenant: str) -> str:
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

`create_account`: `роль = _checked_role(role, tenant)`; в `try` вокруг `cur.execute(_INSERT_USER_SQL, ...)` добавить ветку:

```python
        except (psycopg.errors.ForeignKeyViolation, psycopg.errors.CheckViolation) as exc:
            отказ = _role_refusal(exc, role=роль, tenant=tenant)
            if отказ is None:
                raise
            raise отказ from exc
```

`reassign_role`: `роль = _checked_role(role, tenant)`; вызов `cur.execute(_SET_ROLE_SQL, ...)` обернуть тем же `try/except`. `authenticate`, `find_by_email`, `resolve_session`: возвращать `_account(row)` (у `authenticate` хеш берётся как `row[7]`: `password_matches(password, str(row[7]))`). `ROLES` удалить.

`src/web/accounts.py`: убрать `ROLES` из импорта и из `__all__`; `ROLE_ADMIN`, `ROLE_AUDITOR` оставить. `tools/web_user.py`: `роль.add_argument("role", help="код роли (hq_admin, hq_staff, country_admin, country_staff) или старое admin/auditor")` — без `choices`; импорт `ROLES` убрать.

- [ ] **Step 4: Прогнать — ожидается PASS, затем починить старые ожидания**

Run: `make test-honest ARGS="tests/test_db_roles_door.py -q -rs"` → PASS.
Run: `make test-honest ARGS="tests/test_db_web_access.py tests/test_db_web_own_password.py tests/test_db_web_unlock.py tests/test_db_bot_links.py -q -rs"`
Expected до правки: FAIL только на сравнениях `role == "admin"`/`"auditor"` (например `test_роль_назначается_и_видна_вошедшему`, ~строка 441). Каждое такое ожидание заменить на код по таблице переноса (`HQ × admin → "hq_admin"` и т. д.); любой другой красный — регрессия, разбирать. После правки — PASS, `SKIPPED` нет.

- [ ] **Step 5: Документация** — `docs/12-web-admin.md`, строки команд (~330):

```
make web-user ARGS="role director hq_admin --tenant HQ"   # первый админ стенда (старое «admin» тоже понимается)
```

и строка под блоком команд: «Роли — коды `hq_admin`, `hq_staff`, `country_admin`, `country_staff` (`src/domain/permissions.py`); роль УК — только людям `HQ`, роль страны — только людям страны.»

- [ ] **Step 6: Коммит и пуш**

```bash
git add src/db/roles.py src/db/web_access.py src/web/accounts.py tools/web_user.py tests/test_db_roles_door.py tests/test_db_web_access.py docs/12-web-admin.md
git commit -m "feat: роль и права роли приезжают вместе с опознанием

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

(Если в Step 4 правились и другие файлы тестов — добавить их в `git add` поимённо.)

### Task 6: Заслон прав веба

**Files:**
- Create: `src/web/guard.py`
- Modify: `src/web/auth.py` — `current_actor()` после `current_reach()` (~строка 175)
- Modify: `src/web/app.py` — `create_app`: `guard.install(app)` сразу после `_install_hq_gate(app)` (~строка 123)
- Modify: `tests/web_harness.py` — `Учётка.__init__` (~строки 49–55)
- Create: `tests/test_web_guard.py`

**Interfaces:**
- Consumes: `can`, `Actor`, `ACTION_CODES`, `UnknownAction`, `canonical_role`, `DEFAULT_MATRIX` (Tasks 1–2); `Account.grants` (Task 5); `auth.current_account`, `auth.current_tenant`, `auth.OPEN_ENDPOINTS`.
- Produces:
  - `auth.current_actor() -> Actor` — пространство, роль, права и `user_id` вошедшего.
  - `guard.action(*codes: str, object_in_route: bool = False) -> Callable[[F], F]` — метка на функции маршрута.
  - `guard.permit(code: str, object_tenant: str) -> tuple[str, int] | None` — `None` можно, иначе страница 403.
  - `guard.mark_own() -> None` — маршрут с объектом действует над своим (своя привязка бота): граница не нужна.
  - `guard.install(app: Flask) -> None`.
  - `guard.uncovered(app: Flask) -> list[str]` — пишущие маршруты без кода и без исключения.
  - `guard.EXEMPT_ENDPOINTS: Mapping[str, str]` — эндпоинт → причина; `guard.WRITING_GETS: frozenset[str]`.

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

    @app.post("/_t/own")
    @guard.action("checklist.edit")
    def _own() -> str:
        return "ok"

    @app.post("/_t/object/<tenant>")
    @guard.action("inspection.retract", object_in_route=True)
    def _object(tenant: str) -> str | tuple[str, int]:
        отказ = guard.permit("inspection.retract", tenant)
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


@pytest.mark.parametrize("вошедший", [("GE", "auditor")], indirect=True)
def test_сотрудник_страны_не_правит_методику(вошедший: FlaskClient) -> None:
    assert вошедший.post("/_t/own", headers={"Origin": СВОЙ}).status_code == 403


@pytest.mark.parametrize("вошедший", [("GE", "admin")], indirect=True)
def test_админ_страны_правит_свою_методику(вошедший: FlaskClient) -> None:
    assert вошедший.post("/_t/own", headers={"Origin": СВОЙ}).status_code == 200


@pytest.mark.parametrize("вошедший", [("HQ", "admin")], indirect=True)
def test_уК_действует_над_объектом_партнёра(вошедший: FlaskClient) -> None:
    assert вошедший.post("/_t/object/GE", headers={"Origin": СВОЙ}).status_code == 200


@pytest.mark.parametrize("вошедший", [("GE", "admin")], indirect=True)
def test_страна_не_действует_над_объектом_уК(вошедший: FlaskClient) -> None:
    assert вошедший.post("/_t/object/HQ", headers={"Origin": СВОЙ}).status_code == 403


@pytest.mark.parametrize("вошедший", [("HQ", "admin")], indirect=True)
def test_маршрут_с_объектом_без_permit_падает_500(вошедший: FlaskClient) -> None:
    assert вошедший.post("/_t/forgot", headers={"Origin": СВОЙ}).status_code == 500


def test_незнакомый_код_падает_на_объявлении() -> None:
    with pytest.raises(ValueError, match="inspection.delete"):
        guard.action("inspection.delete")


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

    def __init__(self, login: str = ЛОГИН, tenant: str = "default", role: str = "auditor") -> None:
        self.id = "22222222-2222-2222-2222-222222222222"
        self.login = login
        self.tenant = tenant
        # Роль по умолчанию — САМАЯ УЗКАЯ, как и в базе. Старое имя роли
        # переводится по пространству так же, как его переводит миграция `0038`.
        self.role = canonical_role(role, tenant)
        self.grants = DEFAULT_MATRIX.get(self.role, frozenset())
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
        grants=frozenset(account.grants),
        user_id=account.id,
    )
```

```python
# src/web/guard.py
"""Заслон прав веба (спека «Администрирование»): каждый пишущий маршрут — через `can`.

Маршрут объявляет код действия декоратором `action`. Маршрут своего
пространства проверяется целиком до входа (`before_request`). Маршрут, чей
объект может лежать в чужом пространстве (`object_in_route=True`), сам зовёт
`permit(код, пространство_объекта)` — пространство берётся из объекта, а не из
формы. Забыл позвать — пишущий запрос падает 500 после ответа (`after_request`):
запись без границы громче, чем тихая.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Any, TypeVar

from flask import Flask, current_app, g, render_template, request
from werkzeug.wrappers import Response

from src.domain.permissions import ACTION_CODES, UnknownAction, can

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
    """Объявить код действия маршрута. Незнакомый код — ошибка при сборке приложения."""
    if not codes:
        raise ValueError("Маршрут без кода действия: заслону нечего спрашивать")
    чужие = [код for код in codes if код not in ACTION_CODES]
    if чужие:
        raise UnknownAction(f"Нет в каталоге src/domain/permissions.py: {', '.join(чужие)}")
    if len(codes) > 1 and not object_in_route:
        raise ValueError("Несколько кодов — код выбирает маршрут: object_in_route=True")

    def mark(view: F) -> F:
        setattr(view, ACTIONS_ATTR, codes)
        setattr(view, OBJECT_IN_ROUTE_ATTR, object_in_route)
        return view

    return mark


def _view() -> Any:
    return current_app.view_functions.get(request.endpoint or "")


def _forbidden() -> tuple[str, int]:
    return render_template("users/forbidden.html"), 403


def permit(code: str, object_tenant: str) -> tuple[str, int] | None:
    """Спросить `can` о вошедшем. `None` — можно; иначе страница отказа 403."""
    объявлено = getattr(_view(), ACTIONS_ATTR, ())
    if code not in объявлено:
        raise RuntimeError(
            f"Маршрут {request.endpoint} спрашивает «{code}», а объявил {объявлено}"
        )
    решение = can(auth.current_actor(), code, object_tenant)
    setattr(g, _PERMITTED, True)
    if решение.allowed:
        return None
    logger.info(
        "права: отказ %s %s над %s (%s)", request.endpoint, code, object_tenant, решение.rule
    )
    return _forbidden()


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
            f"Маршрут {request.endpoint} объявил объект чужого пространства и не спросил "
            f"can: запись прошла без границы"
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
Expected: зелёное — ни один настоящий маршрут ещё не объявил код, заслон их не трогает; двойник учётки лишь получил права. Красное — разобрать, это регрессия от двойника.

- [ ] **Step 5: Коммит и пуш**

```bash
git add src/web/guard.py src/web/auth.py src/web/app.py tests/web_harness.py tests/test_web_guard.py
git commit -m "feat: заслон прав веба — код действия на маршруте и can

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

### Task 7: Веб — маршруты своего пространства через `can`

Маршруты, которые пишут только в пространство вошедшего (двери берут `tenant=auth.current_tenant()` или держат страну триггером базы). Объект здесь всегда своего пространства, поэтому код проверяется целиком в `before_request`.

| Эндпоинт | Код |
|---|---|
| `methodology_add`, `methodology_edit`, `methodology_disable`, `methodology_restore`, `methodology_zone_add`, `methodology_zone_shares`, `methodology_zone_rename`, `methodology_zone_remove`, `methodology_route`, `methodology_scoring` | `checklist.edit` |
| `methodology_publish` | `checklist.publish` |
| `checklists_create`, `checklists_state`, `methodology_bot`, `checklists_apply` | `checklist.manage` |
| `rx_create`, `rx_update`, `rx_send`, `rx_close` | `prescription.manage` |
| `order_reply` | `prescription.reply` |
| `actions_review`, `actions_due`, `actions_new` | `plan.manage` |
| `plans_upload` | `plan.submit` |
| `unit_create` | `unit.create` (`object_in_route=True`: прежний 404 партнёру сохраняется) |

**Files:**
- Modify: `src/web/app.py` — декоратор `@guard.action(...)` под каждым `@app.post` методики (~строки 1642–1846) и чек-листов (~1897–2023)
- Modify: `src/web/prescriptions.py` (~строки 184, 224, 244, 253, 491), `src/web/action_plans.py` (~219, 239, 255, 305)
- Modify: `src/web/unit_add.py` — `may_add_in` (~строка 45), `can_add_here` (~57), маршрут `unit_create` (~120)
- Create: `tests/test_web_permissions_routes.py`
- Modify: `tests/test_web_unit_add.py` (ожидания для `hq_staff`)
- Modify: `docs/12-web-admin.md` — новый подраздел «Права на действия» после «Вход: кто вообще видит эти страницы» (~строка 315)

**Interfaces:**
- Consumes: `guard.action`, `guard.permit` (Task 6); `auth.current_actor`, `can`.
- Produces: `unit_add.may_add_in(actor: Actor, reach: Reach, code: str) -> bool` (вместо `tenant: str` первым параметром).

- [ ] **Step 1: Написать падающий тест**

```python
# tests/test_web_permissions_routes.py
"""Маршруты своего пространства спрашивают can — по таблице ролей спеки."""

from __future__ import annotations

import pytest
from web_harness import СВОЙ, войти, подменить_двери, собрать

from src.web import guard

МЕТОДИКА = (
    "/admin/items",
    "/admin/zones",
    "/admin/route",
    "/admin/scoring",
    "/admin/publish",
)


def _клиент(monkeypatch: pytest.MonkeyPatch, *, tenant: str, role: str):  # type: ignore[no-untyped-def]
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
    клиент = _клиент(monkeypatch, tenant="HQ", role="auditor")
    assert клиент.post(путь, headers={"Origin": СВОЙ}).status_code != 403


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
Expected: FAIL — сотрудник страны получает не 403; у эндпоинтов нет `required_actions`.

- [ ] **Step 3: Минимальная реализация**

Каждому эндпоинту из таблицы — декоратор строкой ниже `@app.post(...)`, например:

```python
    @app.post(f"{путь}/items")
    @guard.action("checklist.edit")
    def methodology_add() -> str:
```

В `src/web/prescriptions.py` и `src/web/action_plans.py` — импорт `from . import guard`, декоратор под `@app.post(..., endpoint=...)`. Существующие `_require_hq()` и `is_hq()` остаются: это заслон раздела (D264), он отвечает раньше и тем же кодом, что сегодня.

`src/web/unit_add.py`:

```python
from src.domain.permissions import Actor, can

from . import guard


def may_add_in(actor: Actor, reach: Reach, code: str) -> bool:
    """Может ли вошедший завести пиццерию в стране `code`: право, словарь сети, охват."""
    if not can(actor, "unit.create", actor.tenant) or code not in COUNTRIES:
        return False
    return reach.countries is None or code in reach.countries


def can_add_here(code: str) -> bool:
    """Показывать ли вход «Добавить пиццерию» на экране страны `code`."""
    return bool(code) and may_add_in(auth.current_actor(), auth.current_reach(), code)
```

Маршрут `unit_create`: декоратор `@guard.action("unit.create", object_in_route=True)`; там, где сегодня стоит отказ 404 по `may_add_in(...)`, звать `may_add_in(auth.current_actor(), auth.current_reach(), code)`, и сразу после него — `отказ = guard.permit("unit.create", auth.current_tenant())`, `if отказ is not None: return отказ`. GET `unit_new` — тот же `may_add_in(auth.current_actor(), ...)`. Импорт `may_add_units` из `unit_add.py` убрать.

- [ ] **Step 4: Прогнать — ожидается PASS; веб целиком**

Run: `.venv/bin/pytest tests/test_web_permissions_routes.py -q` → PASS.
Run: `.venv/bin/pytest tests/test_web_*.py -q`
Expected: красными могут стать только ожидания, что сотрудник УК (`auditor` у `HQ`) заводит пиццерию (`tests/test_web_unit_add.py`): по таблице спеки у `hq_staff` нет `unit.create` (расхождение 4, вопрос В1) — переписать ожидание на 404 со ссылкой на расхождение; и ожидания, что сотрудник страны правит методику (`tests/test_web_methodology_spaces.py`) — переписать на 403 (зафиксированное отличие спеки). Любой другой красный — регрессия, разбирать.

- [ ] **Step 5: Документация** — `docs/12-web-admin.md`, новый подраздел:

```markdown
## Права на действия (спека «Администрирование», блок 1)

Каждый пишущий адрес объявляет код действия (`src/web/guard.py: action`), и до
выполнения его спрашивает `can` (`src/domain/permissions.py`): граница пространств
в коде, галочка — в матрице роли (`role_permissions`). Каталог кодов — `ACTIONS`
в том же модуле; соответствие адресов кодам держит тест полноты
`tests/test_web_action_coverage.py`. Отказ — страница 403; адреса раздела «только УК»
по-прежнему отвечают партнёру 404 (D264). Роли по умолчанию — таблица спеки:
сотрудник страны методику не правит, сотрудник УК пиццерий не заводит.
```

- [ ] **Step 6: Коммит и пуш**

```bash
git add src/web/app.py src/web/prescriptions.py src/web/action_plans.py src/web/unit_add.py tests/test_web_permissions_routes.py tests/test_web_unit_add.py docs/12-web-admin.md
git commit -m "feat: маршруты своего пространства спрашивают can

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

(Файлы тестов, ожидания которых переписаны в Step 4, — добавить поимённо.)

### Task 8: Журнал в дверях проверок

Двери снятия, приёмки, переноса, правки на приёмке и письма принимают необязательную запись журнала и пишут её своим подключением до коммита.

**Files:**
- Modify: `src/db/retract.py` — `retract_inspection` (~строки 275–325)
- Modify: `src/db/accept.py` — `accept_inspection` (~52–80)
- Modify: `src/db/move.py` — `move_inspection` (~90–127)
- Modify: `src/db/revise.py` — `revise_finding` (~98–125)
- Modify: `src/db/letters.py` — `save_letter` (~56–100)
- Modify: `src/web/inspections.py` — `accept_card`, `retract_card`, `move_card` и обёртка правки (~строки 228–305): пробросить `journal`
- Create: `tests/test_db_cross_space_doors.py`

**Interfaces:**
- Consumes: `cross_space.Entry`, `cross_space.record` (Task 4).
- Produces (новый keyword-only параметр `journal: Entry | None = None` у каждой):
  - `retract_inspection(inspection_id, *, tenant, reason, storage=None, journal=None) -> Retraction`
  - `accept_inspection(inspection_id, *, tenant, actor, journal=None) -> None`
  - `move_inspection(inspection_id, *, tenant, new_date, new_unit_id, reason, actor, journal=None) -> bool`
  - `revise_finding(inspection_id, *, ..., tenant, ..., journal=None)` (прочие параметры — как сейчас)
  - `save_letter(inspection_id, *, tenant, body, lang, saved_by, journal=None)`
  - `inspections.retract_card(..., journal=None)`, `accept_card(..., journal=None)`, `move_card(..., journal=None)`, обёртка правки — то же.

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


def test_снятие_проверки_партнёра_пишет_журнал(
    domain_env: Path, pg_dsn: str, retraction_env: str
) -> None:
    привязать_пространства(pg_dsn, "GE")
    точка_пространства(ТОЧКА, tenant="GE")
    ident = слить_проверку(unit=ТОЧКА, tenant="GE")
    кто = _учётка_уК(pg_dsn)
    retract_inspection(
        ident,
        tenant="GE",
        reason="УК сняла ошибочную",
        journal=Entry(кто, "HQ", "GE", "inspection.retract", f"inspection:{ident}"),
    )
    assert _журнал(pg_dsn) == [("GE", "inspection.retract", f"inspection:{ident}")]


def test_отказ_двери_не_оставляет_журнала(
    domain_env: Path, pg_dsn: str, retraction_env: str
) -> None:
    привязать_пространства(pg_dsn, "GE", "AM")
    точка_пространства(ТОЧКА, tenant="GE")
    ident = слить_проверку(unit=ТОЧКА, tenant="GE")
    кто = _учётка_уК(pg_dsn)
    with pytest.raises(RetractionError):
        retract_inspection(
            ident,
            tenant="AM",
            reason="не та страна",
            journal=Entry(кто, "HQ", "AM", "inspection.retract", f"inspection:{ident}"),
        )
    assert _журнал(pg_dsn) == []
```

- [ ] **Step 2: Прогнать — ожидается FAIL**

Run: `make test-honest ARGS="tests/test_db_cross_space_doors.py -q -rs"`
Expected: FAIL — `TypeError: retract_inspection() got an unexpected keyword argument 'journal'`.

- [ ] **Step 3: Минимальная реализация**

`src/db/retract.py` (импорт `from .cross_space import Entry, record`):

```python
def retract_inspection(
    inspection_id: str,
    *,
    tenant: str,
    reason: str,
    storage: PhotoStorage | None = None,
    journal: Entry | None = None,
) -> Retraction:
    ...
        with psycopg.connect(settings.dsn) as conn:
            причина, снята = _mark_retracted(
                conn, ident, tenant=tenant_code, reason=записанная_причина
            )
            # Журнал — тем же подключением и ДО уборки кадров: строка живёт
            # ровно столько, сколько пометка (спека «Администрирование»).
            record(conn, journal)
            убрано = _purge_photos(conn, ident, storage=storage)
```

`src/db/accept.py`: параметр `journal: Entry | None = None`; в теле — `record(conn, journal)` между `_open_plan_request(conn, ident, автор)` и `conn.commit()`.
`src/db/move.py`: параметр `journal`; `record(conn, journal)` сразу после `изменено = _apply(...)`, внутри того же `with psycopg.connect(...) as conn`.
`src/db/revise.py`: параметр `journal`; `record(conn, journal)` сразу после `_apply(conn, ...)` внутри `with psycopg.connect(check_environment().dsn) as conn`.
`src/db/letters.py`: параметр `journal`; `record(conn, journal)` после вставки письма внутри `with psycopg.connect(settings.dsn) as conn`.
`src/web/inspections.py`: каждая обёртка получает `journal: Entry | None = None` и передаёт его в дверь без изменений.

- [ ] **Step 4: Прогнать — ожидается PASS; двери целиком**

Run: `make test-honest ARGS="tests/test_db_cross_space_doors.py tests/test_db_retraction.py tests/test_db_accept.py tests/test_db_move.py tests/test_db_revise.py tests/test_db_letters.py -q -rs"`
Expected: PASS, `SKIPPED` нет — прежние наборы дверей не задеты (параметр необязательный).

- [ ] **Step 5: Коммит и пуш**

```bash
git add src/db/retract.py src/db/accept.py src/db/move.py src/db/revise.py src/db/letters.py src/web/inspections.py tests/test_db_cross_space_doors.py
git commit -m "feat: двери проверок пишут журнал действий УК своей транзакцией

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

### Task 9: Веб — проверки: пространство из объекта, УК у партнёра с журналом

| Эндпоинт | Код | Пространство объекта |
|---|---|---|
| `do_retract` | `inspection.retract` | `detail.inspection.tenant_code` |
| `do_accept` | `inspection.accept` | то же |
| `do_revise` | `inspection.revise` | то же |
| `do_move` | `inspection.move` | то же |
| `save_letter` | `inspection.letter` | то же |
| `letter_draft` | `inspection.letter` | то же |
| `google_mail_callback` | `inspection.letter` (письмо) / `prescription.manage` (предписание, объект `HQ`) | проверка письма / `HQ` |

**Files:**
- Modify: `src/web/app.py` — `_refuse_unless_own` (~1399) заменить на `_permit_on_inspection`; маршруты `save_letter` (~987), `do_retract` (~1288), `do_accept` (~1308), `do_revise` (~1333), `do_move` (~1362); `_admin_only` (~1452) и его вызовы из `_render_card` (~1474) — на `can`
- Modify: `src/web/letter_draft.py` — `letter_draft` (~161), `google_mail_callback` (~232)
- Create: `tests/test_web_inspection_rights.py`
- Modify: `tests/test_web_acceptance.py`, `tests/test_web_review.py`, `tests/test_web_spaces_boundary.py` (ожидания по таблице спеки — см. Step 4)

**Interfaces:**
- Consumes: `guard.action`, `guard.permit`, `auth.current_actor`, `cross_space.entry_for` (Task 4), `journal` у обёрток `inspections` (Task 8).
- Produces: `_permit_on_inspection(inspection_id: str, code: str) -> tuple[Any | None, tuple[str, int] | None]` — `(detail, None)` можно; `(None, ответ)` — 404 вне охвата или 403 по `can`. `_may(code: str, object_tenant: str) -> bool` — для показа кнопок карточки (вместо `_admin_only() is None`).

- [ ] **Step 1: Написать падающий тест**

```python
# tests/test_web_inspection_rights.py
"""Действия над проверкой: пространство — из самой проверки, УК у партнёра — в журнал."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from web_harness import СВОЙ, войти, подменить_двери, собрать

from src.web import inspections as data

ПРОВЕРКА = "11111111-1111-1111-1111-111111111111"


def _карточка(tenant: str) -> Any:
    return SimpleNamespace(inspection=SimpleNamespace(tenant_code=tenant, id=ПРОВЕРКА))


@pytest.fixture
def зовы(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    записано: list[dict[str, Any]] = []

    def снять(inspection_id: str, **kw: Any) -> Any:
        записано.append({"id": inspection_id, **kw})
        return SimpleNamespace(photos_purged=0)

    monkeypatch.setattr(data, "retract_card", снять)
    monkeypatch.setattr(data, "retraction_available", lambda: True)
    return записано


def _клиент(monkeypatch: pytest.MonkeyPatch, *, tenant: str, role: str, чья: str):  # type: ignore[no-untyped-def]
    подменить_двери(monkeypatch, tenant=tenant, role=role)
    monkeypatch.setattr(data, "load_card", lambda *_a, **_k: _карточка(чья))
    client = собрать(tenant="HQ").test_client()
    assert войти(client).status_code == 302
    return client


def _снять(client) -> int:  # type: ignore[no-untyped-def]
    return client.post(
        f"/inspections/{ПРОВЕРКА}/retract", data={"reason": "ошибка"}, headers={"Origin": СВОЙ}
    ).status_code


def test_админ_уК_снимает_проверку_партнёра_и_пишет_журнал(
    monkeypatch: pytest.MonkeyPatch, зовы: list[dict[str, Any]]
) -> None:
    клиент = _клиент(monkeypatch, tenant="HQ", role="admin", чья="GE")
    assert _снять(клиент) < 400
    (вызов,) = зовы
    assert вызов["tenant"] == "GE"
    assert вызов["journal"].action_code == "inspection.retract"
    assert вызов["journal"].object_ref == f"inspection:{ПРОВЕРКА}"


def test_своя_проверка_журнала_не_пишет(
    monkeypatch: pytest.MonkeyPatch, зовы: list[dict[str, Any]]
) -> None:
    клиент = _клиент(monkeypatch, tenant="GE", role="admin", чья="GE")
    assert _снять(клиент) < 400
    assert зовы[0]["journal"] is None


def test_админ_страны_не_снимает_проверку_уК(
    monkeypatch: pytest.MonkeyPatch, зовы: list[dict[str, Any]]
) -> None:
    клиент = _клиент(monkeypatch, tenant="GE", role="admin", чья="HQ")
    assert _снять(клиент) == 403
    assert зовы == []


def test_сотрудник_страны_не_снимает_свою(
    monkeypatch: pytest.MonkeyPatch, зовы: list[dict[str, Any]]
) -> None:
    клиент = _клиент(monkeypatch, tenant="GE", role="auditor", чья="GE")
    assert _снять(клиент) == 403
    assert зовы == []
```

- [ ] **Step 2: Прогнать — ожидается FAIL**

Run: `.venv/bin/pytest tests/test_web_inspection_rights.py -q`
Expected: FAIL — админ УК над проверкой `GE` получает 403 (сегодняшний `_refuse_unless_own`), у вызова нет `journal`.

- [ ] **Step 3: Минимальная реализация** (`src/web/app.py`, импорты `from src.db.cross_space import entry_for`, `from src.domain.permissions import can`, `from . import guard`):

```python
def _permit_on_inspection(
    inspection_id: str, code: str
) -> tuple[Any | None, FlaskResponse | None]:
    """Проверка в охвате и право на действие над ней — пространство из самой проверки.

    Вне охвата — 404, как у несуществующей: «нет» и «не видно» неразличимы.
    """
    detail = data.load_card(inspection_id, reach=auth.current_reach())
    if detail is None:
        return None, (render_template("inspections/not_found.html"), 404)  # type: ignore[return-value]
    отказ = guard.permit(code, detail.inspection.tenant_code)
    if отказ is not None:
        return None, отказ  # type: ignore[return-value]
    return detail, None


def _journal(detail: Any, code: str) -> Any:
    """Строка журнала, если человек УК действует в пространстве партнёра."""
    return entry_for(
        auth.current_actor(),
        object_tenant=detail.inspection.tenant_code,
        action=code,
        object_ref=f"inspection:{detail.inspection.id}",
    )


def _may(code: str, object_tenant: str) -> bool:
    """Показывать ли кнопку действия — тот же ответ, что даст маршрут."""
    return can(auth.current_actor(), code, object_tenant).allowed
```

`do_retract`:

```python
    @app.post(f"{section('registry').path}/<inspection_id>/retract")
    @guard.action("inspection.retract", object_in_route=True)
    def do_retract(inspection_id: str) -> FlaskResponse | str | tuple[str, int]:
        detail, отказ = _permit_on_inspection(inspection_id, "inspection.retract")
        if отказ is not None:
            return отказ
        refuse_foreign_origin()
        ...
            done = data.retract_card(
                inspection_id,
                tenant=detail.inspection.tenant_code,
                reason=reason,
                journal=_journal(detail, "inspection.retract"),
            )
```

То же строение — у `do_accept` (`inspection.accept`, `data.accept_card(..., tenant=detail.inspection.tenant_code, journal=_journal(detail, "inspection.accept"))`), `do_revise` (`inspection.revise`), `do_move` (`inspection.move`), `save_letter` (`inspection.letter`; вместо `if not _own(detail)`). Вызовы `_admin_only()` в этих маршрутах удаляются (право теперь в `can`). В `_render_card`: `админ = _admin_only() is None` → флаги кнопок по действию: `can_retract=_may("inspection.retract", detail.inspection.tenant_code)`, `can_move=...`, `can_accept=...`, `can_revise=...` и передать их в шаблон вместо одного `админ` (в шаблоне карточки заменить проверки `admin` на соответствующий флаг). `_admin_only`, `_own`, `_refuse_unless_own` удалить, если у них не осталось вызовов (`make dead` подтвердит).

`src/web/letter_draft.py`: `letter_draft` — `@guard.action("inspection.letter", object_in_route=True)`, `if not auth.is_own(detail.inspection.tenant_code)` → `отказ = guard.permit("inspection.letter", detail.inspection.tenant_code)`; при сохранении письма передать `tenant=detail.inspection.tenant_code` и `journal=entry_for(auth.current_actor(), object_tenant=detail.inspection.tenant_code, action="inspection.letter", object_ref=f"inspection:{inspection_id}")`. `google_mail_callback` — `@guard.action("inspection.letter", "prescription.manage", object_in_route=True)`; ветка письма — то же, что выше; ветка другого вида (`_вернуть_другое`) — первой строкой `отказ = guard.permit("prescription.manage", HQ_TENANT)` и `if отказ is not None: return отказ`.

- [ ] **Step 4: Прогнать — ожидается PASS; веб целиком**

Run: `.venv/bin/pytest tests/test_web_inspection_rights.py tests/test_web_*.py -q`
Expected: новый набор PASS. В прежних наборах ожидаемо краснеют только утверждения таблицы спеки: «аудитор УК не снимает/не переносит/не подтверждает/не правит на приёмке» (у `hq_staff` эти права есть — расхождение 3, В2) и «УК получает 403 на проверке партнёра» (D304: теперь проходит с журналом). Переписать каждое на новое ожидание со ссылкой на расхождение/D304. Любой другой красный — регрессия, разбирать.

- [ ] **Step 5: Коммит и пуш**

```bash
git add src/web/app.py src/web/letter_draft.py tests/test_web_inspection_rights.py
git commit -m "feat: действия над проверкой — пространство из проверки, УК у партнёра с журналом

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

(Шаблон карточки и переписанные наборы — добавить в `git add` поимённо.)

### Task 10: Веб — люди через `can`, журнал, роли из базы

| Эндпоинт | Код | Пространство объекта |
|---|---|---|
| `user_role`, `user_email`, `add_user`, `disable_user` | `people.manage` | пространство из формы (сверено с заведёнными) |
| `bot_unlink` | `people.manage` | пространство учётки, чья привязка; своя — `guard.mark_own()` |

Мост до блока 2: экран людей открыт только людям УК (иначе админ страны получил бы перечень всех пространств). Матрица отвечает на «может ли» — `hq_staff` по-прежнему не управляет никем.

**Files:**
- Modify: `src/web/app.py` — `_hq_admin_only` (~1435) → `_people_permit(target_tenant)`; маршруты ~1117–1285; `_страница_учёток` (`roles=accounts.ROLES` → `role_options`, `role_names`)
- Modify: `src/web/people.py` — `change_role` (~56), `change_email`; `src/web/accounts.py` — `add`, `disable` (параметр `journal`)
- Modify: `src/db/web_access.py` — `create_account`, `reassign_role`, `set_email`, `disable_account` (параметр `journal: Entry | None = None`, `record(conn, journal)` в том же `with _managing(...)`); `src/db/bot_links.py` — `unbind(user_id, *, journal=None)`
- Modify: `src/web/templates/users/index.html` (~строки 113–120, 199–210, 282–286), `src/web/templates/base.html` (~141)
- Modify: `src/web/texts.py` — убрать `users.role.auditor`, `users.role.admin`, `nav.role.admin`, `nav.role.auditor`; добавить `users.role.scope` (ru/en)
- Create: `tests/test_web_people_rights.py`
- Modify: `tests/test_web_users_access.py`, `tests/test_web_users.py` (роль из формы — новые коды)
- Modify: `docs/12-web-admin.md` — строка таблицы «Назначить человеку роль…» (~49)

**Interfaces:**
- Consumes: `guard.permit`, `guard.mark_own`, `entry_for`, `record`, `roles.list_roles() -> tuple[Role, ...]`, `scope_of_tenant`.
- Produces:
  - `people.change_role(*, login, tenant, role, actor_login, actor_tenant, known: Mapping[str, str], journal: Entry | None = None) -> Outcome` — `known`: код роли → охват; неизвестная → `Outcome("role.unknown", 400)`, чужой охват → `Outcome("role.scope", 400)`.
  - `people.change_email(..., journal: Entry | None = None) -> Outcome`.
  - `accounts.add(login, *, tenant, role=ROLE_AUDITOR, journal=None) -> Added`, `accounts.disable(login, *, tenant, journal=None) -> bool`.

- [ ] **Step 1: Написать падающий тест**

```python
# tests/test_web_people_rights.py
"""Люди: people.manage через can, роль из ролей пространства, УК у партнёра — в журнал."""

from __future__ import annotations

from typing import Any

import pytest
from web_harness import СВОЙ, войти, подменить_двери, собрать

from src.db import roles as roles_door
from src.db.roles import Role
from src.web import accounts, people

РОЛИ = (
    Role("hq_admin", "hq", "Админ УК", "HQ admin", frozenset()),
    Role("hq_staff", "hq", "Сотрудник УК", "HQ staff", frozenset()),
    Role("country_admin", "country", "Админ страны", "Country admin", frozenset()),
    Role("country_staff", "country", "Сотрудник страны", "Country staff", frozenset()),
)


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


def _клиент(monkeypatch: pytest.MonkeyPatch, *, tenant: str, role: str):  # type: ignore[no-untyped-def]
    подменить_двери(monkeypatch, tenant=tenant, role=role)
    client = собрать(tenant="HQ").test_client()
    assert войти(client).status_code == 302
    return client


def _назначить(client, роль: str, где: str = "GE") -> int:  # type: ignore[no-untyped-def]
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


def test_текст_чужого_охвата_есть_на_двух_языках() -> None:
    from src.web.texts import TEXTS

    assert set(TEXTS["users.role.scope"]) == {"ru", "en"}
    assert people.Outcome("role.scope", 400).status == 400
```

- [ ] **Step 2: Прогнать — ожидается FAIL**

Run: `.venv/bin/pytest tests/test_web_people_rights.py -q`
Expected: FAIL — `people.change_role` не знает `role.scope`, у вызова нет `journal`, ключа `users.role.scope` нет.

- [ ] **Step 3: Минимальная реализация**

`src/web/app.py`:

```python
def _people_permit(target_tenant: str) -> FlaskResponse | None:
    """Правка людей: мост до блока 2 (экран — только УК) и `people.manage` над пространством."""
    if auth.current_tenant() != HQ_TENANT:
        return render_template("users/forbidden.html"), 403  # type: ignore[return-value]
    return guard.permit("people.manage", target_tenant)  # type: ignore[return-value]


def _people_journal(target_tenant: str, login: str) -> Any:
    return entry_for(
        auth.current_actor(),
        object_tenant=target_tenant,
        action="people.manage",
        object_ref=f"web_user:{login.strip().lower()}",
    )
```

Маршруты `user_role`, `user_email`, `add_user`, `disable_user` — декоратор `@guard.action("people.manage", object_in_route=True)`; первым шагом сегодняшняя проверка `_hq_admin_only()` заменяется на: прочитать пространство из формы (`_пространство_из_формы()`; `None` — тот же 400, что сейчас), затем `отказ = _people_permit(пространство)`. В `_правка_человека` порядок тот же. Вызовы дверей получают `journal=_people_journal(пространство, логин)`. `user_role` передаёт `known={р.code: р.scope for р in roles_door.list_roles()}` в `people.change_role`. `bot_unlink` — `@guard.action("people.manage", object_in_route=True)`; своя привязка → `guard.mark_own()`; чужая — пространство учётки из `accounts.everyone(tenant=None)` по `id`, затем `_people_permit(...)`, `bot_links.unbind(чей, journal=_people_journal(пространство, логин))`.

`_страница_учёток`: `управляет = auth.current_tenant() == HQ_TENANT and can(auth.current_actor(), "people.manage", HQ_TENANT).allowed`; вместо `roles=accounts.ROLES`:

```python
        роли = roles_door.list_roles() if управляет else ()
        подписи = {р.code: (р.name_en if lang == "en" else р.name_ru) for р in роли}
        варианты = {
            охват: tuple(р.code for р in роли if р.scope == охват) for охват in ("hq", "country")
        }
```

(`lang = _lang(conf)`), в шаблон — `role_names=подписи`, `role_options=варианты`, `scope_of=scope_of_tenant`. Отказ базы при чтении ролей — в ту же ветку `except DbError`, что у перечня людей (`перечень_известен = False`).

`src/web/people.py`:

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
    """Назначить роль из ролей пространства. Свою — нельзя."""
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
    ...  # остаток — как сейчас
```

`src/web/texts.py`:

```python
    "users.role.scope": {
        "ru": "Эта роль не для пространства человека: УК — роли УК, стране — роли страны.",
        "en": "This role does not fit the person's space: HQ takes HQ roles, a country takes country roles.",
    },
```

Шаблон `users/index.html`: `t('users.role.' ~ account.role)` → `account.role_name_en if lang == 'en' else account.role_name_ru`; `{% for код in roles %}` в строке человека → `{% for код in role_options[scope_of(человек.tenant)] %}` с подписью `role_names[код]`; в форме заведения — две группы `<optgroup label="{{ t('users.col.space') }}: HQ">` (`role_options['hq']`) и страна (`role_options['country']`). `base.html` ~141: `<small>{{ account.role_name_en if lang == 'en' else account.role_name_ru }}</small>`.

Двери `web_access`: `create_account(..., journal=None)`, `reassign_role(..., journal=None)`, `set_email(..., journal=None)`, `disable_account(..., journal=None)` — `record(conn, journal)` сразу после основного `cur.execute` внутри `with _managing(...) as conn`; `bot_links.unbind(user_id, *, journal=None)` — то же внутри его `with _connected(...)`. Обёртки `accounts.add`, `accounts.disable`, `accounts.reassign_role` пробрасывают `journal`.

- [ ] **Step 4: Прогнать — ожидается PASS; веб и двери**

Run: `.venv/bin/pytest tests/test_web_people_rights.py tests/test_web_users*.py tests/test_web_bot_link.py tests/test_web_texts.py -q`
Expected: PASS после замены в `tests/test_web_users_access.py` и `tests/test_web_users.py` ролей формы `admin`/`auditor` на коды (`country_admin`/`country_staff` для `GE`, `hq_admin`/`hq_staff` для `HQ`) и подменённых `reassign_role`/`disable`, принимающих `journal`.
Run: `make test-honest ARGS="tests/test_db_web_access.py tests/test_db_bot_links.py -q -rs"` → PASS, `SKIPPED` нет.

- [ ] **Step 5: Документация** — `docs/12-web-admin.md`, строка ~49:

```
| Назначить человеку роль (из ролей его пространства: УК — `hq_admin`/`hq_staff`, страна — `country_admin`/`country_staff`) и задать или снять почту для входа через Google — человек УК с правом `people.manage`, людям любого пространства; правка человека партнёра пишется в журнал `cross_space_actions`. До блока 2 админ страны не правит никого | `/users` → `POST /users/role`, `POST /users/email` | `src/web/people.py` → `src/db/web_access.py: reassign_role`, `set_email` |
```

- [ ] **Step 6: Коммит и пуш**

```bash
git add src/web/app.py src/web/people.py src/web/accounts.py src/db/web_access.py src/db/bot_links.py src/web/templates/users/index.html src/web/templates/base.html src/web/texts.py tests/test_web_people_rights.py tests/test_web_users_access.py tests/test_web_users.py docs/12-web-admin.md
git commit -m "feat: правка людей через can, роли пространства из базы, журнал УК

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

### Task 11: Веб — тест полноты на настоящем приложении

**Files:**
- Create: `tests/test_web_action_coverage.py`

**Interfaces:**
- Consumes: `guard.uncovered`, `guard.ACTIONS_ATTR`, `guard.EXEMPT_ENDPOINTS`, `guard.WRITING_GETS` (Task 6); `web_harness.собрать`.
- Produces: тест полноты веба (закрывает #271 со стороны прав).

- [ ] **Step 1: Написать тест** (падает до Tasks 7, 9, 10; если они уже сделаны — FAIL даёт отрицательный прогон ниже)

```python
# tests/test_web_action_coverage.py
"""Каждый пишущий маршрут веба проходит через can с кодом каталога (спека, «Проверка»)."""

from __future__ import annotations

from web_harness import собрать

from src.domain.permissions import ACTION_CODES
from src.web import guard


def test_нет_пишущих_маршрутов_без_кода() -> None:
    assert guard.uncovered(собрать(tenant="HQ")) == []


def test_коды_маршрутов_из_каталога() -> None:
    app = собрать(tenant="HQ")
    коды = {
        код
        for view in app.view_functions.values()
        for код in getattr(view, guard.ACTIONS_ATTR, ())
    }
    assert коды <= ACTION_CODES
    assert коды  # перебор не пуст


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
Expected: PASS. Если `test_нет_пишущих_маршрутов_без_кода` FAIL — он перечисляет эндпоинты без кода: каждому — код по таблицам Tasks 7, 9, 10, либо строка в `guard.EXEMPT_ENDPOINTS` с причиной, если операция личная.

- [ ] **Step 3: Отрицательный прогон**

Снять декоратор `@guard.action("checklist.edit")` у `methodology_add` в `src/web/app.py`, прогнать `PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest tests/test_web_action_coverage.py -q`.
Expected: FAIL `test_нет_пишущих_маршрутов_без_кода` с текстом `methodology_add (/admin/items)`. Вернуть декоратор (`git diff src/web/app.py` пуст), прогнать снова — PASS.

- [ ] **Step 4: Коммит и пуш**

```bash
git add tests/test_web_action_coverage.py
git commit -m "test: полнота прав веба — каждый пишущий маршрут с кодом каталога

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

### Task 12: Бот — роль в привязке, заслон роутеров, тест полноты

| Роутер | Код |
|---|---|
| `start`, `edit`, `records`, `resend`, `finish`, `info`, `record`, `correct`, `material` | `inspection.conduct` |
| `mcp` | `mcp.connect` (поверх круга `mcp_admins`, который остаётся до блока 3) |
| `help`, `lang`, `version`, `stops`, `fallback` | исключения: чтение или личная настройка (расхождение 7) |

**Files:**
- Modify: `src/db/bot_links.py` — `Binding` (~99), `_RESOLVE_BY_USER_SQL`, `_STANDING_SQL`, `_LIVE_BINDINGS_SQL` (~66–87), `_binding(row)`
- Modify: `src/bot/access.py` — `ACTOR_KEY`, `_grants_from_db`, `AccessMiddleware._space_of` → `_actor_of`, `__call__` (~144–206); новая `ActionMiddleware`, `guard_router`, `EXEMPT_ROUTERS`
- Modify: `src/bot/app.py` — `build_dispatcher` (~201–243): роутеры через `guard_router`
- Modify: `src/bot/routers/start.py` (~363, ~392): `may_add_units(space)` → `can(actor, "unit.create", space)`
- Modify: `src/bot/unit_pick.py` (~26), `src/domain/tenants.py` — `may_add_units` удалить, когда вызовов не останется
- Modify: `src/bot/texts.py` — `access.forbidden` (ru/en)
- Modify: `tests/conftest.py` — фикстура `_бот_без_базы_не_знает_привязок` (~345)
- Create: `tests/test_bot_action_coverage.py`
- Modify: тесты, строящие `Binding(...)` (найти: `grep -rln "Binding(" tests`) — добавить `role=`, `grants=`
- Modify: `docs/furca/blocks/bot.md` (раздел «Что блок предоставляет», после `Binding`)

**Interfaces:**
- Consumes: `Actor`, `can`, `DEFAULT_MATRIX`, `ROLE_HQ_STAFF` (Tasks 1–2); `roles.grants_of` (Task 5).
- Produces:
  - `Binding(telegram_id, user_id, login, tenant, bound_at, role: str = "", grants: frozenset[str] = frozenset())`.
  - `access.ACTOR_KEY = "actor"`; обработчики могут принять `actor: Actor`.
  - `access.ActionMiddleware(action: str)`; `access.guard_router(router: Router, action: str) -> Router`; `access.EXEMPT_ROUTERS: Mapping[str, str]` — имя роутера → причина; `access.uncovered_routers(dispatcher: Dispatcher) -> list[str]`.

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

НАСТРОЙКИ = BotSettings(token="123456:TEST", allowed_ids=frozenset({501}), mode="polling")
from src.db.bot_links import Binding, Standing
from src.domain.permissions import DEFAULT_MATRIX, Actor

pytestmark = pytest.mark.asyncio


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


async def test_путь_совместимости_получает_права_hq_staff() -> None:
    mw = AccessMiddleware(frozenset({501}), bindings=None, roster=None)
    данные = await _данные(mw, 501)
    assert данные is not None
    человек: Actor = данные[ACTOR_KEY]
    assert (человек.tenant, человек.role) == ("HQ", "hq_staff")
    assert человек.grants == DEFAULT_MATRIX["hq_staff"]


async def test_привязка_приносит_роль_и_права() -> None:
    привязка = Binding(
        telegram_id=502, user_id="u", login="anna", tenant="GE", bound_at=datetime.now(UTC),
        role="country_staff", grants=DEFAULT_MATRIX["country_staff"],
    )
    кэш = BindingCache(standing=lambda _tg: Standing.live(привязка))
    данные = await _данные(AccessMiddleware(frozenset(), bindings=кэш, roster=None), 502)
    assert данные is not None and данные[ACTOR_KEY].role == "country_staff"


async def test_без_права_обработчик_не_зовётся() -> None:
    вызван: list[bool] = []

    async def handler(_e: Any, _d: dict[str, Any]) -> None:
        вызван.append(True)

    человек = Actor(tenant="GE", role="ghost", grants=frozenset())
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

Настройки собираются так же, как в `tests/test_bot_app.py:32` (`BotSettings(token=..., allowed_ids=..., mode="polling")`).

- [ ] **Step 2: Прогнать — ожидается FAIL**

Run: `.venv/bin/pytest tests/test_bot_action_coverage.py -q`
Expected: FAIL — `ImportError: cannot import name 'ACTOR_KEY' from 'src.bot.access'`.

- [ ] **Step 3: Минимальная реализация**

`src/db/bot_links.py`: `Binding` дописать поля `role: str = ""` и `grants: frozenset[str] = frozenset()`; во все три SQL после `b.bound_at` добавить `, u.role, array(select p.action_code from role_permissions p where p.role_code = u.role order by 1)` (у `_STANDING_SQL` признак `live` остаётся последней колонкой — индекс в `standing` поменять с `row[5]` на `row[7]`); `_binding(row)` заполняет `role=str(row[5])`, `grants=frozenset(row[6])`.

`src/bot/access.py`:

```python
from aiogram import Dispatcher, Router

from src.domain.permissions import ROLE_HQ_STAFF, Actor, can

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


def _grants_from_db(role: str) -> frozenset[str]:
    """Права роли из базы. Отдельной функцией модуля — её подменяют тесты бота без базы."""
    from src.db.roles import grants_of

    return grants_of(role)
```

`AccessMiddleware._space_of` переименовать в `_actor_of(user_id) -> Actor | None`: живая привязка → `Actor(tenant=canonical_tenant(b.tenant), role=b.role, grants=b.grants, user_id=b.user_id)`; путь совместимости → `Actor(tenant=HQ_TENANT, role=ROLE_HQ_STAFF, grants=_grants_from_db(ROLE_HQ_STAFF))`; прочие ветки — `None`, как сейчас. В `__call__`: `actor = await asyncio.to_thread(self._actor_of, user_id)`; `data[SPACE_KEY] = actor.tenant`; `data[ACTOR_KEY] = actor`.

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
            await _answer(event, "access.forbidden")
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

`src/bot/app.py`, `build_dispatcher`: каждый `dispatcher.include_router(build_X_router(...))` для роутеров из таблицы — `dispatcher.include_router(guard_router(build_X_router(...), "inspection.conduct"))`; `mcp` — `guard_router(build_mcp_router(settings), "mcp.connect")`. Имена роутеров (`Router(name=...)`) сверить с ключами `EXEMPT_ROUTERS` — имя берётся из `build_*_router`; несовпадение покажет `test_каждый_роутер_с_кодом_или_в_исключениях`.

`src/bot/routers/start.py`: обработчики, где стоит `may_add_units(space)`, принимают `actor: Actor`; условие → `if not can(actor, "unit.create", space):` (текст отказа `start.unit_new_partner` тот же). `src/bot/unit_pick.py`: убрать реэкспорт `may_add_units`. `src/domain/tenants.py`: удалить `may_add_units`, если `grep -rn "may_add_units" src tests` пуст после правок (тест функции, если есть, удалить вместе с ней — поведение теперь держит таблица прав).

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
        "src.bot.access._grants_from_db", lambda role: DEFAULT_MATRIX.get(role, frozenset())
    )
```

Тесты с `Binding(...)` без роли (`grep -rln "Binding(" tests`) — добавить `role="hq_staff", grants=DEFAULT_MATRIX["hq_staff"]` для `HQ` и `role="country_staff", grants=DEFAULT_MATRIX["country_staff"]` для страны.

- [ ] **Step 4: Прогнать — ожидается PASS; бот целиком**

Run: `.venv/bin/pytest tests/test_bot_action_coverage.py tests/test_bot_*.py -q`
Expected: PASS. Красным может стать только ожидание «сотрудник УК заводит пиццерию в боте» (расхождение 4, В1) — переписать на отказ `start.unit_new_partner` со ссылкой на расхождение. Прочие красные — регрессия.
Run: `make test-honest ARGS="tests/test_db_bot_links.py -q -rs"` → PASS, `SKIPPED` нет.

- [ ] **Step 5: Отрицательный прогон** — убрать `guard_router(...)` вокруг `build_finish_router(store)` в `src/bot/app.py`, `PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest tests/test_bot_action_coverage.py -q` → FAIL с именем роутера `finish`; вернуть, `git diff src/bot/app.py` без этой правки, PASS.

- [ ] **Step 6: Документация** — `docs/furca/blocks/bot.md`, после описания `Binding`:

```
# Binding(..., role, grants): роль учётки и её права — тем же запросом, что привязка
# access.ACTOR_KEY → Actor(tenant, role, grants, user_id) в data апдейта; путь
#   совместимости (ALLOWED_TELEGRAM_IDS, roster.json) — Actor(HQ, hq_staff, права hq_staff)
# guard_router(router, action): внутренняя мидлварь ActionMiddleware — обработчик
#   зовётся, только если can(actor, action, actor.tenant); отказ — access.forbidden
# Коды роутеров: inspection.conduct — start, edit, records, resend, finish, info, record,
#   correct, material; mcp.connect — mcp (поверх круга mcp_admins до блока 3);
#   исключения — access.EXEMPT_ROUTERS. Полноту держит tests/test_bot_action_coverage.py
```

- [ ] **Step 7: Коммит и пуш**

```bash
git add src/db/bot_links.py src/bot/access.py src/bot/app.py src/bot/routers/start.py src/bot/unit_pick.py src/domain/tenants.py src/bot/texts.py tests/conftest.py tests/test_bot_action_coverage.py docs/furca/blocks/bot.md
git commit -m "feat: бот — роль в привязке и can на каждом роутере

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

(Тесты с исправленными `Binding(...)` — добавить поимённо.)

### Task 13: MCP — код действия у инструмента и мост прав из окружения

| Инструменты | Код |
|---|---|
| `add_checklist_item`, `edit_checklist_item`, `remove_checklist_item`, `restore_checklist_item`, `add_zone`, `remove_zone`, `set_zone_shares`, `rename_zone`, `set_route`, `set_scoring`, `add_photo_cue`, `edit_photo_cue`, `set_photo_cue_zone`, `remove_photo_cue` | `checklist.edit` |
| `publish_checklist_version` | `checklist.publish` |
| `create_checklist`, `rename_checklist`, `set_checklist_state`, `set_checklist_bot_access`, `apply_checklist` | `checklist.manage` |
| `retract_learned_phrase`, `repoint_learned_phrase` | `phrases.manage` |
| `retract_inspection` | `inspection.retract` |
| остальные (чтение, в том числе `inspection_letter`) | нет кода |

Мост блока 1: права токена = то, что уже открывает окружение. Хранилище правки методики передано (`MCP_CHECKLIST_TENANTS`) → `checklist.edit`, `checklist.publish`, `checklist.manage`, `phrases.manage`; `may_retract` (`MCP_RETRACTION_TOKENS`) → `inspection.retract`. Пространство объекта — пространство токена: двери MCP пишут только в него (`_aimed`, фильтр снятия по `tenant`). Тексты отказа прежние (`CHECKLIST_CLOSED`, `RETRACTION_CLOSED`) — поведение не меняется.

**Files:**
- Modify: `src/mcp/catalogue.py` — `ToolSpec` (~66–116: поле `action` и `__post_init__`), записи инструментов из таблицы (поле `action=...`)
- Modify: `src/mcp/rpc.py` — `_bridge_actor`, `_call_tool` (~317–322)
- Create: `tests/test_mcp_action_coverage.py`
- Modify: `docs/furca/blocks/mcp.md` — раздел «Откуда берётся арендатор» (~55)

**Interfaces:**
- Consumes: `can`, `Actor`, `ACTION_CODES`, `UnknownAction`, `canonical_tenant`.
- Produces: `ToolSpec.action: str | None = None` (незнакомый код → `UnknownAction` при сборке каталога); `rpc._bridge_actor(*, tenant: str, checklist: Store | None, may_retract: bool) -> Actor`; сигнатура `rpc.handle(...)` не меняется.

- [ ] **Step 1: Написать падающий тест**

```python
# tests/test_mcp_action_coverage.py
"""MCP: каждый пишущий инструмент объявляет код каталога и проходит через can."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.domain.permissions import ACTION_CODES, UnknownAction
from src.mcp import rpc
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


def _пишет(spec: ToolSpec) -> bool:
    return spec.kind == KIND_RETRACTION or (spec.kind == KIND_CHECKLIST and spec.writes)


def test_коды_инструментов_по_таблице() -> None:
    assert {s.name: s.action for s in TOOLS if s.action is not None} == КОДЫ


def test_каждый_пишущий_с_кодом_а_читающий_без() -> None:
    for spec in TOOLS:
        assert (spec.action is not None) == _пишет(spec), spec.name
        assert spec.action is None or spec.action in ACTION_CODES


def test_незнакомый_код_падает_при_сборке() -> None:
    with pytest.raises(UnknownAction):
        ToolSpec(name="x", description="", input_schema={}, handler=lambda **_: {}, action="x.y")


def test_мост_без_права_снятия_отказывает_прежним_текстом() -> None:
    ответ = rpc.handle(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "retract_inspection",
                    "arguments": {"inspection_id": "11111111-1111-1111-1111-111111111111",
                                  "reason": "x"}}},
        tenant="GE",
        may_retract=False,
    )
    assert ответ is not None
    assert rpc.RETRACTION_CLOSED in str(ответ["result"])


def test_мост_с_тенантом_default_правит_как_уК(tmp_path: Path) -> None:
    человек = rpc._bridge_actor(tenant="default", checklist=None, may_retract=True)
    assert человек.tenant == "HQ"
    assert человек.grants == frozenset({"inspection.retract"})
```

- [ ] **Step 2: Прогнать — ожидается FAIL**

Run: `.venv/bin/pytest tests/test_mcp_action_coverage.py -q`
Expected: FAIL — `AttributeError: 'ToolSpec' object has no attribute 'action'`.

- [ ] **Step 3: Минимальная реализация**

`src/mcp/catalogue.py`, в `ToolSpec` после `writes`:

```python
    #: Код действия каталога прав (`src/domain/permissions.py`) — у каждого
    #: пишущего инструмента; у читающего его нет. Полноту держит
    #: `tests/test_mcp_action_coverage.py`.
    action: str | None = None

    def __post_init__(self) -> None:
        if self.action is not None and self.action not in ACTION_CODES:
            raise UnknownAction(f"Инструмент {self.name}: кода «{self.action}» нет в каталоге")
```

(импорт `from src.domain.permissions import ACTION_CODES, UnknownAction`), и в каждую запись из таблицы — `action="..."`.

`src/mcp/rpc.py`:

```python
from src.domain.permissions import Actor, can
from src.domain.tenants import canonical_tenant

#: Права методики, которые мост блока 1 выдаёт вместе с хранилищем правки.
_CHECKLIST_GRANTS = frozenset(
    {"checklist.edit", "checklist.publish", "checklist.manage", "phrases.manage"}
)


def _bridge_actor(*, tenant: str, checklist: Store | None, may_retract: bool) -> Actor:
    """Права токена в блоке 1 — ровно то, что уже открывает окружение (до ролей блока 3)."""
    права = set(_CHECKLIST_GRANTS) if checklist is not None else set()
    if may_retract:
        права.add("inspection.retract")
    return Actor(tenant=canonical_tenant(tenant), role=None, grants=frozenset(права))
```

В `_call_tool` строки

```python
    if spec.kind == KIND_RETRACTION and not may_retract:
        return _tool_text(RETRACTION_CLOSED, failed=True)
```

заменить на

```python
    if spec.action is not None:
        человек = _bridge_actor(tenant=tenant, checklist=checklist, may_retract=may_retract)
        # Пространство объекта — пространство токена: двери MCP пишут только в него.
        if not can(человек, spec.action, человек.tenant):
            закрыто = RETRACTION_CLOSED if spec.kind == KIND_RETRACTION else CHECKLIST_CLOSED
            return _tool_text(закрыто, failed=True)
```

Заслоны `KIND_CHECKLIST and checklist is None` и `KIND_CHECKLIST_SOURCE and source is None` остаются: они закрывают и чтение методики.

- [ ] **Step 4: Прогнать — ожидается PASS; MCP целиком**

Run: `.venv/bin/pytest tests/test_mcp_action_coverage.py tests/test_mcp_*.py -q` → PASS (прежние наборы зелёные — тексты отказа те же).
Run: `make test-honest ARGS="tests/test_mcp_retraction.py tests/test_mcp_retraction_access.py -q -rs"` → PASS, `SKIPPED` нет.

- [ ] **Step 5: Отрицательный прогон** — убрать `action="checklist.edit"` у `add_zone`, `PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest tests/test_mcp_action_coverage.py -q` → FAIL с именем `add_zone`; вернуть, PASS.

- [ ] **Step 6: Документация** — `docs/furca/blocks/mcp.md`, в «Откуда берётся арендатор»:

```markdown
**Права инструментов (спека «Администрирование», блок 1).** У каждого пишущего
инструмента — код действия (`ToolSpec.action`), и вызов идёт через `can`
(`src/domain/permissions.py`). До блока 3 права токена — мост из окружения:
хранилище правки методики (`MCP_CHECKLIST_TENANTS`) даёт `checklist.edit`,
`checklist.publish`, `checklist.manage`, `phrases.manage`; `MCP_RETRACTION_TOKENS` —
`inspection.retract`. Тексты отказа прежние. Полноту держит
`tests/test_mcp_action_coverage.py`.
```

- [ ] **Step 7: Коммит и пуш**

```bash
git add src/mcp/catalogue.py src/mcp/rpc.py tests/test_mcp_action_coverage.py docs/furca/blocks/mcp.md
git commit -m "feat: MCP — код действия у пишущих инструментов и can через мост окружения

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

### Task 14: Сдача блока — CHANGELOG, полный прогон, регрессия, смоук на стенде

**Files:**
- Modify: `CHANGELOG.md` (новая запись сверху)

**Interfaces:**
- Consumes: всё выше.
- Produces: запись журнала изменений; подтверждённые прогоны.

- [ ] **Step 1: Запись CHANGELOG** — сверху, под шапкой:

```markdown
## 2026-10-07 — ядро прав: роли, can и журнал действий УК у партнёра (блок 1 «Администрирование»)

Права теперь решает одна проверка `can` (`src/domain/permissions.py`): граница
пространств зашита в коде, а что может роль — галочки в базе (`roles`,
`role_permissions`, миграция `0038`). Каждый пишущий адрес веба, каждый роутер бота
и каждый пишущий инструмент MCP объявляет код действия и проходит через `can`;
полноту держат тесты. Учётки перенесены: админ и аудитор УК стали `hq_admin` и
`hq_staff`, админ и аудитор страны — `country_admin` и `country_staff`. Что
изменилось для людей — по таблице ролей спеки: человек УК действует над
проверками партнёра (снять, перенести, подтвердить, поправить, письмо) и каждое
такое действие пишется в журнал `cross_space_actions` (миграция `0039`) той же
транзакцией; сотрудник страны больше не правит методику; сотрудник УК снимает,
переносит, подтверждает и правит на приёмке, но не заводит пиццерии — ни в вебе,
ни в боте. MCP работает по прежним переменным окружения; роли токенам — блок 3.
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
1. Накат `0038`, `0039` на базе стенда; `make web-user ARGS="list"` — у каждой учётки код роли по таблице переноса.
2. Вход в веб четырьмя ролями: админ УК снимает проверку партнёра → строка в `cross_space_actions` (`select action_code, object_tenant, object_ref from cross_space_actions order by id desc limit 1`); сотрудник страны на «Методике» получает 403 на сохранение пункта; сотрудник УК — 404 на «Добавить пиццерию»; админ страны — 403 на `/users/role`.
3. Бот стенда: аудитор без привязки (путь совместимости) начинает и сдаёт проверку как раньше.
4. MCP стенда: токен из `MCP_TOKENS` с `MCP_CHECKLIST_TENANTS` правит методику, без `MCP_RETRACTION_TOKENS` снятие отвечает прежним отказом.

Что проверить не удалось — назвать в отчёте прямо, не выдавать за проверенное.

- [ ] **Step 5: Коммит и пуш**

```bash
git add CHANGELOG.md
git commit -m "docs: CHANGELOG — ядро прав, блок 1 «Администрирование»

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push
```

Раскатка на прод — отдельно, только по «да» владельца и в окно 23:00–06:59, с ответами на В1–В3.

## Самопроверка плана

- **Покрытие спеки (только блок 1):** таблицы `roles`, `role_permissions`, FK `web_users.role` — Task 3; `cross_space_actions` — Task 4; миграция ролей и перенос — Task 3; каталог и `can` двумя слоями — Tasks 1–2; таблица прав и прогон на сломанной матрице — Task 2; журнал в той же транзакции — Tasks 4, 8, 9, 10; веб на `can` — Tasks 6, 7, 9, 10; бот — Task 12; MCP — Task 13; тест полноты веб/бот/MCP — Tasks 11, 12, 13; тест миграции «каждая учётка получает роль» — Task 3; доки `12-web-admin`, `blocks/db`, `blocks/bot`, `blocks/mcp`, `08-deploy`, CHANGELOG — Tasks 3, 4, 5, 7, 10, 12, 13, 14. Вне блока 1 и не тронуто: экран «Администрирование», токен ↔ учётка, `tools/list`, `forbidden`, уход env-прав и `mcp_admins`. Пункт спеки «миграция: каждый живой токен сопоставлен или отозван» — блок 3.
- **Имена между задачами:** `Actor`, `Decision`, `can`, `DEFAULT_MATRIX`, `ROLE_SCOPES`, `canonical_role`, `scope_of_tenant`, `validate_matrix` (Tasks 1–2) → `Entry`, `entry_for`, `record` (Task 4) → `Role`, `list_roles`, `grants_of`, `Account.grants` (Task 5) → `guard.action`, `guard.permit`, `guard.mark_own`, `guard.uncovered`, `auth.current_actor` (Task 6) → `ACTOR_KEY`, `ActionMiddleware`, `guard_router`, `uncovered_routers` (Task 12) → `ToolSpec.action`, `_bridge_actor` (Task 13).
- **Плейсхолдеры:** единственная подставляемая величина — отпечатки миграций в `ОТПЕЧАТКИ`, и команда, которая её печатает, дана в Task 3 Step 4.
