"""Чек-листы как сущности: перечень, заведение с нуля, состояние, применение к проду.

Соседний модуль (`checklist.py`) правит методику ВНУТРИ чек-листа — пункты,
зоны, издания. Здесь работа уровнем выше: какие чек-листы вообще есть, как
завести новый и по какому из них идут проверки. Разведены они потому, что это
разные сущности: издание — снимок методики, чек-лист — то, у чего бывают
издания.

**Заведение идёт из бланка, а не копией.** Снимком боевой методики заводится
только первый чек-лист — для второго её брать неоткуда и незачем: копия чужого
эталона под своим кодом расходится с оригиналом с первой же правки, а выглядит
как он. Бланк лежит в репозитории ДАННЫМИ (`checklist-blank/`): его правка
меняет то, с чего начинаются новые чек-листы, и не трогает ни одного
существующего.

**Заслоны стоят на применении к проду, а не на проверке методики** (#339).
Пустой чек-лист — заголовок без вопросов и одна зона на 100% — проходит
`validate`, `init` и `score`, и даёт партнёру 100% и высшую оценку, не задав ни
одного вопроса. То есть сбой выходит наружу не ошибкой, а хорошей новостью.
Для черновика «вопросов 0» законно, поэтому отказывать обязано именно
применение.
"""

from __future__ import annotations

import csv
import json
import os
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

# Чтение карточки, издания и годности к боту — ярусом ниже (#455): по тем же
# правилам выбирает чек-лист бот, а звать `src.mcp` ему нельзя.
from ..domain.checklist_store import (
    BOT_BLOCK_DRAFT as BOT_BLOCK_DRAFT,
)
from ..domain.checklist_store import (
    BOT_BLOCK_EMPTY as BOT_BLOCK_EMPTY,
)
from ..domain.checklist_store import (
    BOT_BLOCK_RETIRED as BOT_BLOCK_RETIRED,
)
from ..domain.checklist_store import (
    BOT_BLOCK_UNPUBLISHED as BOT_BLOCK_UNPUBLISHED,
)
from ..domain.checklist_store import bot_block as _store_bot_block
from ..domain.checklist_store import count_violations as _violations
from ..domain.checklist_store import meta_or_default as _meta_or_default
from ..domain.checklist_store import published_edition as _published_edition
from ..domain.config import DATA_FILES, REQUIRED_DATA_FILES
from ..domain.version import VERSION_FILE, compose
from ..report.engine_call import REPO_ROOT, VERSIONS_DIR
from .checklist import (
    _engine_accepts,
    _holder,
    _journal,
    _point_at,
    _version_dir,
    current_version,
    tip_version,
)
from .checklist_layout import (
    ACTIVE,
    DEFAULT_CODE,
    DEFAULT_SPACE,
    DRAFT,
    RETIRED,
    Meta,
    Store,
    applied,
    check_slug,
    check_state,
    in_bot_of,
    known,
    point_prod_at,
    read_meta,
    write_meta,
)
from .errors import ChecklistError

#: Бланк методики: с него рождается новый чек-лист. Лежит в репозитории, а не в
#: каталоге методики (`AUDIT_DATA_DIR`): методика живёт вне git (D002), а бланк
#: обязан приезжать с кодом — иначе завести чек-лист можно было бы не на всякой
#: машине.
BLANK_DIR = REPO_ROOT / "checklist-blank"


@dataclass(frozen=True)
class Overview:
    """Чек-лист, как его видит перечень: чем связан, как называется, что с ним."""

    space: str
    code: str
    name_ru: str
    name_en: str
    state: str
    in_production: bool
    version: str | None
    #: Доступен аудиторам в боте (волна 3): флаг карточки и «в работе».
    in_bot: bool = False


def _signed(note: str, by: str | None) -> str:
    """Дописать к записи журнала того, кто это сделал.

    Кто именно — знает только дверь, через которую пришли: у агента это код
    арендатора, у экрана — логин вошедшего (`web:<логин>`). Ролей в продукте
    нет (D182), поэтому разбор «кто применил не тот чек-лист» держится ровно
    на этой строке.
    """
    return note if not by else f"{note}; {by}"


