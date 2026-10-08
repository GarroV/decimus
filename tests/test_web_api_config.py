"""`API_ENABLED` (#567): по умолчанию API закрыт, опечатка — отказ запуска."""

from __future__ import annotations

import pytest

from src.web.config import API_ENABLED_VAR, load_settings
from src.web.errors import WebConfigError

СТЕНД = {"WEB_TENANT": "HQ"}


def test_по_умолчанию_api_закрыт() -> None:
    assert load_settings(СТЕНД).api_enabled is False
    assert load_settings({**СТЕНД, API_ENABLED_VAR: "0"}).api_enabled is False


def test_единица_открывает() -> None:
    assert load_settings({**СТЕНД, API_ENABLED_VAR: "1"}).api_enabled is True


@pytest.mark.parametrize("значение", ["yes", "true", "2", "on"])
def test_опечатка_отказ(значение: str) -> None:
    with pytest.raises(WebConfigError, match=API_ENABLED_VAR):
        load_settings({**СТЕНД, API_ENABLED_VAR: значение})
