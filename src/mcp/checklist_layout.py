"""Раскладка хранилища методик: пространство, чек-лист, издания.

До T341 хранилище несло ровно один чек-лист: издания лежали прямо в
`<store>/versions/`, журнал был один на всё, а указатель `current` вёл на
издание. Пока чек-лист один, разницы нет; со вторым такая раскладка
разваливается молча — два чек-листа кладут свои издания в один каталог и делят
один журнал.

Раскладка теперь двухуровневая (D183):

```
<store>/
  current -> <пространство>/<код>/current    применён к проду, ровно один
  <пространство>/
    <код>/
      meta.json                              код, названия, состояние
      current -> versions/<издание>          опубликованное издание ЭТОГО чек-листа
      versions/<издание>/                    семь файлов методики
      journal.jsonl                          журнал правок ЭТОГО чек-листа
```

Три свойства, каждое намеренно.

**`AUDIT_DATA_DIR` не меняется.** Он как и раньше смотрит на `<store>/current`;
поменялось лишь то, куда этот указатель ведёт — теперь на указатель чек-листа, а
тот уже на издание. Площадку перенастраивать не нужно, а значит миграция не
может разойтись с окружением.

**`meta.json` лежит РЯДОМ с изданиями, а не внутри.** Состояние чек-листа не
входит в отпечаток методики: пометка «в работе» не меняет ни одного вопроса и
порождать новое издание не должна.

**Журнал на чек-лист.** «Кто и что правил» читается по тому чек-листу, который
смотрят, и не тонет в соседних.

**Миграция обратима.** Она ничего не переписывает — только перекладывает:
`versions/` и `journal.jsonl` переезжают в `<пространство>/<код>/`, указатели
переставляются. Обратный ход — переместить их назад и направить `<store>/current`
на `versions/<издание>`; хранилище снова однослойное и работает со старым кодом.
"""

from __future__ import annotations

import json
import os
import secrets
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

# Чтение раскладки — то, что нужно и боту, — живёт ярусом ниже, в `src.domain`
# (#455): бот выбирает чек-лист там, а `src.domain` не имеет права звать
# `src.mcp`. Здесь эти имена переиздаются как были, а отказы `domain`
# переводятся в словарь блока MCP — точка входа ловит `ChecklistError`.
from ..domain import checklist_store as _store
from ..domain.checklist_store import (  # переиздание: прежние импортёры не меняются
    ACTIVE as ACTIVE,
)
from ..domain.checklist_store import (
    CURRENT_LINK as CURRENT_LINK,
)
from ..domain.checklist_store import (
    DEFAULT_CODE as DEFAULT_CODE,
)
from ..domain.checklist_store import (
    DEFAULT_SPACE as DEFAULT_SPACE,
)
from ..domain.checklist_store import (
    DRAFT as DRAFT,
)
from ..domain.checklist_store import (
    META_FILE as META_FILE,
)
from ..domain.checklist_store import (
    RETIRED as RETIRED,
)
from ..domain.checklist_store import (
    SLUG_PATTERN as SLUG_PATTERN,
)
from ..domain.checklist_store import (
    STATES as STATES,
)
from ..domain.checklist_store import (
    VERSIONS_DIR as VERSIONS_DIR,
)
from ..domain.checklist_store import (
    Meta as Meta,
)
from ..domain.checklist_store import (
    Store as Store,
)
from ..domain.checklist_store import (
    applied as applied,
)
from ..domain.checklist_store import (
    in_bot_of as in_bot_of,
)
from ..domain.checklist_store import (
    known as known,
)
from ..domain.checklist_store import (
    prod_link as prod_link,
)
from ..domain.checklist_store import (
    read_meta as read_meta,
)
from .errors import ChecklistError

#: Названия того же чек-листа для человека (D181). Связь — кодом, показ —
#: названием: формулировки переводятся и правятся, коды нет.
DEFAULT_NAMES = ("Проверка бизнес-девелопера", "Business developer audit")

#: Хвост отказа, объясняющий, куда делся путь.
#:
#: Ответ инструмента уходит в модель, то есть за пределы машины, и абсолютный
#: путь в нём показывает устройство каталогов деплоя и имя пользователя, под
#: которым поднят сервер (T120, issue #96). Вырезать путь молча нельзя: тому,
#: кто держит сервер, чинить тогда нечего. Поэтому агенту достаётся причина
#: словами и именами переменных, а путь — логу процесса, который остаётся на
#: машине.
IN_LOG = "Какие именно каталоги — в логе сервера: он остаётся на машине"

