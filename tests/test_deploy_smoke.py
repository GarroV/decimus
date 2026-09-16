"""T255/T256: смоук раскатки — ловит ли он то, ради чего заведён.

Смоук на площадку руками не прогонишь: площадка боевая и на ней работает
владелец. Но проверяемое здесь свойство от площадки не зависит — это разбор
ответов, а не связь с машиной. Поэтому `ssh` подменяется заглушкой, которая
отдаёт заранее написанные ответы, и проверяется ровно одно: **на каких ответах
смоук обязан краснеть**.

Почему это стоит теста. Смоук — последний рубеж перед словом «раскатано», и
дважды за сутки сборка «проходила», а внутри было не то. Смоук, который зеленеет
на сломанном стенде, хуже отсутствующего: он выдаёт незнание за проверку.

Отдельно сторожится ловушка, которая молчала, пока сервис был один: строка
«unhealthy» содержит в себе «healthy», и поиск слова по всему выводу `docker
compose ps` объявлял бы больной контейнер здоровым.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
СМОУК = ROOT / "scripts" / "smoke.sh"

#: Ответы здорового стенда: два здоровых сервиса, живое звено до сервера,
#: общий вход площадки, отдающий его порт, и внешний адрес в строке настройки.
ЗДОРОВЫЙ = {
    "docker compose ps": "bot|Up 2 hours (healthy)\nmcp|Up 2 hours (healthy)\nlink|Up 2 hours",
    "git log -1": "abc1234",
    "printenv BUILD_SHA": "abc1234",
    "logs --tail=60 bot": "",
    "mcp_healthcheck.py": "rc=0",
    # Журнал сервиса, который не поднялся: смоук берёт из него причину. У
    # здорового стенда он не спрашивается вовсе.
    "logs --tail=20": "",
    # Ручных копий звена здоровый стенд не держит: с #216 звено — сервис
    # стенда, и копия рядом означает, что кто-то поднял его руками поверх.
    "name=dodo-mcp-proxy": "",
    "tailscale funnel status": "https://stand.example.ts.net:10000/\n|-- proxy http://127.0.0.1:8266",
    "printenv BOT_MCP_URL": "https://stand.example.ts.net:10000/",
}


@pytest.fixture
def площадка(tmp_path: Path) -> Path:
    """Каталог, из которого запускается смоук, и заглушка `ssh` рядом."""
    подмена = tmp_path / "bin"
    подмена.mkdir()
    ssh = подмена / "ssh"
    ssh.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "ответы = json.load(open(os.environ['SMOKE_STUB'], encoding='utf-8'))\n"
        "команда = ' '.join(sys.argv)\n"
        "for кусок, ответ in ответы.items():\n"
        "    if кусок in команда:\n"
        "        print(ответ)\n"
        "        break\n",
        encoding="utf-8",
    )
    ssh.chmod(ssh.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return tmp_path


def прогон(площадка: Path, **правки: str) -> subprocess.CompletedProcess[str]:
    """Смоук против заглушки. Правки перекрывают ответы здорового стенда."""
    ответы = {**ЗДОРОВЫЙ, **правки}
    сценарий = площадка / "stub.json"
    сценарий.write_text(json.dumps(ответы, ensure_ascii=False), encoding="utf-8")
    env = {
        **os.environ,
        "PATH": f"{площадка / 'bin'}:{os.environ['PATH']}",
        "SMOKE_STUB": str(сценарий),
        "DEPLOY_HOST": "заглушка",
        # Ждать здоровья здесь нечего: ответы заглушки не меняются со временем.
        "HEALTH_WAIT": "0",
    }
    return subprocess.run(  # noqa: S603 — аргументы собираем сами, ввода извне нет
        ["/bin/bash", str(СМОУК)],
        cwd=str(площадка),
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=120,
    )


def строка(вывод: str, начало: str) -> str:
    подходящие = [s for s in вывод.splitlines() if s.startswith(начало)]
    assert подходящие, f"в выводе нет строки про «{начало}»:\n{вывод}"
    return подходящие[0]


def test_здоровый_стенд_смоук_считает_зелёным(площадка: Path) -> None:
    r = прогон(площадка)
    assert "СМОУК ЗЕЛЁНЫЙ" in r.stdout, r.stdout


def test_нездоровый_сервер_не_сходит_за_здоровый(площадка: Path) -> None:
    """«unhealthy» содержит в себе «healthy» — ловушка, молчавшая с одним сервисом."""
    r = прогон(
        площадка,
        **{"docker compose ps": "bot|Up 2 hours (healthy)\nmcp|Up 3 minutes (unhealthy)"},
    )
    assert "СМОУК КРАСНЫЙ" in r.stdout, r.stdout
    assert "ПРОВАЛ" in строка(r.stdout, "контейнер MCP-сервера")


def test_сервера_нет_в_стенде_это_провал(площадка: Path) -> None:
    """Ровно сегодняшняя поломка: бот здоров, сервера нет вовсе."""
    r = прогон(площадка, **{"docker compose ps": "bot|Up 2 hours (healthy)"})
    assert "СМОУК КРАСНЫЙ" in r.stdout
    assert "нет в стенде" in строка(r.stdout, "контейнер MCP-сервера")


def test_сервер_не_отвечает_на_петле_это_провал(площадка: Path) -> None:
    r = прогон(площадка, **{"mcp_healthcheck.py": "[mcp-healthcheck] нет ответа\nrc=1"})
    assert "СМОУК КРАСНЫЙ" in r.stdout
    assert "ПРОВАЛ" in строка(r.stdout, "MCP-сервер отвечает на петле")


def test_звено_спрашивается_как_сервис_стенда_а_не_как_ручной_контейнер(
    площадка: Path,
) -> None:
    """С #216 звено — сервис `link`, и смоук обязан смотреть на него.

    Пока смоук искал ручной контейнер `dodo-mcp-proxy`, правильно собранный
    стенд краснел, а человек в ответ поднимал звено руками — то есть проверка
    возвращала ровно то, что задача #216 убирала.
    """
    r = прогон(
        площадка,
        **{
            # Сервиса `link` в стенде нет...
            "docker compose ps": "bot|Up 2 hours (healthy)\nmcp|Up 2 hours (healthy)",
            # ...а ручная копия рядом жива. Смотрящий на неё смоук скажет «OK».
            "name=dodo-mcp-proxy": "dodo-mcp-proxy2 Up 3 hours",
        },
    )
    assert "СМОУК КРАСНЫЙ" in r.stdout
    строчка = строка(r.stdout, "звено до сервера")
    assert "ПРОВАЛ" in строчка, строчка
    assert "link" in строчка, строчка
    assert "COMPOSE_PROFILES" in строчка, строчка


def test_звено_перезапускается_это_провал(площадка: Path) -> None:
    r = прогон(
        площадка,
        **{"docker compose ps": "bot|Up 2 hours (healthy)\nmcp|Up 2 hours (healthy)\nlink|Restarting (1)"},
    )
    assert "СМОУК КРАСНЫЙ" in r.stdout
    assert "ПРОВАЛ" in строка(r.stdout, "звено до сервера")


def test_осиротевшая_ручная_копия_звена_это_провал(площадка: Path) -> None:
    """Ручная копия рядом с сервисом дважды за неделю подменила диагноз.

    Она поднята с автоперезапуском, сидит в сетевом пространстве уже удалённого
    сервера и в списке выглядит рабочей. Пока она жива, ответ на вопрос «через
    что идёт доступ» неизвестен, и разбор поломки идёт не туда.
    """
    r = прогон(площадка, **{"name=dodo-mcp-proxy": "Up 3 hours"})
    assert "СМОУК КРАСНЫЙ" in r.stdout
    assert "ПРОВАЛ" in строка(r.stdout, "ручных копий звена нет")


def test_причина_отказа_сервера_названа_а_не_оставлена_в_логах(площадка: Path) -> None:
    """Контейнер, не поднявшийся из-за настройки, перезапускается вечно.

    `docker compose ps` говорит про него только «Restarting», хотя сам сервер
    назвал причину одной внятной строкой. Смоук обязан её показать — иначе
    человек идёт за ней в логи руками.
    """
    отказ = "[mcp] не поднялся: Ни одной двери: MCP_TOKENS пуста и DATABASE_URL не задана"
    r = прогон(
        площадка,
        **{
            "docker compose ps": "bot|Up 2 hours (healthy)\nmcp|Restarting (1)\nlink|Up 2 hours",
            "logs --tail=20": отказ,
        },
    )
    assert "СМОУК КРАСНЫЙ" in r.stdout
    assert "Ни одной двери" in строка(r.stdout, "контейнер MCP-сервера")


def test_общий_вход_не_отдаёт_сервер_это_провал(площадка: Path) -> None:
    """Funnel, не проксирующий наш порт, выглядит так же, как выключенный."""
    r = прогон(площадка, **{"tailscale funnel status": "no serve config"})
    assert "СМОУК КРАСНЫЙ" in r.stdout
    assert "ПРОВАЛ" in строка(r.stdout, "общий вход отдаёт сервер")


@pytest.mark.parametrize(
    ("адрес", "ожидаемое"),
    [
        ("http://127.0.0.1:8265/", "петля"),
        ("http://localhost:8265/", "петля"),
        ("", "заглушку"),
        ("http://audit-mcp.example.com/", "без TLS"),
    ],
)
def test_адрес_который_бот_раздаёт_проверяется_у_самого_бота(
    площадка: Path, адрес: str, ожидаемое: str
) -> None:
    """Петля в этой переменной — сегодняшняя поломка целиком, а не мелочь.

    Спрашивается она у самого бота, а не у файла рядом: печатает строку человеку
    он, и отвечает за неё только он.
    """
    r = прогон(площадка, **{"printenv BOT_MCP_URL": адрес})
    assert "СМОУК КРАСНЫЙ" in r.stdout, r.stdout
    assert ожидаемое in строка(r.stdout, "адрес в строке настройки")


def test_смоук_не_выдаёт_себя_за_проверку_снаружи(площадка: Path) -> None:
    """Зелёный смоук раскатки доступом с чужой машины не является."""
    r = прогон(площадка)
    assert "Доступ снаружи этим прогоном НЕ проверен" in r.stdout
    assert "mcp_outside.py" in r.stdout
