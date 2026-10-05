"""Раскладка хранилища методик — та её часть, которую читает бот (#455).

Как устроено хранилище целиком (пространство → чек-лист → издания, указатели,
миграция однослойного хранилища) — `src/mcp/checklist_layout.py`. Здесь живёт
только чтение, без которого бот не выберет чек-лист: перечень, карточка,
указатель прода, пространства тенанта и годность чек-листа к боту.

Почему отдельно. Бот выбирает чек-лист в `src/domain/bot_checklists.py`, а
`src.domain` — нижний ярус контракта `lint-imports`: импортировать `src.mcp`
ему нельзя. Раньше бот брал раскладку оттуда, и контракт стоял красным.
Теперь зависимость развёрнута: раскладка для чтения лежит здесь, а `src.mcp`
берёт её отсюда и достраивает запись — правило одно, домов у него один.

Отказы здесь — `ChecklistStoreError` (ярус `domain`). Дверь MCP переводит их в
свой `ChecklistError` теми же словами (`src/mcp/checklist_layout.py`), как
делает это с правилом имени издания из `src/report/engine_call.py`.
"""

from __future__ import annotations

import csv
import json
import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from .edition import DEFAULT_CODE as DEFAULT_CODE
from .errors import DomainError
from .version import is_one_segment

#: Пространство управляющей компании — то единственное, что существует сегодня.
#:
#: `hq`, а не `uk`: пространства получат и партнёры (D182), а продукт работает
#: по Европе, Кавказу, Монголии, Бали и Нигерии — `uk` в таком соседстве
#: читается страной, а не управляющей компанией.
DEFAULT_SPACE = "hq"

#: Каталог версий методики внутри хранилища. Имя общее для всех, кто в это
#: хранилище смотрит: разойдясь, они читали бы разные каталоги.
VERSIONS_DIR = "versions"

#: Карточка чек-листа рядом с его изданиями.
META_FILE = "meta.json"

#: Указатель: и на верхнем ярусе (применён к проду), и внутри чек-листа
#: (опубликованное издание). Имя одно, потому что смысл один — «вот это».
CURRENT_LINK = "current"

#: Состояния чек-листа. `draft` — черновик, годен к правке и не годен к проду;
#: `active` — в работе, таких может быть несколько (задел под выбор чек-листа на
#: старте проверки, D178); `retired` — снят, к проду не применяется.
#:
#: Состояние и применение к проду — разные вещи: «в работе» говорит, что
#: чек-лист годен к употреблению, а «применён к проду» — указатель, и он ровно
#: один, пока выбора на старте не спрашивают.
DRAFT, ACTIVE, RETIRED = "draft", "active", "retired"
STATES = (DRAFT, ACTIVE, RETIRED)

#: Код пространства и код чек-листа: строчные латинские буквы, цифры, дефис и
#: подчёркивание. Тот же шаблон, что у имени набора методики, и это не
#: совпадение — код чек-листа становится куском пути и именем в базе.
SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")

#: Строка вида пункта, которая делает чек-лист способным что-то найти. Пункты
#: других видов (замеры, информационные) в оценке не участвуют, и чек-лист из
#: них одних даёт те же 100%, что пустой.
VIOLATION_KIND = "violation"

#: Почему чек-лист нельзя открыть в боте — коды, а не фразы: текст подбирает
#: экран на своём языке.
BOT_BLOCK_DRAFT, BOT_BLOCK_RETIRED, BOT_BLOCK_UNPUBLISHED, BOT_BLOCK_EMPTY = (
    "draft",
    "retired",
    "unpublished",
    "empty",
)


