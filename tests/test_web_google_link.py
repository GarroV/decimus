"""Своя почта Google из «Настроек» (D447, D450, D430) — уровень страниц.

Сети нет: обмен кода подменён двойником, база — двойником, который держит то же,
что функции `0061` (метка одноразовая и принадлежит сессии, начавшей заход;
почта уникальна). Проверяется то, что делаем МЫ: чья учётка, чья почта годится,
в каком порядке и что видит человек.
"""

from __future__ import annotations

from collections.abc import Iterator
from urllib.parse import parse_qs, urlsplit

import pytest
from flask.testing import FlaskClient
from web_harness import СВОЙ, ТОКЕН, Сессия, Учётка, войти, подменить_двери, собрать

from src.db import web_own_profile
from src.web import auth, google_link
from src.web.google_auth import GoogleAuthError, GoogleIdentity, GoogleSettings

ЗАГОЛОВКИ = {"Origin": СВОЙ}
ПОЧТА_УК = "director@dodobrands.io"
ПОЧТА_ЛИЧНАЯ = "director.home@gmail.com"
ЗАНЯТАЯ = "taken@gmail.com"
ДРУГОЙ_ТОКЕН = "сессия-другого-человека"

РЕКВИЗИТЫ = GoogleSettings(
    client_id="наш-клиент.apps.googleusercontent.com",
    client_secret="секрет-набора",
    redirect_uri="https://стенд.example/auth/google/callback",
)


class База:
    """Двойник функций `0061`: что держит база, то держит и он."""

    def __init__(self) -> None:
        self.метки: dict[str, str] = {}
        self.погашены: set[str] = set()
        self.привязано: dict[str, str] = {}
        self.finish: list[tuple[str, str, str]] = []
        self.языки: list[tuple[str, str]] = []
        self.сбой = False

    def begin(self, token: str, *, state: str, ttl_seconds: int) -> bool:
        self.метки[state] = token
        return True

    def finish_link(self, token: str, *, state: str, email: str) -> str:
        self.finish.append((token, state, email))
        if self.метки.get(state) != token or state in self.погашены:
            return "state"
        self.погашены.add(state)
        if email == ЗАНЯТАЯ:
            return "taken"
        self.привязано[token] = email
        return "ok"

    def unlink(self, token: str, *, current: str) -> str:
        return "ok" if current == "верный-пароль" else "denied"

    def set_lang(self, token: str, lang: str) -> bool:
        if self.сбой:
            from src.db.errors import AccessError

            raise AccessError("двойник: база молчит")
        self.языки.append((token, lang))
        return True


class Обмен:
    """Двойник обмена кода: отдаёт то, что «сказал Google», с `nonce` из ухода."""

    def __init__(self) -> None:
        self.почта = ПОЧТА_УК
        self.домен = "dodobrands.io"
        self.подтверждена = True
        self.nonce = ""
        self.подменить_nonce: str | None = None
        self.звали = 0

    def __call__(self, settings: GoogleSettings, *, code: str) -> GoogleIdentity:
        self.звали += 1
        if code == "сломанный":
            raise GoogleAuthError("двойник: Google отказал")
        return GoogleIdentity(
            email=self.почта,
            email_verified=self.подтверждена,
            hosted_domain=self.домен,
            nonce=self.подменить_nonce if self.подменить_nonce is not None else self.nonce,
        )


@pytest.fixture
def база(monkeypatch: pytest.MonkeyPatch) -> База:
    двойник = База()
    monkeypatch.setattr(web_own_profile, "begin_google_link", двойник.begin)
    monkeypatch.setattr(web_own_profile, "finish_google_link", двойник.finish_link)
    monkeypatch.setattr(web_own_profile, "unlink_google", двойник.unlink)
    monkeypatch.setattr(web_own_profile, "set_web_lang", двойник.set_lang)
    return двойник


@pytest.fixture
def обмен(monkeypatch: pytest.MonkeyPatch) -> Обмен:
    двойник = Обмен()
    monkeypatch.setattr(auth, "exchange_code", двойник)
    return двойник


