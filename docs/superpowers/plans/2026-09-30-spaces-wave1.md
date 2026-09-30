# Пространства (волна 1): план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Человек привязан к пространству: в боте полем приглашения, в админке полем учётки. Граница проверяется на сервере на каждом запросе: в вебе, в двери методики, в MCP и в боте. Чужое по прямому адресу получает «не найден» тем же ответом, что несуществующее. Эталон УК — единственное исключение из границы, и только на чтение.

**Architecture:** Пространство — это уже существующий тенант (`tenants.code`, `web_users.tenant_code`, `mcp_tokens.tenant_code`, `inspections.tenant_code`). Каталог пространства в хранилище методики — тот же код строчными (`HQ` → `hq`, D183). Сегодня тенант приходит из конфига поверхности (`WEB_TENANT`, `BOT_MCP_TENANT`, константа `UK_TENANT` бота, пространство `hq` MCP по умолчанию). Волна меняет источник на человека: веб берёт тенант у учётки из сессии, бот — у связки Telegram ID из приглашения, MCP — у токена (так уже есть для проверок, волна распространяет это на методику). Все запросы `src/db/queries.py` уже фильтруют по `tenant=`, и держать границу там не нужно: меняется только то, что в них передаётся.

**Tech Stack:** Python 3.12, Flask + Jinja (`src/web`), aiogram 3 (`src/bot`), psycopg 3 + Postgres (`src/db`), свой JSON-RPC MCP (`src/mcp`), pytest.

**Spec:** `docs/superpowers/specs/2026-09-28-checklist-admin-design.md`, разделы «Пространства», «Заслоны», «Волны» (согласована, D227). Решения: D182, D183, D233, D234, D240, D261–D264, D278. Задача-родитель #340 (часть #423). Смежная спека: `docs/superpowers/specs/2026-09-30-country-and-prescriptions-design.md`, раздел «Доступы».

## Вопросы владельцу

Каждый вопрос — развилка, которую спека и решения не закрывают. План построен на варианте «по умолчанию», и у каждого вопроса названа задача, которая меняется, если владелец выберет другое. Ни одно решение ниже в `decisions.md` не записано: записывать будет тот, кто услышит ответ.

1. **Логин общий на все пространства или свой внутри каждого?** Сегодня логин уникален внутри тенанта (`0014_web_accounts.sql`: «`director` в двух странах — два разных человека»), и стенд отвечает за один тенант. Один адрес админки на всех требует знать, в какое пространство входит человек. **По умолчанию:** логин и почта Google уникальны во всей базе, форма входа не меняется (задача 7). Альтернатива — поле «пространство» на форме входа; меняет задачу 7 и шаблон `login.html`.
2. **Что видно через границу в «Проверках» и «Обзоре».** Спека чек-листов: «Проверка пишется в пространство аудитора. Отчёты, реестр, „Обзор“ — внутри пространства». При этом D261 говорит «УК видит всё», а критерий приёмки спеки страны — «партнёр Грузии видит запрос» по проверке, которую провела УК. Это две разные вещи: (а) видит ли УК проверки, проведённые аудиторами партнёра; (б) видит ли партнёр проверки УК по своим пиццериям. **По умолчанию в волне 1:** граница строгая в обе стороны, как в спеке чек-листов. Расширение — отдельной работой после ответа; тенант во всех чтениях приходит из одной функции `auth.current_tenant()` (задача 8), и расширять придётся её и запросы, а не обработчики.
3. **Откуда у партнёра справочник пиццерий.** Точка проверки ссылается на точку своего тенанта (`inspections_unit_same_tenant` в `0027_tenant_hq.sql`), а заводить пиццерии партнёру нельзя (D234). Значит, у пространства партнёра пустой справочник, и его аудитор не начнёт ни одной проверки. **По умолчанию:** команда `make space ARGS="units GE --country GE"` копирует точки названных стран из HQ в пространство партнёра (задача 11). Альтернатива — общий справочник на всю сеть; это смена схемы (`units` без тенанта) и отдельная миграция прод-базы.
4. **Какие чек-листы УК видит бот партнёра.** D227: «эталон доступен везде, всем и всегда — в том числе в боте любого партнёра». **По умолчанию:** партнёру в боте видны все чек-листы УК в работе, с опубликованным изданием и пунктами (те же заслоны, что у галочки), независимо от того, открыла ли их УК своим аудиторам (задача 3). Альтернатива — ровно те, что УК открыла в своём боте; меняется одно условие в `available()`.
5. **Приглашение в бот — по юзернейму или по ссылке.** Спека: «приглашённый по ссылке пространства партнёра». В коде ссылок нет: приглашение — строка `BOT_INVITES` с юзернеймом (`src/bot/invites.py`). **По умолчанию:** та же строка с кодом пространства впереди, `GE/petrov:Пётр Петров` (задача 4). Ссылка вида `t.me/<бот>?start=<метка>` — новый механизм выдачи и гашения меток, в волну не входит.
6. **Демо-стенд.** Веб-стенд работает тенантом `demo` (`Makefile`, `WEB_STAND_TENANT ?= demo`). После волны `demo` — такое же пространство партнёра: эталон в «Методике» открывается только на чтение, правка отказывает. **По умолчанию:** демо остаётся партнёрским видом (задача 12 проверяет, что стенд поднимается и показывает отказ правки, а не падение). Альтернатива — перевести демо на `HQ`; меняет `tools/seed_web_demo.py` (`DEMO_TENANT`) и `WEB_STAND_TENANT`.
7. **Свой админ «Людей» у партнёра.** D182: единственная роль — админ, заводящий пространства и людей. Сегодня роль `admin` у учётки открывает экран «Люди» внутри её тенанта. **По умолчанию:** роль `admin` у учётки партнёра заводит и отключает людей только своего пространства; выдаётся роль только командой (задача 8 сохраняет это поведение, меняя тенант на тенант вошедшего). Альтернатива — «Люди» только для HQ: одна строка `hq_only=True` в реестре разделов (задача 10).

## Global Constraints

- Сущности связываются кодами, не формулировками (CLAUDE.md). Пространство связывается кодом тенанта; каталог хранилища — тот же код строчными.
- Язык — параметр: каждый новый текст заводится в `src/web/texts.py` и `src/bot/texts.py` на `ru` и `en` в одном изменении (скилл `product-i18n`).
- Оценка только через движок; ставки и пороги в коде не дублировать.
- Регресс-сверка после изменений: `cd examples/belgrade-1 && python3 ../../engine/audit.py score` → 97.5%, A, 5×D1; `cd ../belgrade-2 && python3 ../../engine/audit.py score` → 97.0%, A, 6×D1.
- Тесты с базой гоняются на тестовой базе MUSPELHEIM (`make test`, `TEST_DATABASE_URL` из файла окружения). Локальный Postgres и стенды на Маке не поднимаются.
- Значения секретов не читаются (`.env`, `printenv` закрыты хуком).
- Чужое по прямому адресу — «не найден» тем же кодом и тем же текстом, что несуществующее. Правка эталона из пространства партнёра — отказ сервера со словами «эталон правит только УК».
- Каждый заслон этого плана прогоняется на сломанном коде: заслон временно ломается, тест обязан упасть с понятной причиной, затем правка возвращается. Шаг «негативный прогон» в задачах — обязательный, не для галочки.
- Раскатка — только по «да» владельца и в ночное окно (скилл `deploy-window`). План заканчивается PR, не раскаткой. Миграция `0028` на проде — отдельное «да».

## Review Focus

Пять дыр границы, которые вероятнее всего укусят. Тест к каждой стоит в задаче, где живёт код.

1. **MCP-токен партнёра без аргумента `checklist`.** `for_code(store, None)` идёт по единому указателю прода `<store>/current`, а он смотрит в `hq`. Правящий инструмент партнёра без кода правил бы эталон. Ожидание: партнёр без кода получает «назовите чек-лист», эталон не тронут. Тест — задача 2.
2. **Бот: проверка чужого пространства в чате и кнопки со старых сообщений.** Состояние проверки привязано к чату, а не к человеку: в общем чате (или после переезда человека в другое пространство) нажатие старой кнопки «Зона»/«Удалить» или новое фото дописывали бы чужую проверку. Ожидание: апдейт до обработчика не доходит, человек получает одну строку «эта проверка ведётся в другом пространстве». Тест — задача 5.
3. **Кадр, отчёт, письмо по чужой проверке по прямому адресу.** `/inspections/<id>/photos/<photo_id>`, `/report`, `/letter`, `/letter/save`, `/retract`, `/move` с id проверки другого пространства. Ожидание: 404 тем же шаблоном, что у несуществующего id, и ни одного вызова двери записи. Тест — задача 8.
4. **Методика: чужой код в адресе и правка эталона.** `/admin?checklist=<код другого партнёра>` и любой POST раздела «Методика» с кодом эталона от партнёра. Плюс тихая копия: дверь хранилища на нетронутом каталоге пространства заводит его снимком боевой методики (`checklist._bootstrap`) — у партнёра появилась бы копия эталона без правки. Ожидание: чужой код — тот же текст, что у несуществующего; POST — отказ, журнал эталона не вырос, каталог партнёра не появился. Тест — задачи 1 и 9.
5. **Вход: учётка другого пространства через общий адрес.** После снятия фильтра `tenant_code = <стенд>` из сверки сессии отключённая учётка, почта Google, привязанная к двум учёткам, или логин-двойник в двух пространствах открывали бы не того человека. Ожидание: отключённая не входит, двойник не заводится (миграция отказывает на двойниках), сессия несёт тенант своей учётки. Тест — задача 7.

---

## Перед началом

- [ ] `git fetch origin && git switch -c feat/spaces-wave1 origin/main` в своём worktree (скилл `worktrees`).
- [ ] Базовый прогон: `make test` (тестовая база MUSPELHEIM) и регресс-сверка belgrade. Записать число упавших ДО работы: известная помеха #348 (тестовая база не чистится между запусками) красит проверки доступа, и её падения не должны читаться как регрессия волны.
- [ ] Ветка `feat/country-screen` (волна 1 экрана страны) добавляет новые `conf.tenant` в `src/web/app.py`. Кто вливается вторым, тот прогоняет тест задачи 8 `tests/test_web_tenant_source.py` после слияния: он поймает каждое новое место.

## Карта файлов

| Файл | Что меняется |
|---|---|
| `src/mcp/checklist_layout.py` | `space_of`, `visible_spaces`, `exists`, `locate`, `may_write`; `for_code` не переходит в чужое пространство |
| `src/mcp/checklists.py` | `overview(spaces=)`, `apply_to_production` только в `hq`, коды не повторяются между эталоном и пространством, `_settle_inherited` в своём пространстве |
| `src/mcp/checklist.py` | `_ensure` заводит снимком боевой методики только `hq` |
| `src/mcp/server.py`, `src/mcp/rpc.py`, `src/mcp/checklists_tools.py` | хранилище по тенанту токена; правящий инструмент — только своё пространство |
| `src/domain/bot_checklists.py`, `src/domain/state.py` | чек-листы бота по пространству аудитора |
| `src/bot/invites.py`, `src/bot/roster.py`, `src/bot/access.py` | пространство в приглашении, в связке и в данных апдейта; заслон чата |
| `src/bot/routers/start.py`, `src/bot/routers/mcp.py`, `src/bot/unit_pick.py`, `src/bot/phrases.py`, `src/bot/config.py`, `src/bot/app.py`, `src/bot/texts.py` | тенант человека вместо констант и `BOT_MCP_TENANT` |
| `src/db/migrations/0028_login_across_spaces.sql` | логин и почта уникальны во всей базе |
| `src/db/web_access.py` | вход и сессия без тенанта стенда; заведение и перечень пространств |
| `src/web/auth.py`, `src/web/app.py`, `src/web/letter_draft.py`, `src/web/methodology.py`, `src/web/sections.py`, `src/web/texts.py` | тенант вошедшего; методика по пространству; разделы «только HQ» |
| `tools/space.py` (новый), `tools/web_user.py`, `Makefile` | команда пространств; учётка только в заведённое пространство |
| `docs/12-web-admin.md`, `docs/06-mvp-bot.md`, `docs/08-deploy.md`, `docs/furca/blocks/{bot,web,mcp,db}.md`, `.env.example`, `CHANGELOG.md` | описание нового поведения и переменных |

Ядро (тесты до кода, правило тестирования): задачи 1, 2, 5, 7, 8, 9, 10 — заслоны доступа. Задачи 3, 4, 6, 11 — тест на поведение плюс прогон.

---

### Task 1: Пространства в раскладке хранилища методики

**Files:**
- Modify: `src/mcp/checklist_layout.py` (после `check_slug`, и `for_code` строки 318–335)
- Modify: `src/mcp/checklists.py` (`overview` строка 139, `create` строка 271, `apply_to_production` строка 476, `_settle_inherited` строка 581)
- Modify: `src/mcp/checklist.py` (`_ensure` строка 566)
- Test: `tests/test_mcp_spaces.py` (новый)

**Interfaces:**
- Produces:
  - `space_of(tenant: str) -> str` — каталог пространства: `"HQ"` → `"hq"`; негодный код → `ChecklistError`.
  - `visible_spaces(tenant: str) -> tuple[str, ...]` — `("hq",)` у УК, `(<своё>, "hq")` у партнёра; своё всегда первое.
  - `exists(store: Store) -> bool` — у пары «пространство + код» есть издания или карточка (тот же признак, что в `known`).
  - `locate(store: Store, *, tenant: str, code: str | None) -> Store | None` — хранилище, наведённое на видимый этому тенанту чек-лист; `None` — «не найден» (чужой и несуществующий неразличимы).
  - `may_write(store: Store, *, tenant: str) -> bool` — правка разрешена только в своём пространстве.
  - `overview(store: Store, *, spaces: tuple[str, ...] | None = None) -> list[Overview]` — `None` значит все (для команд обслуживания), иначе только названные.

- [ ] **Step 1: Написать падающие тесты**

