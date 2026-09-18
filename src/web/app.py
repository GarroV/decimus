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

from dataclasses import dataclass
from typing import Any

from flask import Flask, redirect, render_template, request, url_for
from werkzeug.wrappers import Response

from src.db.errors import DbError, RetractionError
from src.domain.errors import ValidationError
from src.domain.kinds import kind_title

from . import auth, view
from . import inspections as data
from . import methodology as method
from .config import Settings, load_settings
from .errors import MethodologyRefused
from .origin import refuse_foreign_origin
from .sections import SECTIONS, check_registry, section
from .texts import UI_LANGS, lang_or_default, t

#: Сколько проверок читается в реестр за раз. Предел у чтения обязателен
#: (`queries.DEFAULT_LIMIT`), и здесь он назван явно, чтобы менять его правкой
#: одной строки, а не поиском по коду.
REGISTRY_LIMIT = 100

#: Разделы, под которые в этом модуле зарегистрированы настоящие экраны.
#: Список сверяется с реестром при сборке — расхождение роняет приложение.
SCREENS = ("registry", "admin")


def create_app(settings: Settings | None = None) -> Flask:
    """Собрать приложение. Отказ окружения — `WebConfigError` до первого запроса."""
    conf = settings or load_settings()
    check_registry(SCREENS)

    app = Flask(__name__)
    _register_context(app, conf)
    # Заслон вешается ДО экранов и намеренно первым: `before_request` идёт в
    # порядке регистрации, и опознание обязано случиться раньше всего, что
    # ходит в базу за данными арендатора.
    auth.install(app, conf)
    _register_sections(app)
    _register_registry(app, conf)
    _register_methodology(app, conf)
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
            "sections": SECTIONS,
            "tenant": conf.tenant,
            "current_path": request.path,
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


def _register_registry(app: Flask, conf: Settings) -> None:
    """Раздел «Проверки»: реестр, карточка, снятие."""

    @app.get("/")
    def home() -> Response:
        return redirect(url_for("registry"))

    @app.get(section("registry").path)
    def registry() -> str:
        registry_data = data.load_registry(tenant=conf.tenant, limit=REGISTRY_LIMIT)
        return render_template(
            "inspections/list.html",
            registry=registry_data,
            retraction_var=data.RETRACTION_URL_VAR,
            grade_tone=view.grade_tone,
            kind_title=_kind_title,
        )

    @app.get(f"{section('registry').path}/<inspection_id>")
    def card(inspection_id: str) -> str | tuple[str, int]:
        return _render_card(inspection_id, conf=conf, notice=None, failure=None)

    @app.post(f"{section('registry').path}/<inspection_id>/retract")
    def do_retract(inspection_id: str) -> str | tuple[str, int]:
        refuse_foreign_origin()
        reason = (request.form.get("reason") or "").strip()
        notice: str | None = None
        failure: str | None = None
        try:
            done = data.retract_card(inspection_id, tenant=conf.tenant, reason=reason)
        except RetractionError as exc:
            failure = str(exc)
        else:
            notice = t("retract.done", _lang(conf), photos=done.photos_purged)
        return _render_card(inspection_id, conf=conf, notice=notice, failure=failure)