def _стенд(
    monkeypatch: pytest.MonkeyPatch,
    *,
    tenant: str = "HQ",
    role: str = "admin",
    email: str | None = None,
    google: bool = True,
) -> Iterator[FlaskClient]:
    подменить_двери(monkeypatch, tenant=tenant, role=role)
    if google:
        monkeypatch.setattr(auth, "load_google_settings", lambda *_, **__: РЕКВИЗИТЫ)
    with собрать(tenant="HQ").test_client() as client:
        assert войти(client).status_code == 302
        # Вошли без почты (с ней паролем не входят, D450), дальше сессия — с ней.
        monkeypatch.setattr(
            auth,
            "resolve_session",
            lambda token: Учётка(tenant=tenant, role=role, email=email) if token == ТОКЕН else None,
        )
        yield client


@pytest.fixture
def ук(monkeypatch: pytest.MonkeyPatch) -> Iterator[FlaskClient]:
    yield from _стенд(monkeypatch, tenant="HQ", role="admin")


@pytest.fixture
def партнёр(monkeypatch: pytest.MonkeyPatch) -> Iterator[FlaskClient]:
    yield from _стенд(monkeypatch, tenant="GE", role="auditor")


def начать(client: FlaskClient, обмен: Обмен) -> str:
    """Нажать «Продолжить в Google»; вернуть метку, как её увидит Google."""
    ответ = client.post("/settings/google-link", headers=ЗАГОЛОВКИ)
    assert ответ.status_code == 302, ответ.get_data(as_text=True)[:300]
    параметры = parse_qs(urlsplit(ответ.headers["Location"]).query)
    обмен.nonce = параметры["nonce"][0]
    return параметры["state"][0]


def вернуться(client: FlaskClient, метка: str, **ещё: str) -> str:
    """Возврат от Google; ответ — исход в адресе «Настроек» (или путь, куда увели)."""
    запрос = {"state": метка, "code": "код", **ещё}
    ответ = client.get(auth.GOOGLE_CALLBACK_PATH, query_string=запрос)
    assert ответ.status_code == 302, (ответ.status_code, ответ.get_data(as_text=True)[:200])
    адрес = urlsplit(ответ.headers["Location"])
    if адрес.path != "/settings":
        return адрес.path
    return parse_qs(адрес.query).get(google_link.RESULT_PARAM, [""])[0]


# ── Начало ──────────────────────────────────────────────────────────────


def test_начало_только_со_своей_страницы(ук: FlaskClient, база: База) -> None:
    ответ = ук.post("/settings/google-link", headers={"Origin": "https://чужой.example"})

    assert ответ.status_code == 403
    assert not база.метки


def test_начало_пишет_метку_за_своей_сессией_и_шлёт_nonce(
    ук: FlaskClient, база: База, обмен: Обмен
) -> None:
    метка = начать(ук, обмен)

    assert база.метки == {метка: ТОКЕН}
    assert обмен.nonce == google_link.nonce_for(метка)


def test_уже_привязанной_учётке_к_google_не_уводят(
    monkeypatch: pytest.MonkeyPatch, база: База
) -> None:
    for client in _стенд(monkeypatch, email=ПОЧТА_УК):
        ответ = client.post("/settings/google-link", headers=ЗАГОЛОВКИ)

        assert ответ.status_code == 302 and "google=already" in ответ.headers["Location"]
        assert not база.метки


# ── Возврат: кто и какая почта ─────────────────────────────────────────


def test_ук_привязывает_рабочий_аккаунт(ук: FlaskClient, база: База, обмен: Обмен) -> None:
    метка = начать(ук, обмен)

    assert вернуться(ук, метка) == "linked"
    assert база.finish == [(ТОКЕН, метка, ПОЧТА_УК)]


def test_ук_не_привязывает_личный_аккаунт(ук: FlaskClient, база: База, обмен: Обмен) -> None:
    """D430/D450: учётке УК — только `hd` из GOOGLE_HQ_DOMAINS, личный на тот же адрес — нет."""
    обмен.домен = ""
    метка = начать(ук, обмен)

    assert вернуться(ук, метка) == "domain"
    assert база.finish == [], "почта без домена компании дошла до записи"