```python
"""Волна 1 пространств (#340): граница пространств в хранилище методики.

Ядро — тихий переход в чужое пространство. Код чек-листа приходит снаружи, а
единый указатель прода смотрит в `hq`: любая дорога «по умолчанию» уводит
партнёра в эталон. Поэтому сторожится не «функция вернула хранилище», а В КАКОЕ
пространство оно наведено и что бывает с чужим кодом.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest
from mcp_checklist_harness import build_methodology

from src.domain.tenants import HQ_TENANT
from src.mcp.checklist import Store, current_version, read_journal
from src.mcp.checklist_layout import (
    DEFAULT_SPACE,
    applied,
    for_code,
    locate,
    may_write,
    space_of,
    visible_spaces,
)
from src.mcp.checklists import apply_to_production, create, overview
from src.mcp.errors import ChecklistError

СЕГОДНЯ = date(2026, 9, 30)


@pytest.fixture
def склад(tmp_path: Path) -> Store:
    """Эталон `hq/bizdev`, у партнёра GE свой `own`, у партнёра AM свой `rnd`."""
    store = Store(root=tmp_path / "хранилище", live=build_methodology(tmp_path / "методика"))
    current_version(store)
    assert applied(store.root) == (DEFAULT_SPACE, "bizdev")
    create(replace(store, space="ge", code="own"), tenant="GE", name_ru="Свой", name_en="Own", today=СЕГОДНЯ)
    create(replace(store, space="am", code="rnd"), tenant="AM", name_ru="РНД", name_en="RnD", today=СЕГОДНЯ)
    return store


def test_каталог_пространства_это_код_тенанта_строчными() -> None:
    assert space_of(HQ_TENANT) == DEFAULT_SPACE
    assert space_of("GE") == "ge"


def test_негодный_код_тенанта_не_становится_путём() -> None:
    with pytest.raises(ChecklistError):
        space_of("../hq")


def test_партнёр_видит_своё_и_эталон_а_уК_только_своё() -> None:
    assert visible_spaces(HQ_TENANT) == ("hq",)
    assert visible_spaces("GE") == ("ge", "hq")


def test_чужой_код_неотличим_от_несуществующего(склад: Store) -> None:
    assert locate(склад, tenant="GE", code="rnd") is None
    assert locate(склад, tenant="GE", code="nothing") is None


def test_партнёр_находит_эталон_и_своё(склад: Store) -> None:
    эталон = locate(склад, tenant="GE", code="bizdev")
    своё = locate(склад, tenant="GE", code="own")
    assert эталон is not None and (эталон.space, эталон.code) == ("hq", "bizdev")
    assert своё is not None and (своё.space, своё.code) == ("ge", "own")


def test_уК_не_видит_чек_листов_партнёра(склад: Store) -> None:
    assert locate(склад, tenant=HQ_TENANT, code="own") is None


def test_без_кода_партнёр_получает_эталон_на_чтение(склад: Store) -> None:
    найдено = locate(склад, tenant="GE", code=None)
    assert найдено is not None and (найдено.space, найдено.code) == ("hq", "bizdev")
    assert may_write(найдено, tenant="GE") is False


def test_указатель_прода_не_уводит_в_чужое_пространство(склад: Store) -> None:
    """Review Focus 1: дорога «по умолчанию» партнёра обязана остаться у него."""
    наведено = for_code(replace(склад, space="ge"), None)
    assert наведено.space == "ge"


def test_правка_только_в_своём_пространстве(склад: Store) -> None:
    assert may_write(replace(склад, space="hq"), tenant=HQ_TENANT) is True
    assert may_write(replace(склад, space="ge"), tenant="GE") is True
    assert may_write(replace(склад, space="hq"), tenant="GE") is False
    assert may_write(replace(склад, space="am"), tenant="GE") is False


def test_перечень_сужается_до_видимых(склад: Store) -> None:
    видно = {(c.space, c.code) for c in overview(склад, spaces=visible_spaces("GE"))}
    assert видно == {("hq", "bizdev"), ("ge", "own")}


def test_партнёр_не_применяет_к_проду(склад: Store) -> None:
    """Указатель прода один на хранилище и принадлежит УК."""
    with pytest.raises(ChecklistError, match="только УК"):
        apply_to_production(replace(склад, space="ge", code="own"), tenant="GE")
    assert applied(склад.root) == ("hq", "bizdev")


def test_код_эталона_не_заводится_в_пространстве_партнёра(склад: Store) -> None:
    with pytest.raises(ChecklistError, match="эталон"):
        create(replace(склад, space="ge", code="bizdev"), tenant="GE", name_ru="Копия", name_en="Copy", today=СЕГОДНЯ)


def test_уК_не_заводит_код_занятый_партнёром(склад: Store) -> None:
    with pytest.raises(ChecklistError, match="занят"):
        create(replace(склад, space="hq", code="own"), tenant=HQ_TENANT, name_ru="Своё", name_en="Own", today=СЕГОДНЯ)


def test_нетронутое_пространство_партнёра_не_заводится_копией_боевой_методики(
    tmp_path: Path,
) -> None:
    """Review Focus 4: снимок боевой методики — только первый чек-лист УК."""
    пусто = Store(root=tmp_path / "пусто", live=build_methodology(tmp_path / "м"), space="ge")
    with pytest.raises(ChecklistError):
        current_version(пусто)
    assert not (tmp_path / "пусто" / "ge").exists()


def test_журнал_эталона_не_растёт_от_отказов_партнёра(склад: Store) -> None:
    эталон = replace(склад, space="hq", code="bizdev")
    было = len(read_journal(эталон))
    with pytest.raises(ChecklistError):
        apply_to_production(replace(склад, space="ge", code="own"), tenant="GE")
    assert len(read_journal(эталон)) == было
```

- [ ] **Step 2: Прогнать и убедиться, что падают**

Run: `.venv/bin/pytest tests/test_mcp_spaces.py -q --no-cov`
Expected: FAIL — `ImportError: cannot import name 'locate' from 'src.mcp.checklist_layout'`.

- [ ] **Step 3: Реализация в `src/mcp/checklist_layout.py`**

Константы `META_FILE` и `VERSIONS_DIR` уже есть в модуле (ими пользуется `known`). `src.domain.tenants` здесь не импортируется: `src.domain` при загрузке тянет `bot_checklists`, а тот — этот модуль, и вышел бы круг. Связь `HQ` ↔ `hq` держит тест `test_каталог_пространства_это_код_тенанта_строчными`.

```python
def space_of(tenant: str) -> str:
    """Каталог пространства в хранилище для кода тенанта: `HQ` → `hq` (D183).

    Одно правило на все поверхности. Код тенанта приходит из учётки, связки бота
    или токена MCP и становится куском пути — поэтому проходит `check_slug`.
    """
    return check_slug((tenant or "").strip().lower(), что="Код пространства")


def visible_spaces(tenant: str) -> tuple[str, ...]:
    """Пространства, которые тенант видит: своё первым, эталон УК следом (D224).

    Своё первым — не для красоты: при поиске по коду своё выигрывает, и копия
    партнёра (волна 4) не подменяется эталоном с тем же кодом.
    """
    своё = space_of(tenant)
    return (своё,) if своё == DEFAULT_SPACE else (своё, DEFAULT_SPACE)


def exists(store: Store) -> bool:
    """Есть ли такой чек-лист: издания или карточка — тот же признак, что у `known`."""
    return (store.home / VERSIONS_DIR).is_dir() or (store.home / META_FILE).is_file()


def locate(store: Store, *, tenant: str, code: str | None) -> Store | None:
    """Хранилище, наведённое на видимый тенанту чек-лист, или `None` — «не найден».

    `None` один на «нет такого» и «есть, но чужой»: иначе ответ подтверждал бы,
    что чужое существует (спека, «Пространства»). Нетронутое хранилище УК
    отдаётся как есть: его заводит первый заход двери (`checklist._ensure`).
    """
    видимые = visible_spaces(tenant)
    нетронуто = видимые[0] == DEFAULT_SPACE and not known(store.root)
    if code is None:
        for space in видимые:
            найдено = for_code(replace(store, space=space), None)
            if exists(найдено):
                return найдено
        return replace(store, space=DEFAULT_SPACE, code=DEFAULT_CODE) if нетронуто else None
    код = check_slug(code, что="Код чек-листа")
    for space in видимые:
        кандидат = replace(store, space=space, code=код)
        if exists(кандидат):
            return кандидат
    return replace(store, space=DEFAULT_SPACE, code=код) if нетронуто else None


def may_write(store: Store, *, tenant: str) -> bool:
    """Правка — только в своём пространстве. Эталон у партнёра — чтение (D224)."""
    return store.space == space_of(tenant)
```

И в `for_code` после `space, чей = в_проде`:

```python
    # Указатель прода один на хранилище и смотрит в пространство УК. Партнёр,
    # не назвавший чек-лист, остаётся у себя: иначе правка «без кода» уходила
    # бы в эталон (Review Focus 1).
    if space != store.space:
        return store
```

- [ ] **Step 4: Реализация в `src/mcp/checklists.py`**

`overview` получает необязательный фильтр:

```python
def overview(store: Store, *, spaces: tuple[str, ...] | None = None) -> list[Overview]:
    ...
    for space, code in known(store.root):
        if spaces is not None and space not in spaces:
            continue
        ...
```

В `create` сразу после отказа «уже есть» (`if свой.home.exists(): ...`):

```python
    занят = [s for s, c in known(store.root) if c == code and s != space]
    if space != DEFAULT_SPACE and DEFAULT_SPACE in занят:
        raise ChecklistError(
            f"Код «{code}» — код чек-листа эталона УК. Эталон виден в вашем пространстве "
            f"под этим кодом; заведите свой чек-лист под другим кодом"
        )
    if space == DEFAULT_SPACE and занят:
        raise ChecklistError(
            f"Код «{code}» занят чек-листом пространства партнёра. Коды эталона и "
            f"чек-листов партнёров не повторяются: партнёр видит эталон рядом со своими"
        )
```

В `apply_to_production` первой строкой после `_alive(store)`:

```python
    if store.space != DEFAULT_SPACE:
        raise ChecklistError(
            "К проду применяет только УК: указатель прода один на всю сеть. "
            "В пространстве партнёра доступ в боте задаётся галочкой «в боте»"
        )
```

В `_settle_inherited` цикл `for space, code in known(store.root):` получает `if space != store.space: continue` — наследованный флаг фиксируется только в пространстве, где идёт правка.

- [ ] **Step 5: Реализация в `src/mcp/checklist.py`**

В `_ensure` перед `return _bootstrap(store)`:

```python
    # Снимком боевой методики заводится только эталон УК. В пространстве
    # партнёра такая копия была бы копией эталона без единой правки — ровно
    # то, что D226 запрещает (Review Focus 4).
    if store.space != DEFAULT_SPACE:
        raise ChecklistError(
            f"Чек-листа «{store.code}» в пространстве «{store.space}» нет. Перечень отдаёт "
            f"checklists, завести новый — create_checklist"
        )
```

- [ ] **Step 6: Прогнать тесты**

Run: `.venv/bin/pytest tests/test_mcp_spaces.py tests/test_mcp_checklists.py tests/test_mcp_checklist_layout.py tests/test_mcp_checklist_store.py -q --no-cov`
Expected: PASS.

- [ ] **Step 7: Негативный прогон**

По одному, с возвратом после каждого: убрать `if space != store.space: return store` из `for_code` → падает `test_указатель_прода_не_уводит_в_чужое_пространство`; в `locate` заменить `видимые` на все пространства из `known` → падает `test_чужой_код_неотличим_от_несуществующего`; убрать проверку в `apply_to_production` → падает `test_партнёр_не_применяет_к_проду`. Каждый раз убедиться, что правка действительно применилась (`git diff` не пуст), иначе «негативный прогон» ложно зелёный.

- [ ] **Step 8: Commit**

```bash
git add src/mcp/checklist_layout.py src/mcp/checklists.py src/mcp/checklist.py tests/test_mcp_spaces.py
git commit -m "feat(mcp): граница пространств в хранилище методики (волна 1, #340)"
```

---

### Task 2: MCP — хранилище методики по тенанту токена

**Files:**
- Modify: `src/mcp/server.py` (`_checklist_for` строка 301, `_checklist_source_for` строка 317)
- Modify: `src/mcp/rpc.py` (`_call_tool`, строка 238: `for_checklist(база, код)`)
- Modify: `src/mcp/checklists_tools.py` (`checklists`, `checklist_meta`)
- Modify: `tests/test_mcp_checklist_access.py`, `tests/test_mcp_checklists_tools.py` (константа тенанта УК)
- Test: `tests/test_mcp_spaces_rpc.py` (новый)

**Interfaces:**
- Consumes: `space_of`, `visible_spaces`, `for_code`, `DEFAULT_SPACE` (Task 1).
- Produces: `rpc.NAME_THE_CHECKLIST: str` — отказ правящему инструменту партнёра без кода; `_checklist_for(settings, tenant)` возвращает `Store` с `space=space_of(tenant)`; `_checklist_source_for` — с `space=DEFAULT_SPACE`.

- [ ] **Step 1: Написать падающие тесты**

