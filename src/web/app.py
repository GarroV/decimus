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

from typing import Any
from urllib.parse import urlsplit

from flask import Flask, abort, redirect, render_template, request, url_for
from werkzeug.wrappers import Response

from src.db.errors import DbError, RetractionError
from src.domain.errors import ValidationError
from src.domain.kinds import kind_title

from . import inspections as data
from . import view
from .config import Settings, load_settings
from .sections import SECTIONS, check_registry, section
from .texts import UI_LANGS, lang_or_default, t

#: Сколько проверок читается в реестр за раз. Предел у чтения обязателен
#: (`queries.DEFAULT_LIMIT`), и здесь он назван явно, чтобы менять его правкой
#: одной строки, а не поиском по коду.
REGISTRY_LIMIT = 100

#: Разделы, под которые в этом модуле зарегистрированы настоящие экраны.
#: Список сверяется с реестром при сборке — расхождение роняет приложение.
SCREENS = ("registry",)


def create_app(settings: Settings | None = None) -> Flask:
    """Собрать приложение. Отказ окружения — `WebConfigError` до первого запроса."""
    conf = settings or load_settings()
    check_registry(SCREENS)

    app = Flask(__name__)
    _register_context(app, conf)
    _register_sections(app)
    _register_registry(app, conf)
    _register_errors(app)
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
        return {
            "lang": lang,
            "langs": UI_LANGS,
            "t": lambda key, **params: t(key, lang, **params),
            "sections": SECTIONS,
            "tenant": conf.tenant,
            "current_path": request.path,
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
        _refuse_foreign_origin()
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


def _kind_title(code: str, lang: str) -> str:
    """Вид проверки словами — из `domain`, а не из своего словаря.

    Своя копия разошлась бы с методикой на первом же новом виде, а неизвестный
    код не должен стирать строку с экрана: показываем сам код.
    """
    try:
        return kind_title(code, lang)
    except ValidationError:
        return code


def _refuse_foreign_origin() -> None:
    """Отклонить POST, пришедший с чужой страницы.

    Аутентификации у админки нет, а снятие проверки необратимо убирает кадры из
    хранилища — то есть чужая страница, открытая в том же браузере, могла бы
    это запустить одним скрытым запросом. Сверка `Origin` с адресом запроса
    закрывает ровно этот случай и не требует ни сессии, ни секрета: заголовок
    браузер ставит сам и подделать его со страницы нельзя.
    """
    origin = request.headers.get("Origin")
    if origin is None:
        return
    if urlsplit(origin).netloc != request.host:
        abort(403)


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
