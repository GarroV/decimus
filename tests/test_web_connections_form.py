"""Разбор формы «Подключить сервис» (D425): что попадёт в `api.tokens` и что отбивается до базы.

Ядро безопасности: форма — ввод снаружи, а права, страны и срок ключа держат
доступ к данным всей сети. Каждая проверка здесь прогонялась на сломанной копии
(проверка убрана — тест падает с названием отказа).
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from werkzeug.datastructures import MultiDict

from src.db.api_access import SCOPES
from src.web import connections_form
from src.web.connections_form import Draft, Refusal
from src.web.texts import TEXTS

СЕГОДНЯ = date(2026, 10, 12)
СТРАНЫ = frozenset({"GE", "AM", "RS"})


def _форма(**поля: object) -> MultiDict[str, str]:
    форма: MultiDict[str, str] = MultiDict()
    основа: dict[str, object] = {
        "code": "swarm",
        "title": "Swarm",
        "scope": ["ratings:scores"],
        **поля,
    }
    for ключ, значение in основа.items():
        for v in значение if isinstance(значение, list) else [значение]:
            форма.add(ключ, str(v))
    return форма


def _разобрать(форма: MultiDict[str, str], **kw: object) -> Draft | Refusal:
    параметры: dict[str, object] = {
        "known_countries": СТРАНЫ,
        "today": СЕГОДНЯ,
        "with_code": True,
        **kw,
    }
    return connections_form.parse(форма, **параметры)  # type: ignore[arg-type]


def test_верный_ввод_становится_черновиком() -> None:
    итог = _разобрать(
        _форма(
            contact="  ops@example.org ",
            scope=["ratings:scores", "maps:ratings", "ratings:scores"],
            countries="ge, am",
            expires="2026-12-31",
        )
    )
    assert итог == Draft(
        consumer="swarm",
        title="Swarm",
        contact="ops@example.org",
        scopes=("ratings:scores", "maps:ratings"),
        countries=("GE", "AM"),
        expires_at=datetime(2026, 12, 31, 23, 59, 59, tzinfo=UTC),
    )


def test_пустые_страны_и_срок_значат_вся_сеть_и_бессрочно() -> None:
    итог = _разобрать(_форма(countries="  ", expires="", contact=""))
    assert isinstance(итог, Draft)
    assert итог.countries is None and итог.expires_at is None and итог.contact is None


@pytest.mark.parametrize(
    ("поля", "ждём"),
    [
        ({"scope": []}, "scopes_none"),
        ({"scope": ["ratings:write"]}, "scopes_unknown"),
        ({"scope": ["ratings:scores", "admin"]}, "scopes_unknown"),
        ({"code": "Swarm"}, "code"),
        ({"code": "s"}, "code"),
        ({"code": "-swarm"}, "code"),
        ({"code": "swarm_1"}, "code"),
        ({"code": "a" * 33}, "code"),
        ({"code": ""}, "code"),
        ({"title": "   "}, "name_required"),
        ({"title": "н" * 81}, "name_long"),
        ({"contact": "к" * 121}, "contact_long"),
        ({"countries": "GE ZZ"}, "country_unknown"),
        ({"countries": "GEO"}, "country_unknown"),
        ({"countries": "G1"}, "country_unknown"),
        ({"expires": "завтра"}, "expires_bad"),
        ({"expires": "2026-02-30"}, "expires_bad"),
        ({"expires": "2026-10-11"}, "expires_past"),
        ({"expires": "2026-10-12"}, "expires_past"),
    ],
)
def test_отказы_до_базы(поля: dict[str, object], ждём: str) -> None:
    итог = _разобрать(_форма(**поля))
    assert isinstance(итог, Refusal), f"ввод {поля} принят, а должен быть отказ «{ждём}»: {итог}"
    assert итог.key == ждём


def test_завтрашний_срок_допустим() -> None:
    assert isinstance(_разобрать(_форма(expires="2026-10-13")), Draft)


def test_неизвестная_страна_названа_в_отказе() -> None:
    итог = _разобрать(_форма(countries="GE zz KZ"))
    assert isinstance(итог, Refusal)
    assert итог.params == {"codes": "ZZ KZ"}


def test_страна_не_сверяется_со_справочником_без_справочника() -> None:
    """Пустой справочник не пропускает ничего: «не знаю стран» не значит «все можно»."""
    итог = _разобрать(_форма(countries="GE"), known_countries=frozenset())
    assert isinstance(итог, Refusal) and итог.key == "country_unknown"


def test_при_правке_код_берётся_у_сервиса_а_не_из_формы() -> None:
    итог = _разобрать(_форма(code="чужой код!"), with_code=False, code="swarm")
    assert isinstance(итог, Draft) and итог.consumer == "swarm"


def test_сегодняшний_срок_можно_оставить_при_правке() -> None:
    форма = _форма(expires="2026-10-12")
    assert isinstance(_разобрать(форма), Refusal)
    assert isinstance(_разобрать(форма, with_code=False, code="swarm", keep_expiry=СЕГОДНЯ), Draft)


def test_у_каждого_права_есть_подписи_на_экране() -> None:
    """Право без подписи на экране — переключатель-загадка или падение страницы."""
    нет = [
        f"connections.scope.{вид}.{код}"
        for код in SCOPES
        for вид in ("short", "name", "hint")
        if f"connections.scope.{вид}.{код}" not in TEXTS
    ]
    assert нет == [], f"нет подписей прав: {нет}"


def test_у_каждого_отказа_формы_есть_текст() -> None:
    ключи = ["code", "name_required", "name_long", "contact_long", "scopes_none", "scopes_unknown"]
    ключи += ["country_unknown", "expires_bad", "expires_past", "gone", "db", "countries_db"]
    нет = [k for k in ключи if f"connections.err.{k}" not in TEXTS]
    assert нет == [], f"нет текстов отказов: {нет}"
