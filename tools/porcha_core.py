"""Порча ядра (#268): испорченный расчёт обязан уронить прогон.

Запуск: `make porcha` (или `.venv/bin/python tools/porcha_core.py` из корня).
Зелёный прогон не доказывает, что проверки умеют падать: тест может не мочь
упасть, гейт может смотреть в чужую копию или в кэш байткода. Доказательство
одно — испортить ядро и увидеть красноту. Здесь по одной порче на каждый кусок
ядра (`docs/furca/constitution.md`, принцип 2 и правила формулировки):
вычет в движке, ставка в `data/scoring.json`, множитель повтора, правило
формулировки.

Требования, каждое — урок этого проекта:

* восстановление **копией файла**, а не `git checkout`: `data/` вне git, а в
  рабочем дереве бывают чужие незакоммиченные правки;
* после восстановления md5 сверяется с исходным — не вернулось, значит провал;
* `PYTHONDONTWRITEBYTECODE=1`: порча, живущая меньше секунды, иначе подберёт
  старый байткод, и «тест поймал» окажется ложью (12 промахов из 12);
* «НЕ ПРИМЕНИЛАСЬ» — провал, а не пропуск: код уехал, и порчу надо обновить;
* тест, пропущенный без данных (`requires_data`), — тоже провал: пропуск
  ничего не проверил.
"""

from __future__ import annotations

import hashlib
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

T = "tests/"

#: (файл, исходная строка, испорченная строка, тест, который обязан покраснеть).
CASES: tuple[tuple[str, str, str, str], ...] = (
    # Движок: цена нарушения обнулена — все вычеты D1/D2 пропадают.
    (
        "engine/audit.py",
        "                cost = float(pen.get(lvl, 0))\n",
        "                cost = float(pen.get(lvl, 0)) * 0\n",
        T + "test_engine_regress.py",
    ),
    # Ставка вычета в данных: D1 дешевле — боевой якорь 97.5 уезжает.
    (
        "data/scoring.json",
        '    "D1": 0.5,\n',
        '    "D1": 0.4,\n',
        T + "test_engine_regress.py",
    ),
    # Повтор нарушения (D191) перестаёт стоить дороже.
    (
        "engine/audit.py",
        '                if f.get("repeat"):\n',
        "                if False:\n",
        T + "test_engine_repeat_doubles.py",
    ),
    # Правило формулировки 2: масштаб за кадром больше не помечается.
    (
        "src/recognize/rules_check.py",
        '    re.compile(r"на протяжении (нескольких|\\d+) (метр|м\\b)", re.IGNORECASE),\n',
        '    re.compile(r"(?!)", re.IGNORECASE),\n',
        T + "test_recognize_rules_check.py::test_масштаб_за_кадром_из_боевого_отчёта",
    ),
)


def _md5(path: pathlib.Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()  # noqa: S324 — сверка копии, не защита


def _run(test: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 — свой pytest и свои пути из списка выше
        [".venv/bin/pytest", "-q", "-x", "-rs", "-o", "addopts=", "-p", "no:cacheprovider", test],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        check=False,
    )


def _one(path: str, old: str, new: str, test: str, spare: pathlib.Path) -> bool:
    """Одна порча: применить, прогнать, вернуть копией, сверить md5. `True` — поймана."""
    p = pathlib.Path(path)
    if not p.is_file():
        print("НЕТ ФАЙЛА:", path, "— порча не проверялась")
        return False
    orig = p.read_text(encoding="utf-8")
    if old not in orig:
        print("НЕ ПРИМЕНИЛАСЬ:", path, repr(old.strip()[:70]))
        return False
    до = _md5(p)
    копия = spare / (p.name + ".orig")
    shutil.copy2(p, копия)
    p.write_text(orig.replace(old, new, 1), encoding="utf-8")
    try:
        r = _run(test)
    finally:
        shutil.copy2(копия, p)
    if _md5(p) != до:
        print("НЕ ВОССТАНОВЛЕН:", path, "— md5 не совпал с исходным, проверьте файл руками")
        return False
    if " skipped" in r.stdout and " passed" not in r.stdout and " failed" not in r.stdout:
        print("ПРОПУЩЕН:", test, "— без данных тест ничего не проверил")
        return False
    поймана = r.returncode != 0
    строка = next((row for row in r.stdout.splitlines() if row.startswith("E ")), "")
    print(("ЛОВИТ " if поймана else "НЕ ЛОВИТ ") + f"{path} -> {test}", "|", строка[:110])
    return поймана


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        spare = pathlib.Path(tmp)
        итоги = [_one(*case, spare) for case in CASES]
    провалов = итоги.count(False)
    print(f"порча ядра: поймано {итоги.count(True)} из {len(итоги)}")
    return 1 if провалов else 0


if __name__ == "__main__":
    sys.exit(main())