def test_ук_не_привязывает_чужой_домен(ук: FlaskClient, база: База, обмен: Обмен) -> None:
    обмен.почта, обмен.домен = "someone@other-company.com", "other-company.com"
    метка = начать(ук, обмен)

    assert вернуться(ук, метка) == "domain"
    assert база.finish == []


def test_партнёр_привязывает_любой_подтверждённый(
    партнёр: FlaskClient, база: База, обмен: Обмен
) -> None:
    """D430: партнёрам домен не нужен — годится подтверждённая почта."""
    обмен.почта, обмен.домен = ПОЧТА_ЛИЧНАЯ, ""
    метка = начать(партнёр, обмен)

    assert вернуться(партнёр, метка) == "linked"
    assert база.finish == [(ТОКЕН, метка, ПОЧТА_ЛИЧНАЯ)]


def test_неподтверждённая_почта_не_привязывается(
    партнёр: FlaskClient, база: База, обмен: Обмен
) -> None:
    обмен.почта, обмен.домен, обмен.подтверждена = ПОЧТА_ЛИЧНАЯ, "", False
    метка = начать(партнёр, обмен)

    assert вернуться(партнёр, метка) == "unverified"
    assert база.finish == []


def test_занятая_почта_названа_прямо(партнёр: FlaskClient, база: База, обмен: Обмен) -> None:
    обмен.почта, обмен.домен = ЗАНЯТАЯ, ""
    метка = начать(партнёр, обмен)

    assert вернуться(партнёр, метка) == "taken"
    страница = партнёр.get("/settings?google=taken").get_data(as_text=True)
    assert "уже привязана к другой учётке" in страница


def test_токен_чужого_захода_не_привязывает(ук: FlaskClient, база: База, обмен: Обмен) -> None:
    """`nonce` не тот — токен выписан на другой заход, даже если метка верна."""
    метка = начать(ук, обмен)
    обмен.подменить_nonce = google_link.nonce_for("другая-метка")

    assert вернуться(ук, метка) == "state"
    assert база.finish == []


def test_возврат_в_чужой_сессии_ничего_не_привязывает(
    monkeypatch: pytest.MonkeyPatch, база: База, обмен: Обмен
) -> None:
    """Заход начат одним человеком, вернулся в браузер с сессией другого.

    Учётку выбирает сессия ВОЗВРАТА, а база не гасит метку чужой сессии: ничего
    не привязано ни тому, ни другому.
    """
    for client in _стенд(monkeypatch, tenant="GE", role="auditor"):
        обмен.почта, обмен.домен = ПОЧТА_ЛИЧНАЯ, ""
        метка = начать(client, обмен)
        monkeypatch.setattr(auth, "open_session", lambda account: Сессия(ДРУГОЙ_ТОКЕН))
        monkeypatch.setattr(
            auth,
            "resolve_session",
            lambda token: Учётка(login="petr", tenant="GE") if token == ДРУГОЙ_ТОКЕН else None,
        )
        monkeypatch.setattr(auth, "authenticate", lambda login, password: Учётка(tenant="GE"))
        войти(client)

        assert вернуться(client, метка) == "state"
        assert база.finish == [(ДРУГОЙ_ТОКЕН, метка, ПОЧТА_ЛИЧНАЯ)]
        assert база.привязано == {}


def test_возврат_без_сессии_уводит_на_вход(ук: FlaskClient, база: База, обмен: Обмен) -> None:
    метка = начать(ук, обмен)
    ук.post(auth.LOGOUT_PATH, headers=ЗАГОЛОВКИ)

    assert вернуться(ук, метка) == auth.LOGIN_PATH
    assert обмен.звали == 0 and база.finish == []


def test_повтор_метки_не_привязывает(ук: FlaskClient, база: База, обмен: Обмен) -> None:
    метка = начать(ук, обмен)
    кука = ук.get_cookie(auth.GOOGLE_STATE_COOKIE)
    assert кука is not None
    assert вернуться(ук, метка) == "linked"

    # Кука метки снята после первого возврата: повтор — общий отказ.
    ответ = ук.get(auth.GOOGLE_CALLBACK_PATH, query_string={"state": метка, "code": "код"})
    assert ответ.status_code == 401

    # Сохранённая кука, подложенная снова, упирается в базу: метка погашена.
    ук.set_cookie(auth.GOOGLE_STATE_COOKIE, кука.value)
    assert вернуться(ук, метка) == "state"
    assert len(база.привязано) == 1


