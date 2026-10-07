"""Расхождение подключений к базе — в MCP своим кодом, а не «не подключено» (#521).

После #515 расхождение (`DatabaseTargetError`) — наследник `ConfigError`, и
инструменты, ловившие `ConfigError` целиком, отвечали на него «на этом стенде
не подключено: не задана переменная». Здесь проверяется, что каждое такое место
отвечает кодом `db_target` и общими словами — без баз, хостов, ролей и имён
переменных, — а подробности без пароля пишет в журнал сервера на ERROR.
И что незаданное подключение по-прежнему отвечает «не подключено».

Базы не нужно: расхождение находит сверка строк до первого подключения.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from mcp_checklist_harness import build_methodology

pytest.importorskip("psycopg")

import src.db.synonyms as synonyms_api
from src.db.errors import ConfigError as DbConfigError
from src.db.errors import DatabaseTargetError
from src.mcp import phrases, retraction, tools
from src.mcp.checklist import Store
from src.mcp.db_target import DB_TARGET_MISMATCH
from src.mcp.errors import ToolError
from src.mcp.rpc import handle

АРЕНДАТОР = "HQ"
ПАРОЛЬ = "s3cret-не-печатать"
#: Что из устройства стенда не должно попасть в ответ агенту.
ДЕТАЛИ = (
    "db.example",
    "shared",
    "stand",
    "dodo_audit_admin",
    "dodo_audit_app",
    "DATABASE_URL",
    "DATABASE_RETRACTION_URL",
    ПАРОЛЬ,
)
ПРОВЕРКА = "00000000-0000-4000-8000-000000000001"
СНЯТИЕ: dict[str, str] = {
    "id": ПРОВЕРКА,
    "reason": "отчёт ушёл не той точке",
    "confirm_unit": "Белград-1",
    "confirm_date": "2026-09-01",
}
ФРАЗЫ: dict[str, dict[str, Any]] = {
    "learned_phrases": {},
    "retract_learned_phrase": {"phrase": "грязный пол", "lang": "ru", "reason": "не туда"},
    "repoint_learned_phrase": {
        "phrase": "грязный пол",
        "lang": "ru",
        "item_code": "CLN01",
        "reason": "это про пол",
    },
}


@pytest.fixture
def разные_базы(monkeypatch: pytest.MonkeyPatch) -> None:
    """Приложение и администратор истории ведут в разные базы одного хоста."""
    monkeypatch.setenv("DATABASE_URL", f"postgresql://dodo_audit_app:{ПАРОЛЬ}@db.example/stand")
    monkeypatch.setenv(
        "DATABASE_RETRACTION_URL", f"postgresql://dodo_audit_admin:{ПАРОЛЬ}@db.example/shared"
    )
    monkeypatch.delenv("DATABASE_ADMIN_URL", raising=False)


def _расхождение(*_: Any, **__: Any) -> None:
    raise DatabaseTargetError(
        "DATABASE_RETRACTION_URL ведёт в базу shared на db.example:5432 (роль "
        "dodo_audit_admin), а DATABASE_URL — в stand на db.example:5432 (роль dodo_audit_app)"
    )


def _журнал(caplog: pytest.LogCaptureFixture) -> str:
    return " ".join(r.getMessage() for r in caplog.records if r.levelname == "ERROR")


def _ответ_без_деталей(текст: str) -> None:
    for деталь in ДЕТАЛИ:
        assert деталь not in текст, деталь


def _журнал_с_деталями(caplog: pytest.LogCaptureFixture) -> None:
    журнал = _журнал(caplog)
    assert "shared" in журнал, журнал
    assert "db.example" in журнал, журнал
    assert ПАРОЛЬ not in журнал


# --- снятие проверки: настоящая сверка подключений, без подмены ---------------


@pytest.mark.usefixtures("разные_базы")
def test_снятие_на_расхождении_баз_отвечает_своим_кодом(caplog: pytest.LogCaptureFixture) -> None:
    # Act
    with caplog.at_level("ERROR"), pytest.raises(ToolError) as пойман:
        retraction.retract_inspection(tenant=АРЕНДАТОР, **СНЯТИЕ)

    # Assert
    отказ = пойман.value
    assert отказ.refusal == "db_target"
    assert str(отказ) == DB_TARGET_MISMATCH
    assert str(отказ) != retraction.NOT_CONNECTED
    _ответ_без_деталей(str(отказ))
    _журнал_с_деталями(caplog)


def test_снятие_на_расхождении_у_самого_снятия_отвечает_своим_кодом(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Второе место перехвата — сам вызов `db.retract`, после чтения проверки."""
    import src.db.retract as retract_api

    monkeypatch.setattr(retract_api, "retract_inspection", _расхождение)

    with caplog.at_level("ERROR"), pytest.raises(ToolError) as пойман:
        retraction._retract(ПРОВЕРКА, tenant=АРЕНДАТОР, reason="не туда")

    assert пойман.value.refusal == "db_target"
    _ответ_без_деталей(str(пойман.value))
    _журнал_с_деталями(caplog)


