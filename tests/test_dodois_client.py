"""Клиент Dodo IS (D640): разбор ответов, продление, счёт открытых; только чтение у `api`.

Сеть подменена на единственной точке выхода `client._open`: настоящих запросов нет.
"""

from __future__ import annotations

import urllib.request
from datetime import date
from typing import Any

import pytest

from src.dodois import client
from src.dodois.client import Credentials, DodoisError, RefreshRejected, Response

КЛЮЧИ = Credentials("app-id-AAAA", "app-secret-BBBB")
ДОСТУП = "access-token-CCCC-secret"
ПРОДЛЕНИЕ = "refresh-token-DDDD-secret"
КОД_УСТРОЙСТВА = "device-code-EEEE-secret"
СЕГОДНЯ = date(2026, 10, 25)


class Сеть:
    """Двойник `_open`: очередь ответов и журнал того, что ушло."""

    def __init__(self) -> None:
        self.ответы: list[Response | Exception] = []
        self.ушло: list[tuple[str, str, bytes | None]] = []

    def __call__(self, request: urllib.request.Request) -> Response:
        self.ушло.append((request.get_method(), request.full_url, request.data))  # type: ignore[arg-type]
        ответ = self.ответы.pop(0)
        if isinstance(ответ, Exception):
            raise ответ
        return ответ


@pytest.fixture
def сеть(monkeypatch: pytest.MonkeyPatch) -> Сеть:
    двойник = Сеть()
    monkeypatch.setattr(client, "_open", двойник)
    return двойник


def _ответ(статус: int, тело: Any = None, **заголовки: str) -> Response:
    return Response(статус, заголовки, тело)


def test_начало_входа_берёт_код_для_человека_и_ссылку(сеть: Сеть) -> None:
    сеть.ответы.append(
        _ответ(
            200,
            {
                "device_code": КОД_УСТРОЙСТВА,
                "user_code": "ABCD-1234",
                "verification_uri_complete": "https://auth.dodois.com/device?user_code=ABCD-1234",
                "expires_in": 300,
                "interval": 5,
            },
        )
    )
    старт = client.start_device(КЛЮЧИ, "intl")
    assert (старт.user_code, старт.expires_in, старт.interval) == ("ABCD-1234", 300, 5)
    метод, адрес, тело = сеть.ушло[0]
    assert (метод, адрес) == ("POST", "https://auth.dodois.com/connect/deviceauthorization")
    assert b"scope=openid+profile+email+shared+sales+stopsales" in (тело or b"")
    assert b"offline_access" in (тело or b"")


def test_ключи_приложения_не_приняты_это_отказ_а_не_сбой_связи(сеть: Сеть) -> None:
    сеть.ответы.append(_ответ(400, {"error": "invalid_client"}))
    with pytest.raises(DodoisError) as исключение:
        client.start_device(КЛЮЧИ, "intl")
    assert исключение.value.kind == client.UNAUTHORIZED


@pytest.mark.parametrize(
    ("ответ", "ждём"),
    [
        (_ответ(400, {"error": "authorization_pending"}), client.PENDING),
        (_ответ(400, {"error": "slow_down"}), client.SLOW_DOWN),
        (_ответ(400, {"error": "expired_token"}), client.EXPIRED),
        (_ответ(400, {"error": "access_denied"}), client.DENIED),
    ],
)
def test_опрос_кода_устройства_разбирает_состояния(сеть: Сеть, ответ: Response, ждём: str) -> None:
    сеть.ответы.append(ответ)
    assert client.poll_device(КЛЮЧИ, "intl", КОД_УСТРОЙСТВА) == ждём


def test_опрос_при_успехе_отдаёт_пару_ключей(сеть: Сеть) -> None:
    сеть.ответы.append(
        _ответ(
            200,
            {
                "access_token": ДОСТУП,
                "refresh_token": ПРОДЛЕНИЕ,
                "expires_in": 86400,
                "scope": "openid sales",
            },
        )
    )
    пара = client.poll_device(КЛЮЧИ, "intl", КОД_УСТРОЙСТВА)
    assert isinstance(пара, client.TokenPair)
    assert (пара.access, пара.refresh, пара.expires_in) == (ДОСТУП, ПРОДЛЕНИЕ, 86400)
    assert b"grant_type=urn%3Aietf%3Aparams%3Aoauth%3Agrant-type%3Adevice_code" in (
        сеть.ушло[0][2] or b""
    )


