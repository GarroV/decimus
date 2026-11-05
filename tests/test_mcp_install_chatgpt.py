"""Установщик для настольного ChatGPT (D695, #1439): раздача и живой прогон на подставном доме.

Прогон идёт против настоящего MCP-сервера на случайном порту (токен проверяется его же
дверью) и против ПОДСТАВНОГО `codex`, который лишь записывает свои аргументы: настоящий
ChatGPT и его `~/.codex` тест не трогает (`DECIMUS_CODEX_CLI`, `HOME`, `CODEX_HOME`).
Живой ChatGPT здесь не проверяется — только то, что скрипт делает на своей стороне.
"""

from __future__ import annotations

import hashlib
import stat
import subprocess
import threading
import urllib.request
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from src.bot.mcp_setup import chatgpt_installer_sha256, chatgpt_setup_command
from src.mcp.config import Settings
from src.mcp.install import CHATGPT_INSTALL_PATH, chatgpt_install_script
from src.mcp.server import build_server

ТОКЕН = "t" * 40
ПОДСТАВНОЙ_CODEX = """#!/bin/bash
# Подставной codex: пишет аргументы в журнал, `mcp get` и `mcp list` падают по флагу.
echo "$*" >> "$FAKE_CODEX_LOG"
if [ "$1 $2" = "mcp get" ] && [ -n "${FAKE_CODEX_GET_FAILS:-}" ]; then exit 1; fi
if [ "$1 $2" = "mcp list" ] && [ -n "${FAKE_CODEX_LIST_FAILS:-}" ]; then exit 1; fi
exit 0
"""


@pytest.fixture
def сервер() -> Iterator[str]:
    settings = Settings(tokens={ТОКЕН: "default"}, tenants=("default",), host="127.0.0.1", port=0)
    httpd: ThreadingHTTPServer = build_server(settings)
    поток = threading.Thread(target=httpd.serve_forever, daemon=True)
    поток.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        поток.join(timeout=5)


@pytest.fixture
def машина(tmp_path: Path) -> dict[str, Path]:
    """Подставной дом с чужим `config.toml` и подставным codex."""
    дом = tmp_path / "home"
    codex_home = дом / ".codex"
    codex_home.mkdir(parents=True)
    (codex_home / "config.toml").write_text('[mcp_servers.neighbour]\ncommand = "/bin/echo"\n')
    codex = tmp_path / "codex"
    codex.write_text(ПОДСТАВНОЙ_CODEX)
    codex.chmod(0o755)
    return {"home": дом, "codex": codex, "log": tmp_path / "codex.log"}


def _окружение(машина: dict[str, Path], **extra: str) -> dict[str, str]:
    return {
        "HOME": str(машина["home"]),
        "PATH": "/usr/bin:/bin",
        "DECIMUS_CODEX_CLI": str(машина["codex"]),
        "FAKE_CODEX_LOG": str(машина["log"]),
        **extra,
    }


def _прогон(
    машина: dict[str, Path], url: str, token: str = ТОКЕН, **extra: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/bash", "-s"],
        input=chatgpt_install_script(),
        text=True,
        capture_output=True,
        check=False,
        env=_окружение(машина, DECIMUS_MCP_URL=url, DECIMUS_MCP_TOKEN=token, **extra),
    )


def _вызовы(машина: dict[str, Path]) -> list[str]:
    журнал = машина["log"]
    return журнал.read_text().splitlines() if журнал.exists() else []


def test_раздаётся_без_токена_и_с_мостом(сервер: str) -> None:
    with urllib.request.urlopen(f"{сервер}{CHATGPT_INSTALL_PATH}", timeout=10) as ответ:  # noqa: S310
        тело = ответ.read().decode("utf-8")
        тип = ответ.headers.get("Content-Type", "")

    assert "text/plain" in тип
    assert тело == chatgpt_install_script()
    assert "\n@BRIDGE@\n" not in тело, "место для моста осталось пустым"
    assert "curl -sS --max-time 120" in тело, "тело моста не подставилось"
    assert ТОКЕН not in тело


def test_скрипт_разбирается_bash() -> None:
    разбор = subprocess.run(
        ["/bin/bash", "-n"],
        input=chatgpt_install_script(),
        text=True,
        capture_output=True,
        check=False,
    )
    assert разбор.returncode == 0, разбор.stderr


def test_установка_кладёт_мост_токен_и_регистрирует(сервер: str, машина: dict[str, Path]) -> None:
    прогон = _прогон(машина, сервер)

    assert прогон.returncode == 0, прогон.stderr
    корень = машина["home"] / ".decimus" / "chatgpt"
    assert (корень / "token").read_text() == ТОКЕН
    assert stat.S_IMODE((корень / "token").stat().st_mode) == 0o600
    assert (корень / "url").read_text() == сервер
    assert "curl" in (корень / "mcp_bridge.sh").read_text()
    запуск = (корень / "launch.sh").read_text()
    assert ТОКЕН not in запуск and "token" in запуск, "токен должен читаться из файла"
    вызовы = _вызовы(машина)
    assert f"mcp add decimus -- /bin/bash {корень}/launch.sh" in вызовы
    assert "mcp get decimus" in вызовы
    assert all(ТОКЕН not in строка for строка in вызовы), "токен ушёл в аргументы codex"
    копии = list((машина["home"] / ".codex").glob("config.toml.decimus-backup.*"))
    assert len(копии) == 1 and "neighbour" in копии[0].read_text(), "копия config.toml не снята"


