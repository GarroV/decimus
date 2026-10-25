"""Вход по ссылке (D640): device flow на сервере, погашение ссылки записью входа, журнал.

Сеть и база подменены (`client`, `dodois_logins`, `journals`). Поток опроса не запускается:
опрос идёт вызовом `poll_once`, чтобы результат был детерминированным.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from src.db import dodois_logins as store
from src.db import journals
from src.db.errors import AccessError
from src.dodois import client, flow, service
from src.dodois.client import Credentials, DeviceStart, DodoisError, TokenPair
from src.domain import dodois as rules
from src.domain.dodois import Invite, Login

КЛЮЧИ = Credentials("app-id", "app-secret")
КОД_УСТРОЙСТВА = "device-code-ZZZZ-secret"
ПАРА = TokenPair("access-AAAA-secret", "refresh-BBBB-secret", 86400, "openid sales")


def _ссылка(страна: str = "SI") -> Invite:
    сейчас = datetime.now(UTC)
    return Invite(
        id=7,
        country=страна,
        issued_by="director",
        issued_at=сейчас,
        expires_at=сейчас + timedelta(hours=24),
        used_at=None,
        revoked_at=None,
        token_hash="0" * 64,
        issued_by_id="22222222-2222-2222-2222-222222222222",
        issued_by_role="superadmin",
        issued_by_tenant="HQ",
    )


@pytest.fixture(autouse=True)
def _чисто() -> Any:
    flow.forget_all()
    yield
    flow.forget_all()


@pytest.fixture
def мир(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Двойники: что записано входом, что в журнале, чем отвечает Dodo IS."""
    мир: dict[str, Any] = {
        "ответы_опроса": [],
        "вход": [],
        "журнал": [],
        "уже_есть_вход": False,
        "погашена": False,
        "запусков": 0,
    }

    def старт(_creds: Credentials, _contour: str) -> DeviceStart:
        мир["запусков"] += 1
        return DeviceStart(
            КОД_УСТРОЙСТВА, "ABCD-1234", "https://auth.dodois.com/device?user_code=ABCD", 300, 5
        )

    def опрос(_creds: Credentials, _contour: str, device_code: str) -> Any:
        assert device_code == КОД_УСТРОЙСТВА
        return мир["ответы_опроса"].pop(0)

    def записать(**поля: Any) -> Login:
        if мир["погашена"]:
            raise store.InviteUnusable("погашена")
        мир["вход"].append(поля)
        return Login(
            поля["country"], "intl", поля["source"], поля["issued_by"], поля["account_name"],
            поля["account_email"], поля["now"], поля["scope"], None, None, поля["now"],
            поля["access_expires_at"], None, rules.OK, None,
        )  # fmt: skip

    monkeypatch.setattr(client, "start_device", старт)
    monkeypatch.setattr(client, "poll_device", опрос)
    monkeypatch.setattr(client, "userinfo", lambda _c, _a: ("Ana Novak", "ana@example.com"))
    monkeypatch.setattr(store, "save_login", записать)
    monkeypatch.setattr(store, "get_login", lambda _c: object() if мир["уже_есть_вход"] else None)
    monkeypatch.setattr(service, "check", lambda *_a, **_k: None)
    monkeypatch.setattr(journals, "record_action", lambda **запись: мир["журнал"].append(запись))
    return мир


def _начать(мир: dict[str, Any], ссылка: Invite | None = None) -> flow.Flow:
    return flow.start(ссылка or _ссылка(), creds=КЛЮЧИ, ip="203.0.113.7", spawn=False)


def test_старт_показывает_код_и_ссылку_но_не_код_устройства(мир: dict[str, Any]) -> None:
    вход = _начать(мир)
    assert (вход.state, вход.user_code) == (flow.PENDING, "ABCD-1234")
    assert вход.link.startswith("https://auth.dodois.com/")
    assert КОД_УСТРОЙСТВА not in repr(вход), "код устройства не должен светиться даже в repr"


def test_повторное_нажатие_при_идущем_входе_не_заводит_второй(мир: dict[str, Any]) -> None:
    первый = _начать(мир)
    assert _начать(мир) is первый and мир["запусков"] == 1


