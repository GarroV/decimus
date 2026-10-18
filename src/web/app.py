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

import hashlib
import io
import logging
import uuid
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass, replace
from datetime import date
from typing import Any

import psycopg
from flask import (
    Flask,
    abort,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask import Response as FlaskResponse
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.wrappers import Response

from src.db import directory, request_memo, unit_profiles
from src.db.errors import (
    AcceptError,
    DatabaseTargetError,
    DbError,
    MoveError,
    RetractionError,
    ReviseError,
)
from src.db.migrate import discover_migrations
from src.db.models import InspectionRow
from src.db.pool import shared_connections
from src.db.reports import ReportRef
from src.domain.errors import ValidationError
from src.domain.kinds import kind_title
from src.domain.permissions import is_read_only
from src.domain.second_factor import passkey_auto_enroll
from src.domain.tenants import HQ_TENANT, canonical_tenant
from src.domain.uploads import MAX_UPLOAD_BYTES
from src.report.info_titles import FOUND

from . import (
    action_plans,
    actions_screen,
    assets,
    auth,
    calendar_screen,
    country_page,
    edition,
    grade_explain,
    guard,
    home_page,
    journal,
    letter_draft,
    letter_markup,
    oauth,
    prescriptions,
    ratings,
    registry_period,
    registry_view,
    review,
    revision,
    security_headers,
    security_screen,
    settings_screen,
    swarm_api,
    to_inspect,
    ui_lang,
    unit_add,
    users_screen,
    users_view,
    view,
    walk_auth,
    walk_proxy,
)
from . import inspections as data
from . import methodology as method
from . import methodology_view as mview
from . import unit_card as unit_data
from .config import Settings, load_settings
from .db_refusal import domain_reason, public_reason
from .errors import MethodologyRefused
from .geo_names import city_title, country_title
from .icons import icon
from .origin import refuse_foreign_origin
from .sections import (
    CONTROL_HOME,
    SECTIONS,
    TABBAR_MAX,
    check_registry,
    current_section,
    refused_for,
    section,
    visible_sections,
)
from .security_screen import SECURITY_PATH, is_fresh
from .texts import UI_LANGS, t

logger = logging.getLogger(__name__)

#: Сколько проверок читается в реестр за раз. Предел у чтения обязателен
#: (`queries.DEFAULT_LIMIT`), и здесь он назван явно, чтобы менять его правкой
#: одной строки, а не поиском по коду.
REGISTRY_LIMIT = 100

#: Классы нарушения в форме правки записи на приёмке (D200). Только варианты
#: выбора: допустим ли класс для пункта, решает чек-лист версии
#: (`revision.revise_card`), а вычет за класс — движок.
REVISE_LEVELS = ("D1", "D2", "D3")

#: Предел размера тела запроса. Формы админки маленькие — самая крупная это
#: правленое письмо партнёру, — и неограниченное тело на странице, открытой
#: наружу, означало бы, что вошедший съедает память стенда одной отправкой.
#: Отказ на превышении даёт Flask сам, 413-м.
MAX_BODY_BYTES = 256 * 1024

#: Разделы, под которые в этом модуле зарегистрированы настоящие экраны.
#: Список сверяется с реестром при сборке — расхождение роняет приложение.
SCREENS = (
    "overview",
    "registry",
    "country",
    "ratings",
    "admin",
    "users",
    "settings",
    "actions",
    "calendar",
)


_MEMO_ENVIRON_KEY = "decimus.db_memo_token"


_SHARED_DB_ENVIRON_KEY = "decimus.db_shared"


def _open_memo() -> None:
    # Метка есть у любого запроса: на POST память явно выключена, а не «не тронута».
    читает = request.method in ("GET", "HEAD")
    request.environ[_MEMO_ENVIRON_KEY] = request_memo.begin(enabled=читает)
    if читает:
        # Одно соединение на DSN за весь запрос (#732): чтения страницы не платят
        # выдачей и сбросом пула каждое. Возврат в пул — в `_close_memo`.
        стек = ExitStack()
        стек.enter_context(shared_connections())
        request.environ[_SHARED_DB_ENVIRON_KEY] = стек


def _close_memo(_exc: BaseException | None) -> None:
    token = request.environ.pop(_MEMO_ENVIRON_KEY, None)
    if token is not None:
        request_memo.end(token)
    стек = request.environ.pop(_SHARED_DB_ENVIRON_KEY, None)
    if стек is not None:
        стек.close()


def _install_request_memo(app: Flask) -> None:
    """Справочные чтения за один GET-запрос — один раз, а не по разу на блок (`request_memo`).

    Только `GET`/`HEAD`: запрос, который пишет, читает как раньше, и прочитанное
    до записи не может дожить до чтения после неё.
    """
    app.before_request(_open_memo)
    app.teardown_request(_close_memo)


def create_app(settings: Settings | None = None) -> Flask:
    """Собрать приложение. Отказ окружения — `WebConfigError` до первого запроса."""
    conf = settings or load_settings()
    check_registry(SCREENS)

    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_BODY_BYTES
    assets.install(app)
    _install_request_memo(app)
    _register_context(app, conf)
    # Заслон вешается ДО экранов и намеренно первым: `before_request` идёт в
    # порядке регистрации, и опознание обязано случиться раньше всего, что
    # ходит в базу за данными арендатора.
    auth.install(app, conf)
    _install_origin_gate(app)
    _install_hq_gate(app)
    # Матрица «роль × действие» — один заслон на запись и на разделы (заменил
    # заслоны контроля, гостя и методики).
    guard.install(app)
    # Журнал действий админов (D462): одна точка на весь веб, маршруты о нём не знают.
    journal.install(app, conf)
    _register_sections(app)
    _register_overview(app, conf)
    _register_country(app, conf)
    _register_units(app, conf)
    unit_add.install(app, conf)
    _register_registry(app, conf)
    calendar_screen.install(app, conf)
    letter_draft.install(app, conf)
    actions_screen.install(app, conf)
    action_plans.install(app, conf)
    users_screen.install(app, conf)
    settings_screen.install(app, conf)
    security_screen.install(app, conf)
    prescriptions.install(app, conf)
    ratings.install(app, conf)
    # API чтения для Swarm (#567): свой токен, заслон входа его адреса пропускает.
    swarm_api.install(app, conf)
    # Подключение Claude входом через сайт (D417): только при публичных адресах.
    oauth.install(app, conf)
    _register_methodology(app, conf)
    _mount_checklists(app, conf)
    # Мини-апп обхода пишет в идущие проверки, а админка их только читает:
    # адреса обхода передаются отдельному сервису со своим томом на запись.
    walk_proxy.install(app, upstream=conf.walk_upstream, ui_lang=conf.ui_lang)
    _register_errors(app, conf)
    security_headers.install(app, hsts=conf.hsts, demo=conf.demo)
    return app


def _lang(conf: Settings) -> str:
    """Язык этого запроса: `?lang=` поверх языка профиля, затем стенда (`ui_lang`).

    Язык — параметр, а не константа (`CLAUDE.md`), и переключатель в шапке
    делает это видимым, а не только объявленным. Непонятное значение в адресе
    страницу не роняет: это ввод снаружи, и на границе он приводится к
    допустимому.
    """
    return ui_lang.request_lang(conf.ui_lang)


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
            # Письмо партнёру выводится разметкой ТОЛЬКО через белый список, и
            # чистится в момент вывода: запись в базе не принимается на слово.
            # Шаблон ставит `|safe` строго на результат этой функции.
            "letter_html": letter_markup.sanitize,
            # Разделы ОТФИЛЬТРОВАНЫ по роли, а не спрятаны разметкой:
            # ссылка, ведущая в отказ, выглядит как поломка продукта, а
            # проверка внутри шаблона расходится с заслоном на экране молча.
            "sections": visible_sections(account),
            "tabbar_max": TABBAR_MAX,
            # Текущий раздел — по началу адреса, а не по точному совпадению:
            # карточка проверки `/inspections/<id>` живёт в «Проверках», и
            # панель слева обязана это показывать, как Swarm (D164).
            "current_key": current_section(request.path),
            "icon": icon,
            "tenant": canonical_tenant(account.tenant) if account else "",
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
            # Роль без пишущих действий в матрице (гость УК, D440) только читает:
            # кнопки действий разметка не рисует вовсе, а запись закрывает `guard`.
            "read_only": account is not None and is_read_only(account.role, account.tenant),
            # Матрица для разметки: `may("checklist.edit")` и т. п.
            "may": guard.may,
            "logout_path": auth.LOGOUT_PATH,
            # Роль словами — как должность; у партнёра свои названия (D346).
            "role_key": users_view.role_key,
            "hint_key": users_view.hint_key,
            # Меню учётки ведёт в «Настройки»: подключения, вход, язык (D447).
            "settings_url": f"{request.script_root}{section('settings').path}?lang={lang}",
            # Touch ID на этом устройстве (D485): после входа паролем или Google браузер без
            # метки сам просит сохранить ключ; здесь — только допуск и адреса, решает passkey.js.
            "passkey_here": _passkey_here(account, conf),
        }