#: Журнал правок. Строка на событие, дописывается и не переписывается.
JOURNAL_FILE = "journal.jsonl"

#: Где собираются кандидаты. Внутри чек-листа, чтобы принятое издание въезжало
#: на место переименованием, а не копированием через границу файловой системы.
TMP_DIR = ".tmp"


def _translated[T](call: Callable[[], T]) -> T:
    """Позвать правило яруса `domain` и перевести его отказ в словарь блока MCP.

    Слова отказа те же: правило одно (`src/domain/checklist_store.py`), меняется
    только тип — точка входа MCP и админка ловят `ChecklistError`.
    """
    try:
        return call()
    except _store.ChecklistStoreError as отказ:
        raise ChecklistError(str(отказ)) from None


def check_slug(value: str, *, что: str) -> str:
    """Код пространства или чек-листа — или отказ с примером годного (`ChecklistError`)."""
    return _translated(lambda: _store.check_slug(value, что=что))


def space_of(tenant: str) -> str:
    """Каталог пространства в хранилище для кода тенанта: `HQ` → `hq` (D183)."""
    return _translated(lambda: _store.space_of(tenant))


def bot_spaces(tenant: str) -> tuple[str, ...]:
    """Где искать чек-лист по коду: своё первым, эталон следом (`ChecklistError`)."""
    return _translated(lambda: _store.bot_spaces(tenant))


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
            # Код сбрасывается на умолчание, а не наследуется от `store`: иначе
            # хранилище, ранее наведённое на чужой код, подставило бы его сюда,
            # и «без кода» партнёра увело бы не в эталон, а в код из прошлого
            # вызова (Review Н17).
            найдено = for_code(replace(store, space=s, code=DEFAULT_CODE), None)
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


def check_state(value: str) -> str:
    """Состояние чек-листа — или отказ, перечисляющий годные."""
    значение = (value or "").strip()
    if значение not in STATES:
        raise ChecklistError(
            f"Состояние «{value}» неизвестно. Годятся: {', '.join(STATES)} — черновик, в работе, "
            f"снят"
        )
    return значение


def swap_link(link: Path, target: str) -> None:
    """Перевести указатель одним неделимым действием.

    Ссылка создаётся под временным именем и переименовывается на место:
    удалить и создать заново означало бы окно, в котором движок читает методику
    по несуществующему пути.

    Имя временной ссылки уникально: одно и то же имя два раза не займут ни два
    потока сервера, ни два процесса, ни брошенная ссылка после падения.
    """
    link.parent.mkdir(parents=True, exist_ok=True)
    временный = link.parent / f".{link.name}.{os.getpid()}.{secrets.token_hex(6)}"
    os.symlink(target, временный)
    os.replace(временный, link)


def guard_link(link: Path, *, что: str, подсказка: str) -> None:
    """Отказать, если на месте указателя лежит не ссылка.

    Хранилище держится на указателях-ссылках. Обычный файл или каталог на их
    месте означает, что каталог собран не этим механизмом, и дописывать в него
    издания нельзя — иначе однажды окажется, что публикация никуда не ведёт.
    """
    if link.exists(follow_symlinks=False) and not link.is_symlink():
        raise ChecklistError(f"На месте указателя {что} лежит не ссылка. {подсказка}")


# --- карточка чек-листа -------------------------------------------------------


def write_meta(store: Store, meta: Meta) -> None:
    """Записать карточку целиком. Запись атомарна: полкарточки не бывает."""
    store.home.mkdir(parents=True, exist_ok=True)
    поля: dict[str, object] = {
        "code": meta.code,
        "name_ru": meta.name_ru,
        "name_en": meta.name_en,
        "state": meta.state,
    }
    # Нет решения — нет ключа: пустой ключ читался бы как «не в боте» и снял
    # бы с бота чек-лист, по которому сегодня идут проверки.
    if meta.in_bot is not None:
        поля["in_bot"] = meta.in_bot
    тело = json.dumps(
        поля,
        ensure_ascii=False,
        indent=2,
    )
    временный = store.home / f".{META_FILE}.{os.getpid()}.{secrets.token_hex(6)}"
    временный.write_text(тело + "\n", encoding="utf-8")
    os.replace(временный, store.home / META_FILE)


