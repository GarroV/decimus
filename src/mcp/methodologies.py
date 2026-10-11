"""Какими методиками оценены проверки ряда — справка, а не запрет (D352).

Сводка по сети и история точки — ряды: распределение букв, лучшая и худшая
проверка, оценки одной точки одна под другой. Проверки в ряду могут быть
оценены разными методиками: разные чек-листы, издания с другими пунктами и
весами, исторические проверки по методике того времени.

**Оценка каждой проверки верна по своей методике и принимается как есть**
(D352, отменяет T349/#337). Средние, рейтинги и движение по такому ряду
законны: методика будет меняться и дальше, и перекраивать ряд на каждой
смене никто не собирается. Поэтому поле — справка: на какие методики ряд
раскладывается, чтобы агент мог об этом сказать, если спросят. Запрета
усреднять в нём нет.

Группа — «код чек-листа + оценочная форма издания» (`domain.shape`, D218):
переиздание формулировок, не двигающее пункты и веса, новой группы не даёт.
Издания, чьей методики на машине нет, остаются группой по имени издания с
пустой формой. Историческая проверка (D332) — группа по своей метке.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from src.db.models import LEGACY_VERSION_PREFIX, InspectionRow
from src.domain.shape import scoring_shape
from src.mcp.errors import ToolError
from src.mcp.letters import Papers, pinned, sources

#: Как справка называется в ответе. Имя одно на все инструменты: читателю
#: незачем узнавать, что в истории точки и в сводке по сети это одно поле.
FIELD = "methodologies"

ShapeReader = Callable[[str, str, Papers], "str | None"]


@dataclass(frozen=True)
class Group:
    """Проверки ряда, оценённые одной методикой."""

    checklist_code: str
    #: Отпечаток цены или `None` — методики этого издания на машине нет.
    shape: str | None
    editions: tuple[str, ...]
    inspections: int

    def as_dict(self) -> dict[str, object]:
        return {
            "checklist_code": self.checklist_code,
            "scoring": self.shape,
            "editions": list(self.editions),
            "inspections": self.inspections,
        }


def shape_of(version: str, code: str, papers: Papers) -> str | None:
    """Цена издания или `None`, если её негде прочитать.

    Каталог ищет тот же `pinned`, которым собирается письмо по записанной
    проверке: издание может лежать в хранилище версий, в боевой методике или
    на полке снимков бота, и годным считается тот каталог, чьё содержимое и
    есть это издание.

    Негодное имя издания (испорченная строка в базе) — здесь не отказ: сводка
    из-за одной такой строки встать не имеет права.
    """
    try:
        найдено = pinned(version, papers)
    except ToolError:
        return None
    if найдено is None:
        return None
    каталог = найдено[0]
    return scoring_shape(каталог)


def _note(groups: Sequence[Group]) -> str:
    """Фраза для читателя. Пусто — ряд оценён одной методикой, говорить нечего.

    Английский здесь не выбор стиля: ответы инструментов читает агент партнёра,
    и весь остальной текст в них английский (`status`).
    """
    части: list[str] = []
    if len(groups) > 1:
        части.append(
            f"For reference: these inspections were scored under {len(groups)} methodologies "
            "(checklists or editions with different items and weights). Each score is correct "
            "under the methodology it was given by and is taken as recorded; averages, "
            "rankings and trends across all of them are valid."
        )
    if any((г.shape or "").startswith(LEGACY_VERSION_PREFIX) for г in groups):
        части.append(
            "Historical inspections keep the score of their old report, given under the "
            "methodology of that time; that score is accepted as true and never recomputed."
        )
    return " ".join(части)


def of(
    rows: Sequence[InspectionRow],
    *,
    papers: Papers | None = None,
    shape: ShapeReader | None = None,
) -> dict[str, object]:
    """Справка о методиках ряда: на какие группы он раскладывается.

    Цена каждого издания читается ОДИН раз на ряд, а не на строку: сводка по
    сети берёт сотни проверок, а изданий в них единицы — перечитывать методику
    на каждую строку значило бы упереться в диск на ровном месте.

    `papers` и `shape` открыты для проверки: первый — откуда брать каталоги
    методики, второй — чем считать цену.
    """
    бумаги = sources() if papers is None else papers
    читать = shape_of if shape is None else shape

    формы: dict[str, str | None] = {}
    собранные: dict[tuple[str, str | None], list[InspectionRow]] = {}
    for row in rows:
        version = row.checklist_version
        if version not in формы:
            # Историческая (D332): методики её издания в хранилище нет и не
            # будет — это прежняя методика по метке. Каждая метка — своя группа:
            # иначе все прежние методики слились бы в одну с изданиями, которых
            # просто нет на машине.
            формы[version] = (
                version if row.is_legacy else читать(version, row.checklist_code, бумаги)
            )
        ключ = (row.checklist_code, формы[version])
        собранные.setdefault(ключ, []).append(row)

    groups = [
        Group(
            checklist_code=код,
            shape=форма,
            editions=tuple(sorted({r.checklist_version for r in строки})),
            inspections=len(строки),
        )
        for (код, форма), строки in sorted(
            собранные.items(), key=lambda пара: (пара[0][0], пара[0][1] or "")
        )
    ]
    return {"groups": [г.as_dict() for г in groups], "note": _note(groups)}