def _passkey_here(account: Any, conf: Settings) -> dict[str, str] | None:
    """Адреса и номер сессии для автосохранения Touch ID; `None` — не предлагать.

    Предлагается ролям веба, кроме гостя (`passkey_auto_enroll`), пока вход свежий (окно
    подключения у сервера короткое, а предложение стоит сразу после входа) и не на самом
    экране защиты — там своя кнопка. Ключи выключены на площадке — не предлагать.
    """
    if account is None or request.path == SECURITY_PATH or not conf.webauthn_enabled:
        return None
    if not passkey_auto_enroll(str(account.role)) or not is_fresh(account):
        return None
    base = f"{request.script_root}{SECURITY_PATH}"
    return {
        "base": base,
        "session": str(getattr(account, "session_id", "")),
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
    #: Размерность отбора кодом (`country`, …) — чтобы экран мог вынести её
    #: из полосы чипов в свою колонку (D498). Пусто — обычный чип.
    key: str = ""


def _pick(
    *,
    label: str,
    empty_title: str,
    current: str,
    values: tuple[tuple[str, int | None], ...],
    href: Callable[[str], str],
    title: Callable[[str], str] = str,
    key: str = "",
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
    return Pick(
        label=label, current=current, current_title=выбранное, options=tuple(опции), key=key
    )


def _checklist_names(lang: str) -> dict[str, str]:
    """Имена чек-листов по коду — для строки реестра, где есть только код.

    Хранилище не настроено или отказало — пусто, и строка покажет код: реестр
    проверок не про методику и из-за неё не падает.
    """
    state = method.load_store()
    if state.store is None:
        return {}
    try:
        перечень = method.checklists_overview(state.store, tenant=auth.current_tenant())
    except MethodologyRefused:
        return {}
    return {
        item.code: (item.name_ru if lang == "ru" else item.name_en) or item.name_ru or item.code
        for item in перечень
    }


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
        состав = method.load_composition(state.store, tenant=auth.current_tenant())
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
    """Раздел «Главная» (D378, адрес прежний — `/overview`): сборка в `home_page`."""

    @app.get(section("overview").path)
    def overview() -> str:
        язык = _lang(conf)
        return home_page.render(
            lang=язык,
            limit=REGISTRY_LIMIT,
            pick=_pick,
            item_titles=_item_titles(conf, язык),
        )


def _register_country(app: Flask, conf: Settings) -> None:
    """Раздел «Пиццерии»: работа с одной страной (D260, D262, D467).

    Слева колонка стран и пиццерий, справа шапка, плитки и «Где болит» (шаблон
    «выбор слева — рабочая область справа», D474); сборка в `country_page`.
    Срез живёт в адресе, как на «Главной»: «Грузия, пиццерии, октябрь, Батуми-1
    раскрыта» отправляют коллеге, и он видит ровно это.
    """

    @app.get(section("country").path, endpoint="country_index")
    def country_index() -> Any:
        язык = _lang(conf)
        # Язык переезжает, только если его выбрали в адресе: иначе переход в
        # единственную страну вешал бы `?lang=` умолчания.
        переход = country_page.index_redirect(bool(request.args.get("lang")), язык)
        if переход is not None:
            return переход
        # Рабочая зона не пустует: без страны в адресе справа сразу первая
        # страна колонки (самая большая), в колонке она выделена.
        return country_page.render(
            code=None,
            lang=язык,
            limit=REGISTRY_LIMIT,
            item_titles=_item_titles(conf, язык),
            pick=_pick,
        )

    @app.get(section("country").path + "/<code>", endpoint="country")
    def country(code: str) -> Any:
        язык = _lang(conf)
        # Код страны из адреса — ввод снаружи: регистр приводится, чужое
        # сужает выборку в пустоту, и экран говорит об этом словами, а не 500.
        return country_page.render(
            code=code,
            lang=язык,
            limit=REGISTRY_LIMIT,
            item_titles=_item_titles(conf, язык),
            pick=_pick,
        )


def _unit_profile(code: str | None) -> unit_profiles.Profile | None:
    """Строка свода пиццерий по коду Dodo точки (D374); сбой чтения — блок пуст."""
    if not code:
        return None
    try:
        return unit_profiles.by_code(code)
    except DbError:
        logger.warning("Сведения о пиццерии не прочитались", exc_info=True)
        return None


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
    def unit(unit_id: str) -> str | tuple[str, int] | Response:
        lang = _lang(conf)
        # Справочник спрашивается целиком: точек у сети сотни, отдельный
        # запрос по идентификатору — это новая функция слоя базы ради одной
        # строки, и заводить её стоит тогда, когда список станет дорогим.
        точка = next(
            (u for u in directory.list_units(reach=auth.current_reach()) if u.id == unit_id),
            None,
        )
        if точка is None:
            return render_template("inspections/not_found.html"), 404
        # Партнёр (D508): к пиццерии один путь — экран «Пиццерии» с её списком
        # проверок; старая карточка точки остаётся УК. Старые ссылки не мертвеют.
        if auth.current_tenant() != HQ_TENANT and точка.country:
            return redirect(
                _url("country", code=точка.country, unit=точка.id, lang=request.args.get("lang"))
            )
        снимок = unit_data.load(reach=auth.current_reach(), unit=точка.name, lang=lang)
        if снимок.last is None:
            # Проверок нет — география только в справочнике. Так выглядит
            # пиццерия, только что заведённая из админки (#437).
            снимок = replace(снимок, city=точка.city or "", country=точка.country or "")
        return render_template(
            "units/card.html",
            data=снимок,
            profile=_unit_profile(точка.code),
            show_email=auth.current_tenant() == HQ_TENANT,
            added=request.args.get("added") == "1",
            alias_taken=request.args.get("alias_taken") == "1",
            lang=lang,
            window=unit_data.ОКНО,
            grade_tone=view.grade_tone,
            level_tone=view.level_tone,
            overview_path=section("overview").path,
            registry_path=section("registry").path,
            actions_path=section("actions").path,
            item_titles=_item_titles(conf, lang),
        )


def _unit_href(item: to_inspect.ToCheck, *, lang: str) -> str:
    """Куда ведёт точка из «Где не проведено»: экран пиццерии в «Пиццериях» (УК и партнёр, D508)."""
    if item.unit_id and item.country:
        return _url("country", code=item.country, unit=item.unit_id, lang=lang) + (
            f"#unit-{item.unit_id}"
        )
    if item.unit_id:
        return _url("unit", unit_id=item.unit_id, lang=lang)
    return _url("registry", lang=lang)


def _register_registry(app: Flask, conf: Settings) -> None:
    """Раздел «Проверки»: реестр, карточка, снятие."""

    # Стартовый экран — «Обзор», а не реестр: общая картина прежде списка.
    # Вход тоже ведёт сюда (через `home`), чтобы выбор жил в одном месте.
    @app.get("/")
    def home() -> Response:
        вошедший = auth.current_account()
        if вошедший is not None and not guard.may("view.overview"):
            # «Главной» у контролинга нет (D420) — его стартовый экран «Рейтинги».
            return redirect(url_for(CONTROL_HOME))
        return redirect(url_for("overview"))  # при входе все — на «Главной» (D378)

    @app.get(section("registry").path)
    def registry() -> str:
        # Отбор реестра живёт в адресе ровно по той же причине, что и на
        # обзоре: ссылкой на срез делятся. Буква и вид проверки — коды, и
        # сравниваются как коды; непонятное значение сужает выборку в пустоту,
        # но страницу не роняет.
        # «Проверки» открываются всем временем (D487 вернул умолчание D404 поверх
        # D466): месяц прятал проверки, и их искали; месяц — одной кнопкой.
        период = registry_period.read(request.args, today=date.today(), default_all=True)
        registry_data = data.load_registry(
            reach=auth.current_reach(),
            limit=REGISTRY_LIMIT,
            date_from=период.start,
            date_to=период.end,
        )
        отбор_в = registry_view.Filter(
            grade=request.args.get("grade", "").strip().upper()[:1],
            kind=request.args.get("kind", "").strip()[:20],
            # Страна и город — по справочнику точек, кодами: сюда приводит
            # клик по городу на «Обзоре», и реестр обязан показать ровно эти.
            country=request.args.get("country", "").strip().upper()[:2],
            city=request.args.get("city", "").strip()[:80],
            # Поиск: часть названия пиццерии, без учёта регистра.
            q=request.args.get("q", "").strip()[:80],
        )
        гео = data.load_geography(reach=auth.current_reach())

        def место(row: InspectionRow) -> tuple[str, str]:
            страна_точки, город_точки = гео.get(row.unit_name, ("", ""))
            return страна_точки or "", город_точки or ""

        строки = tuple(row for row in registry_data.rows if отбор_в.keeps(row, место(row)))
        язык = _lang(conf)

        def отбор(**изменения: str) -> str:
            параметры = {**отбор_в.params(), **период.params(), "lang": язык, **изменения}
            return _url("registry", **{к: з for к, з in параметры.items() if з})

        выбрано = request.args.get("inspection", "").strip()[:64]
        панель = _registry_panel(выбрано, conf=conf)
        # «На приёмке» (D466): ждущие вычитки — мимо периода и отбора, самые
        # давние сверху; сколько ждут — днями от даты обхода.
        сегодня = date.today()
        на_приёмке = tuple(
            sorted(registry_data.review, key=lambda row: (row.inspection_date, row.pushed_at))
        )
        ждёт_дней = {row.id: max((сегодня - row.inspection_date).days, 0) for row in на_приёмке}
        чипы = _registry_picks(registry_data.rows, отбор_в, место, отбор, язык)
        return render_template(
            "inspections/list.html",
            registry=registry_data,
            review_rows=на_приёмке,
            # «Где не проведено» (D501): период и отбор страны, города и поиска —
            # те же, что у «Принятых»; список целиком, лишнее свёрнуто в шаблоне.
            to_check=to_inspect.load(
                reach=auth.current_reach(),
                date_from=период.start,
                date_to=период.end,
                country=отбор_в.country,
                city=отбор_в.city,
                query=отбор_в.q,
                top=None,
            ),
            to_check_top=to_inspect.TO_CHECK_TOP,
            unit_href=lambda item: _unit_href(item, lang=язык),
            review_wait=ждёт_дней,
            rows=строки,
            # Страна — колонкой слева (D498), остальные размерности — в блоке фильтров.
            picks=tuple(ч for ч in чипы if ч.key != "country"),
            country_pick=next((ч for ч in чипы if ч.key == "country"), None),
            grade_tone=view.grade_tone,
            kind_title=_kind_title,
            # Чек-лист в строке называется, только когда их в реестре больше
            # одного: иначе это одно и то же слово в каждой строке.
            checklist_names=(
                _checklist_names(язык) if len({row.checklist_code for row in строки}) > 1 else None
            ),
            filters=отбор_в,
            period=период,
            period_title=registry_view.period_title(период, язык),
            period_prev=registry_view.period_link(период, -1, отбор),
            period_next=registry_view.period_link(период, 1, отбор),
            period_quick=registry_view.period_quick(период, date.today(), язык, отбор),
            period_hidden={"lang": язык, **{к: з for к, з in отбор_в.params().items() if з}},
            period_all=отбор(**{"from": "", "to": "", "period": registry_period.ALL}),
            select_url=отбор,
            reset_url=отбор(grade="", kind="", country="", city="", q=""),
            picked=панель.picked,
            card=панель.context,
            card_missing=панель.missing,
            card_failed=панель.failed,
            split_open=панель.explicit,
            split_back=отбор(),
        )

    @app.get(f"{section('registry').path}/<inspection_id>")
    def card(inspection_id: str) -> str | tuple[str, int]:
        return _render_card(inspection_id, conf=conf, notice=None, failure=None)

    @app.get(f"{section('registry').path}/<inspection_id>/report")
    def report(inspection_id: str) -> FlaskResponse | str | tuple[str, int]:
        """Готовый PDF проверки — тот самый файл, что получил аудитор (D204).

        Пересборки нет намеренно: она дала бы второй документ, и вопрос «что
        на руках у партнёра» снова остался бы без ответа (T336). Проверка
        спрашивается ДО файла — она же проверяет арендатора.
        """
        lang = _lang(conf)
        detail = data.load_card(inspection_id, reach=auth.current_reach())
        if detail is None:
            return render_template("inspections/not_found.html"), 404
        try:
            ref = data.load_report(inspection_id, reach=auth.current_reach())
            if ref is None:
                return _card_refusal(
                    inspection_id, conf=conf, text=t("card.report.none", lang), status=404
                )
            # Метка версии — по ссылке на файл, а не по его байтам: совпала —
            # хранилище не читается вовсе (#697, ~300 мс на чтение). Новый отчёт
            # (финальный после приёмки, D203) — новая ссылка и новая метка.
            метка = report_etag(ref)
            if метка in request.if_none_match:
                не_изменён = FlaskResponse(status=304)
                не_изменён.set_etag(метка)
                не_изменён.headers["Cache-Control"] = REPORT_CACHE_CONTROL
                return не_изменён
            файл = data.report_bytes(ref)
        except DbError as exc:
            logger.warning("отчёт проверки %s не выдан: %s", inspection_id, exc)
            return _card_refusal(
                inspection_id, conf=conf, text=t("card.report.failed", lang), status=503
            )
        ответ = send_file(
            io.BytesIO(файл),
            mimetype=ref.content_type,
            as_attachment=True,
            download_name=_report_name(detail.inspection),
        )
        ответ.set_etag(метка)
        ответ.headers["Cache-Control"] = REPORT_CACHE_CONTROL
        return ответ

    @app.get(f"{section('registry').path}/<inspection_id>/photos/<photo_id>")
    def photo(inspection_id: str, photo_id: str) -> FlaskResponse | tuple[str, int]:
        """Сжатая копия кадра записи (D219) — по проверке и арендатору, не по ключу.

        Кадр отдаётся только через проверку этого арендатора: адрес хранилища
        наружу не уходит вовсе, и угаданный идентификатор чужого кадра
        отвечает тем же 404, что несуществующий.
        """
        if not (_is_uuid(inspection_id) and _is_uuid(photo_id)):
            return "", 404
        try:
            копия = data.preview_bytes(inspection_id, photo_id, reach=auth.current_reach())
        except DbError as exc:
            logger.warning("кадр %s проверки %s не выдан: %s", photo_id, inspection_id, exc)
            return "", 503
        if копия is None:
            return "", 404
        ответ = FlaskResponse(копия, mimetype="image/jpeg")
        # Копия неизменна (строка заморожена после выгрузки), поэтому браузер
        # может держать её долго — но только у себя: кадр кухни партнёра не
        # должен оседать в общих кэшах по дороге.
        ответ.headers["Cache-Control"] = "private, max-age=86400"
        return ответ

    @app.get(f"{section('registry').path}/<inspection_id>/letter")
    def letter(inspection_id: str) -> str | tuple[str, int]:
        lang = _lang(conf)
        detail = data.load_card(inspection_id, reach=auth.current_reach())
        if detail is None:
            return render_template("inspections/not_found.html"), 404
        if detail.inspection.is_uploaded:
            # Заведённая задним числом: письма нет (D310), а историческую сверка
            # письма пересчитала бы движком (D332). Отказ до сборки.
            return _card_refusal(
                inspection_id, conf=conf, text=t("letter.uploaded", lang), status=409
            )
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
        # Поле правит РАЗМЕТКУ письма (`letter_markup`): заготовка движка —
        # простой текст и становится разметкой экранированием, записанное
        # письмо уже разметка и проходит белый список заново.
        правится = записанное is not None and not показать_заготовку
        разметка = (
            letter_markup.sanitize(записанное.body)
            if правится and записанное is not None
            else letter_markup.from_plain(собранное.text or "")
        )
        return render_template(
            "inspections/letter.html",
            letter=собранное,
            letter_markup=разметка,
            saved=записанное,
            show_draft=показать_заготовку,
            saved_known=сохранённое_известно,
            own=guard.may("inspection.letter", detail.inspection.tenant_code),
            save_outcome=request.args.get("saved"),
            gmail_outcome=request.args.get("gmail"),
            head=detail.inspection,
            letter_langs=data.LETTER_LANGS,
            letter_lang=письмо_на or detail.inspection.report_lang,
            caveats=view.letter_caveats(собранное.caveats, lang),
            source=None if собранное.source is None else view.letter_source(собранное.source, lang),
        )

    @app.post(f"{section('registry').path}/<inspection_id>/letter/save")
    @guard.action("inspection.letter", object_in_route=True)
    def save_letter(inspection_id: str) -> Response | FlaskResponse | tuple[str, int] | str:
        """Зафиксировать письмо в том виде, в каком его подтвердил человек (T333).

        Отправки из системы по-прежнему нет (Q010, D035): письмо уходит из
        почты руками. Фиксация отвечает не на «отправлено», а на «вот текст,
        который мы считаем отправленным», — и без неё этот вопрос остаётся
        без ответа навсегда.
        """
        refuse_foreign_origin()
        detail = data.load_card(inspection_id, reach=auth.current_reach())
        if detail is None:
            return render_template("inspections/not_found.html"), 404
        отказ = guard.permit("inspection.letter", detail.inspection.tenant_code)
        if отказ is not None:
            return отказ
        if detail.inspection.is_uploaded:
            return _card_refusal(
                inspection_id, conf=conf, text=t("letter.uploaded", _lang(conf)), status=409
            )

        текст = request.form.get("text") or ""
        письмо_на = request.form.get("letter_lang") or detail.inspection.report_lang
        if detail.inspection.on_review:
            # Письмо фиксируется как ушедшее партнёру; по непринятой проверке
            # (D199) такой записи быть не должно. Смотреть письмо можно.
            return redirect(
                url_for(
                    "letter", inspection_id=inspection_id, letter_lang=письмо_на, saved="on_review"
                ),
                code=303,
            )
        вошедший = auth.current_account()
        try:
            data.remember_letter(
                inspection_id,
                tenant=auth.current_tenant(),
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

    @app.post(f"{section('registry').path}/<inspection_id>/retract")
    @guard.action("inspection.retract", object_in_route=True)
    def do_retract(inspection_id: str) -> FlaskResponse | str | tuple[str, int]:
        отказ = _permit_inspection("inspection.retract", inspection_id)
        if отказ is not None:
            return отказ
        refuse_foreign_origin()
        reason = (request.form.get("reason") or "").strip()
        notice: str | None = None
        failure: str | None = None
        try:
            done = data.retract_card(inspection_id, tenant=auth.current_tenant(), reason=reason)
        except RetractionError as exc:
            failure = t("retract.failed", _lang(conf), reason=domain_reason(exc, _lang(conf)))
        else:
            notice = t("retract.done", _lang(conf), photos=done.photos_purged)
        return _render_card(inspection_id, conf=conf, notice=notice, failure=failure)

    @app.post(f"{section('registry').path}/<inspection_id>/accept")
    @guard.action("inspection.accept", object_in_route=True)
    def do_accept(inspection_id: str) -> FlaskResponse | str | tuple[str, int]:
        """Подтвердить проверку на приёмке (D199). Админ УК по своей проверке (D283, D341),
        админ партнёра — свежую проверку своих сотрудников (D367)."""
        отказ = _permit_inspection("inspection.accept", inspection_id)
        if отказ is not None:
            return отказ
        refuse_foreign_origin()
        вошедший = auth.current_account()
        notice: str | None = None
        failure: str | None = None
        try:
            data.accept_card(
                inspection_id,
                tenant=auth.current_tenant(),
                actor=вошедший.login if вошедший else "",
            )
        except AcceptError as exc:
            failure = t("accept.failed", _lang(conf), reason=domain_reason(exc, _lang(conf)))
        else:
            notice = t("accept.done", _lang(conf))
        return _render_card(inspection_id, conf=conf, notice=notice, failure=failure)

    @app.post(f"{section('registry').path}/<inspection_id>/findings/<finding_id>/revise")
    @guard.action("inspection.revise", object_in_route=True)
    def do_revise(inspection_id: str, finding_id: str) -> FlaskResponse | str | tuple[str, int]:
        """Исправить запись ждущей проверки с пересчётом (D200). Админ УК (D341),
        админ партнёра — в свежей проверке своих сотрудников (D367)."""
        отказ = _permit_inspection("inspection.revise", inspection_id)
        if отказ is not None:
            return отказ
        refuse_foreign_origin()
        notice: str | None = None
        failure: str | None = None
        try:
            revision.revise_card(
                inspection_id,
                finding_id,
                tenant=auth.current_tenant(),
                lang=_lang(conf),
                code=request.form.get("code") or "",
                level=request.form.get("level") or "",
                zone=request.form.get("zone") or "",
                text=request.form.get("text") or "",
                reading=request.form.get("reading_c") or "",
            )
        except ReviseError as exc:
            failure = t("revise.failed", _lang(conf), reason=domain_reason(exc, _lang(conf)))
        else:
            notice = t("revise.done", _lang(conf))
        return _render_card(inspection_id, conf=conf, notice=notice, failure=failure)

    @app.post(f"{section('registry').path}/<inspection_id>/findings")
    @guard.action("inspection.revise", object_in_route=True)
    def do_add_finding(inspection_id: str) -> FlaskResponse | str | tuple[str, int]:
        """Добавить запись в ждущую проверку с пересчётом (D465); кадр — по желанию."""
        отказ = _permit_inspection("inspection.revise", inspection_id)
        if отказ is not None:
            return отказ
        refuse_foreign_origin()
        lang = _lang(conf)
        кадр, отказ_кадра = _uploaded_photo(lang)
        if отказ_кадра is not None:
            return _render_card(
                inspection_id,
                conf=conf,
                notice=None,
                failure=t("add.failed", lang, reason=отказ_кадра),
            )
        notice: str | None = None
        failure: str | None = None
        try:
            revision.add_card(
                inspection_id,
                tenant=auth.current_tenant(),
                lang=lang,
                code=request.form.get("code") or "",
                level=request.form.get("level") or "",
                zone=request.form.get("zone") or "",
                text=request.form.get("text") or "",
                photo=кадр,
            )
        except ReviseError as exc:
            failure = t("add.failed", lang, reason=domain_reason(exc, lang))
        else:
            notice = t("add.done", lang)
        return _render_card(inspection_id, conf=conf, notice=notice, failure=failure)

    @app.post(f"{section('registry').path}/<inspection_id>/findings/<finding_id>/photos")
    @guard.action("inspection.revise", object_in_route=True)
    def do_add_photo(inspection_id: str, finding_id: str) -> FlaskResponse | str | tuple[str, int]:
        """Приложить кадр к записи ждущей проверки (D465); с `replace` — вместо старого."""
        отказ = _permit_inspection("inspection.revise", inspection_id)
        if отказ is not None:
            return отказ
        refuse_foreign_origin()
        lang = _lang(conf)
        кадр, отказ_кадра = _uploaded_photo(lang)
        failure: str | None = отказ_кадра
        notice: str | None = None
        if failure is None and кадр is None:
            failure = t("photo.none", lang)
        if failure is None and кадр is not None:
            старый = (request.form.get("replace") or "").strip()
            try:
                if старый:
                    revision.replace_photo(
                        inspection_id,
                        finding_id,
                        старый,
                        tenant=auth.current_tenant(),
                        data=кадр,
                    )
                else:
                    revision.attach_photo(
                        inspection_id, finding_id, tenant=auth.current_tenant(), data=кадр
                    )
            except ReviseError as exc:
                failure = domain_reason(exc, lang)
            else:
                notice = t("photo.replaced" if старый else "photo.added", lang)
        if failure is not None:
            failure = t("photo.failed", lang, reason=failure)
        return _render_card(inspection_id, conf=conf, notice=notice, failure=failure)

    @app.post(f"{section('registry').path}/<inspection_id>/photos/<photo_id>/delete")
    @guard.action("inspection.revise", object_in_route=True)
    def do_delete_photo(inspection_id: str, photo_id: str) -> FlaskResponse | str | tuple[str, int]:
        """Снять кадр с записи ждущей проверки (D465)."""
        отказ = _permit_inspection("inspection.revise", inspection_id)
        if отказ is not None:
            return отказ
        refuse_foreign_origin()
        lang = _lang(conf)
        notice: str | None = None
        failure: str | None = None
        try:
            revision.detach_photo(inspection_id, photo_id, tenant=auth.current_tenant())
        except ReviseError as exc:
            failure = t("photo.failed", lang, reason=domain_reason(exc, lang))
        else:
            notice = t("photo.deleted", lang)
        return _render_card(inspection_id, conf=conf, notice=notice, failure=failure)

    @app.post(f"{section('registry').path}/<inspection_id>/move")
    @guard.action("inspection.move", object_in_route=True)
    def do_move(inspection_id: str) -> FlaskResponse | str | tuple[str, int]:
        """Перенести проверку по дате и пиццерии (D195). Только УК (D341)."""
        отказ = _permit_inspection("inspection.move", inspection_id)
        if отказ is not None:
            return отказ
        refuse_foreign_origin()
        вошедший = auth.current_account()
        notice: str | None = None
        failure: str | None = None
        try:
            перенесено = data.move_card(
                inspection_id,
                tenant=auth.current_tenant(),
                new_date=request.form.get("date") or "",
                new_unit_id=request.form.get("unit") or "",
                reason=request.form.get("reason") or "",
                actor=вошедший.login if вошедший else "",
            )
        except MoveError as exc:
            failure = t("move.failed", _lang(conf), reason=domain_reason(exc, _lang(conf)))
        else:
            notice = t("move.done" if перенесено else "move.same", _lang(conf))
        return _render_card(inspection_id, conf=conf, notice=notice, failure=failure)


def _own(detail: Any) -> bool:
    """Проверка своего пространства: писать можно только её (D283).

    Читать вошедший может шире, чем писать: УК — всю сеть, партнёр — проверки
    УК по пиццериям своей страны (D289). Запись по такой проверке — отказ.
    """
    return auth.is_own(detail.inspection.tenant_code)


def _uploaded_photo(lang: str) -> tuple[bytes | None, str | None]:
    """Кадр из поля `photo` формы: `(байты | None, отказ | None)`.

    Предел — тот же, что у мини-аппа (`MAX_UPLOAD_BYTES`), и только этому
    маршруту: остальные формы держат свой (`MAX_BODY_BYTES`). Пустое поле — не
    отказ: кадр необязателен. Что это изображение, проверяет конвейер кадров
    (`make_preview`), а не расширение имени.
    """
    request.max_content_length = MAX_UPLOAD_BYTES + action_plans.FORM_OVERHEAD_BYTES
    try:
        файл = request.files.get("photo")
        if файл is None or not файл.filename:
            return None, None
        data = файл.stream.read(MAX_UPLOAD_BYTES + 1)
    except RequestEntityTooLarge:
        return None, t("photo.too_big", lang, mb=MAX_UPLOAD_BYTES // (1024 * 1024))
    if len(data) > MAX_UPLOAD_BYTES:
        return None, t("photo.too_big", lang, mb=MAX_UPLOAD_BYTES // (1024 * 1024))
    if not data:
        return None, t("photo.unreadable", lang)
    return data, None


def _install_hq_gate(app: Flask) -> None:
    """Раздел только для УК отвечает партнёру тем же 404, что несуществующий адрес (D264).

    Решает по объявлениям маршрута в матрице (`guard.open_to_tenant`), по
    умолчанию — закрыто; префикс раздела (`sections.refused_for`) — второй слой.
    Заслон на раздел целиком, а не на каждую кнопку внутри: так доступы проще
    держать — это и был довод владельца. Стоит после заслона входа: без вошедшего туда не
    доходит ни один закрытый адрес.
    """

    @app.before_request
    def _только_уК() -> None:
        # Маршрут не нашёлся (`endpoint is None`) — 404/405 даст сам Flask.
        if request.endpoint is None or request.endpoint in auth.OPEN_ENDPOINTS:
            return
        if auth.current_account() is None:
            return
        # Умолчание — закрыто (аудит 12.10, F-004): партнёр идёт только к
        # маршруту, объявленному в матрице открытым его пространству, а не «куда
        # не запретили по префиксу». Префиксный заслон остаётся вторым слоем.
        пространство = auth.current_tenant()
        if canonical_tenant(пространство) != HQ_TENANT and not guard.open_to_tenant(
            app, request.endpoint, request.path, пространство
        ):
            abort(404)
        if refused_for(request.path, auth.current_tenant()):
            abort(404)


def _install_origin_gate(app: Flask) -> None:
    """Любая запись в админку — только со своей же страницы (`refuse_foreign_origin`).

    Заслоном на всё приложение, а не вызовом в каждом маршруте: до 12.10.2026
    заслон держался на том, что каждый POST зовёт его сам, и новый маршрут без
    вызова остался бы открытым для чужой страницы молча (аудит доступа, п.6).
    Вызовы в маршрутах остаются — второй слой. Мимо заслона идут только мини-апп
    обхода (опознание подписью Telegram в заголовке, куки админки до него не
    доезжают), API для сервисов (ключ в заголовке, только чтение) и машинные
    адреса OAuth — регистрация клиента и обмен кода (D417): их зовёт сервер
    Claude без `Origin`, куки входа там не участвуют. Согласие (`/oauth/authorize`)
    — форма человека и идёт под заслоном.
    """
    мимо = walk_auth.ENDPOINTS | swarm_api.ENDPOINTS | oauth.ENDPOINTS

    @app.before_request
    def _запись_только_со_своей_страницы() -> None:
        # Маршрут не нашёлся (404, 405) — записи не будет и так, ответ даст Flask.
        if request.routing_exception is not None:
            return
        if request.method in _READ_METHODS or request.endpoint in мимо:
            return
        refuse_foreign_origin()


#: Безопасные методы: чужой раздел на чтение — 404, на запись — 403.
_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _role() -> str | None:
    """Роль вошедшего — для проверок, которые решает дверь методики (D440)."""
    вошёл = auth.current_account()
    return None if вошёл is None else вошёл.role


def _partner_may_review(detail: Any) -> bool:
    """Свежая проверка сотрудников партнёра — её вычитывает сам партнёр (D367).

    Своя (пространство партнёра, а это значит — проведена его людьми; проверки УК
    и сторонних проверяющих лежат в пространстве УК), из обхода, ещё на приёмке.
    Страну держит охват: карточка вне стран партнёра ему не загрузится.
    """
    проверка = detail.inspection
    return (
        _own(detail)
        and проверка.origin == "field"
        and проверка.on_review
        and not проверка.retracted
    )


def _inspection_may(code: str, detail: Any) -> bool:
    """Может ли вошедший `code` над этой проверкой — для кнопок карточки.

    Граница — пространство самой проверки (`can`); партнёру сверх матрицы —
    только свежая проверка своих сотрудников (D367).
    """
    if not guard.may(code, detail.inspection.tenant_code):
        return False
    return auth.current_tenant() == HQ_TENANT or _partner_may_review(detail)


def _permit_inspection(code: str, inspection_id: str) -> FlaskResponse | None:
    """Заслон записи по проверке: матрица над пространством проверки.

    Вне охвата — 404, как несуществующая: «такой нет» и «вам её не видно»
    снаружи неразличимы. Видимая, но не своя или закрытая роли — 403. Партнёру
    сверх матрицы — только свежая проверка своих сотрудников (D367).
    """
    detail = data.load_card(inspection_id, reach=auth.current_reach())
    if detail is None:
        return render_template("inspections/not_found.html"), 404  # type: ignore[return-value]
    отказ = guard.permit(code, detail.inspection.tenant_code)
    if отказ is not None:
        return отказ  # type: ignore[return-value]
    if auth.current_tenant() != HQ_TENANT and not _partner_may_review(detail):
        return guard.forbidden()  # type: ignore[return-value]
    return None


@dataclass(frozen=True)
class _RegistryPanel:
    """Правая колонка реестра: какая проверка открыта и что о ней известно."""

    picked: str
    context: dict[str, Any] | None
    #: Выбор по адресу есть, а проверки в охвате нет (или её не видно).
    missing: bool
    #: Выбор сделан явно (`?inspection=`): панель справа открыта.
    explicit: bool
    #: Карточка не прочиталась (база ответила отказом) — список при этом жив.
    failed: bool = False


def _registry_panel(chosen: str, *, conf: Settings) -> _RegistryPanel:
    """Карточка в панели справа — только по явному выбору адресом (`?inspection=`).

    Права и данные — та же `_card_context`, что у отдельной карточки. Отказ
    базы на карточке не роняет список: реестр уже прочитан, и панель честно
    говорит, что карточка не открылась. Стенд, смотрящий не в ту базу
    (`DatabaseTargetError`), — не частичный сбой: он уходит наверх и
    показывается страницей с названными базами.
    """
    if not chosen:
        return _RegistryPanel("", None, False, False)
    try:
        контекст = _card_context(chosen, conf=conf, notice=None, failure=None, panel=True)
    except DatabaseTargetError:
        raise
    except DbError as exc:
        logger.warning("карточка проверки %s в реестре не прочиталась: %s", chosen, exc)
        return _RegistryPanel(chosen, None, False, True, failed=True)
    return _RegistryPanel(chosen, контекст, контекст is None, True)


def _registry_picks(
    rows: tuple[InspectionRow, ...],
    current: registry_view.Filter,
    place: Callable[[InspectionRow], tuple[str, str]],
    select: Callable[..., str],
    lang: str,
) -> tuple[Pick, ...]:
    """Чипы отбора реестра — страна, город, буква, вид — со счётом по периоду."""
    чипы = []
    страны = tuple(
        (код, sum(1 for row in rows if place(row)[0] == код))
        for код in sorted({place(row)[0] for row in rows} - {""})
    )
    # Города — только выбранной страны, как и на «Обзоре».
    города = tuple(
        (код, sum(1 for row in rows if place(row)[1] == код))
        for код in sorted(
            {
                place(row)[1]
                for row in rows
                if not current.country or place(row)[0] == current.country
            }
            - {""}
        )
    )
    if страны:
        чипы.append(
            _pick(
                label=t("overview.filter.country", lang),
                empty_title=t("overview.filter.all_countries", lang),
                current=current.country,
                values=страны,
                href=lambda значение: select(country=значение, city=""),
                title=lambda код: country_title(код, lang),
                key="country",
            )
        )
    if города:
        чипы.append(
            _pick(
                label=t("overview.filter.city", lang),
                empty_title=t("overview.filter.all_cities", lang),
                current=current.city,
                values=города,
                href=lambda значение: select(city=значение),
                title=lambda код: city_title(код, lang),
            )
        )
    # Буквы — шкалой, а не по частоте: полоса отбора не должна менять порядок
    # от выборки к выборке (то же правило, что на обзоре).
    чипы.append(
        _pick(
            label=t("overview.filter.grade", lang),
            empty_title=t("overview.filter.all_grades", lang),
            current=current.grade,
            values=tuple((буква, sum(1 for row in rows if row.grade == буква)) for буква in "ABCD"),
            href=lambda значение: select(grade=значение),
        )
    )
    виды = tuple(
        (код, sum(1 for row in rows if row.kind == код))
        for код in dict.fromkeys(row.kind for row in rows)
    )
    if виды:
        чипы.append(
            _pick(
                label=t("registry.col.kind", lang),
                empty_title=t("registry.all_kinds", lang),
                current=current.kind,
                values=виды,
                href=lambda значение: select(kind=значение),
                title=lambda код: _kind_title(код, lang),
            )
        )
    return tuple(чипы)


#: Заголовок, которым `split.js` отличает действие из панели от обычной формы.
PANEL_HEADER = "X-Panel"


def _render_card(
    inspection_id: str, *, conf: Settings, notice: str | None, failure: str | None
) -> str | tuple[str, int]:
    контекст = _card_context(inspection_id, conf=conf, notice=notice, failure=failure)
    if контекст is None:
        return render_template("inspections/not_found.html"), 404
    # Действие из панели реестра (`split.js`) отправлено фоном и ждёт обратно
    # только карточку с итогом, а не страницу целиком (D465). Без скрипта форма
    # идёт обычным путём и получает страницу карточки, как и раньше.
    if request.method == "POST" and request.headers.get(PANEL_HEADER) == "1":
        return render_template("inspections/_panel_fragment.html", c=контекст)
    return render_template("inspections/card.html", c=контекст, **контекст)


def _card_context(
    inspection_id: str,
    *,
    conf: Settings,
    notice: str | None,
    failure: str | None,
    panel: bool = False,
) -> dict[str, Any] | None:
    """Всё, что карточка проверки знает и разрешает; `None` — проверки нет в охвате.

    Одна функция на две поверхности: отдельную страницу карточки и правую
    колонку реестра (`?inspection=`). Права (`may_*`) считаются здесь и только
    здесь — у панели не может оказаться кнопки, которой нет у карточки.

    Панель реестра — это и есть полный просмотр (D465): лист вычитки, кадры,
    информационная часть читаются так же, как для отдельной страницы. Отличие
    одно: принятую проверку в панели не правят, переноса там нет — и список
    точек для него (`panel=True`) не читается.
    """
    detail = data.load_card(inspection_id, reach=auth.current_reach())
    if detail is None:
        return None
    lang = _lang(conf)
    тенант = detail.inspection.tenant_code
    try:
        переносы = data.load_moves(inspection_id, reach=auth.current_reach())
        история_известна = True
    except DbError:
        # История недоступна (например, схема ещё без `0025`) — карточка живёт,
        # а переносить без истории нельзя: форма не показывается.
        переносы = ()
        история_известна = False
    своя = _own(detail)
    можно_переносить = (
        _inspection_may("inspection.move", detail)
        and своя
        and история_известна
        and data.retraction_available()
        and not detail.inspection.retracted
        and not detail.inspection.on_review
    )
    # Подтверждать и править записи — по матрице (`inspection.accept`): УК по своей
    # проверке (D283, D341), админ партнёра — свежую своих сотрудников (D367), и
    # ровно до подтверждения (D199, D200). Ждущую приёмки партнёра УК видит на чтение.
    можно_подтвердить = (
        _inspection_may("inspection.accept", detail)
        and своя
        and data.retraction_available()
        and detail.inspection.on_review
        and not detail.inspection.retracted
    )
    # Лист вычитки — только на приёмке (D199): у принятой проверки вычитывать
    # уже нечего, а чтение чек-листа версии на каждом открытии не бесплатно.
    лист = (
        review.load_sheet(detail.inspection, detail.findings, lang=lang)
        if detail.inspection.on_review
        else None
    )
    # Есть ли PDF — спрашивается при каждом открытии: кнопка, ведущая в отказ,
    # хуже отсутствующей. Отказ базы здесь карточку не роняет, а честно
    # говорит, что наличие отчёта сейчас неизвестно (как у истории переносов).
    try:
        отчёт = data.load_report(inspection_id, reach=auth.current_reach())
        отчёт_известен = True
    except DbError:
        отчёт = None
        отчёт_известен = False
    поля, методика_полей = data.load_info(detail, lang=lang)
    # Кадры — украшение к записи, а не её часть: отказ базы здесь карточку не
    # роняет, записи показываются без кадров, и это сказано словами.
    кадры: dict[str, Any] = {}
    кадры_известны = True
    try:
        кадры = data.load_previews(inspection_id, reach=auth.current_reach())
    except DbError:
        кадры_известны = False
    zone_lines = view.zone_lines(detail.by_zone, lang)
    план, план_известен = action_plans.card_plan(inspection_id)
    # План нужен (D2/D3 у принятой проверки УК), а запроса нет: либо его можно
    # запросить, либо у точки нет страны — тогда только видимая отметка.
    план_нужен = (
        guard.may("plan.manage", тенант)
        and своя
        and план is None
        and план_известен
        and not detail.inspection.on_review
        and not detail.inspection.retracted
        # Заведённая задним числом плана не требует и запроса не открывает (D310).
        and not detail.inspection.is_uploaded
        and action_plans.needs_plan(detail.counts)
    )
    без_страны = план_нужен and action_plans.unit_without_country(inspection_id)
    return dict(
        plan=план,
        plan_known=план_известен,
        # Запрос открывается панелью «Действий» (D527) — у УК и у партнёра тем же адресом.
        plan_link=(
            f"{section('actions').path}?tab=plans&id={план.id}"
            if план is not None
            else section("actions").path
        ),
        plan_today=action_plans.today(),
        plan_state_tones=action_plans.STATE_TONES,
        plan_due_default=action_plans.default_due(),
        plan_needed=план_нужен,
        plan_no_country=без_страны,
        # Запросить вручную (D272) — УК по своей принятой проверке без запроса.
        may_request_plan=(
            guard.may("plan.manage", тенант)
            and своя
            and not detail.inspection.on_review
            and not detail.inspection.retracted
            and not detail.inspection.is_uploaded
        ),
        # Предписание с карточки (решение владельца 11.10.2026): раздел УК, принятая
        # проверка УК. Какие проверки годятся основанием, решает база (`inspection_basis`).
        may_prescribe=(
            guard.may("prescription.manage", тенант)
            and своя
            and not detail.inspection.on_review
            and not detail.inspection.retracted
        ),
        sheet=лист,
        may_accept=можно_подтвердить,
        may_revise=можно_подтвердить and _inspection_may("inspection.revise", detail),
        levels=REVISE_LEVELS,
        report=отчёт,
        report_known=отчёт_известен,
        photos=кадры,
        photos_known=кадры_известны,
        info=поля,
        info_titles_found=методика_полей == FOUND,
        moves=переносы,
        moves_known=история_известна,
        may_move=можно_переносить,
        units=data.load_units(reach=auth.current_reach()) if можно_переносить and not panel else (),
        detail=detail,
        head=detail.inspection,
        zones=zone_lines,
        grade_explain=grade_explain.build(detail, lang),
        loss_zones=view.loss_zones(zone_lines),
        counts=view.count_lines(detail.counts),
        grade_tone=view.grade_tone,
        level_tone=view.level_tone,
        kind=_kind_title(detail.inspection.kind, lang),
        checklist_name=_checklist_names(lang).get(
            detail.inspection.checklist_code, detail.inspection.checklist_code
        ),
        # У исторической издания нет — вместо даты сборки карточка показывает
        # метку прежней методики (D332).
        build_since=None
        if detail.inspection.is_legacy
        else (
            edition.edition_day(detail.inspection.checklist_version)
            or data.load_edition_since(
                reach=auth.current_reach(), version=detail.inspection.checklist_version
            )
        ),
        # Ждущую приёмки не снимают: снятие — для принятой (retract.py), а
        # ошибку на приёмке чинят правкой записи (D200).
        may_retract=data.retraction_available()
        and _inspection_may("inspection.retract", detail)
        and своя,
        own=своя,
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
    @guard.action("checklist.edit")
    def methodology_add() -> str:
        refuse_foreign_origin()
        form = request.form
        итог = _apply(
            conf,
            lambda store, автор: method.add_item(
                store,
                tenant=auth.current_tenant(),
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
    @guard.action("checklist.edit")
    def methodology_edit(code: str) -> str:
        refuse_foreign_origin()
        form = request.form
        итог = _apply(
            conf,
            lambda store, автор: method.edit_item(
                store,
                tenant=auth.current_tenant(),
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
    @guard.action("checklist.edit")
    def methodology_disable(code: str) -> str:
        refuse_foreign_origin()
        итог = _apply(
            conf,
            lambda store, автор: method.disable_item(
                store,
                tenant=auth.current_tenant(),
                author=автор,
                code=code,
                note=request.form.get("note"),
                version_name=request.form.get("version_name"),
            ),
        )
        return _render_methodology(conf, notice=итог.notice, failure=итог.failure, item=code)

    @app.post(f"{путь}/items/<code>/restore")
    @guard.action("checklist.edit")
    def methodology_restore(code: str) -> str:
        refuse_foreign_origin()
        итог = _apply(
            conf,
            lambda store, автор: method.restore_item(
                store,
                tenant=auth.current_tenant(),
                author=автор,
                code=code,
                note=request.form.get("note"),
                version_name=request.form.get("version_name"),
            ),
        )
        return _render_methodology(conf, notice=итог.notice, failure=итог.failure, item=code)

    @app.post(f"{путь}/zones")
    @guard.action("checklist.edit")
    def methodology_zone_add() -> str:
        refuse_foreign_origin()
        form = request.form
        итог = _apply(
            conf,
            lambda store, автор: method.add_zone(
                store,
                tenant=auth.current_tenant(),
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
        return _render_methodology(conf, notice=итог.notice, failure=итог.failure, panel="scoring")

    @app.post(f"{путь}/zones/shares")
    @guard.action("checklist.edit")
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
                tenant=auth.current_tenant(),
                author=автор,
                shares=доли,
                note=request.form.get("note"),
                version_name=request.form.get("version_name"),
            ),
        )
        return _render_methodology(conf, notice=итог.notice, failure=итог.failure, panel="scoring")

    @app.post(f"{путь}/zones/<code>/rename")
    @guard.action("checklist.edit")
    def methodology_zone_rename(code: str) -> str:
        refuse_foreign_origin()
        form = request.form
        итог = _apply(
            conf,
            lambda store, автор: method.rename_zone(
                store,
                tenant=auth.current_tenant(),
                author=автор,
                code=code,
                name_ru=form.get("name_ru"),
                name_en=form.get("name_en"),
                note=form.get("note"),
                version_name=form.get("version_name"),
            ),
        )
        return _render_methodology(conf, notice=итог.notice, failure=итог.failure, panel="scoring")

    @app.post(f"{путь}/zones/<code>/remove")
    @guard.action("checklist.edit")
    def methodology_zone_remove(code: str) -> str:
        refuse_foreign_origin()
        form = request.form
        итог = _apply(
            conf,
            lambda store, автор: method.remove_zone(
                store,
                tenant=auth.current_tenant(),
                author=автор,
                code=code,
                equal_shares=bool(form.get("equal_shares")),
                note=form.get("note"),
                version_name=form.get("version_name"),
            ),
        )
        return _render_methodology(conf, notice=итог.notice, failure=итог.failure, panel="scoring")

    @app.post(f"{путь}/route")
    @guard.action("checklist.edit")
    def methodology_route() -> str:
        refuse_foreign_origin()
        form = request.form
        номера = {ключ[len("order_") :]: form[ключ] for ключ in form if ключ.startswith("order_")}
        сейчас = [код for код in form.getlist("zone") if код]
        итог = _apply(
            conf,
            lambda store, автор: method.set_route_zones(
                store,
                tenant=auth.current_tenant(),
                author=автор,
                zones=mview.route_order(номера, сейчас),
                note=form.get("note"),
                version_name=form.get("version_name"),
            ),
        )
        return _render_methodology(conf, notice=итог.notice, failure=итог.failure, panel="scoring")

    @app.post(f"{путь}/scoring")
    @guard.action("checklist.edit")
    def methodology_scoring() -> str:
        refuse_foreign_origin()
        form = request.form
        итог = _apply(
            conf,
            lambda store, автор: method.set_scoring(
                store,
                tenant=auth.current_tenant(),
                author=автор,
                start_pct=form.get("start_pct"),
                d1=form.get("d1"),
                d2=form.get("d2"),
                repeat_multiplier=form.get("repeat_multiplier"),
                note=form.get("note"),
                version_name=form.get("version_name"),
            ),
        )
        return _render_methodology(conf, notice=итог.notice, failure=итог.failure, panel="scoring")

    @app.post(f"{путь}/publish")
    @guard.action("checklist.publish")
    def methodology_publish() -> str:
        refuse_foreign_origin()
        version = (request.form.get("version") or "").strip()
        state = method.load_store()
        if state.store is None:
            return _render_methodology(conf, notice=None, failure=None)
        try:
            # Публикуется версия ПОКАЗАННОГО чек-листа, а не корня хранилища (#382).
            склад = method.store_for(
                state.store,
                _который(request),
                tenant=auth.current_tenant(),
                space=_которое_пространство(request),
                write=True,
                lang=_lang(conf),
                role=_role(),
            )
            опубликована = method.publish_version(
                склад, tenant=auth.current_tenant(), version=version
            )
        except MethodologyRefused as отказ:
            return _render_methodology(
                conf, notice=None, failure=method.refusal_text(отказ, _lang(conf))
            )
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
    @guard.action("checklist.manage")
    def checklists_create() -> str | Response:
        refuse_foreign_origin()
        form = request.form
        # Форма панели «Методики» (D222) возвращает человека туда же, откуда он заводил.
        с_методики = form.get("back") == "admin"
        state = method.load_store()
        if state.store is None:
            return _render_checklists(conf, notice=None, failure=None)
        if auth.current_tenant() != HQ_TENANT:
            # Чек-листы заводит УК (D283): у партнёра заведения нет — он
            # работает по эталону и читает его.
            отказ_заведения = t("methodology.etalon_readonly", _lang(conf))
            if с_методики:
                return _render_methodology(conf, notice=None, failure=отказ_заведения, panel="new")
            return _render_checklists(conf, notice=None, failure=отказ_заведения)
        try:
            заведён = method.create_checklist(
                state.store,
                tenant=auth.current_tenant(),
                author=_author(conf),
                code=(form.get("code") or "").strip(),
                name_ru=(form.get("name_ru") or "").strip(),
                name_en=(form.get("name_en") or "").strip(),
            )
        except MethodologyRefused as отказ:
            if с_методики:
                return _render_methodology(
                    conf, notice=None, failure=method.refusal_text(отказ, _lang(conf)), panel="new"
                )
            return _render_checklists(
                conf, notice=None, failure=method.refusal_text(отказ, _lang(conf))
            )
        if с_методики:
            # Заведённый с «Методики» открывается сразу: его и собирались наполнять.
            return redirect(_url("methodology", checklist=заведён.code, lang=_lang(conf)))
        return _render_checklists(
            conf,
            notice=t("checklists.created", _lang(conf), checklist=заведён.code),
            failure=None,
        )

    @app.post(f"{путь}/<code>/state")
    @guard.action("checklist.manage")
    def checklists_state(code: str) -> str:
        refuse_foreign_origin()
        state = method.load_store()
        if state.store is None:
            return _render_checklists(conf, notice=None, failure=None)
        try:
            стало = method.set_checklist_state(
                state.store,
                tenant=auth.current_tenant(),
                author=_author(conf),
                code=code,
                space=_которое_пространство(request),
                lang=_lang(conf),
                state=(request.form.get("state") or "").strip(),
                role=_role(),
            )
        except MethodologyRefused as отказ:
            return _render_checklists(
                conf, notice=None, failure=method.refusal_text(отказ, _lang(conf))
            )
        return _render_checklists(
            conf,
            notice=t("checklists.state.set", _lang(conf), checklist=стало.code, state=стало.state),
            failure=None,
        )

    @app.post(f"{путь}/<code>/master")
    @guard.action("checklist.master")
    def checklists_master(code: str) -> str | Response:
        """Метка «главный» (D440): ставят и снимают только админы. Отказ — словами."""
        refuse_foreign_origin()
        state = method.load_store()
        if state.store is None:
            return _render_methodology(conf, notice=None, failure=None)
        пространство = _которое_пространство(request)
        try:
            method.set_checklist_master(
                state.store,
                tenant=auth.current_tenant(),
                author=_author(conf),
                code=code,
                space=пространство,
                lang=_lang(conf),
                on=request.form.get("on") == "1",
                role=_role(),
            )
        except MethodologyRefused as отказ:
            return _render_methodology(
                conf, notice=None, failure=method.refusal_text(отказ, _lang(conf))
            )
        return redirect(
            _url(
                "methodology",
                checklist=code,
                lang=_lang(conf),
                **({"space": пространство} if пространство else {}),
            )
        )

    @app.post(f"{section('admin').path}/bot/<code>")
    @guard.action("checklist.manage")
    def methodology_bot(code: str) -> str | Response:
        """Переключатель панели «Бот»: открыть чек-лист в боте или закрыть (волна 3)."""
        refuse_foreign_origin()
        state = method.load_store()
        if state.store is None:
            return _render_methodology(conf, notice=None, failure=None, panel="bot")
        try:
            method.set_bot_access(
                state.store,
                tenant=auth.current_tenant(),
                author=_author(conf),
                code=code,
                space=_которое_пространство(request),
                lang=_lang(conf),
                on=request.form.get("on") == "1",
                role=_role(),
            )
        except MethodologyRefused as отказ:
            return _render_methodology(
                conf, notice=None, failure=method.refusal_text(отказ, _lang(conf)), panel="bot"
            )
        остаться = (request.args.get("checklist") or "").strip()
        return redirect(
            _url(
                "methodology",
                panel="bot",
                lang=_lang(conf),
                **({"checklist": остаться} if остаться else {}),
            )
        )

    @app.get(f"{путь}/<code>/apply")
    def checklists_apply_preview(code: str) -> str:
        """Разница до применения. Отдельной страницей, а не всплывающим вопросом:
        читать «столько пунктов, такие зоны, такие ставки» надо глазами."""
        state = method.load_store()
        if state.store is None:
            return render_template("methodology/unset.html", missing=state.missing)
        try:
            целевое = method.store_for(
                state.store,
                code,
                tenant=auth.current_tenant(),
                space=_которое_пространство(request),
                write=False,
                lang=_lang(conf),
                role=_role(),
            )
        except MethodologyRefused as отказ:
            return _render_checklists(
                conf, notice=None, failure=method.refusal_text(отказ, _lang(conf))
            )
        return render_template(
            "methodology/apply.html",
            code=code,
            difference=method.checklist_difference(целевое),
            failure=None,
        )

    @app.post(f"{путь}/<code>/apply")
    @guard.action("checklist.apply")
    def checklists_apply(code: str) -> str:
        refuse_foreign_origin()
        state = method.load_store()
        if state.store is None:
            return _render_checklists(conf, notice=None, failure=None)
        try:
            итог = method.apply_checklist(
                state.store,
                tenant=auth.current_tenant(),
                author=_author(conf),
                code=code,
                space=_которое_пространство(request),
                lang=_lang(conf),
                role=_role(),
            )
        except MethodologyRefused as отказ:
            return _render_checklists(
                conf, notice=None, failure=method.refusal_text(отказ, _lang(conf))
            )
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
        перечень = method.checklists_overview(state.store, tenant=auth.current_tenant())
    except MethodologyRefused as отказ:
        return render_template(
            "methodology/checklists.html",
            checklists=[],
            states=method.CHECKLIST_STATES,
            notice=None,
            failure=failure or method.refusal_text(отказ, _lang(conf)),
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


def _которое_пространство(запрос: Any) -> str | None:
    """Пространство чек-листа из адреса (`?space=`) — УК открывает чек-лист партнёра.

    Не названо — `None`: чек-лист ищется в своём пространстве, а у партнёра
    следом в эталоне (`checklist_layout.locate`). Чужое пространство в адресе
    не открывает ничего: `locate` сверяет его с тем, что вошедшему видно.
    """
    return (запрос.args.get("space") or "").strip() or None


def _author(conf: Settings) -> str:
    """Кто правит — для журнала хранилища.

    Заслон без учётки на эти маршруты не пускает вовсе, так что ветка с
    тенантом — не подстраховка «на всякий случай», а честный ответ на случай,
    когда правку однажды позовёт не человек: подписать её именем арендатора
    правдивее, чем пустым местом: подпись «web» говорит, откуда пришла правка.
    """
    account = auth.current_account()
    return account.login if account else "web"


def _apply(conf: Settings, действие: Any) -> _Итог:
    """Сделать правку дверью методики и сказать словами, чем она кончилась."""
    state = method.load_store()
    if state.store is None:
        return _Итог()
    try:
        склад = method.store_for(
            state.store,
            _который(request),
            tenant=auth.current_tenant(),
            space=_которое_пространство(request),
            write=True,
            lang=_lang(conf),
            role=_role(),
        )
        правка = действие(склад, _author(conf))
    except MethodologyRefused as отказ:
        return _Итог(failure=method.refusal_text(отказ, _lang(conf)))
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


#: Панели «Методики» помимо пункта: адрес `?panel=`.
METHODOLOGY_PANELS = ("scoring", "versions", "new", "bot")


def _render_methodology(
    conf: Settings,
    *,
    notice: str | None,
    failure: str | None,
    item: str | None = None,
    panel: str | None = None,
) -> str:
    """Чек-лист: пункты во всю ширину и выезжающая справа панель (D197).

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
        перечень = method.checklists_overview(state.store, tenant=auth.current_tenant())
    except MethodologyRefused as отказ:
        перечень, failure = [], failure or method.refusal_text(отказ, _lang(conf))
    код = _который_показан(перечень, _который(request))
    try:
        колонка = method.checklist_rail(state.store, перечень, tenant=auth.current_tenant())
    except MethodologyRefused:
        колонка = ()
    try:
        склад = method.store_for(
            state.store,
            код,
            tenant=auth.current_tenant(),
            space=_которое_пространство(request),
            write=False,
            lang=lang,
            role=_role(),
        )
    except MethodologyRefused as отказ:
        # Чужой или несуществующий чек-лист — отказ словами поверх эталона,
        # который виден всем (D283): пустой экран читался бы как поломка.
        склад, failure = state.store, failure or method.refusal_text(отказ, _lang(conf))
    try:
        состав = method.load_composition(склад, tenant=auth.current_tenant(), version=попросили)
    except MethodologyRefused as отказ:
        состав = method.load_composition(склад, tenant=auth.current_tenant())
        failure = failure or method.refusal_text(отказ, _lang(conf))
    отбор = mview.parse_filter(request.args)
    выбран = item or (request.args.get("item") or "").strip() or None
    # Пункт из адреса, которого в этой версии нет (старая ссылка, другой
    # чек-лист), — не отказ правки: панель просто не открывается, а экран
    # говорит одной строкой, чего не нашёл. До D217 здесь вставал красный
    # отказ хранилища с именами инструментов агента.
    пропал = None
    if выбран and выбран not in {str(i.get("id", "")) for i in состав.items}:
        пропал, выбран = выбран, None
    новый = request.args.get("new") == "1" and состав.is_latest
    # Панели экрана, которые не про пункт: настройка оценки (зоны, обход,
    # ставки) и перечень версий. До редизайна они жили в «пустой» правой
    # колонке и пропадали, как только выбирали пункт.
    панель = panel or (request.args.get("panel") or "").strip()
    панель = панель if панель in METHODOLOGY_PANELS and not выбран and not новый else ""

    def адрес(**изменения: str) -> str:
        """Адрес этого экрана с тем же чек-листом, версией и отбором.

        Чек-лист не назван в адресе (режим выбора на телефоне) — не называется и
        в ссылках: иначе панель, открытая из списка, закрывалась бы на чек-лист
        по умолчанию, а не обратно на список.
        """
        параметры = {
            "checklist": (код or "") if _который(request) else "",
            "space": _которое_пространство(request) or "",
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
            "space": _которое_пространство(request) or "",
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
            карточка = method.load_item(
                склад, tenant=auth.current_tenant(), code=выбран, version=попросили
            )["item"]
        except MethodologyRefused as отказ:
            failure = failure or method.refusal_text(отказ, _lang(conf))
    # Разница действующей и свежей записанной — по запросу: чтение каждого
    # пункта целиком дорого, а полоса версии и так говорит, что она есть.
    разница: tuple[mview.Change, ...] | None = None
    if request.args.get("diff") == "1" and состав.unpublished:
        try:
            разница = mview.diff_items(
                method.full_items(склад, tenant=auth.current_tenant(), version=состав.current),
                method.full_items(склад, tenant=auth.current_tenant(), version=состав.latest),
            ) + mview.diff_zones(
                method.zones_of_version(
                    склад, tenant=auth.current_tenant(), version=состав.current
                ),
                method.zones_of_version(склад, tenant=auth.current_tenant(), version=состав.latest),
            )
        except MethodologyRefused as отказ:
            failure = failure or method.refusal_text(отказ, _lang(conf))
    открыта_зона = (request.args.get("zone_card") or "").strip()
    зона = next((z for z in состав.zones if z.get("code") == открыта_зона), None)
    обход: list[dict[str, Any]] = []
    if панель == "scoring":
        try:
            обход = list(
                method.load_route(склад, tenant=auth.current_tenant(), version=попросили)["zones"]
            )
        except MethodologyRefused as отказ:
            failure = failure or method.refusal_text(отказ, _lang(conf))
    сводка = (
        data.load_item_usage(reach=auth.current_reach(), code=выбран, checklist=код or "")
        if карточка is not None and выбран
        else None
    )
    раньше, позже = mview.neighbours(видимые, выбран or "")
    # Правка чек-листа (D440): главный правят только админы, остальные — и
    # бизнес-девелопер. Решает та же дверь, что отказывает на записи
    # (`method.store_for`), поэтому кнопки не расходятся с отказом.
    админ = guard.may("checklist.master")
    главный = method.is_master(склад)
    закрыт_по = method.protection_of(склад)
    правит = guard.may("checklist.edit") and (админ or закрыт_по is None)
    return render_template(
        "methodology/index.html",
        composition=состав,
        is_admin=админ,
        master_here=главный,
        can_edit_checklist=правит,
        # Почему только чтение: метка чек-листа или роль без правки (партнёрский аудитор).
        protected_by=закрыт_по or (None if правит else "role"),
        checklists=перечень,
        # Колонка слева (D222). Без чек-листа в адресе экран помечен выбором:
        # на телефоне первым экраном тогда идёт список, а не боевой чек-лист.
        rail=колонка,
        # Своё пространство вошедшего: ссылки на чек-листы другого пространства
        # несут его в адресе, а переключатели бота — только у своих (D283).
        own_space=method.own_space(auth.current_tenant()),
        picking=not _который(request),
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
        plain=mview.plain_question,
        selected=выбран,
        card=карточка,
        usage=сводка,
        changes=разница,
        route_zones=обход,
        zone_card=зона,
        zone_items=dict(mview.zone_options(состав.items, состав.zones)).get(открыта_зона, 0),
        adding=новый,
        panel=панель,
        missing_item=пропал,
        prev_href=адрес(item=раньше) if раньше else None,
        next_href=адрес(item=позже) if позже else None,
        href=адрес,
        action=действие,
        notice=notice,
        failure=failure,
        # Ответ на запись формы идёт по адресу действия (`/admin/items/…`), и
        # меню не узнало бы по нему свой раздел: путь — экранный.
        current_path=url_for("methodology")[len(request.script_root) :],
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


def _is_uuid(value: str) -> bool:
    """Похоже ли на идентификатор. Иначе база отказала бы разбором, а не «нет»."""
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


def _card_refusal(
    inspection_id: str, *, conf: Settings, text: str, status: int
) -> str | tuple[str, int]:
    """Карточка с отказом наверху и кодом ответа отказа, а не 200."""
    страница = _render_card(inspection_id, conf=conf, notice=None, failure=text)
    return страница if isinstance(страница, tuple) else (страница, status)


#: Отчёт держит только браузер читающего (`private`: документ партнёра не
#: оседает в общих кэшах) и сверяет его с сервером при каждом открытии
#: (`no-cache`): после приёмки отчёт заменяется финальным (D203).
REPORT_CACHE_CONTROL = "private, no-cache"


def report_etag(ref: ReportRef) -> str:
    """Метка версии отчёта: путь в хранилище, время и размер сохранения (#697)."""
    основа = f"{ref.storage_path}|{ref.created_at.isoformat()}|{ref.size_bytes}"
    return hashlib.sha256(основа.encode()).hexdigest()[:32]


def _report_name(head: InspectionRow) -> str:
    """Имя файла отчёта для человека: точка и дата, как их ищут в папке загрузок.

    Кавычки и переводы строки из названия точки убраны: название приходит из
    справочника, и в заголовке ответа оно не должно становиться разметкой.
    """
    точка = "".join(знак for знак in head.unit_name if знак.isprintable() and знак not in '"\\/')
    return f"{точка.strip() or 'inspection'} {head.inspection_date}.pdf"


def _kind_title(code: str, lang: str) -> str:
    """Вид проверки словами — из `domain`, а не из своего словаря.

    Своя копия разошлась бы с методикой на первом же новом виде, а неизвестный
    код не должен стирать строку с экрана: показываем сам код.
    """
    try:
        return kind_title(code, lang)
    except ValidationError:
        return code


#: Ответы драйвера, которые означают «код новее схемы», а не отказ базы: код
#: обратился к столбцу или таблице, которых в базе нет. Лечится накатом
#: миграций, и сообщение обязано сказать именно это (#351).
_SCHEMA_LAG_ERRORS = (psycopg.errors.UndefinedColumn, psycopg.errors.UndefinedTable)


def _schema_lags(exc: BaseException) -> bool:
    """Отказ базы на деле — отставшая схема? Смотрит цепочку причин.

    Слой `db` отдаёт наружу только тип ошибки драйвера (в её тексте бывает
    строка подключения), а сам драйверный отказ лежит в `__cause__`. Поэтому
    узнаётся он здесь, по типу, и ни одна строка драйвера на экран не уходит.
    """
    причина: BaseException | None = exc
    while причина is not None:
        if isinstance(причина, _SCHEMA_LAG_ERRORS):
            return True
        причина = причина.__cause__
    return False


def _register_errors(app: Flask, conf: Settings) -> None:
    """Отказы показываются страницей, а не трассировкой.

    База недоступна — это нормальный исход, а не поломка кода: админка читает
    чужой стенд, и он бывает выключен. Показать причину словами дешевле, чем
    объяснять человеку 500.
    """

    @app.errorhandler(DbError)
    def _db_down(exc: DbError) -> tuple[str, int]:
        if _schema_lags(exc):
            return render_template("error_schema.html", total=len(discover_migrations())), 503
        # Расхождение подключений — общими словами, подробности в журнал (#515):
        # карта стенда вошедшему, в том числе партнёру, ни к чему.
        return render_template("error_db.html", reason=public_reason(exc, _lang(conf))), 503

    @app.errorhandler(MethodologyRefused)
    def _methodology_broken(exc: MethodologyRefused) -> tuple[str, int]:
        """Отказ хранилища методики, дошедший до края, — страницей, а не пятисоткой.

        Отклонённую правку показывает сама страница раздела: там отказ —
        часть работы. Сюда доходит другое: хранилище не читается вовсе
        (каталог снесли, указатель сломан, движка нет). Это ровно тот же род
        события, что недоступная база, и ответ на него такой же — сказать
        причину словами.
        """
        return render_template(
            "methodology/broken.html", reason=method.refusal_text(exc, _lang(conf))
        ), 503

    @app.errorhandler(404)
    def _not_found(_: object) -> tuple[str, int]:
        return render_template("error_not_found.html"), 404