def _alive(store: Store) -> None:
    """Завести хранилище, если его ещё не заводили. Непустое не трогается вовсе.

    Нулевым изданием в пустом хранилище ложится та методика, по которой продукт
    считает сегодня, — тем же ходом, что у изданий (`_ensure`). Без этого
    первое же действие на живой площадке отвечало бы «чек-листа bizdev нет»,
    стоя на его методике ногами.

    Заводится ТОЛЬКО пустое: в непустом второй чек-лист рождается с нуля из
    бланка, а не молчаливой копией соседа.
    """
    if not known(store.root):
        current_version(replace(store, space=DEFAULT_SPACE, code=DEFAULT_CODE))


def overview(store: Store, *, spaces: tuple[str, ...] | None = None) -> list[Overview]:
    """Все чек-листы хранилища. Нетронутое хранилище заводится здесь же.

    `spaces` не назван — виден весь перечень (старое поведение); назван — перечень
    сужается до этих пространств: так бот партнёра не покажет чужие чек-листы.
    """
    _alive(store)
    в_проде = applied(store.root)
    ответ: list[Overview] = []
    for space, code in known(store.root):
        if spaces is not None and space not in spaces:
            continue
        свой = replace(store, space=space, code=code)
        карточка = _meta_or_default(свой)
        ответ.append(
            Overview(
                space=space,
                code=code,
                name_ru=карточка.name_ru,
                name_en=карточка.name_en,
                state=карточка.state,
                in_production=в_проде == (space, code),
                version=_published_edition(свой),
                in_bot=in_bot_of(карточка, space, code, в_проде),
            )
        )
    return ответ


@dataclass(frozen=True)
class Summary:
    """Чек-лист коротко — чтобы человек увидел, ЧТО он меняет, до того как поменял.

    Ролей в продукте нет (D182), и ошибку применения ловит экран, а не право:
    круг людей узкий, риск здесь не злой умысел, а промах, а от промаха право
    не спасает — у ошибающегося оно как раз есть. Поэтому сводка обязана
    называть цифры, по которым промах виден: сколько вопросов, какие зоны и с
    какими долями, по каким ставкам считается вычет.
    """

    checklist: str
    name_ru: str
    name_en: str
    version: str | None
    items: int
    zones: tuple[tuple[str, float], ...]
    penalty: tuple[tuple[str, float], ...]
    start_pct: float


def _zones(каталог: Path) -> tuple[tuple[str, float], ...]:
    """Зоны издания с долями, в файловом порядке."""
    путь = каталог / "zones.csv"
    if not путь.is_file():
        return ()
    with путь.open(encoding="utf-8-sig", newline="") as f:
        строки = list(csv.DictReader(f))
    собранные: list[tuple[str, float]] = []
    for строка in строки:
        код = (строка.get("code") or "").strip()
        доля = (строка.get("share_pct") or "").strip()
        if код:
            собранные.append((код, float(доля) if доля else 0.0))
    return tuple(собранные)


def _rates(каталог: Path) -> tuple[float, tuple[tuple[str, float], ...]]:
    """Начальный процент и ставки вычета из `scoring.json`.

    Читается ФАЙЛ, а не пересчитывается оценка: второй экземпляр арифметики
    здесь запрещён под любым видом — проценты, буква и разбивка приходят
    только из `audit.py score`.
    """
    путь = каталог / "scoring.json"
    if not путь.is_file():
        return (0.0, ())
    тело = json.loads(путь.read_text(encoding="utf-8"))
    ставки = тело.get("penalty") or {}
    собранные = tuple((str(класс), float(значение)) for класс, значение in sorted(ставки.items()))
    return (float(тело.get("start_pct") or 0.0), собранные)


def summary(store: Store) -> Summary | None:
    """Сводка чек-листа по его опубликованному изданию. Нет издания — `None`."""
    _alive(store)
    карточка = read_meta(store)
    издание = _published_edition(store)
    if карточка is None or издание is None:
        return None
    каталог = _version_dir(store, издание)
    начало, ставки = _rates(каталог)
    return Summary(
        checklist=store.code,
        name_ru=карточка.name_ru,
        name_en=карточка.name_en,
        version=издание,
        items=_violations(каталог),
        zones=_zones(каталог),
        penalty=ставки,
        start_pct=начало,
    )