def test_мост_из_каталога_стартует_через_launch(сервер: str, машина: dict[str, Path]) -> None:
    """launch.sh поднимает мост с адресом и токеном из файлов: ответ сервера доходит."""
    _прогон(машина, сервер)
    корень = машина["home"] / ".decimus" / "chatgpt"
    запрос = '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}\n'

    ответ = subprocess.run(  # noqa: S603
        ["/bin/bash", str(корень / "launch.sh")],
        input=запрос,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
        env={"HOME": str(машина["home"]), "PATH": "/usr/bin:/bin", "DECIMUS_MCP_NO_UPDATE": "1"},
    )

    assert '"result"' in ответ.stdout, f"мост не дошёл до сервера: {ответ.stdout} {ответ.stderr}"


def test_чужой_токен_ничего_не_пишет(сервер: str, машина: dict[str, Path]) -> None:
    прогон = _прогон(машина, сервер, token="x" * 40)

    assert прогон.returncode != 0
    assert "не принял токен" in прогон.stderr, прогон.stderr
    assert not (машина["home"] / ".decimus").exists(), "каталог создан при отказе токена"
    assert not any("mcp add" in строка for строка in _вызовы(машина))


@pytest.mark.parametrize(
    ("token", "url", "extra", "фраза"),
    [
        ("", None, {}, "Нет токена"),
        ("плохой токен", None, {}, "Неверный формат токена"),
        (ТОКЕН, "ftp://x", {}, "должен начинаться"),
        (ТОКЕН, "http://x/'; rm -rf ~; '", {}, "Неверный адрес"),
        (ТОКЕН, None, {"FAKE_CODEX_LIST_FAILS": "1"}, "Не удалось прочитать настройки MCP"),
        (ТОКЕН, None, {"FAKE_CODEX_GET_FAILS": "1"}, "ChatGPT его не видит"),
    ],
)
def test_ввод_ломается_понятной_ошибкой(
    сервер: str,
    машина: dict[str, Path],
    token: str,
    url: str | None,
    extra: dict[str, str],
    фраза: str,
) -> None:
    прогон = _прогон(машина, url or сервер, token, **extra)

    assert прогон.returncode != 0, "скрипт прошёл на сломанном вводе"
    assert фраза in прогон.stderr, прогон.stderr


def test_нет_сервера_файлы_не_тронуты(машина: dict[str, Path]) -> None:
    прогон = _прогон(машина, "http://127.0.0.1:9")

    assert прогон.returncode != 0
    assert "Нет связи" in прогон.stderr
    assert not (машина["home"] / ".decimus").exists()


def test_повторный_запуск_обновляет_запись(сервер: str, машина: dict[str, Path]) -> None:
    _прогон(машина, сервер)
    _прогон(машина, сервер)

    вызовы = _вызовы(машина)
    assert sum(1 for строка in вызовы if строка == "mcp remove decimus") == 2
    assert sum(1 for строка in вызовы if строка.startswith("mcp add decimus")) == 2


def test_строка_запуска_сверяет_отпечаток_и_падает_на_подмене(
    сервер: str, машина: dict[str, Path]
) -> None:
    команда = chatgpt_setup_command(url=сервер, token=ТОКЕН)
    отпечаток = chatgpt_installer_sha256()
    assert отпечаток == hashlib.sha256(chatgpt_install_script().encode("utf-8")).hexdigest()
    assert отпечаток in команда

    честная = subprocess.run(  # noqa: S603
        ["/bin/bash", "-c", команда],
        capture_output=True,
        text=True,
        env=_окружение(машина),
        check=False,
    )
    assert "Готово" in честная.stdout, честная.stderr
    токен_файл = машина["home"] / ".decimus" / "chatgpt" / "token"
    assert токен_файл.exists()
    assert ТОКЕН not in честная.stdout + честная.stderr

    # Негативный прогон: отпечаток подменён — скрипт не должен запуститься вовсе.
    чужой = команда.replace(отпечаток, "0" * 64)
    assert чужой != команда, "подмена отпечатка не применилась"
    токен_файл.unlink()
    подмена = subprocess.run(  # noqa: S603
        ["/bin/bash", "-c", чужой],
        capture_output=True,
        text=True,
        env=_окружение(машина),
        check=False,
    )
    assert "FAILED" in подмена.stderr + подмена.stdout, подмена.stderr
    assert "Готово" not in подмена.stdout
    assert not токен_файл.exists()
