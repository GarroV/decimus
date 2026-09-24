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

#: Сколько поводов показывать в каждом списке. Экран — не отчёт: длинный
#: список поводов не помогает выбрать, куда смотреть, он эту задачу и создаёт.
TOP = 6

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
    посчитаны одним изданием методики: иначе это разница ставок, а не работы
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
    comparability_note: str
    zone_losses: tuple[ZoneLoss, ...]
    systemic: tuple[Systemic, ...]
    attention: tuple[Attention, ...]
    problem_units: tuple[InspectionRow, ...]
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


def _comparable(rows: tuple[InspectionRow, ...]) -> bool:
    """Можно ли усреднять этот ряд: все проверки одного издания одного чек-листа.

    Сравнивается пара «код чек-листа + версия издания», и этого достаточно
    строго, а не приблизительно: имя издания выводится из СОДЕРЖИМОГО методики
    (`<набор>-<дата>-<отпечаток>`, D050), поэтому совпавшая версия означает
    совпавшие ставки, пороги букв и доли зон. Разошлась версия — цена могла
    смениться, и одно среднее по такому ряду было бы средним по несравнимому
    (T349).

    Тонкая форма признака — отпечаток именно ценообразующей части издания —
    живёт у поверхности агента (`src/mcp/comparability.py`) и сюда не тянется
    намеренно: веб не знает про `src.mcp` ничем, кроме двери методики, и это
    правило проверяется прогоном (`tests/test_web_bounds.py`). Разница в том,
    что здесь ряд рвётся и на правке формулировки, которая цену не двигает, —
    то есть эта проверка строже, а не слабее, и ошибается в безопасную
    сторону: отказывается усреднять там, где агент бы усреднил.
    """
    if len(rows) < 2:
        return True
    издания = {(row.checklist_code, row.checklist_version) for row in rows}
    return len(издания) == 1


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


def _fits(row: InspectionRow, *, selection: Selection, geo: dict[str, tuple[str, str]]) -> bool:
    """Попадает ли проверка в выборку. Сравнение по кодам, не по подписям."""
    country, city = geo.get(row.unit_name, ("", ""))
    if selection.country and country != selection.country:
        return False
    if selection.city and city != selection.city:
        return False
    if selection.grade and row.grade != selection.grade:
        return False
    return True


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
        сравнимо = было is not None and (было.checklist_code, было.checklist_version) == (
            row.checklist_code,
            row.checklist_version,
        )
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
    return tuple(sorted(points, key=ключ))  # type: ignore[arg-type,call-overload]


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


def load(
    *,
    tenant: str,
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
    geo = queries.unit_geography(tenant=tenant)
    ид_точек = queries.unit_ids(tenant=tenant)
    counts = queries.class_counts(tenant=tenant, date_from=date_from, date_to=date_to, **узко)
    worst = queries.worst_zones(tenant=tenant, date_from=date_from, date_to=date_to, **узко)
    весь_ряд = tuple(
        queries.list_inspections(tenant=tenant, limit=limit, date_from=date_from, date_to=date_to)
    )
    rows = tuple(row for row in весь_ряд if _fits(row, selection=selection, geo=geo))
    # Прошлое окно читается ТОЛЬКО ради движения и только когда период задан:
    # у «всего времени» предыдущего окна не существует, и лишний поход в базу
    # на каждом открытии экрана был бы платой ни за что.
    было_от, было_до = window_before(selection.period, today=today or date.today())
    было = (
        tuple(
            row
            for row in queries.list_inspections(
                tenant=tenant, limit=limit, date_from=было_от, date_to=было_до
            )
            if _fits(row, selection=selection, geo=geo)
        )
        if было_от is not None
        else ()
    )
    точки = _points(rows, geo=geo, counts=counts, worst=worst)
    losses = queries.zone_losses(
        tenant=tenant, date_from=date_from, date_to=date_to, limit=TOP, **узко
    )
    всего = sum(строка[3] for строка in losses) or 1.0
    страны: dict[str, int] = {}
    города: dict[str, int] = {}
    for country, city in geo.values():
        if country:
            страны[country] = страны.get(country, 0) + 1
        if city:
            города[city] = города.get(city, 0) + 1
    всего_точек = queries.units_total(tenant=tenant)
    return Overview(
        units_total=всего_точек,
        unit_ids=ид_точек,
        inspections=rows,
        grades=_grades(rows),
        average=_average(rows),
        comparable=_comparable(rows),
        comparability_note="",
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
                tenant=tenant, date_from=date_from, date_to=date_to, limit=TOP, **узко
            )
        ),
        attention=_attention(rows, counts=counts),
        problem_units=tuple(sorted(rows, key=lambda r: r.pct)[:TOP]),
        problems=_problems(точки),
        average_delta=_movement(rows, было),
        # Точки справочника, по которым за период нет ни одной проверки.
        # Считается от того же справочника, что и знаменатель плитки: иначе
        # «не проверено» и «всего» пришли бы из разных мест и разошлись.
        unchecked=max(всего_точек - len({row.unit_name for row in rows}), 0),
        selection=selection,
        countries=tuple(sorted(страны.items(), key=lambda п: (-п[1], п[0]))),
        cities=tuple(sorted(города.items(), key=lambda п: (-п[1], п[0]))),
        breakdown=_breakdown(rows, geo=geo, counts=counts, before=было),
        points=sorted_points(точки, selection.sort),
    )