def _render_card(
    inspection_id: str, *, conf: Settings, notice: str | None, failure: str | None
) -> str | tuple[str, int]:
    detail = data.load_card(inspection_id, tenant=conf.tenant)
    if detail is None:
        return render_template("inspections/not_found.html"), 404
    lang = _lang(conf)
    return render_template(
        "inspections/card.html",
        detail=detail,
        head=detail.inspection,
        zones=view.zone_lines(detail.by_zone, lang),
        counts=view.count_lines(detail.counts),
        grade_tone=view.grade_tone,
        level_tone=view.level_tone,
        kind=_kind_title(detail.inspection.kind, lang),
        may_retract=data.retraction_available(),
        retraction_var=data.RETRACTION_URL_VAR,
        notice=notice,
        failure=failure,
    )


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
    def methodology_item(code: str) -> str:
        return _render_item(conf, code=code, notice=None, failure=None)

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
                levels=(form.get("levels") or "").strip(),
                code=form.get("code"),
                process_en=form.get("process_en"),
                question_en=form.get("question_en"),
                zones=form.get("zones"),
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
                levels=form.get("levels"),
                zones=form.get("zones"),
                days=form.get("days"),
                criteria=form.get("criteria"),
                note=form.get("note"),
                version_name=form.get("version_name"),
            ),
        )
        return _render_item(conf, code=code, notice=итог.notice, failure=итог.failure)

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
        return _render_item(conf, code=code, notice=итог.notice, failure=итог.failure)

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
        return _render_item(conf, code=code, notice=итог.notice, failure=итог.failure)

    @app.post(f"{путь}/publish")
    def methodology_publish() -> str:
        refuse_foreign_origin()
        version = (request.form.get("version") or "").strip()
        state = method.load_store()
        if state.store is None:
            return _render_methodology(conf, notice=None, failure=None)
        try:
            опубликована = method.publish_version(state.store, tenant=conf.tenant, version=version)
        except MethodologyRefused as отказ:
            return _render_methodology(conf, notice=None, failure=str(отказ))
        return _render_methodology(
            conf,
            notice=t("methodology.published", _lang(conf), version=опубликована),
            failure=None,
        )


@dataclass(frozen=True)
class _Итог:
    """Чем кончилась правка на экране: сообщение или отказ, но не оба."""

    notice: str | None = None
    failure: str | None = None


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
        правка = действие(state.store, _author(conf))
    except MethodologyRefused as отказ:
        return _Итог(failure=str(отказ))
    return _Итог(notice=t("methodology.saved", _lang(conf), version=правка.version))


def _render_methodology(conf: Settings, *, notice: str | None, failure: str | None) -> str:
    """Состав выбранной версии, список версий и формы правки.

    Хранилище не настроено — страница называет незаданные переменные поимённо и
    состава не показывает вовсе: пустая таблица читалась бы как «чек-лист пуст».
    """
    state = method.load_store()
    if state.store is None:
        return render_template("methodology/unset.html", missing=state.missing)
    попросили = (request.args.get("version") or "").strip() or None
    try:
        состав = method.load_composition(state.store, tenant=conf.tenant, version=попросили)
    except MethodologyRefused as отказ:
        состав = method.load_composition(state.store, tenant=conf.tenant)
        failure = failure or str(отказ)
    return render_template(
        "methodology/index.html",
        composition=состав,
        needs_name=method.needs_set_name(состав),
        columns=method.ITEM_COLUMNS,
        kinds=method.ITEM_KINDS,
        max_note=method.MAX_NOTE,
        notice=notice,
        failure=failure,
    )


def _render_item(conf: Settings, *, code: str, notice: str | None, failure: str | None) -> str:
    """Пункт целиком: все колонки, критерии и правка.

    Правка показывается только у самой свежей записанной версии. У старой её
    быть не может: дверь стакает правку на свежую, и форма под старым составом
    обещала бы поправить то, что на экране, а поправила бы другое.
    """
    state = method.load_store()
    if state.store is None:
        return render_template("methodology/unset.html", missing=state.missing)
    попросили = (request.args.get("version") or "").strip() or None
    try:
        карточка = method.load_item(state.store, tenant=conf.tenant, code=code, version=попросили)
    except MethodologyRefused as отказ:
        return _render_methodology(conf, notice=None, failure=str(отказ))
    версия = str(карточка["version"])
    состав = method.load_composition(state.store, tenant=conf.tenant)
    return render_template(
        "methodology/item.html",
        item=карточка["item"],
        version=версия,
        latest=состав.latest,
        needs_name=method.needs_set_name(состав),
        max_note=method.MAX_NOTE,
        notice=notice,
        failure=failure,
    )


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

    @app.errorhandler(404)
    def _not_found(_: object) -> tuple[str, int]:
        return render_template("error_not_found.html"), 404
