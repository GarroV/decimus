"""Бэкап тома состояния (`STATE_DIR`) в каталог бэкапа (задача #233).

Три вещи здесь стоят особняком:

1. **Связки доступа не теряются молча.** `access/roster.json` — единственный
   след того, какой юзернейм уже активировал приглашение (`src.bot.roster`).
   Его потеря отпирает освободившийся юзернейм постороннему, поэтому его
   попадание в архив проверяется отдельно от общего списка файлов, и об этом
   печатается отдельная строка.
2. **Пустой архив хуже отсутствия архива.** Пустой каталог состояния и
   архив, который не прошёл сверку после записи, не должны оставлять на диске
   ничего похожего на бэкап — оба случая здесь проверены как отказ БЕЗ файла.
3. **Ретеншн трогает только свои файлы.** Каталог бэкапа общий с другими
   проектами площадки; чужой старый файл рядом обязан пережить любой прогон.

Обычные случаи гоняются подпроцессом — так же, как инструмент запускают на
стенде (`python tools/state_backup.py`), включая код возврата и текст в
stderr. Ровно один случай (сверка архива) требует прямого вызова функции
модуля с подменой записи — это единственный способ подсунуть на диск мусор
вместо архива, не трогая настоящую логику записи.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tarfile
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ИНСТРУМЕНТ = ROOT / "tools" / "state_backup.py"

# Каталог `tools/` — в sys.path, а не корень репозитория: инструмент импортируется
# по голому имени `state_backup`, тем же именем, каким его видит mypy при прогоне
# `mypy tools/state_backup.py tests/test_state_backup.py` (в `tools/` нет
# `__init__.py`, и импорт с префиксом `tools.` завёл бы для одного файла два разных
# имени модуля и уронил бы прогон конфликтом «Source file found twice»).
sys.path.insert(0, str(ROOT / "tools"))
import state_backup  # noqa: E402 -- путь к tools/ выставляется выше

#: Путь связок доступа внутри тома состояния — тот же, что в `src/bot/roster.py`.
ROSTER_ПУТЬ = "access/roster.json"

СУТКИ = 86400


def _запустить(env_extra: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Инструмент подпроцессом — так же, как его будут звать на площадке."""
    env = {**os.environ, **env_extra}
    return subprocess.run(  # noqa: S603 — аргументы собираем сами, ввода извне нет
        [sys.executable, str(ИНСТРУМЕНТ)],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=30,
    )


@pytest.fixture
def состояние(tmp_path: Path) -> Path:
    """Каталог `STATE_DIR` для теста — существует и изначально пуст."""
    каталог = tmp_path / "state"
    каталог.mkdir()
    return каталог


@pytest.fixture
def бэкап(tmp_path: Path) -> Path:
    """Каталог `BACKUP_DIR` для теста — существует и изначально пуст."""
    каталог = tmp_path / "backup"
    каталог.mkdir()
    return каталог


def _положить_файл(путь: Path, содержимое: bytes = b"data") -> None:
    путь.parent.mkdir(parents=True, exist_ok=True)
    путь.write_bytes(содержимое)


def _единственный_архив(бэкап: Path) -> Path:
    архивы = sorted(бэкап.glob("decimus-state-*.tar.gz"))
    assert len(архивы) == 1, f"ожидался ровно один архив, нашлось: {архивы}"
    return архивы[0]


# --- содержимое архива --------------------------------------------------------


def test_архив_содержит_все_файлы_состояния_относительными_путями(
    состояние: Path, бэкап: Path
) -> None:
    _положить_файл(состояние / "chat_1" / "report.pdf")
    _положить_файл(состояние / "methodology" / "checklist.csv")

    r = _запустить({"STATE_DIR": str(состояние), "BACKUP_DIR": str(бэкап)})

    assert r.returncode == 0, r.stdout + r.stderr
    архив = _единственный_архив(бэкап)
    with tarfile.open(архив, "r:gz") as т:
        имена = т.getnames()
    assert set(имена) == {"chat_1/report.pdf", "methodology/checklist.csv"}
    for имя in имена:
        assert not имя.startswith("/"), имя
        assert состояние.name not in имя.split("/"), имя


