"""Чек-листы, по которым аудитор может начать проверку в боте (волна 3, D221).

Что открыто в боте, решает методист в админке — флагом в карточке чек-листа
(`src/mcp/checklists.py: set_bot_access`). Здесь это только читается: бот
ничего в хранилище не пишет, том ему смонтирован на чтение. Раскладку
хранилища и годность чек-листа к боту бот берёт ярусом ниже, у себя в
`src.domain` (`checklist_store`), — звать `src.mcp` ему нельзя (#455).

Без хранилища (`MCP_CHECKLIST_STORE` не задан, как в разработке и на демо) бот
ведёт себя слово в слово как до волны 3: чек-лист один, `bizdev`, методика —
`AUDIT_DATA_DIR`. Пустое, ещё не заведённое хранилище читается так же: его
заводит первый заход в админку снимком той же методики.

С волны 1 (#340) бот знает пространство аудитора. В своём пространстве видно
то, что открыто галочкой «в боте»; эталон УК партнёру виден весь годный —
независимо от галочки (D285, D227): это методика, которую партнёр обязан вести,
а не то, что для него по отдельности включили.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .checklist_store import (
    ACTIVE,
    CURRENT_LINK,
    DEFAULT_SPACE,
    Store,
    applied,
    bot_block,
    bot_spaces,
    in_bot_of,
    known,
    read_meta,
)
from .checklist_store import (
    DEFAULT_CODE as _DEFAULT_CODE,
)
from .config import Settings
from .errors import DomainError
from .tenants import canonical_tenant

#: Код чек-листа по умолчанию — тот, что был единственным до множественности.
#: Объявлен один раз (`src/domain/edition.py`), здесь только переиздан.
DEFAULT_CODE = _DEFAULT_CODE


@dataclass(frozen=True)
class BotChecklist:
    """Чек-лист, открытый в боте: чем связан, как называется, где его методика."""

    code: str
    name_ru: str
    name_en: str
    #: Каталог опубликованного издания — с него снимается снимок на старте.
    source: Path
    #: Пространство, которому принадлежит чек-лист: `hq` — эталон, иначе свой
    #: код партнёра. Последним и с умолчанием: остальные поля — без него, а на
    #: границе с умолчанием пространство однажды забудут передать (Review Н2).
    space: str = DEFAULT_SPACE

    def name(self, lang: str) -> str:
        """Название на языке интерфейса; английского нет — русское, пусто — код."""
        if lang == "ru":
            return self.name_ru or self.code
        return self.name_en or self.name_ru or self.code


def _legacy(settings: Settings) -> list[BotChecklist]:
    return [BotChecklist(code=DEFAULT_CODE, name_ru="", name_en="", source=settings.data_dir)]


def available(settings: Settings, *, tenant: str) -> list[BotChecklist]:
    """Чек-листы, по которым аудитор этого пространства начинает проверку.

    Своё пространство — открытые галочкой «в боте». Эталон у партнёра — все годные
    (D285, D227): в работе, с опубликованным изданием и пунктами (`bot_block`),
    независимо от того, открыла ли их УК своему боту.
    """
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
        # Не «в работе» у эталона отсекает и следующая строка (`bot_block`
        # заводит на этом `BOT_BLOCK_DRAFT`/`BOT_BLOCK_RETIRED`) — проверка
        # оставлена явной, а не убрана: годность эталона партнёру не должна
        # держаться на одной строке чужого модуля (Review Minor №3).
        if space != своё and карточка.state != ACTIVE:
            continue
        if bot_block(store) is not None:
            continue
        источник = root / space / code / CURRENT_LINK
        if not источник.is_dir():
            continue
        ответ.append(
            BotChecklist(
                code=code,
                space=space,
                name_ru=карточка.name_ru,
                name_en=карточка.name_en,
                source=источник,
            )
        )
    return sorted(ответ, key=lambda c: c.name_ru.casefold())


def source_for(settings: Settings, code: str, *, space: str = DEFAULT_SPACE) -> Path:
    """Каталог опубликованного издания чек-листа — откуда снимать снимок.

    Не открытый в боте тоже годится: так проверку, начатую по чек-листу,
    который потом закрыли, можно перевести на его действующее издание. Без
    хранилища есть только `bizdev`, и его методика — `AUDIT_DATA_DIR`.
    """
    root = settings.checklist_store
    if root is None or not root.is_dir() or not known(root):
        if code == DEFAULT_CODE:
            return settings.data_dir
        raise DomainError(
            f"Чек-лист «{code}» взять неоткуда: хранилище версий методики боту не "
            f"подключено (MCP_CHECKLIST_STORE), а без него чек-лист один — {DEFAULT_CODE}"
        )
    источник = root / space / code / CURRENT_LINK
    if not источник.is_dir():
        raise DomainError(
            f"У чек-листа «{space}/{code}» нет опубликованного издания в хранилище {root} — "
            f"проверку по нему вести не по чему"
        )
    return источник


def space_for(settings: Settings, tenant: str, code: str) -> str:
    """Пространство, где физически лежит издание кода у этого тенанта.

    Своё пространство первым, эталон УК следом — тот же порядок, что у
    `available` (Review Minor №1): правило «где искать» живёт в одном месте, а
    не повторяется у каждого вызывающего. Код не найден ни там, ни там —
    отдаём своё: `source_for` по нему откажет понятным текстом, который
    назовёт именно то пространство, где искали (Review Minor №2).
    """
    root = settings.checklist_store
    где = bot_spaces(canonical_tenant(tenant))
    if root is not None:
        for кандидат in где:
            if (root / кандидат / code / CURRENT_LINK).is_dir():
                return кандидат
    return где[0]


def pick(settings: Settings, code: str | None, *, tenant: str) -> BotChecklist:
    """Чек-лист, по которому начинается проверка, — или отказ, почему не он.

    Код не назван — годится, только если открыт ровно один: выбирать за
    аудитора, когда их несколько, значило бы угадывать. Назван, но уже не
    открыт (методист закрыл, пока аудитор смотрел на кнопки) — отказ, а не
    молчаливая подмена на соседний.
    """
    открыты = available(settings, tenant=tenant)
    if not открыты:
        # Причина не одна: свой чек-лист открывает методист галочкой «Доступ
        # в боте», а эталон УК становится видимым сам — переводом в работу и
        # публикацией (D285). Партнёру, у которого не годен именно эталон,
        # текст только про галочку соврал бы про причину (Review Minor №4).
        raise DomainError(
            "Начать проверку не по чему: ни один чек-лист сейчас не годится. Свой чек-лист в "
            "бот открывает методист в админке — «Методика» → «Доступ в боте»; эталон "
            "становится видимым сам, когда его перевели в работу и опубликовали"
        )
    if code is None:
        if len(открыты) == 1:
            return открыты[0]
        raise DomainError(
            f"В боте открыто несколько чек-листов ({', '.join(c.code for c in открыты)}) — "
            f"назовите, по какому начинать проверку"
        )
    for c in открыты:
        if c.code == code:
            return c
    raise DomainError(f"Чек-лист «{code}» больше не открыт в боте — выберите из доступных")