def difference(store: Store) -> tuple[Summary | None, Summary | None]:
    """«Сейчас в проде вот этот, будет вот этот» — пара сводок для показа.

    Первая может быть `None` (к проду не применён никто), вторая — если у
    чек-листа нет опубликованного издания. Обе пустые разом означают, что
    показывать нечего, и экран обязан сказать это словами, а не пустой
    таблицей.
    """
    в_проде = applied(store.root)
    сейчас = None
    if в_проде is not None:
        space, code = в_проде
        сейчас = summary(replace(store, space=space, code=code))
    return (сейчас, summary(store))


def create(
    store: Store,
    *,
    tenant: str,
    name_ru: str,
    name_en: str,
    by: str | None = None,
    today: date | None = None,
) -> Overview:
    """Завести чек-лист с нуля из бланка. Рождается черновиком и к проду не идёт.

    Черновиком, а не «в работе», намеренно: только что заведённый чек-лист не
    задаёт ни одного вопроса, и пометить его годным к употреблению значило бы
    предложить считать по нему проверку.

    Хранилище оживляется ПЕРЕД заведением, и это не формальность: если первым
    же действием на нетронутом хранилище завести новый чек-лист, боевая
    методика не попадёт в него вовсе, а к проду не окажется применён никто —
    экран состава после этого отвечал бы «чек-листа bizdev нет», стоя на его
    файлах ногами (поймано прогоном экрана 22.09).
    """
    _alive(store)
    space = check_slug(store.space, что="Код пространства")
    code = check_slug(store.code, что="Код чек-листа")
    свой = replace(store, space=space, code=code)
    if свой.home.exists():
        raise ChecklistError(
            f"Чек-лист «{code}» в пространстве «{space}» уже есть. Код не меняется никогда — им "
            f"чек-лист связан с проверками и со снимками изданий; заведите другой код",
            refusal="checklist_exists",
            params={"code": code, "space": space},
        )
    # Коды эталона и чек-листов партнёров не повторяются: партнёр видит эталон
    # рядом со своими (`bot_spaces`), и совпавший код сделал бы поиск по коду
    # неоднозначным.
    занят = [s for s, c in known(store.root) if c == code and s != space]
    if space != DEFAULT_SPACE and DEFAULT_SPACE in занят:
        raise ChecklistError(
            f"Код «{code}» — код чек-листа эталона УК. Эталон виден в вашем пространстве "
            f"под этим кодом; заведите свой чек-лист под другим кодом",
            refusal="code_is_reference",
            params={"code": code},
        )
    if space == DEFAULT_SPACE and занят:
        raise ChecklistError(
            f"Код «{code}» занят чек-листом пространства партнёра. Коды эталона и "
            f"чек-листов партнёров не повторяются: партнёр видит эталон рядом со своими",
            refusal="code_taken_by_partner",
            params={"code": code},
        )
    имя_ру, имя_ен = (name_ru or "").strip(), (name_en or "").strip()
    if not имя_ру or not имя_ен:
        raise ChecklistError(
            "У чек-листа должны быть оба названия — русское и английское: язык продукта это "
            "параметр, а не константа, и показывается чек-лист названием, а не кодом",
            refusal="names_required",
        )
    нет = [name for name in REQUIRED_DATA_FILES if not (BLANK_DIR / name).is_file()]
    if нет:
        raise ChecklistError(
            f"Бланк методики в репозитории неполный: не хватает {', '.join(нет)}. Новый чек-лист "
            f"рождается из него, и завести его не с чего",
            refusal="blank_incomplete",
            params={"missing": ", ".join(нет)},
        )

    day = today or date.today()
    with _holder(свой) as holder:
        кандидат = holder / "data"
        кандидат.mkdir(parents=True)
        for name in DATA_FILES:
            источник = BLANK_DIR / name
            if источник.is_file():
                (кандидат / name).write_bytes(источник.read_bytes())
        # Имя набора — код чек-листа: издание уезжает в базу к каждой проверке, и
        # по нему должно быть видно, чей это снимок.
        (кандидат / VERSION_FILE).write_text(f"{code} {day.isoformat()}\n", encoding="utf-8")
        отказ = _engine_accepts(кандидат, day)
        if отказ is not None:
            raise ChecklistError(
                f"Движок не принимает бланк методики — завести чек-лист с нуля нечем. Он сказал "
                f"так: {отказ}",
                refusal="blank_rejected",
                params={"engine": отказ},
            )
        издание = compose(кандидат, DATA_FILES)
        (свой.home / VERSIONS_DIR).mkdir(parents=True, exist_ok=True)
        цель = свой.home / VERSIONS_DIR / издание
        if not цель.is_dir():
            os.replace(кандидат, цель)

    _point_at(свой, издание)
    карточка = Meta(code=code, name_ru=имя_ру, name_en=имя_ен, state=DRAFT)
    write_meta(свой, карточка)
    _journal(
        свой,
        {
            "tenant": tenant,
            "tool": "create_checklist",
            "outcome": "accepted",
            "base_version": None,
            "version": издание,
            "refusal": None,
            "note": _signed(f"заведён с нуля из бланка, состояние {DRAFT}", by),
        },
    )
    return Overview(
        space=space,
        code=code,
        name_ru=имя_ру,
        name_en=имя_ен,
        state=DRAFT,
        in_production=False,
        version=издание,
    )