def test_связки_доступа_попадают_в_архив_и_названы_отдельной_строкой(
    состояние: Path, бэкап: Path
) -> None:
    _положить_файл(состояние / ROSTER_ПУТЬ, b'{"version": 1, "entries": []}')

    r = _запустить({"STATE_DIR": str(состояние), "BACKUP_DIR": str(бэкап)})

    assert r.returncode == 0, r.stdout + r.stderr
    архив = _единственный_архив(бэкап)
    with tarfile.open(архив, "r:gz") as т:
        assert ROSTER_ПУТЬ in т.getnames()
    assert "roster.json" in r.stdout.lower()


def test_состояние_без_связок_собирает_архив_и_говорит_об_этом(
    состояние: Path, бэкап: Path
) -> None:
    _положить_файл(состояние / "chat_1" / "report.pdf")

    r = _запустить({"STATE_DIR": str(состояние), "BACKUP_DIR": str(бэкап)})

    assert r.returncode == 0, r.stdout + r.stderr
    assert "связок нет" in r.stdout.lower()
    _единственный_архив(бэкап)


# --- отказы --------------------------------------------------------------------


def test_пустой_каталог_состояния_это_отказ_без_архива(состояние: Path, бэкап: Path) -> None:
    r = _запустить({"STATE_DIR": str(состояние), "BACKUP_DIR": str(бэкап)})

    assert r.returncode == 1
    assert "[state-backup] не вышло: " in r.stderr
    assert list(бэкап.iterdir()) == []


def test_state_dir_не_задана_это_отказ_с_именем_переменной(бэкап: Path) -> None:
    r = _запустить({"STATE_DIR": "", "BACKUP_DIR": str(бэкап)})

    assert r.returncode == 1
    assert "STATE_DIR" in r.stderr


def test_state_dir_указывает_в_никуда_это_отказ(tmp_path: Path, бэкап: Path) -> None:
    r = _запустить({"STATE_DIR": str(tmp_path / "нет-такого"), "BACKUP_DIR": str(бэкап)})

    assert r.returncode == 1
    assert "STATE_DIR" in r.stderr


def test_backup_dir_не_задана_это_отказ_с_именем_переменной(состояние: Path) -> None:
    _положить_файл(состояние / "chat_1" / "report.pdf")

    r = _запустить({"STATE_DIR": str(состояние), "BACKUP_DIR": ""})

    assert r.returncode == 1
    assert "BACKUP_DIR" in r.stderr


def test_backup_dir_указывает_в_никуда_это_отказ(состояние: Path, tmp_path: Path) -> None:
    _положить_файл(состояние / "chat_1" / "report.pdf")

    r = _запустить({"STATE_DIR": str(состояние), "BACKUP_DIR": str(tmp_path / "нет-такого")})

    assert r.returncode == 1
    assert "BACKUP_DIR" in r.stderr


def test_keep_days_не_число_это_отказ(состояние: Path, бэкап: Path) -> None:
    _положить_файл(состояние / "chat_1" / "report.pdf")

    r = _запустить(
        {
            "STATE_DIR": str(состояние),
            "BACKUP_DIR": str(бэкап),
            "BACKUP_KEEP_DAYS": "не число",
        }
    )

    assert r.returncode == 1
    assert "BACKUP_KEEP_DAYS" in r.stderr


def test_keep_days_отрицательный_это_отказ(состояние: Path, бэкап: Path) -> None:
    _положить_файл(состояние / "chat_1" / "report.pdf")

    r = _запустить(
        {
            "STATE_DIR": str(состояние),
            "BACKUP_DIR": str(бэкап),
            "BACKUP_KEEP_DAYS": "-1",
        }
    )

    assert r.returncode == 1
    assert "BACKUP_KEEP_DAYS" in r.stderr


# --- ретеншн ---------------------------------------------------------------


def test_ретеншн_удаляет_только_свои_старые_архивы(состояние: Path, бэкап: Path) -> None:
    _положить_файл(состояние / "chat_1" / "report.pdf")

    чужой = бэкап / "srv-invoice-2026-08-01.dump"
    _положить_файл(чужой)
    свой_старый = бэкап / "decimus-state-20260801-030000.tar.gz"
    _положить_файл(свой_старый)
    старое_время = time.time() - 20 * СУТКИ
    os.utime(чужой, (старое_время, старое_время))
    os.utime(свой_старый, (старое_время, старое_время))

    r = _запустить(
        {"STATE_DIR": str(состояние), "BACKUP_DIR": str(бэкап), "BACKUP_KEEP_DAYS": "14"}
    )

    assert r.returncode == 0, r.stdout + r.stderr
    assert чужой.exists(), "ретеншн не имеет права трогать чужие файлы каталога бэкапа"
    assert not свой_старый.exists(), "свой файл старше срока обязан быть удалён"
    assert свой_старый.name in r.stdout


