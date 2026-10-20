"""Блок «Ключи сервисов» на «Подключениях» (D491, D576): кто пройдёт, значение только на запись.

База и провайдеры подменены на границе модулей (`service_keys`, `service_probes.PROBES`):
здесь поверхность — заслоны, один показ нигде, отказ непринятого значения, второй шаг и
свежесть, предел попыток, журнал действий. Настоящая база и шифрование —
`tests/test_db_service_keys.py`. Заслоны и «значения нет в ответе» — ядро безопасности:
каждая проверка прогонялась на сломанной копии (в докстринге или комментарии теста сказано,
что именно ломали).
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from flask.testing import FlaskClient
from web_harness import СВОЙ, войти, подменить_двери, собрать

from src.db import secret_crypto, service_keys
from src.domain import service_keys as registry
from src.web import auth, reauth, service_probes
from src.web.service_probes import KeyRejected, KeyUnverified

ЗАГОЛОВКИ = {"Origin": СВОЙ}
ВКЛАДКА = "/users?tab=connections"
ЗНАЧЕНИЕ = "sk-proj-Zq9Xw8Vv7Uu6Tt5Ss4Rr3Qq2Pp1-никому-не-показывать"
ID_ISPRING = "ispring-client-id-AAAA1111BBBB2222"
SECRET_ISPRING = "ispring-client-secret-CCCC3333DDDD4444"
ДЕЙСТВИЯ = ("check", "save", "delete")
СЕРВИСЫ = [s.code for s in registry.SERVICES]
РОЛИ = [("HQ", "admin"), ("HQ", "control"), ("HQ", "auditor"), ("GE", "admin"), ("GE", "auditor")]


def _форма(сервис: str, значение: str = ЗНАЧЕНИЕ) -> dict[str, str]:
    return {registry.form_name(f.code): значение for f in registry.service(сервис).fields}  # type: ignore[union-attr]


def _адрес(сервис: str, действие: str) -> str:
    return f"/users/connections/keys/{сервис}/{действие}"


class Склад:
    """Двойник `service_keys` и провайдеров: что звали и что записано."""

    def __init__(self) -> None:
        self.записи: dict[str, service_keys.KeyStatus] = {}
        self.зовы: list[tuple[str, Any]] = []
        self.проверка: Exception | None = None
        self.нет_шифрования = False

    def statuses(self) -> dict[str, service_keys.KeyStatus]:
        return dict(self.записи)

    def save_many(
        self, values: dict[str, str], *, provider: str, by: str
    ) -> dict[str, service_keys.KeyStatus]:
        self.зовы.append(("save", (dict(values), provider, by)))
        if self.нет_шифрования:
            raise secret_crypto.SecretCryptoError("Не задан SECRETS_KEY")
        for имя, значение in values.items():
            self.записи[имя] = service_keys.KeyStatus(
                provider, значение[-4:], by, datetime.now(UTC)
            )
        return {имя: self.записи[имя] for имя in values}

    def clear_many(self, names: tuple[str, ...]) -> bool:
        self.зовы.append(("clear", names))
        было = any(n in self.записи for n in names)
        for n in names:
            self.записи.pop(n, None)
        return было

    def probe(self, values: dict[str, str]) -> None:
        self.зовы.append(("verify", dict(values)))
        if self.проверка is not None:
            raise self.проверка

    def записывающие(self) -> list[str]:
        return [имя for имя, _ in self.зовы if имя in {"save", "clear"}]


@pytest.fixture
def склад(monkeypatch: pytest.MonkeyPatch) -> Склад:
    склад = Склад()
    monkeypatch.setattr(service_keys, "statuses", склад.statuses)
    monkeypatch.setattr(service_keys, "save_many", склад.save_many)
    monkeypatch.setattr(service_keys, "clear_many", склад.clear_many)
    for код in СЕРВИСЫ:
        monkeypatch.setitem(service_probes.PROBES, код, склад.probe)
    from src.db import api_access

    monkeypatch.setattr(api_access, "list_tokens", lambda: [])
    return склад


def _стенд(
    monkeypatch: pytest.MonkeyPatch, *, tenant: str, role: str
) -> Iterator[tuple[FlaskClient, dict[str, list[Any]]]]:
    двери = подменить_двери(monkeypatch, tenant=tenant, role=role)
    with собрать(tenant="HQ").test_client() as клиент:
        assert войти(клиент).status_code == 302
        yield клиент, двери


@pytest.fixture
def стенд(
    monkeypatch: pytest.MonkeyPatch, склад: Склад
) -> Iterator[tuple[FlaskClient, dict[str, list[Any]]]]:
    yield from _стенд(monkeypatch, tenant="HQ", role="superadmin")


@pytest.fixture
def главный(стенд: tuple[FlaskClient, dict[str, list[Any]]]) -> FlaskClient:
    return стенд[0]


def _сессия_с(monkeypatch: pytest.MonkeyPatch, **признаки: Any) -> None:
    """Подменить опознанную учётку: второй шаг, давность входа и т.п."""
    прежняя = auth.resolve_session

    def _resolve(token: str) -> Any:
        учётка = прежняя(token)
        for имя, значение in признаки.items():
            setattr(учётка, имя, значение)
        return учётка

    monkeypatch.setattr(auth, "resolve_session", _resolve)


def _отправить(клиент: FlaskClient, сервис: str, действие: str, значение: str = ЗНАЧЕНИЕ) -> Any:
    return клиент.post(_адрес(сервис, действие), data=_форма(сервис, значение), headers=ЗАГОЛОВКИ)


# --- кто пройдёт ---------------------------------------------------------------------------


def test_главный_админ_видит_все_сервисы_и_поля_без_значений(главный: FlaskClient) -> None:
    html = главный.get(ВКЛАДКА).get_data(as_text=True)
    assert "Ключи сервисов" in html
    for название in ("OpenAI", "Pointer", "iSpring", "Client ID", "Client secret"):
        assert название in html
    assert html.count('type="password"') == 4
    assert 'autocomplete="new-password"' in html and 'autocomplete="off"' in html
    assert "Не задан" in html


def test_блок_на_английском(monkeypatch: pytest.MonkeyPatch, склад: Склад) -> None:
    подменить_двери(monkeypatch, tenant="HQ", role="superadmin")
    with собрать(tenant="HQ", ui_lang="en").test_client() as клиент:
        войти(клиент)
        html = клиент.get(ВКЛАДКА).get_data(as_text=True)
    assert "Service keys" in html and "Replace" in html and "Ключи сервисов" not in html


def test_запись_видна_как_последние_четыре_и_кто_поставил(
    главный: FlaskClient, склад: Склад
) -> None:
    склад.записи["pointer.api_key"] = service_keys.KeyStatus(
        "pointer", "wxyz", "director", datetime.now(UTC)
    )
    html = главный.get(ВКЛАДКА).get_data(as_text=True)
    assert "••••wxyz" in html and "director" in html and "Задан в админке" in html


def test_окружение_называется_окружением(
    главный: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("POINTER_API_KEY", "из-окружения-1234567")
    html = главный.get(ВКЛАДКА).get_data(as_text=True)
    assert "Из окружения сервера" in html and "из-окружения-1234567" not in html


@pytest.mark.parametrize(("tenant", "role"), РОЛИ)
def test_остальным_экрана_нет_ни_на_чтение_ни_на_запись(
    monkeypatch: pytest.MonkeyPatch, склад: Склад, tenant: str, role: str
) -> None:
    # Сломанная копия: в маршрутах заменить `keys.manage` на `view.users` — тест падает на 200/302.
    for клиент, _ in _стенд(monkeypatch, tenant=tenant, role=role):
        читать = клиент.get(ВКЛАДКА)
        assert читать.status_code == 404, f"{role}@{tenant} открыл вкладку"
        assert "Ключи сервисов" not in читать.get_data(as_text=True)
        for сервис in СЕРВИСЫ:
            for действие in ДЕЙСТВИЯ:
                ответ = клиент.post(
                    _адрес(сервис, действие), data=_форма(сервис), headers=ЗАГОЛОВКИ
                )
                assert ответ.status_code == 404, (
                    f"{role}@{tenant} достучался до {сервис}/{действие}"
                )
    assert склад.зовы == [], "чужая роль дошла до базы или провайдера"


def test_неизвестный_сервис_404_и_без_действия(главный: FlaskClient, склад: Склад) -> None:
    for действие in ДЕЙСТВИЯ:
        ответ = главный.post(
            f"/users/connections/keys/evil/{действие}",
            data={"secret_api_key": ЗНАЧЕНИЕ},
            headers=ЗАГОЛОВКИ,
        )
        assert ответ.status_code == 404
    assert склад.зовы == []


@pytest.mark.parametrize("действие", ДЕЙСТВИЯ)
def test_чужое_происхождение_отказ_и_без_действия(
    главный: FlaskClient, склад: Склад, действие: str
) -> None:
    без = главный.post(_адрес("pointer", действие), data=_форма("pointer"))
    чужой = главный.post(
        _адрес("pointer", действие),
        data=_форма("pointer"),
        headers={"Origin": "https://evil.example"},
    )
    assert (без.status_code, чужой.status_code) == (403, 403)
    assert склад.зовы == []


# --- второй шаг и свежесть -----------------------------------------------------------------


@pytest.mark.parametrize("действие", ДЕЙСТВИЯ)
def test_несвежее_подтверждение_уводит_на_подтверждение_без_действия(
    стенд: tuple[FlaskClient, dict[str, list[Any]]],
    склад: Склад,
    monkeypatch: pytest.MonkeyPatch,
    действие: str,
) -> None:
    # Сломанная копия: убрать `require_fresh` из `_key_gate` — тест падает на 200.
    # Вход 11 минут назад: общее окно в 12 часов его бы пустило, окно ключей — нет.
    _сессия_с(monkeypatch, signed_in_at=datetime.now(UTC) - timedelta(minutes=11))
    ответ = _отправить(стенд[0], "ispring", действие)
    assert ответ.status_code == 302 and reauth.CONFIRM_PATH in ответ.headers["Location"]
    assert склад.зовы == []


def test_свежее_подтверждение_внутри_десяти_минут_пускает(
    стенд: tuple[FlaskClient, dict[str, list[Any]]],
    склад: Склад,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _сессия_с(monkeypatch, signed_in_at=datetime.now(UTC) - timedelta(minutes=9))
    assert _отправить(стенд[0], "pointer", "save").status_code == 200


def test_окно_ключей_не_меняет_общее_окно_других_действий() -> None:
    учётка = type("А", (), {"signed_in_at": datetime.now(UTC) - timedelta(minutes=11)})()
    assert reauth.is_fresh(учётка) is True
    assert reauth.is_fresh(учётка, max_age=timedelta(minutes=10)) is False


@pytest.mark.parametrize("действие", ДЕЙСТВИЯ)
def test_без_второго_шага_входа_отказ_с_понятным_текстом(
    стенд: tuple[FlaskClient, dict[str, list[Any]]],
    склад: Склад,
    monkeypatch: pytest.MonkeyPatch,
    действие: str,
) -> None:
    # Сломанная копия: убрать проверку `has_second_factor` в `_key_gate` — падает на 200.
    _сессия_с(monkeypatch, has_second_factor=False)
    ответ = _отправить(стенд[0], "pointer", действие)
    html = ответ.get_data(as_text=True)
    assert ответ.status_code == 403
    assert "Включите второй шаг входа в Настройки → Безопасность" in html
    assert склад.зовы == []


def test_второй_шаг_не_пройден_в_этой_сессии_отказ(
    стенд: tuple[FlaskClient, dict[str, list[Any]]],
    склад: Склад,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Сессия после Google или пароля: способ у учётки есть, но в сессии он не доказан (D485).
    # Сломанная копия: убрать проверку `passed_second_step` — падает на 200.
    _сессия_с(monkeypatch, passed_second_step=False)
    ответ = _отправить(стенд[0], "pointer", "save")
    assert ответ.status_code == 403
    assert "Подтвердите второй шаг входа" in ответ.get_data(as_text=True)
    assert склад.зовы == []


# --- сохранить: проверка до записи; значения в ответе нет ----------------------------------


@pytest.mark.parametrize("сервис", СЕРВИСЫ)
def test_сохранение_проверяет_шифрует_и_показывает_только_последние_четыре(
    главный: FlaskClient, склад: Склад, caplog: pytest.LogCaptureFixture, сервис: str
) -> None:
    with caplog.at_level(logging.DEBUG):
        ответ = _отправить(главный, сервис, "save")
    html = ответ.get_data(as_text=True)
    assert ответ.status_code == 200 and "Проверено у провайдера и сохранено" in html
    assert [и for и, _ in склад.зовы] == ["verify", "save"], "сначала проверка, потом запись"
    _, (значения, провайдер, кто) = склад.зовы[1]
    assert провайдер == сервис and кто == "director"
    assert set(значения) == {f.vault_name for f in registry.service(сервис).fields}  # type: ignore[union-attr]
    assert "••••" + ЗНАЧЕНИЕ[-4:] in html
    повтор = главный.get(ВКЛАДКА)
    for текст in (html, повтор.get_data(as_text=True), str(ответ.headers), caplog.text):
        assert ЗНАЧЕНИЕ not in текст, (
            "значение целиком попало на страницу, в заголовок или в журнал"
        )
        assert ЗНАЧЕНИЕ[:-4] not in текст, "значение без хвоста попало наружу"


def test_ответ_не_кэшируется(главный: FlaskClient) -> None:
    # Заголовок держат двое (`_page` и общий `security_headers`): тест видит итог.
    for ответ in (главный.get(ВКЛАДКА), _отправить(главный, "pointer", "save")):
        assert "no-store" in ответ.headers["Cache-Control"]


def test_ispring_проверяется_и_пишется_парой(главный: FlaskClient, склад: Склад) -> None:
    данные = {"secret_client_id": ID_ISPRING, "secret_client_secret": SECRET_ISPRING}
    ответ = главный.post(_адрес("ispring", "save"), data=данные, headers=ЗАГОЛОВКИ)
    html = ответ.get_data(as_text=True)
    assert ответ.status_code == 200
    assert склад.зовы[0] == ("verify", {"client_id": ID_ISPRING, "client_secret": SECRET_ISPRING})
    assert склад.зовы[1][1][0] == {
        "ispring.client_id": ID_ISPRING,
        "ispring.client_secret": SECRET_ISPRING,
    }
    assert ID_ISPRING not in html and SECRET_ISPRING not in html


def test_ispring_без_одного_поля_не_идёт_к_провайдеру(главный: FlaskClient, склад: Склад) -> None:
    ответ = главный.post(
        _адрес("ispring", "save"), data={"secret_client_id": ID_ISPRING}, headers=ЗАГОЛОВКИ
    )
    assert ответ.status_code == 400 and склад.зовы == []


@pytest.mark.parametrize(
    ("ошибка", "код", "текст"),
    [
        (KeyRejected(401), 422, "ответ 401"),
        (KeyRejected(None), 422, "не принял значение"),
        (KeyUnverified(None), 422, "не проверено и не сохранено"),
        (KeyUnverified(503), 422, "ответил 503"),
    ],
)
def test_непринятое_или_непроверенное_не_записывается(
    главный: FlaskClient, склад: Склад, ошибка: Exception, код: int, текст: str
) -> None:
    # Сломанная копия: пропустить `_verify` в `save` — запись появляется, тест падает.
    склад.проверка = ошибка
    ответ = _отправить(главный, "ispring", "save")
    html = ответ.get_data(as_text=True)
    assert ответ.status_code == код and текст in html
    assert склад.записывающие() == [] and склад.записи == {}
    assert ЗНАЧЕНИЕ not in html, "отказ подставил введённое обратно"


def test_проверить_ничего_не_пишет(главный: FlaskClient, склад: Склад) -> None:
    ответ = _отправить(главный, "pointer", "check")
    assert ответ.status_code == 200 and "принял значение" in ответ.get_data(as_text=True)
    assert склад.записывающие() == []
    assert ЗНАЧЕНИЕ not in ответ.get_data(as_text=True)


@pytest.mark.parametrize("значение", ["", "   ", "два слова", "ключ\nс переносом", "k" * 500])
def test_негодная_форма_отбивается_до_провайдера(
    главный: FlaskClient, склад: Склад, значение: str
) -> None:
    ответ = _отправить(главный, "pointer", "save", значение)
    assert ответ.status_code == 400
    assert склад.зовы == []


def test_без_ключа_шифрования_ничего_не_сохраняется_и_это_сказано(
    главный: FlaskClient, склад: Склад
) -> None:
    склад.нет_шифрования = True
    ответ = _отправить(главный, "pointer", "save")
    html = ответ.get_data(as_text=True)
    assert ответ.status_code == 503 and "SECRETS_KEY" in html and ЗНАЧЕНИЕ not in html
    assert склад.записи == {}


# --- удалить -------------------------------------------------------------------------------


def test_удаление_убирает_все_поля_сервиса(главный: FlaskClient, склад: Склад) -> None:
    главный.post(
        _адрес("ispring", "save"),
        data={"secret_client_id": ID_ISPRING, "secret_client_secret": SECRET_ISPRING},
        headers=ЗАГОЛОВКИ,
    )
    ответ = главный.post(_адрес("ispring", "delete"), headers=ЗАГОЛОВКИ)
    assert ответ.status_code == 200 and "Удалено" in ответ.get_data(as_text=True)
    assert склад.записи == {}
    assert склад.зовы[-1] == ("clear", ("ispring.client_id", "ispring.client_secret"))


def test_удалять_нечего_говорит_об_этом(главный: FlaskClient, склад: Склад) -> None:
    ответ = главный.post(_адрес("pointer", "delete"), headers=ЗАГОЛОВКИ)
    assert ответ.status_code == 409 and "ничего не задано" in ответ.get_data(as_text=True)


# --- предел попыток ------------------------------------------------------------------------


def test_подряд_идущие_неудачи_запирают_проверку(главный: FlaskClient, склад: Склад) -> None:
    # Сломанная копия: убрать `admit_service_key_action` из `_key_gate` — шестая идёт к провайдеру.
    склад.проверка = KeyRejected(401)
    for _ in range(5):
        assert _отправить(главный, "pointer", "check").status_code == 422
    зовов = len(склад.зовы)
    ответ = _отправить(главный, "pointer", "check")
    assert ответ.status_code == 429 and "Слишком много попыток" in ответ.get_data(as_text=True)
    assert len(склад.зовы) == зовов, "запертая попытка дошла до провайдера"


def test_удача_обнуляет_счёт(главный: FlaskClient, склад: Склад) -> None:
    склад.проверка = KeyRejected(401)
    for _ in range(4):
        _отправить(главный, "pointer", "check")
    склад.проверка = None
    assert _отправить(главный, "pointer", "check").status_code == 200
    склад.проверка = KeyRejected(401)
    for _ in range(5):
        assert _отправить(главный, "pointer", "check").status_code == 422


# --- журнал действий -----------------------------------------------------------------------


def _записи_журнала(двери: dict[str, list[Any]]) -> list[dict[str, Any]]:
    return двери["action_journal"]


def test_журнал_получает_сервис_поля_и_хвост_но_не_значение(
    стенд: tuple[FlaskClient, dict[str, list[Any]]], склад: Склад
) -> None:
    # Сломанная копия: убрать `TARGET_OVERRIDE` в `journal.action_target` — цель записи
    # собирается из формы; тест про имя поля с суффиксом `_id` ниже падает на утечке.
    клиент, двери = стенд
    клиент.post(
        _адрес("ispring", "save"),
        data={"secret_client_id": ID_ISPRING, "secret_client_secret": SECRET_ISPRING},
        headers=ЗАГОЛОВКИ,
    )
    запись = _записи_журнала(двери)[-1]
    assert запись["action"] == "service_key_save" and запись["outcome"] == "200"
    assert запись["target"] == (
        f"service=ispring; set=client_id:{ID_ISPRING[-4:]},client_secret:{SECRET_ISPRING[-4:]}"
    )
    for значение in (ID_ISPRING, SECRET_ISPRING):
        assert значение[:-4] not in str(запись)


def test_журнал_не_берёт_значение_и_при_отказе(
    стенд: tuple[FlaskClient, dict[str, list[Any]]], склад: Склад
) -> None:
    клиент, двери = стенд
    склад.проверка = KeyRejected(401)
    _отправить(клиент, "pointer", "save")
    запись = _записи_журнала(двери)[-1]
    assert запись["target"] == "service=pointer" and запись["outcome"] == "422"
    assert ЗНАЧЕНИЕ[:-4] not in str(запись)


def test_журнал_даже_если_имя_поля_допускает_показ_не_берёт_значение(
    стенд: tuple[FlaskClient, dict[str, list[Any]]],
    склад: Склад,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Поле названо `api_key_id`: правило по именам его бы показало. Значение держит явная цель.
    монитор = "kodopodobnoe-znachenie-1234567890"
    monkeypatch.setattr(registry, "form_name", lambda код: f"{код}_id")
    клиент, двери = стенд
    клиент.post(_адрес("pointer", "save"), data={"api_key_id": монитор}, headers=ЗАГОЛОВКИ)
    assert монитор not in str(_записи_журнала(двери)[-1])


# --- оформление: обе локали ----------------------------------------------------------------


def test_тексты_обеих_локалей_заведены_для_каждого_ключа() -> None:
    from src.web.texts_service_keys import SERVICE_KEYS_TEXTS

    for ключ, значения in SERVICE_KEYS_TEXTS.items():
        assert set(значения) == {"ru", "en"} and all(v.strip() for v in значения.values()), ключ
    for сервис in registry.SERVICES:
        assert f"keys.service.{сервис.code}" in SERVICE_KEYS_TEXTS
        assert f"keys.purpose.{сервис.code}" in SERVICE_KEYS_TEXTS
        for поле in сервис.fields:
            assert f"keys.field.{поле.code}" in SERVICE_KEYS_TEXTS