def test_ответ_без_ключей_не_считается_успехом(сеть: Сеть) -> None:
    # Сломанная копия: не проверять наличие `refresh_token` — вход записался бы без продления.
    сеть.ответы.append(_ответ(200, {"access_token": ДОСТУП}))
    with pytest.raises(DodoisError):
        client.poll_device(КЛЮЧИ, "intl", КОД_УСТРОЙСТВА)


def test_продление_несёт_новую_пару_и_шлёт_ключ_продления(сеть: Сеть) -> None:
    сеть.ответы.append(
        _ответ(200, {"access_token": "new-a", "refresh_token": "new-r", "expires_in": 86400})
    )
    пара = client.refresh_tokens(КЛЮЧИ, "intl", ПРОДЛЕНИЕ)
    assert (пара.access, пара.refresh) == ("new-a", "new-r")
    assert b"grant_type=refresh_token" in (сеть.ушло[0][2] or b"")


def test_продление_отвергнуто_invalid_grant_это_истёкший_вход(сеть: Сеть) -> None:
    # Сломанная копия: invalid_grant как обычный сбой связи — вход не помечался бы истёкшим.
    сеть.ответы.append(_ответ(400, {"error": "invalid_grant"}))
    with pytest.raises(RefreshRejected):
        client.refresh_tokens(КЛЮЧИ, "intl", ПРОДЛЕНИЕ)


@pytest.mark.parametrize(
    ("ответ", "вид"),
    [
        (_ответ(400, {"error": "invalid_client"}), client.UNAUTHORIZED),
        (_ответ(503), client.NETWORK),
        (_ответ(429), client.RATE_LIMITED),
        (DodoisError(client.NETWORK), client.NETWORK),
    ],
)
def test_прочие_отказы_продления_не_делают_вход_истёкшим(
    сеть: Сеть, ответ: Response | Exception, вид: str
) -> None:
    сеть.ответы.append(ответ)
    with pytest.raises(DodoisError) as исключение:
        client.refresh_tokens(КЛЮЧИ, "intl", ПРОДЛЕНИЕ)
    assert not isinstance(исключение.value, RefreshRejected)
    assert исключение.value.kind == вид


def test_неизвестный_контур_не_заведён() -> None:
    with pytest.raises(DodoisError):
        client.start_device(КЛЮЧИ, "cis")


def test_имя_и_почта_из_userinfo_и_ничего_больше(сеть: Сеть) -> None:
    сеть.ответы.append(
        _ответ(200, {"name": " Ana Novak ", "email": "ana@example.com", "phone": "+386 1"})
    )
    assert client.userinfo("intl", ДОСТУП) == ("Ana Novak", "ana@example.com")
    assert сеть.ушло[0][0] == "GET"


def test_userinfo_при_сбое_отдаёт_пустое_и_вход_не_ломается(сеть: Сеть) -> None:
    сеть.ответы.append(_ответ(500))
    assert client.userinfo("intl", ДОСТУП) == (None, None)
    сеть.ответы.append(DodoisError(client.NETWORK))
    assert client.userinfo("intl", ДОСТУП) == (None, None)


def test_работающие_пиццерии_только_тип_один_и_состояние_один(сеть: Сеть) -> None:
    сеть.ответы.append(
        _ответ(
            200,
            [
                {"UUId": "u1", "Type": 1, "State": 1},
                {"UUId": "u2", "Type": 1, "State": 0},
                {"UUId": "u3", "Type": 2, "State": 1},
                {"UUId": "u4", "Type": 1, "State": 1},
                {"Type": 1, "State": 1},
            ],
        )
    )
    assert client.working_pizzerias("SI") == ["u1", "u4"]
    assert сеть.ушло[0][1] == "https://publicapi.dodois.io/si/api/v1/unitinfo/all"


def _открыты(*доступные: str) -> Any:
    """Двойник стопов: 200, если среди пиццерий запроса нет недоступных, иначе 403."""

    def отвечает(request: urllib.request.Request) -> Response:
        units = request.full_url.split("units=")[1].split("&")[0].split(",")
        if all(u in доступные for u in units):
            return _ответ(200, [])
        return _ответ(403, {"code": "NoAccessToUnit"})

    return отвечает


