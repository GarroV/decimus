"""#1246: `deploy/demo/update.sh` и `reset.sh` отказываются работать вне дерева демо.

Запущенные из боевого дерева, они собрали бы демо с боевым `.env` (боевые пароли,
ключи хранилища, токен бота), а `reset.sh` перед этим сносил бы демо-стенд. Скрипты
гоняются в копии каталога с подставными `git`, `docker` и `flock`: отказ должен
случиться ДО первой команды, и подставные ничего не должны успеть вызвать.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

КОРЕНЬ = Path(__file__).resolve().parent.parent
СКРИПТЫ = ("update.sh", "reset.sh")


def _дерево(каталог: Path, env: str | None) -> tuple[Path, Path]:
    """Копия `deploy/demo` с подставными командами; вернуть (дерево, журнал вызовов)."""
    дерево = каталог / "tree"
    (дерево / "deploy" / "demo").mkdir(parents=True)
    (дерево / "scripts").mkdir()
    for имя in ("update.sh", "reset.sh", "guard.sh"):
        shutil.copy(КОРЕНЬ / "deploy" / "demo" / имя, дерево / "deploy" / "demo" / имя)
    (дерево / "scripts" / "verify-source.sh").write_text("#!/bin/sh\n")
    (дерево / "scripts" / "verify-source.sh").chmod(0o755)
    if env is not None:
        (дерево / ".env").write_text(env)
    журнал = каталог / "calls.log"
    журнал.write_text("")
    бин = каталог / "bin"
    бин.mkdir()
    for команда in ("git", "docker", "flock"):
        подмена = бин / команда
        подмена.write_text(f'#!/bin/sh\necho "{команда} $*" >> "{журнал}"\n')
        подмена.chmod(0o755)
    return дерево, журнал


def _запуск(дерево: Path, скрипт: str, каталог: Path) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "PATH": f"{каталог / 'bin'}:{os.environ['PATH']}",
        "DECIMUS_DEMO_TREE": "/srv/нет-такого-демо",
    }
    return subprocess.run(  # noqa: S603 — скрипты наши, оболочка нужна им самим
        ["bash", str(дерево / "deploy" / "demo" / скрипт)],  # noqa: S607
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


@pytest.mark.parametrize("скрипт", СКРИПТЫ)
@pytest.mark.parametrize(
    "env",
    [None, "AUDIT_DATA_DIR=/srv/decimus/data\nS3_BUCKET=prod\n", "WEB_SECRET_KEY=x\n"],
    ids=["без .env", "боевая методика", "нет признака демо"],
)
def test_вне_дерева_демо_скрипт_отказывает_до_первой_команды(
    tmp_path: Path, скрипт: str, env: str | None
) -> None:
    дерево, журнал = _дерево(tmp_path, env)

    r = _запуск(дерево, скрипт, tmp_path)

    assert r.returncode != 0, f"скрипт отработал в чужом дереве: {r.stdout}{r.stderr}"
    assert "не дерево демо" in r.stderr, r.stderr
    assert журнал.read_text() == "", f"до отказа успели вызвать: {журнал.read_text()}"


@pytest.mark.parametrize("скрипт", СКРИПТЫ)
@pytest.mark.parametrize(
    "env", ["AUDIT_DATA_DIR=./demo/data\n", "X=1\nAUDIT_DATA_DIR=/srv/d/demo/data\n"]
)
def test_в_дереве_демо_с_признаком_скрипт_работает(tmp_path: Path, скрипт: str, env: str) -> None:
    дерево, журнал = _дерево(tmp_path, env)

    r = _запуск(дерево, скрипт, tmp_path)

    assert "не дерево демо" not in r.stderr, r.stderr
    assert журнал.read_text() != "", "скрипт отказал в дереве демо — демо перестанет обновляться"


def test_дерево_демо_по_адресу_пускается_без_признака(tmp_path: Path) -> None:
    дерево, журнал = _дерево(tmp_path, "WEB_SECRET_KEY=x\n")
    env = {
        **os.environ,
        "PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}",
        "DECIMUS_DEMO_TREE": str(дерево.resolve()),
    }

    r = subprocess.run(  # noqa: S603
        ["bash", str(дерево / "deploy" / "demo" / "reset.sh")],  # noqa: S607
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert "не дерево демо" not in r.stderr, r.stderr
    assert журнал.read_text() != ""