def test_успех_пишет_вход_страны_из_ссылки_гасит_ссылку_и_пишет_в_журнал(
    мир: dict[str, Any],
) -> None:
    # Сломанная копия: `invite_id=None` в `_complete` — ссылка остаётся многоразовой.
    мир["уже_есть_вход"] = True
    вход = _начать(мир, _ссылка("BG"))
    мир["ответы_опроса"].append(ПАРА)
    закончено, _ = flow.poll_once(вход, КЛЮЧИ, interval=5)
    assert закончено and вход.state == flow.DONE
    (запись,) = мир["вход"]
    assert (запись["country"], запись["invite_id"], запись["source"]) == ("BG", 7, "invite")
    assert запись["issued_by"] == "director", "кто выдал ссылку — учётка владельца"
    assert (запись["account_name"], запись["account_email"]) == ("Ana Novak", "ana@example.com")
    (журнал,) = мир["журнал"]
    assert журнал["action"] == "dodois_connect_start" and журнал["credential"] == "invite:7"
    assert журнал["target"] == "country=BG; invite=7; replaced=yes"
    for значение in (ПАРА.access, ПАРА.refresh, КОД_УСТРОЙСТВА):
        assert значение not in str(журнал), "значение ключа попало в журнал действий"
    assert вход._device_code == "", "после конца код устройства забыт"


def test_ссылку_отозвали_за_время_входа_вход_не_пишется(мир: dict[str, Any]) -> None:
    # Сломанная копия: ловить `InviteUnusable` и всё равно писать вход — тест падает.
    вход = _начать(мир)
    мир["ответы_опроса"].append(ПАРА)
    мир["погашена"] = True
    flow.poll_once(вход, КЛЮЧИ, interval=5)
    assert вход.state == flow.REVOKED and мир["вход"] == [] and мир["журнал"] == []


@pytest.mark.parametrize(
    ("ответ", "состояние"),
    [(client.EXPIRED, flow.EXPIRED), (client.DENIED, flow.DENIED)],
)
def test_код_устарел_или_отказ_можно_начать_заново_пока_жива_ссылка(
    мир: dict[str, Any], ответ: str, состояние: str
) -> None:
    вход = _начать(мир)
    мир["ответы_опроса"].append(ответ)
    assert flow.poll_once(вход, КЛЮЧИ, interval=5)[0] is True
    assert вход.state == состояние and состояние in flow.RESTARTABLE
    again = _начать(мир)
    assert again is not вход and again.state == flow.PENDING and мир["запусков"] == 2


def test_ожидание_и_замедление_продолжают_опрос_с_паузой(мир: dict[str, Any]) -> None:
    вход = _начать(мир)
    мир["ответы_опроса"].extend([client.PENDING, client.SLOW_DOWN])
    assert flow.poll_once(вход, КЛЮЧИ, interval=5) == (False, 5)
    assert flow.poll_once(вход, КЛЮЧИ, interval=5) == (False, 5 + flow.SLOW_DOWN_SEC)
    assert вход.state == flow.PENDING


def test_срок_кода_вышел_без_опроса(мир: dict[str, Any]) -> None:
    вход = _начать(мир)
    вход.deadline = time.monotonic() - 1
    assert flow.poll_once(вход, КЛЮЧИ, interval=5)[0] is True and вход.state == flow.EXPIRED


def test_сбой_связи_в_опросе_это_отказ_входа_не_успех(
    мир: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    вход = _начать(мир)

    def падает(*_a: Any) -> Any:
        raise DodoisError(client.NETWORK)

    monkeypatch.setattr(client, "poll_device", падает)
    flow.poll_once(вход, КЛЮЧИ, interval=5)
    assert (вход.state, вход.reason) == (flow.FAILED, client.NETWORK) and мир["вход"] == []


def test_база_отказала_при_записи_вход_не_считается_готовым(
    мир: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    вход = _начать(мир)
    мир["ответы_опроса"].append(ПАРА)

    def падает(**_поля: Any) -> Login:
        raise AccessError("база отказала")

    monkeypatch.setattr(store, "save_login", падает)
    flow.poll_once(вход, КЛЮЧИ, interval=5)
    assert (вход.state, вход.reason) == (flow.FAILED, "write_failed") and мир["журнал"] == []


@pytest.mark.parametrize(
    ("ссылка", "доверяем"),
    [
        ("https://auth.dodois.com/device?user_code=A", True),
        ("https://auth.dodois.io/device", True),
        ("http://auth.dodois.com/device", False),
        ("https://evil.example/auth.dodois.com", False),
        ("https://auth.dodois.com.evil.example/x", False),
        ("https://dodois.com@evil.example/x", False),
        ("javascript:alert(1)", False),
    ],
)
def test_ссылка_подтверждения_только_на_хост_dodo_is(ссылка: str, доверяем: bool) -> None:
    # Сломанная копия: `host in ссылка` вместо проверки хоста — чужие адреса проходят.
    assert flow.trusted_link(ссылка) is доверяем


def test_чужая_ссылка_подтверждения_вход_не_начинает(
    мир: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        client,
        "start_device",
        lambda *_a: DeviceStart("d", "u", "https://evil.example/x", 300, 5),
    )
    with pytest.raises(DodoisError):
        _начать(мир)
    assert flow.current(7) is None
