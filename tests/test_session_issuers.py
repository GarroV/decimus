"""Кто выдаёт полную веб-сессию (D463): список закрыт, новый путь входа обязан попасть сюда.

Полная сессия человеку со вторым способом выдаётся только после второй ступени, и держит это
сама `open_session` (запрос отказывает без `second_step=True`, см. `test_db_second_factor`).
Этот тест — вторая половина: он перечисляет ВСЕ места, где сессию открывают, и падает на
любом новом. Автор нового пути входа (бот, мини-апп, SSO) увидит его здесь и обязан решить,
как путь проходит вторую ступень, а не обнаружить дыру ревью-ботом.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: (файл, число вызовов `open_session`) → как этот путь проходит вторую ступень.
ВЫДАЮЩИЕ = {
    # Пароль и Google: `second_step.first_step_suffices(метод)` (у Google ступени нет, D485)
    # решает, помечать ли сессию; сперва `second_step.begin` (есть способ — полувход, сессии нет),
    # открытие без `second_step=True` возможно, только если способа нет (иначе отказ базы).
    # Третий вызов — обновление сессии при подтверждении входа: несёт признак прежней
    # сессии, а сессия без второй ступени у человека со способом получит отказ базы.
    "src/web/auth.py": 3,
    # Единственное место, где `second_step=True`: после ключа, кода или резервного кода.
    # Второй вызов — `security_prove_code`: верный код приложения в сессии открывает новую
    # сессию с `second_step=True` (доказательство для снятия способов, D485).
    "src/web/second_step.py": 2,
    # Вход ключом с формы входа (D485): подпись ключа сама и есть доказательство, сессия
    # открывается с `second_step=True`.
    "src/web/passkey_login.py": 1,
}

#: Файлы, где допустима сама вставка в `web_sessions` (одна точка).
ВСТАВКА = {"src/db/web_access.py"}


def _исходники() -> list[Path]:
    return [p for base in ("src", "tools") for p in (ROOT / base).rglob("*.py")]


def _вызовы(path: Path) -> int:
    дерево = ast.parse(path.read_text(encoding="utf-8"))
    return sum(
        1
        for узел in ast.walk(дерево)
        if isinstance(узел, ast.Call)
        and (
            (isinstance(узел.func, ast.Name) and узел.func.id == "open_session")
            or (isinstance(узел.func, ast.Attribute) and узел.func.attr == "open_session")
        )
    )


def test_полную_сессию_открывают_только_названные_места() -> None:
    найдено = {str(p.relative_to(ROOT)): n for p in _исходники() if (n := _вызовы(p))}
    найдено.pop("src/db/web_access.py", None)  # само определение и его внутренние ссылки

    assert найдено == ВЫДАЮЩИЕ, (
        "изменился круг мест, где открывается веб-сессия: каждое новое обязано пройти вторую "
        "ступень (`open_session` без `second_step=True` откажет человеку со способом) — "
        f"опишите путь в этом тесте. Найдено: {найдено}"
    )


def test_только_одна_вставка_в_web_sessions() -> None:
    вставки = {
        str(p.relative_to(ROOT))
        for p in _исходники()
        if "insert into web_sessions" in p.read_text(encoding="utf-8").lower()
    }

    assert вставки == ВСТАВКА, f"сессии создаются мимо open_session: {вставки}"


def test_второй_ступенью_сессию_помечают_только_второй_шаг_и_вход_ключом() -> None:
    помечают = {
        str(p.relative_to(ROOT))
        for p in (ROOT / "src" / "web").rglob("*.py")
        if "second_step=True" in p.read_text(encoding="utf-8")
    }

    assert помечают == {"src/web/second_step.py", "src/web/passkey_login.py"}, помечают