# --- применение к проду -------------------------------------------------------


def guard_prod_link(root: Path) -> None:
    """Отказать, если верхний указатель занят не ссылкой.

    Зовётся ПЕРЕД тем, как хранилище начнут заводить, а не после. Иначе первый
    вызов успевал бы разложить издания и падал на последнем шаге, а второй шёл
    бы мимо отказа как ни в чём не бывало: сбитое хранилище выглядело бы
    исправным со второго раза.
    """
    guard_link(
        prod_link(root),
        что=f"применённого к проду чек-листа — файла «{CURRENT_LINK}» в хранилище",
        подсказка=(
            f"Хранилище версий методики, названное в MCP_CHECKLIST_STORE, собрано не этим "
            f"механизмом: уберите этот файл или укажите под хранилище другой каталог. {IN_LOG}"
        ),
    )


def point_prod_at(store: Store) -> None:
    """Применить чек-лист к проду: перевести верхний указатель на его `current`.

    Проверок годности чек-листа здесь нет намеренно — они стоят ярусом выше, у
    операции применения (`apply_checklist`): здесь только перестановка, и она
    обязана быть одним действием.
    """
    guard_prod_link(store.root)
    swap_link(prod_link(store.root), os.path.join(store.space, store.code, CURRENT_LINK))


def for_code(store: Store, code: str | None) -> Store:
    """Хранилище, наведённое на названный чек-лист — или на применённый к проду.

    Умолчание здесь не «тот, что был единственным», а именно **применённый к
    проду**: иначе вызов без кода после смены прода продолжал бы править
    чек-лист, по которому больше не считают, и правка уходила бы в никуда
    молча.

    Код проверяется до подстановки: он становится куском пути внутри
    хранилища, а приходит снаружи — из вызова агента.
    """
    if code is not None:
        return replace(store, code=check_slug(code, что="Код чек-листа"))
    в_проде = applied(store.root)
    if в_проде is None:
        return store
    space, чей = в_проде
    # Указатель прода один на хранилище и смотрит в пространство УК. Кто не назвал
    # чек-лист, остаётся в своём пространстве (Review Focus 4).
    if space != store.space:
        return store
    return replace(store, space=space, code=чей)


# --- миграция однослойного хранилища ------------------------------------------


def migrate(store: Store) -> bool:
    """Перенести однослойное хранилище в `<пространство>/<код>/`. Идемпотентна.

    Возвращает, случился ли перенос. Ничего не переписывается — только
    перекладывается, поэтому обратный ход это перемещение назад.

    Издание, на которое смотрел верхний указатель, остаётся тем же: ссылка
    читается ДО переноса и восстанавливается после. Иначе продукт после
    миграции считал бы по другому изданию, не сказав об этом ни слова.
    """
    старые = store.root / VERSIONS_DIR
    if not старые.is_dir():
        return False

    было = None
    link = prod_link(store.root)
    if link.is_symlink():
        цель = Path(os.readlink(link))
        if цель.parts and цель.parts[0] == VERSIONS_DIR:
            было = цель.name

    новые = store.home / VERSIONS_DIR
    if новые.exists():
        raise ChecklistError(
            f"Хранилище версий методики выглядит наполовину перенесённым: издания лежат и в "
            f"старом месте, и в «{store.space}/{store.code}». Слить их молча нельзя — уберите "
            f"одно из двух и повторите"
        )
    store.home.mkdir(parents=True, exist_ok=True)
    os.replace(старые, новые)

    старый_журнал = store.root / JOURNAL_FILE
    if старый_журнал.is_file():
        os.replace(старый_журнал, store.home / JOURNAL_FILE)

    if было is not None:
        swap_link(store.home / CURRENT_LINK, os.path.join(VERSIONS_DIR, было))
        point_prod_at(store)

    if read_meta(store) is None:
        write_meta(
            store,
            Meta(
                code=store.code,
                name_ru=DEFAULT_NAMES[0],
                name_en=DEFAULT_NAMES[1],
                state=ACTIVE,
            ),
        )
    return True
