"""Порча защит рейтингов: каждая сломанная защита обязана уронить свой тест.

Запуск: `.venv/bin/python tools/porcha_ratings.py` из корня репозитория, с
`DATABASE_URL` тестовой базы, как в `make test`. Каждый случай подменяет одну
строку кода, гоняет ровно её тест и возвращает файл на место. «НЕ ПРИМЕНИЛАСЬ» —
код уехал, и порчу надо обновить: молча зелёный прогон без подмены и есть та
ложь, ради которой скрипт заведён.

Байткод не пишется (`PYTHONDONTWRITEBYTECODE=1`, см. цель `test-honest` в
`Makefile`): порча того же размера в ту же секунду подхватила бы кэш, и тест
«поймал» бы исправный код.
"""

import os
import pathlib
import subprocess
import sys

cases = [
    (
        "src/domain/tenants.py",
        "    return canonical_tenant(tenant) == HQ_TENANT and role in RATINGS_MANAGER_ROLES\n",
        "    return role in RATINGS_MANAGER_ROLES\n",
        "tests/test_ratings_access.py",
    ),
    (
        "src/db/web_access.py",
        "    if role not in roles_for(tenant):\n",
        "    if False:\n",
        "tests/test_db_web_access_control.py::test_контроль_у_партнёра_отказ_кодом",
    ),
    (
        "src/web/app.py",
        "        if not _control_may_write(\n",
        "        if False and not _control_may_write(\n",
        "tests/test_web_users_access.py::test_контроль_вне_рейтингов_не_пишет",
    ),
    (
        "src/web/people.py",
        "    if role not in accounts.roles_for(tenant):",
        "    if role not in accounts.ROLES:",
        "tests/test_web_users_access.py::test_контроль_вне_уК_до_базы_не_доходит",
    ),
]

env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
failed = False
for path, original, broken, test in cases:
    file = pathlib.Path(path)
    text = file.read_text(encoding="utf-8")
    if original not in text:
        print(f"НЕ ПРИМЕНИЛАСЬ: {path}: {original.strip()!r}")
        failed = True
        continue
    file.write_text(text.replace(original, broken, 1), encoding="utf-8")
    try:
        run = subprocess.run(  # noqa: S603
            [".venv/bin/pytest", "-q", "--no-cov", "-p", "no:cacheprovider", test],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        file.write_text(text, encoding="utf-8")
    if run.returncode == 0:
        print(f"НЕ ПОЙМАНА: {path}: {original.strip()!r} -> {test}")
        failed = True
    else:
        print(f"поймана: {path} -> {test}")
sys.exit(1 if failed else 0)