class ChecklistStoreError(DomainError):
    """Хранилище методик или код в нём не годятся — отказ яруса `domain`.

    Код отказа и параметры — как у отказов MCP (`src/mcp/errors.py`): MCP
    переводит этот отказ в свой, не теряя их, и веб берёт по коду фразу на
    языке интерфейса (#504). Текст остаётся русским — его читает агент.
    """

    def __init__(
        self,
        message: str,
        *,
        refusal: str | None = None,
        params: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.refusal = refusal
        self.params: Mapping[str, object] = MappingProxyType(dict(params or {}))


@dataclass(frozen=True)
class Store:
    """Куда пишем издания и что сегодня читает движок.

    `root` — хранилище целиком (`MCP_CHECKLIST_STORE`), `live` — каталог
    методики продукта (`AUDIT_DATA_DIR`). Пара «пространство + код» называет,
    С КАКИМ чек-листом работает вызывающий; не названа — работаем с тем, что
    был единственным до множественности.

    Умолчания здесь не для краткости. Ими держится обещание, ради которого
    двухуровневая раскладка и делалась так: вызов, ничего не знающий про
    чек-листы, продолжает работать слово в слово.
    """

    root: Path
    live: Path
    space: str = DEFAULT_SPACE
    code: str = DEFAULT_CODE

    @property
    def home(self) -> Path:
        """Каталог этого чек-листа: издания, журнал и карточка внутри него."""
        return self.root / self.space / self.code


@dataclass(frozen=True)
class Meta:
    """Карточка чек-листа: чем он связан, как называется и годен ли к делу."""

    code: str
    name_ru: str
    name_en: str
    state: str
    #: Доступен ли аудиторам в боте (волна 3, D221). `None` — ключа в карточке
    #: нет: так выглядит каждая карточка до волны 3, и тогда «в боте» тот, на
    #: кого смотрит верхний указатель `current` (`in_bot_of`).
    in_bot: bool | None = None


def check_slug(value: str, *, что: str) -> str:
    """Код пространства или чек-листа — или отказ с примером годного.

    Проверяется здесь, а не у вызывающего: код становится куском пути внутри
    хранилища, и `..` в нём открыл бы дорогу к чужому каталогу.
    """
    значение = (value or "").strip()
    if not SLUG_PATTERN.match(значение):
        raise ChecklistStoreError(
            f"{что} «{value}» не годится: ожидаются строчные латинские буквы, цифры, дефис и "
            f"подчёркивание, до 32 знаков (например «bizdev»). Код уезжает в базу к каждой "
            f"проверке и в путь хранилища, поэтому он строже названия",
            refusal="bad_slug",
            params={"value": value},
        )
    return значение


#: Прежний код тенанта УК, `default` (до переименования в `HQ`, D234, #439).
#: Он ещё живёт в `MCP_TOKENS` и файлах состояния идущих проверок бота — не
#: приведённый `canonical_tenant`: эта карта старше переезда сюда, и правило
#: «какой каталог у тенанта» держится на ней одной.
_LEGACY_TENANT_SPACES: dict[str, str] = {"default": DEFAULT_SPACE}


def space_of(tenant: str) -> str:
    """Каталог пространства в хранилище для кода тенанта: `HQ` → `hq` (D183).

    Старый код тенанта УК приводится картой выше, а не проверкой слага: он не
    должен читаться как код пространства партнёра «default».
    """
    очищенный = (tenant or "").strip().lower()
    if очищенный in _LEGACY_TENANT_SPACES:
        return _LEGACY_TENANT_SPACES[очищенный]
    return check_slug(очищенный, что="Код пространства")


def bot_spaces(tenant: str) -> tuple[str, ...]:
    """Где искать чек-лист по коду и что предлагать боту: своё первым, эталон следом.

    Своё первым: при поиске по коду оно выигрывает, и копия партнёра (волна 4) не
    подменяется эталоном с тем же кодом.
    """
    своё = space_of(tenant)
    return (своё,) if своё == DEFAULT_SPACE else (своё, DEFAULT_SPACE)


def read_meta(store: Store) -> Meta | None:
    """Карточка чек-листа. Нет карточки — `None`, а не отказ.

    `None` законен: так выглядит хранилище, которое ещё не заводили, и
    однослойное хранилище до миграции. Отказывать на это значило бы требовать
    карточку раньше, чем её есть кому написать.
    """
    путь = store.home / META_FILE
    if not путь.is_file():
        return None
    тело = json.loads(путь.read_text(encoding="utf-8"))
    return Meta(
        code=str(тело.get("code") or store.code),
        name_ru=str(тело.get("name_ru") or ""),
        name_en=str(тело.get("name_en") or ""),
        state=str(тело.get("state") or ACTIVE),
        in_bot=тело["in_bot"] if isinstance(тело.get("in_bot"), bool) else None,
    )


def meta_or_default(store: Store) -> Meta:
    """Карточка чек-листа или та, которой он был бы заведён.

    Карточки может не быть у хранилища, перенесённого руками. Отказывать на это
    нельзя: перечень чек-листов обязан показывать и такой, иначе человек не
    увидит, что у него на диске.
    """
    карточка = read_meta(store)
    if карточка is not None:
        return карточка
    return Meta(code=store.code, name_ru=store.code, name_en=store.code, state=ACTIVE)


def in_bot_of(карточка: Meta, space: str, code: str, в_проде: tuple[str, str] | None) -> bool:
    """Доступен ли чек-лист в боте — с учётом карточек до волны 3.

    Флаг карточки решает, когда он записан. Нет ключа — наследуем прежний смысл:
    в боте тот, на кого смотрит верхний указатель `current`. Так хранилище
    прода после выката показывает ровно то, по чему проверки шли вчера, и
    мигрировать его не нужно. Снятый и черновик в боте не бывают, что бы ни
    стояло во флаге: флаг — намерение, «в работе» — годность.
    """
    if карточка.state != ACTIVE:
        return False
    if карточка.in_bot is not None:
        return карточка.in_bot
    return в_проде == (space, code)


def prod_link(root: Path) -> Path:
    """Указатель «по этому чек-листу идут проверки». Ровно один на хранилище."""
    return root / CURRENT_LINK


def applied(root: Path) -> tuple[str, str] | None:
    """Какой чек-лист применён к проду — или `None`, если указателя нет.

    Читается по ссылке, а не по отдельной записи: указатель и есть ответ, а
    вторая копия этого факта разошлась бы с ним молча.
    """
    link = prod_link(root)
    if not link.is_symlink():
        return None
    куски = Path(os.readlink(link)).parts
    # Ждём «<пространство>/<код>/current». Другая форма — однослойное хранилище
    # до миграции («versions/<издание>»): чек-листа она не называет.
    if len(куски) != 3 or куски[2] != CURRENT_LINK:
        return None
    return куски[0], куски[1]


def known(root: Path) -> list[tuple[str, str]]:
    """Все чек-листы хранилища парами «пространство, код», по порядку.

    Чек-листом считается каталог с изданиями или с карточкой: каталог, куда
    ничего не положили, чек-листом не является и в перечне только мешал бы.
    """
    if not root.is_dir():
        return []
    найденные: list[tuple[str, str]] = []
    for пространство in sorted(p for p in root.iterdir() if p.is_dir()):
        if пространство.name.startswith(".") or пространство.name == VERSIONS_DIR:
            continue
        for чеклист in sorted(c for c in пространство.iterdir() if c.is_dir()):
            if (чеклист / VERSIONS_DIR).is_dir() or (чеклист / META_FILE).is_file():
                найденные.append((пространство.name, чеклист.name))
    return найденные


def published_edition(store: Store) -> str | None:
    """Опубликованное издание чек-листа — или `None`, если публиковать нечего."""
    указатель = store.home / CURRENT_LINK
    if not указатель.is_symlink():
        return None
    return Path(os.readlink(указатель)).name


def count_violations(каталог: Path) -> int:
    """Сколько в методике пунктов, по которым бывает нарушение.

    Считается разбором файла, а не движком: движок таких вопросов не отвечает, а
    заводить ради счёта четвёртый подпроцесс — дороже и медленнее. Формат
    колонок общий с движком (`id,kind,...`), и разойтись они не могут: колонку
    `kind` читает и он.
    """
    путь = каталог / "checklist.csv"
    if not путь.is_file():
        return 0
    with путь.open(encoding="utf-8-sig", newline="") as f:
        return sum(
            1
            for строка in csv.DictReader(f)
            if (строка.get("kind") or "").strip() == VIOLATION_KIND
        )


def published_dir(store: Store, edition: str) -> Path:
    """Каталог опубликованного издания — или отказ, если указатель ведёт в пустоту.

    Имя издания проверяется тем же правилом, что везде в продукте
    (`domain.version.is_one_segment`): оно становится куском пути.
    """
    if not is_one_segment((edition or "").strip()):
        raise ChecklistStoreError(
            f"«{edition}» не может быть именем каталога издания. Перечень версий отдаёт "
            f"checklist_versions",
            refusal="bad_version",
            params={"version": edition},
        )
    каталог = store.home / VERSIONS_DIR / edition
    if not каталог.is_dir():
        raise ChecklistStoreError(
            f"Версии методики «{edition}» в хранилище нет. Перечень версий отдаёт "
            f"checklist_versions",
            refusal="version_missing",
            params={"version": edition},
        )
    return каталог


def bot_block(
    store: Store, *, version_dir: Callable[[Store, str], Path] = published_dir
) -> str | None:
    """Код причины, по которой чек-лист нельзя открыть в боте, или `None`.

    Пустое опубликованное издание называется здесь `BOT_BLOCK_EMPTY`, даже если
    пункты уже записаны в неопубликованную версию: отличить «пусто» от «не
    опубликовано» может только тот, кто читает журнал правок, а журнал — дело
    двери MCP (`src/mcp/checklists.py: bot_block`). Боту разница не нужна:
    в обоих случаях чек-лист в бот не годится.

    `version_dir` — как найти каталог издания и чем отказать, если его нет:
    дверь MCP подставляет свой поиск, чтобы отказ пришёл в её словаре.
    """
    карточка = meta_or_default(store)
    if карточка.state == RETIRED:
        return BOT_BLOCK_RETIRED
    if карточка.state == DRAFT:
        return BOT_BLOCK_DRAFT
    издание = published_edition(store)
    if издание is None:
        return BOT_BLOCK_UNPUBLISHED
    if count_violations(version_dir(store, издание)) == 0:
        return BOT_BLOCK_EMPTY
    return None