def rename(
    store: Store,
    *,
    tenant: str,
    name_ru: str | None,
    name_en: str | None,
    by: str | None = None,
) -> Overview:
    """Поменять названия чек-листа. Код не меняется ничем и никогда.

    Названия — формулировка: их переводят и правят. Код — связь: им чек-лист
    сцеплен с проверками в базе и со снимками изданий на полке, и смена кода
    оборвала бы обе связи молча.
    """
    _alive(store)
    карточка = read_meta(store)
    if карточка is None:
        raise ChecklistError(
            f"Чек-листа «{store.code}» в пространстве «{store.space}» нет. Перечень отдаёт "
            f"checklists",
            refusal="checklist_missing",
            params={"code": store.code, "space": store.space},
        )
    новая = replace(
        карточка,
        name_ru=(name_ru or карточка.name_ru).strip() or карточка.name_ru,
        name_en=(name_en or карточка.name_en).strip() or карточка.name_en,
    )
    write_meta(store, новая)
    _journal(
        store,
        {
            "tenant": tenant,
            "tool": "rename_checklist",
            "outcome": "accepted",
            "base_version": None,
            "version": None,
            "refusal": None,
            "note": _signed(f"названия: {новая.name_ru} / {новая.name_en}", by),
        },
    )
    return _overview_of(store, новая)


def set_state(store: Store, *, tenant: str, state: str, by: str | None = None) -> Overview:
    """Черновик / в работе / снят.

    Снять применённый к проду нельзя: по нему идут проверки, и «снят» означало
    бы, что продукт считает по снятой методике. Сначала применяется другой.
    """
    _alive(store)
    хотим = check_state(state)
    карточка = read_meta(store)
    if карточка is None:
        raise ChecklistError(
            f"Чек-листа «{store.code}» в пространстве «{store.space}» нет. Перечень отдаёт "
            f"checklists",
            refusal="checklist_missing",
            params={"code": store.code, "space": store.space},
        )
    в_проде = applied(store.root) == (store.space, store.code)
    if в_проде and хотим == RETIRED:
        raise ChecklistError(
            f"Чек-лист «{store.code}» применён к проду — по нему идут проверки, и снять его "
            f"значит считать по снятой методике. Сначала примените к проду другой",
            refusal="applied_cannot_retire",
            params={"code": store.code},
        )
    новая = replace(карточка, state=хотим)
    write_meta(store, новая)
    _journal(
        store,
        {
            "tenant": tenant,
            "tool": "set_checklist_state",
            "outcome": "accepted",
            "base_version": None,
            "version": None,
            "refusal": None,
            "note": _signed(f"состояние: {карточка.state} → {хотим}", by),
        },
    )
    return _overview_of(store, новая)


