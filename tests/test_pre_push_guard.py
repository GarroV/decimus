"""#189: сторож пуша (`tools/pre-push-guard.sh`) не имел автоматических тестов —
единственная проверка была ручной, и именно во время такой проверки 05.09.2026
`git reset --hard HEAD~1` откатил тестовый коммит вместе с незакоммиченной
правкой рядом (D093, Q040, T232).

Тесты здесь работают во временных git-репозиториях (`tmp_path`), реальный
репозиторий не трогают — ручной откат коммитов больше не нужен никому.

Заодно ловят найденную здесь же дыру: для **первого** пуша ветки (`remote_sha`
из одних нулей) сторож сравнивал коммит с рабочим деревом (`git diff
"$local_sha"`), а не с пустым состоянием. В момент пуша рабочее дерево обычно
совпадает с самим коммитом — diff получался пустым, и весь первый пуш новой
ветки проходил вообще без проверки на секреты.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
GUARD = HERE.parent / "tools" / "pre-push-guard.sh"
ZERO = "0" * 40


@dataclass(frozen=True)
class Run:
    code: int
    out: str
    err: str

    @property
    def text(self) -> str:
        return self.out + self.err


def git(*args: str, cwd: Path) -> None:
    subprocess.run(  # noqa: S603, S607 — аргументы собираем сами, тестовая песочница
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    )


def commit_sha(cwd: Path) -> str:
    p = subprocess.run(  # noqa: S603, S607
        ["git", "rev-parse", "HEAD"], cwd=cwd, check=True, capture_output=True, text=True
    )
    return p.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Пустой git-репозиторий с настроенной личностью для коммитов."""
    d = tmp_path / "repo"
    d.mkdir()
    git("init", "-q", "-b", "main", cwd=d)
    git("config", "user.email", "test@example.com", cwd=d)
    git("config", "user.name", "Test", cwd=d)
    return d


@pytest.fixture
def terms_file(tmp_path: Path) -> Callable[..., Path]:
    """Список запрещённых значений вне репозитория — как в бою (D094)."""

    def make(*values: str) -> Path:
        p = tmp_path / "secret-terms.txt"
        p.write_text("\n".join(values) + "\n", encoding="utf-8")
        return p

    return make


@pytest.fixture
def guard(repo: Path, terms_file: Callable[..., Path]) -> Callable[..., Run]:
    """Вызов сторожа: строка пуша на stdin, список терминов через окружение."""

    def call(local_sha: str, remote_sha: str, *values: str) -> Run:
        env = dict(os.environ)
        env["GIT_SECRET_TERMS"] = str(terms_file(*values)) if values else "/nonexistent"
        p = subprocess.run(  # noqa: S603
            ["bash", str(GUARD)],
            cwd=repo,
            input=f"refs/heads/main {local_sha} refs/heads/main {remote_sha}\n",
            env=env,
            capture_output=True,
            text=True,
        )
        return Run(p.returncode, p.stdout, p.stderr)

    return call


def test_список_терминов_отсутствует_проверка_не_делалась(
    repo: Path, guard: Callable[..., Run]
) -> None:
    (repo / "f.txt").write_text("что угодно\n", encoding="utf-8")
    git("add", "f.txt", cwd=repo)
    git("commit", "-q", "-m", "init", cwd=repo)
    r = guard(commit_sha(repo), ZERO)
    assert r.code == 0, r.text
    assert "проверка НЕ делалась" in r.text


def test_обычный_пуш_ловит_запрещённое_значение(repo: Path, guard: Callable[..., Run]) -> None:
    """Ветка на remote уже есть: диапазон remote_sha..local_sha — путь, который и раньше работал."""
    (repo / "f.txt").write_text("безобидно\n", encoding="utf-8")
    git("add", "f.txt", cwd=repo)
    git("commit", "-q", "-m", "base", cwd=repo)
    base = commit_sha(repo)

    (repo / "f.txt").write_text("SECRETVALUE123 тут\n", encoding="utf-8")
    git("commit", "-q", "-am", "leak", cwd=repo)
    head = commit_sha(repo)

    r = guard(head, base, "SECRETVALUE123")
    assert r.code != 0, "запрещённое значение в обычном пуше не остановлено"
    assert "запрещённое значение" in r.text


def test_обычный_пуш_без_запрещённого_проходит(repo: Path, guard: Callable[..., Run]) -> None:
    (repo / "f.txt").write_text("безобидно\n", encoding="utf-8")
    git("add", "f.txt", cwd=repo)
    git("commit", "-q", "-m", "base", cwd=repo)
    base = commit_sha(repo)

    (repo / "f.txt").write_text("тоже безобидно\n", encoding="utf-8")
    git("commit", "-q", "-am", "still fine", cwd=repo)
    head = commit_sha(repo)

    r = guard(head, base, "SECRETVALUE123")
    assert r.code == 0, r.text


def test_первый_пуш_новой_ветки_ловит_запрещённое_значение(
    repo: Path, guard: Callable[..., Run]
) -> None:
    """Найденная дыра: `remote_sha` из нулей — ветки на remote ещё нет.

    До фикса сторож сравнивал коммит с рабочим деревом (`git diff "$local_sha"`),
    которое в момент пуша совпадает с самим коммитом, — diff пустой, секрет из
    самого первого коммита новой ветки не виден вообще.
    """
    (repo / "f.txt").write_text("SECRETVALUE123 с самого первого коммита\n", encoding="utf-8")
    git("add", "f.txt", cwd=repo)
    git("commit", "-q", "-m", "первый коммит новой ветки", cwd=repo)
    head = commit_sha(repo)

    r = guard(head, ZERO, "SECRETVALUE123")
    assert r.code != 0, "первый пуш новой ветки прошёл без проверки на секреты"
    assert "запрещённое значение" in r.text


def test_первый_пуш_новой_ветки_без_запрещённого_проходит(
    repo: Path, guard: Callable[..., Run]
) -> None:
    (repo / "f.txt").write_text("безобидное содержимое\n", encoding="utf-8")
    git("add", "f.txt", cwd=repo)
    git("commit", "-q", "-m", "первый коммит новой ветки", cwd=repo)
    head = commit_sha(repo)

    r = guard(head, ZERO, "SECRETVALUE123")
    assert r.code == 0, r.text
