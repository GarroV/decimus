"""Порча ядра «Начала работы» (D756, #1668): сломанная защита обязана уронить свой тест.

Запуск: `python tools/porcha_onboarding.py` из корня репозитория
(`make porcha-onboarding`). Каждый случай подменяет одну строку кода, гоняет ровно её
тест и возвращает файл на место. «НЕ ПРИМЕНИЛАСЬ» — код уехал, и порчу надо обновить:
молча зелёный прогон без подмены и есть та ложь, ради которой скрипт заведён. Базы тестам
не нужно.

Байткод не пишется (`PYTHONDONTWRITEBYTECODE=1`): порча того же размера в ту же секунду
подхватила бы кэш, и тест «поймал» бы исправный код.
"""

import os
import pathlib
import subprocess
import sys

T = "tests/test_web_onboarding.py::"
S = "src/web/onboarding.py"
cases = [
    # Шаг УК «не сделан» читается как «сделайте сами».
    (
        S,
        "    state = UNKNOWN if done is None else (DONE if done else WAITING)\n",
        "    state = UNKNOWN if done is None else (DONE if done else TODO)\n",
        T + "test_страны_пиццерии_и_чеклист_ждут_ук_а_не_партнёра",
    ),
    # Онбординг показан и управляющей компании.
    (
        S,
        "    if not код or side_of(код) != SIDE_PARTNER:\n",
        "    if not код:\n",
        T + "test_у_ук_шагов_нет_ни_у_одной_роли",
    ),
    # Непрочитанное показано шагом.
    (
        S,
        "    return tuple(step for step in steps if step.state != UNKNOWN)\n",
        "    return tuple(steps)\n",
        T + "test_непрочитанное_не_показывается_и_не_считается_сделанным",
    ),
    # Необязательный Claude держит карточку.
    (
        S,
        "    return any(step.required and step.state in (TODO, WAITING) for step in steps)\n",
        "    return any(step.state in (TODO, WAITING) for step in steps)\n",
        T + "test_клод_необязателен_карточку_не_держит",
    ),
    # Ожидание УК не держит карточку.
    (
        S,
        "    return any(step.required and step.state in (TODO, WAITING) for step in steps)\n",
        "    return any(step.required and step.state == TODO for step in steps)\n",
        T + "test_ожидание_ук_тоже_держит_карточку",
    ),
    # Пространство «готово», пока есть хоть одна строка.
    (
        S,
        "    return all(row.state == DONE for row in space_rows(space))\n",
        "    return any(row.state == DONE for row in space_rows(space))\n",
        T + "test_пространство_готово_только_когда_три_строки_есть",
    ),
    # Проверяющему показан шаг админа.
    (
        S,
        "    if role_may(role, код, _PEOPLE_ACTION):\n",
        "    if True:\n",
        T + "test_проверяющий_без_шагов_админа",
    ),
]

bad = 0
for path, old, new, test in cases:
    p = pathlib.Path(path)
    orig = p.read_text(encoding="utf-8")
    if old not in orig:
        print("НЕ ПРИМЕНИЛАСЬ:", path, repr(old[:60]))
        bad += 1
        continue
    p.write_text(orig.replace(old, new, 1), encoding="utf-8")
    try:
        r = subprocess.run(  # noqa: S603 — свой pytest и свои пути из списка выше
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-x",
                "-o",
                "addopts=",
                "-p",
                "no:cacheprovider",
                test,
            ],
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            check=False,
        )
    finally:
        p.write_text(orig, encoding="utf-8")
    ok = r.returncode != 0
    line = [row for row in r.stdout.splitlines() if row.startswith("E ")][:1]
    print(
        ("ЛОВИТ " if ok else "НЕ ЛОВИТ ") + test.split("::")[1],
        "|",
        (line[0][:110] if line else ""),
    )
    bad += 0 if ok else 1
sys.exit(1 if bad else 0)
