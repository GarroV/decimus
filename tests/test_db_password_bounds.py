"""Пароль длиннее `MAX_PASSWORD_LENGTH` отвергается ДО scrypt и до базы (ревью access2, L5).

scrypt над телом в сотни килобайт — работа, которую вошедший (или любой на
форме входа) заказывает одной отправкой. Предел сверху стоит у каждой двери,
которая хеширует пароль: заведение и смена (`_checked_password`), сверка
текущего при смене своего, вход. База здесь не нужна: проверяется, что до неё
и до scrypt дело не доходит.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.db import web_access
from src.db.errors import AccessError
from src.db.web_access import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH

ДЛИННЫЙ = "д" * (MAX_PASSWORD_LENGTH + 1)
ГОДНЫЙ = "г" * MIN_PASSWORD_LENGTH


@pytest.fixture(autouse=True)
def _без_scrypt_и_базы(monkeypatch: pytest.MonkeyPatch) -> None:
    """Каждая проверка здесь обязана отказать раньше scrypt и базы."""

    def _нельзя(*_: Any, **__: Any) -> Any:
        raise AssertionError("дошло до scrypt или базы")

    for имя in ("password_hash", "password_matches", "_connected", "_managing"):
        monkeypatch.setattr(web_access, имя, _нельзя)


def test_предел_разумный() -> None:
    assert MIN_PASSWORD_LENGTH < 64 <= MAX_PASSWORD_LENGTH <= 1024


def test_длинный_новый_отвергается_при_заведении() -> None:
    with pytest.raises(AccessError) as отказ:
        web_access.create_account("director", tenant="HQ", password=ДЛИННЫЙ)
    assert str(MAX_PASSWORD_LENGTH) in str(отказ.value)


def test_длинный_новый_отвергается_при_смене_командой() -> None:
    with pytest.raises(AccessError):
        web_access.change_password("director", tenant="HQ", password=ДЛИННЫЙ)


def test_длинный_новый_отвергается_при_смене_своего() -> None:
    with pytest.raises(AccessError):
        web_access.change_own_password("токен", current=ГОДНЫЙ, new=ДЛИННЫЙ)


def test_длинный_текущий_это_просто_не_тот() -> None:
    """Такого пароля не бывает ни у кого, значит ответ «не тот» ничего не выдаёт."""
    assert web_access.change_own_password("токен", current=ДЛИННЫЙ, new=ГОДНЫЙ) is False


def test_длинный_на_входе_это_просто_не_тот() -> None:
    assert web_access.authenticate("director", ДЛИННЫЙ) is None


def test_пароль_ровно_в_предел_проходит() -> None:
    assert web_access._checked_password("п" * MAX_PASSWORD_LENGTH) == "п" * MAX_PASSWORD_LENGTH
