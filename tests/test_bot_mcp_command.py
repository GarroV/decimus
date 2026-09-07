"""Строка настройки Claude Desktop: без Node, своим мостом и штатным `plutil` (#222, D103).

Прежняя редакция присылала человеку `npx -y mcp-remote` — то есть требовала
Node на его машине и заводила постоянный процесс-посредник, который на
отозванном токене молча ретраился (в логе площадки — больше 170 строк `401` за
час). Владелец это отверг прямо: мост stdio↔HTTP у продукта уже есть
(`tools/mcp_bridge.sh`, D055), и он лучше — токен уходит файлом конфигурации
curl с правами 600, а не в `argv`, где его видно через `ps`.

Здесь проверяется ровно то, что из этого следует, и проверяется ЗАПУСКОМ:
команда правит файл настроек живого человека, где стоят его собственные
серверы, и «судя по коду, должна работать» стоит здесь чужих рабочих
инструментов. Дом подставной — настоящий файл настроек не трогается ни при
каком исходе.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from src.bot.mcp_setup import BRIDGE_PATH, SERVER_NAME, bridge_body, desktop_command

ТОКЕН = "tok_" + "x" * 28
АДРЕС = "https://audit.example.invalid/"

#: Правдоподобный файл настроек: чужие серверы и настройка, к серверам
#: отношения не имеющая. Всё это обязано пережить нашу команду.
ЧУЖИЕ_НАСТРОЙКИ = {
    "globalShortcut": "Alt+Space",
    "mcpServers": {
        "filesystem": {"command": "npx", "args": ["-y", "server-filesystem", "/somewhere"]},
        "sqlite": {"command": "uvx", "args": ["mcp-server-sqlite"]},
        "neighbour": {"command": "/bin/bash", "args": ["/Users/x/.swarm-brain/bin/bridge.sh"]},
    },
}

ЕСТЬ_PLUTIL = pytest.mark.skipif(
    shutil.which("plutil") is None, reason="не macOS: команда настройки написана под plutil"
)


def _настройки(дом: Path) -> Path:
    return дом / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"


def _команда(url: str = АДРЕС, token: str = ТОКЕН) -> str:
    return desktop_command(url=url, token=token, done="готово")


def _выполнить(команда: str, дом: Path) -> subprocess.CompletedProcess[str]:
    """Выполнить присланную строку так, как её выполнит человек: целиком, в оболочке."""
    return subprocess.run(  # noqa: S602 — строка наша же, и проверяется именно она
        команда,
        shell=True,
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "HOME": str(дом)},
    )


# --- то, ради чего задача заведена -------------------------------------------


def test_в_команде_нет_ни_node_ни_посредника() -> None:
    """Суть #222: Node из подключения уходит совсем, вместе с `mcp-remote`.

    Проверяется текстом, а не только исходом запуска: команда может сработать и
    при этом прописать в настройки `npx` — тогда Node останется нужен уже не
    для установки, а навсегда, при каждом запуске приложения.
    """
    команда = _команда()

    for слово in ("node", "npx", "mcp-remote"):
        assert слово not in команда, f"в команде осталось «{слово}» — Node не ушёл"


def test_тело_моста_в_команде_то_же_что_в_репозитории() -> None:
    """Мост один, источник у него один — файл в репозитории.

    Копия текста моста внутри каталога сообщений разъехалась бы с оригиналом на
    первой же правке, и разъехалась бы молча: у человека на машине работала бы
    вчерашняя редакция, а чинили бы сегодняшнюю.
    """
    значимые = [
        строка
        for строка in Path("tools/mcp_bridge.sh").read_text(encoding="utf-8").splitlines()
        if строка.strip() and not строка.lstrip().startswith("#")
    ]
    тело = bridge_body()

    assert тело.startswith("#!/bin/bash"), "у моста на машине человека нет строки запуска"
    for строка in значимые:
        assert строка in тело, f"строка моста потерялась при сборке команды: {строка!r}"
    assert тело in _команда(), "в команду уехало не то тело моста"


@ЕСТЬ_PLUTIL
def test_команда_не_сносит_уже_настроенные_серверы(tmp_path: Path) -> None:
    """Главное требование: у человека уже есть свои серверы, и они остаются."""
    файл = _настройки(tmp_path)
    файл.parent.mkdir(parents=True)
    файл.write_text(json.dumps(ЧУЖИЕ_НАСТРОЙКИ), encoding="utf-8")

    исход = _выполнить(_команда(), tmp_path)

    assert исход.returncode == 0, f"команда не выполнилась: {исход.stderr}"
    стало = json.loads(файл.read_text(encoding="utf-8"))
    assert set(стало["mcpServers"]) == {*ЧУЖИЕ_НАСТРОЙКИ["mcpServers"], SERVER_NAME}
    for имя, было in ЧУЖИЕ_НАСТРОЙКИ["mcpServers"].items():
        assert стало["mcpServers"][имя] == было, f"сервер «{имя}» изменился"
    assert стало["globalShortcut"] == "Alt+Space", "посторонняя настройка не пережила команду"


@ЕСТЬ_PLUTIL
def test_запись_поднимает_наш_мост_а_токен_лежит_в_окружении(tmp_path: Path) -> None:
    """Так же, как у соседнего продукта: `/bin/bash`, путь моста, адрес и токен в `env`.

    Токен именно в `env`, а не в `args`: аргументы процесса видны на машине
    всем через `ps`, и мост потому и заведён, чтобы секрет туда не попадал.
    """
    исход = _выполнить(_команда(), tmp_path)

    assert исход.returncode == 0, f"команда не выполнилась: {исход.stderr}"
    наш = json.loads(_настройки(tmp_path).read_text(encoding="utf-8"))["mcpServers"][SERVER_NAME]
    assert наш["command"] == "/bin/bash"
    assert наш["args"] == [str(tmp_path / BRIDGE_PATH)]
    assert наш["env"] == {"DODO_MCP_URL": АДРЕС, "DODO_MCP_TOKEN": ТОКЕН}
    assert ТОКЕН not in json.dumps(наш["args"]), "токен уехал в argv, где его видно через ps"


@ЕСТЬ_PLUTIL
def test_мост_кладётся_исполняемым_и_только_для_владельца(tmp_path: Path) -> None:
    """Не исполняемый мост приложение не запустит, а читаемый чужими — отдаёт путь к секрету."""
    исход = _выполнить(_команда(), tmp_path)

    assert исход.returncode == 0, f"команда не выполнилась: {исход.stderr}"
    мост = tmp_path / BRIDGE_PATH
    assert мост.exists(), "мост не установлен"
    assert мост.stat().st_mode & 0o777 == 0o700, "права моста не только для владельца"


@ЕСТЬ_PLUTIL
def test_команда_заводит_файл_если_его_нет(tmp_path: Path) -> None:
    """Человек мог не настраивать ни одного сервера до нас — тогда файла нет вовсе."""
    исход = _выполнить(_команда(), tmp_path)

    assert исход.returncode == 0, f"команда не выполнилась: {исход.stderr}"
    стало = json.loads(_настройки(tmp_path).read_text(encoding="utf-8"))
    assert list(стало["mcpServers"]) == [SERVER_NAME]


@ЕСТЬ_PLUTIL
def test_непонятый_файл_настроек_команда_не_трогает(tmp_path: Path) -> None:
    """Файл есть, но не разбирается — значит, писать в него нельзя.

    «Не разобрали, начнём с пустого» означало бы тихо заменить конфиг человека
    на наш единственный сервер. Пусть лучше человек увидит отказ.
    """
    файл = _настройки(tmp_path)
    файл.parent.mkdir(parents=True)
    файл.write_text("{ это не json", encoding="utf-8")

    исход = _выполнить(_команда(), tmp_path)

    assert исход.returncode != 0, "команда смолчала о непонятом файле настроек"
    assert файл.read_text(encoding="utf-8") == "{ это не json", "испорченный файл переписан"
    assert not list(файл.parent.glob("*dodo-tmp*")), "после отказа остался обрывок записи"


@ЕСТЬ_PLUTIL
def test_повторная_настройка_не_плодит_записей(tmp_path: Path) -> None:
    """Пункт вызывают второй раз (токен выпускается заново) — запись обязана замениться."""
    _выполнить(_команда(), tmp_path)

    исход = _выполнить(_команда(token="tok_" + "y" * 28), tmp_path)

    assert исход.returncode == 0, f"команда не выполнилась: {исход.stderr}"
    стало = json.loads(_настройки(tmp_path).read_text(encoding="utf-8"))
    assert list(стало["mcpServers"]) == [SERVER_NAME], "вторая настройка добавила ещё одну запись"
    assert стало["mcpServers"][SERVER_NAME]["env"]["DODO_MCP_TOKEN"] == "tok_" + "y" * 28


@ЕСТЬ_PLUTIL
def test_файл_настроек_остаётся_читаемым_человеком(tmp_path: Path) -> None:
    """`plutil` по умолчанию пишет двоичный plist — человек свой конфиг больше не прочтёт."""
    _выполнить(_команда(), tmp_path)

    текст = _настройки(tmp_path).read_text(encoding="utf-8")

    assert текст.lstrip().startswith("{"), "конфиг перестал быть текстовым JSON"
    assert "\n" in текст, "конфиг записан одной строкой — читать его глазами нечем"


# --- установленный мост проверяется работой, а не чтением ---------------------


class _Заглушка(BaseHTTPRequestHandler):
    """MCP-сервер на две строки: возвращает то, что пришло, и заголовок запроса."""

    def do_POST(self) -> None:
        тело = self.rfile.read(int(self.headers["Content-Length"]))
        ответ = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": json.loads(тело).get("id"),
                "result": {"auth": self.headers.get("Authorization", "")},
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(ответ)))
        self.end_headers()
        self.wfile.write(ответ)

    def log_message(self, *_: object) -> None:
        """Молча: сервер живёт внутри теста, его журнал только мешает выводу."""


@ЕСТЬ_PLUTIL
def test_установленный_мост_доносит_запрос_и_приносит_ответ(tmp_path: Path) -> None:
    """Смоук всей связки: то, что установлено командой, действительно работает.

    Именно этого не хватало прежней редакции — она проверялась чтением текста,
    а «подключение есть» человек узнавал уже на своей машине.
    """
    assert _выполнить(_команда(), tmp_path).returncode == 0
    сервер = HTTPServer(("127.0.0.1", 0), _Заглушка)
    threading.Thread(target=сервер.serve_forever, daemon=True).start()
    адрес = f"http://127.0.0.1:{сервер.server_port}/"
    try:
        мост = subprocess.run(  # noqa: S603 — запускается наш же установленный файл
            [str(tmp_path / BRIDGE_PATH)],
            input='{"jsonrpc":"2.0","id":1,"method":"tools/list"}\n'
            '{"jsonrpc":"2.0","method":"notifications/initialized"}\n',
            capture_output=True,
            text=True,
            timeout=30,
            env={**os.environ, "DODO_MCP_URL": адрес, "DODO_MCP_TOKEN": ТОКЕН},
        )
    finally:
        сервер.shutdown()

    строки = [строка for строка in мост.stdout.splitlines() if строка.strip()]
    assert len(строки) == 1, f"на уведомление без id мост ответил, а не должен: {строки!r}"
    ответ = json.loads(строки[0])
    assert ответ["id"] == 1
    assert ответ["result"]["auth"] == f"Bearer {ТОКЕН}", "токен не доехал до сервера"
