# Пространства (волна 1): план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** У каждого пространства свои люди, человек принадлежит одному пространству и входит своим логином. Бот привязывается к учётке через веб одноразовой ссылкой. Граница проверяется на сервере на каждом запросе — в вебе, в двери методики, в MCP и в боте. УК читает всё и пишет только своё; партнёр видит только своё (свою страну) и читает эталон. Чужое по прямому адресу — «не найден» тем же ответом, что несуществующее.

**Architecture:** Пространство — существующий тенант (`tenants.code`; `web_users.tenant_code`, `mcp_tokens.tenant_code`, `inspections.tenant_code` уже есть). Каталог пространства в хранилище методики — код строчными (`HQ` → `hq`, D183). Партнёр привязан к своим странам (новая таблица `space_countries`, одна страна — одно пространство, D284). Справочник пиццерий один: проверка партнёра ссылается на точку справочника УК его страны — составная ссылка «точка своего тенанта» заменяется простой ссылкой на точку и сторожем «точка из стран пространства». Чтение идёт через **охват** (`Reach`): у УК — всё, у партнёра — пиццерии его стран. Запись — только в своё пространство. Тенант человека берётся из учётки (веб), из привязки Telegram ID к учётке (бот), из токена (MCP) — больше ни из одного конфига.

**Tech Stack:** Python 3.12, Flask + Jinja (`src/web`), aiogram 3 (`src/bot`), psycopg 3 + Postgres (`src/db`), свой JSON-RPC MCP (`src/mcp`), pytest.

**Spec:** `docs/superpowers/specs/2026-09-28-checklist-admin-design.md`, разделы «Пространства», «Заслоны», «Волны» (D227). Решения владельца по этому плану: D282 (свои люди, логин уникален в системе), D283 (УК делает эталоны и читает партнёров, партнёр — только своё), D284 (одна страна — один партнёр, справочник один), D285 (в боте партнёра все годные эталоны), D286 (бот привязывается через веб), D287 (демо — пространство партнёра), D288 (права админа партнёра — открыто, не строим). Также D182, D183, D234, D264. Родитель #340 (часть #423). Смежная спека `2026-09-30-country-and-prescriptions-design.md`, «Доступы».

## Вопросы владельцу

Только открытое. Для каждого вопроса назван вариант по умолчанию, по которому построен план, и задача, которая изменится при другом ответе.

1. **Видит ли партнёр проверки своих пиццерий, которые провела УК?** D283 говорит «партнёр видит только своё». Без этих проверок не работает запрос экшн-плана (D272): УК проверила Батуми-1, партнёр Грузии должен увидеть запрос по этой проверке. **По умолчанию — да, и только проверки пиццерий своей страны**: охват партнёра — пиццерии его стран, кто бы ни проверял (задача 5, `reach_of`). Если ответ «нет», охват партнёра сужается до его собственных проверок — меняется одна строка в `reach_of`.
2. **Как действующие аудиторы УК переходят на привязку через веб.** Сегодня аудитор пускается по двум спискам: `ALLOWED_TELEGRAM_IDS` в окружении и `roster.json`, собранный по `BOT_INVITES`. Учётки в вебе у аудиторов может не быть. **По умолчанию:** оба списка на время волны работают как совместимость — «сотрудник УК». Новых записей не появляется: `BOT_INVITES` снимается, новые люди приходят только привязкой. Совместимость снимается отдельным шагом, когда админ УК завёл учётки всем и каждый привязал бота (задача 11). Нужно решение: снимать совместимость к запуску на партнёров или держать дальше.
3. **Бот при недоступной базе.** Привязки живут в базе, а сейчас доступ бота от базы не зависит нарочно (`src/bot/roster.py`: «отказ базы не мешает боту подняться»). **По умолчанию:** уже узнанный человек работает по последнему удачному ответу базы. Отвязка и отключение учётки при живой базе действуют в течение минуты (кэш). Незнакомый при недоступной базе не пускается (задача 11). Альтернатива — при отказе базы бот не пускает никого.
4. **Один Telegram на учётку.** **По умолчанию:** новая привязка той же учётки гасит прежнюю, как новый токен MCP гасит прежний (`replaced_previous`). Telegram, уже привязанный к другой учётке, новой ссылкой не перепривязывается — нужно сначала отвязать (задача 9). Альтернатива — отказывать во второй привязке, пока прежняя не снята руками.

Открыто и в волну не входит (D288): права админа партнёра. В волне людей в любое пространство заводит админ УК на вкладке «Пользователи», и роль `admin` у учётки партнёра на этой вкладке ничего не открывает.

## Global Constraints

- Сущности связываются кодами, не формулировками (CLAUDE.md). Пространство — код тенанта, страна — код ISO (`units.country`), каталог хранилища — код тенанта строчными.
- Язык — параметр: каждый новый текст заводится в `src/web/texts.py` и `src/bot/texts.py` на `ru` и `en` в одном изменении (скилл `product-i18n`).
- Оценка только через движок; ставки и пороги в коде не дублировать.
- Регресс-сверка после изменений: `cd examples/belgrade-1 && python3 ../../engine/audit.py score` → 97.5%, A, 5×D1; `cd ../belgrade-2 && python3 ../../engine/audit.py score` → 97.0%, A, 6×D1.
- Тесты с базой — на тестовой базе MUSPELHEIM (`make test`, `make test-honest`). Локальный Postgres и стенды на Маке не поднимаются.
- Значения секретов не читаются (`.env`, `printenv` закрыты хуком).
- Чужое по прямому адресу — «не найден» тем же кодом и текстом, что несуществующее. Чтение чужого, которое разрешено (УК у партнёра), с попыткой записи — отказ «пространство пишет только своё». Правка эталона из пространства партнёра — «эталон правит только УК».
- Текст SQL не собирается строкой (правило S608, `src/db/queries.py`): охват передаётся параметрами-массивами в неизменном тексте запроса.
- Каждый заслон прогоняется на сломанном коде: заслон временно ломается, тест обязан упасть с понятной причиной, затем правка возвращается, и `git diff` показывает, что поломка действительно применялась.
- Раскатка — только по «да» владельца и в ночное окно (скилл `deploy-window`). План заканчивается PR. Миграции `0028`–`0031` на проде — отдельное «да».

## Review Focus

Самые вероятные дыры границы. Тест к каждой стоит в задаче, которая владеет кодом.

