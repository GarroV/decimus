"""Блок «Ключ модели» на «Подключениях» (D491): кто пройдёт, ключ только на запись, проверка.

База и провайдер подменены на границе модулей (`model_key`, `client.verify_key`): здесь
поверхность — заслон, один показ нигде, отказ непринятого ключа. Настоящая база и
шифрование — `tests/test_db_model_key.py`. Заслон и «ключа нет в ответе» — ядро
безопасности: каждая проверка прогонялась на сломанной копии.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from flask.testing import FlaskClient
from web_harness import СВОЙ, войти, подменить_двери, собрать

from src.db import model_key, secret_crypto
from src.domain.journal import summarize_target
from src.recognize import client
from src.recognize.errors import ModelKeyRejected, ModelUnavailable
from src.web import model_key_screen, reauth

ЗАГОЛОВКИ = {"Origin": СВОЙ}
ВКЛАДКА = "/users?tab=connections"
КЛЮЧ = "sk-proj-Zq9Xw8Vv7Uu6Tt5Ss4Rr3Qq2Pp1-никому-не-показывать"
ПОЛЕ = model_key_screen.FIELD
АДРЕСА = [f"/users/connections/model-key/{д}" for д in ("check", "save", "delete")]
РОЛИ = [("HQ", "admin"), ("HQ", "control"), ("HQ", "auditor"), ("GE", "admin"), ("GE", "auditor")]


class Склад:
    """Двойник `model_key` и провайдера: что звали и что записано."""

    def __init__(self) -> None:
        self.запись: model_key.KeyStatus | None = None
        self.зовы: list[tuple[str, Any]] = []
        self.проверка: Exception | None = None
        self.нет_шифрования = False

    def status(self) -> model_key.KeyStatus | None:
        return self.запись

    def save(self, value: str, *, by: str, provider: str = "openai") -> model_key.KeyStatus:
        self.зовы.append(("save", (value, by)))
        if self.нет_шифрования:
            raise secret_crypto.SecretCryptoError("Не задан SECRETS_KEY")
        self.запись = model_key.KeyStatus(provider, value[-4:], by, datetime.now(UTC))
        return self.запись

    def clear(self) -> bool:
        self.зовы.append(("clear", None))
        было, self.запись = self.запись is not None, None
        return было

    def verify(self, value: str) -> None:
        self.зовы.append(("verify", value))
        if self.проверка is not None:
            raise self.проверка

    def записи(self) -> list[str]:
        return [имя for имя, _ in self.зовы if имя in {"save", "clear"}]


@pytest.fixture
def склад(monkeypatch: pytest.MonkeyPatch) -> Склад:
    склад = Склад()
    monkeypatch.setattr(model_key, "status", склад.status)
    monkeypatch.setattr(model_key, "save", склад.save)
    monkeypatch.setattr(model_key, "clear", склад.clear)
    monkeypatch.setattr(client, "verify_key", склад.verify)
    # Остальное на вкладке — перечень ключей API — здесь не предмет.
    from src.db import api_access

    monkeypatch.setattr(api_access, "list_tokens", lambda: [])
    return склад


def _стенд(monkeypatch: pytest.MonkeyPatch, *, tenant: str, role: str) -> Iterator[FlaskClient]:
    подменить_двери(monkeypatch, tenant=tenant, role=role)
    with собрать(tenant="HQ").test_client() as клиент:
        assert войти(клиент).status_code == 302
        yield клиент


@pytest.fixture
def главный(monkeypatch: pytest.MonkeyPatch, склад: Склад) -> Iterator[FlaskClient]:
    yield from _стенд(monkeypatch, tenant="HQ", role="superadmin")


def _отправить(клиент: FlaskClient, действие: str, значение: str = КЛЮЧ) -> Any:
    return клиент.post(
        f"/users/connections/model-key/{действие}", data={ПОЛЕ: значение}, headers=ЗАГОЛОВКИ
    )


# --- кто пройдёт ---------------------------------------------------------------------------


def test_главный_админ_видит_блок_и_запасной_ключ(главный: FlaskClient) -> None:
    html = главный.get(ВКЛАДКА).get_data(as_text=True)
    assert "Ключ модели" in html and "Новый ключ" in html
    assert 'type="password"' in html and "настроек сервера" in html


def test_блок_на_английском(monkeypatch: pytest.MonkeyPatch, склад: Склад) -> None:
    подменить_двери(monkeypatch, tenant="HQ", role="superadmin")
    with собрать(tenant="HQ", ui_lang="en").test_client() as клиент:
        войти(клиент)
        html = клиент.get(ВКЛАДКА).get_data(as_text=True)
    assert "Model key" in html and "New key" in html and "Новый ключ" not in html


@pytest.mark.parametrize(("tenant", "role"), РОЛИ)
def test_остальным_экрана_нет_ни_на_чтение_ни_на_запись(
    monkeypatch: pytest.MonkeyPatch, склад: Склад, tenant: str, role: str
) -> None:
    for клиент in _стенд(monkeypatch, tenant=tenant, role=role):
        читать = клиент.get(ВКЛАДКА)
        assert читать.status_code == 404, f"{role}@{tenant} открыл вкладку"
        assert "Ключ модели" not in читать.get_data(as_text=True)
        for адрес in АДРЕСА:
            ответ = клиент.post(адрес, data={ПОЛЕ: КЛЮЧ}, headers=ЗАГОЛОВКИ)
            assert ответ.status_code == 404, f"{role}@{tenant} достучался до {адрес}"
    assert склад.зовы == [], "чужая роль дошла до базы или провайдера"


@pytest.mark.parametrize("адрес", АДРЕСА)
def test_чужое_происхождение_отказ_и_без_действия(
    главный: FlaskClient, склад: Склад, адрес: str
) -> None:
    без = главный.post(адрес, data={ПОЛЕ: КЛЮЧ})
    чужой = главный.post(адрес, data={ПОЛЕ: КЛЮЧ}, headers={"Origin": "https://evil.example"})
    assert (без.status_code, чужой.status_code) == (403, 403)
    assert склад.зовы == []


@pytest.mark.parametrize("адрес", АДРЕСА)
def test_несвежий_вход_уводит_на_подтверждение_без_действия(
    главный: FlaskClient, склад: Склад, monkeypatch: pytest.MonkeyPatch, адрес: str
) -> None:
    # Сломанная копия: убрать `require_fresh` из `_key_action` — тест падает на 200.
    monkeypatch.setattr(reauth, "is_fresh", lambda *_a, **_k: False)
    ответ = главный.post(адрес, data={ПОЛЕ: КЛЮЧ}, headers=ЗАГОЛОВКИ)
    assert ответ.status_code == 302 and reauth.CONFIRM_PATH in ответ.headers["Location"]
    assert склад.зовы == []


# --- сохранить: проверка до записи; ключа в ответе нет -------------------------------------


def test_сохранение_проверяет_шифрует_и_показывает_только_последние_четыре(
    главный: FlaskClient, склад: Склад, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        ответ = _отправить(главный, "save")
    html = ответ.get_data(as_text=True)
    assert ответ.status_code == 200 and "проверен и сохранён" in html
    assert [и for и, _ in склад.зовы] == ["verify", "save"], "сначала проверка, потом запись"
    assert склад.зовы[1][1] == (КЛЮЧ, "director")
    assert "••••" + КЛЮЧ[-4:] in html and "director" in html
    повтор = главный.get(ВКЛАДКА)
    for текст in (html, повтор.get_data(as_text=True), str(ответ.headers), caplog.text):
        assert КЛЮЧ not in текст, "ключ целиком попал на страницу, в заголовок или в журнал"
        assert КЛЮЧ[:-4] not in текст, "ключ без хвоста попал наружу"


def test_отказ_не_подставляет_введённое_обратно(главный: FlaskClient, склад: Склад) -> None:
    склад.проверка = ModelKeyRejected("нет")
    html = _отправить(главный, "save").get_data(as_text=True)
    assert КЛЮЧ not in html


def test_непринятый_ключ_не_записывается(главный: FlaskClient, склад: Склад) -> None:
    # Сломанная копия: пропустить `_verify` в `save` — запись появляется, тест падает.
    склад.проверка = ModelKeyRejected("нет")
    ответ = _отправить(главный, "save")
    assert ответ.status_code == 422 and "не принят провайдером" in ответ.get_data(as_text=True)
    assert склад.записи() == []


def test_непроверенный_ключ_не_записывается(главный: FlaskClient, склад: Склад) -> None:
    склад.проверка = ModelUnavailable("сеть")
    ответ = _отправить(главный, "save")
    assert ответ.status_code == 422 and "не проверен и не сохранён" in ответ.get_data(as_text=True)
    assert склад.записи() == []


def test_проверить_ничего_не_пишет(главный: FlaskClient, склад: Склад) -> None:
    ответ = _отправить(главный, "check")
    assert ответ.status_code == 200 and "принял ключ" in ответ.get_data(as_text=True)
    assert склад.записи() == []
    assert КЛЮЧ not in ответ.get_data(as_text=True)


@pytest.mark.parametrize("значение", ["", "   ", "два слова", "ключ\nс переносом", "k" * 500])
def test_негодная_форма_отбивается_до_провайдера(
    главный: FlaskClient, склад: Склад, значение: str
) -> None:
    ответ = _отправить(главный, "save", значение)
    assert ответ.status_code == 400
    assert склад.зовы == []


def test_без_ключа_шифрования_ничего_не_сохраняется_и_это_сказано(
    главный: FlaskClient, склад: Склад
) -> None:
    склад.нет_шифрования = True
    ответ = _отправить(главный, "save")
    html = ответ.get_data(as_text=True)
    assert ответ.status_code == 503 and "SECRETS_KEY" in html and КЛЮЧ not in html
    assert склад.запись is None


# --- удалить -------------------------------------------------------------------------------


def test_удаление_возвращает_запасной_ключ(главный: FlaskClient, склад: Склад) -> None:
    _отправить(главный, "save")
    ответ = главный.post("/users/connections/model-key/delete", headers=ЗАГОЛОВКИ)
    html = ответ.get_data(as_text=True)
    assert ответ.status_code == 200 and "Ключ удалён" in html
    assert склад.запись is None and "настроек сервера" in html


# --- журнал действий -----------------------------------------------------------------------


def test_журнал_действий_не_берёт_значение_ключа() -> None:
    # Сломанная копия: назвать поле `code` — значение попадает в сводку, тест падает.
    # Ключ здесь «кодоподобный» (латиница, цифры, дефис): от показа его спасает только имя поля.
    ключ = "sk-proj-Zq9Xw8Vv7Uu6Tt5Ss4Rr3Qq2Pp1"
    сводка = summarize_target({}, {ПОЛЕ: ключ})
    assert ключ not in сводка and ключ[:8] not in сводка