```python
"""Волна 1 (#340): MCP правит методику только в пространстве токена.

Тенант приходит из токена и ниоткуда больше (T098). Волна добавляет второе
следствие: пространство хранилища — тоже из токена. Эталон партнёр читает
исходником (T315), а правящий инструмент получает только своё пространство.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from mcp_checklist_harness import build_methodology

from src.mcp.checklist import Store, current_version, read_journal
from src.mcp.checklists import create
from src.mcp.config import MIN_TOKEN_LENGTH, Settings
from src.mcp.rpc import NAME_THE_CHECKLIST, handle
from src.mcp.server import _checklist_for, _checklist_source_for

ПАРТНЁР = "GE"


@pytest.fixture
def настройки(tmp_path: Path) -> Settings:
    методика = build_methodology(tmp_path / "методика")
    store = Store(root=tmp_path / "хранилище", live=методика)
    current_version(store)
    create(replace(store, space="ge", code="own"), tenant=ПАРТНЁР, name_ru="Свой", name_en="Own", today=date(2026, 9, 30))
    return Settings(
        tokens={"p" * MIN_TOKEN_LENGTH: ПАРТНЁР},
        tenants=(ПАРТНЁР,),
        host="127.0.0.1",
        port=0,
        checklist_store=store.root,
        # Партнёру правка открыта нарочно: проверяется, КУДА она попадает.
        checklist_tenants=(ПАРТНЁР,),
        data_dir=методика,
    )


def _вызов(имя: str, аргументы: dict[str, Any], настройки: Settings) -> dict[str, Any]:
    ответ = handle(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": имя, "arguments": аргументы}},
        tenant=ПАРТНЁР,
        checklist=_checklist_for(настройки, ПАРТНЁР),
        source=_checklist_source_for(настройки, ПАРТНЁР),
    )
    assert ответ is not None
    return ответ


def _текст(ответ: dict[str, Any]) -> str:
    return "".join(блок.get("text", "") for блок in ответ["result"]["content"])


def test_правка_партнёра_наведена_на_его_пространство(настройки: Settings) -> None:
    store = _checklist_for(настройки, ПАРТНЁР)
    assert store is not None and store.space == "ge"


def test_исходник_эталона_читается_из_пространства_уК(настройки: Settings) -> None:
    store = _checklist_source_for(настройки, ПАРТНЁР)
    assert store is not None and store.space == "hq"


def test_правящий_инструмент_без_кода_не_уходит_в_эталон(настройки: Settings) -> None:
    """Review Focus 1."""
    assert настройки.checklist_store is not None
    эталон = Store(root=настройки.checklist_store, live=настройки.data_dir, space="hq", code="bizdev")  # type: ignore[arg-type]
    было = len(read_journal(эталон))

    ответ = _вызов("set_checklist_state", {"state": "retired"}, настройки)

    assert ответ["result"].get("isError") is True
    assert NAME_THE_CHECKLIST in _текст(ответ)
    assert len(read_journal(эталон)) == было


def test_код_эталона_в_правящем_инструменте_это_не_найден(настройки: Settings) -> None:
    ответ = _вызов("set_checklist_state", {"checklist": "bizdev", "state": "retired"}, настройки)
    assert ответ["result"].get("isError") is True
    assert "нет" in _текст(ответ)


def test_перечень_партнёра_без_чужих_пространств(настройки: Settings, tmp_path: Path) -> None:
    assert настройки.checklist_store is not None and настройки.data_dir is not None
    create(
        Store(root=настройки.checklist_store, live=настройки.data_dir, space="am", code="rnd"),
        tenant="AM", name_ru="РНД", name_en="RnD", today=date(2026, 9, 30),
    )
    ответ = _вызов("checklists", {}, настройки)
    assert "rnd" not in _текст(ответ)
    assert "own" in _текст(ответ) and "bizdev" in _текст(ответ)
```

- [ ] **Step 2: Прогнать и убедиться, что падают**

Run: `.venv/bin/pytest tests/test_mcp_spaces_rpc.py -q --no-cov`
Expected: FAIL — `ImportError: cannot import name 'NAME_THE_CHECKLIST'`.

- [ ] **Step 3: Реализация**

`src/mcp/server.py`:

```python
from .checklist_layout import DEFAULT_SPACE, space_of
...
    return Store(root=хранилище, live=методика, space=space_of(tenant))   # в _checklist_for
...
    return Store(root=хранилище, live=методика, space=DEFAULT_SPACE)      # в _checklist_source_for
```

`src/mcp/rpc.py` — константа рядом с `CHECKLIST_CLOSED` и наведение вместо `for_checklist(база, код)`:

```python
NAME_THE_CHECKLIST = (
    "Назовите чек-лист аргументом checklist: правка без кода в пространстве "
    "партнёра не наводится ни на какой чек-лист, перечень отдаёт checklists"
)


def _aimed(kind: str, база: Store, *, tenant: str, код: str | None) -> Store:
    """Хранилище, наведённое на чек-лист: исходник — эталон, правка — своё пространство."""
    if kind == KIND_CHECKLIST_SOURCE:
        return for_checklist(replace(база, space=DEFAULT_SPACE), код)
    свой = replace(база, space=space_of(tenant))
    if код is None and свой.space != DEFAULT_SPACE:
        raise ToolError(NAME_THE_CHECKLIST)
    return for_checklist(свой, код)
```

и в `_call_tool`: `прочее = {} if база is None else {"store": _aimed(spec.kind, база, tenant=tenant, код=код)}`. Импорты: `from dataclasses import replace`, `from .checklist_layout import DEFAULT_SPACE, space_of`. Правящий инструмент с кодом эталона наведён на `ge/bizdev`, которого нет, — дверь отвечает своим «Чека-листа „bizdev“ в пространстве „ge“ нет», то есть тем же, что на любой несуществующий код.

`src/mcp/checklists_tools.py`, функции `checklists` и `checklist_meta`: `api.overview(store, spaces=visible_spaces(tenant))`.

Существующие тесты, где тенант УК назван произвольно (`УК = "укашка"`) и методика правится через `_checklist_for`/`handle`, получают `УК = "HQ"`: после волны пространство правки выводится из тенанта, и `укашка` — не код пространства. Найти: `grep -ln '"укашка"' tests/test_mcp_*.py`. Тесты, зовущие дверь напрямую (`create(store, tenant=...)`), не меняются: дверь тенант не читает.

- [ ] **Step 4: Прогнать тесты**

Run: `.venv/bin/pytest tests/test_mcp_spaces_rpc.py tests/test_mcp_checklist_access.py tests/test_mcp_checklists_tools.py tests/test_mcp_checklist_tools.py tests/test_mcp_catalogue.py -q --no-cov`
Expected: PASS.

- [ ] **Step 5: Негативный прогон**

Вернуть в `_checklist_for` `Store(root=..., live=...)` без `space` → падает `test_правка_партнёра_наведена_на_его_пространство`; убрать `raise ToolError(NAME_THE_CHECKLIST)` → падает `test_правящий_инструмент_без_кода_не_уходит_в_эталон` (правка ушла бы в `ge/bizdev`, которого нет, — тест требует именно текст `NAME_THE_CHECKLIST`). Вернуть правку.

- [ ] **Step 6: Commit**

```bash
git add src/mcp/server.py src/mcp/rpc.py src/mcp/checklists_tools.py tests/test_mcp_spaces_rpc.py tests/test_mcp_checklist_access.py tests/test_mcp_checklists_tools.py
git commit -m "feat(mcp): методика правится в пространстве токена, эталон — только чтение (#340)"
```

---

### Task 3: Чек-листы бота по пространству аудитора

**Files:**
- Modify: `src/domain/bot_checklists.py` (`BotChecklist`, `available`, `source_for`, `pick`)
- Modify: `src/domain/state.py` (`start_inspection`, строка 591: `pick(settings, checklist_code)`)
- Modify: `tests/test_domain_bot_checklists.py` (вызовы `available(...)` получают `tenant=HQ_TENANT`)
- Test: `tests/test_domain_bot_spaces.py` (новый)

**Interfaces:**
- Consumes: `visible_spaces`, `space_of`, `DEFAULT_SPACE`, `ACTIVE` (Task 1, `checklist_layout`).
- Produces: `BotChecklist.space: str`; `available(settings: Settings, *, tenant: str) -> list[BotChecklist]`; `pick(settings: Settings, code: str | None, *, tenant: str) -> BotChecklist`; `source_for(settings: Settings, code: str, *, space: str = DEFAULT_SPACE) -> Path`. Тенант обязателен и без умолчания: граница, у которой есть умолчание, однажды будет забыта.

- [ ] **Step 1: Написать падающие тесты**

```python
"""Волна 1 (#340): бот предлагает чек-листы пространства аудитора и эталон УК."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from src.domain import get_state, start_inspection
from src.domain.bot_checklists import available
from src.domain.config import check_environment
from src.domain.tenants import HQ_TENANT
from src.mcp.checklist import Store, apply_change, current_version, publish
from src.mcp.checklists import create, set_bot_access, set_state

CHAT = 7401
СЕГОДНЯ = date(2026, 9, 30)


def _открыть(store: Store, *, tenant: str) -> None:
    create(store, tenant=tenant, name_ru=store.code, name_en=store.code, today=СЕГОДНЯ)
    правка = apply_change(
        store, tenant=tenant, tool="add_checklist_item", command="add",
        options={"id": "X01", "process": "Проба", "question-ru": "Проба", "levels": "D1",
                 "zones": "all", "days": 5, "criteria": "D1: проба"},
        today=СЕГОДНЯ,
    )
    assert правка.accepted and правка.version is not None, правка
    publish(store, tenant=tenant, version=правка.version)
    set_state(store, tenant=tenant, state="active")
    set_bot_access(store, tenant=tenant, on=True)


@pytest.fixture
def хранилище(data_copy: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Store:
    monkeypatch.setenv("AUDIT_DATA_DIR", str(data_copy))
    monkeypatch.setenv("STATE_DIR", str(tmp_path / "state"))
    monkeypatch.chdir(tmp_path)
    store = Store(root=tmp_path / "хранилище", live=data_copy)
    current_version(store)
    _открыть(replace(store, space="ge", code="own"), tenant="GE")
    _открыть(replace(store, space="am", code="rnd"), tenant="AM")
    monkeypatch.setenv("MCP_CHECKLIST_STORE", str(store.root))
    return store


def test_партнёр_видит_эталон_и_свои(хранилище: Store) -> None:
    видно = {(c.space, c.code) for c in available(check_environment(), tenant="GE")}
    assert видно == {("hq", "bizdev"), ("ge", "own")}


def test_уК_не_видит_чек_листов_партнёров(хранилище: Store) -> None:
    видно = {(c.space, c.code) for c in available(check_environment(), tenant=HQ_TENANT)}
    assert видно == {("hq", "bizdev")}


def test_чужой_код_не_стартует_проверку(хранилище: Store) -> None:
    with pytest.raises(Exception, match="больше не открыт"):
        start_inspection(CHAT, unit="Тестовая", kind="planned", report_lang="ru",
                         tenant="GE", checklist_code="rnd")
    assert get_state(CHAT) is None


def test_проверка_партнёра_пишется_в_его_тенант(хранилище: Store) -> None:
    start_inspection(CHAT, unit="Тестовая", kind="planned", report_lang="ru",
                     tenant="GE", checklist_code="own")
    состояние = get_state(CHAT)
    assert состояние is not None
    assert (состояние.tenant, состояние.checklist_code) == ("GE", "own")
```

- [ ] **Step 2: Прогнать и убедиться, что падают**

Run: `.venv/bin/pytest tests/test_domain_bot_spaces.py -q --no-cov`
Expected: FAIL — `TypeError: available() got an unexpected keyword argument 'tenant'`.

- [ ] **Step 3: Реализация**

В `BotChecklist` добавить поле `space: str = DEFAULT_SPACE` после `code`. `_legacy` оставить как есть (эталон `bizdev` из `AUDIT_DATA_DIR` годится любому пространству: это и есть эталон). Новый `available`:

```python
def available(settings: Settings, *, tenant: str) -> list[BotChecklist]:
    """Чек-листы, по которым аудитор этого пространства начинает проверку.

    Своё пространство — открытые галочкой «в боте». Эталон у партнёра — всегда
    (D227), кроме черновика, снятого и негодного: те же заслоны, что у галочки
    (`bot_block`). Вопрос владельцу 4: если эталон у партнёра должен следовать
    галочке УК, условие ниже меняется на `in_bot_of`.
    """
    from src.mcp.checklists import bot_block

    root = settings.checklist_store
    if root is None or not root.is_dir() or not known(root):
        return _legacy(settings)
    видимые = visible_spaces(canonical_tenant(tenant))
    своё = видимые[0]
    в_проде = applied(root)
    ответ = []
    for space, code in known(root):
        if space not in видимые:
            continue
        store = Store(root=root, live=settings.data_dir, space=space, code=code)
        карточка = read_meta(store)
        if карточка is None:
            continue
        if space == своё and not in_bot_of(карточка, space, code, в_проде):
            continue
        if space != своё and карточка.state != ACTIVE:
            continue
        if bot_block(store) is not None:
            continue
        источник = root / space / code / CURRENT_LINK
        if not источник.is_dir():
            continue
        ответ.append(BotChecklist(code=code, space=space, name_ru=карточка.name_ru,
                                  name_en=карточка.name_en, source=источник))
    return sorted(ответ, key=lambda c: c.name_ru.casefold())
```

`pick(settings, code, *, tenant)` зовёт `available(settings, tenant=tenant)`, остальное без изменений. `source_for` получает `space: str = DEFAULT_SPACE` и строит путь `root / space / code / CURRENT_LINK`. Импорты: `ACTIVE`, `visible_spaces` из `src.mcp.checklist_layout`, `canonical_tenant` из `src.domain.tenants`. Шапку модуля переписать: строки «Пространство пока одно — УК (`hq`)…» больше неправда.

`src/domain/state.py`: `выбран = pick(settings, checklist_code, tenant=tenant)`.

`tests/test_domain_bot_checklists.py`: каждый `available(check_environment())` → `available(check_environment(), tenant=HQ_TENANT)`, импорт `from src.domain.tenants import HQ_TENANT`.

- [ ] **Step 4: Прогнать тесты**

Run: `.venv/bin/pytest tests/test_domain_bot_spaces.py tests/test_domain_bot_checklists.py tests/test_bot_start_checklist.py tests/test_domain_state.py -q --no-cov`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/domain/bot_checklists.py src/domain/state.py tests/test_domain_bot_spaces.py tests/test_domain_bot_checklists.py
git commit -m "feat(domain): чек-листы бота по пространству аудитора, эталон у партнёра всегда (#340)"
```

---

### Task 4: Пространство в приглашении и в связке бота

**Files:**
- Modify: `src/bot/invites.py` (`Invite`, `parse_invites`)
- Modify: `src/bot/roster.py` (`RosterEntry`, `Roster.load`, `Roster.activate`, `Roster._save`, новый `Roster.space_of`)
- Test: `tests/test_bot_invites.py`, `tests/test_bot_roster.py` (дописать)

**Interfaces:**
- Produces: `Invite.space: str` (по умолчанию `HQ_TENANT`); `RosterEntry.space: str`; `Roster.space_of(telegram_id: int) -> str | None`; формат `BOT_INVITES`: `[<ПРОСТРАНСТВО>/]<юзернейм>[:Имя]`, например `ivanov:Иван Иванов,GE/petrov:Пётр Петров`; `roster.json` версии 2 с полем `space`; версия 1 читается как `HQ`.

- [ ] **Step 1: Написать падающие тесты**

В `tests/test_bot_invites.py`:

```python
from src.domain.tenants import HQ_TENANT