def _fit_for_inspections(store: Store) -> tuple[Meta, str, int]:
    """Годен ли чек-лист к проверкам — или отказ, почему нет (#339).

    Одни заслоны на два действия: применить к проду и открыть в боте. Они не
    про формат, а про смысл — годный по формату, но пустой чек-лист дал бы
    партнёру 100% и высшую оценку.
    """
    карточка = read_meta(store)
    if карточка is None:
        raise ChecklistError(
            f"Чек-листа «{store.code}» в пространстве «{store.space}» нет. Перечень отдаёт "
            f"checklists",
            refusal="checklist_missing",
            params={"code": store.code, "space": store.space},
        )
    if карточка.state == RETIRED:
        raise ChecklistError(
            f"Чек-лист «{store.code}» снят. Снятый к проду не применяется: его сняли потому, что "
            f"считать по нему больше не следует. Верните его в работу, если это ошибка",
            refusal="retired_not_applicable",
            params={"code": store.code},
        )
    издание = _published_edition(store)
    if издание is None:
        raise ChecklistError(
            f"У чек-листа «{store.code}» нет опубликованного издания — применять к проду нечего",
            refusal="no_published_edition",
            params={"code": store.code},
        )
    вопросов = _violations(_version_dir(store, издание))
    if вопросов == 0:
        raise ChecklistError(
            f"В чек-листе «{store.code}» нет ни одного пункта, по которому бывает нарушение. "
            f"Такой чек-лист считается без единого вопроса и даёт партнёру 100% и высшую "
            f"оценку — то есть сбой вышел бы наружу не ошибкой, а хорошей новостью. Заведите "
            f"пункты и примените снова",
            refusal="no_violation_items",
            params={"code": store.code},
        )
    return карточка, издание, вопросов


def apply_to_production(store: Store, *, tenant: str, by: str | None = None) -> dict[str, object]:
    """Применить чек-лист к проду: по нему пойдут проверки.

    Одно движение — перестановка верхнего указателя. Повторной сверки методики
    движком здесь нет: она уже прошла, когда издание создавалось. А вот заслоны
    есть, и они не про формат, а про смысл (#339).
    """
    _alive(store)
    if store.space != DEFAULT_SPACE:
        raise ChecklistError(
            "К проду применяет только УК: указатель прода один на всю сеть. "
            "В пространстве партнёра доступ в боте задаётся галочкой «в боте»",
            refusal="apply_only_reference",
        )
    карточка, издание, вопросов = _fit_for_inspections(store)
    прежний = applied(store.root)
    point_prod_at(store)
    if карточка.state == DRAFT:
        write_meta(
            store,
            replace(карточка, state=ACTIVE),
        )
    _journal(
        store,
        {
            "tenant": tenant,
            "tool": "apply_checklist",
            "outcome": "accepted",
            "base_version": None,
            "version": издание,
            "refusal": None,
            "note": _signed(f"применён к проду вместо {прежний[1] if прежний else 'ничего'}", by),
        },
    )
    return {
        "applied": store.code,
        "space": store.space,
        "previous": прежний[1] if прежний else None,
        "version": издание,
        "items": вопросов,
        "status": (
            f"checklist {store.code} is now the one inspections are scored against; inspections "
            f"already scored stay on their own checklist and version and are not recalculated"
        ),
    }


def _overview_of(store: Store, карточка: Meta) -> Overview:
    return Overview(
        space=store.space,
        code=store.code,
        name_ru=карточка.name_ru,
        name_en=карточка.name_en,
        state=карточка.state,
        in_production=applied(store.root) == (store.space, store.code),
        version=_published_edition(store),
        in_bot=in_bot_of(карточка, store.space, store.code, applied(store.root)),
    )


__all__ = [
    "BLANK_DIR",
    "Overview",
    "Summary",
    "apply_to_production",
    "create",
    "difference",
    "overview",
    "rename",
    "set_state",
    "summary",
]


