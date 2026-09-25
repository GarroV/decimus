"""Где ряд оценок разорван и почему (T349, #337).

Сводка по сети и история точки — ряды: распределение букв, лучшая и худшая
проверка, оценки одной точки одна под другой. Проверки в таком ряду могут быть
посчитаны по разным ценам, и до этой задачи никто об этом не предупреждал:
средняя по смешанному ряду выглядит совершенно правдоподобно. Это худший вид
ошибки — не падение, а цифра, которой верят.

**Признак строится по тому, что записано у проверки**, и оценку не пересчитывает
ничем: у каждой строки есть код чек-листа (T345) и издание методики (T169), а
цена этого издания читается из его файлов (`domain.shape`).

Две проверки складываются в один ряд, когда совпало и то и другое:

* **код чек-листа** — разные чек-листы несравнимы всегда. Это разные наборы
  пунктов: девелоперский аудит и аудит РНД не складываются в общую среднюю
  оттого, что ставка вычета у них случайно одинаковая;
* **оценочная форма издания** — ставки, пороги букв, доли зон и состав
  влияющих на оценку пунктов. Правка формулировки её не двигает, и ряд от
  такого переиздания не рвётся: иначе признак срабатывал бы на каждой
  опечатке, и читатель перестал бы его замечать.

**Незнание за сравнимость не выдаётся.** Издания, методики которого на машине
нет, сравнить не с чем — и сводка говорит об этом прямо, а не показывает целый
ряд там, где он может быть разорван.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from src.db.models import InspectionRow
from src.domain.shape import scoring_shape
from src.mcp.errors import ToolError
from src.mcp.letters import Papers, pinned, sources

#: Как признак называется в ответе. Имя одно на все инструменты: читателю
#: незачем узнавать, что «ряд разорван» в истории точки и в сводке по сети —
#: одно и то же поле, названное по-разному.
FIELD = "comparability"

ShapeReader = Callable[[str, str, Papers], "str | None"]


@dataclass(frozen=True)
class Group:
    """Отрезок ряда, внутри которого оценки считались одинаково."""

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
    из-за одной такой строки встать не имеет права, а «цену не установить» и
    есть правдивый ответ про неё.
    """
    try:
        найдено = pinned(version, papers)
    except ToolError:
        return None
    if найдено is None:
        return None
    каталог = найдено[0]
    return scoring_shape(каталог)


def _note(*, groups: Sequence[Group], unknown: bool) -> str:
    """Фраза для читателя. Пусто — значит сказать нечего, а не «всё хорошо».

    Английский здесь не выбор стиля: ответы инструментов читает агент партнёра,
    и весь остальной текст в них английский (`status`).
    """
    части: list[str] = []
    if len(groups) > 1:
        коды = {г.checklist_code for г in groups}
        причина = (
            "different checklists"
            if len(коды) > 1
            else "the scoring rules changed between editions"
        )
        части.append(
            f"These inspections were not scored the same way ({причина}): "
            f"{len(groups)} incomparable groups. Averaging or ranking across them is meaningless; "
            f"compare within a group."
        )
    if unknown:
        части.append(
            "For some editions the methodology is not on this machine, so their scoring rules "
            "could not be checked — treat those as unverified rather than comparable."
        )
    return " ".join(части)


def of(
    rows: Sequence[InspectionRow],
    *,
    papers: Papers | None = None,
    shape: ShapeReader | None = None,
) -> dict[str, object]:
    """Признак сравнимости ряда: чем он разорван и на какие отрезки.

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
            формы[version] = читать(version, row.checklist_code, бумаги)
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
    unknown = any(г.shape is None for г in groups)
    # Ряд короче двух строк складывать не из чего: разрыва в нём нет по
    # определению, и предупреждение о нём обесценивало бы то, которое важно.
    comparable = True if len(rows) < 2 else (len(groups) == 1 and not unknown)
    return {
        "comparable": comparable,
        "unknown": unknown and bool(rows),
        "groups": [г.as_dict() for г in groups],
        "note": _note(groups=groups, unknown=unknown) if rows else "",
    }
