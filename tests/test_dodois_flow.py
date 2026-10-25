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
        "открыто": 3,
        "отклонено": [],
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
    monkeypatch.setattr(client, "working_pizzerias", lambda _c: ["u1", "u2", "u3"])

    def открыто(*_a: Any, **_k: Any) -> int:
        if isinstance(мир["открыто"], Exception):
            raise мир["открыто"]
        return int(мир["открыто"])

    monkeypatch.setattr(client, "count_open", открыто)
    monkeypatch.setattr(store, "reject_invite", lambda *a, **_k: мир["отклонено"].append(a))
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
    assert журнал["target"] == "country=BG; invite=7; replaced=yes; applied=yes"
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


def test_новый_вход_без_доступа_к_пиццериям_не_заменяет_рабочий(мир: dict[str, Any]) -> None:
    # Сломанная копия: убрать проверку `_gives_access` в `_complete` — пустая учётка затрёт вход.
    мир["уже_есть_вход"] = True
    мир["открыто"] = 0
    вход = _начать(мир)
    мир["ответы_опроса"].append(ПАРА)
    flow.poll_once(вход, КЛЮЧИ, interval=5)
    assert вход.state == flow.NOT_APPLIED
    assert мир["вход"] == [], "прежний вход заменён учёткой без доступа"
    ((номер, страна, учётка, _),) = мир["отклонено"]
    assert (номер, страна, учётка) == (7, "SI", "Ana Novak"), "имя учётки не записано"
    (журнал,) = мир["журнал"]
    assert журнал["target"].endswith("applied=no")


def test_новый_вход_с_доступом_заменяет_рабочий(мир: dict[str, Any]) -> None:
    мир["уже_есть_вход"] = True
    мир["открыто"] = 1
    вход = _начать(мир)
    мир["ответы_опроса"].append(ПАРА)
    flow.poll_once(вход, КЛЮЧИ, interval=5)
    assert вход.state == flow.DONE and len(мир["вход"]) == 1 and мир["отклонено"] == []


def test_первый_вход_страны_пишется_без_предпроверки(мир: dict[str, Any]) -> None:
    мир["открыто"] = DodoisError(client.NETWORK)  # предпроверка не нужна: защищать нечего
    вход = _начать(мир)
    мир["ответы_опроса"].append(ПАРА)
    flow.poll_once(вход, КЛЮЧИ, interval=5)
    assert вход.state == flow.DONE and len(мир["вход"]) == 1


def test_сбой_связи_при_предпроверке_ничего_не_пишет_и_ссылка_жива(мир: dict[str, Any]) -> None:
    мир["уже_есть_вход"] = True
    мир["открыто"] = DodoisError(client.NETWORK)
    вход = _начать(мир)
    мир["ответы_опроса"].append(ПАРА)
    flow.poll_once(вход, КЛЮЧИ, interval=5)
    assert (вход.state, вход.reason) == (flow.FAILED, client.NETWORK)
    assert мир["вход"] == [] and мир["отклонено"] == []


def test_ошибка_журнала_не_портит_готово(
    мир: dict[str, Any], monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # Сломанная копия: звать `record_used` напрямую, без `_journal` — «Готово» станет сбоем.
    def падает(**_запись: Any) -> None:
        raise AccessError("журнал недоступен")

    monkeypatch.setattr(journals, "record_action", падает)
    вход = _начать(мир)
    мир["ответы_опроса"].append(ПАРА)
    flow.poll_once(вход, КЛЮЧИ, interval=5)
    assert вход.state == flow.DONE and len(мир["вход"]) == 1
    assert "журнал" in caplog.text and ПАРА.access not in caplog.text


def test_параллельные_нажатия_заводят_один_вход(
    мир: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Сломанная копия: отпускать замок до `client.start_device` без заглушки — потоков станет N.
    import threading

    в_сети = threading.Event()
    отпустить = threading.Event()
    оригинал = client.start_device

    def медленный(creds: Credentials, contour: str) -> DeviceStart:
        в_сети.set()
        assert отпустить.wait(5)
        return оригинал(creds, contour)

    monkeypatch.setattr(client, "start_device", медленный)
    итоги: list[flow.Flow] = []

    def нажать() -> None:
        итоги.append(flow.start(_ссылка(), creds=КЛЮЧИ, ip=None, spawn=False))

    первый = threading.Thread(target=нажать)
    первый.start()
    assert в_сети.wait(5)
    остальные = [threading.Thread(target=нажать) for _ in range(4)]
    for поток in остальные:
        поток.start()
    for поток in остальные:
        поток.join(5)
    отпустить.set()
    первый.join(5)
    assert мир["запусков"] == 1, "параллельные нажатия дошли до Dodo IS"
    assert len({id(вход) for вход in итоги}) == 1 and len(итоги) == 5


def _другая() -> Invite:
    from dataclasses import replace

    return replace(_ссылка("BG"), id=8)


def test_заглушка_считается_в_предел_входов(
    мир: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(flow, "MAX_FLOWS", 1)
    seen: list[int] = []

    def чужой_старт(creds: Credentials, contour: str) -> DeviceStart:
        # В момент похода в сеть по другой ссылке заглушка первой уже занимает предел.
        with pytest.raises(DodoisError) as err:
            flow.start(_другая(), creds=КЛЮЧИ, ip=None, spawn=False)
        seen.append(1 if err.value.kind == client.RATE_LIMITED else 0)
        return DeviceStart(КОД_УСТРОЙСТВА, "ABCD-1234", "https://auth.dodois.com/d", 300, 5)

    monkeypatch.setattr(client, "start_device", чужой_старт)
    _начать(мир)
    assert seen == [1], "заглушка не считается в MAX_FLOWS"


def test_неудавшийся_старт_убирает_заглушку(
    мир: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def падает(*_a: Any) -> DeviceStart:
        raise DodoisError(client.NETWORK)

    monkeypatch.setattr(client, "start_device", падает)
    with pytest.raises(DodoisError):
        _начать(мир)
    assert flow.current(7) is None, "заглушка осталась и блокирует ссылку"


def test_удачных_начал_по_ссылке_не_больше_предела(мир: dict[str, Any]) -> None:
    # Сломанная копия: убрать проверку `_starts` в `start` — ссылкой можно жечь коды без конца.
    for _ in range(flow.MAX_STARTS_PER_INVITE):
        вход = _начать(мир)
        вход.state = flow.FAILED  # закончился отказом — можно начать заново
    with pytest.raises(DodoisError) as err:
        _начать(мир)
    assert err.value.kind == client.RATE_LIMITED
    assert мир["запусков"] == flow.MAX_STARTS_PER_INVITE


def test_осиротевший_поток_не_опрашивает_и_не_пишет(
    мир: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Сломанная копия: убрать `_is_current` из `_run` — поток опросит Dodo IS и запишет вход.
    вход = _начать(мир)
    flow.forget_all()  # вход вытеснили: поток больше не хозяин ссылки
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    мир["ответы_опроса"].append(ПАРА)
    устройство = DeviceStart(КОД_УСТРОЙСТВА, "ABCD-1234", "https://auth.dodois.com/d", 300, 5)
    flow._run(вход, КЛЮЧИ, устройство)
    assert мир["вход"] == [] and мир["ответы_опроса"] == [ПАРА], "осиротевший поток опросил Dodo IS"
