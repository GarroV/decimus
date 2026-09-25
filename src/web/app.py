"""Веб-админка управляющей компании: маршруты и сборка приложения.

Серверный рендеринг, синхронный код, тот же образ, что у бота и MCP (D148).
Flask выбран внутри этой рамки: WSGI и синхронные обработчики ложатся на
`psycopg` без слоя совместимости, шаблоны Jinja идут в комплекте, а сборщика и
Node не требуется вовсе — стиль приезжает готовым CSS из `forma` (D136).

**Признак «построен / не построен» сверяется на сборке.** `create_app` называет
`check_registry` ровно те разделы, под которые зарегистрировал настоящие
экраны. Реестр разошёлся с фактом — приложение не собирается (D138). Поэтому
дописать раздел и забыть снять ленту нельзя: забудешь — не поднимется.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from flask import Flask, redirect, render_template, request, url_for
from flask import Response as FlaskResponse
from werkzeug.wrappers import Response

from src.db import directory
from src.db.errors import DbError, MoveError, RetractionError
from src.db.models import InspectionRow
from src.domain.errors import ValidationError
from src.domain.kinds import kind_title

from . import accounts, assets, auth, letter_draft, view
from . import inspections as data
from . import methodology as method
from . import methodology_view as mview
from . import overview as overview_data
from . import unit_card as unit_data
from .config import Settings, load_settings
from .errors import MethodologyRefused
from .geo_names import city_title, country_title
from .origin import refuse_foreign_origin
from .sections import SECTIONS, check_registry, section, visible_sections
from .texts import UI_LANGS, lang_or_default, t

#: Сколько проверок читается в реестр за раз. Предел у чтения обязателен
#: (`queries.DEFAULT_LIMIT`), и здесь он назван явно, чтобы менять его правкой
#: одной строки, а не поиском по коду.
REGISTRY_LIMIT = 100

#: Предел размера тела запроса. Формы админки маленькие — самая крупная это
#: правленое письмо партнёру, — и неограниченное тело на странице, открытой
#: наружу, означало бы, что вошедший съедает память стенда одной отправкой.
#: Отказ на превышении даёт Flask сам, 413-м.
MAX_BODY_BYTES = 256 * 1024

#: Разделы, под которые в этом модуле зарегистрированы настоящие экраны.
#: Список сверяется с реестром при сборке — расхождение роняет приложение.
SCREENS = ("overview", "registry", "admin", "users")


def create_app(settings: Settings | None = None) -> Flask:
    """Собрать приложение. Отказ окружения — `WebConfigError` до первого запроса."""
    conf = settings or load_settings()
    check_registry(SCREENS)

    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_BODY_BYTES
    assets.install(app)
    _register_context(app, conf)
    # Заслон вешается ДО экранов и намеренно первым: `before_request` идёт в
    # порядке регистрации, и опознание обязано случиться раньше всего, что
    # ходит в базу за данными арендатора.
    auth.install(app, conf)
    _register_sections(app)
    _register_overview(app, conf)
    _register_units(app, conf)
    _register_registry(app, conf)
    letter_draft.install(app, conf)
    _register_methodology(app, conf)
    _mount_checklists(app, conf)
    _register_errors(app)
    _register_frame_ban(app)
    return app


def _lang(conf: Settings) -> str:
    """Язык этого запроса: `?lang=` поверх языка стенда.

    Язык — параметр, а не константа (`CLAUDE.md`), и переключатель в шапке
    делает это видимым, а не только объявленным. Непонятное значение в адресе
    страницу не роняет: это ввод снаружи, и на границе он приводится к
    допустимому.
    """
    return lang_or_default(request.args.get("lang"), fallback=conf.ui_lang)


def _register_context(app: Flask, conf: Settings) -> None:
    """Всё, что нужно каждому шаблону: язык, тексты, реестр разделов, тенант."""

    @app.context_processor
    def _context() -> dict[str, Any]:
        lang = _lang(conf)
        account = auth.current_account()
        return {
            "lang": lang,
            "langs": UI_LANGS,
            "t": lambda key, **params: t(key, lang, **params),
            # Страна и город в справочнике — коды; на экран они идут словом.
            "city_title": lambda code: city_title(code, lang),
            "country_title": lambda code: country_title(code, lang),
            # Разделы ОТФИЛЬТРОВАНЫ по роли, а не спрятаны разметкой:
            # ссылка, ведущая в отказ, выглядит как поломка продукта, а
            # проверка внутри шаблона расходится с заслоном на экране молча.
            "sections": visible_sections(account),
            "tenant": conf.tenant,
            "current_path": request.path,
            # Внутренние ссылки собираются ЭТИМ, а не склейкой строк в шаблоне.
            # Снаружи админка может жить под путём общего входа площадки
            # (`WEB_URL_PREFIX`), и тогда `request.path` — путь ВНУТРИ
            # приложения, без этого пути. Ссылка, собранная без него, уводит
            # человека в корень площадки, то есть в чужой продукт, который там
            # стоит: страница открывается, а первая же кнопка выносит наружу.
            "url": lambda path: f"{request.script_root}{path}",
            # Кто вошёл — берётся из того же ответа, что пропустил запрос
            # через заслон, а не спрашивается у базы второй раз.
            "account": account,
            "logout_path": auth.LOGOUT_PATH,
        }


def _register_sections(app: Flask) -> None:
    """Экран «ещё в разработке» — по одному адресу на каждый непостроенный раздел.

    Адрес настоящий, а не заглушка под общим маршрутом: раздел обязан быть
    виден в карте продукта и открываться, иначе «покажем непостроенное» снова
    превращается в «спрячем».
    """
    for item in SECTIONS:
        if item.built:
            continue
        app.add_url_rule(
            item.path,
            endpoint=f"wip_{item.key}",
            view_func=_wip_view(item.key),
        )


def _wip_view(key: str) -> Any:
    def render() -> str:
        item = section(key)
        return render_template("under_construction.html", section=item)

    render.__name__ = f"wip_{key}"
    return render


def _url(endpoint: str, **params: Any) -> str:
    """`url_for` для параметров, собранных словарём.

    Заглушки Flask типизируют `url_for(**dict[str, str])` против его булевых
    `_external`/`_scheme`, и каждый такой вызов светился ошибкой типов. Смысл
    тот же — это только честная сигнатура для вызова со словарём.
    """
    return url_for(endpoint, **params)


@dataclass(frozen=True)
class PickOption:
    """Один вариант отбора: подпись, счёт, готовый адрес и выбран ли он."""

    title: str
    href: str
    selected: bool
    count: int | None = None


@dataclass(frozen=True)
class Pick:
    """Раскрывающийся чип отбора: название размерности и её варианты.

    `current_title` — подпись ТЕКУЩЕГО выбора, а не название размерности:
    панель обязана отвечать «что сейчас выбрано» одним взглядом.
    """

    label: str
    current: str
    current_title: str
    options: tuple[PickOption, ...]


def _pick(
    *,
    label: str,
    empty_title: str,
    current: str,
    values: tuple[tuple[str, int | None], ...],
    href: Callable[[str], str],
    title: Callable[[str], str] = str,
) -> Pick:
    """Собрать чип отбора. Вариант «не сужать» всегда первый.

    Снять отбор должно быть так же легко, как поставить: если «все» спрятано
    в конце списка или его нет вовсе, человек снимает фильтр правкой адреса.
    """
    опции = [PickOption(title=empty_title, href=href(""), selected=not current)]
    опции += [
        PickOption(title=title(value), href=href(value), selected=current == value, count=count)
        for value, count in values
    ]
    выбранное = next((о.title for о in опции[1:] if о.selected), empty_title)
    return Pick(label=label, current=current, current_title=выбранное, options=tuple(опции))


def _item_titles(conf: Settings, lang: str) -> dict[str, str]:
    """Формулировки пунктов методики по коду — для экранов, где есть только код.

    Берётся ДЕЙСТВУЮЩАЯ методика, а не замороженная у проверки: экран сети
    сводит проверки разных изданий, и одной формулировки на код у них нет.
    Поэтому это подпись к коду, а не текст той проверки, — код остаётся
    связью, формулировка только помогает его прочесть.

    Методика может быть не настроена (законная настройка стенда) или
    отказать: тогда словарь пуст, и экран покажет один код. Отказ здесь не
    повод не показать сеть — аналитика не про методику.
    """
    state = method.load_store()
    if state.store is None:
        return {}
    try:
        состав = method.load_composition(state.store, tenant=conf.tenant)
    except MethodologyRefused:
        return {}
    ключ = "question_ru" if lang == "ru" else "question_en"
    подписи: dict[str, str] = {}
    for item in состав.items:
        код = str(item.get("id", "")).strip()
        текст = str(item.get(ключ) or item.get("question_ru") or "").strip()
        if код and текст:
            подписи[код] = текст
    return подписи


def _register_overview(app: Flask, conf: Settings) -> None:
    """Раздел «Обзор»: сеть целиком одним экраном.

    Плитки собираются здесь, а не в шаблоне: у каждой есть адрес перехода, и
    адрес — это решение приложения, а не оформление. Цифра, из которой нельзя
    провалиться в список, на вопрос экрана не отвечает (бриф на визуал).
    """

    @app.get(section("overview").path)
    def overview() -> str:
        # Выборка приходит адресом, а не состоянием сессии: ссылку на срез
        # («Белград, буква D, за 30 дней») человек отправляет коллеге, и тот
        # обязан увидеть ровно тот же экран. Значения — коды; непонятное
        # значение сужает выборку в пустоту, но страницу не роняет.
        selection = overview_data.Selection(
            country=request.args.get("country", "").strip().upper()[:2],
            city=request.args.get("city", "").strip()[:80],
            grade=request.args.get("grade", "").strip().upper()[:1],
            period=request.args.get("period", "all").strip()[:8],
            sort=request.args.get("sort", "score").strip()[:8],
        )
        snapshot = overview_data.load(tenant=conf.tenant, limit=REGISTRY_LIMIT, selection=selection)
        registry_path = section("registry").path

        def отбор(**изменения: str) -> str:
            """Адрес того же экрана с изменённым срезом.

            Собирается здесь, а не склейкой в шаблоне: пустое значение обязано
            ИСЧЕЗАТЬ из адреса, иначе «сбросить город» оставляет в ссылке
            `city=` и срез выглядит суженным, хотя он полный.
            """
            параметры = {
                "country": selection.country,
                "city": selection.city,
                "grade": selection.grade,
                "period": selection.period,
                "sort": selection.sort,
                "lang": _lang(conf),
                **изменения,
            }
            # Умолчания из адреса ВЫПАДАЮТ: иначе «сбросить город» оставляет
            # в ссылке `city=`, а `sort=score` висит в каждом адресе и срез
            # выглядит настроенным, хотя он обычный.
            умолчания = {"period": "all", "sort": "score"}
            живые: dict[str, Any] = {
                ключ: значение
                for ключ, значение in параметры.items()
                if значение and умолчания.get(ключ) != значение
            }
            return _url("overview", **живые)

        def в_реестр(city: str | None = None) -> str:
            """Проверки этого среза в разделе «Проверки» — клик по городу (24.09.2026).

            Разбивка отвечает «где плохо», а за ответом человек идёт к самим
            проверкам: сужать тот же экран было тупиком — те же плитки, меньше
            строк. Период в реестр не уходит: там его отбора нет.
            """
            параметры = {
                "country": selection.country,
                "city": city or "",
                "grade": selection.grade,
                "lang": _lang(conf),
            }
            return _url("registry", **{к: з for к, з in параметры.items() if з})

        критических = sum(1 for item in snapshot.attention if item.why == "critical")
        среднее = (
            t("overview.tile.note.average_none", _lang(conf))
            if snapshot.average is None or not snapshot.comparable
            else t("overview.tile.note.average", _lang(conf))
        )
        # Плиток пять, и они РАЗНЫЕ на вид: бриф прямо запрещает полосу
        # одинаковых плиток, и различие здесь несёт смысл, а не украшает —
        # цветом помечено только то, что требует действия.
        tiles = (
            overview_data.Tile(
                key="units",
                value=str(snapshot.units_total),
                note=t(
                    "overview.tile.note.units",
                    _lang(conf),
                    checked=len({row.unit_name for row in snapshot.inspections}),
                ),
                href=registry_path,
            ),
            overview_data.Tile(
                key="unchecked",
                value=str(snapshot.unchecked),
                note=t("overview.tile.note.unchecked", _lang(conf)),
                href=registry_path,
                tone="warn" if snapshot.unchecked else "plain",
            ),
            overview_data.Tile(
                key="inspections",
                value=str(len(snapshot.inspections)),
                note=t("overview.tile.note.inspections", _lang(conf)),
                href=registry_path,
            ),
            overview_data.Tile(
                key="average",
                value="—"
                if snapshot.average is None or not snapshot.comparable
                else f"{snapshot.average:.1f}",
                note=среднее,
                href=registry_path,
                # Движение показывается только там, где его есть с чем
                # сравнить И где сравнение законно: ряд одного издания
                # методики против такого же ряда прошлого периода (T349).
                delta="" if snapshot.average_delta is None else f"{snapshot.average_delta:+.1f}",
                tone="err" if (snapshot.average_delta or 0) < 0 else "plain",
            ),
            overview_data.Tile(
                key="critical",
                value=str(критических),
                note=t("overview.tile.note.critical", _lang(conf)),
                href=registry_path,
                tone="err" if критических else "ok",
            ),
        )
        язык = _lang(conf)
        чипы = []
        if snapshot.countries:
            чипы.append(
                _pick(
                    label=t("overview.filter.country", язык),
                    empty_title=t("overview.filter.all_countries", язык),
                    current=selection.country,
                    values=snapshot.countries,
                    # Смена страны сбрасывает город: город другой страны в
                    # отборе дал бы пустую выборку без единого объяснения.
                    href=lambda значение: отбор(country=значение, city=""),
                    title=lambda код: country_title(код, язык),
                )
            )
        if snapshot.cities:
            чипы.append(
                _pick(
                    label=t("overview.filter.city", язык),
                    empty_title=t("overview.filter.all_cities", язык),
                    current=selection.city,
                    values=snapshot.cities,
                    href=lambda значение: отбор(city=значение),
                    title=lambda код: city_title(код, язык),
                )
            )
        чипы.append(
            _pick(
                label=t("overview.filter.grade", язык),
                empty_title=t("overview.filter.all_grades", язык),
                current=selection.grade,
                values=snapshot.grades,
                href=lambda значение: отбор(grade=значение),
            )
        )
        чипы.append(
            _pick(
                label=t("overview.filter.period", язык),
                empty_title=t("overview.period.all", язык),
                current="" if selection.period == "all" else selection.period,
                values=tuple((код, None) for код in overview_data.PERIODS if код != "all"),
                href=lambda значение: отбор(period=значение or "all"),
                title=lambda код: t("overview.period." + код, язык),
            )
        )
        порядок = _pick(
            label=t("overview.sort", язык),
            empty_title=t("overview.sort.score", язык),
            current="" if selection.sort == "score" else selection.sort,
            values=tuple((код, None) for код in overview_data.ПОРЯДКИ if код != "score"),
            href=lambda значение: отбор(sort=значение or "score"),
            title=lambda код: t("overview.sort." + код, язык),
        )
        return render_template(
            "overview/index.html",
            data=snapshot,
            tiles=tiles,
            picks=tuple(чипы),
            sort_pick=порядок,
            registry_path=registry_path,
            grade_tone=view.grade_tone,
            level_tone=view.level_tone,
            lang=_lang(conf),
            selection=selection,
            select_url=отбор,
            registry_url=в_реестр,
            periods=tuple(overview_data.PERIODS),
            plans_path=section("plans").path,
            item_titles=_item_titles(conf, _lang(conf)),
            # Идентификаторы точек нужны таблице, чтобы строка вела в карточку
            # точки, а не в последний отчёт: по прототипу владельца клик по
            # точке открывает точку. Связь идёт идентификатором справочника —
            # название в ссылке сломалось бы на первой же правке названия.
            unit_ids=snapshot.unit_ids,
        )


def _register_units(app: Flask, conf: Settings) -> None:
    """Карточка одной точки: где она сейчас, куда движется, что не чинится.

    Точка адресуется ИДЕНТИФИКАТОРОМ справочника, а не названием в адресной
    строке. Название — формулировка: его правят, переводят и пишут с опечаткой,
    и ссылка на карточку, собранная из него, ломается молча (CLAUDE.md,
    «сущности связывать кодами»). Внутри выборка проверок всё ещё идёт по
    каноничному названию — это устройство самой выборки вместе с её картой
    синонимов, а не способ адресации снаружи.
    """

    @app.get("/units/<unit_id>")
    def unit(unit_id: str) -> str | tuple[str, int]:
        lang = _lang(conf)
        # Справочник спрашивается целиком: точек у сети сотни, отдельный
        # запрос по идентификатору — это новая функция слоя базы ради одной
        # строки, и заводить её стоит тогда, когда список станет дорогим.
        точка = next(
            (u for u in directory.list_units(tenant=conf.tenant) if u.id == unit_id),
            None,
        )
        if точка is None:
            return render_template("inspections/not_found.html"), 404
        снимок = unit_data.load(tenant=conf.tenant, unit=точка.name, lang=lang)
        return render_template(
            "units/card.html",
            data=снимок,
            lang=lang,
            window=unit_data.ОКНО,
            grade_tone=view.grade_tone,
            level_tone=view.level_tone,
            overview_path=section("overview").path,
            registry_path=section("registry").path,
            plans_path=section("plans").path,
            item_titles=_item_titles(conf, lang),
        )


def _register_registry(app: Flask, conf: Settings) -> None:
    """Раздел «Проверки»: реестр, карточка, снятие."""

    @app.get("/")
    def home() -> Response:
        return redirect(url_for("registry"))

    @app.get(section("registry").path)
    def registry() -> str:
        registry_data = data.load_registry(tenant=conf.tenant, limit=REGISTRY_LIMIT)
        # Отбор реестра живёт в адресе ровно по той же причине, что и на
        # обзоре: ссылкой на срез делятся. Буква и вид проверки — коды, и
        # сравниваются как коды; непонятное значение сужает выборку в пустоту,
        # но страницу не роняет.
        буква = request.args.get("grade", "").strip().upper()[:1]
        вид = request.args.get("kind", "").strip()[:20]
        # Страна и город — по справочнику точек, кодами: сюда приводит клик по
        # городу на «Обзоре», и реестр обязан показать ровно эти проверки.
        страна = request.args.get("country", "").strip().upper()[:2]
        город = request.args.get("city", "").strip()[:80]
        гео = data.load_geography(tenant=conf.tenant)

        def место(row: InspectionRow) -> tuple[str, str]:
            страна_точки, город_точки = гео.get(row.unit_name, ("", ""))
            return страна_точки or "", город_точки or ""

        строки = tuple(
            row
            for row in registry_data.rows
            if (not буква or row.grade == буква)
            and (not вид or row.kind == вид)
            and (not страна or место(row)[0] == страна)
            and (not город or место(row)[1] == город)
        )

        def отбор(**изменения: str) -> str:
            параметры = {
                "country": страна,
                "city": город,
                "grade": буква,
                "kind": вид,
                "lang": _lang(conf),
                **изменения,
            }
            живые = {ключ: значение for ключ, значение in параметры.items() if значение}
            return _url("registry", **живые)

        язык = _lang(conf)
        # Буквы — шкалой со счётом по выборке: сколько проверок за каждой.
        буквы = tuple(
            (значение, sum(1 for row in registry_data.rows if row.grade == значение))
            for значение in ("A", "B", "C", "D")
        )
        виды = tuple(
            (код, sum(1 for row in registry_data.rows if row.kind == код))
            for код in dict.fromkeys(row.kind for row in registry_data.rows)
        )
        чипы = []
        страны = tuple(
            (код, sum(1 for row in registry_data.rows if место(row)[0] == код))
            for код in sorted({место(row)[0] for row in registry_data.rows} - {""})
        )
        # Города — только выбранной страны, как и на «Обзоре».
        города = tuple(
            (код, sum(1 for row in registry_data.rows if место(row)[1] == код))
            for код in sorted(
                {
                    место(row)[1]
                    for row in registry_data.rows
                    if not страна or место(row)[0] == страна
                }
                - {""}
            )
        )
        if страны:
            чипы.append(
                _pick(
                    label=t("overview.filter.country", язык),
                    empty_title=t("overview.filter.all_countries", язык),
                    current=страна,
                    values=страны,
                    href=lambda значение: отбор(country=значение, city=""),
                    title=lambda код: country_title(код, язык),
                )
            )
        if города:
            чипы.append(
                _pick(
                    label=t("overview.filter.city", язык),
                    empty_title=t("overview.filter.all_cities", язык),
                    current=город,
                    values=города,
                    href=lambda значение: отбор(city=значение),
                    title=lambda код: city_title(код, язык),
                )
            )
        чипы.append(
            _pick(
                label=t("overview.filter.grade", язык),
                empty_title=t("overview.filter.all_grades", язык),
                current=буква,
                values=буквы,
                href=lambda значение: отбор(grade=значение),
            )
        )
        if виды:
            чипы.append(
                _pick(
                    label=t("registry.col.kind", язык),
                    empty_title=t("registry.all_kinds", язык),
                    current=вид,
                    values=виды,
                    href=lambda значение: отбор(kind=значение),
                    title=lambda код: _kind_title(код, язык),
                )
            )
        return render_template(
            "inspections/list.html",
            registry=registry_data,
            rows=строки,
            picks=tuple(чипы),
            grade_tone=view.grade_tone,
            kind_title=_kind_title,
            # Буквы — шкалой, а не по частоте: полоса отбора не должна менять
            # порядок от выборки к выборке (то же правило, что на обзоре).
            grades=("A", "B", "C", "D"),
            kinds=tuple(dict.fromkeys(row.kind for row in registry_data.rows)),
            grade=буква,
            kind=вид,
            select_url=отбор,
        )

    @app.get(f"{section('registry').path}/<inspection_id>")
    def card(inspection_id: str) -> str | tuple[str, int]:
        return _render_card(inspection_id, conf=conf, notice=None, failure=None)

    @app.get(f"{section('registry').path}/<inspection_id>/letter")
    def letter(inspection_id: str) -> str | tuple[str, int]:
        lang = _lang(conf)
        detail = data.load_card(inspection_id, tenant=conf.tenant)
        if detail is None:
            return render_template("inspections/not_found.html"), 404
        # Язык ПИСЬМА — третий язык продукта, и он свой: партнёру пишут на его
        # языке, а не на языке того, кто открыл админку. По умолчанию это язык
        # отчёта проверки; переключатель нужен там, где письмо уходит партнёру
        # другой страны. Незнакомый язык проверяет сборщик и отказывает вслух —
        # движок на такой молча собрал бы письмо по-русски.
        письмо_на = request.args.get("letter_lang") or None
        собранное = data.load_letter(detail, lang=письмо_на)
        # Зафиксированное письмо СИЛЬНЕЕ заготовки: у партнёра на руках лежит
        # один текст, и показать вместо него сегодняшнюю пересборку значит
        # ответить на «что мы отправили» правдоподобной неправдой. Заготовка
        # при этом собирается всё равно — по ней видно оговорки (пустая шапка,
        # чужой язык), и они не перестают быть правдой оттого, что письмо
        # зафиксировали.
        # Отказ базы здесь НЕ роняет экран и не выдаётся за «письма нет»: это
        # разные вещи, и вторая — молчаливая ложь. Без базы (законная настройка
        # стенда) страница честно говорит, что сохранённое сейчас неизвестно, и
        # показывает заготовку.
        try:
            записанное = data.saved_letter(
                inspection_id, lang=письмо_на or detail.inspection.report_lang
            )
            сохранённое_известно = True
        except DbError:
            записанное = None
            сохранённое_известно = False
        # «Вернуть заготовку» — отказ от СВОИХ правок, а не от записи: письмо
        # партнёру уже могло уйти, и вынуть его из истории нельзя ничем.
        # Поэтому режим показывает свежесобранный движком текст в поле, но
        # зафиксированное письмо остаётся на месте и остаётся видно, кем и
        # когда оно записано. Новая правка ложится новой записью.
        показать_заготовку = request.args.get("draft") == "1"
        return render_template(
            "inspections/letter.html",
            letter=собранное,
            saved=записанное,
            show_draft=показать_заготовку,
            saved_known=сохранённое_известно,
            save_outcome=request.args.get("saved"),
            gmail_outcome=request.args.get("gmail"),
            head=detail.inspection,
            letter_langs=data.LETTER_LANGS,
            letter_lang=письмо_на or detail.inspection.report_lang,
            caveats=view.letter_caveats(собранное.caveats, lang),
            source=None if собранное.source is None else view.letter_source(собранное.source, lang),
        )

    @app.post(f"{section('registry').path}/<inspection_id>/letter")
    def export_letter(inspection_id: str) -> FlaskResponse | tuple[str, int]:
        refuse_foreign_origin()
        # Проверка существует и принадлежит этому арендатору — спрашивается
        # ДО того, как что-то отдаётся. Иначе страница выгрузки превратилась
        # бы в готовый способ получить от админки файл с любым присланным
        # текстом по её собственному адресу.
        head = data.load_card(inspection_id, tenant=conf.tenant)
        if head is None:
            return render_template("inspections/not_found.html"), 404
        текст = request.form.get("text") or ""
        return _letter_file(текст, inspection_id)

    @app.post(f"{section('registry').path}/<inspection_id>/letter/save")
    def save_letter(inspection_id: str) -> Response | FlaskResponse | tuple[str, int] | str:
        """Зафиксировать письмо в том виде, в каком его подтвердил человек (T333).

        Отправки из системы по-прежнему нет (Q010, D035): письмо уходит из
        почты руками. Фиксация отвечает не на «отправлено», а на «вот текст,
        который мы считаем отправленным», — и без неё этот вопрос остаётся
        без ответа навсегда.
        """
        refuse_foreign_origin()
        detail = data.load_card(inspection_id, tenant=conf.tenant)
        if detail is None:
            return render_template("inspections/not_found.html"), 404

        текст = request.form.get("text") or ""
        письмо_на = request.form.get("letter_lang") or detail.inspection.report_lang
        вошедший = auth.current_account()
        try:
            data.remember_letter(
                inspection_id,
                body=текст,
                lang=письмо_на,
                saved_by="—" if вошедший is None else вошедший.login,
            )
        except DbError:
            # Исход виден человеку словами на той же странице, а не пятисотой:
            # пустое письмо и потерянная база чинятся по-разному, и молчащая
            # кнопка «Сохранить» — ровно то, на что владелец и пожаловался.
            return redirect(
                url_for(
                    "letter", inspection_id=inspection_id, letter_lang=письмо_на, saved="failed"
                ),
                code=303,
            )
        # Перенаправление, а не отрисовка на месте: иначе обновление страницы
        # повторяло бы отправку формы, и в истории появлялось бы второе письмо,
        # которого никто не фиксировал.
        return redirect(
            url_for("letter", inspection_id=inspection_id, letter_lang=письмо_на, saved="ok"),
            code=303,
        )

    # --- учётки админки (T338, #322) ---------------------------------------
    # Заведение переехало из командной строки на экран, и заслон стоит ЗДЕСЬ, а
    # не в навигации: адрес известен, набрать его руками может кто угодно.
    users_path = section("users").path

    def _страница_учёток(
        *, added: accounts.Added | None = None, outcome: str | None = None, code: int = 200
    ) -> tuple[str, int]:
        try:
            люди = accounts.everyone(tenant=conf.tenant)
            перечень_известен = True
        except DbError:
            # Отказ базы НЕ выдаётся за «никого нет»: это разные вещи, и вторая
            # была бы молчаливой ложью на экране, где считают людей с доступом.
            люди = ()
            перечень_известен = False
        return (
            render_template(
                "users/index.html",
                people=люди,
                people_known=перечень_известен,
                added=added,
                outcome=outcome,
                roles=accounts.ROLES,
                users_path=users_path,
            ),
            code,
        )

    @app.get(users_path)
    def users() -> FlaskResponse | tuple[str, int]:
        отказ = _admin_only()
        if отказ is not None:
            return отказ
        return _страница_учёток()

    @app.post(f"{users_path}/add")
    def add_user() -> FlaskResponse | tuple[str, int]:
        """Завести человека. Пароль показывается ОДИН раз — на этой же странице.

        Страница, а не перенаправление: пароль в адресе остался бы в истории
        браузера и в журнале обратного прокси, то есть перестал бы быть
        паролем ровно в момент показа.
        """
        отказ = _admin_only()
        if отказ is not None:
            return отказ
        refuse_foreign_origin()
        логин = (request.form.get("login") or "").strip()
        роль = request.form.get("role") or accounts.ROLE_AUDITOR
        try:
            заведённый = accounts.add(логин, tenant=conf.tenant, role=роль)
        except DbError:
            return _страница_учёток(outcome="add_failed", code=400)
        return _страница_учёток(added=заведённый, outcome="added")

    @app.post(f"{users_path}/disable")
    def disable_user() -> FlaskResponse | tuple[str, int]:
        отказ = _admin_only()
        if отказ is not None:
            return отказ
        refuse_foreign_origin()
        логин = (request.form.get("login") or "").strip()
        вошедший = auth.current_account()
        if вошедший is not None and логин == вошедший.login:
            # Отключить себя — это выйти и не вернуться, а на стенде с одним
            # администратором ещё и закрыть экран учёток навсегда: снять
            # пометку изнутри продукта нечем.
            return _страница_учёток(outcome="disable_self", code=400)
        try:
            отключено = accounts.disable(логин, tenant=conf.tenant)
        except DbError:
            return _страница_учёток(outcome="disable_failed", code=400)
        return _страница_учёток(outcome="disabled" if отключено else "disable_missing")

    @app.post(f"{section('registry').path}/<inspection_id>/retract")
    def do_retract(inspection_id: str) -> FlaskResponse | str | tuple[str, int]:
        отказ = _admin_only()
        if отказ is not None:
            return отказ
        refuse_foreign_origin()
        reason = (request.form.get("reason") or "").strip()
        notice: str | None = None
        failure: str | None = None
        try:
            done = data.retract_card(inspection_id, tenant=conf.tenant, reason=reason)
        except RetractionError as exc:
            failure = t("retract.failed", _lang(conf), reason=str(exc))
        else:
            notice = t("retract.done", _lang(conf), photos=done.photos_purged)
        return _render_card(inspection_id, conf=conf, notice=notice, failure=failure)

    @app.post(f"{section('registry').path}/<inspection_id>/move")
    def do_move(inspection_id: str) -> FlaskResponse | str | tuple[str, int]:
        """Перенести проверку по дате и пиццерии (D195). Только администратор."""
        отказ = _admin_only()
        if отказ is not None:
            return отказ
        refuse_foreign_origin()
        вошедший = auth.current_account()
        notice: str | None = None
        failure: str | None = None
        try:
            перенесено = data.move_card(
                inspection_id,
                tenant=conf.tenant,
                new_date=request.form.get("date") or "",
                new_unit_id=request.form.get("unit") or "",
                reason=request.form.get("reason") or "",
                actor=вошедший.login if вошедший else "",
            )
        except MoveError as exc:
            failure = t("move.failed", _lang(conf), reason=str(exc))
        else:
            notice = t("move.done" if перенесено else "move.same", _lang(conf))
        return _render_card(inspection_id, conf=conf, notice=notice, failure=failure)


def _admin_only() -> FlaskResponse | None:
    """Отказ 403 всем, кроме администратора; `None` — можно.

    Заслон стоит на МАРШРУТЕ, а не в разметке: адрес известен, и POST набирается
    руками. До 24.09.2026 отклонение проверки проверяло только вход, и отклонить
    её с выносом кадров мог любой аудитор.
    """
    вошедший = auth.current_account()
    if вошедший is not None and вошедший.role == accounts.ROLE_ADMIN:
        return None
    # 403, а не 404: человек вошёл, он здесь свой, и делать вид, что
    # раздела нет, значит отвечать на «мне сюда нельзя?» загадкой.
    return render_template("users/forbidden.html"), 403  # type: ignore[return-value]


def _render_card(
    inspection_id: str, *, conf: Settings, notice: str | None, failure: str | None
) -> str | tuple[str, int]:
    detail = data.load_card(inspection_id, tenant=conf.tenant)
    if detail is None:
        return render_template("inspections/not_found.html"), 404
    lang = _lang(conf)
    админ = _admin_only() is None
    try:
        переносы = data.load_moves(inspection_id, tenant=conf.tenant)
        история_известна = True
    except DbError:
        # История недоступна (например, схема ещё без `0025`) — карточка живёт,
        # а переносить без истории нельзя: форма не показывается.
        переносы = ()
        история_известна = False
    можно_переносить = (
        админ
        and история_известна
        and data.retraction_available()
        and not detail.inspection.retracted
    )
    return render_template(
        "inspections/card.html",
        moves=переносы,
        moves_known=история_известна,
        may_move=можно_переносить,
        units=data.load_units(tenant=conf.tenant) if можно_переносить else (),
        detail=detail,
        head=detail.inspection,
        zones=view.zone_lines(detail.by_zone, lang),
        counts=view.count_lines(detail.counts),
        grade_tone=view.grade_tone,
        level_tone=view.level_tone,
        kind=_kind_title(detail.inspection.kind, lang),
        may_retract=data.retraction_available() and админ,
        notice=notice,
        failure=failure,
    )


def _joined(form: Any, name: str, sep: str) -> str | None:
    """Плашки выбора (несколько значений одного поля) — в ячейку методики.

    Классы пишутся через `;`, зоны через `,` — как их читает движок. «Все зоны»
    (`*`) поглощает остальные: пункт «все зоны + кухня» это просто все зоны.
    Ничего не выбрано — `None`, то есть «не трогать»: так поле не приходит
    вовсе из формы, где его нет.
    """
    значения = [v.strip() for v in form.getlist(name) if v and v.strip()]
    if not значения:
        return None
    if name == "zones" and mview.ALL_ZONES in значения:
        return mview.ALL_ZONES
    return sep.join(значения)


def _register_methodology(app: Flask, conf: Settings) -> None:
    """Раздел «Методика»: состав чек-листа, правка, публикация отдельным шагом.

    Ни одна правка не трогает действующую методику. Каждая кладёт РЯДОМ новую
    версию, движок её проверяет, и только принятую можно опубликовать (D049,
    D050). Сами эти правила живут в хранилище версий — `src/web/methodology.py`
    зовёт его, а не повторяет.

    Правка отвечает не перенаправлением, а той же страницей с итогом: человеку
    нужно увидеть номер записанной версии и то, что она ещё НЕ опубликована, —
    иначе «сохранил» прочиталось бы как «теперь по ней и считают».
    """
    путь = section("admin").path

    @app.get(путь)
    def methodology() -> str:
        return _render_methodology(conf, notice=None, failure=None)

    @app.get(f"{путь}/items/<code>")
    def methodology_item(code: str) -> Response:
        # Карточка пункта теперь — панель экрана чек-листа (D197). Старый адрес
        # живёт перенаправлением: на него ведут ссылки из писем и журналов.
        return redirect(_url("methodology", **request.args.to_dict(), item=code))

    @app.post(f"{путь}/items")
    def methodology_add() -> str:
        refuse_foreign_origin()
        form = request.form
        итог = _apply(
            conf,
            lambda store, автор: method.add_item(
                store,
                tenant=conf.tenant,
                author=автор,
                process=(form.get("process") or "").strip(),
                question_ru=(form.get("question_ru") or "").strip(),
                levels=_joined(form, "levels", ";") or "",
                code=form.get("code"),
                process_en=form.get("process_en"),
                question_en=form.get("question_en"),
                zones=_joined(form, "zones", ","),
                days=form.get("days"),
                criteria=form.get("criteria"),
                kind=form.get("kind"),
                note=form.get("note"),
                version_name=form.get("version_name"),
            ),
        )
        return _render_methodology(conf, notice=итог.notice, failure=итог.failure)

    @app.post(f"{путь}/items/<code>")
    def methodology_edit(code: str) -> str:
        refuse_foreign_origin()
        form = request.form
        итог = _apply(
            conf,
            lambda store, автор: method.edit_item(
                store,
                tenant=conf.tenant,
                author=автор,
                code=code,
                process=form.get("process"),
                process_en=form.get("process_en"),
                question_ru=form.get("question_ru"),
                question_en=form.get("question_en"),
                levels=_joined(form, "levels", ";"),
                zones=_joined(form, "zones", ","),
                days=form.get("days"),
                criteria=form.get("criteria"),
                note=form.get("note"),
                version_name=form.get("version_name"),
            ),
        )
        return _render_methodology(conf, notice=итог.notice, failure=итог.failure, item=code)

    @app.post(f"{путь}/items/<code>/disable")
    def methodology_disable(code: str) -> str:
        refuse_foreign_origin()
        итог = _apply(
            conf,
            lambda store, автор: method.disable_item(
                store,
                tenant=conf.tenant,
                author=автор,
                code=code,
                note=request.form.get("note"),
                version_name=request.form.get("version_name"),
            ),
        )
        return _render_methodology(conf, notice=итог.notice, failure=итог.failure, item=code)

    @app.post(f"{путь}/items/<code>/restore")
    def methodology_restore(code: str) -> str:
        refuse_foreign_origin()
        итог = _apply(
            conf,
            lambda store, автор: method.restore_item(
                store,
                tenant=conf.tenant,
                author=автор,
                code=code,
                note=request.form.get("note"),
                version_name=request.form.get("version_name"),
            ),
        )
        return _render_methodology(conf, notice=итог.notice, failure=итог.failure, item=code)

    @app.post(f"{путь}/zones")
    def methodology_zone_add() -> str:
        refuse_foreign_origin()
        form = request.form
        итог = _apply(
            conf,
            lambda store, автор: method.add_zone(
                store,
                tenant=conf.tenant,
                author=автор,
                code=(form.get("code") or "").strip(),
                name_ru=(form.get("name_ru") or "").strip(),
                name_en=form.get("name_en"),
                share=form.get("share"),
                equal_shares=bool(form.get("equal_shares")),
                note=form.get("note"),
                version_name=form.get("version_name"),
            ),
        )
        return _render_methodology(conf, notice=итог.notice, failure=итог.failure)

    @app.post(f"{путь}/zones/shares")
    def methodology_zone_shares() -> str:
        refuse_foreign_origin()
        # Доли приезжают полями `share_<код>` и отправляются ВСЕ разом: сумма
        # обязана сойтись к 100%, поэтому правка одной доли до расчёта не дошла
        # бы вовсе — версию с несошедшейся суммой хранилище не примет.
        доли = {
            имя[len("share_") :]: значение
            for имя, значение in request.form.items()
            if имя.startswith("share_")
        }
        итог = _apply(
            conf,
            lambda store, автор: method.set_zone_shares(
                store,
                tenant=conf.tenant,
                author=автор,
                shares=доли,
                note=request.form.get("note"),
                version_name=request.form.get("version_name"),
            ),
        )
        return _render_methodology(conf, notice=итог.notice, failure=итог.failure)

    @app.post(f"{путь}/zones/<code>/rename")
    def methodology_zone_rename(code: str) -> str:
        refuse_foreign_origin()
        form = request.form
        итог = _apply(
            conf,
            lambda store, автор: method.rename_zone(
                store,
                tenant=conf.tenant,
                author=автор,
                code=code,
                name_ru=form.get("name_ru"),
                name_en=form.get("name_en"),
                note=form.get("note"),
                version_name=form.get("version_name"),
            ),
        )
        return _render_methodology(conf, notice=итог.notice, failure=итог.failure)

    @app.post(f"{путь}/zones/<code>/remove")
    def methodology_zone_remove(code: str) -> str:
        refuse_foreign_origin()
        form = request.form
        итог = _apply(
            conf,
            lambda store, автор: method.remove_zone(
                store,
                tenant=conf.tenant,
                author=автор,
                code=code,
                equal_shares=bool(form.get("equal_shares")),
                note=form.get("note"),
                version_name=form.get("version_name"),
            ),
        )
        return _render_methodology(conf, notice=итог.notice, failure=итог.failure)

    @app.post(f"{путь}/route")
    def methodology_route() -> str:
        refuse_foreign_origin()
        form = request.form
        номера = {ключ[len("order_") :]: form[ключ] for ключ in form if ключ.startswith("order_")}
        сейчас = [код for код in form.getlist("zone") if код]
        итог = _apply(
            conf,
            lambda store, автор: method.set_route_zones(
                store,
                tenant=conf.tenant,
                author=автор,
                zones=mview.route_order(номера, сейчас),
                note=form.get("note"),
                version_name=form.get("version_name"),
            ),
        )
        return _render_methodology(conf, notice=итог.notice, failure=итог.failure)

    @app.post(f"{путь}/scoring")
    def methodology_scoring() -> str:
        refuse_foreign_origin()
        form = request.form
        итог = _apply(
            conf,
            lambda store, автор: method.set_scoring(
                store,
                tenant=conf.tenant,
                author=автор,
                start_pct=form.get("start_pct"),
                d1=form.get("d1"),
                d2=form.get("d2"),
                repeat_multiplier=form.get("repeat_multiplier"),
                note=form.get("note"),
                version_name=form.get("version_name"),
            ),
        )
        return _render_methodology(conf, notice=итог.notice, failure=итог.failure)

    @app.post(f"{путь}/publish")
    def methodology_publish() -> str:
        refuse_foreign_origin()
        version = (request.form.get("version") or "").strip()
        state = method.load_store()
        if state.store is None:
            return _render_methodology(conf, notice=None, failure=None)
        try:
            # Публикуется версия ПОКАЗАННОГО чек-листа, а не корня хранилища (#382).
            склад = method.store_for(state.store, _который(request))
            опубликована = method.publish_version(склад, tenant=conf.tenant, version=version)
        except MethodologyRefused as отказ:
            return _render_methodology(conf, notice=None, failure=str(отказ))
        return _render_methodology(
            conf,
            notice=t("methodology.published", _lang(conf), version=опубликована),
            failure=None,
        )


def _mount_checklists(app: Flask, conf: Settings) -> None:
    """Экраны чек-листов: перечень, заведение с нуля, состояние, применение к проду.

    Отдельным адресом внутри «Методики», а не новым разделом: это та же
    методика, только ярусом выше — какие чек-листы есть и по какому идут
    проверки.

    Применение к проду не спрятано за правом, и это решение (D182): ролей в
    продукте нет, круг людей узкий, а от ошибки право не спасает — у
    ошибающегося оно как раз есть. Вместо права три вещи: заслоны двери,
    след в журнале с логином вошедшего и ПОКАЗ РАЗНИЦЫ перед применением.
    Третье и есть настоящая защита, поэтому кнопка живёт на отдельной
    странице, а не рядом со списком.
    """
    путь = f"{section('admin').path}/checklists"

    @app.get(путь)
    def checklists() -> str:
        return _render_checklists(conf, notice=None, failure=None)

    @app.post(путь)
    def checklists_create() -> str:
        refuse_foreign_origin()
        form = request.form
        state = method.load_store()
        if state.store is None:
            return _render_checklists(conf, notice=None, failure=None)
        try:
            заведён = method.create_checklist(
                state.store,
                tenant=conf.tenant,
                author=_author(conf),
                code=(form.get("code") or "").strip(),
                name_ru=(form.get("name_ru") or "").strip(),
                name_en=(form.get("name_en") or "").strip(),
            )
        except MethodologyRefused as отказ:
            return _render_checklists(conf, notice=None, failure=str(отказ))
        return _render_checklists(
            conf,
            notice=t("checklists.created", _lang(conf), checklist=заведён.code),
            failure=None,
        )

    @app.post(f"{путь}/<code>/state")
    def checklists_state(code: str) -> str:
        refuse_foreign_origin()
        state = method.load_store()
        if state.store is None:
            return _render_checklists(conf, notice=None, failure=None)
        try:
            стало = method.set_checklist_state(
                state.store,
                tenant=conf.tenant,
                author=_author(conf),
                code=code,
                state=(request.form.get("state") or "").strip(),
            )
        except MethodologyRefused as отказ:
            return _render_checklists(conf, notice=None, failure=str(отказ))
        return _render_checklists(
            conf,
            notice=t("checklists.state.set", _lang(conf), checklist=стало.code, state=стало.state),
            failure=None,
        )

    @app.get(f"{путь}/<code>/apply")
    def checklists_apply_preview(code: str) -> str:
        """Разница до применения. Отдельной страницей, а не всплывающим вопросом:
        читать «столько пунктов, такие зоны, такие ставки» надо глазами."""
        state = method.load_store()
        if state.store is None:
            return render_template("methodology/unset.html", missing=state.missing)
        целевое = method.store_for(state.store, code)
        return render_template(
            "methodology/apply.html",
            code=code,
            difference=method.checklist_difference(целевое),
            failure=None,
        )

    @app.post(f"{путь}/<code>/apply")
    def checklists_apply(code: str) -> str:
        refuse_foreign_origin()
        state = method.load_store()
        if state.store is None:
            return _render_checklists(conf, notice=None, failure=None)
        try:
            итог = method.apply_checklist(
                state.store, tenant=conf.tenant, author=_author(conf), code=code
            )
        except MethodologyRefused as отказ:
            return _render_checklists(conf, notice=None, failure=str(отказ))
        return _render_checklists(
            conf,
            notice=t("checklists.applied", _lang(conf), checklist=str(итог["applied"])),
            failure=None,
        )


def _render_checklists(conf: Settings, *, notice: str | None, failure: str | None) -> str:
    """Перечень чек-листов и заведение нового.

    Хранилище не настроено — страница называет незаданные переменные поимённо,
    как и соседний экран состава: пустой перечень читался бы как «чек-листов
    нет», а это разные вещи.
    """
    state = method.load_store()
    if state.store is None:
        return render_template("methodology/unset.html", missing=state.missing)
    try:
        перечень = method.checklists_overview(state.store)
    except MethodologyRefused as отказ:
        return render_template(
            "methodology/checklists.html",
            checklists=[],
            states=method.CHECKLIST_STATES,
            notice=None,
            failure=failure or str(отказ),
        )
    return render_template(
        "methodology/checklists.html",
        checklists=перечень,
        states=method.CHECKLIST_STATES,
        notice=notice,
        failure=failure,
    )


@dataclass(frozen=True)
class _Итог:
    """Чем кончилась правка на экране: сообщение или отказ, но не оба."""

    notice: str | None = None
    failure: str | None = None


def _который(запрос: Any) -> str | None:
    """Какой чек-лист смотрит или правит человек — из адреса страницы.

    Не назван — `None`, и дверь возьмёт применённый к проду. Своего умолчания
    здесь нет намеренно: два умолчания на один вопрос однажды разойдутся, и
    экран будет править не то, что показывает.
    """
    return (запрос.args.get("checklist") or "").strip() or None


def _author(conf: Settings) -> str:
    """Кто правит — для журнала хранилища.

    Заслон без учётки на эти маршруты не пускает вовсе, так что ветка с
    тенантом — не подстраховка «на всякий случай», а честный ответ на случай,
    когда правку однажды позовёт не человек: подписать её именем арендатора
    правдивее, чем пустым местом.
    """
    account = auth.current_account()
    return account.login if account else conf.tenant


def _apply(conf: Settings, действие: Any) -> _Итог:
    """Сделать правку дверью методики и сказать словами, чем она кончилась."""
    state = method.load_store()
    if state.store is None:
        return _Итог()
    try:
        правка = действие(method.store_for(state.store, _который(request)), _author(conf))
    except MethodologyRefused as отказ:
        return _Итог(failure=str(отказ))
    return _Итог(notice=t("methodology.saved", _lang(conf), version=правка.version))


def _который_показан(перечень: list[Any], попросили: str | None) -> str | None:
    """Код чек-листа на экране: названный в адресе или применённый к проду.

    Код держится в КАЖДОМ адресе и действии экрана явно (#382): до 25.09.2026
    формы правки теряли `?checklist=`, и правка открытого чернового чек-листа
    молча записывалась в боевой.
    """
    if попросили:
        return попросили
    return next((c.code for c in перечень if c.in_production), None)


def _render_methodology(
    conf: Settings,
    *,
    notice: str | None,
    failure: str | None,
    item: str | None = None,
) -> str:
    """Чек-лист в три колонки (D197): чек-листы, пункты, панель пункта.

    Хранилище не настроено — страница называет незаданные переменные поимённо и
    состава не показывает вовсе: пустой список читался бы как «чек-лист пуст».
    Панель — часть той же страницы и того же адреса (`?item=`): её можно
    переслать ссылкой, обновить и открыть без скрипта.
    """
    state = method.load_store()
    if state.store is None:
        return render_template("methodology/unset.html", missing=state.missing)
    lang = _lang(conf)
    попросили = (request.args.get("version") or "").strip() or None
    try:
        перечень = method.checklists_overview(state.store)
    except MethodologyRefused as отказ:
        перечень, failure = [], failure or str(отказ)
    код = _который_показан(перечень, _который(request))
    try:
        склад = method.store_for(state.store, код)
    except MethodologyRefused as отказ:
        склад, failure = state.store, failure or str(отказ)
    try:
        состав = method.load_composition(склад, tenant=conf.tenant, version=попросили)
    except MethodologyRefused as отказ:
        состав = method.load_composition(склад, tenant=conf.tenant)
        failure = failure or str(отказ)
    отбор = mview.parse_filter(request.args)
    выбран = item or (request.args.get("item") or "").strip() or None
    новый = request.args.get("new") == "1" and состав.is_latest

    def адрес(**изменения: str) -> str:
        """Адрес этого экрана с тем же чек-листом, версией и отбором."""
        параметры = {
            "checklist": код or "",
            "version": попросили or "",
            "q": отбор.q,
            "level": отбор.level,
            "zone": отбор.zone,
            "off": "1" if отбор.off else "",
            "group": "" if отбор.group == mview.GROUPINGS[0] else отбор.group,
            "item": выбран or "",
            "lang": lang,
            **изменения,
        }
        return _url("methodology", **{к: з for к, з in параметры.items() if з})

    def действие(endpoint: str, **ключи: str) -> str:
        """Адрес формы: несёт тот же чек-лист и отбор, чтобы итог лёг на тот же экран."""
        параметры = {
            "checklist": код or "",
            "q": отбор.q,
            "level": отбор.level,
            "zone": отбор.zone,
            "off": "1" if отбор.off else "",
            "group": "" if отбор.group == mview.GROUPINGS[0] else отбор.group,
            "lang": lang,
        }
        живые = {к: з for к, з in параметры.items() if з}
        return _url(endpoint, **ключи, **живые)

    видимые = mview.select(состав.items, отбор)
    зоны = {
        z.get("code", ""): (z.get(f"name_{lang}") or z.get("name_ru") or z.get("code", ""))
        for z in состав.zones
    }
    карточка = None
    if выбран and not новый:
        try:
            карточка = method.load_item(склад, tenant=conf.tenant, code=выбран, version=попросили)[
                "item"
            ]
        except MethodologyRefused as отказ:
            failure = failure or str(отказ)
    # Разница действующей и свежей записанной — по запросу: чтение каждого
    # пункта целиком дорого, а полоса версии и так говорит, что она есть.
    разница: tuple[mview.Change, ...] | None = None
    if request.args.get("diff") == "1" and состав.unpublished:
        try:
            разница = mview.diff_items(
                method.full_items(склад, tenant=conf.tenant, version=состав.current),
                method.full_items(склад, tenant=conf.tenant, version=состав.latest),
            ) + mview.diff_zones(
                method.zones_of_version(склад, tenant=conf.tenant, version=состав.current),
                method.zones_of_version(склад, tenant=conf.tenant, version=состав.latest),
            )
        except MethodologyRefused as отказ:
            failure = failure or str(отказ)
    открыта_зона = (request.args.get("zone_card") or "").strip()
    зона = next((z for z in состав.zones if z.get("code") == открыта_зона), None)
    обход: list[dict[str, Any]] = []
    if карточка is None and not новый:
        try:
            обход = list(method.load_route(склад, tenant=conf.tenant, version=попросили)["zones"])
        except MethodologyRefused as отказ:
            failure = failure or str(отказ)
    сводка = (
        data.load_item_usage(tenant=conf.tenant, code=выбран, checklist=код or "")
        if карточка is not None and выбран
        else None
    )
    раньше, позже = mview.neighbours(видимые, выбран or "")
    return render_template(
        "methodology/index.html",
        composition=состав,
        checklists=перечень,
        checklist_code=код,
        needs_name=method.needs_set_name(состав),
        kinds=method.ITEM_KINDS,
        max_note=method.MAX_NOTE,
        item_filter=отбор,
        groups=mview.group(видимые, отбор.group),
        shown=len(видимые),
        total=sum(1 for x in состав.items if отбор.off or not mview.is_off(x)),
        picks=_methodology_picks(состав, отбор, адрес, зоны, lang),
        zone_names=зоны,
        level_choices=mview.level_options(состав.items),
        zone_choices=mview.zone_options(состав.items, состав.zones),
        levels_of=mview.levels_of,
        zones_of=mview.zones_of,
        is_off=mview.is_off,
        selected=выбран,
        card=карточка,
        usage=сводка,
        changes=разница,
        route_zones=обход,
        zone_card=зона,
        zone_items=dict(mview.zone_options(состав.items, состав.zones)).get(открыта_зона, 0),
        adding=новый,
        prev_href=адрес(item=раньше) if раньше else None,
        next_href=адрес(item=позже) if позже else None,
        href=адрес,
        action=действие,
        notice=notice,
        failure=failure,
    )


def _methodology_picks(
    состав: Any,
    отбор: mview.ItemFilter,
    адрес: Callable[..., str],
    зоны: dict[str, str],
    lang: str,
) -> tuple[Pick, ...]:
    """Чипы над списком пунктов: класс, зона, группировка."""
    return (
        _pick(
            label=t("methodology.pick.level", lang),
            empty_title=t("methodology.pick.level.all", lang),
            current=отбор.level,
            values=mview.level_options(состав.items),
            href=lambda значение: адрес(level=значение, item=""),
        ),
        _pick(
            label=t("methodology.pick.zone", lang),
            empty_title=t("methodology.pick.zone.all", lang),
            current=отбор.zone,
            values=mview.zone_options(состав.items, состав.zones),
            href=lambda значение: адрес(zone=значение, item=""),
            title=lambda код: зоны.get(код, код),
        ),
        Pick(
            label=t("methodology.pick.group", lang),
            current="" if отбор.group == mview.GROUPINGS[0] else отбор.group,
            current_title=t(f"methodology.group.{отбор.group}", lang),
            options=tuple(
                PickOption(
                    title=t(f"methodology.group.{g}", lang),
                    href=адрес(group="" if g == mview.GROUPINGS[0] else g),
                    selected=g == отбор.group,
                )
                for g in mview.GROUPINGS
            ),
        ),
    )


def _letter_file(text: str, inspection_id: str) -> FlaskResponse:
    """Правленое письмо — файлом, который человек приложит к почте.

    Отправки из системы нет и в этой задаче не заводится: письмо формируется в
    почте и отправляется человеком руками (Q010, D035). Выгрузка — ровно мост
    между экраном и почтой, а не тихое начало собственной рассылки.

    Текст приезжает от человека и уезжает ему же обратно, поэтому отдаётся
    вложением, простым текстом и с запретом угадывать тип: без этого браузер
    вправе показать присланное как страницу с адреса самой админки.
    """
    # `mimetype`, а не готовый `Content-Type`: кодировку Flask дописывает сам, и
    # написанная здесь вручную уехала бы в заголовок дважды
    # (`text/plain; charset=utf-8; charset=utf-8` — поймано смоуком снаружи).
    ответ = FlaskResponse(text, mimetype="text/plain")
    ответ.headers["Content-Disposition"] = f'attachment; filename="{_letter_name(inspection_id)}"'
    ответ.headers["X-Content-Type-Options"] = "nosniff"
    return ответ


def _letter_name(inspection_id: str) -> str:
    """Имя файла письма: только то, что не ломает заголовок ответа.

    Идентификатор приходит из адреса, то есть снаружи. Кавычка или перевод
    строки в нём — это уже не имя файла, а дописанный заголовок.
    """
    чистое = "".join(знак for знак in inspection_id if знак.isalnum() or знак in "-_")[:64]
    return f"letter-{чистое or 'inspection'}.txt"


def _kind_title(code: str, lang: str) -> str:
    """Вид проверки словами — из `domain`, а не из своего словаря.

    Своя копия разошлась бы с методикой на первом же новом виде, а неизвестный
    код не должен стирать строку с экрана: показываем сам код.
    """
    try:
        return kind_title(code, lang)
    except ValidationError:
        return code


def _register_frame_ban(app: Flask) -> None:
    """Запретить встраивание страниц админки в чужой документ.

    Заслон происхождения (`origin.refuse_foreign_origin`) закрывает запрос С чужой
    страницы, но не закрывает случай, когда чужая страница показывает НАШУ в
    рамке: документ тогда честно наш, происхождение совпадает, и заслон
    пропустит отправку формы — сняв проверку руками человека, который думал,
    что нажимает что-то другое. Обязательное поле причины делает подмену
    многоходовой, но не невозможной.

    Два заголовка, а не один: `frame-ancestors` — действующее правило, а
    `X-Frame-Options` остаётся ради просмотрщиков, которые его не знают.
    """

    @app.after_request
    def _no_frames(response: Response) -> Response:
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = "frame-ancestors 'none'"
        return response


def _register_errors(app: Flask) -> None:
    """Отказы показываются страницей, а не трассировкой.

    База недоступна — это нормальный исход, а не поломка кода: админка читает
    чужой стенд, и он бывает выключен. Показать причину словами дешевле, чем
    объяснять человеку 500.
    """

    @app.errorhandler(DbError)
    def _db_down(exc: DbError) -> tuple[str, int]:
        return render_template("error_db.html", reason=str(exc)), 503

    @app.errorhandler(MethodologyRefused)
    def _methodology_broken(exc: MethodologyRefused) -> tuple[str, int]:
        """Отказ хранилища методики, дошедший до края, — страницей, а не пятисоткой.

        Отклонённую правку показывает сама страница раздела: там отказ —
        часть работы. Сюда доходит другое: хранилище не читается вовсе
        (каталог снесли, указатель сломан, движка нет). Это ровно тот же род
        события, что недоступная база, и ответ на него такой же — сказать
        причину словами.
        """
        return render_template("methodology/broken.html", reason=str(exc)), 503

    @app.errorhandler(404)
    def _not_found(_: object) -> tuple[str, int]:
        return render_template("error_not_found.html"), 404
