"""«Входить по Touch ID в этом браузере?» (D485): плашка после входа и автозапуск по метке.

Без базы, как `test_web_enroll_banner.py`. Что плашка показывается именно в браузере без
метки, решает скрипт, а не сервер: сервер отдаёт её скрытой, а скрипт обязан гасить
автозапуск без метки, поэтому его текст проверяется как часть договора.
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


def test_админу_со_способом_после_входа_плашка_есть(monkeypatch: pytest.MonkeyPatch) -> None:
    страница = _страница(monkeypatch, роль="admin", есть_способ=True)

    assert МАРКЕР in страница
    assert 'data-options-url="/settings/security/passkey/options"' in страница
    assert 'data-register-url="/settings/security/passkey/register"' in страница
    assert "Входить по Touch ID в этом браузере?" in страница
    # Скрыта разметкой: показывает её скрипт, и только в браузере без метки.
    assert re.search(r"<div[^>]*data-passkey-here hidden", страница)


def test_разработчику_без_способа_плашки_нет(monkeypatch: pytest.MonkeyPatch) -> None:
    assert МАРКЕР not in _страница(monkeypatch, роль="developer", есть_способ=False)


def test_админу_без_способа_плашки_нет_у_него_плашка_подключения(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    страница = _страница(monkeypatch, роль="admin", есть_способ=False)

    assert МАРКЕР not in страница
    assert "data-enroll-banner" in страница


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
    # Метка ставится и после входа ключом, и после создания ключа (экран защиты и плашка).
    assert js.count("storageSet(HERE_KEY)") >= 4


def test_страница_подтверждения_не_запускает_ключ_безусловно() -> None:
    """Разметка лишь допускает автозапуск; без метки скрипт ведёт с поля кода."""
    html = (ШАБЛОНЫ / "login_second_step.html").read_text(encoding="utf-8")
    js = (СТАТИКА / "passkey.js").read_text(encoding="utf-8")

    assert "login__methods" in html
    assert "login__methods--code-first" in js
    assert re.search(r"<input[^>]*id=\"code\"[^>]*\bautofocus\b", html, re.S)
