"""Команда `tools/api_token.py` (#567): значение токена печатается один раз.

Импорт команды читает `.env` репозитория; в тесте чтение подменено, иначе в
окружение набора приехали бы подключения стенда (#356).
"""

from __future__ import annotations

import importlib
import re
from types import ModuleType

import pytest
from conftest import requires_db
from db_harness import set_retraction_env

pytest.importorskip("psycopg")

from src.db import api_tokens

pytestmark = requires_db


@pytest.fixture
def команда(db_env: str, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    set_retraction_env(db_env, monkeypatch)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *_a, **_k: False)
    return importlib.import_module("tools.api_token")


def test_выпуск_печатает_значение_один_раз(
    команда: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    код = команда.main(["issue", "swarm", "--scope", "ratings:read", "--by", "tester"])
    вывод = capsys.readouterr().out

    assert код == 0
    (значение,) = re.findall(r"dcm_[A-Za-z0-9_-]{43}", вывод)
    assert api_tokens.resolve(значение) is not None

    assert команда.main(["list"]) == 0
    список = capsys.readouterr().out
    assert "swarm" in список and значение not in список

    (строка,) = api_tokens.list_tokens()
    assert команда.main(["revoke", строка.id, "--by", "tester"]) == 0
    assert api_tokens.resolve(значение) is None
    assert команда.main(["revoke", строка.id, "--by", "tester"]) == 1


def test_неизвестное_право_отказ_до_базы(команда: ModuleType) -> None:
    with pytest.raises(SystemExit):
        команда.main(["issue", "swarm", "--scope", "ratings:write", "--by", "tester"])
