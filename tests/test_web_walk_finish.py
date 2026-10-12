"""D422: «Завершить проверку» из приложения — тот же итог в чат, что даёт `/finish`.

Ядро — запуск сообщения человеку: без явного «да» владельца (`WALK_APP_FINISH`)
оно не уходит; уходит только в чат самого подписавшего; без подписи — 401.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from test_web_walk import АУДИТОР, ТОКЕН, _приложение
from test_web_walk_app import ПОСТОРОННИЙ, База, _действие, база  # noqa: F401 — фикстура

from src.web import walk_finish, walk_settings
from src.web.walk_auth import APP_PATH


def _клиент(monkeypatch: pytest.MonkeyPatch, **env: str) -> Any:
    return _приложение(
        monkeypatch,
        TELEGRAM_BOT_TOKEN=ТОКЕН,
        ALLOWED_TELEGRAM_IDS=str(АУДИТОР),
        **env,
    ).test_client()


@pytest.fixture
def отправки(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, int]]:
    """Подмена отправки итога: что и кому ушло бы в чат."""
    ушло: list[tuple[str, int]] = []

    def итог(token: str, chat_id: int) -> str:
        ушло.append((token, chat_id))
        return walk_finish.SENT

    monkeypatch.setattr(walk_settings, "send_summary", итог)
    return ушло


def test_выключено_сообщения_нет(
    база: База,  # noqa: F811
    отправки: list[tuple[str, int]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _клиент(monkeypatch)

    ответ = _действие(client, АУДИТОР, op="finish")

    assert ответ.status_code == 200 and ответ.get_json() == {"sent": False}
    assert отправки == [], "без «да» владельца новый запуск сообщения не работает"


def test_включено_итог_в_чат_самого_человека(
    база: База,  # noqa: F811
    отправки: list[tuple[str, int]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _клиент(monkeypatch, WALK_APP_FINISH="1")

    ответ = _действие(client, АУДИТОР, op="finish", chat=ПОСТОРОННИЙ)

    assert ответ.status_code == 200 and ответ.get_json() == {"sent": True}
    assert отправки == [(ТОКЕН, АУДИТОР)], "чат берётся из подписи, а не из тела запроса"


def test_без_подписи_401_и_ничего_не_ушло(
    база: База,  # noqa: F811
    отправки: list[tuple[str, int]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _клиент(monkeypatch, WALK_APP_FINISH="1")

    assert client.post(APP_PATH, json={"op": "finish"}).status_code == 401
    assert _действие(client, ПОСТОРОННИЙ, op="finish").status_code == 401
    assert отправки == []


def test_без_проверки_отказ_словами_и_бот_не_зван(
    база: База,  # noqa: F811
    domain_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def бот_не_нужен(*_: Any, **__: Any) -> None:
        raise AssertionError("бот не должен вызываться, если проверки нет")

    monkeypatch.setattr(walk_finish, "_send_summary", бот_не_нужен)
    client = _клиент(monkeypatch, WALK_APP_FINISH="1")

    ответ = _действие(client, АУДИТОР, op="finish")

    assert ответ.status_code == 409 and ответ.get_json()["error"] == "refused"


def test_итог_собирает_функция_команды_finish(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Тексты не дублируются: зовётся `show_summary` бота, один раз, для чата человека."""
    import aiogram

    from src.bot.routers import finish
    from src.domain import start_inspection

    start_inspection(АУДИТОР, unit="Белград-1", kind="planned", report_lang="ru", ui_lang="ru")
    вызовы: list[int] = []

    async def итог(_message: Any, chat_id: int, _lang: str, *, store: Any) -> None:
        вызовы.append(chat_id)

    class ПодменаБота:
        def __init__(self, token: str) -> None:
            self.session = self

        async def close(self) -> None: ...

    monkeypatch.setattr(finish, "show_summary", итог)
    monkeypatch.setattr(aiogram, "Bot", ПодменаБота)
    # `Message.as_` требует настоящий клиент; для проверки вызова хватит заготовки.
    monkeypatch.setattr("aiogram.types.Message.as_", lambda self, _bot: self)

    assert walk_finish.send_summary(ТОКЕН, АУДИТОР) == walk_finish.SENT
    assert вызовы == [АУДИТОР]
