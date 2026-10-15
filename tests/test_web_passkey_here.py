"""Touch ID в браузере (D485): строка автосохранения после входа и автозапуск ключа по метке.

Без базы. Показывать ли строку в конкретном браузере (метка, одна попытка на вход) решает
скрипт, а не сервер: сервер отдаёт её скрытой, а скрипт обязан гасить автозапуск без метки,
поэтому его текст проверяется как часть договора.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from web_harness import ТОКЕН, Учётка, войти, подменить_двери, собрать

from src.domain.tenants import HQ_TENANT
from src.web import auth

ТЕНАНТ = HQ_TENANT
МАРКЕР = "data-passkey-here"
СТАТИКА = Path(__file__).resolve().parents[1] / "src" / "web" / "static"
ШАБЛОНЫ = Path(__file__).resolve().parents[1] / "src" / "web" / "templates"


def _страница(
    monkeypatch: pytest.MonkeyPatch,
    *,
    роль: str,
    есть_способ: bool,
    путь: str = "/settings",
    вход: datetime | None = None,
    ключи_включены: bool = True,
    коды: tuple[int, ...] = (200,),
) -> str:
    подменить_двери(monkeypatch, tenant=ТЕНАНТ, role=роль)
    monkeypatch.setattr(
        auth,
        "resolve_session",
        lambda token: (
            Учётка(tenant=ТЕНАНТ, role=роль, has_second_factor=есть_способ, signed_in_at=вход)
            if token == ТОКЕН
            else None
        ),
    )
    app = (
        собрать(tenant=ТЕНАНТ, webauthn_rp_id="localhost", webauthn_origin="http://localhost")
        if ключи_включены
        else собрать(tenant=ТЕНАНТ)
    )
    with app.test_client() as client:
        assert войти(client).status_code == 302
        ответ = client.get(путь, follow_redirects=True)
        assert ответ.status_code in коды, ответ.status_code
        return ответ.get_data(as_text=True)


@pytest.mark.parametrize("роль", ["developer", "admin", "superadmin", "control"])
@pytest.mark.parametrize("есть_способ", [True, False])
def test_ролям_веба_после_входа_строка_есть_со_способом_и_без(
    monkeypatch: pytest.MonkeyPatch, роль: str, есть_способ: bool
) -> None:
    страница = _страница(monkeypatch, роль=роль, есть_способ=есть_способ)

    assert МАРКЕР in страница
    assert 'data-options-url="/settings/security/passkey/options"' in страница
    assert 'data-register-url="/settings/security/passkey/register"' in страница
    assert "Включить вход по Touch ID в этом браузере" in страница
    # Скрыта разметкой: решает скрипт, по метке браузера и по тому, пробовали ли уже при этом входе.
    assert re.search(r"<button[^>]*data-passkey-here hidden", страница)
    assert 'data-session="' in страница


@pytest.mark.parametrize("роль", ["guest", "auditor"])
def test_гостю_и_аудитору_строки_нет(monkeypatch: pytest.MonkeyPatch, роль: str) -> None:
    assert МАРКЕР not in _страница(monkeypatch, роль=роль, есть_способ=False)


def test_плашки_подключения_два_шага_больше_нет(monkeypatch: pytest.MonkeyPatch) -> None:
    assert "data-enroll-banner" not in _страница(monkeypatch, роль="admin", есть_способ=False)


def test_на_экране_защиты_плашки_нет(monkeypatch: pytest.MonkeyPatch) -> None:
    # Базы нет: экран отвечает 503 «база недоступна», но в той же оболочке страницы.
    страница = _страница(
        monkeypatch, роль="admin", есть_способ=True, путь="/settings/security", коды=(200, 503)
    )

    assert МАРКЕР not in страница
    assert "<main" in страница


def test_позже_окна_подключения_плашки_нет(monkeypatch: pytest.MonkeyPatch) -> None:
    давно = datetime.now(UTC) - timedelta(hours=3)

    assert МАРКЕР not in _страница(monkeypatch, роль="admin", есть_способ=True, вход=давно)


def test_без_ключей_на_площадке_плашки_нет(monkeypatch: pytest.MonkeyPatch) -> None:
    assert МАРКЕР not in _страница(
        monkeypatch, роль="admin", есть_способ=True, ключи_включены=False
    )


def test_скрипт_запускает_ключ_сам_только_по_метке() -> None:
    js = (СТАТИКА / "passkey.js").read_text(encoding="utf-8")

    assert 'var HERE_KEY = "decimus.passkey.here"' in js
    assert re.search(
        r"if \(storageGet\(HERE_KEY\)\) \{\s*"
        r"if \(root\.hasAttribute\(\"data-passkey-autostart\"\)\) run\(true\);",
        js,
    ), "автозапуск ключа не стоит за меткой браузера"
    # Метка ставится после входа ключом, после автосохранения и если ключ уже есть на устройстве.
    assert js.count("storageSet(HERE_KEY)") >= 3


def test_автосохранение_пробует_один_раз_на_вход_и_без_кнопок_отказа() -> None:
    js = (СТАТИКА / "passkey.js").read_text(encoding="utf-8")

    assert 'var TRIED_KEY = "decimus.passkey.tried"' in js
    assert "storageSetValue(TRIED_KEY, session);\n    attempt(true);" in js
    assert "data-passkey-here-later" not in js


def test_на_форме_входа_нет_ключа_доступа(monkeypatch: pytest.MonkeyPatch) -> None:
    """Вход — Google или пароль; Touch ID только вторым шагом после пароля (D515)."""
    подменить_двери(monkeypatch, tenant=ТЕНАНТ, role="admin")
    app = собрать(tenant=ТЕНАНТ, webauthn_rp_id="localhost", webauthn_origin="http://localhost")

    with app.test_client() as client:
        страница = client.get("/login").get_data(as_text=True)

    assert "data-passkey-login" not in страница
    assert "data-passkey-autostart" not in страница
    assert "Touch ID" not in страница
    assert "passkey.js" not in страница


def test_вторая_ступень_стоит_у_пароля_и_не_стоит_у_google() -> None:
    from src.domain.journal import METHOD_GOOGLE, METHOD_PASSWORD
    from src.web import second_step

    assert second_step.step_required(METHOD_PASSWORD)
    assert not second_step.step_required(METHOD_GOOGLE)
    assert second_step.first_step_suffices(METHOD_GOOGLE)
    assert not second_step.first_step_suffices(METHOD_PASSWORD)