# --- доступ в боте (волна 3) -------------------------------------------------


def bot_block(store: Store) -> str | None:
    """Код причины, по которой чек-лист нельзя открыть в боте, или `None`.

    Те же заслоны, что у `set_bot_access`, но без отказа: экран панели «Бот»
    показывает причину вместо переключателя, а не даёт нажать и отказывает.
    Само правило — ярусом ниже (`src/domain/checklist_store.py: bot_block`), им
    же выбирает чек-лист бот; здесь к нему добавлено одно уточнение, для
    которого нужен журнал правок.
    """
    причина = _store_bot_block(store, version_dir=_version_dir)
    if причина != BOT_BLOCK_EMPTY:
        return причина
    # Новый чек-лист рождается с опубликованным пустым бланком. Пункты,
    # записанные после, живут в неопубликованной версии — и сказать «нет
    # пунктов» человеку, который их только что завёл, значило бы соврать.
    издание = _published_edition(store)
    последняя = tip_version(store)
    if последняя != издание and _violations(_version_dir(store, последняя)) > 0:
        return BOT_BLOCK_UNPUBLISHED
    return BOT_BLOCK_EMPTY


def _settle_inherited(store: Store) -> None:
    """Записать всем карточкам их наследованный флаг — один раз, перед первым решением.

    Пока ни у одной карточки ключа нет, «в боте» определяет указатель `current`.
    Первое же явное решение по одному чек-листу иначе оставило бы остальным
    старый смысл, а он читается от указателя — и включение второго чек-листа
    молча сняло бы с бота первый. Поэтому до первой записи прежнее положение
    фиксируется у всех явным значением.

    Только в своём пространстве (Review Н18): иначе решение партнёра по своему
    чек-листу дописывало бы карточки эталона УК и соседних партнёров — правка
    не должна уходить дальше пространства, из которого пришла.
    """
    в_проде = applied(store.root)
    карточки = []
    for space, code in known(store.root):
        if space != store.space:
            continue
        свой = replace(store, space=space, code=code)
        карточка = read_meta(свой)
        if карточка is None:
            continue
        if карточка.in_bot is not None:
            return
        карточки.append((свой, карточка, в_проде == (space, code)))
    for свой, карточка, было in карточки:
        write_meta(свой, replace(карточка, in_bot=было))


def set_bot_access(store: Store, *, tenant: str, on: bool, by: str | None = None) -> Overview:
    """Открыть чек-лист аудиторам в боте или закрыть.

    Открыть можно только годный к проверкам и в работе (#339): черновик ещё
    правят, снятый считать не следует, пустой дал бы 100%. Закрыть можно любой,
    и последний тоже — тогда бот прямо скажет аудитору, что начать не по чему
    (спека, раздел «Бот»). Идущие проверки это не трогает: они считаются по
    снимку, снятому на старте.
    """
    _alive(store)
    if on:
        карточка, _, _ = _fit_for_inspections(store)
        if карточка.state != ACTIVE:
            raise ChecklistError(
                f"Чек-лист «{store.code}» — черновик. В бот открывается только чек-лист в работе: "
                f"черновик ещё правят, и аудитор получил бы вопросы, которых завтра не будет",
                refusal="draft_not_for_bot",
                params={"code": store.code},
            )
    else:
        есть = read_meta(store)
        if есть is None:
            raise ChecklistError(
                f"Чек-листа «{store.code}» в пространстве «{store.space}» нет. Перечень отдаёт "
                f"checklists",
                refusal="checklist_missing",
                params={"code": store.code, "space": store.space},
            )
        карточка = есть
    _settle_inherited(store)
    карточка = read_meta(store) or карточка
    новая = replace(карточка, in_bot=on)
    write_meta(store, новая)
    _journal(
        store,
        {
            "tenant": tenant,
            "tool": "set_bot_access",
            "outcome": "accepted",
            "base_version": None,
            "version": None,
            "refusal": None,
            "note": _signed("открыт в боте" if on else "закрыт в боте", by),
        },
    )
    return _overview_of(store, новая)