def test_счёт_открытых_делит_пачку_пока_не_найдёт_закрытые(monkeypatch: pytest.MonkeyPatch) -> None:
    единицы = [f"u{n}" for n in range(1, 8)]
    нет_доступа = {"u3", "u6"}
    monkeypatch.setattr(client, "_open", _открыты(*(set(единицы) - нет_доступа)))
    открыто = client.count_open("SI", "intl", ДОСТУП, единицы, СЕГОДНЯ)
    assert открыто == 5


def test_все_открыты_одним_запросом(monkeypatch: pytest.MonkeyPatch, сеть: Сеть) -> None:
    сеть.ответы.append(_ответ(200, []))
    assert client.count_open("SI", "intl", ДОСТУП, ["u1", "u2"], СЕГОДНЯ) == 2
    assert len(сеть.ушло) == 1


def test_пачки_по_тридцать(monkeypatch: pytest.MonkeyPatch, сеть: Сеть) -> None:
    сеть.ответы.extend(_ответ(200, []) for _ in range(3))
    единицы = [f"u{n}" for n in range(65)]
    assert client.count_open("SI", "intl", ДОСТУП, единицы, СЕГОДНЯ) == 65
    assert len(сеть.ушло) == 3
    assert max(len(u[1].split("units=")[1].split("&")[0].split(",")) for u in сеть.ушло) == 30


def test_лимит_ждёт_retry_after_и_повторяет_один_раз(сеть: Сеть) -> None:
    сеть.ответы.extend([_ответ(429, None, **{"retry-after": "2"}), _ответ(200, [])])
    паузы: list[float] = []
    assert client.count_open("SI", "intl", ДОСТУП, ["u1"], СЕГОДНЯ, sleep=паузы.append) == 1
    assert паузы == [2]


def test_лимит_с_долгим_ожиданием_это_отказ_лимита(сеть: Сеть) -> None:
    сеть.ответы.append(_ответ(429, None, **{"retry-after": "600"}))
    with pytest.raises(DodoisError) as исключение:
        client.count_open("SI", "intl", ДОСТУП, ["u1"], СЕГОДНЯ, sleep=lambda _s: None)
    assert исключение.value.kind == client.RATE_LIMITED


def test_ключ_доступа_отвергнут_401_это_unauthorized(сеть: Сеть) -> None:
    сеть.ответы.append(_ответ(401))
    with pytest.raises(DodoisError) as исключение:
        client.count_open("SI", "intl", ДОСТУП, ["u1"], СЕГОДНЯ)
    assert исключение.value.kind == client.UNAUTHORIZED


def test_к_api_dodois_только_get_а_post_только_к_серверу_авторизации(сеть: Сеть) -> None:
    # Сломанная копия: `_stop_sales` шлёт `_post_form` вместо `_get` — тест падает на методе.
    сеть.ответы.extend(
        [
            _ответ(200, [{"UUId": "u1", "Type": 1, "State": 1}]),
            _ответ(200, []),
            _ответ(200, {"name": "A", "email": "a@b.c"}),
            _ответ(
                200,
                {
                    "device_code": "d",
                    "user_code": "u",
                    "verification_uri": "https://x",
                    "expires_in": 1,
                },
            ),
            _ответ(400, {"error": "authorization_pending"}),
            _ответ(200, {"access_token": "a", "refresh_token": "r"}),
        ]
    )
    client.working_pizzerias("SI")
    client.count_open("SI", "intl", ДОСТУП, ["u1"], СЕГОДНЯ)
    client.userinfo("intl", ДОСТУП)
    client.start_device(КЛЮЧИ, "intl")
    client.poll_device(КЛЮЧИ, "intl", КОД_УСТРОЙСТВА)
    client.refresh_tokens(КЛЮЧИ, "intl", ПРОДЛЕНИЕ)
    for метод, адрес, _ in сеть.ушло:
        if "api.dodois.com" in адрес:
            assert метод == "GET", f"{метод} к api.dodois.com: {адрес}"
        if метод == "POST":
            assert адрес.startswith("https://auth.dodois.com/connect/"), адрес


def test_значения_не_светятся_в_отладочном_виде() -> None:
    пара = client.TokenPair(ДОСТУП, ПРОДЛЕНИЕ, 1, None)
    старт = client.DeviceStart(КОД_УСТРОЙСТВА, "u", "https://x", 1, 1)
    for объект in (пара, старт, КЛЮЧИ):
        вид = repr(объект) + str(объект)
        for значение in (ДОСТУП, ПРОДЛЕНИЕ, КОД_УСТРОЙСТВА, КЛЮЧИ.client_secret):
            assert значение not in вид
