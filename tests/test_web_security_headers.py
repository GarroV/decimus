"""Заголовки безопасности админки и шаблоны без встроенного кода (#489).

Ошибка здесь молчит дважды. Снятый заголовок ничего не ломает на экране —
его отсутствие видно только тому, кто им воспользуется. А встроенный
`<script>`, вернувшийся в шаблон, под действующей политикой источников просто
не исполнится: тема перестанет ставиться до отрисовки, кнопка перестанет
нажиматься, и никто не увидит причины. Поэтому сторожатся оба края: каждый
ответ несёт полный набор, и в шаблонах нет кода, который политика запретит.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from flask import Flask
from flask.testing import FlaskClient
from web_harness import СВОЙ, СЕКРЕТ, войти, подменить_двери, собрать

from src.web import action_plans
from src.web import country as country_data
from src.web import inspections as data
from src.web import overview as overview_data
from src.web.app import create_app
from src.web.config import WEB_HSTS_VAR, Settings, load_settings
from src.web.errors import WebConfigError
from src.web.sections import SECTIONS

ТЕНАНТ = "default"
ШАБЛОНЫ = Path(__file__).resolve().parents[1] / "src" / "web" / "templates"

ПУСТАЯ_СЕТЬ = overview_data.Overview(
    units_total=0,
    inspections=(),
    grades=(),
    average=None,
    comparable=True,
    zone_losses=(),
    systemic=(),
    attention=(),
)

#: Части политики, без которых она теряет смысл. Проверяются по отдельности,
#: а не строкой целиком: порядок директив браузеру безразличен.
ОБЯЗАТЕЛЬНЫЕ_ДИРЕКТИВЫ = (
    "default-src 'self'",
    "script-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "frame-ancestors 'none'",
    # «Черновик в Gmail»: форма → 303 на согласие Google, дальше цепочка может
    # уйти на другой поддомен; браузер проверяет form-action на каждом шаге.
    "form-action 'self' https://accounts.google.com https://*.google.com",
)


def _директивы(политика: str) -> dict[str, str]:
    части = (часть.strip() for часть in политика.split(";"))
    return {ч.split(" ", 1)[0]: ч for ч in части if ч}


def _проверить_набор(ответ: object, где: str) -> None:
    заголовки = ответ.headers  # type: ignore[attr-defined]
    политика = заголовки.get("Content-Security-Policy", "")
    директивы = _директивы(политика)
    for нужная in ОБЯЗАТЕЛЬНЫЕ_ДИРЕКТИВЫ:
        assert директивы.get(нужная.split(" ", 1)[0]) == нужная, (где, политика)
    assert "unsafe-inline" not in директивы["script-src"], (где, политика)
    assert "unsafe-eval" not in политика, (где, политика)
    assert заголовки.get("X-Content-Type-Options") == "nosniff", где
    assert заголовки.get("X-Frame-Options") == "DENY", где
    assert заголовки.get("Referrer-Policy") == "strict-origin-when-cross-origin", где
    разрешения = заголовки.get("Permissions-Policy", "")
    for возможность in ("camera=()", "microphone=()", "geolocation=()"):
        assert возможность in разрешения, (где, разрешения)
    # Один заголовок одной строкой: два крючка, поставившие политику каждый
    # свою, дали бы браузеру ПЕРЕСЕЧЕНИЕ политик, а не ту, что написана.
    assert len(заголовки.getlist("Content-Security-Policy")) == 1, где


def _заглушить_данные(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(data, "retraction_available", lambda: True)
    monkeypatch.setattr(data, "load_registry", lambda **_: data.Registry((), True))
    monkeypatch.setattr(overview_data, "load", lambda **_: ПУСТАЯ_СЕТЬ)
    monkeypatch.setattr(country_data, "countries", lambda **_: ())
    monkeypatch.setattr(data, "load_card", lambda *_a, **_k: None)
    monkeypatch.setattr(action_plans.plans, "list_requests", lambda **_: action_plans.EMPTY)


@pytest.fixture
def приложение(monkeypatch: pytest.MonkeyPatch) -> Flask:
    _заглушить_данные(monkeypatch)
    подменить_двери(monkeypatch, tenant=ТЕНАНТ, role="admin")
    app = собрать(tenant=ТЕНАНТ)

    def упасть() -> str:
        raise RuntimeError("непредвиденный отказ")

    # Пятисотая — тоже ответ админки, и заголовки на ней обязаны быть: её
    # страницу показывает тот же браузер.
    app.add_url_rule("/__падение", "падение", упасть)
    app.config["PROPAGATE_EXCEPTIONS"] = False
    return app


@pytest.fixture
def вошедший(приложение: Flask) -> Iterator[FlaskClient]:
    with приложение.test_client() as client:
        assert войти(client).status_code == 302
        yield client


def test_каждый_раздел_несёт_полный_набор(вошедший: FlaskClient) -> None:
    # Act / Assert — все разделы карты, включая заглушки и отказы по роли.
    for раздел in SECTIONS:
        ответ = вошедший.get(раздел.path)
        _проверить_набор(ответ, раздел.path)
        # Отрисованная страница, а не только шаблон: встроенный код мог бы
        # прийти и из макроса, и из строки, собранной в Python.
        assert нарушения_шаблона(ответ.get_data(as_text=True)) == [], раздел.path


@pytest.mark.parametrize(
    ("адрес", "код"),
    [
        ("/", 302),  # редирект в обзор
        ("/нет-такой-страницы", 404),
        ("/inspections/11111111-1111-1111-1111-111111111111", 404),
        ("/__падение", 500),
        ("/static/theme.js", 200),
        ("/static/dodo-ds.css", 200),
    ],
)
def test_редиректы_ошибки_и_статика_тоже(вошедший: FlaskClient, адрес: str, код: int) -> None:
    # Act
    ответ = вошедший.get(адрес)

    # Assert
    assert ответ.status_code == код, адрес
    _проверить_набор(ответ, адрес)


def test_до_входа_и_на_отказе_тоже(приложение: Flask) -> None:
    with приложение.test_client() as client:
        # Act — страница входа, увод на вход и отказ заслона происхождения.
        вход = client.get("/login")
        увод = client.get("/inspections")
        отказ = client.post("/login", headers={"Origin": "https://чужой.пример"})

    # Assert
    assert вход.status_code == 200
    assert увод.status_code == 302
    assert отказ.status_code == 403
    for ответ, где in ((вход, "вход"), (увод, "увод"), (отказ, "отказ")):
        _проверить_набор(ответ, где)


def test_свой_referer_по_прежнему_проходит_заслон(вошедший: FlaskClient) -> None:
    # Arrange — `Referrer-Policy` режет Referer только для ЧУЖИХ адресов; свой
    # уходит целиком, и заслон, которому нет `Origin`, обязан его принять.
    # Act
    ответ = вошедший.post("/logout", headers={"Referer": f"{СВОЙ}/inspections"})

    # Assert
    assert ответ.status_code == 302


def test_hsts_по_умолчанию_не_шлётся(вошедший: FlaskClient) -> None:
    assert "Strict-Transport-Security" not in вошедший.get("/inspections").headers


def test_hsts_шлётся_по_настройке(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange — то же приложение, что у стенда, но с `WEB_HSTS=1`.
    _заглушить_данные(monkeypatch)
    подменить_двери(monkeypatch, tenant=ТЕНАНТ)
    app = create_app(
        Settings(
            host="127.0.0.1", port=8266, tenant=ТЕНАНТ, ui_lang="ru", secret_key=СЕКРЕТ, hsts=True
        )
    )

    # Act
    ответ = app.test_client().get("/login")

    # Assert
    assert ответ.headers["Strict-Transport-Security"] == "max-age=31536000"
    _проверить_набор(ответ, "вход с HSTS")


@pytest.mark.parametrize(("значение", "ждём"), [("", False), ("0", False), ("1", True)])
def test_настройка_hsts_читается(значение: str, ждём: bool) -> None:
    окружение = {"WEB_TENANT": ТЕНАНТ, WEB_HSTS_VAR: значение}
    assert load_settings(окружение).hsts is ждём


@pytest.mark.parametrize("значение", ["yes", "true", "2"])
def test_непонятная_настройка_hsts_отказ_запуска(значение: str) -> None:
    with pytest.raises(WebConfigError, match=WEB_HSTS_VAR):
        load_settings({"WEB_TENANT": ТЕНАНТ, WEB_HSTS_VAR: значение})


# --- шаблоны без встроенного кода -------------------------------------------

#: Комментарий Jinja: текст в нём браузеру не уходит и проверке не подлежит.
_КОММЕНТАРИЙ = re.compile(r"\{#.*?#\}", re.S)
#: Тег `<script>` и его содержимое.
_СКРИПТ = re.compile(r"<script\b([^>]*)>(.*?)</script\s*>", re.S | re.I)
#: Обработчик события атрибутом: ` onclick=`, ` onload =` и т. п.
_ОБРАБОТЧИК = re.compile(r"<[a-zA-Z][^>]*?\son[a-z]+\s*=", re.S)
#: Ссылка-скрипт.
_ССЫЛКА_СКРИПТ = re.compile(r"""(?:href|src|action)\s*=\s*["']?\s*javascript:""", re.I)


