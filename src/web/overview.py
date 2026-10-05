"""Экран «Обзор сети»: что показать и чем это взято.

Экран отвечает на один вопрос из брифа — **куда смотреть сегодня**. Поэтому он
собран не вокруг красивых чисел, а вокруг поводов: точка, где сожжена зона;
пункт, который нарушается на многих точках; проверка, по которой письмо так и
не ушло. Числа сверху нужны, чтобы понять масштаб, но они кликабельные и
сужают выборку — мёртвых цифр на экране нет.

НИ ОДНОЙ ЦИФРЫ СОБСТВЕННОГО ПРОИЗВОДСТВА, как и в соседнем модуле раздела
«Проверки». Процент и буква приходят такими, какими их записал движок; потери
по зонам складываются запросом из `by_zone`, куда их положил он же. Среднее по
сети — единственное вычисляемое число, и оно снабжено признаком сравнимости:
усреднять проверки, посчитанные по разным ставкам, нельзя, и экран об этом
говорит вслух, а не показывает бодрую цифру (T349).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, timedelta

from src.db import queries
from src.db.models import InspectionRow
from src.db.reach import Reach

from .pricing import price_key, price_key_of

#: Сколько поводов показывать в каждом списке. Экран — не отчёт: длинный
#: список поводов не помогает выбрать, куда смотреть, он эту задачу и создаёт.
TOP = 6
#: С какого числа точек нарушение пункта считается системным. Пункт на одной
#: точке — это одна точка, и её уже показывают «Проблемные точки».
SYSTEMIC_MIN_UNITS = 2

#: Класс, сжигающий долю зоны целиком. Живёт кодом, не словом (D025).
CRITICAL = "D3"


@dataclass(frozen=True)
class Tile:
    """Плитка сводки. `href` обязателен: цифра без перехода — мёртвая цифра.

    `delta` — движение числа против прошлого периода, уже готовой строкой со
    знаком. Пусто — движения не показываем: ни нуля, ни стрелки в никуда.
    Бриф требует у средней именно движение, а не голое число.
    """

    key: str
    value: str
    note: str
    href: str
    tone: str = "plain"
    delta: str = ""


@dataclass(frozen=True)
class ZoneLoss:
    """Потеря по зоне за период — сложенная, а не пересчитанная."""

    code: str
    name_ru: str
    name_en: str
    loss: float
    inspections: int
    units: int
    share: float


@dataclass(frozen=True)
class Systemic:
    """Пункт, нарушенный на нескольких точках.

    `text` — формулировка самой свежей записи этого пункта, а `lang` — язык
    РЕЧИ той проверки, где она записана. Язык носится рядом с текстом, потому
    что на экране интерфейса он другой, и показывать чужой язык молча нельзя.
    """

    code: str
    level: str
    records: int
    units: int
    text: str = ""
    lang: str = ""


@dataclass(frozen=True)
class Attention:
    """Повод посмотреть сегодня. `why` — код причины, не готовая фраза.

    Фразу собирает шаблон на языке интерфейса: причина одна, а языков у
    продукта два, и склеивать текст здесь значило бы печатать его мимо
    словаря.
    """

    why: str
    unit: str
    inspection_id: str
    when: date
    detail: str
    tone: str


@dataclass(frozen=True)
class Selection:
    """Чем сужена выборка. Везде КОДЫ, нигде формулировки (конституция, 5).

    Пустая строка означает «не сужено», а не «сужено пустым»: отсутствие
    фильтра и фильтр по пустому значению — разные выборки, и склеивать их
    нельзя. Период хранится кодом окна (`all`, `d30`, `d90`, `y1`), а не парой
    дат: подпись окна переводится, а его смысл — нет.
    """

    country: str = ""
    city: str = ""
    grade: str = ""
    period: str = "all"
    #: Чем сортировать таблицу точек — код порядка, не подпись.
    sort: str = "score"

    @property
    def narrowed(self) -> bool:
        """Сужена ли выборка хоть чем-нибудь — для кнопки «Сбросить»."""
        return bool(self.country or self.city or self.grade) or self.period != "all"


@dataclass(frozen=True)
class CityRow:
    """Строка разбивки: город, его точки и что с ними за период.

    Средняя считается по записанным процентам ровно так же, как по сети, и
    подчиняется тому же признаку сравнимости: ряд из разных изданий методики
    не усредняется вовсе (T349).
    """

    city: str
    country: str
    units: int
    inspections: int
    average: float | None
    comparable: bool
    grades: tuple[tuple[str, int], ...]
    critical: int
    #: Движение средней против такого же периода перед этим. `None` — не с
    #: чем сравнивать или сравнивать нельзя, и тогда на экране прочерк, а не
    #: ноль: ноль читался бы как «ничего не изменилось».
    delta: float | None = None


@dataclass(frozen=True)
class PointRow:
    """Точка выборки: её последняя проверка и куда она движется.

    `delta` — разница с предыдущей проверкой ТОЙ ЖЕ точки, и только если обе
    посчитаны одной ценой (`pricing`, #405): иначе это разница ставок, а не работы
    точки, и стрелка вниз соврала бы человеку прямо на главном экране.
    """

    unit: str
    city: str
    country: str
    inspection_id: str
    when: date
    grade: str
    pct: float
    delta: float | None
    worst_zone_ru: str
    worst_zone_en: str
    critical: int
    #: Почему точка попала в проблемные — КОДОМ причины, не готовой фразой:
    #: причина одна, а языков у продукта два. Пусто — точка не проблемная.
    why: str = ""


@dataclass(frozen=True)
class Overview:
    """Всё, что показывает экран, одним снимком."""

    units_total: int
    inspections: tuple[InspectionRow, ...]
    grades: tuple[tuple[str, int], ...]
    average: float | None
    comparable: bool
    zone_losses: tuple[ZoneLoss, ...]
    systemic: tuple[Systemic, ...]
    attention: tuple[Attention, ...]
    problems: tuple[PointRow, ...] = ()
    #: Движение средней против такого же периода перед этим. `None` — не с чем
    #: или нельзя сравнивать.
    average_delta: float | None = None
    #: Сколько точек выборки за период не проверяли ни разу. Знаменатель
    #: берётся из справочника: «проверено 12» без «из 150» — это не ответ.
    unchecked: int = 0
    selection: Selection = Selection()
    countries: tuple[tuple[str, int], ...] = ()
    cities: tuple[tuple[str, int], ...] = ()
    breakdown: tuple[CityRow, ...] = ()
    points: tuple[PointRow, ...] = ()
    #: `{название точки: идентификатор}` — чтобы строка таблицы вела в карточку
    #: точки. Экран берёт ВСЁ одним снимком: отдельный поход в базу из
    #: обработчика прошёл бы мимо подменяемого слоя и сломал бы проверки
    #: экрана, которые до базы не доходят.
    unit_ids: dict[str, str] = field(default_factory=dict)
    #: Срез за период больше предела ряда: ряд `inspections` и всё, что из него
    #: строится (таблицы точек и городов, поводы), взяты по последним `limit`
    #: проверкам среза. Плитки, буквы, потери и системные — по всему срезу
    #: (#503). Экран обязан сказать это вслух (#470).
    truncated: bool = False
    #: Проверок и проверенных точек во ВСЁМ срезе (#503) — для плиток. Ряд
    #: `inspections` ограничен пределом, а плитки — нет.
    inspections_total: int = 0
    units_checked: int = 0
    #: Проверок среза с критическим нарушением — по ВСЕМУ срезу, из
    #: `class_counts` (#503). Список поводов `attention` — по ряду и до `TOP`.
    critical_total: int = 0


def _grades(rows: tuple[InspectionRow, ...]) -> tuple[tuple[str, int], ...]:
    """Распределение букв в порядке шкалы, а не по убыванию частоты.

    Порядок шкалы позволяет читать полосу как шкалу: A слева, D справа. При
    сортировке по частоте та же полоса меняет смысл от выборки к выборке.
    """
    счёт = {буква: 0 for буква in ("A", "B", "C", "D")}
    for row in rows:
        if row.grade in счёт:
            счёт[row.grade] += 1
    return tuple((буква, число) for буква, число in счёт.items())


@dataclass(frozen=True)
class _Summary:
    """Сводка всего среза из базы: то, о чём говорят плитки (#503)."""

    inspections: int
    units: int
    average: float | None
    grades: tuple[tuple[str, int], ...]
    #: Ключи цены (`price_key_of`) всех проверок среза — для сравнимости.
    prices: frozenset[tuple[str, str]]

    @property
    def comparable(self) -> bool:
        return len(self.prices) <= 1


_НИЧЕГО = _Summary(inspections=0, units=0, average=None, grades=(), prices=frozenset())


def _summary(
    *, reach: Reach, selection: Selection, date_from: date | None, date_to: date | None
) -> _Summary:
    """Средняя, буквы и счёт по всему срезу — агрегатом в базе, без предела ряда.

    Процент и буква — записанные движком; здесь они только складываются, как и
    раньше складывались по прочитанному ряду (`_average`, `_grades`).
    """
    точек, группы = queries.slice_summary(
        reach=reach,
        date_from=date_from,
        date_to=date_to,
        city=selection.city,
        country=selection.country,
        grade=selection.grade,
    )
    проверок = sum(группа[3] for группа in группы)
    счёт = {буква: 0 for буква in ("A", "B", "C", "D")}
    for группа in группы:
        if группа[2] in счёт:
            счёт[группа[2]] += группа[3]
    return _Summary(
        inspections=проверок,
        units=точек,
        average=round(sum(группа[4] for группа in группы) / проверок, 1) if проверок else None,
        grades=tuple(счёт.items()),
        prices=frozenset(price_key_of(группа[0], группа[1]) for группа in группы),
    )


def _summary_movement(сейчас: _Summary, раньше: _Summary) -> float | None:
    """Движение средней всего среза против прошлого окна — по правилам `_movement`."""
    if сейчас.average is None or раньше.average is None:
        return None
    if len(сейчас.prices | раньше.prices) > 1:
        return None
    return round(сейчас.average - раньше.average, 1)


def _comparable(rows: tuple[InspectionRow, ...]) -> bool:
    """Можно ли усреднять этот ряд: все проверки одного чек-листа одной ценой.

    Сравнивается «код чек-листа + оценочная форма издания» (`pricing`, D187),
    а не имя издания: имя меняется и от правки формулировки, которая цену не
    двигает, и до #405 обзор отказывался считать среднюю по проверкам,
    посчитанным одинаково. Издания нет на машине — сравнивается его имя, то
    есть ряд рвётся в безопасную сторону (T349).
    """
    if len(rows) < 2:
        return True
    return len({price_key(row) for row in rows}) == 1


def _average(rows: tuple[InspectionRow, ...]) -> float | None:
    """Среднее по записанным процентам. `None` — считать нечего.

    Ноль вместо `None` читался бы как «сеть на нуле», а не как «проверок нет».
    """
    if not rows:
        return None
    return round(sum(row.pct for row in rows) / len(rows), 1)


def _attention(
    rows: tuple[InspectionRow, ...], *, counts: dict[str, dict[str, int]]
) -> tuple[Attention, ...]:
    """Поводы посмотреть сегодня, самое срочное сверху.

    Сегодня поводов два вида, и оба берутся из записанного: сожжённая зона
    (`D3` в счётчиках проверки) и проверка, у которой нет ни одной находки при
    низкой букве — признак, что проверку прервали. Просроченных предписаний
    здесь нет, потому что предписаний нет в базе вовсе (T357): выдумывать их
    строки означало бы показать владельцу работу, которой не было.
    """
    поводы: list[Attention] = []
    for row in rows:
        критических = counts.get(row.id, {}).get(CRITICAL, 0)
        if критических:
            поводы.append(
                Attention(
                    why="critical",
                    unit=row.unit_name,
                    inspection_id=row.id,
                    when=row.inspection_date,
                    detail=str(критических),
                    tone="err",
                )
            )
        elif row.grade == "D":
            поводы.append(
                Attention(
                    why="low_grade",
                    unit=row.unit_name,
                    inspection_id=row.id,
                    when=row.inspection_date,
                    detail=f"{row.pct:.1f}",
                    tone="warn",
                )
            )
    поводы.sort(key=lambda п: (п.tone != "err", -п.when.toordinal()))
    return tuple(поводы[:TOP])


#: Окна периода кодом: подпись окна переводится, число дней — нет.
#: `all` намеренно первый и означает «не сужать»: обзор сети без выбранного
#: периода обязан показывать всё, а не молча последний месяц.
PERIODS: dict[str, int | None] = {"all": None, "d30": 30, "d90": 90, "y1": 365}


def window(period: str, *, today: date) -> tuple[date | None, date | None]:
    """Границы окна по его коду. Неизвестный код — то же, что «всё время».

    Отказом это делать нельзя: код периода приходит из адресной строки, и
    опечатка в ней не повод показать человеку страницу ошибки вместо сети.
    """
    дней = PERIODS.get(period)
    if дней is None:
        return None, None
    return today - timedelta(days=дней), today


def window_before(period: str, *, today: date) -> tuple[date | None, date | None]:
    """Окно такой же длины, стоящее сразу перед текущим.

    Нужно ровно для одного: сказать, куда сеть движется. Сравнивать месяц с
    «всем временем» бессмысленно, поэтому у периода «всё время» предыдущего
    окна нет вовсе — и движение тогда не показывается, а не выдумывается.
    """
    дней = PERIODS.get(period)
    if дней is None:
        return None, None
    конец = today - timedelta(days=дней + 1)
    return конец - timedelta(days=дней), конец


def _movement(сейчас: tuple[InspectionRow, ...], раньше: tuple[InspectionRow, ...]) -> float | None:
    """Насколько средняя сдвинулась. `None` — сравнивать нечего или нельзя.

    Нельзя — это когда хоть один из двух рядов посчитан разными изданиями
    методики или когда ряды посчитаны РАЗНЫМИ изданиями между собой: тогда
    разница показывает смену ставок, а не работу сети (T349).
    """
    если_сейчас, если_раньше = _average(сейчас), _average(раньше)
    if если_сейчас is None or если_раньше is None:
        return None
    if not _comparable(сейчас) or not _comparable(раньше) or not _comparable(сейчас + раньше):
        return None
    return round(если_сейчас - если_раньше, 1)


def _by_city(
    rows: tuple[InspectionRow, ...], *, geo: dict[str, tuple[str, str]]
) -> dict[tuple[str, str], list[InspectionRow]]:
    """Разложить ряд по городам. Отдельно — потому что то же нужно прошлому окну."""
    разложено: dict[tuple[str, str], list[InspectionRow]] = {}
    for row in rows:
        country, city = geo.get(row.unit_name, ("", ""))
        разложено.setdefault((country, city), []).append(row)
    return разложено


def _breakdown(
    rows: tuple[InspectionRow, ...],
    *,
    geo: dict[str, tuple[str, str]],
    counts: dict[str, dict[str, int]],
    before: tuple[InspectionRow, ...] = (),
) -> tuple[CityRow, ...]:
    """Разбивка выборки по городам, крупные города сверху.

    Точка без города попадает в отдельную строку с пустым названием, а не
    выбрасывается: «в разбивке 40 точек, а в сети 150» — это вопрос к
    справочнику, и экран обязан его задать, а не спрятать.
    """
    по_городам = _by_city(rows, geo=geo)
    было_по_городам = _by_city(before, geo=geo)
    строки = [
        CityRow(
            city=city,
            country=country,
            units=len({row.unit_name for row in ряд}),
            inspections=len(ряд),
            average=_average(tuple(ряд)),
            comparable=_comparable(tuple(ряд)),
            grades=_grades(tuple(ряд)),
            critical=sum(counts.get(row.id, {}).get(CRITICAL, 0) for row in ряд),
            delta=_movement(tuple(ряд), tuple(было_по_городам.get((country, city), ()))),
        )
        for (country, city), ряд in по_городам.items()
    ]
    строки.sort(key=lambda с: (-с.units, -с.inspections, с.city))
    return tuple(строки)


def _points(
    rows: tuple[InspectionRow, ...],
    *,
    geo: dict[str, tuple[str, str]],
    counts: dict[str, dict[str, int]],
    worst: dict[str, tuple[str, str, str, float]],
) -> tuple[PointRow, ...]:
    """Точки выборки: у каждой — её последняя проверка и движение оценки.

    Ряд приходит отсортированным по дате убыванием, поэтому первая встреченная
    проверка точки и есть последняя, а вторая — та, с которой считается
    движение. Пересортировывать здесь нечего: порядок задан запросом.
    """
    последние: dict[str, InspectionRow] = {}
    предыдущие: dict[str, InspectionRow] = {}
    for row in rows:
        if row.unit_name not in последние:
            последние[row.unit_name] = row
        elif row.unit_name not in предыдущие:
            предыдущие[row.unit_name] = row
    точки: list[PointRow] = []
    for имя, row in последние.items():
        country, city = geo.get(имя, ("", ""))
        было = предыдущие.get(имя)
        сравнимо = было is not None and price_key(было) == price_key(row)
        зона = worst.get(row.id, ("", "", "", 0.0))
        точки.append(
            PointRow(
                unit=имя,
                city=city,
                country=country,
                inspection_id=row.id,
                when=row.inspection_date,
                grade=row.grade,
                pct=row.pct,
                delta=round(row.pct - было.pct, 1) if сравнимо and было else None,
                worst_zone_ru=зона[1],
                worst_zone_en=зона[2],
                critical=counts.get(row.id, {}).get(CRITICAL, 0),
            )
        )
    точки.sort(key=lambda т: (т.pct, т.unit))
    return tuple(точки)


#: Экран без единого выбранного чипа. Значение одно на модуль: отбор
#: неизменяемый, и создавать его заново на каждый вызов незачем.
БЕЗ_ОТБОРА = Selection()


#: Порядки таблицы точек: код → как сортировать. Порядок объявлен здесь, а
#: не в шаблоне, потому что подпись переводится, а правило сортировки нет.
#: `score` первый и он же умолчание: экран отвечает на вопрос «куда смотреть»,
#: и худшее должно стоять сверху, пока человек не попросил иначе.
ПОРЯДКИ: dict[str, object] = {
    "score": lambda т: (т.pct, т.unit),
    "delta": lambda т: (т.delta if т.delta is not None else 0.0, т.unit),
    "date": lambda т: (-т.when.toordinal(), т.unit),
    "unit": lambda т: (т.unit.lower(), т.unit),
}


def sorted_points(points: tuple[PointRow, ...], sort: str) -> tuple[PointRow, ...]:
    """Отсортировать точки выбранным порядком. Непонятный код — умолчание.

    Отказ здесь был бы не к месту: код порядка приходит из адресной строки,
    а опечатка в ней не повод показать страницу ошибки вместо сети.
    """
    ключ = ПОРЯДКИ.get(sort) or ПОРЯДКИ["score"]
    return tuple(sorted(points, key=ключ))  # type: ignore[call-overload]


#: Ниже этой буквы точка попадает в проблемные сама по себе. Буквы — коды
#: шкалы методики, порог здесь только для отбора на экран и оценку не трогает.
СЛАБЫЕ_БУКВЫ = ("C", "D")


def _problems(points: tuple[PointRow, ...]) -> tuple[PointRow, ...]:
    """Точки, к которым есть вопрос, и КАКОЙ именно — по убыванию срочности.

    Отбор по причине, а не по низу сортировки. «Шесть худших по проценту» —
    это всегда шесть строк, даже когда в сети всё хорошо, и человек привыкает
    читать список как шум. Список по причинам бывает пустым, и это тоже ответ:
    поводов нет.

    Причины в порядке веса: сожжённая зона (класс D3), падение против прошлой
    сравнимой проверки, слабая буква. Первая сработавшая и записывается —
    точке незачем объяснять три раза.
    """
    отобранные: list[PointRow] = []
    for точка in points:
        if точка.critical:
            причина = "critical"
        elif точка.delta is not None and точка.delta < 0:
            причина = "dropped"
        elif точка.grade in СЛАБЫЕ_БУКВЫ:
            причина = "low_grade"
        else:
            continue
        отобранные.append(replace(точка, why=причина))
    порядок = {"critical": 0, "dropped": 1, "low_grade": 2}
    отобранные.sort(key=lambda т: (порядок[т.why], т.delta or 0, т.pct))
    return tuple(отобранные[:TOP])


def _units_in(geo: dict[str, tuple[str, str]], *, selection: Selection) -> int | None:
    """Точек справочника в выбранном месте; `None` — место не выбрано, считать всю сеть.

    Буква здесь не участвует: она свойство проверки, а не точки. Без этого
    «Обзор» с Грузией показывал «точек 151, не проверено 147» при четырёх
    грузинских точках, проверенных все (#380).
    """
    if not selection.country and not selection.city:
        return None
    return sum(
        1
        for country, city in geo.values()
        if (not selection.country or country == selection.country)
        and (not selection.city or city == selection.city)
    )


def _geo_choices(
    geo: dict[str, tuple[str, str]], *, selection: Selection
) -> tuple[tuple[tuple[str, int], ...], tuple[tuple[str, int], ...]]:
    """Варианты чипов «страна» и «город» с числом точек, самые крупные первыми.

    Города — только выбранной страны: список, где рядом с Анталией стоит
    Тбилиси при выбранной Турции, предлагает заведомо пустую выборку.
    """
    страны: dict[str, int] = {}
    города: dict[str, int] = {}
    for country, city in geo.values():
        if country:
            страны[country] = страны.get(country, 0) + 1
        if city and (not selection.country or country == selection.country):
            города[city] = города.get(city, 0) + 1

    def по_весу(счёт: dict[str, int]) -> tuple[tuple[str, int], ...]:
        return tuple(sorted(счёт.items(), key=lambda п: (-п[1], п[0])))

    return по_весу(страны), по_весу(города)


def _slice(
    *,
    reach: Reach,
    limit: int,
    selection: Selection,
    date_from: date | None,
    date_to: date | None,
) -> tuple[tuple[InspectionRow, ...], bool]:
    """Ряд проверок среза и признак, что он длиннее предела.

    Отбор по месту и букве едет В ЗАПРОС, до предела (#470): поверх сотни
    свежих по всей сети страна, чьи проверки старше сотой, получала бы неполный
    ряд. Читается на одну строку больше предела — так обрезка видна, а не
    угадывается по ровному числу.
    """
    ряд = queries.list_inspections(
        reach=reach,
        limit=limit + 1,
        date_from=date_from,
        date_to=date_to,
        city=selection.city,
        country=selection.country,
        grade=selection.grade,
    )
    return tuple(ряд[:limit]), len(ряд) > limit


def load(
    *,
    reach: Reach,
    limit: int,
    selection: Selection = БЕЗ_ОТБОРА,
    today: date | None = None,
) -> Overview:
    """Снимок сети за период. Один проход по базе на каждый блок, не по строке."""
    date_from, date_to = window(selection.period, today=today or date.today())
    # Отбор человека едет В БАЗУ, а не применяется поверх ответа. Иначе блоки,
    # которые считаются запросом (потери по зонам, системные нарушения),
    # показывают сеть целиком, пока соседние блоки на том же экране показывают
    # выбранный город, — и ни один из них не сообщает, что говорит о другом
    # множестве. Найдено сверкой экрана: «Белград + буква D» давал пустую
    # таблицу точек и полный список потерь всей сети.
    узко = {
        "city": selection.city,
        "country": selection.country,
        "grade": selection.grade,
    }
    охват = reach
    geo = queries.unit_geography(reach=охват)
    ид_точек = queries.unit_ids(reach=охват)
    counts = queries.class_counts(reach=охват, date_from=date_from, date_to=date_to, **узко)
    worst = queries.worst_zones(reach=охват, date_from=date_from, date_to=date_to, **узко)
    rows, обрезан = _slice(
        reach=охват, limit=limit, selection=selection, date_from=date_from, date_to=date_to
    )
    # Прошлое окно читается ТОЛЬКО ради движения и только когда период задан:
    # у «всего времени» предыдущего окна не существует, и лишний поход в базу
    # на каждом открытии экрана был бы платой ни за что.
    было_от, было_до = window_before(selection.period, today=today or date.today())
    было, было_обрезано = (
        _slice(reach=охват, limit=limit, selection=selection, date_from=было_от, date_to=было_до)
        if было_от is not None
        else ((), False)
    )
    сводка = _summary(reach=охват, selection=selection, date_from=date_from, date_to=date_to)
    сводка_было = (
        _summary(reach=охват, selection=selection, date_from=было_от, date_to=было_до)
        if было_от is not None
        else _НИЧЕГО
    )
    точки = _points(rows, geo=geo, counts=counts, worst=worst)
    losses = queries.zone_losses(
        reach=охват, date_from=date_from, date_to=date_to, limit=TOP, **узко
    )
    всего = sum(строка[3] for строка in losses) or 1.0
    страны, города = _geo_choices(geo, selection=selection)
    в_месте = _units_in(geo, selection=selection)
    всего_точек = queries.units_total(reach=охват) if в_месте is None else в_месте
    return Overview(
        units_total=всего_точек,
        unit_ids=ид_точек,
        inspections=rows,
        grades=сводка.grades,
        average=сводка.average,
        comparable=сводка.comparable,
        zone_losses=tuple(
            ZoneLoss(
                code=code,
                name_ru=ru,
                name_en=en,
                loss=loss,
                inspections=insp,
                units=units,
                share=round(loss / всего * 100, 1),
            )
            for code, ru, en, loss, insp, units in losses
        ),
        systemic=tuple(
            Systemic(code=code, level=level, records=records, units=units, text=text, lang=lang)
            for code, level, records, units, text, lang in queries.systemic_findings(
                reach=охват, date_from=date_from, date_to=date_to, limit=TOP, **узко
            )
            # Запрос отдаёт пункты по убыванию числа точек, поэтому отсев после
            # предела не теряет ни одного системного.
            if units >= SYSTEMIC_MIN_UNITS
        ),
        attention=_attention(rows, counts=counts),
        problems=_problems(точки),
        average_delta=_summary_movement(сводка, сводка_было),
        # Точки справочника, по которым за период нет ни одной проверки.
        # Считается от того же справочника, что и знаменатель плитки: иначе
        # «не проверено» и «всего» пришли бы из разных мест и разошлись.
        unchecked=max(всего_точек - сводка.units, 0),
        selection=selection,
        countries=страны,
        cities=города,
        breakdown=_breakdown(rows, geo=geo, counts=counts, before=было),
        points=sorted_points(точки, selection.sort),
        truncated=обрезан or было_обрезано,
        inspections_total=сводка.inspections,
        units_checked=сводка.units,
        critical_total=sum(1 for классы in counts.values() if классы.get(CRITICAL)),
    )