def test_приглашение_без_пространства_ведёт_в_уК() -> None:
    assert parse_invites("ivanov:Иван")["ivanov"].space == HQ_TENANT


def test_пространство_приглашения_называется_впереди() -> None:
    приглашение = parse_invites("GE/Petrov:Пётр Петров")["petrov"]
    assert (приглашение.space, приглашение.name) == ("GE", "Пётр Петров")


def test_старый_код_пространства_переводится() -> None:
    assert parse_invites("default/ivanov")["ivanov"].space == HQ_TENANT


def test_кривое_пространство_это_отказ_на_старте() -> None:
    with pytest.raises(BotConfigError, match="пространств"):
        parse_invites("../hq/ivanov")
```

В `tests/test_bot_roster.py`:

```python
def test_связка_помнит_пространство(tmp_path: Path) -> None:
    roster = Roster.load(tmp_path)
    roster.activate(501, Invite(username="petrov", name=None, space="GE"))
    assert Roster.load(tmp_path).space_of(501) == "GE"


def test_связка_первой_версии_читается_как_уК(tmp_path: Path) -> None:
    путь = tmp_path / "access" / "roster.json"
    путь.parent.mkdir(parents=True)
    путь.write_text(json.dumps({"version": 1, "entries": [
        {"telegram_id": 7, "username": "ivanov", "name": None, "activated_at": ""}]}), encoding="utf-8")
    assert Roster.load(tmp_path).space_of(7) == HQ_TENANT


def test_незнакомому_пространства_нет(tmp_path: Path) -> None:
    assert Roster.load(tmp_path).space_of(999) is None
```

- [ ] **Step 2: Прогнать и убедиться, что падают**

Run: `.venv/bin/pytest tests/test_bot_invites.py tests/test_bot_roster.py -q --no-cov`
Expected: FAIL — `AttributeError: 'Invite' object has no attribute 'space'`.

- [ ] **Step 3: Реализация**

`src/bot/invites.py`:

```python
from src.domain.tenants import HQ_TENANT, canonical_tenant

#: Код пространства в приглашении: те же знаки, что у кода тенанта. Строже не
#: нужно — ошибка кода ловится здесь, а смысл («такое пространство заведено»)
#: проверяет команда пространств (`tools/space.py`).
_SPACE_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


@dataclass(frozen=True)
class Invite:
    username: str
    name: str | None = None
    #: Пространство, аудитором которого станет приглашённый (волна 1, #340).
    space: str = HQ_TENANT
```

В `parse_invites` перед разбором юзернейма:

```python
        raw_head, has_name, raw_name = piece.partition(":")
        raw_space, has_space, raw_username = raw_head.rpartition("/")
        if not has_space:
            raw_username = raw_space
        space = canonical_tenant(raw_space) if has_space else HQ_TENANT
        if has_space and not _SPACE_RE.match(space):
            raise BotConfigError(
                f"{INVITES_VAR}: «{piece}» — код пространства «{raw_space}» не годится. "
                f"Нужен вид GE/username:Имя Фамилия"
            )
        username = normalize_username(raw_username)
```

и `Invite(username=username, name=name or None, space=space)`. Строку `INVITES_VAR` в шапке модуля дополнить форматом с пространством.

`src/bot/roster.py`: `FORMAT_VERSION = 2`; `RosterEntry.space: str`; в `load` — `space=canonical_tenant(str(item.get("space") or HQ_TENANT))`; в `activate` — `space=invite.space`; в `_save` — ключ `"space": entry.space`; новый метод:

```python
    def space_of(self, telegram_id: int) -> str | None:
        """Пространство узнанного человека. Незнакомому — `None`, а не УК."""
        entry = self._entries.get(telegram_id)
        return entry.space if entry is not None else None
```

- [ ] **Step 4: Прогнать тесты**

Run: `.venv/bin/pytest tests/test_bot_invites.py tests/test_bot_roster.py tests/test_bot_config.py -q --no-cov`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/bot/invites.py src/bot/roster.py tests/test_bot_invites.py tests/test_bot_roster.py
git commit -m "feat(bot): пространство в приглашении и в связке Telegram ID (#340)"
```

---

### Task 5: Пространство в апдейте и заслон чата

**Files:**
- Modify: `src/bot/access.py` (`AccessMiddleware`, новые `SPACE_KEY`, `ChatSpaceMiddleware`, `chat_tenant`)
- Modify: `src/bot/app.py` (строки 173–175: регистрация мидлварей)
- Modify: `src/bot/texts.py` (ключ `access.foreign_space`, ru и en)
- Test: `tests/test_bot_access.py` (дописать), `tests/test_bot_space_guard.py` (новый)

**Interfaces:**
- Consumes: `Roster.space_of`, `Invite.space` (Task 4).
- Produces: `SPACE_KEY = "space"` — под этим именем тенант человека лежит в `data` апдейта, и обработчик получает его параметром `space: str`; `chat_tenant(chat_id: int) -> str | None`; `ChatSpaceMiddleware(read_tenant: Callable[[int], str | None] = chat_tenant)`.

- [ ] **Step 1: Написать падающие тесты**

В `tests/test_bot_access.py`:

```python
from src.bot.access import SPACE_KEY
from src.domain.tenants import HQ_TENANT


@pytest.mark.asyncio
async def test_названный_окружением_работает_в_уК() -> None:
    увидено: dict[str, Any] = {}

    async def handler(event: TelegramObject, data: dict[str, Any]) -> None:
        увидено.update(data)

    await AccessMiddleware(allowed_ids=frozenset({111}))(handler, _message(111), {})
    assert увидено[SPACE_KEY] == HQ_TENANT


@pytest.mark.asyncio
async def test_приглашённый_работает_в_пространстве_приглашения(tmp_path: Path) -> None:
    увидено: dict[str, Any] = {}

    async def handler(event: TelegramObject, data: dict[str, Any]) -> None:
        увидено.update(data)

    roster = Roster.load(tmp_path)
    middleware = AccessMiddleware(frozenset(), StaticInvites(parse_invites("GE/petrov")), roster)
    await middleware(handler, _message(501, username="petrov"), {})
    assert увидено[SPACE_KEY] == "GE"
    # Второй апдейт — уже по ID, пространство то же.
    await middleware(handler, _message(501, username=None), {})
    assert увидено[SPACE_KEY] == "GE"
```

(`_message(user_id, username="x")` — помощник набора, собирающий `Message` как в `test_middleware_calls_handler_for_allowed_user`; если его нет, завести рядом с `_user`.)

`tests/test_bot_space_guard.py`:

```python
"""Review Focus 2: апдейт по проверке чужого пространства до обработчика не доходит."""

from __future__ import annotations

from typing import Any

import pytest
from aiogram.types import TelegramObject
from bot_harness import callback_query, text_message

from src.bot.access import SPACE_KEY, ChatSpaceMiddleware

pytestmark = pytest.mark.asyncio


async def _прогнать(event: TelegramObject, *, space: str, чья: str | None) -> list[TelegramObject]:
    дошло: list[TelegramObject] = []

    async def handler(e: TelegramObject, data: dict[str, Any]) -> None:
        дошло.append(e)

    await ChatSpaceMiddleware(read_tenant=lambda _chat: чья)(handler, event, {SPACE_KEY: space})
    return дошло


async def test_своя_проверка_проходит() -> None:
    assert await _прогнать(text_message("фото"), space="GE", чья="GE")


async def test_чата_без_проверки_заслон_не_касается() -> None:
    assert await _прогнать(text_message("/start"), space="GE", чья=None)


async def test_старая_кнопка_по_чужой_проверке_не_доходит() -> None:
    assert await _прогнать(callback_query("zone:3"), space="GE", чья="HQ") == []


async def test_сообщение_в_чужую_проверку_не_доходит() -> None:
    assert await _прогнать(text_message("холодильник грязный"), space="HQ", чья="GE") == []


async def test_старый_код_тенанта_в_проверке_считается_уК() -> None:
    assert await _прогнать(text_message("фото"), space="HQ", чья="default")
```

- [ ] **Step 2: Прогнать и убедиться, что падают**

Run: `.venv/bin/pytest tests/test_bot_access.py tests/test_bot_space_guard.py -q --no-cov`
Expected: FAIL — `ImportError: cannot import name 'SPACE_KEY'`.

- [ ] **Step 3: Реализация `src/bot/access.py`**

```python
#: Под этим ключом тенант человека лежит в данных апдейта; aiogram отдаёт его
#: обработчику параметром `space` (волна 1, #340).
SPACE_KEY = "space"


class AccessMiddleware(BaseMiddleware):
    ...
    async def __call__(self, handler, event, data):
        user = getattr(event, "from_user", None)
        user_id = user.id if user is not None else None
        space = self._space_of(user_id, getattr(user, "username", None))
        if space is None:
            logger.warning("отклонено обновление от постороннего Telegram ID %s", user_id)
            return None
        data[SPACE_KEY] = space
        return await handler(event, data)

    def _space_of(self, user_id: int | None, username: str | None) -> str | None:
        """Пространство человека — или `None`: не пускать.

        Названный окружением стенда — сотрудник УК: этот список заводился до
        пространств, и в нём только свои.
        """
        if is_allowed(user_id, self._allowed_ids):
            return HQ_TENANT
        if user_id is None:
            return None
        if self._roster is not None:
            known = self._roster.space_of(user_id)
            if known is not None:
                return known
        return self._activate(user_id, username)
```

`_activate` возвращает `invite.space` вместо `True` и `None` вместо `False`.

```python
def chat_tenant(chat_id: int) -> str | None:
    """Тенант проверки, идущей в чате, — или `None`, если проверки нет или она не читается.

    Нечитаемое состояние — не повод молча отказывать: его разбирает обработчик
    своим отказом (`src/bot/errors.py`), а заслон пропускает апдейт дальше.
    """
    from src import domain

    try:
        состояние = domain.get_state(chat_id)
    except (DomainError, OSError, ValueError):
        return None
    return состояние.tenant if состояние is not None else None


class ChatSpaceMiddleware(BaseMiddleware):
    """Проверка в чате принадлежит пространству, а не чату (Review Focus 2).

    Состояние проверки привязано к чату. В общем чате или после переезда
    человека в другое пространство его кнопки и кадры дописывали бы чужую
    проверку. Чат без проверки заслон не касается: новую человек начнёт в своём.
    """

    def __init__(self, read_tenant: Callable[[int], str | None] = chat_tenant) -> None:
        self._read_tenant = read_tenant

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        space = data.get(SPACE_KEY)
        chat = _chat_of(event)
        if space is None or chat is None:
            return await handler(event, data)
        чья = await asyncio.to_thread(self._read_tenant, chat.id)
        if чья is None or canonical_tenant(чья) == space:
            return await handler(event, data)
        logger.warning("апдейт из пространства %s к проверке пространства %s в чате %s", space, чья, chat.id)
        текст = t("access.foreign_space", chat_ui_lang(chat.id))
        if isinstance(event, CallbackQuery):
            await event.answer(текст, show_alert=True)
        elif isinstance(event, Message):
            await event.answer(текст)
        return None


def _chat_of(event: TelegramObject) -> Chat | None:
    if isinstance(event, Message):
        return event.chat
    if isinstance(event, CallbackQuery) and isinstance(event.message, Message):
        return event.message.chat
    return None
```

Импорты: `asyncio`, `Chat`, `CallbackQuery`, `Message` из `aiogram.types`, `HQ_TENANT`, `canonical_tenant` из `src.domain.tenants`, `DomainError` из `src.domain.errors`, `t` из `.texts`, `chat_ui_lang` из того модуля, откуда его берут роутеры (`grep -n "def chat_ui_lang" src/bot/*.py`).

`src/bot/app.py`, после регистрации `access`:

```python
    space_guard = ChatSpaceMiddleware()
    dispatcher.message.outer_middleware(space_guard)
    dispatcher.callback_query.outer_middleware(space_guard)
```

Порядок важен: внешние мидлвари идут в порядке регистрации, и заслону чата нужен `SPACE_KEY`, который кладёт доступ.

`src/bot/texts.py`, рядом с `start.unit_new_partner`:

```python
    "access.foreign_space": {
        "ru": "Эта проверка ведётся в другом пространстве. Свою проверку начните в личном чате с ботом.",
        "en": "This inspection belongs to another space. Start your own in a private chat with the bot.",
    },
```

- [ ] **Step 4: Прогнать тесты**

Run: `.venv/bin/pytest tests/test_bot_access.py tests/test_bot_space_guard.py tests/test_bot_app.py tests/test_bot_texts.py tests/test_bot_stale_button.py -q --no-cov`
Expected: PASS.

- [ ] **Step 5: Негативный прогон**

В `ChatSpaceMiddleware.__call__` заменить `canonical_tenant(чья) == space` на `True` → падают `test_старая_кнопка_по_чужой_проверке_не_доходит` и `test_сообщение_в_чужую_проверку_не_доходит`. Убрать регистрацию `space_guard` в `app.py` → должен упасть тест маршрута из Task 6 (`test_чужая_проверка_в_чате_не_дописывается`); если он не падает, он проверяет не то. Вернуть.

- [ ] **Step 6: Commit**

```bash
git add src/bot/access.py src/bot/app.py src/bot/texts.py tests/test_bot_access.py tests/test_bot_space_guard.py
git commit -m "feat(bot): пространство человека в апдейте, заслон чужой проверки в чате (#340)"
```

