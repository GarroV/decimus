"""Чек-листы, по которым аудитор может начать проверку в боте (волна 3, D221).

Что открыто в боте, решает методист в админке — флагом в карточке чек-листа
(`src/mcp/checklists.py: set_bot_access`). Здесь это только читается: бот
ничего в хранилище не пишет, том ему смонтирован на чтение.

Без хранилища (`MCP_CHECKLIST_STORE` не задан, как в разработке и на демо) бот
ведёт себя слово в слово как до волны 3: чек-лист один, `bizdev`, методика —
`AUDIT_DATA_DIR`. Пустое, ещё не заведённое хранилище читается так же: его
заводит первый заход в админку снимком той же методики.

Пространство пока одно — УК (`hq`): бот пространств не знает до волны 1
(#340). Когда узнает, сюда придёт пространство аудитора, и эталон УК будет
виден рядом с чек-листами партнёра (D227).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.mcp.checklist_layout import (
    CURRENT_LINK,
    DEFAULT_SPACE,
    Store,
    applied,
    in_bot_of,
    known,
    read_meta,
)

from .config import Settings
from .errors import DomainError

#: Код чек-листа по умолчанию — тот, что был единственным до множественности.
DEFAULT_CODE = "bizdev"


@dataclass(frozen=True)
class BotChecklist:
    """Чек-лист, открытый в боте: чем связан, как называется, где его методика."""

    code: str
    name_ru: str
    name_en: str
    #: Каталог опубликованного издания — с него снимается снимок на старте.
    source: Path

    def name(self, lang: str) -> str:
        """Название на языке интерфейса; английского нет — русское, пусто — код."""
        if lang == "ru":
            return self.name_ru or self.code
        return self.name_en or self.name_ru or self.code


def _legacy(settings: Settings) -> list[BotChecklist]:
    return [BotChecklist(code=DEFAULT_CODE, name_ru="", name_en="", source=settings.data_dir)]


def available(settings: Settings) -> list[BotChecklist]:
    """Открытые в боте чек-листы пространства УК, по названию.

    Чек-лист без опубликованного издания сюда не попадает, даже с флагом: снять
    с него снимок нечем. Снятый и черновик не попадают по `in_bot_of`.
    """
    root = settings.checklist_store
    if root is None or not root.is_dir() or not known(root):
        return _legacy(settings)
    в_проде = applied(root)
    ответ = []
    for space, code in known(root):
        if space != DEFAULT_SPACE:
            continue
        карточка = read_meta(Store(root=root, live=settings.data_dir, space=space, code=code))
        if карточка is None or not in_bot_of(карточка, space, code, в_проде):
            continue
        источник = root / space / code / CURRENT_LINK
        if not источник.is_dir():
            continue
        ответ.append(
            BotChecklist(
                code=code, name_ru=карточка.name_ru, name_en=карточка.name_en, source=источник
            )
        )
    return sorted(ответ, key=lambda c: c.name_ru.casefold())


def source_for(settings: Settings, code: str) -> Path:
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
    источник = root / DEFAULT_SPACE / code / CURRENT_LINK
    if not источник.is_dir():
        raise DomainError(
            f"У чек-листа «{code}» нет опубликованного издания в хранилище {root} — "
            f"проверку по нему вести не по чему"
        )
    return источник


def pick(settings: Settings, code: str | None) -> BotChecklist:
    """Чек-лист, по которому начинается проверка, — или отказ, почему не он.

    Код не назван — годится, только если открыт ровно один: выбирать за
    аудитора, когда их несколько, значило бы угадывать. Назван, но уже не
    открыт (методист закрыл, пока аудитор смотрел на кнопки) — отказ, а не
    молчаливая подмена на соседний.
    """
    открыты = available(settings)
    if not открыты:
        raise DomainError(
            "Ни один чек-лист не открыт в боте — начать проверку не по чему. Чек-лист в бот "
            "открывает методист в админке: «Методика» → «Доступ в боте»"
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