1. **Ссылка привязки бота: перехват и повтор.** Ссылку `t.me/<бот>?start=<токен>` переслали, сняли с экрана, открыли дважды или спустя час. Ожидание: токен срабатывает один раз и живёт 10 минут; повтор, чужой и просроченный токен получают один и тот же отказ, и привязка не меняется. В базе лежит только отпечаток токена. Новая ссылка гасит прежнюю, не использованную. На странице «Пользователи» видно, какой Telegram привязан и когда. Тест — задача 9.
2. **Второй Telegram к той же учётке и чужой Telegram к учётке.** Ожидание: у учётки одна живая привязка. Новая гасит прежнюю, и прежний ID теряет доступ на следующем апдейте после истечения кэша. Telegram, привязанный к учётке A, по ссылке учётки B не перепривязывается. Тест — задачи 9 и 11.
3. **Отвязка и отключение действуют на бота.** Отключили учётку в вебе или нажали «Отвязать», а бот продолжает пускать по старому кэшу или по файлу связок. Ожидание: при живой базе доступ пропадает в течение `BINDING_TTL`. Совместимость по `ALLOWED_TELEGRAM_IDS`/`roster.json` не открывает человека, у которого есть привязка, — привязка главнее. Тест — задача 11.
4. **MCP-токен партнёра без аргумента `checklist`.** `for_code(store, None)` идёт по единому указателю прода, а он смотрит в `hq`. Ожидание: партнёр без кода получает «назовите чек-лист», эталон не тронут. Тест — задачи 1 и 2.
5. **Кадр, отчёт, письмо, снятие, перенос по чужой проверке по прямому адресу.** Ожидание: для партнёра — 404 тем же шаблоном, что у несуществующей. Для УК на проверке партнёра карточка открывается, а снятие, перенос и сохранение письма отвечают отказом записи; дверь записи получает только тенант вошедшего. Тест — задача 6.
6. **Бот: проверка чужого пространства в чате.** Кнопки со старых сообщений и новые кадры в чате, где идёт проверка другого пространства. Ожидание: до обработчика апдейт не доходит, человек получает одну строку. Тест — задача 11.
7. **Пиццерия чужой страны в проверке партнёра.** Сбой справочника при старте (#471), подменённое название или перенос проверки. Ожидание: база не запишет проверку партнёра на точку вне его стран — сторож в схеме, а не только в боте. Тест — задача 5.

---

## Перед началом

- [ ] `git fetch origin && git switch -c feat/spaces-wave1 origin/main` в своём worktree (скилл `worktrees`).
- [ ] Базовый прогон `make test` и регресс-сверка belgrade. Записать число упавших ДО работы: помеха #348 (тестовая база не чистится между запусками) красит проверки доступа, и её падения не должны читаться как регрессия волны.
- [ ] Если PR #472 (экран «Страна», `src/web/country.py`, `_register_country`) уже влит — работать поверх него. Если нет — тот, кто вливается вторым, прогоняет `tests/test_web_tenant_source.py` (задача 6) после слияния.

## Карта файлов

| Файл | Что меняется |
|---|---|
| `src/mcp/checklist_layout.py` | `space_of`, `read_spaces`, `bot_spaces`, `exists`, `locate`, `may_write`; `for_code` не переходит в чужое пространство |
| `src/mcp/checklists.py`, `src/mcp/checklist.py` | перечень по пространствам, прод только у УК, коды эталона и партнёра не повторяются, снимок боевой методики только в `hq` |
| `src/mcp/server.py`, `src/mcp/rpc.py`, `src/mcp/checklists_tools.py`, `src/mcp/tools.py` | хранилище по тенанту токена; чтение проверок по охвату |
| `src/domain/bot_checklists.py`, `src/domain/state.py` | чек-листы бота по пространству аудитора |
| `src/db/migrations/0028_login_across_spaces.sql` | логин и почта уникальны во всей базе |
| `src/db/migrations/0029_space_countries.sql` | страны пространства партнёра |
| `src/db/migrations/0030_inspection_unit_of_space.sql` | проверка ссылается на точку справочника; сторож «точка из стран пространства» |
| `src/db/migrations/0031_bot_bindings.sql` | ссылки привязки и привязки Telegram ID к учётке |
| `src/db/reach.py` (новый) | охват чтения: `Reach`, `reach_of`, `countries_of` |
| `src/db/queries.py`, `reports.py`, `previews.py`, `move.py`, `directory.py`, `push.py` | чтение по охвату, соединение с точкой по `id`, слив проверки партнёра без заведения точки |
| `src/db/web_access.py` | вход без тенанта стенда; пространства и их страны |
| `src/db/bot_links.py` (новый) | выпуск ссылки, погашение, привязка, отвязка, опознание по Telegram ID |
| `src/web/auth.py`, `app.py`, `letter_draft.py`, `country.py` (после #472), `inspections.py`, `methodology.py`, `sections.py`, `accounts.py`, `config.py`, `texts.py`, `templates/users/index.html` | тенант и охват вошедшего; запись только в своё; методика по пространству; «только HQ»; вкладка «Пользователи» с привязкой бота |
| `src/bot/access.py`, `app.py`, `config.py`, `routers/start.py`, `routers/mcp.py`, `unit_pick.py`, `phrases.py`, `texts.py` | доступ по привязке, совместимость, заслон чата, пространство человека в обработчиках |
| `src/bot/invites.py` | удаляется (D286) |
| `tools/space.py` (новый), `tools/web_user.py`, `tools/seed_web_demo.py`, `Makefile` | заведение пространств и стран; демо — пространство партнёра |
| доки: `docs/12-web-admin.md`, `docs/06-mvp-bot.md`, `docs/08-deploy.md`, `docs/furca/blocks/{bot,web,mcp,db}.md`, `.env.example`, `CHANGELOG.md` | описание поведения и переменных |

Ядро с тестами до кода (правило тестирования): задачи 1, 2, 5, 6, 7, 8, 9, 11 — заслоны доступа и привязка. Остальное — тест на поведение плюс прогон.

---

### Task 1: Пространства в раскладке хранилища методики

**Files:**
- Modify: `src/mcp/checklist_layout.py` (после `check_slug`; `for_code`, строки 318–335)
- Modify: `src/mcp/checklists.py` (`overview` строка 139, `create` 271, `apply_to_production` 476, `_settle_inherited` 581)
- Modify: `src/mcp/checklist.py` (`_ensure`, строка 566)
- Test: `tests/test_mcp_spaces.py` (новый)

**Interfaces:**
- Produces:
  - `space_of(tenant: str) -> str` — `"HQ"` → `"hq"`, негодный код → `ChecklistError`.
  - `bot_spaces(tenant: str) -> tuple[str, ...]` — где искать чек-лист «по коду» и что предлагать в боте: `("hq",)` у УК, `(<своё>, "hq")` у партнёра, своё первым.
  - `read_spaces(tenant: str, root: Path) -> tuple[str, ...]` — что тенант может ЧИТАТЬ: у УК — `hq` и все пространства хранилища (D283), у партнёра — как `bot_spaces`.
  - `exists(store: Store) -> bool`.
  - `locate(store: Store, *, tenant: str, code: str | None, space: str | None = None) -> Store | None` — `space` не назван: поиск по `bot_spaces`; назван: только если он в `read_spaces`. `None` означает «не найден», и чужой в нём неотличим от несуществующего.
  - `may_write(store: Store, *, tenant: str) -> bool` — только своё пространство.
  - `overview(store: Store, *, spaces: tuple[str, ...] | None = None) -> list[Overview]`.

- [ ] **Step 1: Написать падающие тесты**

```python
"""Волна 1 (#340): граница пространств в хранилище методики.

Ядро — тихий переход в чужое пространство. Код чек-листа приходит снаружи, а
единый указатель прода смотрит в `hq`: любая дорога «по умолчанию» уводит
партнёра в эталон. Сторожится, В КАКОЕ пространство наведено хранилище.
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
    DEFAULT_SPACE, applied, bot_spaces, for_code, locate, may_write, read_spaces, space_of,
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
    with pytest.raises(ChecklistError):
        space_of("../hq")


def test_бот_партнёра_смотрит_своё_и_эталон_бот_уК_только_эталон() -> None:
    assert bot_spaces(HQ_TENANT) == ("hq",)
    assert bot_spaces("GE") == ("ge", "hq")


def test_уК_читает_все_пространства_партнёр_только_своё(склад: Store) -> None:
    assert set(read_spaces(HQ_TENANT, склад.root)) == {"hq", "ge", "am"}
    assert read_spaces("GE", склад.root) == ("ge", "hq")


def test_чужой_код_неотличим_от_несуществующего(склад: Store) -> None:
    assert locate(склад, tenant="GE", code="rnd") is None
    assert locate(склад, tenant="GE", code="nothing") is None
    assert locate(склад, tenant="GE", code="rnd", space="am") is None


def test_партнёр_находит_эталон_и_своё(склад: Store) -> None:
    эталон = locate(склад, tenant="GE", code="bizdev")
    своё = locate(склад, tenant="GE", code="own")
    assert эталон is not None and (эталон.space, эталон.code) == ("hq", "bizdev")
    assert своё is not None and (своё.space, своё.code) == ("ge", "own")


def test_уК_открывает_чек_лист_партнёра_только_на_чтение(склад: Store) -> None:
    assert locate(склад, tenant=HQ_TENANT, code="own") is None, "без пространства — только эталон"
    чужое = locate(склад, tenant=HQ_TENANT, code="own", space="ge")
    assert чужое is not None and чужое.space == "ge"
    assert may_write(чужое, tenant=HQ_TENANT) is False


def test_без_кода_партнёр_получает_эталон_на_чтение(склад: Store) -> None:
    найдено = locate(склад, tenant="GE", code=None)
    assert найдено is not None and (найдено.space, найдено.code) == ("hq", "bizdev")
    assert may_write(найдено, tenant="GE") is False


def test_указатель_прода_не_уводит_в_чужое_пространство(склад: Store) -> None:
    """Review Focus 4."""
    assert for_code(replace(склад, space="ge"), None).space == "ge"


def test_правка_только_в_своём_пространстве(склад: Store) -> None:
    assert may_write(replace(склад, space="hq"), tenant=HQ_TENANT) is True
    assert may_write(replace(склад, space="ge"), tenant="GE") is True
    assert may_write(replace(склад, space="hq"), tenant="GE") is False
    assert may_write(replace(склад, space="am"), tenant="GE") is False


def test_перечень_сужается_до_названных_пространств(склад: Store) -> None:
    видно = {(c.space, c.code) for c in overview(склад, spaces=bot_spaces("GE"))}
    assert видно == {("hq", "bizdev"), ("ge", "own")}


def test_партнёр_не_применяет_к_проду(склад: Store) -> None:
    журнал = len(read_journal(replace(склад, space="hq", code="bizdev")))
    with pytest.raises(ChecklistError, match="только УК"):
        apply_to_production(replace(склад, space="ge", code="own"), tenant="GE")
    assert applied(склад.root) == ("hq", "bizdev")
    assert len(read_journal(replace(склад, space="hq", code="bizdev"))) == журнал


def test_код_эталона_не_заводится_в_пространстве_партнёра(склад: Store) -> None:
    with pytest.raises(ChecklistError, match="эталон"):
        create(replace(склад, space="ge", code="bizdev"), tenant="GE", name_ru="К", name_en="C", today=СЕГОДНЯ)


def test_уК_не_заводит_код_занятый_партнёром(склад: Store) -> None:
    with pytest.raises(ChecklistError, match="занят"):
        create(replace(склад, space="hq", code="own"), tenant=HQ_TENANT, name_ru="С", name_en="O", today=СЕГОДНЯ)


def test_нетронутое_пространство_партнёра_не_заводится_копией_боевой_методики(tmp_path: Path) -> None:
    """Снимок боевой методики — только первый чек-лист УК (D226: копии без правки нет)."""
    пусто = Store(root=tmp_path / "пусто", live=build_methodology(tmp_path / "м"), space="ge")
    with pytest.raises(ChecklistError):
        current_version(пусто)
    assert not (tmp_path / "пусто" / "ge").exists()
```

- [ ] **Step 2: Прогнать и убедиться, что падают**

Run: `.venv/bin/pytest tests/test_mcp_spaces.py -q --no-cov`
Expected: FAIL — `ImportError: cannot import name 'bot_spaces'`.

- [ ] **Step 3: Реализация `src/mcp/checklist_layout.py`**

`src.domain.tenants` здесь не импортируется: `src.domain` при загрузке тянет `bot_checklists`, а тот — этот модуль, получился бы круг. Связь `HQ` ↔ `hq` держит `test_каталог_пространства_это_код_тенанта_строчными`.

```python
def space_of(tenant: str) -> str:
    """Каталог пространства в хранилище для кода тенанта: `HQ` → `hq` (D183)."""
    return check_slug((tenant or "").strip().lower(), что="Код пространства")


def bot_spaces(tenant: str) -> tuple[str, ...]:
    """Где искать чек-лист по коду и что предлагать боту: своё первым, эталон следом.

    Своё первым: при поиске по коду оно выигрывает, и копия партнёра (волна 4) не
    подменяется эталоном с тем же кодом.
    """
    своё = space_of(tenant)
    return (своё,) if своё == DEFAULT_SPACE else (своё, DEFAULT_SPACE)


def read_spaces(tenant: str, root: Path) -> tuple[str, ...]:
    """Что тенант может читать. УК — всё хранилище (D283), партнёр — своё и эталон."""
    if space_of(tenant) != DEFAULT_SPACE:
        return bot_spaces(tenant)
    прочие = sorted({space for space, _code in known(root)} - {DEFAULT_SPACE})
    return (DEFAULT_SPACE, *прочие)


def exists(store: Store) -> bool:
    """Есть ли такой чек-лист: издания или карточка — тот же признак, что у `known`."""
    return (store.home / VERSIONS_DIR).is_dir() or (store.home / META_FILE).is_file()


def locate(
    store: Store, *, tenant: str, code: str | None, space: str | None = None
) -> Store | None:
    """Хранилище видимого тенанту чек-листа, или `None` — «не найден».

    Один `None` на «нет такого» и «есть, но чужой»: иначе ответ подтверждал бы, что
    чужое существует. Нетронутое хранилище УК отдаётся как есть — его заводит первый
    заход двери (`checklist._ensure`).
    """
    if space is not None:
        if check_slug(space, что="Код пространства") not in read_spaces(tenant, store.root):
            return None
        где: tuple[str, ...] = (space,)
    else:
        где = bot_spaces(tenant)
    нетронуто = где[0] == DEFAULT_SPACE and not known(store.root)
    if code is None:
        for s in где:
            найдено = for_code(replace(store, space=s), None)
            if exists(найдено):
                return найдено
        return replace(store, space=DEFAULT_SPACE, code=DEFAULT_CODE) if нетронуто else None
    код = check_slug(code, что="Код чек-листа")
    for s in где:
        кандидат = replace(store, space=s, code=код)
        if exists(кандидат):
            return кандидат
    return replace(store, space=DEFAULT_SPACE, code=код) if нетронуто else None


def may_write(store: Store, *, tenant: str) -> bool:
    """Правка — только в своём пространстве: эталон у партнёра и партнёр у УК — чтение."""
    return store.space == space_of(tenant)
```

В `for_code` после `space, чей = в_проде`:

```python
    # Указатель прода один на хранилище и смотрит в пространство УК. Кто не назвал
    # чек-лист, остаётся в своём пространстве (Review Focus 4).
    if space != store.space:
        return store
```

- [ ] **Step 4: Реализация `src/mcp/checklists.py` и `src/mcp/checklist.py`**

`overview(store, *, spaces=None)`: в цикле `if spaces is not None and space not in spaces: continue`.

`create`, сразу после отказа «уже есть»:

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

`apply_to_production`, первой строкой после `_alive(store)`:

```python
    if store.space != DEFAULT_SPACE:
        raise ChecklistError(
            "К проду применяет только УК: указатель прода один на всю сеть. "
            "В пространстве партнёра доступ в боте задаётся галочкой «в боте»"
        )
```

`_settle_inherited`: в цикле `if space != store.space: continue`.

`src/mcp/checklist.py`, `_ensure`, перед `return _bootstrap(store)`:

```python
    if store.space != DEFAULT_SPACE:
        raise ChecklistError(
            f"Чек-листа «{store.code}» в пространстве «{store.space}» нет. Перечень отдаёт "
            f"checklists, завести новый — create_checklist"
        )
```

- [ ] **Step 5: Прогнать тесты**

Run: `.venv/bin/pytest tests/test_mcp_spaces.py tests/test_mcp_checklists.py tests/test_mcp_checklist_layout.py tests/test_mcp_checklist_store.py -q --no-cov`
Expected: PASS.

- [ ] **Step 6: Негативный прогон**

По одному, с возвратом: убрать `if space != store.space: return store` → падает `test_указатель_прода_не_уводит_в_чужое_пространство`; в `locate` при названном `space` не сверять с `read_spaces` → падает `test_чужой_код_неотличим_от_несуществующего`; убрать проверку в `apply_to_production` → падает `test_партнёр_не_применяет_к_проду`.

- [ ] **Step 7: Commit**

```bash
git add src/mcp/checklist_layout.py src/mcp/checklists.py src/mcp/checklist.py tests/test_mcp_spaces.py
git commit -m "feat(mcp): граница пространств в хранилище методики (волна 1, #340)"
```

---

### Task 2: MCP — хранилище методики по тенанту токена

**Files:**
- Modify: `src/mcp/server.py` (`_checklist_for` строка 301, `_checklist_source_for` 317)
- Modify: `src/mcp/rpc.py` (`_call_tool`, строка 238)
- Modify: `src/mcp/checklists_tools.py` (`checklists`, `checklist_meta`)
- Modify: `tests/test_mcp_checklist_access.py`, `tests/test_mcp_checklists_tools.py` (тенант УК `"укашка"` → `"HQ"`)
- Test: `tests/test_mcp_spaces_rpc.py` (новый)

**Interfaces:**
- Consumes: `space_of`, `read_spaces`, `for_code`, `DEFAULT_SPACE` (Task 1).
- Produces: `rpc.NAME_THE_CHECKLIST: str`; `_checklist_for(settings, tenant)` → `Store(space=space_of(tenant))`; `_checklist_source_for` → `Store(space=DEFAULT_SPACE)`; инструмент `checklists` отдаёт `read_spaces(tenant)`.

- [ ] **Step 1: Написать падающие тесты**

```python
"""Волна 1 (#340): MCP правит методику только в пространстве токена."""

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
СЕГОДНЯ = date(2026, 9, 30)


@pytest.fixture
def настройки(tmp_path: Path) -> Settings:
    методика = build_methodology(tmp_path / "методика")
    store = Store(root=tmp_path / "хранилище", live=методика)
    current_version(store)
    create(replace(store, space="ge", code="own"), tenant=ПАРТНЁР, name_ru="Свой", name_en="Own", today=СЕГОДНЯ)
    create(replace(store, space="am", code="rnd"), tenant="AM", name_ru="РНД", name_en="RnD", today=СЕГОДНЯ)
    return Settings(
        tokens={"p" * MIN_TOKEN_LENGTH: ПАРТНЁР},
        tenants=(ПАРТНЁР,),
        host="127.0.0.1",
        port=0,
        checklist_store=store.root,
        # Правка партнёру открыта нарочно: проверяется, КУДА она попадает.
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
    """Review Focus 4."""
    assert настройки.checklist_store is not None and настройки.data_dir is not None
    эталон = Store(root=настройки.checklist_store, live=настройки.data_dir, space="hq", code="bizdev")
    было = len(read_journal(эталон))
    ответ = _вызов("set_checklist_state", {"state": "retired"}, настройки)
    assert ответ["result"].get("isError") is True
    assert NAME_THE_CHECKLIST in _текст(ответ)
    assert len(read_journal(эталон)) == было


def test_код_эталона_в_правящем_инструменте_это_не_найден(настройки: Settings) -> None:
    ответ = _вызов("set_checklist_state", {"checklist": "bizdev", "state": "retired"}, настройки)
    assert ответ["result"].get("isError") is True
    assert "нет" in _текст(ответ)


def test_перечень_партнёра_без_чужих_пространств(настройки: Settings) -> None:
    текст = _текст(_вызов("checklists", {}, настройки))
    assert "rnd" not in текст
    assert "own" in текст and "bizdev" in текст
```

- [ ] **Step 2: Прогнать и убедиться, что падают**

Run: `.venv/bin/pytest tests/test_mcp_spaces_rpc.py -q --no-cov`
Expected: FAIL — `ImportError: cannot import name 'NAME_THE_CHECKLIST'`.

- [ ] **Step 3: Реализация**

`src/mcp/server.py`: `from .checklist_layout import DEFAULT_SPACE, space_of`; `_checklist_for` возвращает `Store(root=хранилище, live=методика, space=space_of(tenant))`, `_checklist_source_for` — `Store(root=хранилище, live=методика, space=DEFAULT_SPACE)`.

`src/mcp/rpc.py`:

```python
NAME_THE_CHECKLIST = (
    "Назовите чек-лист аргументом checklist: правка без кода в пространстве "
    "партнёра не наводится ни на какой чек-лист, перечень отдаёт checklists"
)


def _aimed(kind: str, база: Store, *, tenant: str, код: str | None) -> Store:
    """Исходник — эталон УК; правка — только своё пространство."""
    if kind == KIND_CHECKLIST_SOURCE:
        return for_checklist(replace(база, space=DEFAULT_SPACE), код)
    свой = replace(база, space=space_of(tenant))
    if код is None and свой.space != DEFAULT_SPACE:
        raise ToolError(NAME_THE_CHECKLIST)
    return for_checklist(свой, код)
```

В `_call_tool` вместо `for_checklist(база, код)`: `_aimed(spec.kind, база, tenant=tenant, код=код)`. Наведение уже стоит внутри перехвата `ToolError`. Правящий инструмент с кодом эталона наведён на `ge/bizdev`, которого нет, и дверь отвечает своим «Чек-листа „bizdev“ в пространстве „ge“ нет» — тем же, что на любой несуществующий код.

`src/mcp/checklists_tools.py`: в `checklists` и `checklist_meta` — `api.overview(store, spaces=read_spaces(tenant, store.root))`.

Тесты, где тенант УК назван произвольно и методика правится через `_checklist_for`/`handle`, получают `УК = "HQ"` (`grep -ln '"укашка"' tests/test_mcp_*.py`). Прямые вызовы двери (`create(store, tenant=...)`) не меняются: дверь тенант не читает.

- [ ] **Step 4: Прогнать тесты**

Run: `.venv/bin/pytest tests/test_mcp_spaces_rpc.py tests/test_mcp_checklist_access.py tests/test_mcp_checklists_tools.py tests/test_mcp_checklist_tools.py tests/test_mcp_catalogue.py -q --no-cov`
Expected: PASS.

- [ ] **Step 5: Негативный прогон**

Вернуть `Store(...)` без `space` в `_checklist_for` → падает `test_правка_партнёра_наведена_на_его_пространство`; убрать `raise ToolError(NAME_THE_CHECKLIST)` → падает `test_правящий_инструмент_без_кода_не_уходит_в_эталон`.

- [ ] **Step 6: Commit**

```bash
git add src/mcp/server.py src/mcp/rpc.py src/mcp/checklists_tools.py tests/test_mcp_spaces_rpc.py tests/test_mcp_checklist_access.py tests/test_mcp_checklists_tools.py
git commit -m "feat(mcp): методика правится в пространстве токена, эталон — только чтение (#340)"
```

---

### Task 3: Чек-листы бота по пространству аудитора (D285)

**Files:**
- Modify: `src/domain/bot_checklists.py` (`BotChecklist`, `available`, `source_for`, `pick`)
- Modify: `src/domain/state.py` (`start_inspection`, строка 591)
- Modify: `tests/test_domain_bot_checklists.py` (вызовы `available(...)` получают `tenant=HQ_TENANT`)
- Test: `tests/test_domain_bot_spaces.py` (новый)

**Interfaces:**
- Consumes: `bot_spaces`, `ACTIVE` (Task 1).
- Produces: `BotChecklist.space: str`; `available(settings: Settings, *, tenant: str) -> list[BotChecklist]`; `pick(settings: Settings, code: str | None, *, tenant: str) -> BotChecklist`; `source_for(settings, code, *, space: str = DEFAULT_SPACE) -> Path`. Тенант без умолчания: у границы с умолчанием его однажды забудут передать.

- [ ] **Step 1: Написать падающие тесты**

```python
"""Волна 1 (#340): бот предлагает чек-листы пространства аудитора и эталон УК (D285)."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from src.domain import get_state, start_inspection
from src.domain.bot_checklists import available
from src.domain.config import check_environment
from src.domain.errors import DomainError
from src.domain.tenants import HQ_TENANT
from src.mcp.checklist import Store, apply_change, current_version, publish
from src.mcp.checklists import create, set_bot_access, set_state

CHAT = 7401
СЕГОДНЯ = date(2026, 9, 30)


def _открыть(store: Store, *, tenant: str, в_бот: bool = True) -> None:
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
    set_bot_access(store, tenant=tenant, on=в_бот)


@pytest.fixture
def хранилище(data_copy: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Store:
    monkeypatch.setenv("AUDIT_DATA_DIR", str(data_copy))
    monkeypatch.setenv("STATE_DIR", str(tmp_path / "state"))
    monkeypatch.chdir(tmp_path)
    store = Store(root=tmp_path / "хранилище", live=data_copy)
    current_version(store)
    # Второй эталон, который УК своему боту НЕ открыла: партнёру он виден (D285).
    _открыть(replace(store, code="hq2"), tenant=HQ_TENANT, в_бот=False)
    _открыть(replace(store, space="ge", code="own"), tenant="GE")
    _открыть(replace(store, space="am", code="rnd"), tenant="AM")
    monkeypatch.setenv("MCP_CHECKLIST_STORE", str(store.root))
    return store


def test_партнёр_видит_все_годные_эталоны_и_свои(хранилище: Store) -> None:
    видно = {(c.space, c.code) for c in available(check_environment(), tenant="GE")}
    assert видно == {("hq", "bizdev"), ("hq", "hq2"), ("ge", "own")}


def test_уК_видит_свои_открытые_и_не_видит_партнёров(хранилище: Store) -> None:
    видно = {(c.space, c.code) for c in available(check_environment(), tenant=HQ_TENANT)}
    assert видно == {("hq", "bizdev")}


def test_чужой_код_не_стартует_проверку(хранилище: Store) -> None:
    with pytest.raises(DomainError, match="больше не открыт"):
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

`BotChecklist` получает `space: str = DEFAULT_SPACE` после `code`. `_legacy` без изменений: `bizdev` из `AUDIT_DATA_DIR` и есть эталон.

```python
def available(settings: Settings, *, tenant: str) -> list[BotChecklist]:
    """Чек-листы, по которым аудитор этого пространства начинает проверку.

    Своё пространство — открытые галочкой «в боте». Эталон у партнёра — все годные
    (D285, D227): в работе, с опубликованным изданием и пунктами (`bot_block`),
    независимо от того, открыла ли их УК своему боту.
    """
    from src.mcp.checklists import bot_block

    root = settings.checklist_store
    if root is None or not root.is_dir() or not known(root):
        return _legacy(settings)
    где = bot_spaces(canonical_tenant(tenant))
    своё = где[0]
    в_проде = applied(root)
    ответ = []
    for space, code in known(root):
        if space not in где:
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

`pick(settings, code, *, tenant)` зовёт `available(settings, tenant=tenant)`. `source_for(..., space=DEFAULT_SPACE)` строит `root / space / code / CURRENT_LINK`. Импорты: `ACTIVE`, `bot_spaces` из `src.mcp.checklist_layout`; `canonical_tenant` из `src.domain.tenants`. В шапке модуля снять фразу «Пространство пока одно — УК (`hq`)…».

`src/domain/state.py`: `выбран = pick(settings, checklist_code, tenant=tenant)`.

- [ ] **Step 4: Прогнать тесты**

Run: `.venv/bin/pytest tests/test_domain_bot_spaces.py tests/test_domain_bot_checklists.py tests/test_bot_start_checklist.py tests/test_domain_state.py -q --no-cov`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/domain/bot_checklists.py src/domain/state.py tests/test_domain_bot_spaces.py tests/test_domain_bot_checklists.py
git commit -m "feat(domain): чек-листы бота по пространству, все годные эталоны партнёру (D285, #340)"
```

---

### Task 4: Вход по учётке любого пространства через один адрес (D282)

**Files:**
- Create: `src/db/migrations/0028_login_across_spaces.sql`
- Modify: `src/db/web_access.py` (`_SELECT_USER_SQL`, `_SELECT_USER_BY_EMAIL_SQL`, `_RESOLVE_SESSION_SQL`, `authenticate`, `find_by_email`, `resolve_session`, тексты отказов `create_account` и `set_email`)
- Modify: `src/web/auth.py` (строки 155, 191–204, 305–312)
- Modify: `tests/web_harness.py` (`подменить_двери`), `tests/test_db_web_access.py`, `tests/test_web_google_login.py`
- Test: `tests/test_db_web_access.py`, `tests/test_web_auth.py` (дописать)

**Interfaces:**
- Produces: `authenticate(login: str, password: str) -> Account | None`; `find_by_email(email: str) -> Account | None`; `resolve_session(token: str) -> Account | None`. `Account.tenant` — пространство учётки. Счётчик попыток (`admit_attempt`, `note_success`) по-прежнему ведётся по тенанту стенда `conf.tenant`: до входа пространство неизвестно, а счётчик — защита от перебора, не граница.

- [ ] **Step 1: Написать падающие тесты (база)**

В `tests/test_db_web_access.py` удалить `test_один_логин_живёт_в_разных_тенантах`, `test_сессия_чужого_тенанта_не_открывает_этот_стенд`, `test_учётка_чужого_тенанта_не_опознаётся`: они держали модель «стенд = тенант», которую D282 снимает. Добавить:

```python
def test_логин_один_на_всю_систему(обе_роли: str) -> None:
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
    сессия = open_session(create_account("partner", tenant=ЧУЖОЙ, password=ПАРОЛЬ))
    disable_account("partner", tenant=ЧУЖОЙ)
    assert authenticate("partner", ПАРОЛЬ) is None
    assert resolve_session(сессия.token) is None


def test_почта_одна_на_всю_систему(обе_роли: str) -> None:
    create_account("a", tenant=ТЕНАНТ, password=ПАРОЛЬ)
    create_account("b", tenant=ЧУЖОЙ, password=ПАРОЛЬ)
    set_email("a", tenant=ТЕНАНТ, email="p@example.org")
    with pytest.raises(EmailTakenError):
        set_email("b", tenant=ЧУЖОЙ, email="p@example.org")
    учётка = find_by_email("p@example.org")
    assert учётка is not None and учётка.tenant == ТЕНАНТ


def test_миграция_отказывает_на_двойниках(pg_dsn: str) -> None:
    """Двойник логина — отказ наката, а не выбор одного наугад."""
    import pathlib

    sql = pathlib.Path("src/db/migrations/0028_login_across_spaces.sql").read_text(encoding="utf-8")
    проверка = sql.split("create unique index", 1)[0]
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute("create temp table web_users (login text, email text, tenant_code text)")
        cur.execute("insert into web_users values ('director', null, 'A'), ('director', null, 'B')")
        with pytest.raises(psycopg.errors.RaiseException, match="нескольких пространствах"):
            cur.execute(проверка)
        conn.rollback()
```

Прочие вызовы `authenticate`/`resolve_session`/`find_by_email` в файле теряют `tenant=`.

- [ ] **Step 2: Написать падающий тест (веб)**

В `tests/test_web_auth.py`:

```python
def test_стенд_уК_впускает_учётку_партнёра_в_её_пространство(monkeypatch: pytest.MonkeyPatch) -> None:
    зовы = подменить_двери(monkeypatch, tenant="GE")
    with собрать(tenant="HQ").test_client() as client:
        войти(client)
        client.get("/inspections")
    assert зовы["authenticate"] == [(ЛОГИН, ПАРОЛЬ)]
    assert зовы["resolve"] and all(len(зов) == 1 for зов in зовы["resolve"])
```

- [ ] **Step 3: Прогнать и убедиться, что падают**

Run: `make test-honest ARGS="tests/test_db_web_access.py tests/test_web_auth.py -q"`
Expected: FAIL — `TypeError: authenticate() missing 1 required keyword-only argument: 'tenant'`, файла миграции нет.

- [ ] **Step 4: Миграция `src/db/migrations/0028_login_across_spaces.sql`**

```sql
-- 0028_login_across_spaces.sql
--
-- Волна 1 пространств (#340, D282): у каждого человека свой логин, уникальный
-- во всей системе, и один адрес админки на все пространства.
--
-- ЧТО БЫЛО. Логин и почта Google были уникальны ВНУТРИ арендатора (0014, 0021),
-- стенд отвечал за один арендатор (`WEB_TENANT`), и опознание искало строку по
-- паре «арендатор стенда + логин». Партнёр на стенде УК войти не мог.
--
-- ЧТО СТАЛО. Опознание ищет по логину (или почте) во всей базе, пространство
-- человека — `tenant_code` его строки.
--
-- ДВОЙНИКИ НЕ РАЗРЕШАЮТСЯ МОЛЧА: накат отказывает и говорит, сколько их и как
-- найти. Логины в отказ не печатаются — он уходит в журнал наката.
--
-- Раннер оборачивает файл в одну транзакцию сам.

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
            || '. Снимите лишние привязки, затем повторите накат';
    end if;
end $$;

create unique index web_users_login_uq on web_users (login);
drop index web_users_tenant_login_idx;

create unique index web_users_email_global_uq on web_users (email) where email is not null;
drop index web_users_email_uq;

comment on column web_users.login is
    'Логин, единый на всю систему (D282): опознание ищет по нему во всей базе, '
    'пространство человека — tenant_code его строки.';
```

Знаков `%` в теле нет намеренно: `raise ... using message =` их не разбирает.

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

`authenticate(login, password)` → `(login.strip().lower(),)`; `find_by_email(email)` → `(приведённая,)`; `resolve_session(token)` → `(session_fingerprint(token),)`. Докстринги: «Пространство приходит из строки учётки». Отказ `create_account` на повтор: `f"Логин «{имя}» уже занят — логины единые на всю систему. Возьмите другой"`. `set_email`: `f"почта {значение} уже привязана к другой учётке"`.

- [ ] **Step 6: `src/web/auth.py` и оснастка**

В `install`, после `max_age = ...`:

```python
    # Счётчик попыток ведётся по тенанту СТЕНДА: до входа пространство
    # человека неизвестно, а счётчик — защита от перебора, не граница.
    рубеж = conf.tenant
```

`admit_attempt(tenant=рубеж, ...)`, `note_success(tenant=рубеж, ...)` в обоих местах; `resolve_session(token)`, `authenticate(имя, request.form.get("password") or "")`, `find_by_email(кто.email)`.

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

Докстринг: «`tenant` — пространство УЧЁТКИ; тенант стенда задаёт `собрать(tenant=...)`». Сверки `зовы["authenticate"]` с тройкой в других наборах — без тенанта (`grep -rn 'зовы\["authenticate"\]\|зовы\["resolve"\]' tests`). В `tests/test_web_google_login.py` подмена `find_by_email` без `tenant`.

- [ ] **Step 7: Прогнать тесты**

Run: `make migrate` (тестовая база MUSPELHEIM), затем `make test-honest ARGS="tests/test_db_web_access.py tests/test_db_migrate.py tests/test_db_migrations_frozen.py tests/test_web_auth.py tests/test_web_login_limit.py tests/test_web_google_login.py -q"`
Expected: PASS.

- [ ] **Step 8: Негативный прогон**

Убрать `and u.disabled_at is null` из `_RESOLVE_SESSION_SQL` → падает `test_отключённая_учётка_другого_пространства_не_входит`. В миграции `> 0` → `> 100` → падает `test_миграция_отказывает_на_двойниках`.

- [ ] **Step 9: Commit**

```bash
git add src/db/migrations/0028_login_across_spaces.sql src/db/web_access.py src/web/auth.py tests/web_harness.py tests/test_db_web_access.py tests/test_web_auth.py tests/test_web_google_login.py
git commit -m "feat(web): вход по учётке любого пространства, логин единый на систему (D282, #340)"
```

---

### Task 5: Страны пространства, один справочник и охват чтения (D283, D284)

**Files:**
- Create: `src/db/migrations/0029_space_countries.sql`, `src/db/migrations/0030_inspection_unit_of_space.sql`
- Create: `src/db/reach.py`
- Modify: `src/db/queries.py` (каждый запрос с `i.tenant_code = %(tenant)s` и `u.tenant_code = %(tenant)s`: строки 86, 111, 135, 183, 593, 625, 653, 762, 812, 819, 828, 911, 972, 998; соединение `join units u on u.tenant_code = i.tenant_code and u.id = i.unit_id` → `join units u on u.id = i.unit_id`)
- Modify: `src/db/reports.py:144`, `src/db/previews.py:65,74`, `src/db/move.py:46` (чтение переносов), `src/db/directory.py:60` (`list_units`)
- Modify: `src/db/push.py` (разрешение точки для проверки партнёра, строки 320–335)
- Test: `tests/test_db_reach.py` (новый)

**Interfaces:**
- Produces:
  - `Reach(tenant: str, tenants: tuple[str, ...] | None, countries: tuple[str, ...] | None)` — кто читает; чьи проверки (`None` — всех); пиццерии каких стран (`None` — всех). `Reach.params() -> dict[str, list[str] | None]`.
  - `reach_of(tenant: str) -> Reach` — УК: `Reach("HQ", None, None)`. Партнёр: `Reach(t, None, <его страны>)` (вопрос 1: если «нет», `tenants=(t,)`). Партнёр без стран — `countries=()`: не видит ничего. Закрыто по умолчанию.
  - `countries_of(tenant: str) -> tuple[str, ...]`.
  - Функции чтения `queries`, `reports.latest_report`, `previews.finding_previews`, `previews.preview_bytes`, `move.list_moves`, `directory.list_units` принимают `reach: Reach` вместо `tenant: str`. Запись (`retract`, `move.move_inspection`, `synonyms.remember_phrase`, `push`) принимает `tenant: str` — своё пространство.
  - `queries.previous_inspection(*, tenant, unit)` остаётся по тенанту: повтор ×2 (D255) считается по проверкам своего пространства.

- [ ] **Step 1: Написать падающие тесты**

```python
"""Волна 1 (#340): УК читает всё, партнёр — пиццерии своей страны; справочник один (D283, D284)."""

from __future__ import annotations

import pytest
from conftest import requires_db

psycopg = pytest.importorskip("psycopg")

from db_harness import push_inspection  # noqa: E402
from src.db import queries  # noqa: E402
from src.db.directory import list_units, upsert_unit  # noqa: E402
from src.db.errors import DbError  # noqa: E402
from src.db.reach import Reach, reach_of  # noqa: E402

pytestmark = requires_db


@pytest.fixture
def сеть(pg_dsn: str, db_env: str) -> dict[str, str]:
    """Справочник УК: Batumi-1 (GE), Yerevan-1 (AM). Пространство GE привязано к GE."""
    upsert_unit("Batumi-1", country="GE", city="Batumi", tenant="HQ")
    upsert_unit("Yerevan-1", country="AM", city="Yerevan", tenant="HQ")
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute("insert into tenants (code) values ('GE') on conflict do nothing")
        cur.execute("insert into space_countries (country, tenant_code) values ('GE', 'GE') on conflict do nothing")
    return {
        "уК_батуми": push_inspection(unit="Batumi-1", tenant="HQ"),
        "уК_ереван": push_inspection(unit="Yerevan-1", tenant="HQ"),
        "партнёр_батуми": push_inspection(unit="Batumi-1", tenant="GE"),
    }


def _ids(reach: Reach) -> set[str]:
    return {row.id for row in queries.list_inspections(reach=reach, limit=100)}


def test_уК_читает_все_проверки(сеть: dict[str, str]) -> None:
    assert set(сеть.values()) <= _ids(reach_of("HQ"))


def test_партнёр_видит_только_свою_страну(сеть: dict[str, str]) -> None:
    видно = _ids(reach_of("GE"))
    assert сеть["партнёр_батуми"] in видно
    assert сеть["уК_батуми"] in видно, "вопрос 1: по умолчанию да"
    assert сеть["уК_ереван"] not in видно


def test_чужая_карточка_партнёру_не_найдена(сеть: dict[str, str]) -> None:
    assert queries.get_inspection(сеть["уК_ереван"], reach=reach_of("GE")) is None


def test_пространство_без_стран_не_видит_ничего(сеть: dict[str, str], pg_dsn: str) -> None:
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute("insert into tenants (code) values ('XX') on conflict do nothing")
    assert _ids(reach_of("XX")) == set()


def test_справочник_партнёра_это_точки_его_страны(сеть: dict[str, str]) -> None:
    assert [u.name for u in list_units(reach=reach_of("GE"))] == ["Batumi-1"]


def test_проверка_партнёра_ссылается_на_точку_справочника_уК(сеть: dict[str, str], pg_dsn: str) -> None:
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute("select u.tenant_code from inspections i join units u on u.id = i.unit_id where i.id = %s",
                    (сеть["партнёр_батуми"],))
        assert cur.fetchone() == ("HQ",)


def test_база_не_пишет_проверку_партнёра_на_точку_чужой_страны(сеть: dict[str, str]) -> None:
    """Review Focus 7: сторож в схеме, а не только в боте."""
    with pytest.raises(DbError):
        push_inspection(unit="Yerevan-1", tenant="GE")


def test_слив_партнёра_не_заводит_новую_точку(сеть: dict[str, str]) -> None:
    """#471: у партнёра незнакомое имя — отказ, а не новая пиццерия (D234)."""
    with pytest.raises(DbError, match="справочник"):
        push_inspection(unit="Batumi-99", tenant="GE")
    assert "Batumi-99" not in {u.name for u in list_units(reach=reach_of("HQ"))}


def test_одна_страна_одно_пространство(сеть: dict[str, str], pg_dsn: str) -> None:
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute("insert into tenants (code) values ('G2') on conflict do nothing")
        with pytest.raises(psycopg.errors.UniqueViolation):
            cur.execute("insert into space_countries (country, tenant_code) values ('GE', 'G2')")
```

(`push_inspection(unit=, tenant=) -> str` — помощник `tests/db_harness.py`: собирает `Inspection` и `Score` так же, как `tests/test_db_push.py`, зовёт `src.db.push.push` и возвращает id. Если такого помощника нет, завести его в `db_harness.py` из кода `test_db_push.py`, а не копией в каждом наборе.)

- [ ] **Step 2: Прогнать и убедиться, что падают**

Run: `make test-honest ARGS="tests/test_db_reach.py -q"`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.db.reach'`.

- [ ] **Step 3: Миграция `0029_space_countries.sql`**

```sql
-- 0029_space_countries.sql
--
-- Волна 1 пространств (#340, D284): одна страна — один партнёр. Пространство
-- партнёра привязано к своим странам; справочник пиццерий один, и партнёр видит
-- пиццерии своих стран. Страна — ключ строки, поэтому второе пространство на ту
-- же страну не заведётся: это отказ схемы, а не договорённость.
--
-- У УК строк нет: её охват — вся сеть (D283).

create table space_countries (
    country text primary key check (country ~ '^[A-Z]{2}$'),
    tenant_code text not null references tenants (code) check (tenant_code <> 'HQ'),
    created_at timestamptz not null default now()
);

create index space_countries_tenant_idx on space_countries (tenant_code);

comment on table space_countries is
    'Страны пространства партнёра (D284). Страна — ключ: одна страна, одно пространство.';

grant select on space_countries to dodo_audit_app;
grant select on space_countries to dodo_audit_admin;
```

(Имена ролей сверить с `0014`/`0016`: `dodo_audit_app`, `dodo_audit_admin`.)

- [ ] **Step 4: Миграция `0030_inspection_unit_of_space.sql`**

Наименьшее изменение под D284: составная ссылка `(tenant_code, unit_id) → units (tenant_code, id)` запрещала проверке партнёра ссылаться на точку справочника УК. Ссылка становится простой, `unit_id → units (id)`, а правило «чья точка годится» переезжает в сторож-триггер. Синонимы точек (`unit_aliases`) не трогаются: их по-прежнему заводит УК в своём справочнике.

```sql
-- 0030_inspection_unit_of_space.sql
--
-- Волна 1 пространств (#340, D284): справочник пиццерий один. Проверка партнёра
-- ссылается на точку справочника УК своей страны; точку своего тенанта у
-- партнёра заводить незачем и нельзя (D234).
--
-- Составная ссылка «точка своего тенанта» (0002, 0025, 0027) заменяется простой
-- ссылкой на точку и сторожем: точка проверки — либо своего тенанта, либо
-- справочника УК, и у партнёра — только из его стран. Сторож в схеме, а не в
-- боте: бот пропускает имя как написано, когда справочник недоступен (#471).

alter table inspections drop constraint inspections_unit_same_tenant;
alter table inspections add constraint inspections_unit_id_fkey
    foreign key (unit_id) references units (id);

alter table inspection_moves drop constraint inspection_moves_tenant_code_new_unit_id_fkey;
alter table inspection_moves drop constraint inspection_moves_tenant_code_old_unit_id_fkey;
alter table inspection_moves add constraint inspection_moves_new_unit_id_fkey
    foreign key (new_unit_id) references units (id);
alter table inspection_moves add constraint inspection_moves_old_unit_id_fkey
    foreign key (old_unit_id) references units (id);

create function inspection_unit_of_space() returns trigger
language plpgsql as $$
declare
    чья text;
    страна text;
begin
    select tenant_code, country into чья, страна from units where id = new.unit_id;
    if чья = new.tenant_code then
        return new;
    end if;
    if чья = 'HQ' and exists (
        select 1 from space_countries s where s.tenant_code = new.tenant_code and s.country = страна
    ) then
        return new;
    end if;
    raise exception using message =
        'Пиццерия проверки не из справочника страны этого пространства';
end $$;

create trigger inspections_unit_of_space
    before insert or update of unit_id, tenant_code on inspections
    for each row execute function inspection_unit_of_space();
```

- [ ] **Step 5: `src/db/reach.py`**

```python
"""Охват чтения: что видит пространство (волна 1, #340; D283, D284).

УК делает эталоны и читает всю сеть. Партнёр читает пиццерии своих стран — кто бы
их ни проверял (вопрос владельцу 1, по умолчанию «да»). Запись охватом не
расширяется: пишет каждый только в своё пространство, и функции записи принимают
`tenant`, а не `Reach`.

Охват уходит в запрос параметрами-массивами, а текст запроса не меняется
(правило S608). `None` в массиве — «без ограничения», пустой массив — «ничего».
"""

from __future__ import annotations

from dataclasses import dataclass

from src.domain.tenants import HQ_TENANT, canonical_tenant

from .queries import _reading

#: Кусок условия, одинаковый во всех чтениях. Дописывается в текст запроса
#: ЛИТЕРАЛОМ в каждом запросе, а не склейкой: сверку «везде ли он есть» делает
#: `test_каждое_чтение_стоит_на_охвате`.
REACH_SQL = (
    "(%(tenants)s::text[] is null or i.tenant_code = any(%(tenants)s)) "
    "and (%(countries)s::text[] is null or u.country = any(%(countries)s))"
)

_COUNTRIES_SQL = "select country from space_countries where tenant_code = %s order by country"


@dataclass(frozen=True)
class Reach:
    tenant: str
    tenants: tuple[str, ...] | None
    countries: tuple[str, ...] | None

    def params(self) -> dict[str, list[str] | None]:
        return {
            "tenants": None if self.tenants is None else list(self.tenants),
            "countries": None if self.countries is None else list(self.countries),
        }


def countries_of(tenant: str) -> tuple[str, ...]:
    with _reading("прочитать страны пространства") as conn, conn.cursor() as cur:
        cur.execute(_COUNTRIES_SQL, (canonical_tenant(tenant),))
        return tuple(str(row[0]) for row in cur.fetchall())


def reach_of(tenant: str) -> Reach:
    """Охват пространства. Партнёр без стран не видит ничего — закрыто по умолчанию."""
    код = canonical_tenant(tenant)
    if код == HQ_TENANT:
        return Reach(tenant=код, tenants=None, countries=None)
    return Reach(tenant=код, tenants=None, countries=countries_of(код))
```

(Если `_reading` в `queries` приватный и импорт из соседнего модуля ловит линтер, `countries_of` живёт в `queries.py`, а `reach.py` её импортирует.)

- [ ] **Step 6: Чтения на охвате**

В каждом запросе чтения `where i.tenant_code = %(tenant)s` заменяется на `where {REACH_SQL}` литералом (текст условия вписывается в строку запроса целиком, без форматирования). Соединение с точкой — `join units u on u.id = i.unit_id`. Запросы по справочнику (`units_total`, `unit_ids`, `unit_geography`, `directory.list_units`) — `where (%(countries)s::text[] is null or u.country = any(%(countries)s)) and u.tenant_code = 'HQ'`: справочник один, и он у УК. Функции получают `reach: Reach` и передают `{**reach.params(), ...}`. `_require_tenant` заменяется на `_require_reach(reach: Reach) -> Reach`: без охвата — отказ (молчаливая пустота хуже ошибки, тот же довод, что сегодня).

Сверка, что ни одно чтение не забыто, — тест в том же наборе:

```python
def test_каждое_чтение_стоит_на_охвате() -> None:
    """Запрос по проверкам без условия охвата — дыра границы, видимая только чтением."""
    import re

    from src.db import previews, queries, reports
    from src.db.reach import REACH_SQL

    for модуль in (queries, reports, previews):
        for имя, текст in vars(модуль).items():
            if isinstance(текст, str) and имя.endswith("_SQL") and re.search(r"from inspections i\b", текст):
                assert REACH_SQL in " ".join(текст.split()), f"{модуль.__name__}.{имя} читает без охвата"
```

(Сверка идёт по тексту с нормализованными пробелами; `REACH_SQL` хранится в одну строку.)

- [ ] **Step 7: Слив проверки партнёра (`src/db/push.py`)**

Для тенанта не `HQ` точка ищется в справочнике УК среди точек стран пространства, и точка не заводится:

```python
    if tenant_code != HQ_TENANT:
        unit_id = resolve_unit_id(conn, inspection.unit, tenant=HQ_TENANT)
        if unit_id is None:
            raise PushError(
                f"Пиццерии «{inspection.unit}» нет в справочнике страны пространства "
                f"{tenant_code}. Новую пиццерию заводит только УК (D234)"
            )
    else:
        # прежний путь УК без изменений: найти или завести точку
```

Страну проверяет сторож схемы (Step 4). Отказ триггера приходит `psycopg.errors.RaiseException` и уходит наружу `PushError`, как прочие отказы слива. Задача #471 закрывается этим коммитом для партнёров; для УК поведение не меняется.

- [ ] **Step 8: Прогнать тесты**

Run: `make migrate`, затем `make test-honest ARGS="tests/test_db_reach.py tests/test_db_push.py tests/test_db_push_units.py tests/test_db_reads_tenant.py tests/test_db_tenant_isolation.py tests/test_db_queries_tenant.py tests/test_db_move.py tests/test_db_directory.py tests/test_db_previews_offline.py tests/test_db_reports.py -q"`
Expected: PASS. Наборы, где чтение звали с `tenant=`, переходят на `reach=reach_of(<тенант>)` или на `Reach(tenant=t, tenants=(t,), countries=None)`, когда тест проверяет именно «свой тенант» (`test_db_tenant_isolation.py`): смысл этих тестов — изоляция партнёров друг от друга — сохраняется.

- [ ] **Step 9: Негативный прогон**

В `reach_of` вернуть партнёру `countries=None` → падает `test_партнёр_видит_только_свою_страну`. Удалить условие охвата из `_LIST_ALL_SQL` → падает `test_каждое_чтение_стоит_на_охвате` с именем запроса. Отключить триггер (`drop trigger` в тестовой транзакции) → падает `test_база_не_пишет_проверку_партнёра_на_точку_чужой_страны`.

- [ ] **Step 10: Commit**

```bash
git add src/db tests/test_db_reach.py tests/db_harness.py tests/test_db_*.py
git commit -m "feat(db): страны пространства, один справочник, охват чтения (D283, D284, #340)"
```

---

### Task 6: Веб и MCP — охват вошедшего на чтение, своё пространство на запись

**Files:**
- Modify: `src/web/auth.py` (новые `current_tenant`, `current_reach`)
- Modify: `src/web/app.py` — каждое `tenant=conf.tenant` (в main сейчас: строки 127, 261, 295, 490–534, 667–1017, 1072–1371, 1411, 1478, 1543–1634); после PR #472 также `_register_country`: `country_data.countries(tenant=conf.tenant)` (два места), `country_data.load(tenant=conf.tenant, ...)`
- Modify: `src/web/country.py` (после #472: `load(tenant=)` и `countries(tenant=)` → `reach=`)
- Modify: `src/web/letter_draft.py` (строки 99, 191), `src/web/inspections.py`, `src/web/overview.py`, `src/web/unit_card.py` (обёртки чтения: `tenant=` → `reach=`)
- Modify: `src/web/templates/inspections/card.html` (действия записи только у своей проверки)
- Modify: `src/mcp/tools.py`, `src/mcp/letters.py`, `src/mcp/retraction.py` (чтение по `reach_of(tenant)`, снятие — по `tenant`)
- Test: `tests/test_web_tenant_source.py`, `tests/test_web_spaces_boundary.py` (новые)

**Interfaces:**
- Consumes: `Account.tenant` (Task 4); `Reach`, `reach_of` (Task 5).
- Produces: `auth.current_tenant() -> str`; `auth.current_reach() -> Reach` (считается один раз на запрос и кладётся в `g`); `app._own(detail) -> bool` — проверка принадлежит пространству вошедшего. Правило для следующих экранов: чтение — `reach=auth.current_reach()`, запись — `tenant=auth.current_tenant()`.

- [ ] **Step 1: Написать падающие тесты**

`tests/test_web_tenant_source.py`:

```python
"""Волна 1 (#340): ни один экран не читает данные по тенанту стенда.

Статическая сверка: маршрут с `tenant=conf.tenant` зеленеет на любом тесте, где
стенд и человек из одного пространства, — а это все тесты, написанные до волны.
"""

from __future__ import annotations

from pathlib import Path

#: Единственное законное место — счётчик попыток до входа (Task 4).
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
"""Review Focus 5: чужая проверка — 404 партнёру; УК читает, но не пишет чужое."""

from __future__ import annotations

from typing import Any

import pytest
from web_harness import СВОЙ, войти, подменить_двери, собрать

from src.web import inspections as data
from src.web.app import MoveError, RetractionError

ЧУЖАЯ = "11111111-1111-1111-1111-111111111111"
КАДР = "33333333-3333-3333-3333-333333333333"
ЗАПИСЬ = [f"/inspections/{ЧУЖАЯ}/retract", f"/inspections/{ЧУЖАЯ}/move", f"/inspections/{ЧУЖАЯ}/letter/save"]


@pytest.fixture
def двери(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Any]]:
    """Чтение отвечает «такой нет»; запись запоминает тенант и отказывает, как база на чужой id."""
    зовы: list[tuple[str, Any]] = []

    def нет(имя: str) -> Any:
        def дверь(*_a: Any, **k: Any) -> None:
            зовы.append((имя, k.get("reach")))
            return None
        return дверь

    def отказ(имя: str, ошибка: type[Exception]) -> Any:
        def дверь(*_a: Any, **k: Any) -> None:
            зовы.append((имя, k.get("tenant")))
            raise ошибка("проверка не найдена")
        return дверь

    for имя in ("load_card", "load_report", "preview_bytes"):
        monkeypatch.setattr(data, имя, нет(имя))
    monkeypatch.setattr(data, "retract_card", отказ("retract_card", RetractionError))
    monkeypatch.setattr(data, "move_card", отказ("move_card", MoveError))
    monkeypatch.setattr(data, "retraction_available", lambda: True)
    monkeypatch.setattr("src.web.reach_of", lambda t: __import__("src.db.reach", fromlist=["Reach"]).Reach(t, None, ("GE",)), raising=False)
    # Администратор: снятие и перенос у аудитора отказывают 403 ещё до двери.
    подменить_двери(monkeypatch, tenant="GE", role="admin")
    return зовы


@pytest.mark.parametrize(
    ("метод", "адрес"),
    [("get", f"/inspections/{ЧУЖАЯ}"), ("get", f"/inspections/{ЧУЖАЯ}/report"),
     ("get", f"/inspections/{ЧУЖАЯ}/photos/{КАДР}"), ("get", f"/inspections/{ЧУЖАЯ}/letter"),
     ("post", f"/inspections/{ЧУЖАЯ}/letter")] + [("post", a) for a in ЗАПИСЬ],
)
def test_партнёру_чужая_проверка_не_найдена(двери: list[tuple[str, Any]], метод: str, адрес: str) -> None:
    with собрать(tenant="HQ").test_client() as client:
        войти(client)
        ответ = getattr(client, метод)(адрес, headers={"Origin": СВОЙ}, data={"reason": "x"})
    assert ответ.status_code == 404
    for имя, чем in двери:
        тенант = getattr(чем, "tenant", чем)
        assert тенант == "GE", (имя, чем)


def test_ответ_на_чужую_такой_же_как_на_несуществующую(двери: list[tuple[str, Any]]) -> None:
    другая = "22222222-0000-0000-0000-000000000000"
    with собрать(tenant="HQ").test_client() as client:
        войти(client)
        чужая, нет = client.get(f"/inspections/{ЧУЖАЯ}"), client.get(f"/inspections/{другая}")
    assert (чужая.status_code, чужая.data.replace(ЧУЖАЯ.encode(), b"")) == (
        нет.status_code, нет.data.replace(другая.encode(), b""))
```

(Строка с `monkeypatch.setattr("src.web.reach_of", ...)` нужна, только если `current_reach` зовёт базу за странами. Проще подменить `auth.reach_of` одной лямбдой, возвращающей `Reach("GE", None, ("GE",))`; исполнитель берёт тот путь, которым `current_reach` на деле получает охват.)

Второй набор — УК читает проверку партнёра, но не пишет её:

```python
def test_уК_открывает_проверку_партнёра_но_запись_отказывает(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    карточка = SimpleNamespace(inspection=SimpleNamespace(tenant="GE", id=ЧУЖАЯ))
    monkeypatch.setattr(data, "load_card", lambda *_a, **_k: карточка)
    записи: list[Any] = []
    monkeypatch.setattr(data, "retract_card", lambda *a, **k: записи.append(k))
    подменить_двери(monkeypatch, tenant="HQ", role="admin")
    with собрать(tenant="HQ").test_client() as client:
        войти(client)
        ответ = client.post(f"/inspections/{ЧУЖАЯ}/retract", headers={"Origin": СВОЙ}, data={"reason": "x"})
    assert ответ.status_code == 403
    assert записи == [], "дверь записи вызвана по проверке чужого пространства"
```

(Если карточка рендерится с полями, которых у двойника нет, двойник собирается из настоящего `InspectionDetail` набора `tests/test_web_app.py`.)

- [ ] **Step 2: Прогнать и убедиться, что падают**

Run: `.venv/bin/pytest tests/test_web_tenant_source.py tests/test_web_spaces_boundary.py -q --no-cov`
Expected: FAIL — перечень нарушений из `app.py`, `letter_draft.py` (и `country.py`, если #472 влит); снятие УК по проверке GE доходит до двери.

- [ ] **Step 3: Реализация**

`src/web/auth.py`:

```python
def current_tenant() -> str:
    """Пространство вошедшего — для записи. Без вошедшего — ошибка кода, не «покажем УК»."""
    account = current_account()
    if account is None:
        raise RuntimeError("current_tenant() вызван без вошедшего: маршрут прошёл мимо заслона")
    return canonical_tenant(account.tenant)


def current_reach() -> Reach:
    """Охват вошедшего — для чтения (D283). Один раз на запрос: страны читаются из базы."""
    if not hasattr(g, "reach"):
        g.reach = reach_of(current_tenant())
    return g.reach
```

`src/web/app.py`, `letter_draft.py`, `country.py`: чтение (`load_card`, `load_report`, `preview_bytes`, `load_previews`, `load_moves`, `load_registry`, `load_geography`, `load_units`, `load_edition_since`, `load_item_usage`, `overview_data.load`, `unit_data.load`, `directory.list_units`, `country_data.load`, `country_data.countries`) — `reach=auth.current_reach()`. Запись (`retract_card`, `move_card`, `accounts.*`, методика) — `tenant=auth.current_tenant()`. `_author`: `return account.login if account else "web"`. В `_register_context`: `"tenant": canonical_tenant(account.tenant) if account else ""`.

Запись по чужой проверке, которую вошедший может читать (УК у партнёра, партнёр у проверки УК по своей пиццерии):

```python
def _own(detail: Any) -> bool:
    """Проверка своего пространства: писать можно только её (D283)."""
    return canonical_tenant(detail.inspection.tenant) == auth.current_tenant()
```

В `do_retract`, `do_move`, `letter` (POST), `letter/save`, `letter_draft` — первым делом после `_admin_only`/`refuse_foreign_origin`: `detail = data.load_card(id, reach=...)`; `None` → 404 (`inspections/not_found.html`); `not _own(detail)` → `render_template("users/forbidden.html"), 403`. Карточка (`card.html`) показывает кнопки «Снять», «Перенести», «Письмо» только при `own`, который передаёт `_render_card`.

MCP (`src/mcp/tools.py`, `letters.py`): чтение проверок — `reach=reach_of(tenant)` по тенанту токена; `retraction.py` — снятие по `tenant`.

- [ ] **Step 4: Прогнать тесты**

Run: `.venv/bin/pytest tests/test_web_tenant_source.py tests/test_web_spaces_boundary.py tests/test_web_app.py tests/test_web_letter.py tests/test_web_letter_draft.py tests/test_web_overview.py tests/test_web_unit_card.py tests/test_web_registry_filter.py tests/test_mcp_reads.py tests/test_mcp_tools.py tests/test_mcp_letters.py tests/test_mcp_retraction.py -q --no-cov`; наборы экрана «Страна» после #472 — тоже.
Expected: PASS. Подмены `data.load_*` с `**_` в старых наборах к имени аргумента не чувствительны; наборы, сверяющие `tenant=` у чтения, переходят на `reach=`.

- [ ] **Step 5: Негативный прогон**

Добавить `_ = conf.tenant` в любой обработчик → падает `test_данные_берутся_по_пространству_вошедшего` с файлом и строкой. Убрать `not _own(detail)` в `do_retract` → падает `test_уК_открывает_проверку_партнёра_но_запись_отказывает`.

- [ ] **Step 6: Commit**

```bash
git add src/web src/mcp tests/test_web_tenant_source.py tests/test_web_spaces_boundary.py tests/test_web_*.py tests/test_mcp_*.py
git commit -m "feat(web,mcp): чтение по охвату вошедшего, запись только в своё пространство (#340)"
```

---

### Task 7: «Методика» по пространству

**Files:**
- Modify: `src/web/methodology.py` (`store_for` строка 707, `checklists_overview` 719, `RailRow`)
- Modify: `src/web/app.py` (`_который` строка 1459 — добавить `?space=`; `_apply` 1482; `_render_methodology` 1523–1545; маршруты `publish` 1268, заведение 1308, `state` 1339, `bot` 1361, `apply` 1388–1420)
- Modify: `src/web/texts.py` (`methodology.not_found`, `methodology.etalon_readonly`, `methodology.foreign_readonly`)
- Test: `tests/test_web_methodology_spaces.py` (новый)

**Interfaces:**
- Consumes: `locate`, `may_write`, `read_spaces`, `DEFAULT_SPACE` (Task 1); `auth.current_tenant()` (Task 6).
- Produces: `method.store_for(store, code, *, tenant: str, space: str | None, write: bool, lang: str) -> Store` — отказы `MethodologyRefused`: `methodology.not_found` (чужой и несуществующий), `methodology.etalon_readonly` (эталон из пространства партнёра), `methodology.foreign_readonly` (УК на чек-листе партнёра); `method.checklists_overview(store, *, tenant) -> list[Overview]` (по `read_spaces`); `RailRow.space`, `RailRow.etalon`. Адрес чек-листа другого пространства: `/admin?space=ge&checklist=own` — для УК (D283).

- [ ] **Step 1: Написать падающие тесты**

```python
"""Review Focus 4: «Методика» — эталон партнёру на чтение, УК у партнёра на чтение, чужое не найдено."""

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
    return store


def _маршруты_записи(app) -> list[str]:
    return sorted({p.rule for p in app.url_map.iter_rules()
                   if "POST" in (p.methods or set()) and p.rule.startswith("/admin")})


def test_чужой_код_звучит_как_несуществующий(склад: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    подменить_двери(monkeypatch, tenant="GE")
    with собрать(tenant="HQ").test_client() as client:
        войти(client)
        чужой = client.get("/admin?space=am&checklist=rnd").get_data(as_text=True)
        нет = client.get("/admin?checklist=zzz").get_data(as_text=True)
    assert t("methodology.not_found", "ru", code="rnd") in чужой
    assert t("methodology.not_found", "ru", code="zzz") in нет
    assert "РНД" not in чужой


def test_уК_открывает_чек_лист_партнёра(склад: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    подменить_двери(monkeypatch, tenant="HQ")
    with собрать(tenant="HQ").test_client() as client:
        войти(client)
        ответ = client.get("/admin?space=am&checklist=rnd")
    assert ответ.status_code == 200 and "РНД" in ответ.get_data(as_text=True)


@pytest.mark.parametrize(("кто", "адрес", "чей"), [
    ("GE", "?checklist=bizdev", ("hq", "bizdev")),
    ("HQ", "?space=am&checklist=rnd", ("am", "rnd")),
])
def test_ни_одна_правка_чужого_не_проходит(
    склад: Store, monkeypatch: pytest.MonkeyPatch, кто: str, адрес: str, чей: tuple[str, str]
) -> None:
    """Каждый POST раздела — по карте маршрутов: новый маршрут записи попадает под проверку сам."""
    цель = replace(склад, space=чей[0], code=чей[1])
    журнал, издание = len(read_journal(цель)), tip_version(цель)
    подменить_двери(monkeypatch, tenant=кто, role="admin")
    app = собрать(tenant="HQ")
    маршруты = _маршруты_записи(app)
    assert маршруты, "маршрутов записи методики не нашлось — тест проверяет пустоту"
    with app.test_client() as client:
        войти(client)
        for маршрут in маршруты:
            client.post(маршрут.replace("<code>", чей[1]) + адрес, headers={"Origin": СВОЙ},
                        data={"note": "проба", "version": издание})
    assert len(read_journal(цель)) == журнал
    assert tip_version(цель) == издание
    assert not (склад.root / "ge").exists(), "у партнёра появилась копия без правки"


def test_отказ_правки_эталона_назван_словами(склад: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    подменить_двери(monkeypatch, tenant="GE")
    with собрать(tenant="HQ").test_client() as client:
        войти(client)
        ответ = client.post("/admin/items?checklist=bizdev", headers={"Origin": СВОЙ}, data={"id": "X01"})
    assert t("methodology.etalon_readonly", "ru") in ответ.get_data(as_text=True)
```

- [ ] **Step 2: Прогнать и убедиться, что падают**

Run: `.venv/bin/pytest tests/test_web_methodology_spaces.py -q --no-cov`
Expected: FAIL — `KeyError: 'methodology.not_found'`; после заведения текстов — журнал эталона вырос.

- [ ] **Step 3: Реализация `src/web/methodology.py`**

```python
from src.mcp.checklist_layout import (
    ACTIVE, DEFAULT_SPACE, DRAFT, RETIRED, locate, may_write, read_spaces,
)


def store_for(
    store: Store, code: str | None, *, tenant: str, space: str | None, write: bool, lang: str
) -> Store:
    """Хранилище чек-листа с экрана — видимого этому пространству, иначе отказ.

    Чужой и несуществующий — одним текстом. Правка чужого — отказ ДО двери: дверь
    на чтении заводит нетронутое хранилище, на правке пишет журнал.
    """
    try:
        найдено = locate(store, tenant=tenant, code=code, space=space)
    except McpError as отказ:
        raise _refusal(отказ) from None
    if найдено is None:
        raise MethodologyRefused(t("methodology.not_found", lang, code=code or ""))
    if write and not may_write(найдено, tenant=tenant):
        ключ = "methodology.etalon_readonly" if найдено.space == DEFAULT_SPACE else "methodology.foreign_readonly"
        raise MethodologyRefused(t(ключ, lang))
    return найдено


def checklists_overview(store: Store, *, tenant: str) -> list[lists_door.Overview]:
    """Чек-листы, видимые пространству: у УК — все, у партнёра — свои и эталон."""
    try:
        return lists_door.overview(store, spaces=read_spaces(tenant, store.root))
    except McpError as отказ:
        raise _refusal(отказ) from None
```

(`t` импортируется из `.texts`; тексты — обычный словарь, Flask модулю не нужен.) `RailRow`: `space: str`, `etalon: bool` (`c.space == DEFAULT_SPACE`).

- [ ] **Step 4: Реализация `src/web/app.py`**

- `_который_space(запрос) -> str | None` — `(запрос.args.get("space") or "").strip() or None`.
- `_apply`: `method.store_for(state.store, _который(request), tenant=auth.current_tenant(), space=_который_space(request), write=True, lang=_lang(conf))`.
- `_render_methodology`: `checklists_overview(state.store, tenant=...)`; `store_for(..., write=False)`.
- `publish`, `state`, `bot`, `apply` (POST) — `write=True`; `GET .../<code>/apply` — `write=False`.
- заведение нового чек-листа (`POST` раздела, строка 1308): у партнёра заведения нет (спека, «Заведение») — `if auth.current_tenant() != HQ_TENANT:` страница с отказом `methodology.etalon_readonly`.
- ссылки колонки на чек-листы другого пространства получают `space=` в адресе (`templates/methodology/index.html`, строка 166: `url_for('methodology', checklist=r.code, space=r.space if not r.etalon else None, ...)`).

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
    "methodology.foreign_readonly": {
        "ru": "Чек-лист другого пространства открыт только для чтения.",
        "en": "A checklist of another space is read-only.",
    },
```

- [ ] **Step 6: Прогнать тесты**

Run: `.venv/bin/pytest tests/test_web_methodology_spaces.py tests/test_web_methodology.py tests/test_web_methodology_screen.py tests/test_web_methodology_rail.py tests/test_web_checklists_screen.py tests/test_web_bot_access.py tests/test_web_texts.py tests/test_web_bounds.py -q --no-cov`
Expected: PASS. Наборы, где стенд и учётка — не-slug тенант (`укашка`) и методика правится, получают `HQ`.

- [ ] **Step 7: Негативный прогон**

Убрать `if write and not may_write(...)` → падают обе ветки `test_ни_одна_правка_чужого_не_проходит`. Вернуть в `checklists_overview` вызов без `spaces=` → падает `test_чужой_код_звучит_как_несуществующий`.

- [ ] **Step 8: Commit**

```bash
git add src/web tests/test_web_methodology_spaces.py tests/test_web_*.py
git commit -m "feat(web): методика по пространству — эталон и чужое только на чтение (#340)"
```

---

### Task 8: Разделы «только HQ» и вкладка «Пользователи» (D264, D286, D288)

**Files:**
- Modify: `src/web/sections.py` (`Section.hq_only`, `visible_sections`, `refused_for`; `users` — `admin_only=False`)
- Modify: `src/web/app.py` (заслон после `auth.install`; маршруты `/users`, `/users/add`, `/users/disable`)
- Modify: `src/web/accounts.py` (`everyone` по охвату: УК — все пространства; `add(login, *, tenant, role)` с выбранным пространством)
- Modify: `src/db/web_access.py` (`list_accounts(*, tenant: str | None)` — `None` все, со столбцом `tenant_code`)
- Modify: `src/web/templates/users/index.html`, `src/web/texts.py` (`section.users.title` → «Пользователи» / «Users»)
- Test: `tests/test_web_sections.py`, `tests/test_web_users.py` (дописать)

**Interfaces:**
- Consumes: `auth.current_tenant()` (Task 6).
- Produces: `Section.hq_only: bool = False`; `refused_for(path: str, tenant: str) -> bool`; `app._hq_admin_only() -> Response | None` — 403 всем, кроме роли `admin` пространства `HQ` (D288: админ партнёра на этой вкладке не управляет никем). Вкладка «Пользователи» открыта всем вошедшим: человек видит свою строку (и блок привязки бота из задачи 10), админ УК — всех людей всех пространств и форму заведения с выбором пространства.

- [ ] **Step 1: Написать падающие тесты**

В `tests/test_web_sections.py`:

```python
from src.web.sections import SECTIONS, refused_for, section, visible_sections


class _Кто:
    def __init__(self, tenant: str, role: str = "auditor") -> None:
        self.tenant, self.role = tenant, role


def test_раздел_уК_скрыт_у_партнёра() -> None:
    assert "tenants" not in {s.key for s in visible_sections(_Кто("GE"))}
    assert "tenants" in {s.key for s in visible_sections(_Кто("HQ"))}
    assert "tenants" in {s.key for s in visible_sections(_Кто("default"))}


def test_пользователи_видны_каждому() -> None:
    assert "users" in {s.key for s in visible_sections(_Кто("GE"))}


def test_адрес_раздела_уК_отказывает_партнёру_и_вложенный_тоже() -> None:
    путь = section("tenants").path
    assert refused_for(путь, "GE") and refused_for(путь + "/GE", "GE")
    assert not refused_for(путь, "HQ")
    assert not refused_for(section("registry").path, "GE")


def test_каждый_раздел_только_уК_закрыт_партнёру(monkeypatch: pytest.MonkeyPatch) -> None:
    подменить_двери(monkeypatch, tenant="GE", role="admin")
    закрытые = [s for s in SECTIONS if s.hq_only]
    assert закрытые, "ни один раздел не помечен — тест ничего не проверяет"
    with собрать(tenant="HQ").test_client() as client:
        войти(client)
        for s in закрытые:
            assert client.get(s.path).status_code == 404, s.key
```

В `tests/test_web_users.py`:

```python
def test_админ_партнёра_не_заводит_людей(monkeypatch: pytest.MonkeyPatch) -> None:
    """D288: права админа партнёра не построены — вкладка ему ничего не открывает."""
    заведено: list[Any] = []
    monkeypatch.setattr(accounts, "add", lambda *a, **k: заведено.append(k))
    подменить_двери(monkeypatch, tenant="GE", role="admin")
    with собрать(tenant="HQ").test_client() as client:
        войти(client)
        ответ = client.post("/users/add", headers={"Origin": СВОЙ}, data={"login": "x", "tenant": "GE"})
    assert ответ.status_code == 403 and заведено == []


def test_админ_уК_заводит_человека_в_выбранное_пространство(monkeypatch: pytest.MonkeyPatch) -> None:
    заведено: list[Any] = []
    monkeypatch.setattr(accounts, "add", lambda login, **k: заведено.append((login, k["tenant"])) or accounts.Added(login=login, password="p"))
    monkeypatch.setattr(accounts, "spaces", lambda: ("HQ", "GE"))
    подменить_двери(monkeypatch, tenant="HQ", role="admin")
    with собрать(tenant="HQ").test_client() as client:
        войти(client)
        client.post("/users/add", headers={"Origin": СВОЙ}, data={"login": "ge-director", "tenant": "GE"})
    assert заведено == [("ge-director", "GE")]


def test_незаведённое_пространство_в_форме_это_отказ(monkeypatch: pytest.MonkeyPatch) -> None:
    заведено: list[Any] = []
    monkeypatch.setattr(accounts, "add", lambda *a, **k: заведено.append(k))
    monkeypatch.setattr(accounts, "spaces", lambda: ("HQ", "GE"))
    подменить_двери(monkeypatch, tenant="HQ", role="admin")
    with собрать(tenant="HQ").test_client() as client:
        войти(client)
        ответ = client.post("/users/add", headers={"Origin": СВОЙ}, data={"login": "x", "tenant": "ZZ"})
    assert ответ.status_code == 400 and заведено == []


def test_не_админ_видит_только_себя(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(accounts, "everyone", lambda **k: pytest.fail("перечень людей отдан не-админу"))
    подменить_двери(monkeypatch, tenant="GE")
    with собрать(tenant="HQ").test_client() as client:
        войти(client)
        assert client.get("/users").status_code == 200
```

(Поля `accounts.Added` сверить с `src/web/accounts.py`.)

- [ ] **Step 2: Прогнать и убедиться, что падают**

Run: `.venv/bin/pytest tests/test_web_sections.py tests/test_web_users.py -q --no-cov`
Expected: FAIL — `ImportError: cannot import name 'refused_for'`.

- [ ] **Step 3: Реализация `src/web/sections.py`**

```python
from src.domain.tenants import HQ_TENANT, canonical_tenant

    #: Виден и открывается ТОЛЬКО пространству УК (D264). Заслон — на раздел
    #: целиком (`refused_for` в `before_request`), а не на каждую кнопку.
    hq_only: bool = False
```

В `SECTIONS`: `tenants` — `hq_only=True`; `users` — без `admin_only` (содержимое по роли решает экран).

```python
def refused_for(path: str, tenant: str) -> bool:
    """Закрыт ли адрес пространству: раздел только для УК, а тенант не УК."""
    ключ = current_section(path)
    return ключ is not None and section(ключ).hq_only and canonical_tenant(tenant) != HQ_TENANT


def visible_sections(account: object | None) -> tuple[Section, ...]:
    админ = getattr(account, "role", None) == "admin"
    уК = canonical_tenant(str(getattr(account, "tenant", "") or "")) == HQ_TENANT
    return tuple(item for item in SECTIONS
                 if (админ or not item.admin_only) and (уК or not item.hq_only))
```

- [ ] **Step 4: Реализация `src/web/app.py`, `accounts.py`, `web_access.py`**

Сразу после `auth.install(app, conf)`:

```python
    @app.before_request
    def _только_уК() -> None:
        """Раздел только для УК отвечает партнёру тем же 404, что несуществующий адрес."""
        if request.endpoint in auth.OPEN_ENDPOINTS or auth.current_account() is None:
            return
        if refused_for(request.path, auth.current_tenant()):
            abort(404)
```

```python
def _hq_admin_only() -> FlaskResponse | None:
    """Управлять людьми может только админ УК (D286, D288)."""
    вошедший = auth.current_account()
    if (вошедший is not None and вошедший.role == accounts.ROLE_ADMIN
            and canonical_tenant(вошедший.tenant) == HQ_TENANT):
        return None
    return render_template("users/forbidden.html"), 403  # type: ignore[return-value]
```

`/users` (GET): админ УК — `accounts.everyone(tenant=None)` (все пространства, со столбцом «Пространство») и форма с выбором из `accounts.spaces()`; остальные — страница без перечня (своя строка и блок бота из задачи 10). `/users/add`, `/users/disable` — `_hq_admin_only()`. Пространство из формы сверяется с `accounts.spaces()`, незнакомое — 400 без записи. `accounts.add(логин, tenant=пространство, role=роль)`; `accounts.disable(логин, tenant=из строки учётки)`.

`accounts.spaces() -> tuple[str, ...]` — коды заведённых пространств (`web_access.list_spaces`, задача 13; до неё — `select code from tenants order by code` под ролью администратора истории). `web_access.list_accounts(*, tenant: str | None)`: `None` — все строки, `AccountRow` получает `tenant: str`.

`texts.py`: `section.users.title` → `{"ru": "Пользователи", "en": "Users"}` (слово владельца, D286); подписи столбца «Пространство» / «Space» и поля формы.

- [ ] **Step 5: Прогнать тесты**

Run: `.venv/bin/pytest tests/test_web_sections.py tests/test_web_users.py tests/test_web_app.py tests/test_web_auth.py tests/test_web_texts.py -q --no-cov`
Expected: PASS.

- [ ] **Step 6: Негативный прогон**

Убрать регистрацию `_только_уК` → падает `test_каждый_раздел_только_уК_закрыт_партнёру`. В `_hq_admin_only` убрать сверку пространства → падает `test_админ_партнёра_не_заводит_людей`.

- [ ] **Step 7: Commit**

```bash
git add src/web src/db/web_access.py tests/test_web_sections.py tests/test_web_users.py
git commit -m "feat(web): разделы «только УК», вкладка «Пользователи» с выбором пространства (D264, D286, #340)"
```

---

### Task 9: Привязка бота к учётке — ядро (D286)

**Files:**
- Create: `src/db/migrations/0031_bot_bindings.sql`
- Create: `src/db/bot_links.py`
- Test: `tests/test_db_bot_links.py` (новый)

**Interfaces:**
- Produces:
  - `LINK_TTL = timedelta(minutes=10)`; `LINK_PREFIX = "link-"` (метка deep-link: `t.me/<бот>?start=link-<токен>`; Telegram пропускает в `start` до 64 знаков `A-Za-z0-9_-`).
  - `IssuedLink(token: str, expires_at: datetime)`; `Binding(telegram_id: int, user_id: str, login: str, tenant: str, bound_at: datetime)`.
  - `issue_link(user_id: str) -> IssuedLink` — новая ссылка гасит прежние неиспользованные ссылки этой учётки.
  - `redeem(token: str, *, telegram_id: int) -> Binding | None` — одним движением: погасить ссылку (одноразово, до срока), привязать. `None` — один ответ на «нет такой», «использована», «просрочена», «учётка отключена», «этот Telegram уже привязан к другой учётке».
  - `resolve(telegram_id: int) -> Binding | None` — живая привязка к живой учётке.
  - `binding_of(user_id: str) -> Binding | None`; `unbind(user_id: str) -> bool`.
  - Отказ базы — `AccessError`, а не `None` (как `web_access`): «не пускаем» и «не смогли посмотреть» — разные ответы.

- [ ] **Step 1: Написать падающие тесты**

```python
"""Ядро D286: ссылка привязки одноразовая, короткоживущая, привязывает к учётке и её пространству."""

from __future__ import annotations

import pytest
from conftest import requires_db

psycopg = pytest.importorskip("psycopg")

from src.db.bot_links import LINK_PREFIX, binding_of, issue_link, redeem, resolve, unbind  # noqa: E402
from src.db.web_access import create_account, disable_account  # noqa: E402

pytestmark = requires_db
ПАРОЛЬ = "верный-пароль-учётки"


@pytest.fixture
def учётки(pg_dsn: str, db_env: str, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    monkeypatch.setenv("DATABASE_ADMIN_URL", pg_dsn)
    return {
        "ge": create_account("ge-auditor", tenant="GE", password=ПАРОЛЬ).id,
        "hq": create_account("hq-auditor", tenant="HQ", password=ПАРОЛЬ).id,
    }


def test_ссылка_привязывает_к_пространству_учётки(учётки: dict[str, str]) -> None:
    привязка = redeem(issue_link(учётки["ge"]).token, telegram_id=501)
    assert привязка is not None and (привязка.tenant, привязка.login) == ("GE", "ge-auditor")
    assert resolve(501) is not None and resolve(501).tenant == "GE"  # type: ignore[union-attr]


def test_повтор_ссылки_не_срабатывает(учётки: dict[str, str]) -> None:
    """Review Focus 1: перехваченная ссылка после хозяина ничего не даёт."""
    ссылка = issue_link(учётки["ge"])
    assert redeem(ссылка.token, telegram_id=501) is not None
    assert redeem(ссылка.token, telegram_id=666) is None
    assert resolve(666) is None


def test_просроченная_ссылка_не_срабатывает(учётки: dict[str, str], pg_dsn: str) -> None:
    ссылка = issue_link(учётки["ge"])
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute("update bot_link_tokens set expires_at = now() - interval '1 second' where user_id = %s",
                    (учётки["ge"],))
    assert redeem(ссылка.token, telegram_id=501) is None


def test_чужая_или_выдуманная_ссылка_не_срабатывает(учётки: dict[str, str]) -> None:
    assert redeem("x" * 32, telegram_id=501) is None
    assert redeem("", telegram_id=501) is None


def test_новая_ссылка_гасит_прежнюю(учётки: dict[str, str]) -> None:
    прежняя = issue_link(учётки["ge"])
    issue_link(учётки["ge"])
    assert redeem(прежняя.token, telegram_id=501) is None


def test_ссылка_отключённой_учётки_не_срабатывает(учётки: dict[str, str]) -> None:
    ссылка = issue_link(учётки["ge"])
    disable_account("ge-auditor", tenant="GE")
    assert redeem(ссылка.token, telegram_id=501) is None


def test_второй_telegram_гасит_прежнюю_привязку(учётки: dict[str, str]) -> None:
    """Review Focus 2, вопрос 4 (по умолчанию — заменяет)."""
    redeem(issue_link(учётки["ge"]).token, telegram_id=501)
    redeem(issue_link(учётки["ge"]).token, telegram_id=502)
    assert resolve(501) is None
    assert resolve(502) is not None


def test_telegram_чужой_учётки_не_перепривязывается(учётки: dict[str, str]) -> None:
    redeem(issue_link(учётки["hq"]).token, telegram_id=501)
    assert redeem(issue_link(учётки["ge"]).token, telegram_id=501) is None
    assert resolve(501).tenant == "HQ"  # type: ignore[union-attr]


def test_отвязка_и_отключение_снимают_доступ(учётки: dict[str, str]) -> None:
    """Review Focus 3."""
    redeem(issue_link(учётки["ge"]).token, telegram_id=501)
    assert unbind(учётки["ge"]) is True
    assert resolve(501) is None and binding_of(учётки["ge"]) is None
    redeem(issue_link(учётки["hq"]).token, telegram_id=601)
    disable_account("hq-auditor", tenant="HQ")
    assert resolve(601) is None


def test_в_базе_нет_токена_только_отпечаток(учётки: dict[str, str], pg_dsn: str) -> None:
    ссылка = issue_link(учётки["ge"])
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute("select fingerprint from bot_link_tokens where user_id = %s", (учётки["ge"],))
        (отпечаток,) = cur.fetchone()  # type: ignore[misc]
    assert ссылка.token not in отпечаток and len(отпечаток) == 64


def test_метка_помещается_в_deep_link(учётки: dict[str, str]) -> None:
    import re

    метка = LINK_PREFIX + issue_link(учётки["ge"]).token
    assert re.fullmatch(r"[A-Za-z0-9_-]{1,64}", метка)
```

- [ ] **Step 2: Прогнать и убедиться, что падают**

Run: `make test-honest ARGS="tests/test_db_bot_links.py -q"`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.db.bot_links'`.

- [ ] **Step 3: Миграция `0031_bot_bindings.sql`**

```sql
-- 0031_bot_bindings.sql
--
-- D286: бот привязывается через веб. Человек входит в своё пространство, жмёт
-- «привязать бота», получает одноразовую ссылку t.me/<бот>?start=link-<токен>, и
-- бот связывает его Telegram ID с учёткой — а значит, с её пространством.
--
-- Приёмы те же, что у сессий (0014) и токенов MCP (0011): в базе отпечаток
-- SHA-256, а не токен; погашение и отвязка односторонние и держатся сужающими
-- политиками, а не кодом.

create table bot_link_tokens (
    fingerprint text primary key check (fingerprint ~ '^[0-9a-f]{64}$'),
    user_id uuid not null references web_users (id),
    issued_at timestamptz not null default now(),
    expires_at timestamptz not null,
    used_at timestamptz,
    used_by bigint
);

create index bot_link_tokens_user_idx on bot_link_tokens (user_id) where used_at is null;

create table bot_bindings (
    id uuid primary key default gen_random_uuid(),
    telegram_id bigint not null,
    user_id uuid not null references web_users (id),
    bound_at timestamptz not null default now(),
    unbound_at timestamptz
);

-- Одна живая привязка на Telegram ID и одна на учётку (вопрос 4).
create unique index bot_bindings_live_telegram_uq on bot_bindings (telegram_id) where unbound_at is null;
create unique index bot_bindings_live_user_uq on bot_bindings (user_id) where unbound_at is null;

grant select, insert on bot_link_tokens to dodo_audit_app;
grant update (used_at, used_by) on bot_link_tokens to dodo_audit_app;
grant select, insert on bot_bindings to dodo_audit_app;
grant update (unbound_at) on bot_bindings to dodo_audit_app;

alter table bot_link_tokens enable row level security;
alter table bot_link_tokens force row level security;
create policy bot_link_tokens_access on bot_link_tokens for all using (true) with check (true);
-- Погашение одностороннее: погашенную ссылку не воскресить.
create policy bot_link_tokens_used_once on bot_link_tokens as restrictive for update
    using (used_at is null) with check (used_at is not null);

alter table bot_bindings enable row level security;
alter table bot_bindings force row level security;
create policy bot_bindings_access on bot_bindings for all using (true) with check (true);
create policy bot_bindings_unbound_once on bot_bindings as restrictive for update
    using (unbound_at is null) with check (unbound_at is not null);

comment on table bot_link_tokens is
    'Одноразовые ссылки привязки бота (D286). Хранится отпечаток; ссылка живёт LINK_TTL.';
comment on table bot_bindings is
    'Привязки Telegram ID к учётке (D286). Отвязка — пометкой; живая — одна на ID и одна на учётку.';
```

(Имя роли приложения сверить с `0014`.)

- [ ] **Step 4: `src/db/bot_links.py`**

```python
"""Привязка бота к учётке через веб (D286): выпуск ссылки, погашение, привязка, отвязка.

Ядро держится тремя свойствами, и каждое проверяет свой тест:
* ссылка одноразовая — погашение и привязка идут одной транзакцией, а повтор
  упирается в `used_at is null`;
* ссылка короткоживущая — срок в строке (`LINK_TTL`), сверка на стороне базы;
* привязка ведёт в пространство УЧЁТКИ — тенант берётся из `web_users`, а не из
  бота, ссылки или чего-то, что пришло снаружи.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from .errors import AccessError
from .web_access import _connected  # общее подключение роли приложения

LINK_TTL = timedelta(minutes=10)
LINK_PREFIX = "link-"
_TOKEN_BYTES = 24  # 32 знака urlsafe: с меткой — 37 из 64 допустимых

_EXPIRE_PREVIOUS_SQL = """
    update bot_link_tokens set used_at = now()
     where user_id = %s and used_at is null
"""
_ISSUE_SQL = """
    insert into bot_link_tokens (fingerprint, user_id, expires_at)
    values (%s, %s, now() + %s) returning expires_at
"""
_SPEND_SQL = """
    update bot_link_tokens t set used_at = now(), used_by = %(tg)s
      from web_users u
     where t.fingerprint = %(fp)s and t.used_at is null and t.expires_at > now()
       and u.id = t.user_id and u.disabled_at is null
 returning t.user_id
"""
_TAKEN_BY_OTHER_SQL = """
    select 1 from bot_bindings where telegram_id = %s and unbound_at is null and user_id <> %s
"""
_UNBIND_USER_SQL = "update bot_bindings set unbound_at = now() where user_id = %s and unbound_at is null"
_UNBIND_TG_SQL = "update bot_bindings set unbound_at = now() where telegram_id = %s and unbound_at is null"
_BIND_SQL = "insert into bot_bindings (telegram_id, user_id) values (%s, %s)"
_RESOLVE_SQL = """
    select b.telegram_id, u.id, u.login, u.tenant_code, b.bound_at
      from bot_bindings b join web_users u on u.id = b.user_id
     where b.unbound_at is null and u.disabled_at is null and {where}
"""


@dataclass(frozen=True)
class IssuedLink:
    token: str
    expires_at: datetime


@dataclass(frozen=True)
class Binding:
    telegram_id: int
    user_id: str
    login: str
    tenant: str
    bound_at: datetime


def _fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_link(user_id: str) -> IssuedLink:
    """Новая ссылка. Прежние неиспользованные гаснут: живой остаётся одна."""
    token = secrets.token_urlsafe(_TOKEN_BYTES)
    with _connected("выпустить ссылку привязки бота") as conn, conn.cursor() as cur:
        cur.execute(_EXPIRE_PREVIOUS_SQL, (user_id,))
        cur.execute(_ISSUE_SQL, (_fingerprint(token), user_id, LINK_TTL))
        row = cur.fetchone()
    assert row is not None  # noqa: S101 — insert ... returning без строки не бывает
    return IssuedLink(token=token, expires_at=row[0])


def redeem(token: str, *, telegram_id: int) -> Binding | None:
    """Погасить ссылку и привязать Telegram ID. `None` — один ответ на все отказы."""
    if not token:
        return None
    with _connected("привязать бота") as conn, conn.cursor() as cur:
        cur.execute(_SPEND_SQL, {"tg": telegram_id, "fp": _fingerprint(token)})
        row = cur.fetchone()
        if row is None:
            return None
        user_id = str(row[0])
        cur.execute(_TAKEN_BY_OTHER_SQL, (telegram_id, user_id))
        if cur.fetchone() is not None:
            # Ссылка при этом погашена: перепривязка чужого Telegram не срабатывает
            # и со второй попытки той же ссылкой.
            return None
        cur.execute(_UNBIND_USER_SQL, (user_id,))
        cur.execute(_UNBIND_TG_SQL, (telegram_id,))
        cur.execute(_BIND_SQL, (telegram_id, user_id))
    return resolve(telegram_id)


def resolve(telegram_id: int) -> Binding | None:
    return _one(_RESOLVE_SQL.format(where="b.telegram_id = %s"), telegram_id, "опознать Telegram ID")


def binding_of(user_id: str) -> Binding | None:
    return _one(_RESOLVE_SQL.format(where="u.id = %s"), user_id, "прочитать привязку бота")


def unbind(user_id: str) -> bool:
    with _connected("отвязать бота") as conn, conn.cursor() as cur:
        cur.execute(_UNBIND_USER_SQL, (user_id,))
        return cur.rowcount > 0


def _one(sql: str, value: object, зачем: str) -> Binding | None:
    with _connected(зачем) as conn, conn.cursor() as cur:
        cur.execute(sql, (value,))
        row = cur.fetchone()
    if row is None:
        return None
    return Binding(telegram_id=int(row[0]), user_id=str(row[1]), login=str(row[2]),
                   tenant=str(row[3]), bound_at=row[4])
```

`.format(where=...)` подставляет одну из двух КОНСТАНТ модуля, а не ввод. Если линтер (S608) всё равно ругается, `_RESOLVE_SQL` расписывается двумя полными константами `_RESOLVE_BY_TG_SQL` и `_RESOLVE_BY_USER_SQL`; это предпочтительнее `noqa`. `_connected` из `web_access` приватный: если импорт ловит линтер, общее подключение выносится в `src/db/connect.py` и берётся обоими модулями.

- [ ] **Step 5: Прогнать тесты**

Run: `make migrate`, затем `make test-honest ARGS="tests/test_db_bot_links.py tests/test_db_migrations_frozen.py tests/test_db_policies.py -q"`
Expected: PASS.

- [ ] **Step 6: Негативный прогон**

В `_SPEND_SQL` убрать `and t.used_at is null` → падает `test_повтор_ссылки_не_срабатывает`; убрать `and t.expires_at > now()` → падает `test_просроченная_ссылка_не_срабатывает`; убрать проверку `_TAKEN_BY_OTHER_SQL` → падает `test_telegram_чужой_учётки_не_перепривязывается`.

- [ ] **Step 7: Commit**

```bash
git add src/db/migrations/0031_bot_bindings.sql src/db/bot_links.py tests/test_db_bot_links.py
git commit -m "feat(db): одноразовая ссылка привязки бота к учётке и её пространству (D286, #340)"
```

---

### Task 10: «Привязать бота» на вкладке «Пользователи»

**Files:**
- Modify: `src/web/config.py` (`WEB_BOT_USERNAME_VAR = "WEB_BOT_USERNAME"`, поле `bot_username: str | None`)
- Modify: `src/web/app.py` (маршруты `POST /users/bot-link`, `POST /users/bot-unlink`; блок бота в `/users`)
- Modify: `src/web/templates/users/index.html`, `src/web/texts.py`
- Test: `tests/test_web_bot_link.py` (новый)

**Interfaces:**
- Consumes: `issue_link`, `binding_of`, `unbind`, `LINK_PREFIX`, `LINK_TTL` (Task 9); `_hq_admin_only` (Task 8).
- Produces: `link_url(bot_username: str, token: str) -> str` = `f"https://t.me/{bot_username}?start={LINK_PREFIX}{token}"`. Ссылка показывается ОДИН раз, на странице ответа POST, а не в адресе: адрес оседает в истории браузера и журнале прокси — тот же довод, что у пароля новой учётки. Отвязать свою привязку может каждый; чужую — только админ УК.

- [ ] **Step 1: Написать падающие тесты**

```python
"""D286: человек сам привязывает бота к своей учётке; ссылка — только своей учётке."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from web_harness import СВОЙ, Учётка, войти, подменить_двери, собрать

from src.db import bot_links


@pytest.fixture
def выпуски(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    кому: list[str] = []

    def выпуск(user_id: str) -> bot_links.IssuedLink:
        кому.append(user_id)
        return bot_links.IssuedLink(token="t0k3n", expires_at=datetime.now(UTC))

    monkeypatch.setattr(bot_links, "issue_link", выпуск)
    monkeypatch.setattr(bot_links, "binding_of", lambda _u: None)
    monkeypatch.setenv("WEB_BOT_USERNAME", "decimus_test_bot")
    return кому


def test_ссылка_выпускается_вошедшему_и_показывается_на_странице(
    выпуски: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    подменить_двери(monkeypatch, tenant="GE")
    with собрать(tenant="HQ").test_client() as client:
        войти(client)
        ответ = client.post("/users/bot-link", headers={"Origin": СВОЙ}, data={"user_id": "чужой-id"})
    assert выпуски == [Учётка().id], "ссылка выпущена не своей учётке"
    assert "https://t.me/decimus_test_bot?start=link-t0k3n" in ответ.get_data(as_text=True)
    assert "t0k3n" not in (ответ.headers.get("Location") or "")


def test_ссылка_не_выпускается_с_чужой_страницы(выпуски: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    подменить_двери(monkeypatch, tenant="GE")
    with собрать(tenant="HQ").test_client() as client:
        войти(client)
        client.post("/users/bot-link", headers={"Origin": "https://evil.example"})
    assert выпуски == []


def test_чужую_привязку_отвязывает_только_админ_уК(monkeypatch: pytest.MonkeyPatch) -> None:
    отвязано: list[Any] = []
    monkeypatch.setattr(bot_links, "unbind", lambda u: отвязано.append(u) or True)
    подменить_двери(monkeypatch, tenant="GE", role="admin")
    with собрать(tenant="HQ").test_client() as client:
        войти(client)
        ответ = client.post("/users/bot-unlink", headers={"Origin": СВОЙ}, data={"user_id": "другой"})
    assert ответ.status_code == 403 and отвязано == []
```

- [ ] **Step 2: Прогнать и убедиться, что падают**

Run: `.venv/bin/pytest tests/test_web_bot_link.py -q --no-cov`
Expected: FAIL — 404 на `/users/bot-link`.

- [ ] **Step 3: Реализация**

```python
    @app.post(f"{users_path}/bot-link")
    def bot_link() -> tuple[str, int]:
        """Выпустить ссылку привязки — ВСЕГДА своей учётке: id из формы не читается."""
        refuse_foreign_origin()
        вошедший = auth.current_account()
        assert вошедший is not None  # noqa: S101 — заслон не пускает неопознанного
        if not conf.bot_username:
            return _страница_учёток(outcome="bot_unset", code=503)
        try:
            ссылка = bot_links.issue_link(вошедший.id)
        except DbError:
            return _страница_учёток(outcome="bot_link_failed", code=503)
        return _страница_учёток(bot_link=link_url(conf.bot_username, ссылка.token),
                                bot_link_until=ссылка.expires_at)

    @app.post(f"{users_path}/bot-unlink")
    def bot_unlink() -> tuple[str, int] | FlaskResponse:
        refuse_foreign_origin()
        вошедший = auth.current_account()
        assert вошедший is not None  # noqa: S101
        чей = (request.form.get("user_id") or "").strip() or вошедший.id
        if чей != вошедший.id:
            отказ = _hq_admin_only()
            if отказ is not None:
                return отказ
        bot_links.unbind(чей)
        return _страница_учёток(outcome="bot_unlinked")
```

`_страница_учёток` получает `bot_link`, `bot_link_until` и показывает блок «Telegram»: привязан (ID, с какого времени, кнопка «Отвязать») или не привязан (кнопка «Привязать бота»). Выпущенная ссылка — строкой с подписью «действует 10 минут, откройте её в Telegram на своём телефоне». Админ УК в перечне людей видит у каждого отметку привязки и кнопку «Отвязать». Тексты — ru и en: `users.bot.title`, `users.bot.bound`, `users.bot.unbound`, `users.bot.link`, `users.bot.until`, `users.bot.unset`, `users.bot.unlink`, `users.bot.unlinked`. `config.py`: `WEB_BOT_USERNAME` необязательна; без неё кнопка не показывается, а на её месте — строка `users.bot.unset` с именем переменной.

- [ ] **Step 4: Прогнать тесты**

Run: `.venv/bin/pytest tests/test_web_bot_link.py tests/test_web_users.py tests/test_web_config.py tests/test_web_texts.py -q --no-cov`
Expected: PASS.

- [ ] **Step 5: Негативный прогон**

В `bot_link` взять id из `request.form["user_id"]` → падает `test_ссылка_выпускается_вошедшему_и_показывается_на_странице`.

- [ ] **Step 6: Commit**

```bash
git add src/web tests/test_web_bot_link.py
git commit -m "feat(web): «привязать бота» — одноразовая ссылка своей учётке (D286, #340)"
```

---

### Task 11: Доступ бота по привязке, совместимость и заслон чата

**Files:**
- Modify: `src/bot/access.py` (переписать `AccessMiddleware`; новые `SPACE_KEY`, `BindingCache`, `ChatSpaceMiddleware`, `chat_tenant`)
- Modify: `src/bot/app.py` (строки 35, 145–175: без `StaticInvites`, с `BindingCache`, регистрация заслона чата)
- Modify: `src/bot/config.py` (удалить `invites`, `INVITES_VAR`, разбор `BOT_INVITES`; `AUDITOR_NAMES` больше не требует ID из `ALLOWED_TELEGRAM_IDS`)
- Modify: `src/bot/roster.py` (только чтение: `activate` и `_save` удаляются; шапка — «совместимость до снятия», вопрос 2)
- Delete: `src/bot/invites.py`, `tests/test_bot_invites.py`
- Modify: `src/bot/texts.py` (`access.linked`, `access.link_invalid`, `access.foreign_space`)
- Test: `tests/test_bot_access.py` (переписать), `tests/test_bot_space_guard.py` (новый)

**Interfaces:**
- Consumes: `resolve`, `redeem`, `LINK_PREFIX`, `Binding` (Task 9).
- Produces:
  - `SPACE_KEY = "space"` — тенант человека в `data` апдейта; обработчик получает его параметром `space: str`.
  - `BindingCache(resolve: Callable[[int], Binding | None] = bot_links.resolve, ttl: timedelta = BINDING_TTL, now: Callable[[], datetime] = ...)`; `BINDING_TTL = timedelta(seconds=60)`; `.space_of(telegram_id) -> str | None`: при живой базе — ответ не старше `ttl`; при отказе базы (`AccessError`) — последний удачный ответ (вопрос 3), незнакомому — `None`.
  - `AccessMiddleware(allowed_ids: frozenset[int], bindings: BindingCache | None, roster: Roster | None, redeem: Callable[..., Binding | None] = bot_links.redeem)`. Порядок: `/start link-<токен>` → погашение (и для знакомого тоже: так аудитор УК из совместимости переходит на привязку); привязка → её пространство; `ALLOWED_TELEGRAM_IDS` или `roster.json` → `HQ` (совместимость, вопрос 2) — **только если привязки нет**; иначе — не пускать.
  - `ChatSpaceMiddleware(read_tenant: Callable[[int], str | None] = chat_tenant)`.

- [ ] **Step 1: Написать падающие тесты**

`tests/test_bot_access.py` (набор переписывается целиком: приглашений больше нет):

```python
"""Доступ бота по привязке к учётке (D286), совместимость для действующих, заслон чата."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from aiogram.types import Chat, Message, TelegramObject, User

from src.bot.access import SPACE_KEY, AccessMiddleware, BindingCache
from src.bot.roster import Roster
from src.db.bot_links import Binding
from src.db.errors import AccessError
from src.domain.tenants import HQ_TENANT

pytestmark = pytest.mark.asyncio


def _msg(user_id: int, text: str = "привет") -> Message:
    return Message(message_id=1, date=0, chat=Chat(id=user_id, type="private"),  # type: ignore[arg-type]
                   from_user=User(id=user_id, is_bot=False, first_name="Т"), text=text)


def _привязка(tg: int, tenant: str) -> Binding:
    return Binding(telegram_id=tg, user_id="u", login="l", tenant=tenant, bound_at=datetime.now(UTC))


async def _пустить(mw: AccessMiddleware, event: TelegramObject) -> str | None:
    увидено: dict[str, Any] = {}

    async def handler(_e: TelegramObject, data: dict[str, Any]) -> None:
        увидено.update(data)

    await mw(handler, event, {})
    return увидено.get(SPACE_KEY)


def _кэш(ответы: dict[int, Binding | None]) -> BindingCache:
    return BindingCache(resolve=lambda tg: ответы.get(tg))


async def test_привязанный_работает_в_пространстве_учётки() -> None:
    mw = AccessMiddleware(frozenset(), _кэш({501: _привязка(501, "GE")}), None)
    assert await _пустить(mw, _msg(501)) == "GE"


async def test_незнакомому_бот_молчит() -> None:
    mw = AccessMiddleware(frozenset(), _кэш({}), None)
    assert await _пустить(mw, _msg(999)) is None


async def test_ссылка_привязывает_незнакомого() -> None:
    погашено: list[tuple[str, int]] = []

    def погасить(token: str, *, telegram_id: int) -> Binding | None:
        погашено.append((token, telegram_id))
        return _привязка(telegram_id, "GE")

    mw = AccessMiddleware(frozenset(), _кэш({}), None, redeem=погасить)
    await _пустить(mw, _msg(501, "/start link-abc"))
    assert погашено == [("abc", 501)]


async def test_негодная_ссылка_не_пускает() -> None:
    mw = AccessMiddleware(frozenset(), _кэш({}), None, redeem=lambda *_a, **_k: None)
    assert await _пустить(mw, _msg(501, "/start link-abc")) is None


async def test_совместимость_пускает_действующих_аудиторов_уК(tmp_path: Path) -> None:
    mw = AccessMiddleware(frozenset({111}), _кэш({}), Roster.load(tmp_path))
    assert await _пустить(mw, _msg(111)) == HQ_TENANT


async def test_привязка_главнее_совместимости() -> None:
    """Review Focus 3: ID из окружения, привязанный к учётке партнёра, работает как партнёр."""
    mw = AccessMiddleware(frozenset({111}), _кэш({111: _привязка(111, "GE")}), None)
    assert await _пустить(mw, _msg(111)) == "GE"


async def test_отвязка_действует_после_истечения_кэша() -> None:
    сейчас = [datetime(2026, 9, 30, tzinfo=UTC)]
    ответы: dict[int, Binding | None] = {501: _привязка(501, "GE")}
    кэш = BindingCache(resolve=lambda tg: ответы.get(tg), ttl=timedelta(seconds=60), now=lambda: сейчас[0])
    assert кэш.space_of(501) == "GE"
    ответы[501] = None
    assert кэш.space_of(501) == "GE", "в пределах срока кэша — прежний ответ"
    сейчас[0] += timedelta(seconds=61)
    assert кэш.space_of(501) is None


async def test_при_отказе_базы_узнанный_работает_незнакомый_нет() -> None:
    """Вопрос 3, по умолчанию: аудитор на точке не остаётся без бота из-за базы."""
    сейчас = [datetime(2026, 9, 30, tzinfo=UTC)]
    живая = [True]

    def resolve(tg: int) -> Binding | None:
        if not живая[0]:
            raise AccessError("база недоступна")
        return _привязка(tg, "GE") if tg == 501 else None

    кэш = BindingCache(resolve=resolve, ttl=timedelta(seconds=60), now=lambda: сейчас[0])
    assert кэш.space_of(501) == "GE"
    живая[0] = False
    сейчас[0] += timedelta(hours=2)
    assert кэш.space_of(501) == "GE"
    assert кэш.space_of(777) is None
```

`tests/test_bot_space_guard.py`:

```python
"""Review Focus 6: апдейт по проверке чужого пространства до обработчика не доходит."""

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
SPACE_KEY = "space"
BINDING_TTL = timedelta(seconds=60)


class BindingCache:
    """Опознание по привязке с коротким кэшем и запасным ответом при отказе базы.

    Кэш — затем, чтобы не ходить в базу на каждый кадр альбома. Запасной ответ —
    затем, чтобы аудитор на точке не остался без бота из-за базы (вопрос 3): прежде
    доступ от базы не зависел вовсе (`roster.json`), и это свойство сохраняется для
    уже узнанных. Незнакомого при отказе базы не пускаем: узнать его нечем.
    """

    def __init__(self, resolve=bot_links.resolve, ttl: timedelta = BINDING_TTL,
                 now=lambda: datetime.now(UTC)) -> None:
        self._resolve, self._ttl, self._now = resolve, ttl, now
        self._known: dict[int, tuple[datetime, str | None]] = {}

    def space_of(self, telegram_id: int) -> str | None:
        сейчас = self._now()
        было = self._known.get(telegram_id)
        if было is not None and сейчас - было[0] < self._ttl:
            return было[1]
        try:
            привязка = self._resolve(telegram_id)
        except AccessError:
            logger.warning("привязки не прочитались, Telegram ID %s — по последнему ответу", telegram_id)
            return было[1] if было is not None else None
        ответ = canonical_tenant(привязка.tenant) if привязка is not None else None
        self._known[telegram_id] = (сейчас, ответ)
        return ответ

    def forget(self, telegram_id: int) -> None:
        self._known.pop(telegram_id, None)


class AccessMiddleware(BaseMiddleware):
    """Внешняя мидлварь: пространство человека в `data[SPACE_KEY]` — или чужого не пускать."""

    def __init__(self, allowed_ids, bindings, roster, redeem=bot_links.redeem) -> None:
        self._allowed_ids, self._bindings, self._roster, self._redeem = allowed_ids, bindings, roster, redeem

    async def __call__(self, handler, event, data):
        user = getattr(event, "from_user", None)
        user_id = user.id if user is not None else None
        if user_id is None:
            return None
        метка = _link_token(event)
        if метка is not None:
            привязка = await asyncio.to_thread(self._redeem, метка, telegram_id=user_id)
            if self._bindings is not None:
                self._bindings.forget(user_id)
            await _answer(event, "access.linked" if привязка else "access.link_invalid",
                          login=привязка.login if привязка else "")
            return None
        space = await asyncio.to_thread(self._space_of, user_id)
        if space is None:
            logger.warning("отклонено обновление от постороннего Telegram ID %s", user_id)
            return None
        data[SPACE_KEY] = space
        return await handler(event, data)

    def _space_of(self, user_id: int) -> str | None:
        if self._bindings is not None:
            привязан = self._bindings.space_of(user_id)
            if привязан is not None:
                return привязан
        # Совместимость (вопрос 2): кто пускался до D286 — сотрудник УК. Только
        # если привязки нет — её проверили выше.
        if is_allowed(user_id, self._allowed_ids):
            return HQ_TENANT
        if self._roster is not None and self._roster.knows(user_id):
            return HQ_TENANT
        return None


def _link_token(event: TelegramObject) -> str | None:
    """Токен из `/start link-<токен>` — или `None`. Прочие `/start` сюда не относятся."""
    text = getattr(event, "text", None) or ""
    команда, _, метка = text.partition(" ")
    if команда.split("@", 1)[0] != "/start" or not метка.startswith(LINK_PREFIX):
        return None
    return метка.removeprefix(LINK_PREFIX).strip() or None
```

Ответ на негодную ссылку (`access.link_invalid`) — одна строка незнакомому. Это единственное отступление от «посторонним не отвечаем» (`access.py`, шапка). Оправдание: у человека уже есть ссылка на бота, существование бота ему известно, а молчание на просроченную ссылку выглядит как поломка. Ответ один на все причины: он не подсказывает, чем отказ вызван.

`chat_tenant`, `ChatSpaceMiddleware`, `_chat_of` — как в прежней редакции плана: заслон читает тенант проверки чата (`domain.get_state`, нечитаемое состояние — `None`, пропустить дальше) и при несовпадении с `data[SPACE_KEY]` (через `canonical_tenant`) отвечает `access.foreign_space` (у нажатия — `show_alert=True`) и апдейт не передаёт.

`src/bot/app.py`: `access = AccessMiddleware(settings.allowed_ids, BindingCache(), roster)`; затем `ChatSpaceMiddleware()` на `message` и `callback_query` — ПОСЛЕ доступа (внешние мидлвари идут в порядке регистрации, заслону нужен `SPACE_KEY`). Строка `settings = replace(settings, auditor_names={**roster.names(), ...})` остаётся: имена из старой связки нужны шапке отчёта.

`src/bot/texts.py` (ru и en):

```python
    "access.linked": {
        "ru": "Бот привязан к учётке {login}. Можно начинать проверку: /start",
        "en": "The bot is linked to the account {login}. You can start an inspection: /start",
    },
    "access.link_invalid": {
        "ru": "Ссылка недействительна. Получите новую на странице «Пользователи» в админке.",
        "en": "This link is not valid. Get a new one on the Users page of the admin.",
    },
    "access.foreign_space": {
        "ru": "Эта проверка ведётся в другом пространстве. Свою проверку начните в личном чате с ботом.",
        "en": "This inspection belongs to another space. Start your own in a private chat with the bot.",
    },
```

`src/bot/config.py`: удалить `from .invites ...`, поле `invites`, разбор `BOT_INVITES`; в `_parse_auditor_names` снять требование «ID из `ALLOWED_TELEGRAM_IDS`» (привязанные люди в этот список не входят). `src/bot/roster.py`: удалить `activate` и `_save`; шапка — «связки, собранные по приглашениям до D286; читаются как совместимость — люди УК — до её снятия (вопрос 2)». Удалить `src/bot/invites.py` и `tests/test_bot_invites.py`; тесты `tests/test_bot_roster.py` про активацию — тоже.

- [ ] **Step 4: Прогнать тесты**

Run: `.venv/bin/pytest tests/test_bot_access.py tests/test_bot_space_guard.py tests/test_bot_roster.py tests/test_bot_app.py tests/test_bot_config.py tests/test_bot_texts.py tests/test_bot_stale_button.py -q --no-cov`
Expected: PASS.

- [ ] **Step 5: Негативный прогон**

В `_space_of` поставить совместимость ПЕРЕД привязкой → падает `test_привязка_главнее_совместимости`. В `BindingCache` вернуть при отказе базы `None` → падает `test_при_отказе_базы_узнанный_работает_незнакомый_нет` (так и должно быть, если владелец ответит на вопрос 3 «никого»: тогда тест переписывается вместе с кодом). В `ChatSpaceMiddleware` сравнение заменить на `True` → падают тесты заслона чата.

- [ ] **Step 6: Commit**

```bash
git add -A src/bot tests/test_bot_access.py tests/test_bot_space_guard.py tests/test_bot_roster.py tests/test_bot_invites.py
git commit -m "feat(bot): доступ по привязке к учётке, совместимость для УК, заслон чата (D286, #340)"
```

---

### Task 12: Обработчики бота на пространстве человека

**Files:**
- Modify: `src/bot/routers/start.py` (строки 64, 141–175, 334–410, 459–470, 505–548)
- Modify: `src/bot/unit_pick.py` (строки 103–110, 143–160)
- Modify: `src/bot/routers/mcp.py` (строка 254)
- Modify: `src/bot/phrases.py` (`recall`, `learn`)
- Modify: `src/bot/config.py` (удалить `MCP_TENANT_VAR`, `DEFAULT_MCP_TENANT`, `mcp_tenant`, `_parse_mcp_tenant`)
- Test: `tests/test_bot_start_space.py` (новый); правка `tests/test_bot_config.py`, `tests/test_bot_mcp_command.py`

**Interfaces:**
- Consumes: `space: str` в обработчике (Task 11); `available(settings, *, tenant)` (Task 3); `reach_of`, `list_units(reach=)` (Task 5).
- Produces: `unit_pick.match_unit(typed: str, *, tenant: str) -> UnitMatch` — справочник по охвату пространства (у партнёра — точки его стран); `unit_pick.may_add_units(tenant: str) -> bool` (`canonical_tenant(tenant) == HQ_TENANT`); `bot_tenant` и `UK_TENANT` удалены; `BOT_MCP_TENANT` не читается.

- [ ] **Step 1: Написать падающие тесты**

```python
"""Волна 1 (#340): бот ведёт проверку в пространстве того, кто её начал."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from bot_harness import AUDITOR_ID, CHAT_ID, callback_query, feed, make_bot, text_message
from test_bot_start_router import settings

from src.bot import unit_pick
from src.bot.access import BindingCache
from src.bot.app import build_dispatcher
from src.bot.keyboards import NEW_INSPECTION_CALLBACK
from src.db.bot_links import Binding
from src.domain import get_state, start_inspection
from src.domain.tenants import HQ_TENANT

pytestmark = pytest.mark.asyncio


def _партнёр() -> BindingCache:
    return BindingCache(resolve=lambda tg: Binding(tg, "u", "ge-auditor", "GE", datetime.now(UTC))
                        if tg == AUDITOR_ID else None)


def _диспетчер():
    return build_dispatcher(replace(settings(), allowed_ids=frozenset()), bindings=_партнёр())


async def test_справочник_сверяется_в_пространстве_аудитора(domain_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    спросили: list[str] = []

    def сверка(typed: str, *, tenant: str) -> unit_pick.UnitMatch:
        спросили.append(tenant)
        return unit_pick.UnitMatch(name="Batumi-1", suggestions=(), checked=True)

    from src.bot.routers import start as start_router

    monkeypatch.setattr(start_router, "match_unit", сверка)
    bot, _session = make_bot()
    dp = _диспетчер()
    await feed(dp, bot, text_message("/start"))
    await feed(dp, bot, callback_query(NEW_INSPECTION_CALLBACK))
    await feed(dp, bot, text_message("Батуми 1"))
    assert спросили == ["GE"]


async def test_партнёр_не_заводит_пиццерию() -> None:
    assert unit_pick.may_add_units("GE") is False
    assert unit_pick.may_add_units(HQ_TENANT) is True
    assert unit_pick.may_add_units("default") is True


async def test_чужая_проверка_в_чате_не_дописывается(domain_env: Path) -> None:
    """Review Focus 6 на живом диспетчере."""
    start_inspection(CHAT_ID, unit="Тестовая", kind="planned", report_lang="ru", tenant=HQ_TENANT)
    bot, session = make_bot()
    await feed(_диспетчер(), bot, text_message("холодильник грязный"))
    состояние = get_state(CHAT_ID)
    assert состояние is not None and состояние.tenant == HQ_TENANT and not состояние.findings
    assert "другом пространстве" in session.last_text  # type: ignore[attr-defined]
```

(`build_dispatcher` получает параметр `bindings: BindingCache | None = None` рядом с `roster`; без него — `BindingCache()` на настоящей базе.)

- [ ] **Step 2: Прогнать и убедиться, что падают**

Run: `.venv/bin/pytest tests/test_bot_start_space.py -q --no-cov`
Expected: FAIL — `спросили == ["HQ"]`.

- [ ] **Step 3: Реализация**

`src/bot/unit_pick.py`: удалить `UK_TENANT`, `bot_tenant`;

```python
def match_unit(typed: str, *, tenant: str) -> UnitMatch:
    """Сверить написанное со справочником страны(стран) пространства (D284)."""
    try:
        units = directory.list_units(reach=reach_of(tenant))
    except DbError as exc:
        logger.warning("справочник точек недоступен, название принято как написано: %s", exc)
        return UnitMatch(name=None, suggestions=(), checked=False)
    return match_in(typed, [(u.name, u.aliases, u.country is not None) for u in units])


def may_add_units(tenant: str) -> bool:
    """Заводить новые пиццерии может только управляющая компания (D233, D234)."""
    return canonical_tenant(tenant) == HQ_TENANT
```

(У партнёра имя, принятое «как написано» при недоступном справочнике, потом отклонит слив — Task 5, Step 7.)

`src/bot/routers/start.py`: импорт `from ..unit_pick import match_unit, may_add_units`; `_open_checklists(space)` → `available(check_environment(), tenant=space)`; `_ask_checklist(message, state, lang, space)`; параметр `space: str` у `on_new`, `on_resume_new`, `on_unit`, `on_unit_new`, `on_checklist`, `on_lang`; `match_unit(имя.name, tenant=space)`; `may_add_units(space)` в обоих местах; `upsert_unit(..., tenant=space)`; `domain.start_inspection(..., tenant=space)`.

`src/bot/routers/mcp.py`: выпуск токена — `issue_token(user.id, tenant=space)`.

`src/bot/phrases.py`: тенант записи — тенант проверки чата (`domain.get_state(chat_id).tenant`, без проверки — `HQ_TENANT`); `lookup_phrase(..., tenant=...)`, `remember_phrase(..., tenant=...)`.

`src/bot/config.py`: удалить `BOT_MCP_TENANT` целиком; тесты на него удалить (`grep -rn "mcp_tenant\|BOT_MCP_TENANT" tests`).

- [ ] **Step 4: Прогнать тесты**

Run: `.venv/bin/pytest tests/test_bot_start_space.py tests/test_bot_start_router.py tests/test_bot_start_checklist.py tests/test_bot_unit_pick.py tests/test_bot_mcp_command.py tests/test_bot_phrases.py tests/test_bot_learned_phrase.py tests/test_bot_config.py -q --no-cov`
Expected: PASS.

- [ ] **Step 5: Негативный прогон**

Снять регистрацию `ChatSpaceMiddleware` в `app.py` → падает `test_чужая_проверка_в_чате_не_дописывается`. Если не падает — тест проверяет не то, чинить тест.

- [ ] **Step 6: Commit**

```bash
git add src/bot tests/test_bot_start_space.py tests/test_bot_config.py tests/test_bot_mcp_command.py
git commit -m "feat(bot): проверка, справочник страны, фразы и токен MCP — в пространстве аудитора (#340)"
```

---

### Task 13: Заведение пространств и их стран командой; демо — пространство партнёра (D287)

**Files:**
- Modify: `src/db/web_access.py` (новые `SPACE_CODE`, `SpaceRow`, `check_space_code`, `space_exists`, `create_space`, `list_spaces`, `bind_countries`)
- Create: `tools/space.py`
- Modify: `tools/web_user.py` (`_tenant`: незаведённое пространство — отказ)
- Modify: `tools/seed_web_demo.py` (демо-пространство привязано к странам демо)
- Modify: `Makefile` (цель `space`, `.PHONY`)
- Test: `tests/test_db_spaces.py` (новый)

**Interfaces:**
- Produces: `create_space(code: str, *, name: str) -> SpaceRow`; `list_spaces() -> tuple[SpaceRow, ...]`; `space_exists(code: str) -> bool`; `bind_countries(space: str, countries: tuple[str, ...]) -> tuple[str, ...]` — страны после привязки; занятая другим пространством страна — отказ с названием пространства; `SpaceRow(code, name, countries: tuple[str, ...], people: int)`. Команды: `make space ARGS="add GE --name 'Партнёр Грузия'"`, `make space ARGS="countries GE GE"`, `make space ARGS="list"`.

- [ ] **Step 1: Написать падающие тесты**

```python
"""Волна 1 (#340): пространство и его страны заводит команда; опечатка не заводит новое."""

from __future__ import annotations

import pytest
from conftest import requires_db

psycopg = pytest.importorskip("psycopg")

from src.db.errors import AccessError  # noqa: E402
from src.db.web_access import bind_countries, create_space, list_spaces, space_exists  # noqa: E402

pytestmark = requires_db


@pytest.fixture
def владелец(pg_dsn: str, db_env: str, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("DATABASE_ADMIN_URL", pg_dsn)
    if not space_exists("HQ"):
        create_space("HQ", name="УК")
    return pg_dsn


def test_пространство_и_страна_заводятся(владелец: str) -> None:
    create_space("GE", name="Партнёр Грузия")
    assert bind_countries("GE", ("GE",)) == ("GE",)
    строка = next(s for s in list_spaces() if s.code == "GE")
    assert (строка.name, строка.countries) == ("Партнёр Грузия", ("GE",))


@pytest.mark.parametrize("код", ["ge", "../hq", "", "Г1", "HQ", "default"])
def test_негодный_или_занятый_код_это_отказ(владелец: str, код: str) -> None:
    with pytest.raises(AccessError):
        create_space(код, name="х")


def test_страна_второго_партнёра_это_отказ(владелец: str) -> None:
    """D284: одна страна — один партнёр."""
    create_space("GE", name="Грузия")
    bind_countries("GE", ("GE",))
    create_space("G2", name="Второй")
    with pytest.raises(AccessError, match="GE"):
        bind_countries("G2", ("GE",))


def test_уК_не_привязывается_к_странам(владелец: str) -> None:
    with pytest.raises(AccessError):
        bind_countries("HQ", ("GE",))


def test_негодный_код_страны_это_отказ(владелец: str) -> None:
    create_space("GE", name="Грузия")
    with pytest.raises(AccessError):
        bind_countries("GE", ("Georgia",))
```

- [ ] **Step 2: Прогнать и убедиться, что падают**

Run: `make test-honest ARGS="tests/test_db_spaces.py -q"`
Expected: FAIL — `ImportError: cannot import name 'create_space'`.

- [ ] **Step 3: Реализация `src/db/web_access.py`**

```python
SPACE_CODE = re.compile(r"^[A-Z][A-Z0-9_-]{1,31}$")
COUNTRY_CODE = re.compile(r"^[A-Z]{2}$")

_LIST_SPACES_SQL = """
    select t.code, t.name,
           coalesce((select array_agg(c.country order by c.country)
                       from space_countries c where c.tenant_code = t.code), '{}'),
           (select count(*) from web_users u where u.tenant_code = t.code and u.disabled_at is null)
      from tenants t order by t.code
"""
_OWNER_OF_COUNTRY_SQL = "select tenant_code from space_countries where country = %s"
_BIND_COUNTRY_SQL = "insert into space_countries (country, tenant_code) values (%s, %s)"


@dataclass(frozen=True)
class SpaceRow:
    code: str
    name: str
    countries: tuple[str, ...]
    people: int


def check_space_code(code: str) -> str:
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
    """Завести пространство. Совпадение с заведённым без учёта регистра — отказ:
    каталог хранилища у них был бы один (`checklist_layout.space_of`)."""
    код = check_space_code(code)
    if код.lower() in {s.code.lower() for s in list_spaces()}:
        raise AccessError(f"Пространство «{код}» уже заведено (или совпадает с заведённым без учёта регистра)")
    with _owned(f"завести пространство «{код}»") as conn, conn.cursor() as cur:
        cur.execute("insert into tenants (code, name) values (%s, %s)", (код, name.strip()))
    return SpaceRow(code=код, name=name.strip(), countries=(), people=0)


def list_spaces() -> tuple[SpaceRow, ...]:
    with _owned("перечислить пространства") as conn, conn.cursor() as cur:
        cur.execute(_LIST_SPACES_SQL)
        return tuple(SpaceRow(code=str(r[0]), name=str(r[1]), countries=tuple(r[2]), people=int(r[3]))
                     for r in cur.fetchall())


def bind_countries(space: str, countries: tuple[str, ...]) -> tuple[str, ...]:
    """Привязать пространство партнёра к странам (D284). Страна другого — отказ с его кодом."""
    код = canonical_tenant(space)
    if код == HQ_TENANT or not space_exists(код):
        raise AccessError(f"К странам привязывается заведённое пространство партнёра, а не «{space}»")
    for страна in countries:
        if not COUNTRY_CODE.match(страна):
            raise AccessError(f"Код страны «{страна}» не годится: две заглавные буквы ISO, например GE")
    with _owned(f"привязать «{код}» к странам") as conn, conn.cursor() as cur:
        for страна in countries:
            cur.execute(_OWNER_OF_COUNTRY_SQL, (страна,))
            чья = cur.fetchone()
            if чья is not None and чья[0] != код:
                raise AccessError(f"Страна {страна} уже у пространства {чья[0]}: одна страна — один партнёр")
            if чья is None:
                cur.execute(_BIND_COUNTRY_SQL, (страна, код))
    return next(s.countries for s in list_spaces() if s.code == код)
```

Роль владельца схемы пишет `space_countries` правами владельца; гранты приложению — только чтение (Task 5). Если файл перевалит 800 строк, пространства выносятся в `src/db/spaces.py` вместе с общим модулем подключений.

- [ ] **Step 4: Команда, `web_user`, демо, `Makefile`**

`tools/space.py` — по образцу `tools/web_user.py` (`load_dotenv`, `sys.path`, `argparse`): `add CODE --name`, `countries CODE XX [YY ...]`, `list`. Итог — одной строкой, `AccessError` → `SystemExit` с текстом отказа.

`tools/web_user.py`, в `_tenant` для всех подкоманд, кроме `ensure`:

```python
    if not space_exists(tenant):
        raise SystemExit(
            f"Пространства «{tenant}» нет. Опечатка в --tenant завела бы новое пустое "
            f"пространство молча; заведите его явно: make space ARGS=\"add {tenant} --name ...\""
        )
```

`tools/seed_web_demo.py` (D287): после посева — `bind_countries(DEMO_TENANT, <страны демо-пиццерий>)`. Если страна уже у другого пространства той же базы, посев печатает, какая, и пропускает её, не падая: демо на тестовой базе MUSPELHEIM соседствует с другими данными. Код `demo` строчными не проходит `SPACE_CODE`, но пространство заводится посевом в обход `create_space` (как сегодня, `_ensure_tenant`). Это единственное пространство вне правила кода, и так записано в шапке посева.

`Makefile`: цель `space: ; $(VENV)/python tools/space.py $(ARGS)` с комментарием в стиле `web-user` (роль владельца схемы, примеры), `space` в `.PHONY`.

- [ ] **Step 5: Прогнать тесты и команду**

Run: `make test-honest ARGS="tests/test_db_spaces.py tests/test_db_web_access.py -q"`, затем на тестовой базе MUSPELHEIM `make space ARGS="list"`.
Expected: PASS; перечень печатается, у `HQ` стран нет.

- [ ] **Step 6: Commit**

```bash
git add src/db/web_access.py tools/space.py tools/web_user.py tools/seed_web_demo.py Makefile tests/test_db_spaces.py
git commit -m "feat(db): пространства и их страны заводятся командой; демо — пространство партнёра (D284, D287, #340)"
```

---

### Task 14: Документация, приёмка на стенде, итоговая проверка

**Files:**
- Modify: `docs/12-web-admin.md`, `docs/06-mvp-bot.md`, `docs/08-deploy.md`, `docs/furca/blocks/bot.md`, `docs/furca/blocks/web.md`, `docs/furca/blocks/mcp.md`, `docs/furca/blocks/db.md`, `.env.example`, `CHANGELOG.md`

- [ ] **Step 1: Доки (скилл `keeping-docs-current`), сверяя с кодом**

- `.env.example`: удалить `BOT_INVITES` и `BOT_MCP_TENANT` с их абзацами; `WEB_BOT_USERNAME` — «имя бота без @ для ссылки привязки; без неё кнопка „Привязать бота“ не показывается»; `WEB_TENANT` — «тенант стенда: счётчик попыток входа и умолчание `make web-user`; чьи данные видны, решает учётка»; `ALLOWED_TELEGRAM_IDS` — «совместимость до D286: эти ID работают как сотрудники УК, пока у них нет привязки».
- `docs/12-web-admin.md`: один адрес для всех пространств; логин единый; УК читает всё, пишет своё; партнёр видит свою страну; эталон и чужое — только чтение; «Пользователи» и привязка бота; `make space`.
- `docs/06-mvp-bot.md`, `docs/furca/blocks/bot.md`: доступ по привязке, совместимость и её снятие, поведение при недоступной базе, заслон чужой проверки, справочник страны.
- `docs/furca/blocks/mcp.md`: правка — в пространстве токена, без `checklist` у партнёра — отказ; чтение проверок по охвату.
- `docs/furca/blocks/db.md`: миграции `0028`–`0031`, охват чтения, сторож точки проверки.
- `docs/08-deploy.md`: перед накатом `0028` — запрос двойников из текста миграции; перед `0030` — что проверки партнёров ещё не существуют; порядок раскатки; заведение `WEB_BOT_USERNAME`.
- `CHANGELOG.md`: запись волны 1.
- Задача #471: закрыть ссылкой на коммит Task 5 (для партнёров) с пометкой, что путь УК не менялся.
- Карточка imf-vc (`decimus.yaml`) не меняется: адрес, бот и шаги входа прежние. Если к раскатке шаг «привязать бота» становится обязательным для новых людей — строка в карточке тем же заходом.

- [ ] **Step 2: Итоговые проверки**

Run: `make check` (fmt, lint, types, test на тестовой базе MUSPELHEIM, dead, bounds).
Expected: PASS, кроме падений из «Перед началом» (помеха #348); новых нет.

Run: регресс belgrade из Global Constraints.
Expected: 97.5%, A, 5×D1 и 97.0%, A, 6×D1.

- [ ] **Step 3: Приёмочный смоук на стенде MUSPELHEIM (скилл `muspelheim`, не на Маке)**

С записью фактического ответа каждого шага:
1. `make migrate`; `make space ARGS="add GE --name 'Партнёр Грузия'"`; `make space ARGS="countries GE GE"`.
2. Админ УК на «Пользователях» заводит `ge-director` в пространство GE. Вход этой учёткой: «Проверки» — только проверки грузинских пиццерий; «Методика» открывает эталон, «Сохранить» на пункте отвечает «Эталон правит только УК».
3. Адрес карточки армянской проверки у `ge-director` — «не найдено», как у выдуманного id; то же для `/photos/<id>`. Учётка УК открывает проверку партнёра, «Снять» отвечает отказом записи.
4. `/tenants` у `ge-director` — 404, у УК — экран «в разработке».
5. `ge-director` жмёт «Привязать бота», открывает ссылку в Telegram тестового аккаунта: бот отвечает «привязан к учётке ge-director». Повтор той же ссылки — «ссылка недействительна». Проверка в боте предлагает `Batumi-1`, на `Yerevan-1` — нет в справочнике; сданная проверка в базе с `tenant_code = 'GE'` (под ролью владельца, только `select tenant_code`). «Отвязать» → через минуту бот этому аккаунту не отвечает.
6. Действующий аудитор УК из `ALLOWED_TELEGRAM_IDS` работает как раньше (совместимость).
7. Демо-стенд: поднимается, «Методика» показывает эталон и отказ правки, а не ошибку.

Что проверить нельзя (например, бот стенда недоступен) — записать в отчёт прямо, не выдавать за проверенное.

- [ ] **Step 4: Commit и PR**

```bash
git add docs .env.example CHANGELOG.md
git commit -m "docs: пространства (волна 1) — вход, привязка бота, охват, команды (#340)"
git push -u origin feat/spaces-wave1
gh pr create --title "Пространства, волна 1: граница на сервере, привязка бота (#340)" --body-file <файл с описанием>
```

PR не вливается и не раскатывается без «да» владельца; миграции на проде — отдельное «да» (скилл `deploy-window`).

---

## Самопроверка плана

- **Спека и решения → задачи.** Одно пространство у человека, свои люди, логин на систему (D282) — задачи 4, 8. Бот привязывается через веб (D286) — задачи 9–11. Граница на сервере на каждом запросе: экран — 6, 7, 8; дверь методики — 1, 7; MCP — 2, 6; бот — 11, 12. Чужое — «не найден» тем же ответом — 1, 5, 6, 7. УК читает партнёра, пишет своё (D283) — 1 (`read_spaces`), 5 (`reach_of`), 6 (`_own`), 7 (`foreign_readonly`). Одна страна — один партнёр, справочник один (D284) — 5, 13. Все годные эталоны в боте партнёра (D285) — 3. Демо — пространство партнёра (D287) — 13, 14. Админ партнёра не управляет людьми (D288) — 8. Раздел действий УК только HQ (D264) — 8, механизм `hq_only`; сам раздел заведёт волна 2 спеки страны.
- **Не входит (волны 2–5 спеки):** раскладка «От УК»/«Наши», копия эталона правкой и предложения, «Обзор» с выбором чек-листа. Волна 1 кладёт под них данные (`RailRow.etalon`, `BotChecklist.space`) и не рисует их.
- **Риски после волны.** Проверка хранит `checklist_code` без пространства (T345): в волне коды эталона и партнёров не повторяются (задача 1), колонка пространства понадобится в волне 4. Совместимость `ALLOWED_TELEGRAM_IDS`/`roster.json` пускает людей УК без учётки, пока её не сняли (вопрос 2). Демо на тестовой базе может не получить страну, занятую другим пространством той же базы (задача 13). Чтение по охвату затрагивает каждый запрос истории: сверка `test_каждое_чтение_стоит_на_охвате` ловит забытое по тексту `from inspections i`, а запрос, названный иначе, она пропустит — такой запрос обязан попасть в неё при заведении.
