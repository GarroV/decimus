"""D422, D447: «Завершить проверку» из приложения — сводка или сразу отчёт.

Ядро — запуск сообщения человеку: оно уходит только по подписанному запросу и
только в чат самого подписавшего; отчёт не собирается на язык вне перечня
страны и при незаполненных сведениях; режим хранится за человеком, умолчание —
сначала сводка.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from test_web_walk import АУДИТОР, ТОКЕН, _приложение
from test_web_walk_app import КОЛЛЕГА, ПОСТОРОННИЙ, База, _действие, база  # noqa: F401 — фикстура

from src.bot.info import fields_to_ask
from src.db.errors import DbError
from src.domain import set_info, start_inspection
from src.web import walk, walk_finish, walk_settings
from src.web.walk_auth import APP_PATH


def _клиент(monkeypatch: pytest.MonkeyPatch) -> Any:
    return _приложение(
        monkeypatch,
        TELEGRAM_BOT_TOKEN=ТОКЕН,
        ALLOWED_TELEGRAM_IDS=f"{АУДИТОР},{КОЛЛЕГА}",
    ).test_client()


@pytest.fixture
def итоги(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, int]]:
    """Подмена отправки итога: что и кому ушло бы в чат."""
    ушло: list[tuple[str, int]] = []

    def итог(token: str, chat_id: int) -> str:
        ушло.append((token, chat_id))
        return walk_finish.SENT

    monkeypatch.setattr(walk_settings.walk_finish, "send_summary", итог)
    return ушло


@pytest.fixture
def отчёты(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, int]]:
    """Подмена фоновой сборки отчёта: запуск записывается, чат остаётся занятым."""
    запущено: list[tuple[str, int]] = []
    monkeypatch.setattr(
        walk_finish, "_run_report", lambda token, chat: запущено.append((token, chat))
    )
    walk_finish._building.clear()
    yield запущено
    walk_finish._building.clear()


def _начать() -> None:
    start_inspection(АУДИТОР, unit="Белград-1", kind="planned", report_lang="ru", ui_lang="ru")


def _заполнить_сведения() -> None:
    for поле, _ in fields_to_ask("ru", chat_id=АУДИТОР):
        set_info(АУДИТОР, поле.code, "ответ")


def _режим(client: Any, кто: int, режим: str) -> Any:
    return _действие(client, кто, op="finish_mode", mode=режим)


# ── сводка (умолчание) ────────────────────────────────────────────────────


def test_по_умолчанию_сводка_в_чат_самого_человека(
    база: База,  # noqa: F811
    итоги: list[tuple[str, int]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _клиент(monkeypatch)

    ответ = _действие(client, АУДИТОР, op="finish", chat=ПОСТОРОННИЙ)

    assert ответ.status_code == 200 and ответ.get_json() == {"sent": True, "mode": "summary"}
    assert итоги == [(ТОКЕН, АУДИТОР)], "чат берётся из подписи, а не из тела запроса"


@pytest.mark.parametrize("режим", ["summary", "report"])
def test_без_подписи_401_и_ничего_не_ушло(
    база: База,  # noqa: F811
    итоги: list[tuple[str, int]],
    отчёты: list[tuple[str, int]],
    monkeypatch: pytest.MonkeyPatch,
    режим: str,
) -> None:
    client = _клиент(monkeypatch)
    база.режим[АУДИТОР] = режим

    assert client.post(APP_PATH, json={"op": "finish"}).status_code == 401
    assert _действие(client, ПОСТОРОННИЙ, op="finish").status_code == 401
    assert итоги == [] and отчёты == []


def test_без_проверки_отказ_словами_и_бот_не_зван(
    база: База,  # noqa: F811
    domain_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def бот_не_нужен(*_: Any, **__: Any) -> None:
        raise AssertionError("бот не должен вызываться, если проверки нет")

    monkeypatch.setattr(walk_finish, "_send_summary", бот_не_нужен)
    client = _клиент(monkeypatch)

    ответ = _действие(client, АУДИТОР, op="finish")

    assert ответ.status_code == 409 and ответ.get_json()["error"] == "refused"


def test_итог_собирает_функция_команды_finish(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Тексты не дублируются: зовётся `show_summary` бота, один раз, для чата человека."""
    import aiogram

    from src.bot.routers import finish

    _начать()
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


# ── режим хранится за человеком ───────────────────────────────────────────


