"""Самообновление моста (D626): мост на старте сверяется с сервером и заменяет себя.

Мост запускается по-настоящему — из подставного дома, по тому пути, где его кладёт
установщик (`~/.decimus/bin/mcp_bridge.sh`), против поддельного сервера на случайном
порту. «Новый мост», который отдаёт сервер, — крошечный скрипт с маркером и большей
версией: по его выводу видно, что после замены работает именно он.
"""

# ruff: noqa: S603 — аргументы subprocess здесь собраны из путей подставного дома, чужого ввода нет
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

BRIDGE = Path(__file__).resolve().parents[1] / "tools" / "mcp_bridge.sh"
ТОКЕН = "t" * 40
НОВАЯ_ВЕРСИЯ = 999
ПРИВЕТ = "NEW-BRIDGE-RUNNING"

pytestmark = pytest.mark.skipif(
    shutil.which("shasum") is None,
    reason="нужен shasum (macOS): самообновление моста здесь НЕ проверено",
)

# Шапка повторяет то, что мост проверяет у скачанного файла: шебанг, маркер, версия.
НОВЫЙ_МОСТ = (
    "#!/bin/bash\n"
    "# Мост stdio ↔ HTTP для MCP-сервера проверок (T095).\n"
    f"BRIDGE_VERSION={НОВАЯ_ВЕРСИЯ}\n"
    f'echo "{ПРИВЕТ}"\n'
)


@dataclass
class _Сервер:
    url: str
    script: str = НОВЫЙ_МОСТ
    #: Какую сумму сервер объявляет; по умолчанию — настоящую от `script`.
    sha: str | None = None
    version: int = НОВАЯ_ВЕРСИЯ
    token_ok: list[bool] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)


