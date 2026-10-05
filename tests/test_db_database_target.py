"""Подключения продукта ведут в одну базу — или отказ вслух (#487).

Стенд на одноразовой базе переопределил `DATABASE_URL` и `DATABASE_ADMIN_URL`,
а `DATABASE_RETRACTION_URL` пришёл из `.env`. Учётка заводилась через третье —
в общей тестовой базе; команда отвечала «заведена», вход давал 401. Здесь
проверяется, что такое расхождение теперь отказ ДО подключения, что отказ
называет каждую базу без пароля и что команда называет базу, куда пишет.

Базы не нужно: сверка идёт по строкам подключения, а подключение подменено
так, чтобы тест падал, если до него дошло при расхождении.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.db import web_access
from src.db.database_target import managing_target, same_database_or_refuse, target_of
from src.db.errors import AccessError, ConfigError

ПАРОЛЬ = "s3cret-не-печатать"
ПРИЛОЖЕНИЕ = f"postgresql://dodo_audit_app:{ПАРОЛЬ}@db.example:5432/stand_one"
НАКАТ = f"postgresql://postgres:{ПАРОЛЬ}@db.example:5432/stand_one"
ИСТОРИЯ_ТА_ЖЕ = f"postgresql://dodo_audit_admin:{ПАРОЛЬ}@db.example:5432/stand_one"
ИСТОРИЯ_ЧУЖАЯ = f"postgresql://dodo_audit_admin:{ПАРОЛЬ}@db.example:5432/shared_test"


def окружение(история: str) -> dict[str, str]:
    return {
        "DATABASE_URL": ПРИЛОЖЕНИЕ,
        "DATABASE_ADMIN_URL": НАКАТ,
        "DATABASE_RETRACTION_URL": история,
    }


def test_цель_подключения_без_пароля() -> None:
    цель = target_of(ИСТОРИЯ_ТА_ЖЕ, var="DATABASE_RETRACTION_URL")

    assert (цель.host, цель.port, цель.dbname, цель.user) == (
        "db.example",
        "5432",
        "stand_one",
        "dodo_audit_admin",
    )
    assert ПАРОЛЬ not in цель.label()


def test_одна_база_под_разными_ролями_проходит() -> None:
    цель = same_database_or_refuse(
        "DATABASE_RETRACTION_URL", ИСТОРИЯ_ТА_ЖЕ, окружение(ИСТОРИЯ_ТА_ЖЕ)
    )

    assert цель.dbname == "stand_one"


@pytest.mark.parametrize(
    "история",
    [
        ИСТОРИЯ_ЧУЖАЯ,
        f"postgresql://dodo_audit_admin:{ПАРОЛЬ}@db.example:5433/stand_one",
        f"postgresql://dodo_audit_admin:{ПАРОЛЬ}@other.example:5432/stand_one",
    ],
    ids=["другое имя базы", "другой порт", "другой хост"],
)
def test_расхождение_баз_отказ_с_названием_каждой_и_без_пароля(история: str) -> None:
    with pytest.raises(ConfigError) as отказ:
        same_database_or_refuse("DATABASE_RETRACTION_URL", история, окружение(история))

    текст = str(отказ.value)
    assert "разные базы" in текст
    for имя in ("DATABASE_URL", "DATABASE_ADMIN_URL", "DATABASE_RETRACTION_URL"):
        assert имя in текст, f"отказ не называет {имя}: {текст}"
    assert ПАРОЛЬ not in текст


def test_неразборная_строка_отказ_без_самой_строки() -> None:
    with pytest.raises(ConfigError) as отказ:
        target_of(f"host=db password={ПАРОЛЬ} =битая", var="DATABASE_ADMIN_URL")

    assert "DATABASE_ADMIN_URL" in str(отказ.value)
    assert ПАРОЛЬ not in str(отказ.value)


class _Подключился(Exception):
    """Подключение дошло до psycopg — с какой строкой, видно в `args`."""


def _подменить_подключение(monkeypatch: pytest.MonkeyPatch) -> None:
    def connect(dsn: str, *a: Any, **kw: Any) -> Any:
        raise _Подключился(dsn)

    monkeypatch.setattr(web_access.psycopg, "connect", connect)


def _выставить(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> None:
    for имя, значение in env.items():
        monkeypatch.setenv(имя, значение)


def test_учётки_при_расхождении_баз_не_подключаются(monkeypatch: pytest.MonkeyPatch) -> None:
    """Сценарий #487: запись учётки не уходит в чужую базу, а отказывает вслух."""
    _выставить(monkeypatch, окружение(ИСТОРИЯ_ЧУЖАЯ))
    _подменить_подключение(monkeypatch)

    with pytest.raises(AccessError) as отказ:
        web_access.list_accounts(tenant="demo")

    assert "разные базы" in str(отказ.value)
    assert "shared_test" in str(отказ.value)


def test_учётки_при_одной_базе_идут_ролью_истории(monkeypatch: pytest.MonkeyPatch) -> None:
    _выставить(monkeypatch, окружение(ИСТОРИЯ_ТА_ЖЕ))
    _подменить_подключение(monkeypatch)

    with pytest.raises(_Подключился) as дошло:
        web_access.list_accounts(tenant="demo")

    assert дошло.value.args[0] == ИСТОРИЯ_ТА_ЖЕ


def test_пространства_при_расхождении_баз_не_подключаются(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Подключение владельца схемы сверяется так же: накат в чужую базу — отказ."""
    env = окружение(ИСТОРИЯ_ТА_ЖЕ)
    env["DATABASE_ADMIN_URL"] = f"postgresql://postgres:{ПАРОЛЬ}@db.example:5432/shared_test"
    _выставить(monkeypatch, env)
    _подменить_подключение(monkeypatch)

    with pytest.raises(AccessError) as отказ, web_access._owned("перечислить пространства"):
        pass

    assert "разные базы" in str(отказ.value)


def test_команда_называет_базу_учёток(monkeypatch: pytest.MonkeyPatch) -> None:
    _выставить(monkeypatch, окружение(ИСТОРИЯ_ТА_ЖЕ))

    куда = managing_target()

    assert "stand_one" in куда
    assert "DATABASE_RETRACTION_URL" in куда
    assert ПАРОЛЬ not in куда


def test_web_user_при_расхождении_баз_отказывает_до_записи() -> None:
    """Живой запуск команды: расхождение баз — код 2 и названные базы, не «заведена»."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    корень = Path(__file__).resolve().parents[1]
    env = {
        "PATH": os.environ.get("PATH", ""),
        "WEB_USER_PASSWORD": "достаточно-длинный-пароль",
        **окружение(ИСТОРИЯ_ЧУЖАЯ),
    }
    итог = subprocess.run(  # noqa: S603 — свой интерпретатор и свой скрипт
        [
            sys.executable,
            str(корень / "tools" / "web_user.py"),
            "add",
            "letterbot",
            "--tenant",
            "demo",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert итог.returncode == 2, итог.stdout + итог.stderr
    assert "разные базы" in итог.stderr
    assert "shared_test" in итог.stderr
    assert "заведена" not in итог.stdout
    assert ПАРОЛЬ not in итог.stdout + итог.stderr
