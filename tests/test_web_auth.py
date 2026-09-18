from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from flask.testing import FlaskClient
from web_harness import ЛОГИН, ПАРОЛЬ, СВОЙ, ТОКЕН, Учётка, войти, подменить_двери, собрать

from src.web import auth
from src.web import inspections as data

ТЕНАНТ = "default"


@pytest.fixture
def двери(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    return подменить_двери(monkeypatch, tenant=ТЕНАНТ)


@pytest.fixture
def стенд(monkeypatch: pytest.MonkeyPatch, двери: dict[str, list[Any]]) -> Iterator[FlaskClient]:
    """Приложение с подменёнными дверями базы и опознания. Никто ещё не вошёл."""
    monkeypatch.setattr(data, "retraction_available", lambda: True)
    monkeypatch.setattr(data, "load_registry", lambda **_: data.Registry((), True))
    monkeypatch.setattr(data, "load_card", lambda *_a, **_k: None)
    with собрать(tenant=ТЕНАНТ).test_client() as client:
        yield client


def вошёл(стенд: FlaskClient) -> None:
    assert войти(стенд).status_code == 302


def маршруты(стенд: FlaskClient) -> list[tuple[str, str]]:
    """Все адреса приложения, кроме входа и статики, — методом и образцом пути.

    Образцы с параметрами заполняются правдоподобным значением: проверяется
    заслон, а не то, что лежит по адресу.
    """
    собрано: list[tuple[str, str]] = []
    for rule in стенд.application.url_map.iter_rules():
        if rule.endpoint in auth.OPEN_ENDPOINTS:
            continue
        путь = rule.rule.replace("<inspection_id>", "11111111-1111-1111-1111-111111111111")
        for метод in ("GET", "POST"):
            if метод in (rule.methods or set()):
                собрано.append((метод, путь))
    assert собрано, "карта маршрутов пуста — перебор ничего не проверяет"
    return собрано


# --- заслон: без опознания не открывается ничего ----------------------------


def test_каждый_маршрут_админки_закрыт_без_опознания(стенд: FlaskClient) -> None:
    """Перебором по карте маршрутов, а не по списку из головы."""
    for метод, путь in маршруты(стенд):
        ответ = стенд.open(путь, method=метод, headers={"Origin": СВОЙ})
        assert ответ.status_code == 302, f"{метод} {путь} открылся без входа"
        assert auth.LOGIN_PATH in (ответ.headers.get("Location") or ""), (
            f"{метод} {путь} увёл не на форму входа"
        )


def test_неопознанный_видит_форму_входа_а_не_пустую_страницу(стенд: FlaskClient) -> None:
    ответ = стенд.get("/", follow_redirects=True)
    страница = ответ.get_data(as_text=True)
    assert ответ.status_code == 200
    assert 'name="password"' in страница
    assert 'name="login"' in страница


def test_неопознанному_не_видно_ни_строки_истории(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Частичных данных не бывает: дверь реестра без опознания даже не зовут."""
    зовы: list[Any] = []
    monkeypatch.setattr(
        data, "load_registry", lambda **k: зовы.append(k) or data.Registry((), True)
    )
    стенд.get("/inspections", follow_redirects=True)
    assert зовы == []


def test_снятие_проверки_без_опознания_не_доходит_до_двери(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Самое дорогое действие админки необратимо: до него не должно дойти вовсе."""
    зовы: list[Any] = []
    monkeypatch.setattr(data, "retract_card", lambda *a, **k: зовы.append((a, k)))
    ответ = стенд.post(
        "/inspections/11111111-1111-1111-1111-111111111111/retract",
        data={"reason": "любая"},
        headers={"Origin": СВОЙ},
    )
    assert ответ.status_code == 302
    assert зовы == []


def test_форма_входа_открыта_без_опознания(стенд: FlaskClient) -> None:
    """Иначе вход уводил бы на вход, и войти было бы нечем."""
    assert стенд.get(auth.LOGIN_PATH).status_code == 200


def test_статика_открыта_без_опознания(стенд: FlaskClient) -> None:
    """Форма входа обязана быть одетой: стиль ничего о данных не рассказывает."""
    ответ = стенд.get("/static/dodo-ds.css")
    assert ответ.status_code in (200, 404), "статику заслон пропускать обязан"


# --- вход -------------------------------------------------------------------


def test_верный_пароль_впускает(стенд: FlaskClient, двери: dict[str, list[Any]]) -> None:
    вошёл(стенд)
    assert двери["open"] == [ЛОГИН]
    assert стенд.get("/inspections").status_code == 200


def test_кука_подписана_и_недоступна_скриптам(стенд: FlaskClient) -> None:
    ответ = войти(стенд)
    печенье = ответ.headers.get("Set-Cookie") or ""
    assert "HttpOnly" in печенье
    assert "SameSite=Lax" in печенье
    assert ТОКЕН not in печенье, "в куке едет подписанное значение, а не токен открытым текстом"


def test_кука_secure_только_на_https(стенд: FlaskClient) -> None:
    """`Secure` на петле по HTTP закрыл бы вход вовсе, а наружу мы выходим по HTTPS."""
    по_http = стенд.post(
        auth.LOGIN_PATH, data={"login": ЛОГИН, "password": ПАРОЛЬ}, headers={"Origin": СВОЙ}
    )
    assert "Secure" not in (по_http.headers.get("Set-Cookie") or "")

    по_https = стенд.post(
        auth.LOGIN_PATH,
        data={"login": ЛОГИН, "password": ПАРОЛЬ},
        headers={"Origin": "https://localhost", "X-Forwarded-Proto": "https"},
        base_url="https://localhost",
    )
    assert "Secure" in (по_https.headers.get("Set-Cookie") or "")


def test_неверный_пароль_не_впускает(стенд: FlaskClient, двери: dict[str, list[Any]]) -> None:
    ответ = стенд.post(
        auth.LOGIN_PATH,
        data={"login": ЛОГИН, "password": "не тот"},
        headers={"Origin": СВОЙ},
    )
    assert ответ.status_code == 401
    assert двери["open"] == []
    assert стенд.get("/inspections").status_code == 302


def test_отказ_не_говорит_что_именно_не_так(стенд: FlaskClient) -> None:
    """Иначе форма подсказывает перебором, какой логин существует."""
    нет_логина = стенд.post(
        auth.LOGIN_PATH,
        data={"login": "никто", "password": ПАРОЛЬ},
        headers={"Origin": СВОЙ},
    ).get_data(as_text=True)
    нет_пароля = стенд.post(
        auth.LOGIN_PATH,
        data={"login": ЛОГИН, "password": "не тот"},
        headers={"Origin": СВОЙ},
    ).get_data(as_text=True)
    assert нет_логина == нет_пароля


def test_вход_с_чужой_страницы_не_принимается(стенд: FlaskClient) -> None:
    """Тот же заслон происхождения, что у снятия, а не второй свой."""
    ответ = стенд.post(
        auth.LOGIN_PATH,
        data={"login": ЛОГИН, "password": ПАРОЛЬ},
        headers={"Origin": "https://чужой.example"},
    )
    assert ответ.status_code == 403


def test_пароль_не_возвращается_на_страницу_отказа(стенд: FlaskClient) -> None:
    секрет = "пароль-который-нельзя-показывать"
    страница = стенд.post(
        auth.LOGIN_PATH,
        data={"login": ЛОГИН, "password": секрет},
        headers={"Origin": СВОЙ},
    ).get_data(as_text=True)
    assert секрет not in страница


# --- кука: подделка и протухание -------------------------------------------


def test_подделанная_кука_не_впускает(стенд: FlaskClient) -> None:
    стенд.set_cookie(auth.COOKIE_NAME, "подделка", domain="localhost")
    assert стенд.get("/inspections").status_code == 302


def test_кука_живой_подписи_но_мёртвой_сессии_не_впускает(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Подпись говорит «мы это выдавали», а не «это ещё действует»."""
    вошёл(стенд)
    monkeypatch.setattr(auth, "resolve_session", lambda *_a, **_k: None)
    assert стенд.get("/inspections").status_code == 302


def test_сессия_сверяется_на_каждом_запросе(
    стенд: FlaskClient, двери: dict[str, list[Any]]
) -> None:
    """Иначе отзыв учётки начинал бы действовать «после следующего подъёма»."""
    вошёл(стенд)
    двери["resolve"].clear()
    стенд.get("/inspections")
    стенд.get("/inspections")
    assert len(двери["resolve"]) == 2


# --- выход ------------------------------------------------------------------


def test_выход_гасит_сессию_в_базе_а_не_только_куку(
    стенд: FlaskClient, двери: dict[str, list[Any]]
) -> None:
    вошёл(стенд)
    ответ = стенд.post(auth.LOGOUT_PATH, headers={"Origin": СВОЙ})
    assert ответ.status_code == 302
    assert двери["close"] == [ТОКЕН], "выход обязан закрыть сессию на стороне сервера"


def test_после_выхода_страницы_снова_закрыты(стенд: FlaskClient) -> None:
    вошёл(стенд)
    стенд.post(auth.LOGOUT_PATH, headers={"Origin": СВОЙ})
    assert стенд.get("/inspections").status_code == 302


def test_выход_чужой_страницей_не_запускается(стенд: FlaskClient) -> None:
    вошёл(стенд)
    ответ = стенд.post(auth.LOGOUT_PATH, headers={"Origin": "https://чужой.example"})
    assert ответ.status_code == 403


def test_выход_по_ссылке_не_делается(стенд: FlaskClient) -> None:
    """GET на выход — это картинка на чужой странице, выбивающая человека из админки."""
    вошёл(стенд)
    assert стенд.get(auth.LOGOUT_PATH).status_code == 405


# --- граница арендатора -----------------------------------------------------


def test_сессия_чужого_тенанта_не_впускает(
    стенд: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Тенант стенда приходит из окружения, и сверяется он на каждом запросе."""
    вошёл(стенд)
    monkeypatch.setattr(
        auth, "resolve_session", lambda token, *, tenant: None if tenant == ТЕНАНТ else Учётка()
    )
    assert стенд.get("/inspections").status_code == 302


def test_дверь_опознания_зовут_с_тенантом_стенда(
    стенд: FlaskClient, двери: dict[str, list[Any]]
) -> None:
    стенд.post(auth.LOGIN_PATH, data={"login": ЛОГИН, "password": ПАРОЛЬ}, headers={"Origin": СВОЙ})
    assert двери["authenticate"] == [(ЛОГИН, ПАРОЛЬ, ТЕНАНТ)]


def test_вход_за_туннелем_проходит_а_понижение_схемы_нет(стенд: FlaskClient) -> None:
    """Случай публикации (D100, D154): TLS снят туннелем, до сервера доехал HTTP.

    Проверяется ровно та комбинация, которой не было ни в одном тесте до
    разбора безопасности: внутри `http`, снаружи `https`. Браузер за туннелем
    пришлёт `Origin: https://...`, а сервер видит себя по `http` — сравнение
    «как видит сервер» не совпало бы никогда, и заслон отвечал бы 403 на вход,
    выход и снятие проверки, то есть публикация ломала бы админку целиком.

    Вторая половина теста сторожит, чтобы починка не превратилась в дыру:
    понижение схемы (`http` в `Origin` при HTTPS снаружи) — по-прежнему отказ.
    """
    за_туннелем = стенд.post(
        auth.LOGIN_PATH,
        data={"login": ЛОГИН, "password": ПАРОЛЬ},
        headers={"Origin": "https://localhost", "X-Forwarded-Proto": "https"},
    )
    assert за_туннелем.status_code != 403, "заслон происхождения запер вход за туннелем"

    понижение = стенд.post(
        auth.LOGIN_PATH,
        data={"login": ЛОГИН, "password": ПАРОЛЬ},
        headers={"Origin": СВОЙ, "X-Forwarded-Proto": "https"},
    )
    assert понижение.status_code == 403, "понижение схемы обязано оставаться отказом"