---

### Task 6: Обработчики бота на пространстве человека

**Files:**
- Modify: `src/bot/routers/start.py` (строки 64, 141–175, 334–410, 459–470, 505–548)
- Modify: `src/bot/unit_pick.py` (строки 143–160)
- Modify: `src/bot/routers/mcp.py` (строка 254)
- Modify: `src/bot/phrases.py` (`recall`, `learn`)
- Modify: `src/bot/config.py` (убрать `MCP_TENANT_VAR`, `DEFAULT_MCP_TENANT`, `mcp_tenant`, `_parse_mcp_tenant`)
- Test: `tests/test_bot_start_space.py` (новый); правка `tests/test_bot_config.py`, `tests/test_bot_mcp_command.py` (где упоминается `mcp_tenant`)

**Interfaces:**
- Consumes: `SPACE_KEY` и параметр `space: str` обработчика (Task 5); `available(settings, *, tenant)` (Task 3).
- Produces: `unit_pick.may_add_units(tenant: str) -> bool` (сравнивает `canonical_tenant(tenant)` с `HQ_TENANT`); `bot_tenant` и `UK_TENANT` удалены; `BOT_MCP_TENANT` больше не читается.

- [ ] **Step 1: Написать падающие тесты**

```python
"""Волна 1 (#340): бот ведёт проверку в пространстве того, кто её начал."""

from __future__ import annotations

from pathlib import Path

import pytest
from bot_harness import AUDITOR_ID, CHAT_ID, callback_query, feed, make_bot, text_message
from test_bot_start_router import settings

from src.bot import unit_pick
from src.bot.app import build_dispatcher
from src.bot.invites import Invite
from src.bot.keyboards import NEW_INSPECTION_CALLBACK
from src.bot.roster import Roster
from src.domain import get_state
from src.domain.tenants import HQ_TENANT

pytestmark = pytest.mark.asyncio


def _партнёр(state_dir: Path) -> Roster:
    roster = Roster.load(state_dir)
    roster.activate(AUDITOR_ID, Invite(username="petrov", space="GE"))
    return roster


def _без_окружения():
    from dataclasses import replace

    return replace(settings(), allowed_ids=frozenset())


async def test_справочник_сверяется_в_пространстве_аудитора(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    спросили: list[str] = []

    def сверка(typed: str, *, tenant: str) -> unit_pick.UnitMatch:
        спросили.append(tenant)
        return unit_pick.UnitMatch(name="Batumi-1", suggestions=(), checked=True)

    from src.bot.routers import start as start_router

    monkeypatch.setattr(start_router, "match_unit", сверка)
    bot, _session = make_bot()
    dp = build_dispatcher(_без_окружения(), roster=_партнёр(domain_env))
    await feed(dp, bot, text_message("/start"))
    await feed(dp, bot, callback_query(NEW_INSPECTION_CALLBACK))
    await feed(dp, bot, text_message("Батуми 1"))
    assert спросили == ["GE"]


async def test_партнёр_не_заводит_пиццерию() -> None:
    assert unit_pick.may_add_units("GE") is False
    assert unit_pick.may_add_units(HQ_TENANT) is True
    assert unit_pick.may_add_units("default") is True


async def test_чужая_проверка_в_чате_не_дописывается(domain_env: Path) -> None:
    """Review Focus 2 на живом диспетчере: проверку УК в чате партнёр не трогает."""
    from src.domain import start_inspection

    start_inspection(CHAT_ID, unit="Тестовая", kind="planned", report_lang="ru", tenant=HQ_TENANT)
    bot, session = make_bot()
    dp = build_dispatcher(_без_окружения(), roster=_партнёр(domain_env))
    await feed(dp, bot, text_message("холодильник грязный"))
    состояние = get_state(CHAT_ID)
    assert состояние is not None and состояние.tenant == HQ_TENANT
    assert not состояние.findings
    assert "другом пространстве" in session.last_text  # type: ignore[attr-defined]
```

(Связка передаётся диспетчеру объектом, поэтому каталог, из которого её прочитали, роли не играет. Поле списка записей у `Inspection` — то, что в `src/domain/models.py`; если оно называется не `findings`, подставить его.)

- [ ] **Step 2: Прогнать и убедиться, что падают**

Run: `.venv/bin/pytest tests/test_bot_start_space.py -q --no-cov`
Expected: FAIL — `спросили == ["HQ"]`, а не `["GE"]`.

- [ ] **Step 3: Реализация**

`src/bot/unit_pick.py`: удалить `UK_TENANT` и `bot_tenant`;

```python
def may_add_units(tenant: str) -> bool:
    """Заводить новые пиццерии может только управляющая компания (D233, D234)."""
    return canonical_tenant(tenant) == HQ_TENANT
```

`src/bot/routers/start.py`:
- импорт `from ..unit_pick import match_unit, may_add_units`;
- `_open_checklists(space: str)` → `available(check_environment(), tenant=space)`; `_ask_checklist(message, state, lang, space)` передаёт `space`;
- у обработчиков `on_new`, `on_resume_new`, `on_unit`, `on_unit_new`, `on_checklist`, `on_lang` — параметр `space: str` (aiogram отдаёт его из `data[SPACE_KEY]`);
- `match_unit(имя.name, tenant=space)`, `may_add_units(space)` в обоих местах, `upsert_unit(..., tenant=space)`;
- в вызове `domain.start_inspection` добавить `tenant=space`;
- в `on_checklist`: `открыты = _open_checklists(space) or []`.

`src/bot/routers/mcp.py`: обработчик выпуска токена получает `space: str`, `issue_token(user.id, tenant=space)`.

`src/bot/phrases.py`: тенант записи — тенант проверки чата:

```python
def _tenant_of(chat_id: int) -> str:
    """Словарь фраз — пространства проверки: выученное партнёром не уходит в УК."""
    состояние = domain.get_state(chat_id)
    return состояние.tenant if состояние is not None else HQ_TENANT
```

и `synonyms.lookup_phrase(сказанное, lang=lang, tenant=_tenant_of(chat_id))`, `synonyms.remember_phrase(..., tenant=_tenant_of(chat_id))`.

`src/bot/config.py`: удалить `MCP_TENANT_VAR`, `DEFAULT_MCP_TENANT`, поле `mcp_tenant`, `_parse_mcp_tenant` и строку `mcp_tenant=...` в сборке настроек. Тесты, проверявшие `BOT_MCP_TENANT` (`grep -rn "mcp_tenant\|BOT_MCP_TENANT" tests`), удалить: поведение, которое они держали, снято намеренно.

- [ ] **Step 4: Прогнать тесты**