def test_режим_по_умолчанию_сводка_и_хранится_за_человеком(
    база: База,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _клиент(monkeypatch)

    до = _действие(client, АУДИТОР, op="lang", lang="ru").get_json()["app"]["finish_mode"]
    после = _режим(client, АУДИТОР, "report").get_json()["app"]["finish_mode"]
    у_коллеги = _действие(client, КОЛЛЕГА, op="lang", lang="ru").get_json()["app"]["finish_mode"]

    assert (до, после, у_коллеги) == ("summary", "report", "summary")


def test_чужой_режим_отказ_и_ничего_не_записано(
    база: База,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _клиент(monkeypatch)

    for режим in ("both", "", None, 1):
        assert _действие(client, АУДИТОР, op="finish_mode", mode=режим).status_code == 422
    assert база.режим == {}


def test_база_молчит_режим_по_умолчанию_сводка(
    база: База,  # noqa: F811
    итоги: list[tuple[str, int]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def молчит(_: int) -> None:
        raise DbError("нет базы")

    monkeypatch.setattr(walk_settings.finish_modes, "chosen_finish_mode", молчит)
    client = _клиент(monkeypatch)

    ответ = _действие(client, АУДИТОР, op="finish")

    assert ответ.get_json() == {"sent": True, "mode": "summary"}


# ── «Сразу отчёт» ─────────────────────────────────────────────────────────


def test_отчёт_сразу_уходит_в_чат_подписавшего(
    база: База,  # noqa: F811
    отчёты: list[tuple[str, int]],
    domain_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _начать()
    _заполнить_сведения()
    client = _клиент(monkeypatch)
    _режим(client, АУДИТОР, "report")

    ответ = _действие(client, АУДИТОР, op="finish", report_lang="en", chat=ПОСТОРОННИЙ)

    assert ответ.status_code == 200 and ответ.get_json() == {"sent": True, "mode": "report"}
    assert отчёты == [(ТОКЕН, АУДИТОР)]
    from src.domain import get_state

    state = get_state(АУДИТОР)
    assert state is not None and state.report_lang == "en"


def test_язык_вне_перечня_страны_отказ_и_ничего_не_собрано(
    база: База,  # noqa: F811
    отчёты: list[tuple[str, int]],
    domain_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _начать()
    _заполнить_сведения()
    client = _клиент(monkeypatch)
    _режим(client, АУДИТОР, "report")

    for тело in ({"report_lang": "ka"}, {"report_lang": 5}, {}):
        ответ = _действие(client, АУДИТОР, op="finish", **тело)
        assert ответ.status_code == 409, тело
    assert отчёты == []


def test_сведения_не_заполнены_отказ_со_счётом_и_ничего_не_собрано(
    база: База,  # noqa: F811
    отчёты: list[tuple[str, int]],
    domain_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _начать()
    client = _клиент(monkeypatch)
    _режим(client, АУДИТОР, "report")
    осталось = len(fields_to_ask("ru", chat_id=АУДИТОР))
    assert осталось > 0

    ответ = _действие(client, АУДИТОР, op="finish", report_lang="ru")

    тело = ответ.get_json()
    assert ответ.status_code == 409 and тело["reason"] == "info" and тело["count"] == осталось
    assert str(осталось) in тело["message"]
    assert отчёты == []


def test_второе_нажатие_пока_собирается_отказ(
    база: База,  # noqa: F811
    отчёты: list[tuple[str, int]],
    domain_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _начать()
    _заполнить_сведения()
    client = _клиент(monkeypatch)
    _режим(client, АУДИТОР, "report")

    первое = _действие(client, АУДИТОР, op="finish", report_lang="ru")
    второе = _действие(client, АУДИТОР, op="finish", report_lang="ru")

    assert первое.status_code == 200 and второе.status_code == 409
    assert отчёты == [(ТОКЕН, АУДИТОР)], "сборка запущена один раз"


def test_экран_отдаёт_языки_отчёта_только_в_режиме_отчёта(
    база: База,  # noqa: F811
    domain_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _начать()
    client = _клиент(monkeypatch)

    def данные() -> dict[str, Any]:
        from test_web_walk import подписать

        return client.post(
            walk.DATA_PATH, data=подписать(АУДИТОР), content_type="text/plain"
        ).get_json()

    до = данные()
    _режим(client, АУДИТОР, "report")
    после = данные()

    assert "report_langs" not in до
    assert [x["code"] for x in после["report_langs"]] == ["ru", "en"]


def test_отчёт_собирает_функция_чата_для_чата_человека(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Тексты и сборка не дублируются: зовётся `deliver` бота, без права пропускать кадры."""
    import aiogram

    from src.bot.routers import finish

    _начать()
    вызовы: list[tuple[int, int, bool]] = []

    async def собрать(message: Any, chat_id: int, _lang: str, *, allow_missing: bool) -> None:
        вызовы.append((message.chat.id, chat_id, allow_missing))

    class ПодменаБота:
        def __init__(self, token: str) -> None:
            self.session = self

        async def close(self) -> None: ...

    monkeypatch.setattr(finish, "deliver", собрать)
    monkeypatch.setattr(aiogram, "Bot", ПодменаБота)
    monkeypatch.setattr("aiogram.types.Message.as_", lambda self, _bot: self)
    walk_finish._building.add(АУДИТОР)

    walk_finish._run_report(ТОКЕН, АУДИТОР)

    assert вызовы == [(АУДИТОР, АУДИТОР, False)]
    assert АУДИТОР not in walk_finish._building, "после сборки чат освобождается"