def test_снятие_без_подключения_по_прежнему_не_настроено(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://dodo_audit_app@db.example/stand")
    monkeypatch.delenv("DATABASE_RETRACTION_URL", raising=False)

    with caplog.at_level("ERROR"), pytest.raises(ToolError) as пойман:
        retraction.retract_inspection(tenant=АРЕНДАТОР, **СНЯТИЕ)

    assert str(пойман.value) == retraction.NOT_CONNECTED
    assert пойман.value.refusal is None
    assert not _журнал(caplog)


# --- карта синонимов: через вход MCP целиком ----------------------------------


@pytest.fixture
def методика(tmp_path: Path) -> Store:
    return Store(root=tmp_path / "хранилище", live=build_methodology(tmp_path / "живая"))


def _отказ_инструмента(имя: str, методика: Store) -> str:
    ответ = handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": имя, "arguments": ФРАЗЫ[имя]},
        },
        tenant=АРЕНДАТОР,
        checklist=методика,
    )
    assert ответ is not None
    результат = ответ["result"]
    assert результат.get("isError") is True, результат
    return str(результат["content"][0]["text"])


@pytest.mark.parametrize("имя", sorted(ФРАЗЫ))
def test_карта_на_расхождении_баз_отвечает_общими_словами(
    имя: str,
    методика: Store,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    for функция in ("list_phrases", "retract_phrase", "repoint_phrase"):
        monkeypatch.setattr(synonyms_api, функция, _расхождение)

    with caplog.at_level("ERROR"):
        текст = _отказ_инструмента(имя, методика)

    assert текст == DB_TARGET_MISMATCH
    _ответ_без_деталей(текст)
    _журнал_с_деталями(caplog)


def test_карта_отдаёт_код_отказа() -> None:
    """Код виден у исключения: вход MCP отдаёт агенту текст, веб берёт код."""
    with pytest.raises(ToolError) as пойман, phrases._карта(правка=True):
        _расхождение()
    assert пойман.value.refusal == "db_target"


# --- чтение истории --------------------------------------------------------------


def test_чтение_на_расхождении_баз_отвечает_своим_кодом(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("ERROR"), pytest.raises(ToolError) as пойман, tools._history():
        _расхождение()

    assert пойман.value.refusal == "db_target"
    assert str(пойман.value) == DB_TARGET_MISMATCH
    _журнал_с_деталями(caplog)


def test_чтение_без_базы_по_прежнему_не_подключено() -> None:
    with pytest.raises(ToolError) as пойман, tools._history():
        raise DbConfigError("не задана DATABASE_URL")

    assert str(пойман.value) == tools.HISTORY_NOT_CONNECTED
    assert пойман.value.refusal is None


def test_текст_расхождения_не_называет_переменных() -> None:
    """Сторож самого текста: он один на все инструменты и уходит в модель."""
    _ответ_без_деталей(DB_TARGET_MISMATCH)
    assert "{" not in DB_TARGET_MISMATCH, "текст не шаблон: подставлять в него нечего"
