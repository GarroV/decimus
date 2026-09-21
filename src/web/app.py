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
from flask import Response as FlaskResponse
from werkzeug.wrappers import Response

from src.db.errors import DbError, RetractionError
from src.domain.errors import ValidationError
from src.domain.kinds import kind_title

from . import accounts, auth, view
from . import inspections as data
from . import methodology as method
from .config import Settings, load_settings
from .errors import MethodologyRefused
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
SCREENS = ("registry", "admin", "users")


def create_app(settings: Settings | None = None) -> Flask:
    """Собрать приложение. Отказ окружения — `WebConfigError` до первого запроса."""
    conf = settings or load_settings()
    check_registry(SCREENS)

    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_BODY_BYTES
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
    def save_letter(inspection_id: str) -> FlaskResponse | tuple[str, int] | str:
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

    def _только_админ() -> FlaskResponse | None:
        вошедший = auth.current_account()
        if вошедший is not None and вошедший.role == accounts.ROLE_ADMIN:
            return None
        # 403, а не 404: человек вошёл, он здесь свой, и делать вид, что
        # раздела нет, значит отвечать на «мне сюда нельзя?» загадкой.
        return render_template("users/forbidden.html"), 403  # type: ignore[return-value]

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
        отказ = _только_админ()
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
        отказ = _только_админ()
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
        отказ = _только_админ()
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
        current=состав.current,
        needs_name=method.needs_set_name(состав),
        max_note=method.MAX_NOTE,
        notice=notice,
        failure=failure,
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
