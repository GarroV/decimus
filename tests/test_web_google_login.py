"""Вход через учётку Google на уровне страниц (T332, #308).

Сети здесь нет: обмен кода подменяется двойником. Проверяется не то, что
Google отвечает, а то, что делаем МЫ — кого пускаем, кого нет и в каком
порядке проверяем, потому что порядок здесь и есть защита.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from flask import Response
from flask.testing import FlaskClient
from web_harness import Сессия, Учётка, подменить_двери, собрать

from src.web import auth
from src.web import inspections as data
from src.web.google_auth import GoogleAuthError, GoogleIdentity, GoogleSettings

ТЕНАНТ = "rs"
ПОЧТА_СВОЯ = "director@dodobrands.io"
ПОЧТА_ЧУЖАЯ = "kto-ugodno@gmail.com"

РЕКВИЗИТЫ = GoogleSettings(
    client_id="наш-клиент.apps.googleusercontent.com",
    client_secret="секрет-набора",
    redirect_uri="https://стенд.example/auth/google/callback",
)


class Обмен:
    """Двойник обмена кода. Помнит, звали ли его — это половина проверок."""

    def __init__(self, почта: str = ПОЧТА_СВОЯ, срывается: bool = False) -> None:
        self.почта = почта
        self.срывается = срывается
        self.подтверждена = True
        self.домен = "dodobrands.io"
        self.звали = 0

    def __call__(self, settings: GoogleSettings, *, code: str) -> GoogleIdentity:
        self.звали += 1
        if self.срывается:
            raise GoogleAuthError("двойник: Google отказал")
        return GoogleIdentity(
            email=self.почта, email_verified=self.подтверждена, hosted_domain=self.домен
        )


@pytest.fixture
def обмен(monkeypatch: pytest.MonkeyPatch) -> Обмен:
    двойник = Обмен()
    monkeypatch.setattr(auth, "exchange_code", двойник)
    return двойник


@pytest.fixture
def клиент(monkeypatch: pytest.MonkeyPatch) -> Iterator[FlaskClient]:
    """Стенд с настроенным входом через Google и знакомой почтой в базе."""
    подменить_двери(monkeypatch, tenant=ТЕНАНТ)
    monkeypatch.setattr(auth, "load_google_settings", lambda *_, **__: РЕКВИЗИТЫ)
    monkeypatch.setattr(
        auth,
        "find_by_email",
        lambda email: Учётка(tenant=ТЕНАНТ) if email == ПОЧТА_СВОЯ else None,
    )
    monkeypatch.setattr(auth, "open_session", lambda account: Сессия())
    with собрать(tenant=ТЕНАНТ).test_client() as client:
        yield client


def метка_захода(client: FlaskClient) -> str:
    """Пройти первый шаг и вернуть метку, которую Google получил бы в адресе."""
    ответ = client.get(auth.GOOGLE_START_PATH)
    адрес = ответ.headers["Location"]
    return адрес.split("state=")[1].split("&")[0]


def test_без_реквизитов_кнопки_нет(monkeypatch: pytest.MonkeyPatch) -> None:
    """Стенд без реквизитов работает паролем: мёртвая кнопка читалась бы поломкой."""
    подменить_двери(monkeypatch, tenant=ТЕНАНТ)
    monkeypatch.setattr(auth, "load_google_settings", lambda *_, **__: None)

    with собрать(tenant=ТЕНАНТ).test_client() as client:
        страница = client.get(auth.LOGIN_PATH).get_data(as_text=True)

    assert "Войти через Google" not in страница


def test_с_реквизитами_кнопка_есть(клиент: FlaskClient) -> None:
    страница = клиент.get(auth.LOGIN_PATH).get_data(as_text=True)

    assert "Войти через Google" in страница
    assert auth.GOOGLE_START_PATH in страница


def test_начало_уводит_к_google_и_запоминает_метку(клиент: FlaskClient) -> None:
    ответ = клиент.get(auth.GOOGLE_START_PATH)

    assert ответ.status_code == 302
    assert ответ.headers["Location"].startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert auth.GOOGLE_STATE_COOKIE in ответ.headers.get("Set-Cookie", "")


def test_возврат_без_метки_не_пускает_и_не_ходит_к_google(
    клиент: FlaskClient, обмен: Обмен
) -> None:
    """Метка сверяется ДО обмена: иначе чужая страница тратила бы наш запрос."""
    ответ = клиент.get(f"{auth.GOOGLE_CALLBACK_PATH}?code=код&state=взятая-с-потолка")

    assert ответ.status_code == 401
    assert обмен.звали == 0


def test_подделанная_метка_не_пускает_и_не_ходит_к_google(
    клиент: FlaskClient, обмен: Обмен
) -> None:
    метка_захода(клиент)

    ответ = клиент.get(f"{auth.GOOGLE_CALLBACK_PATH}?code=код&state=не-та-метка")

    assert ответ.status_code == 401
    assert обмен.звали == 0


def test_знакомая_почта_пускает_внутрь(клиент: FlaskClient, обмен: Обмен) -> None:
    метка = метка_захода(клиент)

    ответ = клиент.get(f"{auth.GOOGLE_CALLBACK_PATH}?code=код&state={метка}")

    assert ответ.status_code == 302
    assert обмен.звали == 1
    assert auth.COOKIE_NAME in ответ.headers.get("Set-Cookie", "")


def test_стенд_уК_впускает_через_google_учётку_партнёра_в_её_пространство(
    monkeypatch: pytest.MonkeyPatch, обмен: Обмен
) -> None:
    """Аналог формы (D282, ревью Task 4 круг 1, Minor 1б): Google на стенде УК
    тоже отдаёт пространство УЧЁТКИ, а не стенда.

    `подменить_двери(..., tenant="GE")` держит и опознание, и сессию на
    пространстве УЧЁТКИ; `find_by_email` подменён тем же пространством —
    ровно то, что вернула бы настоящая строка `web_users`. Стенд собран на
    `tenant="HQ"`: это и есть проверяемый сценарий.
    """
    подменить_двери(monkeypatch, tenant="GE")
    monkeypatch.setattr(auth, "load_google_settings", lambda *_, **__: РЕКВИЗИТЫ)
    monkeypatch.setattr(auth, "find_by_email", lambda email: Учётка(tenant="GE"))
    monkeypatch.setattr(data, "load_registry", lambda **_: data.Registry((), True))

    app = собрать(tenant="HQ")
    увиденные_пространства: list[str] = []

    @app.after_request
    def _запомнить_пространство_вошедшего(response: Response) -> Response:
        учётка = auth.current_account()
        if учётка is not None:
            увиденные_пространства.append(учётка.tenant)
        return response

    with app.test_client() as client:
        метка = метка_захода(client)
        вход = client.get(f"{auth.GOOGLE_CALLBACK_PATH}?code=код&state={метка}")
        assert вход.status_code == 302
        assert auth.COOKIE_NAME in вход.headers.get("Set-Cookie", "")
        ответ = client.get("/inspections")
        assert ответ.status_code == 200

    assert обмен.звали == 1
    assert увиденные_пространства == ["GE"], (
        "приложение обязано увидеть пространство УЧЁТКИ, а не тенант стенда"
    )


def test_незнакомая_почта_получает_отказ_а_не_учётку(клиент: FlaskClient, обмен: Обмен) -> None:
    """Круг допущенных задаёт владелец: Google подтверждает почту, и только."""
    обмен.почта = ПОЧТА_ЧУЖАЯ
    метка = метка_захода(клиент)

    ответ = клиент.get(f"{auth.GOOGLE_CALLBACK_PATH}?code=код&state={метка}")

    assert ответ.status_code == 401
    assert auth.COOKIE_NAME not in ответ.headers.get("Set-Cookie", "")


def test_осечка_у_google_не_пускает(клиент: FlaskClient, обмен: Обмен) -> None:
    обмен.срывается = True
    метка = метка_захода(клиент)

    ответ = клиент.get(f"{auth.GOOGLE_CALLBACK_PATH}?code=код&state={метка}")

    assert ответ.status_code == 401


def test_человек_отказался_в_окне_согласия_возвращается_на_форму(
    клиент: FlaskClient, обмен: Обмен
) -> None:
    """Это не поломка и не попытка взлома — красным его пугать не за что."""
    метка = метка_захода(клиент)

    ответ = клиент.get(f"{auth.GOOGLE_CALLBACK_PATH}?error=access_denied&state={метка}")

    assert ответ.status_code == 302
    assert ответ.headers["Location"].endswith(auth.LOGIN_PATH)
    assert обмен.звали == 0


def test_метка_одноразовая(клиент: FlaskClient, обмен: Обмен) -> None:
    """Второй возврат с той же меткой не проходит: заход уже состоялся."""
    метка = метка_захода(клиент)
    первый = клиент.get(f"{auth.GOOGLE_CALLBACK_PATH}?code=код&state={метка}")
    assert первый.status_code == 302

    второй = клиент.get(f"{auth.GOOGLE_CALLBACK_PATH}?code=код&state={метка}")

    assert второй.status_code == 401


def test_неподтверждённая_почта_не_пускает_даже_со_знакомым_адресом(
    клиент: FlaskClient, обмен: Обмен
) -> None:
    """Заслон продублирован в маршруте: первый стоит в разборе токена.

    Дубль не лишний — `GoogleIdentity` несёт признак с собой, и маршрут,
    который его не смотрит, пропустил бы неподтверждённую почту, приди она
    любым другим путём.
    """
    обмен.подтверждена = False
    метка = метка_захода(клиент)

    ответ = клиент.get(f"{auth.GOOGLE_CALLBACK_PATH}?code=код&state={метка}")

    assert ответ.status_code == 401
    assert auth.COOKIE_NAME not in ответ.headers.get("Set-Cookie", "")


ФРОНТ = "https://decimus.front.example/auth/google/callback"


def test_через_фронт_google_получает_адрес_фронта_и_тот_же_при_обмене(
    monkeypatch: pytest.MonkeyPatch, обмен: Обмен
) -> None:
    """D236: адрес возврата обязан совпасть в уходе к Google и в обмене кода."""
    from dataclasses import replace
    from urllib.parse import parse_qs, urlsplit

    подменить_двери(monkeypatch, tenant=ТЕНАНТ)
    с_фронтом = replace(РЕКВИЗИТЫ, front_redirect_uri=ФРОНТ)
    monkeypatch.setattr(auth, "load_google_settings", lambda *_, **__: с_фронтом)
    monkeypatch.setattr(auth, "find_by_email", lambda email: Учётка(tenant=ТЕНАНТ))
    monkeypatch.setattr(auth, "open_session", lambda account: Сессия())
    виденные: list[str] = []
    исходный = обмен.__call__

    def запомнить(settings: GoogleSettings, *, code: str) -> GoogleIdentity:
        виденные.append(settings.redirect_uri)
        return исходный(settings, code=code)

    monkeypatch.setattr(auth, "exchange_code", запомнить)
    метка_фронта = {auth.FRONT_MARKER_HEADER: "1"}
    with собрать(tenant=ТЕНАНТ).test_client() as client:
        ушли = client.get(auth.GOOGLE_START_PATH, headers=метка_фронта).headers["Location"]
        assert parse_qs(urlsplit(ушли).query)["redirect_uri"] == [ФРОНТ]
        state = parse_qs(urlsplit(ушли).query)["state"][0]
        client.get(f"{auth.GOOGLE_CALLBACK_PATH}?code=c&state={state}", headers=метка_фронта)
        assert виденные == [ФРОНТ]

        прямо = client.get(auth.GOOGLE_START_PATH).headers["Location"]
        assert parse_qs(urlsplit(прямо).query)["redirect_uri"] == [РЕКВИЗИТЫ.redirect_uri]


def test_вход_через_google_возвращает_на_согласие_oauth(клиент: FlaskClient, обмен: Обмен) -> None:
    """D417: путь возврата едет через Google в подписанной куке и только на согласие."""
    вернуться = "/oauth/authorize?client_id=c&state=s"
    ответ = клиент.get(auth.GOOGLE_START_PATH, query_string={"next": вернуться})
    метка = ответ.headers["Location"].split("state=")[1].split("&")[0]

    после = клиент.get(f"{auth.GOOGLE_CALLBACK_PATH}?code=код&state={метка}")

    assert после.status_code == 302
    assert после.headers["Location"].endswith(вернуться)


def test_вход_через_google_не_уводит_на_чужой_next(клиент: FlaskClient, обмен: Обмен) -> None:
    ответ = клиент.get(auth.GOOGLE_START_PATH, query_string={"next": "https://evil.com/x"})
    метка = ответ.headers["Location"].split("state=")[1].split("&")[0]

    после = клиент.get(f"{auth.GOOGLE_CALLBACK_PATH}?code=код&state={метка}")

    assert "evil.com" not in после.headers["Location"]


# --- домен компании для учёток УК (D430, F-028 аудита 12.10) ---------------


def _учётка_уК(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        auth,
        "find_by_email",
        lambda email: Учётка(tenant="HQ") if email == ПОЧТА_СВОЯ else None,
    )


@pytest.mark.parametrize(("домен", "пускает"), [("dodobrands.io", True), ("", False)])
def test_учётку_уК_пускает_только_аккаунт_домена_компании(
    клиент: FlaskClient,
    обмен: Обмен,
    monkeypatch: pytest.MonkeyPatch,
    домен: str,
    пускает: bool,
) -> None:
    """Совпала почта, но аккаунт не из Workspace компании (`hd`) — отказ."""
    _учётка_уК(monkeypatch)
    обмен.домен = домен
    метка = метка_захода(клиент)

    ответ = клиент.get(f"{auth.GOOGLE_CALLBACK_PATH}?code=код&state={метка}")

    assert (ответ.status_code == 302) is пускает
    assert (auth.COOKIE_NAME in ответ.headers.get("Set-Cookie", "")) is пускает


def test_домены_компании_задаются_окружением(monkeypatch: pytest.MonkeyPatch, обмен: Обмен) -> None:
    monkeypatch.setenv("GOOGLE_HQ_DOMAINS", "example.org")
    подменить_двери(monkeypatch, tenant=ТЕНАНТ)
    monkeypatch.setattr(auth, "load_google_settings", lambda *_, **__: РЕКВИЗИТЫ)
    _учётка_уК(monkeypatch)
    monkeypatch.setattr(auth, "open_session", lambda account: Сессия())
    обмен.домен = "dodobrands.io"
    with собрать(tenant=ТЕНАНТ).test_client() as client:
        метка = метка_захода(client)
        ответ = client.get(f"{auth.GOOGLE_CALLBACK_PATH}?code=код&state={метка}")
    assert ответ.status_code == 401


def test_учётку_партнёра_домен_не_касается(клиент: FlaskClient, обмен: Обмен) -> None:
    """D430: партнёры входят по почтам из списка пространства, без домена."""
    обмен.домен = ""
    метка = метка_захода(клиент)

    ответ = клиент.get(f"{auth.GOOGLE_CALLBACK_PATH}?code=код&state={метка}")

    assert ответ.status_code == 302


# --- пароль закрыт учёткам с привязанной почтой Google ---------------------


def _войти_паролем(client: FlaskClient) -> Response:
    from web_harness import ЛОГИН, ПАРОЛЬ, СВОЙ

    return client.post(  # type: ignore[return-value]
        "/login",
        data={"login": ЛОГИН, "password": ПАРОЛЬ},
        headers={"Origin": СВОЙ},
    )


def test_учётка_с_почтой_google_паролем_не_входит(monkeypatch: pytest.MonkeyPatch) -> None:
    зовы = подменить_двери(monkeypatch, tenant=ТЕНАНТ, email=ПОЧТА_СВОЯ)
    monkeypatch.setattr(auth, "load_google_settings", lambda *_, **__: РЕКВИЗИТЫ)
    with собрать(tenant=ТЕНАНТ).test_client() as client:
        ответ = _войти_паролем(client)

    assert ответ.status_code == 403
    assert зовы["open"] == [], "сессия открылась паролем"
    assert "Войти через Google" in ответ.get_data(as_text=True)
    assert auth.COOKIE_NAME not in ответ.headers.get("Set-Cookie", "")


def test_без_реквизитов_google_пароль_остаётся(monkeypatch: pytest.MonkeyPatch) -> None:
    """Стенд без Google: закрыть пароль значило бы закрыть вход совсем."""
    зовы = подменить_двери(monkeypatch, tenant=ТЕНАНТ, email=ПОЧТА_СВОЯ)
    monkeypatch.setattr(auth, "load_google_settings", lambda *_, **__: None)
    with собрать(tenant=ТЕНАНТ).test_client() as client:
        ответ = _войти_паролем(client)

    assert ответ.status_code == 302
    assert зовы["open"]


def test_учётка_без_почты_google_входит_паролем(monkeypatch: pytest.MonkeyPatch) -> None:
    зовы = подменить_двери(monkeypatch, tenant=ТЕНАНТ)
    monkeypatch.setattr(auth, "load_google_settings", lambda *_, **__: РЕКВИЗИТЫ)
    with собрать(tenant=ТЕНАНТ).test_client() as client:
        ответ = _войти_паролем(client)

    assert ответ.status_code == 302
    assert зовы["open"]
