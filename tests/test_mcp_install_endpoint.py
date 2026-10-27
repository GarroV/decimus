"""Раздача установщика: публичный GET отдаёт скрипт, который человек запускает (#244, D112).

Форма взята у соседнего продукта (`swarm-brain`): бот присылает одну строку,
она качает скрипт отсюда и запускает его с токеном в окружении. Здесь
проверяется именно та дверь, в которую постучится `curl` человека, — а не
функция сборки: ошибиться можно ровно на стыке (путь, код ответа, тип), и
ровно этот стык человек увидит первым.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from src.mcp.config import Settings
from src.mcp.install import (
    BRIDGE_META_PATH,
    BRIDGE_SCRIPT_PATH,
    INSTALL_PATH,
    bridge_meta,
    bridge_script,
    install_script,
)
from src.mcp.server import build_server

ТОКЕН = "t" * 40
АРЕНДАТОР = "default"


@pytest.fixture
def сервер() -> Iterator[str]:
    """Сервер на случайном порту — как в `test_mcp_server.py`."""
    settings = Settings(tokens={ТОКЕН: АРЕНДАТОР}, tenants=(АРЕНДАТОР,), host="127.0.0.1", port=0)
    httpd: ThreadingHTTPServer = build_server(settings)
    поток = threading.Thread(target=httpd.serve_forever, daemon=True)
    поток.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        поток.join(timeout=5)


def _get(адрес: str) -> tuple[int, str, str]:
    try:
        with urllib.request.urlopen(адрес, timeout=10) as ответ:  # noqa: S310
            return ответ.status, ответ.read().decode("utf-8"), ответ.headers.get("Content-Type", "")
    except urllib.error.HTTPError as отказ:
        return отказ.code, отказ.read().decode("utf-8"), отказ.headers.get("Content-Type", "")


def test_установщик_отдаётся_без_токена(сервер: str) -> None:
    """Токен на скачивание не спрашивается — его негде взять до установки.

    Секретов в скрипте нет: адрес и токен человек подставляет сам, запуская
    его. Требовать токен здесь значило бы требовать его до того, как человек
    узнал, куда вписывать.
    """
    код, тело, тип = _get(f"{сервер}{INSTALL_PATH}")

    assert код == 200, "установщик не отдался без токена"
    assert "text/plain" in тип, f"тип ответа не текстовый: {тип!r}"
    assert тело.startswith("#!/bin/bash"), "отдан не скрипт"


def test_в_отданном_скрипте_есть_мост(сервер: str) -> None:
    """Скрипт без моста прошёл бы до конца и оставил настройку нерабочей.

    Мост подставляется из `tools/mcp_bridge.sh` — единственного источника, — и
    именно его отсутствие было бы молчаливым промахом: человек увидел бы
    «готово», а Claude сервера не нашёл бы.
    """
    _, тело, _ = _get(f"{сервер}{INSTALL_PATH}")

    assert "curl -sS --max-time 120" in тело, "тело моста в скрипт не подставилось"
    assert "\n@BRIDGE@\n" not in тело, "место для моста осталось незаполненным"


def test_отданный_скрипт_разбирается_bash(сервер: str) -> None:
    """`bash -n` на том, что реально уедет человеку.

    Проверяется ответ сервера, а не файл в репозитории: подстановка моста
    происходит при раздаче, и сломать скрипт может именно она.
    """
    _, тело, _ = _get(f"{сервер}{INSTALL_PATH}")

    разбор = subprocess.run(
        ["/bin/bash", "-n"], input=тело, text=True, capture_output=True, check=False
    )

    assert разбор.returncode == 0, f"скрипт не разбирается: {разбор.stderr}"


def test_секретов_в_скрипте_нет(сервер: str) -> None:
    """Публичная дверь не имеет права отдать ни одного токена сервера.

    Скрипт отдаётся кому угодно, и единственная причина, по которой это
    допустимо, — что в нём нечего взять.
    """
    _, тело, _ = _get(f"{сервер}{INSTALL_PATH}")

    assert ТОКЕН not in тело, "в установщик попал токен из настроек сервера"
    # Слово `Bearer` в скрипте есть и должно быть — внутри моста, в шаблоне
    # `printf`, где вместо токена стоит `%s`, и в строке, подставляющей
    # переменную. Проверяется не слово, а ЗНАЧЕНИЕ: за `Bearer` не должно
    # стоять ничего, кроме подстановки.
    for строка in тело.splitlines():
        # Комментарии пропускаются: в мосте объяснено, почему заголовок не
        # уходит в argv, и слово там стоит в тексте, а не в коде.
        if "Bearer" not in строка or строка.lstrip().startswith("#"):
            continue
        хвост = строка.split("Bearer", 1)[1].lstrip()
        assert хвост.startswith(("%s", "$", "\\$")), f"в скрипте готовый заголовок: {строка!r}"


def test_остальные_адреса_по_прежнему_405(сервер: str) -> None:
    """Просматриваемой поверхности у сервера не появилось.

    За дверью — история проверок партнёров, и раздача установщика не повод
    открывать всё остальное.
    """
    for путь in ("/", "/tools", "/setup/../"):
        код, _, _ = _get(f"{сервер}{путь}")
        assert код == 405, f"адрес {путь} ответил {код}, а не 405"


def test_сборщик_и_дверь_отдают_одно_и_то_же(сервер: str) -> None:
    """Между сборкой и раздачей не должно быть расхождения.

    Иначе тесты сборки останутся зелёными, а человек получит другое — самый
    неприятный сорт промаха, потому что ищут его не там.
    """
    _, тело, _ = _get(f"{сервер}{INSTALL_PATH}")

    assert тело == install_script()


@pytest.mark.skipif(
    shutil.which("plutil") is None,
    reason="нужен plutil (macOS): гоняется локально `make test`, как в Swarm (D669)",
)
def test_установщик_реально_отрабатывает_на_подставном_доме(сервер: str, tmp_path: Path) -> None:
    """Скрипт запускается по-настоящему, а не только разбирается.

    **Зачем отдельно от `bash -n`.** Разбор проверяет синтаксис и пропускает
    то, что ломается на исполнении. Живой промах 15.09.2026: имена переменных
    были написаны кириллицей, а bash допускает в них только `[A-Za-z0-9_]` —
    для него `TOKEN="..."` с русскими буквами не присваивание, а команда с
    таким именем. `bash -n` дал зелёный свет, установщик упал у человека на
    первой же строке `command not found`, и поймал это не тест, а владелец.

    Прогон идёт в подставном доме (`HOME`) и без `claude` в `PATH`: трогать
    настоящий файл настроек человека тест не имеет права, а ветку Claude Code
    здесь и не проверяют — проверяется, что скрипт доходит до конца и кладёт
    мост.
    """
    _, тело, _ = _get(f"{сервер}{INSTALL_PATH}")
    дом = tmp_path / "home"
    (дом / "Library" / "Application Support" / "Claude").mkdir(parents=True)
    чужой = дом / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    # У человека уже стоит прежняя установка (`dodo-audit`, мост в `~/.dodo-audit`).
    (дом / ".dodo-audit" / "bin").mkdir(parents=True)
    (дом / ".dodo-audit" / "bin" / "mcp_bridge.sh").write_text("старый мост")
    чужой.write_text(
        '{"mcpServers":{"сосед":{"command":"/bin/echo","args":["привет"]},'
        '"dodo-audit":{"command":"/bin/bash","args":["старый"]}}}'
    )

    прогон = subprocess.run(
        ["/bin/bash", "-s"],
        input=тело,
        text=True,
        capture_output=True,
        check=False,
        env={
            "HOME": str(дом),
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "DECIMUS_MCP_URL": "http://127.0.0.1:8265/",
            "DECIMUS_MCP_TOKEN": "t" * 40,
        },
    )

    assert прогон.returncode == 0, f"установщик упал: {прогон.stderr}"
    мост = дом / ".decimus" / "bin" / "mcp_bridge.sh"
    assert мост.exists(), "мост на машину не лёг"
    assert "curl" in мост.read_text(), "мост лёг пустым"
    настройки = json.loads(чужой.read_text())
    assert "сосед" in настройки["mcpServers"], "чужой сервер в настройках затёрт"
    assert "dodo-audit" not in настройки["mcpServers"], "прежний ключ сервера остался"
    assert not (дом / ".dodo-audit").exists(), "прежний каталог моста остался"
    наш = настройки["mcpServers"]["decimus"]
    assert наш["env"]["DECIMUS_MCP_URL"] == "http://127.0.0.1:8265/"
    assert наш["command"] == "/bin/bash", "запись сделана не в форме command+args"
    assert "url" not in наш and "type" not in наш, (
        "в настройки Desktop попала форма http — приложение молча сотрёт весь блок"
    )


def test_отпечаток_в_строке_запуска_совпадает_с_тем_что_отдаёт_сервер(сервер: str) -> None:
    """Бот сверяет скачанное с отпечатком; расхождение — установка не идёт (F-103)."""
    from src.bot.mcp_setup import installer_sha256, setup_command

    _, тело, _ = _get(сервер + INSTALL_PATH)
    отдано = hashlib.sha256(тело.encode("utf-8")).hexdigest()

    команда = setup_command(url=сервер, token=ТОКЕН)

    assert installer_sha256() == отдано, "отпечаток считается не от того, что отдаёт сервер"
    assert f'echo "{отдано}  $f" | shasum -a 256 -c -' in команда
    assert "| bash" not in команда, "вернулся слепой `curl | bash`"


def _get_with_token(адрес: str, токен: str | None) -> tuple[int, str]:
    запрос = urllib.request.Request(адрес)  # noqa: S310
    if токен is not None:
        запрос.add_header("Authorization", f"Bearer {токен}")
    try:
        with urllib.request.urlopen(запрос, timeout=10) as ответ:  # noqa: S310
            return ответ.status, ответ.read().decode("utf-8")
    except urllib.error.HTTPError as отказ:
        return отказ.code, отказ.read().decode("utf-8")


def test_мост_для_самообновления_без_токена_не_отдаётся(сервер: str) -> None:
    """В отличие от `/setup`, мост отдаётся только с токеном (D626)."""
    for путь in (BRIDGE_META_PATH, BRIDGE_SCRIPT_PATH):
        assert _get_with_token(f"{сервер}{путь}", None)[0] == 401, путь
        assert _get_with_token(f"{сервер}{путь}", "x" * 40)[0] == 401, путь


def test_мост_отдаёт_версию_и_сумму_того_файла_что_лежит_после_установки(сервер: str) -> None:
    """Сумма из `/bridge` обязана совпасть и с `/bridge/script`, и с мостом внутри `/setup`."""
    код, мета = _get_with_token(f"{сервер}{BRIDGE_META_PATH}", ТОКЕН)
    код_файла, файл = _get_with_token(f"{сервер}{BRIDGE_SCRIPT_PATH}", ТОКЕН)

    assert (код, код_файла) == (200, 200)
    данные = json.loads(мета)
    assert данные == bridge_meta()
    assert isinstance(данные["version"], int) and данные["version"] >= 1
    assert hashlib.sha256(файл.encode("utf-8")).hexdigest() == данные["sha256"]
    assert файл == bridge_script()
    assert f"\n{файл}" in install_script(), "установщик кладёт не тот мост, что отдаёт обновление"