def test_молодой_и_только_что_созданный_архив_ретеншн_не_трогает(
    состояние: Path, бэкап: Path
) -> None:
    _положить_файл(состояние / "chat_1" / "report.pdf")
    молодой = бэкап / "decimus-state-20260915-030000.tar.gz"
    _положить_файл(молодой)

    r = _запустить(
        {"STATE_DIR": str(состояние), "BACKUP_DIR": str(бэкап), "BACKUP_KEEP_DAYS": "14"}
    )

    assert r.returncode == 0, r.stdout + r.stderr
    assert молодой.exists()
    архивы = sorted(бэкап.glob("decimus-state-*.tar.gz"))
    assert len(архивы) == 2, "молодой архив и только что записанный обязаны остаться оба"


def test_keep_days_ноль_ничего_не_удаляет(состояние: Path, бэкап: Path) -> None:
    _положить_файл(состояние / "chat_1" / "report.pdf")
    заведомо_старый = бэкап / "decimus-state-20200101-000000.tar.gz"
    _положить_файл(заведомо_старый)
    давно = time.time() - 3650 * СУТКИ
    os.utime(заведомо_старый, (давно, давно))

    r = _запустить({"STATE_DIR": str(состояние), "BACKUP_DIR": str(бэкап), "BACKUP_KEEP_DAYS": "0"})

    assert r.returncode == 0, r.stdout + r.stderr
    assert заведомо_старый.exists(), "BACKUP_KEEP_DAYS=0 значит «не удалять ничего»"


# --- аккуратность записи ----------------------------------------------------


def test_после_успешного_прогона_временных_файлов_не_остаётся(состояние: Path, бэкап: Path) -> None:
    _положить_файл(состояние / "chat_1" / "report.pdf")

    r = _запустить({"STATE_DIR": str(состояние), "BACKUP_DIR": str(бэкап)})

    assert r.returncode == 0, r.stdout + r.stderr
    скрытые = [p.name for p in бэкап.iterdir() if p.name.startswith(".")]
    assert скрытые == []


def test_сверка_ловит_испорченный_архив_и_удаляет_его(
    состояние: Path, бэкап: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Запись и сверка — разные функции модуля: подмена одной не трогает другую.

    Настоящая запись здесь не вызывается вовсе — на диск ложится готовый мусор,
    и единственное, что может его поймать, это перечитывание архива сверкой.
    """
    _положить_файл(состояние / "chat_1" / "report.pdf")

    def мусор(state_dir: Path, archive_path: Path) -> list[str]:
        del state_dir
        archive_path.write_bytes(b"not a tar.gz archive at all")
        return ["chat_1/report.pdf"]

    monkeypatch.setattr(state_backup, "_write_archive", мусор)

    env = {
        state_backup.STATE_DIR_VAR: str(состояние),
        state_backup.BACKUP_DIR_VAR: str(бэкап),
    }
    with pytest.raises(state_backup.BackupError):
        state_backup.run_backup(env)

    assert list(бэкап.iterdir()) == [], "битый архив обязан быть удалён, а не оставлен на диске"


def test_оборванная_запись_не_оставляет_временный_файл(tmp_path: Path) -> None:
    """Неудачный прогон не имеет права оставить мусор в каталоге бэкапа.

    Временный файл начинается с точки и не подходит под маску ретеншна: ни
    человек его не увидит, ни срок хранения не уберёт, а каждый следующий
    неудачный прогон добавит ещё один. Каталог бэкапа на площадке общий с
    чужими проектами.
    """
    состояние = tmp_path / "state"
    (состояние / "access").mkdir(parents=True)
    (состояние / "access" / "roster.json").write_text("{}", encoding="utf-8")
    бэкап = tmp_path / "backup"
    бэкап.mkdir()

    def падать(*_: object, **__: object) -> None:
        raise OSError("диск кончился посреди переименования")

    with pytest.MonkeyPatch.context() as заплатка:
        заплатка.setattr(state_backup.os, "replace", падать)
        with pytest.raises(OSError, match="диск кончился"):
            state_backup._write_archive(состояние, бэкап / "decimus-state-20260916-000000.tar.gz")

    assert list(бэкап.iterdir()) == [], f"в каталоге бэкапа остался мусор: {list(бэкап.iterdir())}"