def test_подделанная_метка_не_ходит_к_google(ук: FlaskClient, база: База, обмен: Обмен) -> None:
    начать(ук, обмен)
    ответ = ук.get(auth.GOOGLE_CALLBACK_PATH, query_string={"state": "чужая", "code": "код"})

    assert ответ.status_code == 401
    assert обмен.звали == 0 and база.finish == []


def test_отказ_в_окне_google_ничего_не_меняет(ук: FlaskClient, база: База, обмен: Обмен) -> None:
    метка = начать(ук, обмен)

    assert вернуться(ук, метка, error="access_denied") == "cancelled"
    assert обмен.звали == 0 and база.finish == []


def test_сбой_обмена_сказан_словами(ук: FlaskClient, база: База, обмен: Обмен) -> None:
    метка = начать(ук, обмен)

    assert вернуться(ук, метка, code="сломанный") == "failed"
    assert база.finish == []


def test_исход_в_адресе_только_из_списка(ук: FlaskClient) -> None:
    своё = ук.get("/settings?google=linked").get_data(as_text=True)
    чужое = ук.get("/settings?google=<b>взлом</b>").get_data(as_text=True)

    assert "Почта Google привязана" in своё
    assert "взлом" not in чужое


def test_журнал_не_пишет_почту_целиком(
    партнёр: FlaskClient, база: База, обмен: Обмен, caplog: pytest.LogCaptureFixture
) -> None:
    обмен.почта, обмен.домен = ПОЧТА_ЛИЧНАЯ, ""
    метка = начать(партнёр, обмен)
    with caplog.at_level("INFO"):
        вернуться(партнёр, метка)

    assert "d***@gmail.com" in caplog.text
    assert ПОЧТА_ЛИЧНАЯ not in caplog.text


# ── Экран: предупреждение и снятие ─────────────────────────────────────


def test_до_ухода_к_google_сказано_что_пароль_закроется(ук: FlaskClient) -> None:
    страница = ук.get("/settings").get_data(as_text=True)

    assert "Привязать Google" in страница
    assert "вход паролем для этой учётки закроется" in страница
    assert "dodobrands.io" in страница, "учётке УК не сказано, какой аккаунт годится"


def test_без_реквизитов_привязки_нет(monkeypatch: pytest.MonkeyPatch) -> None:
    for client in _стенд(monkeypatch, google=False):
        страница = client.get("/settings").get_data(as_text=True)

        assert "Привязать Google" not in страница
        assert "привязать почту пока нельзя" in страница


def test_снять_почту_можно_только_с_паролем(
    monkeypatch: pytest.MonkeyPatch, база: База, caplog: pytest.LogCaptureFixture
) -> None:
    for client in _стенд(monkeypatch, tenant="HQ", role="guest", email=ПОЧТА_УК):
        страница = client.get("/settings").get_data(as_text=True)
        assert "Отвязать Google" in страница and "только зная пароль учётки" in страница

        пусто = client.post("/settings/google-unlink", data={}, headers=ЗАГОЛОВКИ)
        assert пусто.status_code == 400
        assert "без него отвязать нельзя" in пусто.get_data(as_text=True)

        мимо = client.post("/settings/google-unlink", data={"current": "не-тот"}, headers=ЗАГОЛОВКИ)
        assert мимо.status_code == 400
        assert "привязка осталась" in мимо.get_data(as_text=True)

        with caplog.at_level("INFO"):
            верно = client.post(
                "/settings/google-unlink", data={"current": "верный-пароль"}, headers=ЗАГОЛОВКИ
            )
        assert верно.status_code == 302 and "google=unlinked" in верно.headers["Location"]
        assert ПОЧТА_УК not in caplog.text


def test_снятие_со_чужой_страницы_не_проходит(monkeypatch: pytest.MonkeyPatch, база: База) -> None:
    for client in _стенд(monkeypatch, email=ПОЧТА_УК):
        ответ = client.post(
            "/settings/google-unlink",
            data={"current": "верный-пароль"},
            headers={"Origin": "https://чужой.example"},
        )

        assert ответ.status_code == 403
