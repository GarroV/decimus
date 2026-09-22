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
)
from .checklist_layout import (
    ACTIVE,
    CURRENT_LINK,
    DEFAULT_CODE,
    DEFAULT_SPACE,
    DRAFT,
    RETIRED,
    Meta,
    Store,
    applied,
    check_slug,
    check_state,
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

#: Строка вида пункта, которая делает чек-лист способным что-то найти. Пункты
#: других видов (замеры, информационные) в оценке не участвуют, и чек-лист из
#: них одних даёт те же 100%, что пустой.
VIOLATION_KIND = "violation"


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


def _signed(note: str, by: str | None) -> str:
    """Дописать к записи журнала того, кто это сделал.

    Кто именно — знает только дверь, через которую пришли: у агента это код
    арендатора, у экрана — логин вошедшего (`web:<логин>`). Ролей в продукте
    нет (D182), поэтому разбор «кто применил не тот чек-лист» держится ровно
    на этой строке.
    """
    return note if not by else f"{note}; {by}"


def _meta_or_default(store: Store) -> Meta:
    """Карточка чек-листа или та, которой он был бы заведён.

    Карточки может не быть у хранилища, перенесённого руками. Отказывать на это
    нельзя: перечень чек-листов обязан показывать и такой, иначе человек не
    увидит, что у него на диске.
    """
    карточка = read_meta(store)
    if карточка is not None:
        return карточка
    return Meta(code=store.code, name_ru=store.code, name_en=store.code, state=ACTIVE)


def _published_edition(store: Store) -> str | None:
    """Опубликованное издание чек-листа — или `None`, если публиковать нечего."""
    указатель = store.home / CURRENT_LINK
    if not указатель.is_symlink():
        return None
    return Path(os.readlink(указатель)).name


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


def overview(store: Store) -> list[Overview]:
    """Все чек-листы хранилища. Нетронутое хранилище заводится здесь же."""
    _alive(store)
    в_проде = applied(store.root)
    ответ: list[Overview] = []
    for space, code in known(store.root):
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
            )
        )
    return ответ


def _violations(каталог: Path) -> int:
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
    """
    space = check_slug(store.space, что="Код пространства")
    code = check_slug(store.code, что="Код чек-листа")
    свой = replace(store, space=space, code=code)
    if свой.home.exists():
        raise ChecklistError(
            f"Чек-лист «{code}» в пространстве «{space}» уже есть. Код не меняется никогда — им "
            f"чек-лист связан с проверками и со снимками изданий; заведите другой код"
        )
    имя_ру, имя_ен = (name_ru or "").strip(), (name_en or "").strip()
    if not имя_ру or not имя_ен:
        raise ChecklistError(
            "У чек-листа должны быть оба названия — русское и английское: язык продукта это "
            "параметр, а не константа, и показывается чек-лист названием, а не кодом"
        )
    нет = [name for name in REQUIRED_DATA_FILES if not (BLANK_DIR / name).is_file()]
    if нет:
        raise ChecklistError(
            f"Бланк методики в репозитории неполный: не хватает {', '.join(нет)}. Новый чек-лист "
            f"рождается из него, и завести его не с чего"
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
                f"так: {отказ}"
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
            f"checklists"
        )
    новая = Meta(
        code=карточка.code,
        name_ru=(name_ru or карточка.name_ru).strip() or карточка.name_ru,
        name_en=(name_en or карточка.name_en).strip() or карточка.name_en,
        state=карточка.state,
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
            f"checklists"
        )
    в_проде = applied(store.root) == (store.space, store.code)
    if в_проде and хотим == RETIRED:
        raise ChecklistError(
            f"Чек-лист «{store.code}» применён к проду — по нему идут проверки, и снять его "
            f"значит считать по снятой методике. Сначала примените к проду другой"
        )
    новая = Meta(
        code=карточка.code, name_ru=карточка.name_ru, name_en=карточка.name_en, state=хотим
    )
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


def apply_to_production(store: Store, *, tenant: str, by: str | None = None) -> dict[str, object]:
    """Применить чек-лист к проду: по нему пойдут проверки.

    Одно движение — перестановка верхнего указателя. Повторной сверки методики
    движком здесь нет: она уже прошла, когда издание создавалось. А вот заслоны
    есть, и они не про формат, а про смысл (#339).
    """
    _alive(store)
    карточка = read_meta(store)
    if карточка is None:
        raise ChecklistError(
            f"Чек-листа «{store.code}» в пространстве «{store.space}» нет. Перечень отдаёт "
            f"checklists"
        )
    if карточка.state == RETIRED:
        raise ChecklistError(
            f"Чек-лист «{store.code}» снят. Снятый к проду не применяется: его сняли потому, что "
            f"считать по нему больше не следует. Верните его в работу, если это ошибка"
        )
    издание = _published_edition(store)
    if издание is None:
        raise ChecklistError(
            f"У чек-листа «{store.code}» нет опубликованного издания — применять к проду нечего"
        )
    вопросов = _violations(_version_dir(store, издание))
    if вопросов == 0:
        raise ChecklistError(
            f"В чек-листе «{store.code}» нет ни одного пункта, по которому бывает нарушение. "
            f"Такой чек-лист считается без единого вопроса и даёт партнёру 100% и высшую "
            f"оценку — то есть сбой вышел бы наружу не ошибкой, а хорошей новостью. Заведите "
            f"пункты и примените снова"
        )
    прежний = applied(store.root)
    point_prod_at(store)
    if карточка.state == DRAFT:
        write_meta(
            store,
            Meta(
                code=карточка.code,
                name_ru=карточка.name_ru,
                name_en=карточка.name_en,
                state=ACTIVE,
            ),
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