Run: `.venv/bin/pytest tests/test_bot_start_space.py tests/test_bot_start_router.py tests/test_bot_start_checklist.py tests/test_bot_unit_pick.py tests/test_bot_mcp_command.py tests/test_bot_phrases.py tests/test_bot_learned_phrase.py tests/test_bot_config.py -q --no-cov`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/bot tests/test_bot_start_space.py tests/test_bot_config.py tests/test_bot_mcp_command.py
git commit -m "feat(bot): проверка, справочник, фразы и токен MCP — в пространстве аудитора (#340)"
```

---

### Task 7: Вход по учётке любого пространства через один адрес

**Files:**
- Create: `src/db/migrations/0028_login_across_spaces.sql`
- Modify: `src/db/web_access.py` (`_SELECT_USER_SQL`, `_SELECT_USER_BY_EMAIL_SQL`, `_RESOLVE_SESSION_SQL`, `authenticate`, `find_by_email`, `resolve_session`, тексты отказов `create_account` и `set_email`)
- Modify: `src/web/auth.py` (строки 155, 191–204, 305–312)
- Modify: `tests/web_harness.py` (`подменить_двери`)
- Modify: `tests/test_db_web_access.py` (тесты «один логин в разных тенантах», «сессия чужого тенанта»), `tests/test_web_google_login.py` (подмена `find_by_email`)
- Test: `tests/test_db_web_access.py` (дописать), `tests/test_web_auth.py` (дописать)

**Interfaces:**
- Produces: `authenticate(login: str, password: str) -> Account | None`; `find_by_email(email: str) -> Account | None`; `resolve_session(token: str) -> Account | None` — все без тенанта, `Account.tenant` — тенант учётки. Счётчик попыток (`admit_attempt`, `note_success`) по-прежнему ведётся по тенанту стенда `conf.tenant`: до входа человека его пространство неизвестно, а счётчик — не граница.
- Вопрос владельцу 1: если владелец выберет поле пространства на форме, эта задача меняется — тенант приходит из формы, миграция `0028` не нужна.

- [ ] **Step 1: Написать падающие тесты (база)**

В `tests/test_db_web_access.py` заменить `test_один_логин_живёт_в_разных_тенантах` и `test_сессия_чужого_тенанта_не_открывает_этот_стенд` (они держали модель «стенд = тенант», которую волна снимает) на:

```python
def test_логин_один_на_все_пространства(обе_роли: str) -> None:
    create_account("director", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    with pytest.raises(AccessError, match="занят"):
        create_account("director", tenant=ЧУЖОЙ, password="другой-пароль-подлиннее")


def test_вход_находит_учётку_любого_пространства(обе_роли: str) -> None:
    create_account("partner", tenant=ЧУЖОЙ, password=ПАРОЛЬ)
    учётка = authenticate("partner", ПАРОЛЬ)
    assert учётка is not None and учётка.tenant == ЧУЖОЙ


def test_сессия_несёт_пространство_своей_учётки(обе_роли: str) -> None:
    сессия = open_session(create_account("partner", tenant=ЧУЖОЙ, password=ПАРОЛЬ))
    учётка = resolve_session(сессия.token)
    assert учётка is not None and учётка.tenant == ЧУЖОЙ


def test_отключённая_учётка_другого_пространства_не_входит(обе_роли: str) -> None:
    """Review Focus 5: снятый фильтр стенда не должен снять и отключение."""
    сессия = open_session(create_account("partner", tenant=ЧУЖОЙ, password=ПАРОЛЬ))
    disable_account("partner", tenant=ЧУЖОЙ)
    assert authenticate("partner", ПАРОЛЬ) is None
    assert resolve_session(сессия.token) is None


def test_почта_одна_на_все_пространства(обе_роли: str) -> None:
    create_account("a", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    create_account("b", tenant=ЧУЖОЙ, password=ПАРОЛЬ)
    set_email("a", tenant=ТЕНАНТ, email="p@example.org")
    with pytest.raises(EmailTakenError):
        set_email("b", tenant=ЧУЖОЙ, email="p@example.org")
    учётка = find_by_email("p@example.org")
    assert учётка is not None and учётка.tenant == ТЕНАНТ


def test_миграция_отказывает_на_двойниках(pg_dsn: str) -> None:
    """Двойник логина в двух пространствах — отказ наката, а не выбор одного наугад."""
    import pathlib

    sql = pathlib.Path("src/db/migrations/0028_login_across_spaces.sql").read_text(encoding="utf-8")
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute("create temp table web_users (login text, email text, tenant_code text)")
        cur.execute("insert into web_users values ('director', null, 'A'), ('director', null, 'B')")
        проверка = sql.split("create unique index", 1)[0]
        with pytest.raises(psycopg.errors.RaiseException, match="нескольких пространствах"):
            cur.execute(проверка)
        conn.rollback()
```

Вызовы `authenticate(..., tenant=ТЕНАНТ)`, `resolve_session(..., tenant=...)` и `find_by_email(..., tenant=...)` в остальных тестах файла теряют `tenant=` (`grep -n "authenticate(\|resolve_session(\|find_by_email(" tests/test_db_web_access.py`). Тест `test_учётка_чужого_тенанта_не_опознаётся` удаляется: входа «в тенант» больше нет.

- [ ] **Step 2: Написать падающий тест (веб)**

В `tests/test_web_auth.py`:

```python
def test_стенд_уК_впускает_учётку_партнёра_в_её_пространство(monkeypatch: pytest.MonkeyPatch) -> None:
    зовы = подменить_двери(monkeypatch, tenant="GE")
    with собрать(tenant="HQ").test_client() as client:
        войти(client)
        client.get("/inspections")
    assert зовы["authenticate"] == [(ЛОГИН, ПАРОЛЬ)]
    assert all(len(зов) == 1 for зов in зовы["resolve"]), "сессия сверяется без тенанта стенда"
```

- [ ] **Step 3: Прогнать и убедиться, что падают**

Run: `make test-honest ARGS="tests/test_db_web_access.py tests/test_web_auth.py -q"`
Expected: FAIL — `TypeError: authenticate() missing 1 required keyword-only argument: 'tenant'` и нет файла миграции.

- [ ] **Step 4: Миграция**

`src/db/migrations/0028_login_across_spaces.sql`:

```sql
-- 0028_login_across_spaces.sql
--
-- Волна 1 пространств (#340, D182): один адрес админки на все пространства.
--
-- ЧТО БЫЛО. Логин и почта Google были уникальны ВНУТРИ арендатора (0014,
-- 0021), а стенд отвечал за один арендатор (`WEB_TENANT`): опознание искало
-- строку по паре «арендатор стенда + логин». Партнёр на стенде УК войти не
-- мог вовсе — его строки там не искали.
--
-- ЧТО СТАЛО. Опознание ищет по логину (или почте) во всей базе, и пространство
-- человека берётся из его строки. Для этого логин и почта обязаны быть
-- уникальны во всей базе: иначе «director» в двух пространствах — это вопрос
-- «кого впустить», на который у формы входа нет ответа.
--
-- ДВОЙНИКИ НЕ РАЗРЕШАЮТСЯ МОЛЧА. Если они уже есть, накат отказывает и
-- говорит, сколько их и как найти, — выбрать одного наугад значило бы
-- впустить не того человека. Логины в тексте отказа не печатаются: отказ
-- уходит в журнал наката.
--
-- Раннер оборачивает файл в одну транзакцию сам — begin/commit здесь не нужны.

do $$
declare
    двойников bigint;
begin
    select count(*) into двойников
      from (select login from web_users group by login having count(*) > 1) d;
    if двойников > 0 then
        raise exception using message =
            'Логины, заведённые в нескольких пространствах: ' || двойников::text
            || '. Найти: select login from web_users group by login having count(*) > 1. '
            || 'Переименуйте их, затем повторите накат';
    end if;
    select count(*) into двойников
      from (select email from web_users where email is not null
             group by email having count(*) > 1) d;
    if двойников > 0 then
        raise exception using message =
            'Почта привязана к учёткам нескольких пространств: ' || двойников::text
            || '. Снимите лишние привязки (make web-user ARGS="email <логин> --tenant <код>"), '
            || 'затем повторите накат';
    end if;
end $$;

create unique index web_users_login_uq on web_users (login);
drop index web_users_tenant_login_idx;

create unique index web_users_email_global_uq on web_users (email) where email is not null;
drop index web_users_email_uq;

comment on column web_users.login is
    'Логин, единый на все пространства (волна 1, #340): опознание ищет по нему '
    'во всей базе, а пространство человека — tenant_code его строки.';
```

Текст отказа слова «нескольких пространствах» содержит в обеих ветках, их ловит тест из Step 1. Процентов в теле нет намеренно: `raise ... using message =` не разбирает `%`.

- [ ] **Step 5: `src/db/web_access.py`**

```python
_SELECT_USER_SQL = """
    select id, login, tenant_code, password_hash, role
      from web_users
     where login = %s and disabled_at is null
"""

_SELECT_USER_BY_EMAIL_SQL = """
    select id, login, tenant_code, role
      from web_users
     where email = %s and disabled_at is null
"""

_RESOLVE_SESSION_SQL = """
    select u.id, u.login, u.tenant_code, u.role
      from web_sessions s
      join web_users u on u.id = s.user_id
     where s.fingerprint = %s
       and s.closed_at is null
       and s.expires_at > now()
       and u.disabled_at is null
"""
```

`authenticate(login, password)`: `cur.execute(_SELECT_USER_SQL, (login.strip().lower(),))`. `find_by_email(email)`: `(приведённая,)`. `resolve_session(token)`: `(session_fingerprint(token),)`. Докстринги переписать: абзац «Арендатор приходит из окружения стенда» → «Пространство приходит из строки учётки». В `create_account` текст отказа на повтор: `f"Логин «{имя}» уже занят — логины единые на все пространства. Возьмите другой"`. В `set_email`: `f"почта {значение} уже привязана к другой учётке"`.

- [ ] **Step 6: `src/web/auth.py`**

В `install`, первой строкой после `max_age = ...`:

```python
    # Счётчик попыток ведётся по тенанту СТЕНДА: до входа пространство
    # человека неизвестно, а счётчик — защита от перебора, не граница.
    рубеж = conf.tenant
```

`admit_attempt(tenant=рубеж, ...)`, `note_success(tenant=рубеж, ...)` в обоих местах; `resolve_session(token)`, `authenticate(имя, request.form.get("password") or "")`, `find_by_email(кто.email)`. Шапку модуля дополнить абзацем: «Стенд один на все пространства: пространство вошедшего — у его учётки».

- [ ] **Step 7: Оснастка веба**

`tests/web_harness.py`, в `подменить_двери`:

```python
    def _authenticate(login: str, password: str) -> Учётка | None:
        зовы["authenticate"].append((login, password))
        if login == ЛОГИН and password == ПАРОЛЬ:
            return Учётка(tenant=tenant, role=role)
        return None

    def _resolve(token: str) -> Учётка | None:
        зовы["resolve"].append((token,))
        return Учётка(tenant=tenant, role=role) if token == ТОКЕН else None
```

Докстринг: «`tenant` — пространство УЧЁТКИ; стенд свой задаёт `собрать(tenant=...)`». В тестах, сверяющих `зовы["authenticate"]` с тройкой `(логин, пароль, тенант)`, убрать тенант (`grep -rn 'зовы\["authenticate"\]\|зовы\["resolve"\]' tests`). В `tests/test_web_google_login.py` подмена `find_by_email` теряет `tenant`.

- [ ] **Step 8: Прогнать тесты**

Run: `make migrate` на тестовой базе MUSPELHEIM (цель `migrate` берёт `DATABASE_ADMIN_URL` из файла окружения), затем `make test-honest ARGS="tests/test_db_web_access.py tests/test_db_migrate.py tests/test_db_migrations_frozen.py tests/test_web_auth.py tests/test_web_login_limit.py tests/test_web_google_login.py tests/test_web_users.py -q"`
Expected: PASS.

- [ ] **Step 9: Негативный прогон**

Вернуть в `_RESOLVE_SESSION_SQL` пропавшую строку `and u.disabled_at is null` удалением → падает `test_отключённая_учётка_другого_пространства_не_входит`. В миграции заменить `> 0` на `> 100` → падает `test_миграция_отказывает_на_двойниках`. Вернуть.

- [ ] **Step 10: Commit**

```bash
git add src/db/migrations/0028_login_across_spaces.sql src/db/web_access.py src/web/auth.py tests/web_harness.py tests/test_db_web_access.py tests/test_web_auth.py tests/test_web_google_login.py
git commit -m "feat(web): вход по учётке любого пространства, логин и почта единые на базу (#340)"
```

---

### Task 8: Веб — данные по пространству вошедшего, а не стенда

**Files:**
- Modify: `src/web/auth.py` (новая `current_tenant`)
- Modify: `src/web/app.py` (все `tenant=conf.tenant`, строки 127, 261, 295, 490–534, 667–1017, 1072–1371, 1411, 1478, 1543–1634; `_author`)
- Modify: `src/web/letter_draft.py` (строки 99, 191)
- Test: `tests/test_web_tenant_source.py` (новый), `tests/test_web_spaces_boundary.py` (новый)

**Interfaces:**
- Consumes: `Account.tenant` из сессии (Task 7).
- Produces: `auth.current_tenant() -> str` — `canonical_tenant` тенанта вошедшего; без вошедшего — `RuntimeError` (заслон до этого не пускает, значит это ошибка кода, а не состояние). Правило для следующих экранов: данные читаются только с `tenant=auth.current_tenant()`.

- [ ] **Step 1: Написать падающие тесты**

`tests/test_web_tenant_source.py`:

```python
"""Волна 1 (#340): ни один экран не читает данные по тенанту стенда.

Статическая сверка, а не только прогон экранов: новый маршрут с
`tenant=conf.tenant` зеленеет на любом тесте, где стенд и человек из одного
пространства, — а это все тесты, написанные до волны.
"""

from __future__ import annotations

from pathlib import Path

#: Единственное законное место: счётчик попыток до входа (Task 7).
РАЗРЕШЕНО = {("auth.py", "рубеж = conf.tenant")}


def test_данные_берутся_по_пространству_вошедшего() -> None:
    нарушения = []
    for путь in sorted(Path("src/web").rglob("*.py")):
        for номер, строка in enumerate(путь.read_text(encoding="utf-8").splitlines(), 1):
            if "conf.tenant" in строка and (путь.name, строка.strip()) not in РАЗРЕШЕНО:
                нарушения.append(f"{путь}:{номер}: {строка.strip()}")
    assert нарушения == [], "тенант стенда вместо тенанта вошедшего:\n" + "\n".join(нарушения)
```

`tests/test_web_spaces_boundary.py`:

```python
"""Review Focus 3: чужая проверка по прямому адресу — тот же 404, что у несуществующей."""

from __future__ import annotations

from typing import Any

import pytest
from web_harness import СВОЙ, войти, подменить_двери, собрать

from src.web import inspections as data
from src.web.app import MoveError, RetractionError

ЧУЖАЯ = "11111111-1111-1111-1111-111111111111"
КАДР = "33333333-3333-3333-3333-333333333333"


@pytest.fixture
def спрошено(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Any]]:
    """Двери чтения, отвечающие «такой нет», и запись, кто и с каким тенантом спрашивал."""
    зовы: list[tuple[str, Any]] = []

    def нет(имя: str) -> Any:
        def дверь(*_a: Any, **k: Any) -> None:
            зовы.append((имя, k.get("tenant")))
            return None
        return дверь

    for имя in ("load_card", "load_report", "preview_bytes"):
        monkeypatch.setattr(data, имя, нет(имя))

    def отказ(имя: str, ошибка: type[Exception]) -> Any:
        """Дверь записи: запомнить тенант и ответить так, как ответит база на чужой id."""
        def дверь(*_a: Any, **k: Any) -> None:
            зовы.append((имя, k.get("tenant")))
            raise ошибка("проверка не найдена")
        return дверь

    monkeypatch.setattr(data, "retract_card", отказ("retract_card", RetractionError))
    monkeypatch.setattr(data, "move_card", отказ("move_card", MoveError))
    monkeypatch.setattr(data, "retraction_available", lambda: True)
    # Администратор партнёра: снятие и перенос у аудитора отказывают 403 ещё до
    # двери, и тест тогда проверял бы роль, а не границу.
    подменить_двери(monkeypatch, tenant="GE", role="admin")
    return зовы


@pytest.mark.parametrize(
    ("метод", "адрес"),
    [
        ("get", f"/inspections/{ЧУЖАЯ}"),
        ("get", f"/inspections/{ЧУЖАЯ}/report"),
        ("get", f"/inspections/{ЧУЖАЯ}/photos/{КАДР}"),
        ("get", f"/inspections/{ЧУЖАЯ}/letter"),
        ("post", f"/inspections/{ЧУЖАЯ}/letter"),
        ("post", f"/inspections/{ЧУЖАЯ}/letter/save"),
        ("post", f"/inspections/{ЧУЖАЯ}/retract"),
        ("post", f"/inspections/{ЧУЖАЯ}/move"),
    ],
)
def test_чужая_проверка_не_найдена(спрошено: list[tuple[str, Any]], метод: str, адрес: str) -> None:
    with собрать(tenant="HQ").test_client() as client:
        войти(client)
        ответ = getattr(client, метод)(адрес, headers={"Origin": СВОЙ}, data={"reason": "x"})
    assert ответ.status_code == 404
    assert спрошено and all(тенант == "GE" for _имя, тенант in спрошено), спрошено


def test_ответ_на_чужую_такой_же_как_на_несуществующую(спрошено: list[tuple[str, Any]]) -> None:
    with собрать(tenant="HQ").test_client() as client:
        войти(client)
        чужая = client.get(f"/inspections/{ЧУЖАЯ}")
        нет = client.get("/inspections/22222222-0000-0000-0000-000000000000")
    assert (чужая.status_code, чужая.data.replace(ЧУЖАЯ.encode(), b"")) == (
        нет.status_code,
        нет.data.replace(b"22222222-0000-0000-0000-000000000000", b""),
    )
```

(Маршруты `/retract` и `/move` зовут дверь записи ДО чтения карточки (`src/web/app.py:896–935`): граница там держится только фильтром тенанта в SQL двери. Тест поэтому требует, чтобы дверь получила тенант `GE`, а ответ после её отказа был тем же 404 карточки. Если снятие без `retraction_available` отвечает раньше двери, подмена на `True` это снимает.)

- [ ] **Step 2: Прогнать и убедиться, что падают**

Run: `.venv/bin/pytest tests/test_web_tenant_source.py tests/test_web_spaces_boundary.py -q --no-cov`
Expected: FAIL — список нарушений из `app.py` и `letter_draft.py`; в границе — тенант `HQ` вместо `GE`.

- [ ] **Step 3: Реализация**

`src/web/auth.py`:

```python
def current_tenant() -> str:
    """Чьи данные показывать: пространство вошедшего (волна 1, #340).

    Не тенант стенда: стенд один на все пространства. Без вошедшего — ошибка
    кода, а не «покажем УК»: заслон `_guard` до экрана неопознанного не пускает,
    и молчаливое умолчание здесь открыло бы историю УК первому же маршруту,
    вызванному мимо заслона.
    """
    account = current_account()
    if account is None:
        raise RuntimeError("current_tenant() вызван без вошедшего: маршрут прошёл мимо заслона")
    return canonical_tenant(account.tenant)
```

`src/web/app.py` и `src/web/letter_draft.py`: каждое `tenant=conf.tenant` → `tenant=auth.current_tenant()` (механически, `sed -i '' 's/tenant=conf\.tenant/tenant=auth.current_tenant()/g' src/web/app.py src/web/letter_draft.py`, затем `git diff` глазами). В `_register_context`: `"tenant": auth.current_tenant() if account else conf.tenant` заменить на `"tenant": canonical_tenant(account.tenant) if account else ""` (форма входа тенант не показывает). `_author`: `return account.login if account else "web"`.

`letter_draft.py` импортирует `auth` из `.`, если ещё не импортирует.

- [ ] **Step 4: Прогнать тесты**

Run: `.venv/bin/pytest tests/test_web_tenant_source.py tests/test_web_spaces_boundary.py tests/test_web_app.py tests/test_web_letter.py tests/test_web_letter_draft.py tests/test_web_overview.py tests/test_web_unit_card.py tests/test_web_users.py tests/test_web_registry_filter.py -q --no-cov`
Expected: PASS.

- [ ] **Step 5: Негативный прогон**

Добавить в `app.py` строку `_ = conf.tenant` в любом обработчике → падает `test_данные_берутся_по_пространству_вошедшего` и печатает файл и строку. В маршруте кадра вернуть `tenant=conf.tenant` → падают оба теста. Вернуть.

- [ ] **Step 6: Commit**

```bash
git add src/web/auth.py src/web/app.py src/web/letter_draft.py tests/test_web_tenant_source.py tests/test_web_spaces_boundary.py
git commit -m "feat(web): экраны читают данные пространства вошедшего, чужое — 404 (#340)"
```

---

### Task 9: Веб — «Методика» по пространству

**Files:**
- Modify: `src/web/methodology.py` (`store_for` строка 707, `checklists_overview` строка 719, `RailRow`)
- Modify: `src/web/app.py` (`_apply` строка 1482, `_render_methodology` строки 1523–1545, маршруты `publish` 1268, `state` 1339, `bot` 1361, `apply` 1388–1420)
- Modify: `src/web/texts.py` (ключи `methodology.not_found`, `methodology.etalon_readonly`, ru и en)
- Test: `tests/test_web_methodology_spaces.py` (новый)

**Interfaces:**
- Consumes: `locate`, `may_write`, `visible_spaces` (Task 1); `auth.current_tenant()` (Task 8).
- Produces: `method.store_for(store: Store, code: str | None, *, tenant: str, write: bool) -> Store` — отказ `MethodologyRefused` с текстом `methodology.not_found` (чужой и несуществующий) или `methodology.etalon_readonly` (правка эталона из пространства партнёра); `method.checklists_overview(store: Store, *, tenant: str) -> list[Overview]`; `RailRow.space: str`, `RailRow.etalon: bool` (для группы «От УК» волны 2).

- [ ] **Step 1: Написать падающие тесты**

```python
"""Review Focus 4: «Методика» партнёра — эталон только на чтение, чужое не найдено."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest
from mcp_checklist_harness import build_methodology
from web_harness import СВОЙ, войти, подменить_двери, собрать

from src.mcp.checklist import Store, current_version, read_journal, tip_version
from src.mcp.checklists import create
from src.web.texts import t


@pytest.fixture
def склад(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Store:
    методика = build_methodology(tmp_path / "методика")
    store = Store(root=tmp_path / "хранилище", live=методика)
    current_version(store)
    create(replace(store, space="am", code="rnd"), tenant="AM", name_ru="РНД", name_en="RnD", today=date(2026, 9, 30))
    monkeypatch.setenv("MCP_CHECKLIST_STORE", str(store.root))
    monkeypatch.setenv("AUDIT_DATA_DIR", str(методика))
    подменить_двери(monkeypatch, tenant="GE")
    return store


def test_чужой_код_звучит_как_несуществующий(склад: Store) -> None:
    with собрать(tenant="HQ").test_client() as client:
        войти(client)
        чужой = client.get("/admin?checklist=rnd").get_data(as_text=True)
        нет = client.get("/admin?checklist=zzz").get_data(as_text=True)
    assert t("methodology.not_found", "ru", code="rnd") in чужой
    assert t("methodology.not_found", "ru", code="zzz") in нет
    assert "РНД" not in чужой


def test_эталон_партнёру_виден(склад: Store) -> None:
    with собрать(tenant="HQ").test_client() as client:
        войти(client)
        ответ = client.get("/admin?checklist=bizdev")
    assert ответ.status_code == 200
    assert t("methodology.not_found", "ru", code="bizdev") not in ответ.get_data(as_text=True)


def test_ни_одна_правка_эталона_из_пространства_партнёра_не_проходит(склад: Store) -> None:
    """Каждый POST раздела «Методика» — по карте маршрутов, а не по списку в тесте:
    новый маршрут записи попадает под проверку сам."""
    эталон = replace(склад, space="hq", code="bizdev")
    журнал, издание = len(read_journal(эталон)), tip_version(эталон)
    app = собрать(tenant="HQ")
    маршруты = sorted(
        {правило.rule for правило in app.url_map.iter_rules()
         if "POST" in (правило.methods or set()) and правило.rule.startswith("/admin")}
    )
    assert маршруты, "маршрутов записи методики не нашлось — тест проверяет пустоту"
    with app.test_client() as client:
        войти(client)
        for маршрут in маршруты:
            адрес = маршрут.replace("<code>", "bizdev") + "?checklist=bizdev"
            client.post(адрес, headers={"Origin": СВОЙ}, data={"note": "проба", "version": издание})
    assert len(read_journal(эталон)) == журнал
    assert tip_version(эталон) == издание
    assert not (склад.root / "ge").exists(), "у партнёра появилась копия без правки"


def test_отказ_правки_эталона_назван_словами(склад: Store) -> None:
    with собрать(tenant="HQ").test_client() as client:
        войти(client)
        ответ = client.post(
            "/admin/items?checklist=bizdev", headers={"Origin": СВОЙ}, data={"id": "X01"}
        )
    assert t("methodology.etalon_readonly", "ru") in ответ.get_data(as_text=True)
```

- [ ] **Step 2: Прогнать и убедиться, что падают**

Run: `.venv/bin/pytest tests/test_web_methodology_spaces.py -q --no-cov`
Expected: FAIL — `KeyError: 'methodology.not_found'` в текстах; после их заведения — журнал эталона вырос.

- [ ] **Step 3: Реализация `src/web/methodology.py`**

```python
from src.mcp.checklist_layout import ACTIVE, DEFAULT_SPACE, DRAFT, RETIRED, locate, may_write, visible_spaces


def store_for(store: Store, code: str | None, *, tenant: str, write: bool) -> Store:
    """Хранилище чек-листа с экрана — видимого этому пространству, иначе отказ.

    Чужой и несуществующий — одним текстом: иначе ответ подтверждал бы, что
    чужое есть. Правка эталона из пространства партнёра — отказ до двери, а не
    после: дверь на чтении заводит нетронутое хранилище, а на правке пишет
    журнал, и ни того, ни другого у эталона партнёр делать не должен.
    """
    try:
        найдено = locate(store, tenant=tenant, code=code)
    except McpError as отказ:
        raise _refusal(отказ) from None
    if найдено is None:
        raise MethodologyRefused(t("methodology.not_found", _lang(), code=code or ""))
    if write and not may_write(найдено, tenant=tenant):
        raise MethodologyRefused(t("methodology.etalon_readonly", _lang()))
    return найдено


def checklists_overview(store: Store, *, tenant: str) -> list[lists_door.Overview]:
    """Чек-листы, видимые пространству: своё и эталон. Чужие пространства не читаются."""
    try:
        return lists_door.overview(store, spaces=visible_spaces(tenant))
    except McpError as отказ:
        raise _refusal(отказ) from None
```

(Язык текста отказа: модуль сегодня текстов не знает. Если `_lang()` в нём нет, `store_for` получает параметр `lang: str`, и `app.py` передаёт `_lang(conf)`; второй вариант предпочтительнее — модуль остаётся без Flask.)

`RailRow` получает `space: str` и `etalon: bool`; в `checklist_rail` — `space=c.space, etalon=c.space == DEFAULT_SPACE`.

- [ ] **Step 4: Реализация `src/web/app.py`**

- `_apply`: `method.store_for(state.store, _который(request), tenant=auth.current_tenant(), write=True)`.
- `_render_methodology`: `method.checklists_overview(state.store, tenant=auth.current_tenant())`; `method.store_for(state.store, код, tenant=..., write=False)`.
- маршруты `publish`, `state`, `bot`, `apply` (POST) — `write=True`; `GET .../<code>/apply` (предпросмотр) — `write=False`.
- заведение нового чек-листа (`POST` на `путь` раздела, строка 1308): у партнёра заведения нет (спека, «Заведение»), поэтому в начале обработчика `if auth.current_tenant() != HQ_TENANT: return _render_methodology(conf, notice=None, failure=t("methodology.etalon_readonly", _lang(conf)))`.

- [ ] **Step 5: Тексты `src/web/texts.py`**

```python
    "methodology.not_found": {
        "ru": "Чек-листа «{code}» нет.",
        "en": "There is no checklist “{code}”.",
    },
    "methodology.etalon_readonly": {
        "ru": "Эталон правит только УК. Здесь его можно смотреть, но не менять.",
        "en": "Only HQ edits the reference checklist. You can view it here but not change it.",
    },
```

- [ ] **Step 6: Прогнать тесты**

Run: `.venv/bin/pytest tests/test_web_methodology_spaces.py tests/test_web_methodology.py tests/test_web_methodology_screen.py tests/test_web_methodology_rail.py tests/test_web_checklists_screen.py tests/test_web_bot_access.py tests/test_web_texts.py tests/test_web_bounds.py -q --no-cov`
Expected: PASS. Тесты, где стенд и учётка — `укашка` или иной не-slug тенант, а методика правится, получают тенант `HQ` (`grep -ln 'tenant="укашка"\|ТЕНАНТ = "укашка"' tests/test_web_*.py`).

- [ ] **Step 7: Негативный прогон**

В `store_for` убрать `if write and not may_write(...)` → падает `test_ни_одна_правка_эталона_из_пространства_партнёра_не_проходит` (журнал эталона вырос). В `checklists_overview` убрать `spaces=` → падает `test_чужой_код_звучит_как_несуществующий` («РНД» на странице). Вернуть.

- [ ] **Step 8: Commit**

```bash
git add src/web/methodology.py src/web/app.py src/web/texts.py tests/test_web_methodology_spaces.py tests/test_web_*.py
git commit -m "feat(web): методика по пространству — эталон партнёру только на чтение (#340)"
```

---

### Task 10: Разделы «только HQ» (D264)

**Files:**
- Modify: `src/web/sections.py` (`Section.hq_only`, `visible_sections`, новая `refused_for`)
- Modify: `src/web/app.py` (регистрация заслона сразу после `auth.install(app, conf)`, строка 80)
- Test: `tests/test_web_sections.py` (дописать)

**Interfaces:**
- Consumes: `auth.current_tenant()` (Task 8).
- Produces: `Section.hq_only: bool = False`; `refused_for(path: str, tenant: str) -> bool`; заслон `before_request` отвечает 404 на любой адрес раздела `hq_only` (и вложенный) для тенанта не `HQ`. В волне флаг стоит у `tenants` (заведение пространств — дело УК). Раздел действий УК из спеки страны (волна 2 той спеки) получает флаг при заведении; «Люди» — по ответу на вопрос 7.

- [ ] **Step 1: Написать падающие тесты**

```python
from src.web.sections import SECTIONS, Section, refused_for, section, visible_sections


class _Кто:
    def __init__(self, tenant: str, role: str = "auditor") -> None:
        self.tenant, self.role = tenant, role


def test_раздел_только_для_уК_скрыт_у_партнёра() -> None:
    ключи = {s.key for s in visible_sections(_Кто("GE"))}
    assert "tenants" not in ключи
    assert "tenants" in {s.key for s in visible_sections(_Кто("HQ"))}


def test_старый_код_уК_видит_раздел_уК() -> None:
    assert "tenants" in {s.key for s in visible_sections(_Кто("default"))}


def test_адрес_раздела_уК_отказывает_партнёру_и_вложенный_тоже() -> None:
    путь = section("tenants").path
    assert refused_for(путь, "GE") and refused_for(путь + "/GE", "GE")
    assert not refused_for(путь, "HQ")
    assert not refused_for(section("registry").path, "GE")


def test_партнёр_получает_404_на_разделе_уК(monkeypatch: pytest.MonkeyPatch) -> None:
    подменить_двери(monkeypatch, tenant="GE")
    with собрать(tenant="HQ").test_client() as client:
        войти(client)
        assert client.get(section("tenants").path).status_code == 404


def test_каждый_раздел_только_уК_закрыт(monkeypatch: pytest.MonkeyPatch) -> None:
    """Флаг, поставленный завтра новому разделу, проверяется этим же тестом."""
    подменить_двери(monkeypatch, tenant="GE")
    закрытые = [s for s in SECTIONS if s.hq_only]
    assert закрытые, "ни один раздел не помечен — тест ничего не проверяет"
    with собрать(tenant="HQ").test_client() as client:
        войти(client)
        for s in закрытые:
            assert client.get(s.path).status_code == 404, s.key
```

(Импорты `подменить_двери`, `собрать`, `войти` из `web_harness`, если в файле их ещё нет.)

- [ ] **Step 2: Прогнать и убедиться, что падают**

Run: `.venv/bin/pytest tests/test_web_sections.py -q --no-cov`
Expected: FAIL — `ImportError: cannot import name 'refused_for'`.

- [ ] **Step 3: Реализация `src/web/sections.py`**

```python
from src.domain.tenants import HQ_TENANT, canonical_tenant

@dataclass(frozen=True)
class Section:
    ...
    #: Виден и открывается ТОЛЬКО пространству УК (D264). Заслон — на раздел
    #: целиком (`refused_for` в `before_request`), а не на каждую кнопку.
    hq_only: bool = False
```

В `SECTIONS`: `Section(key="tenants", path="/tenants", built=False, icon="board", hq_only=True)`.

```python
def refused_for(path: str, tenant: str) -> bool:
    """Закрыт ли этот адрес этому пространству: раздел только для УК, а тенант не УК."""
    ключ = current_section(path)
    return ключ is not None and section(ключ).hq_only and canonical_tenant(tenant) != HQ_TENANT


def visible_sections(account: object | None) -> tuple[Section, ...]:
    админ = getattr(account, "role", None) == "admin"
    уК = canonical_tenant(str(getattr(account, "tenant", "") or "")) == HQ_TENANT
    return tuple(
        item for item in SECTIONS
        if (админ or not item.admin_only) and (уК or not item.hq_only)
    )
```

`src/web/app.py`, сразу после `auth.install(app, conf)`:

```python
    @app.before_request
    def _только_уК() -> None:
        """Раздел только для УК отвечает партнёру тем же 404, что несуществующий адрес."""
        if request.endpoint in auth.OPEN_ENDPOINTS or auth.current_account() is None:
            return
        if refused_for(request.path, auth.current_tenant()):
            abort(404)
```

- [ ] **Step 4: Прогнать тесты**

Run: `.venv/bin/pytest tests/test_web_sections.py tests/test_web_app.py tests/test_web_auth.py -q --no-cov`
Expected: PASS.

- [ ] **Step 5: Негативный прогон**

Убрать регистрацию `_только_уК` → падают `test_партнёр_получает_404_на_разделе_уК` и `test_каждый_раздел_только_уК_закрыт` (200 от экрана «в разработке»). Вернуть.

- [ ] **Step 6: Commit**

```bash
git add src/web/sections.py src/web/app.py tests/test_web_sections.py
git commit -m "feat(web): признак раздела «только УК» и заслон на сервере (D264, #340)"
```

---

### Task 11: Заведение пространств и людей командой

**Files:**
- Modify: `src/db/web_access.py` (новые `SPACE_CODE`, `SpaceRow`, `check_space_code`, `space_exists`, `create_space`, `list_spaces`, `copy_units`)
- Create: `tools/space.py`
- Modify: `tools/web_user.py` (`_tenant`: незаведённое пространство — отказ)
- Modify: `Makefile` (цель `space`, `.PHONY`)
- Test: `tests/test_db_spaces.py` (новый)

**Interfaces:**
- Produces: `create_space(code: str, *, name: str) -> SpaceRow`; `list_spaces() -> tuple[SpaceRow, ...]`; `space_exists(code: str) -> bool`; `copy_units(space: str, *, countries: tuple[str, ...]) -> int` — число скопированных точек (вопрос владельцу 3); `SpaceRow(code: str, name: str, people: int)`. Команды: `make space ARGS="add GE --name 'Партнёр Грузия'"`, `make space ARGS="list"`, `make space ARGS="units GE --country GE"`.

- [ ] **Step 1: Написать падающие тесты**

```python
"""Волна 1 (#340): пространства заводит команда проекта, опечатка не заводит новое."""

from __future__ import annotations

import pytest
from conftest import requires_db

psycopg = pytest.importorskip("psycopg")

from src.db.directory import list_units, upsert_unit  # noqa: E402
from src.db.errors import AccessError  # noqa: E402
from src.db.web_access import copy_units, create_space, list_spaces, space_exists  # noqa: E402

pytestmark = requires_db


@pytest.fixture
def владелец(pg_dsn: str, db_env: str, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("DATABASE_ADMIN_URL", pg_dsn)
    return pg_dsn


def test_пространство_заводится_и_видно(владелец: str) -> None:
    create_space("GE", name="Партнёр Грузия")
    assert space_exists("GE")
    assert ("GE", "Партнёр Грузия") in {(s.code, s.name) for s in list_spaces()}


@pytest.mark.parametrize("код", ["ge", "../hq", "", "Г1", "HQ", "default"])
def test_негодный_или_занятый_код_это_отказ(владелец: str, код: str) -> None:
    if not space_exists("HQ"):
        create_space("HQ", name="УК")
    with pytest.raises(AccessError):
        create_space(код, name="х")


def test_точки_копируются_только_названных_стран(владелец: str) -> None:
    upsert_unit("Batumi-1", aliases=(), country="GE", city="Batumi", tenant="HQ")
    upsert_unit("Yerevan-1", aliases=(), country="AM", city="Yerevan", tenant="HQ")
    create_space("GP", name="Партнёр")
    assert copy_units("GP", countries=("GE",)) == 1
    assert [u.name for u in list_units(tenant="GP")] == ["Batumi-1"]
    assert copy_units("GP", countries=("GE",)) == 0, "повтор не плодит двойников"
```

- [ ] **Step 2: Прогнать и убедиться, что падают**

Run: `make test-honest ARGS="tests/test_db_spaces.py -q"`
Expected: FAIL — `ImportError: cannot import name 'create_space'`.

- [ ] **Step 3: Реализация `src/db/web_access.py`**

```python
#: Код нового пространства: заглавные латинские, цифры, дефис, подчёркивание.
#: Строчными он становится каталогом хранилища методики (`checklist_layout.space_of`).
SPACE_CODE = re.compile(r"^[A-Z][A-Z0-9_-]{1,31}$")

_LIST_SPACES_SQL = """
    select t.code, t.name, count(u.id) filter (where u.disabled_at is null)
      from tenants t left join web_users u on u.tenant_code = t.code
     group by t.code, t.name order by t.code
"""

_COPY_UNITS_SQL = """
    insert into units (tenant_code, name, name_normalized, code, country, city)
    select %(space)s, name, name_normalized, code, country, city
      from units
     where tenant_code = %(hq)s and country = any(%(countries)s)
    on conflict (tenant_code, name_normalized) do nothing
"""


@dataclass(frozen=True)
class SpaceRow:
    code: str
    name: str
    people: int


def check_space_code(code: str) -> str:
    """Код нового пространства — или отказ с примером годного."""
    значение = (code or "").strip()
    if not SPACE_CODE.match(значение) or значение in LEGACY_TENANTS:
        raise AccessError(
            f"Код пространства «{code}» не годится: заглавные латинские буквы, цифры, дефис, "
            f"подчёркивание, от 2 до 32 знаков (например «GE»). Код не меняется никогда"
        )
    return значение


def space_exists(code: str) -> bool:
    with _connected("проверить пространство") as conn, conn.cursor() as cur:
        cur.execute(_SELECT_TENANT_SQL, (canonical_tenant(code),))
        return cur.fetchone() is not None


def create_space(code: str, *, name: str) -> SpaceRow:
    """Завести пространство. Код, совпадающий с заведённым без учёта регистра, — отказ:
    каталог хранилища у них был бы один."""
    код = check_space_code(code)
    занятые = {s.code.lower() for s in list_spaces()}
    if код.lower() in занятые:
        raise AccessError(f"Пространство «{код}» уже заведено (или совпадает с заведённым без учёта регистра)")
    with _owned(f"завести пространство «{код}»") as conn, conn.cursor() as cur:
        cur.execute("insert into tenants (code, name) values (%s, %s)", (код, name.strip()))
    return SpaceRow(code=код, name=name.strip(), people=0)


def list_spaces() -> tuple[SpaceRow, ...]:
    with _owned("перечислить пространства") as conn, conn.cursor() as cur:
        cur.execute(_LIST_SPACES_SQL)
        return tuple(SpaceRow(code=str(r[0]), name=str(r[1]), people=int(r[2])) for r in cur.fetchall())


def copy_units(space: str, *, countries: tuple[str, ...]) -> int:
    """Скопировать точки названных стран из справочника УК в пространство партнёра.

    Партнёр пиццерии не заводит (D234), а точка проверки ссылается на точку
    своего тенанта (`inspections_unit_same_tenant`). Вопрос владельцу 3.
    """
    if not space_exists(space):
        raise AccessError(f"Пространства «{space}» нет — заведите его: make space ARGS=\"add {space}\"")
    with _owned(f"скопировать точки в «{space}»") as conn, conn.cursor() as cur:
        cur.execute(_COPY_UNITS_SQL, {"space": canonical_tenant(space), "hq": HQ_TENANT,
                                      "countries": list(countries)})
        return cur.rowcount
```

Импорты: `re`, `HQ_TENANT`, `LEGACY_TENANTS`, `canonical_tenant` из `src.domain.tenants`. Колонки `units` (`code`, `country`, `city`, `name_normalized`) сверить с `src/db/migrations/0017_unit_geography.sql` и `src/db/directory.py`; синонимы точек (`unit_aliases`) не копируются — их заводит УК, партнёр пишет каноническое имя (D233).

Файл после добавления — около 720 строк, в пределе 800. Если перевалит, пространства выносятся в `src/db/spaces.py`, а `_connected`/`_owned` — в общий модуль подключений.

- [ ] **Step 4: `tools/space.py` и `tools/web_user.py`**

`tools/space.py` — по образцу `tools/web_user.py` (тот же `load_dotenv`, `sys.path`, `argparse` с подкомандами `add CODE --name`, `list`, `units CODE --country XX [--country YY]`), печатает итог одной строкой, ошибки `AccessError` — `SystemExit` с текстом отказа. В `tools/web_user.py`, `_tenant`, после получения кода:

```python
    if not space_exists(tenant):
        raise SystemExit(
            f"Пространства «{tenant}» нет. Опечатка в --tenant завела бы новое пустое "
            f"пространство молча; заведите его явно: make space ARGS=\"add {tenant} --name ...\""
        )
```

(`ensure` для стенда разработки не проверяется: `make web-up` заводит свой тенант сам; у подкоманды `ensure` вызов `space_exists` пропускается.)

`Makefile`: цель `space: ; $(VENV)/python tools/space.py $(ARGS)` с комментарием в стиле `web-user` (под ролью владельца схемы, примеры команд), и `space` в `.PHONY`.

- [ ] **Step 5: Прогнать тесты и команду**

Run: `make test-honest ARGS="tests/test_db_spaces.py tests/test_db_web_access.py tests/test_db_units.py -q"`, затем на тестовой базе MUSPELHEIM: `make space ARGS="list"`.
Expected: PASS; перечень печатается, `HQ` в нём есть.

- [ ] **Step 6: Commit**

```bash
git add src/db/web_access.py tools/space.py tools/web_user.py Makefile tests/test_db_spaces.py
git commit -m "feat(db): пространства и справочник партнёра заводятся командой (#340)"
```

---

### Task 12: Документация, приёмка на стенде, итоговая проверка

**Files:**
- Modify: `docs/12-web-admin.md`, `docs/06-mvp-bot.md`, `docs/08-deploy.md`, `docs/furca/blocks/bot.md`, `docs/furca/blocks/web.md`, `docs/furca/blocks/mcp.md`, `docs/furca/blocks/db.md`, `.env.example`, `CHANGELOG.md`

- [ ] **Step 1: Доки (скилл `keeping-docs-current`)**

Сверять с кодом, не по памяти:
- `.env.example`: `BOT_INVITES` — формат `[<ПРОСТРАНСТВО>/]<юзернейм>[:Имя]` с примером; `BOT_MCP_TENANT` удалить вместе с абзацем про него (строки 387–420); `WEB_TENANT` — «тенант стенда: счётчик попыток входа и умолчание `make web-user`; чьи данные видны, решает учётка».
- `docs/12-web-admin.md`: вход — один адрес для всех пространств, логин единый на базу; эталон партнёру на чтение; разделы «только УК»; команды `make space`.
- `docs/06-mvp-bot.md`, `docs/furca/blocks/bot.md`: приглашение с пространством, заслон чужой проверки в чате, токен MCP в пространстве аудитора.
- `docs/furca/blocks/mcp.md`: хранилище правки — пространство токена; без `checklist` у партнёра — отказ.
- `docs/furca/blocks/db.md`: миграция `0028`, уникальность логина и почты.
- `docs/08-deploy.md`: перед накатом `0028` на проде — запрос двойников из текста миграции; порядок раскатки.
- `CHANGELOG.md`: запись волны 1.
- Карточка imf-vc (`decimus.yaml`) не меняется: адрес, бот и шаги входа прежние.

- [ ] **Step 2: Итоговые проверки**

Run: `make check` (fmt, lint, types, test на тестовой базе MUSPELHEIM, dead, bounds).
Expected: PASS, кроме падений, записанных в «Перед началом» как известная помеха #348; новых нет.

Run: регресс belgrade из Global Constraints.
Expected: 97.5%, A, 5×D1 и 97.0%, A, 6×D1.

- [ ] **Step 3: Приёмочный смоук на стенде MUSPELHEIM (скилл `muspelheim`, не на Маке)**

По шагам, с записью фактического ответа каждого:
1. `make migrate` на базе стенда; `make space ARGS="add GE --name 'Партнёр Грузия'"`; `make space ARGS="units GE --country GE"`.
2. `make web-user ARGS="add ge-director --tenant GE"`; вход этой учёткой на стенде: «Проверки» пусты, «Методика» открывает эталон, «Сохранить» на пункте отвечает «Эталон правит только УК».
3. Адрес карточки проверки УК, скопированный из-под учётки УК, у `ge-director` — страница «не найдено», та же, что у выдуманного id; то же для `/photos/<id>` кадра этой проверки.
4. `/tenants` у `ge-director` — 404, у учётки УК — экран «в разработке».
5. Бот стенда: `BOT_INVITES` с `GE/<юзернейм тестового аккаунта>`, перезапуск; проверка от этого аккаунта — справочник предлагает `Batumi-1`, незнакомая пиццерия отвечает «заводит только УК», сданная проверка лежит в базе с `tenant_code = 'GE'` (запрос под ролью владельца, только `select tenant_code`).
6. Демо-стенд (вопрос 6): поднимается, «Методика» показывает эталон и отказ правки, а не ошибку.

Что проверить нельзя (например, бот стенда недоступен) — записать в отчёт прямо, не выдавать за проверенное.

- [ ] **Step 4: Commit и PR**

```bash
git add docs .env.example CHANGELOG.md
git commit -m "docs: пространства (волна 1) — вход, приглашение, методика, команды (#340)"
git push -u origin feat/spaces-wave1
gh pr create --title "Пространства, волна 1: граница на сервере (#340)" --body "..."
```

PR не вливается и не раскатывается без «да» владельца; миграция `0028` на проде — отдельное «да» (скилл `deploy-window`).

---

## Самопроверка плана

- **Спека → задачи.** «У человека одно пространство: в админке полем учётки» — задача 7 (поле уже есть, `web_users.tenant_code`; меняется то, что вход его читает). «В боте — полем приглашения» — задача 4. «Граница на сервере, на каждом запросе: экран, дверь методики, MCP, бот» — задачи 8, 9, 2, 5–6. «Чужой — „не найден“ тем же ответом» — задачи 1, 8, 9. «Эталон — исключение, только чтение» — задачи 1, 2, 9. «Проверка пишется в пространство аудитора» — задачи 3, 6. «Заводит админ командой» — задача 11. «Раздел действий УК виден только HQ» (D264) — задача 10. Заслоны «Галочка „в боте“ у черновика…», «Смена кода», «Удаления нет» уже стоят с волны 3 (`bot_block`, `check_slug`, `create`) и волной не трогаются.
- **Не входит (волны 2–5 спеки):** раскладка экрана с группами «От УК»/«Наши», копия эталона правкой и предложения, «Обзор» с выбором чек-листа. Волна 1 кладёт под них данные (`RailRow.etalon`, `BotChecklist.space`) и не рисует их.
- **Риски, оставшиеся после волны:** слив проверки заводит точку в тенанте проверки, если справочник был недоступен на старте (`src/db/push.py`, `resolve_unit_id` и `insert into units`), — у партнёра это обход D234 при сбое базы; в волне не чинится, задача #471. Перевод человека в другое пространство в боте — ручная правка `roster.json`; команды нет. Коды проверки хранят `checklist_code` без пространства (T345): в волне 1 коды эталона и партнёра не повторяются (задача 1), а колонка пространства проверки понадобится в волне 4, когда появятся копии.