def нарушения_шаблона(текст: str) -> list[str]:
    """Что в шаблоне политика источников исполнять не станет."""
    чистый = _КОММЕНТАРИЙ.sub("", текст)
    найдено: list[str] = []
    for совпадение in _СКРИПТ.finditer(чистый):
        атрибуты, тело = совпадение.group(1), совпадение.group(2)
        if "src=" not in атрибуты or тело.strip():
            найдено.append(f"встроенный скрипт: {совпадение.group(0)[:80]!r}")
    найдено.extend(
        f"обработчик атрибутом: {м.group(0)[-40:]!r}" for м in _ОБРАБОТЧИК.finditer(чистый)
    )
    найдено.extend(f"javascript:-ссылка: {м.group(0)!r}" for м in _ССЫЛКА_СКРИПТ.finditer(чистый))
    return найдено


def test_в_шаблонах_нет_встроенного_кода() -> None:
    # Arrange
    шаблоны = sorted(ШАБЛОНЫ.rglob("*.html"))
    assert шаблоны, "шаблоны не найдены — проверка ничего бы не проверила"

    # Act
    нарушения = {
        str(путь.relative_to(ШАБЛОНЫ)): найдено
        for путь in шаблоны
        if (найдено := нарушения_шаблона(путь.read_text(encoding="utf-8")))
    }

    # Assert
    assert not нарушения, нарушения


@pytest.mark.parametrize(
    "порча",
    [
        "<script>alert(1)</script>",
        '<script type="module">x()</script>',
        '<script src="/static/a.js">x()</script>',
        '<button type="button" onclick="x()">',
        "<body onload='x()'>",
        '<a href="javascript:x()">',
    ],
)
def test_проверка_шаблонов_ловит_встроенный_код(порча: str) -> None:
    # Порча: та же проверка на заведомо испорченном шаблоне обязана покраснеть.
    assert нарушения_шаблона(f"<div>{порча}</div>")


def test_проверка_шаблонов_пропускает_разрешённое() -> None:
    чистое = (
        "{# <script>в комментарии</script> onclick= #}"
        "<script src=\"{{ url_for('static', filename='theme.js') }}\"></script>"
        '<script src="/static/nav.js" defer></script>'
        '<a href="/x" data-online="1">'
    )
    assert нарушения_шаблона(чистое) == []
