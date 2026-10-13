"""Настройки ключей доступа (D463): домен и происхождение из настроек, не из заголовков."""

from __future__ import annotations

import pytest

from src.web.config import Settings, WebConfigError
from src.web.config import load_settings as _load

ПРОД = "https://decimus.vasiliy-garro.workers.dev"


def load_settings(env: dict[str, str]) -> Settings:
    return _load({"WEB_TENANT": "HQ", **env})


def test_без_адреса_ключи_доступа_выключены() -> None:
    настройки = load_settings({})

    assert настройки.webauthn_rp_id is None
    assert настройки.webauthn_origin is None
    assert not настройки.webauthn_enabled


def test_домен_и_происхождение_берутся_из_внешнего_адреса_админки() -> None:
    настройки = load_settings({"ADMIN_PUBLIC_URL": f"{ПРОД}/admin"})

    assert настройки.webauthn_rp_id == "decimus.vasiliy-garro.workers.dev"
    assert настройки.webauthn_origin == ПРОД
    assert настройки.webauthn_enabled


def test_явные_настройки_главнее_внешнего_адреса() -> None:
    настройки = load_settings(
        {
            "ADMIN_PUBLIC_URL": ПРОД,
            "WEBAUTHN_RP_ID": "vasiliy-garro.workers.dev",
            "WEBAUTHN_ORIGIN": ПРОД,
        }
    )

    # Родитель хоста допустим, пока он не общий суффикс: здесь он — отдельный поддомен учётки.
    assert настройки.webauthn_rp_id == "vasiliy-garro.workers.dev"


@pytest.mark.parametrize("общий", ["workers.dev", "github.io", "pages.dev"])
def test_общий_суффикс_как_домен_ключа_отвергается(общий: str) -> None:
    with pytest.raises(WebConfigError, match="общий суффикс"):
        load_settings({"WEBAUTHN_ORIGIN": f"https://x.{общий}", "WEBAUTHN_RP_ID": общий})


def test_домен_ключа_не_родитель_хоста_отвергается() -> None:
    with pytest.raises(WebConfigError, match="не годится"):
        load_settings({"WEBAUTHN_ORIGIN": ПРОД, "WEBAUTHN_RP_ID": "evil.example"})


def test_домен_без_происхождения_отвергается() -> None:
    with pytest.raises(WebConfigError, match="без"):
        load_settings({"WEBAUTHN_RP_ID": "decimus.example"})


def test_происхождение_с_путём_отвергается() -> None:
    with pytest.raises(WebConfigError):
        load_settings({"WEBAUTHN_ORIGIN": f"{ПРОД}/admin"})


def test_ip_адрес_как_домен_отвергается() -> None:
    with pytest.raises(WebConfigError):
        load_settings({"WEBAUTHN_ORIGIN": "https://10.0.0.5", "WEBAUTHN_RP_ID": "10.0.0.5"})