@pytest.fixture
def сервер() -> Iterator[_Сервер]:
    state = _Сервер(url="")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: object) -> None:
            return

        def _reply(self, status: int, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            state.paths.append(self.path)
            state.token_ok.append(self.headers.get("Authorization") == f"Bearer {ТОКЕН}")
            if self.path == "/bridge":
                sha = state.sha or hashlib.sha256(state.script.encode()).hexdigest()
                self._reply(200, json.dumps({"version": state.version, "sha256": sha}).encode())
            elif self.path == "/bridge/script":
                self._reply(200, state.script.encode())
            else:
                self._reply(404, b"")

        def do_POST(self) -> None:
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            self._reply(200, b'{"jsonrpc":"2.0","id":1,"result":{"tools":[]}}')

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    поток = threading.Thread(target=httpd.serve_forever, daemon=True)
    поток.start()
    state.url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    try:
        yield state
    finally:
        httpd.shutdown()
        httpd.server_close()
        поток.join(timeout=5)


@pytest.fixture
def установленный(tmp_path: Path) -> tuple[Path, Path]:
    """Подставной дом с мостом там, где его оставляет установщик. Возвращает (дом, файл)."""
    дом = tmp_path / "home"
    файл = дом / ".decimus" / "bin" / "mcp_bridge.sh"
    файл.parent.mkdir(parents=True)
    shutil.copy(BRIDGE, файл)
    файл.chmod(0o700)
    return дом, файл


def _запустить(
    дом: Path, файл: Path, url: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/bash", str(файл)],
        input='{"jsonrpc":"2.0","id":1,"method":"tools/list"}\n',
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
        env={
            "HOME": str(дом),
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "DECIMUS_MCP_URL": url,
            "DECIMUS_MCP_TOKEN": ТОКЕН,
            **(env or {}),
        },
    )


def test_новая_версия_на_сервере_заменяет_файл_и_работает_уже_она(
    сервер: _Сервер, установленный: tuple[Path, Path]
) -> None:
    дом, файл = установленный

    прогон = _запустить(дом, файл, сервер.url)

    assert файл.read_text(encoding="utf-8") == НОВЫЙ_МОСТ
    assert ПРИВЕТ in прогон.stdout, "после замены должна работать новая версия"
    assert oct(файл.stat().st_mode & 0o777) == "0o700"
    assert "обновлён до версии 999" in прогон.stderr
    assert all(сервер.token_ok), "токен ушёл не заголовком Authorization"
    assert [p.name for p in файл.parent.iterdir()] == ["mcp_bridge.sh"], "остался временный файл"


def test_битая_сумма_файл_не_заменяет(сервер: _Сервер, установленный: tuple[Path, Path]) -> None:
    дом, файл = установленный
    было = файл.read_bytes()
    сервер.sha = "0" * 64

    прогон = _запустить(дом, файл, сервер.url)

    assert файл.read_bytes() == было
    assert ПРИВЕТ not in прогон.stdout
    assert "сумма файла не сошлась" in прогон.stderr
    assert '"tools"' in прогон.stdout, "прежний мост обязан продолжить работу"
    assert [p.name for p in файл.parent.iterdir()] == ["mcp_bridge.sh"]


def test_файл_без_маркера_моста_не_ставится_даже_с_верной_суммой(
    сервер: _Сервер, установленный: tuple[Path, Path]
) -> None:
    дом, файл = установленный
    было = файл.read_bytes()
    сервер.script = f"#!/bin/bash\nBRIDGE_VERSION={НОВАЯ_ВЕРСИЯ}\necho чужой\n"

    прогон = _запустить(дом, файл, сервер.url)

    assert файл.read_bytes() == было
    assert "файл не похож на мост" in прогон.stderr


def test_сервер_недоступен_мост_работает_старой_версией(
    установленный: tuple[Path, Path],
) -> None:
    дом, файл = установленный
    было = файл.read_bytes()

    # Порт 9 (discard) на loopback закрыт: соединение отказывает сразу.
    прогон = _запустить(дом, файл, "http://127.0.0.1:9/")

    assert файл.read_bytes() == было
    assert прогон.stderr.count("обновление моста пропущено") == 1
    assert "нет связи" in прогон.stderr, "обычная работа моста не должна пропасть"


def test_та_же_версия_ничего_не_качает(сервер: _Сервер, установленный: tuple[Path, Path]) -> None:
    дом, файл = установленный
    сервер.version = 1

    прогон = _запустить(дом, файл, сервер.url)

    assert "/bridge/script" not in сервер.paths
    assert ПРИВЕТ not in прогон.stdout
    assert '"tools"' in прогон.stdout


@pytest.mark.parametrize("env", [{"DECIMUS_MCP_NO_UPDATE": "1"}, {"DECIMUS_BRIDGE_UPDATED": "1"}])
def test_выключенная_проверка_сервер_не_спрашивает(
    сервер: _Сервер, установленный: tuple[Path, Path], env: dict[str, str]
) -> None:
    дом, файл = установленный

    _запустить(дом, файл, сервер.url, env)

    assert "/bridge" not in сервер.paths


def test_мост_вне_папки_установщика_себя_не_трогает(сервер: _Сервер, tmp_path: Path) -> None:
    """Запуск из рабочей копии репозитория не должен переписать файл разработчика."""
    дом = tmp_path / "home"
    дом.mkdir()
    копия = tmp_path / "checkout" / "mcp_bridge.sh"
    копия.parent.mkdir()
    shutil.copy(BRIDGE, копия)
    было = копия.read_bytes()

    _запустить(дом, копия, сервер.url)

    assert копия.read_bytes() == было
    assert "/bridge" not in сервер.paths


def test_адрес_не_https_и_не_эта_машина_не_запрашивается(
    сервер: _Сервер, установленный: tuple[Path, Path]
) -> None:
    дом, файл = установленный
    было = файл.read_bytes()

    прогон = _запустить(дом, файл, "http://example.invalid/")

    assert файл.read_bytes() == было
    assert "адрес не https" in прогон.stderr
    assert сервер.paths == []
