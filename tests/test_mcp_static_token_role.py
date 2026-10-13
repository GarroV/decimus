"""Роль служебного токена из `MCP_TOKENS`: без названной роли — только чтение.

Ядро прав (аудит, пункты по служебным токенам): раньше у токена из карты `.env`
роли не было, и `rpc` пропускал его мимо матрицы — правка методики, указатель
прода и загрузки открывались целиком. Теперь у записи есть роль
(`арендатор:роль=токен`), а без неё — `guest`; «роли нет» (`None`) отказывает
везде. Проверки идут через настоящий разбор `.env`, `resolve_access` и `handle`,
как ходит транспорт.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from typing import Any

import pytest

from src.mcp import ratelimit
from src.mcp.catalogue import TOOLS
from src.mcp.config import MCP_TOKENS_VAR, Settings, load_settings, resolve_access
from src.mcp.errors import McpConfigError
from src.mcp.ratelimit import CODE_RATE_LIMITED, McpRate, WindowLimiter
from src.mcp.rpc import ROLE_CLOSED, handle
from src.mcp.server import build_server

ТОКЕН_ГОСТЬ = "g" * 32
ТОКЕН_АДМИН = "a" * 32
ТОКЕН_ПАРТНЁР = "p" * 32

#: Инструменты, которые токену без роли видеть и звать нельзя.
ИЗМЕНЯЮЩИЕ = (
    "apply_checklist",
    "publish_checklist_version",
    "add_checklist_item",
    "edit_checklist_item",
    "create_checklist",
    "import_create_inspection",
    "import_ratings",
    "request_aggregators_update",
    "retract_inspection",
)


def _настройки(*записи: str) -> Settings:
    return load_settings({MCP_TOKENS_VAR: "\n".join(записи)})


def _список(настройки: Settings, токен: str) -> set[str]:
    доступ = resolve_access(настройки, f"Bearer {токен}")
    ответ = handle(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        tenant=доступ.tenant,
        may_retract=доступ.may_retract,
        role=доступ.role,
    )
    assert ответ is not None
    return {t["name"] for t in ответ["result"]["tools"]}


def _вызов(настройки: Settings, токен: str, имя: str) -> dict[str, Any]:
    доступ = resolve_access(настройки, f"Bearer {токен}")
    ответ = handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": имя, "arguments": {}},
        },
        tenant=доступ.tenant,
        may_retract=доступ.may_retract,
        actor=доступ.actor,
        role=доступ.role,
    )
    assert ответ is not None
    return ответ


# --- разбор записи -------------------------------------------------------------


def test_запись_без_роли_читается_как_прежде_и_получает_чтение() -> None:
    доступ = resolve_access(_настройки(f"HQ={ТОКЕН_ГОСТЬ}"), f"Bearer {ТОКЕН_ГОСТЬ}")

    assert доступ.tenant == "HQ"
    assert доступ.role == "guest"
    assert доступ.actor == "mcp:HQ"


def test_запись_с_ролью_называет_её_после_двоеточия() -> None:
    настройки = _настройки(f"HQ:admin={ТОКЕН_АДМИН}", f"HQ={ТОКЕН_ГОСТЬ}")

    assert resolve_access(настройки, f"Bearer {ТОКЕН_АДМИН}").role == "admin"
    assert resolve_access(настройки, f"Bearer {ТОКЕН_ГОСТЬ}").role == "guest"
    assert настройки.tenants == ("HQ",)


def test_двоеточие_в_самом_токене_не_читается_ролью() -> None:
    токен = "tok:en:" + "x" * 30
    доступ = resolve_access(_настройки(f"HQ={токен}"), f"Bearer {токен}")

    assert доступ.tenant == "HQ" and доступ.role == "guest"


@pytest.mark.parametrize("запись", ["HQ:root", "HQ:auditor", "HQ:"])
def test_неизвестная_роль_в_записи_это_отказ_запуска(запись: str) -> None:
    with pytest.raises(McpConfigError) as отказ:
        _настройки(f"{запись}={ТОКЕН_АДМИН}")

    assert MCP_TOKENS_VAR in str(отказ.value)
    assert ТОКЕН_АДМИН not in str(отказ.value)


def test_токен_партнёра_без_роли_закрыт_целиком() -> None:
    """У партнёра роли «только чтение» нет: запись без роли ничего не открывает."""
    настройки = _настройки(f"partner-a={ТОКЕН_ПАРТНЁР}")

    assert _список(настройки, ТОКЕН_ПАРТНЁР) == set()


# --- права: ядро ---------------------------------------------------------------


def test_токен_без_роли_не_видит_изменяющих_инструментов() -> None:
    видно = _список(_настройки(f"HQ={ТОКЕН_ГОСТЬ}"), ТОКЕН_ГОСТЬ)

    assert "list_inspections" in видно
    assert видно.isdisjoint(ИЗМЕНЯЮЩИЕ)


@pytest.mark.parametrize("имя", ИЗМЕНЯЮЩИЕ)
def test_токен_без_роли_получает_отказ_на_изменяющий_вызов(имя: str) -> None:
    ответ = _вызов(_настройки(f"HQ={ТОКЕН_ГОСТЬ}"), ТОКЕН_ГОСТЬ, имя)

    assert ответ["result"]["isError"] is True
    assert ответ["result"]["content"][0]["text"] == ROLE_CLOSED.format(роль="guest")


def test_токен_с_ролью_admin_видит_и_зовёт_изменяющее() -> None:
    настройки = _настройки(f"HQ:admin={ТОКЕН_АДМИН}")

    видно = _список(настройки, ТОКЕН_АДМИН)
    assert {"apply_checklist", "publish_checklist_version", "add_checklist_item"} <= видно
    ответ = _вызов(настройки, ТОКЕН_АДМИН, "apply_checklist")
    # Роль не закрывает: отказ, если он есть, — уже настройки (методика не открыта).
    assert ответ["result"]["content"][0]["text"] != ROLE_CLOSED.format(роль="admin")


def test_снятие_проверки_выдаётся_только_правом_из_карты_снятия() -> None:
    """Матрица закрывает снятие всем ролям; открывает его только `MCP_RETRACTION_TOKENS`."""
    без = load_settings({MCP_TOKENS_VAR: f"HQ:admin={ТОКЕН_АДМИН}"})
    с = load_settings(
        {MCP_TOKENS_VAR: f"HQ:admin={ТОКЕН_АДМИН}", "MCP_RETRACTION_TOKENS": ТОКЕН_АДМИН}
    )

    assert "retract_inspection" not in _список(без, ТОКЕН_АДМИН)
    assert "retract_inspection" in _список(с, ТОКЕН_АДМИН)


def test_роль_none_отказывает_везде_включая_tools_list() -> None:
    список = handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, tenant="HQ", role=None)
    assert список is not None and список["result"]["tools"] == []

    for spec in TOOLS:
        ответ = handle(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": spec.name, "arguments": {}},
            },
            tenant="HQ",
            may_retract=True,
            role=None,
        )
        assert ответ is not None
        assert ответ["result"]["isError"] is True, spec.name
        assert ответ["result"]["content"][0]["text"] == ROLE_CLOSED.format(роль="—"), spec.name


# --- ограничитель частоты --------------------------------------------------------


def test_окно_пускает_предел_и_отказывает_сверх_него() -> None:
    часы = [0.0]
    окно = WindowLimiter(3, clock=lambda: часы[0], window=60.0)

    assert [окно.allow("k") for _ in range(4)] == [True, True, True, False]
    assert окно.allow("другой") is True, "счётчик у каждого ключа свой"
    часы[0] = 61.0
    assert окно.allow("k") is True, "окно ушло вперёд — предел снова свободен"


def test_ключ_токена_это_отпечаток_а_не_токен() -> None:
    assert ТОКЕН_АДМИН not in ratelimit.token_key(ТОКЕН_АДМИН)


@pytest.fixture
def сервер(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[str, McpRate]]:
    настройки = _настройки(f"HQ:admin={ТОКЕН_АДМИН}", f"HQ={ТОКЕН_ГОСТЬ}")
    httpd: ThreadingHTTPServer = build_server(настройки)
    счётчик = httpd.rate  # type: ignore[attr-defined]
    поток = threading.Thread(target=httpd.serve_forever, daemon=True)
    поток.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}/", счётчик
    finally:
        httpd.shutdown()
        httpd.server_close()
        поток.join(timeout=5)


def _пинг(адрес: str, токен: str) -> tuple[int, Any]:
    запрос = urllib.request.Request(  # noqa: S310 — адрес свой, петля
        адрес,
        data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {токен}"},
    )
    try:
        with urllib.request.urlopen(запрос, timeout=10) as ответ:  # noqa: S310
            return ответ.status, json.loads(ответ.read())
    except urllib.error.HTTPError as отказ:
        return отказ.code, json.loads(отказ.read())


def test_сервер_отвечает_429_сверх_предела_токена_и_не_трогает_соседний_токен(
    сервер: tuple[str, McpRate],
) -> None:
    адрес, счётчик = сервер
    счётчик.by_token = WindowLimiter(2)

    коды = [_пинг(адрес, ТОКЕН_ГОСТЬ)[0] for _ in range(3)]
    код, тело = _пинг(адрес, ТОКЕН_ГОСТЬ)

    assert коды == [200, 200, 429]
    assert код == 429 and тело["error"]["code"] == CODE_RATE_LIMITED
    assert _пинг(адрес, ТОКЕН_АДМИН)[0] == 200


def test_сервер_отвечает_429_сверх_предела_адреса(сервер: tuple[str, McpRate]) -> None:
    адрес, счётчик = сервер
    счётчик.by_address = WindowLimiter(1)

    assert _пинг(адрес, "z" * 32)[0] == 401
    assert _пинг(адрес, "y" * 32)[0] == 429, "перебор токенов считается по адресу"
    # Неудачи постороннего с того же (общего, прокси) адреса не отрезают
    # клиента с действующим токеном.
    assert _пинг(адрес, ТОКЕН_ГОСТЬ)[0] == 200


# --- журнал изменяющих вызовов ---------------------------------------------------


def test_журнал_пишет_автора_и_инструмент_но_не_токен(
    сервер: tuple[str, McpRate], capsys: pytest.CaptureFixture[str]
) -> None:
    адрес, _ = сервер
    запрос = urllib.request.Request(  # noqa: S310
        адрес,
        data=json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "apply_checklist", "arguments": {"секрет": "тело"}},
            }
        ).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {ТОКЕН_ГОСТЬ}"},
    )
    with urllib.request.urlopen(запрос, timeout=10):  # noqa: S310
        pass

    журнал = capsys.readouterr().err
    строка = next(л for л in журнал.splitlines() if л.startswith("[mcp-audit]"))
    assert "actor=mcp:HQ" in строка and "role=guest" in строка
    assert "tool=apply_checklist" in строка
    assert "token=" in строка
    assert ТОКЕН_ГОСТЬ not in журнал and "тело" not in журнал


def test_чтение_в_журнал_не_пишется(
    сервер: tuple[str, McpRate], capsys: pytest.CaptureFixture[str]
) -> None:
    адрес, _ = сервер
    _пинг(адрес, ТОКЕН_ГОСТЬ)

    assert "[mcp-audit]" not in capsys.readouterr().err
