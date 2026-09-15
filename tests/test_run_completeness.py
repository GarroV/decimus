"""Сторож полноты прогона: неполный прогон не выдаёт себя за полный.

Механизм существовал для данных (`data/`, `examples/`), но база в него не
входила — и это стоило проекту 339 тестов, пропускавшихся молча, пока гейт
оставался зелёным (задача #207).

Проверяется прямым вызовом сводки, а не подпроцессом: отсутствие данных
вычисляется от корня репозитория (`conftest.NO_DATA`), то есть на машине, где
данные лежат, подпроцессом его не воспроизвести — такой тест был бы зелёным
всегда и не проверял бы ничего.
"""

from __future__ import annotations

from typing import Any

import conftest
import pytest


class _Репортёр:
    """То немногое от `TerminalReporter`, что зовёт сводка."""

    def __init__(self, пропущено: int = 0) -> None:
        self.stats: dict[str, list[object]] = {"skipped": [object()] * пропущено}
        self.строки: list[str] = []

    def write_sep(self, _знак: str, текст: str, **_: Any) -> None:
        self.строки.append(текст)

    def write_line(self, текст: str, **_: Any) -> None:
        self.строки.append(текст)

    @property
    def всё(self) -> str:
        return "\n".join(self.строки)


def test_без_базы_прогон_назван_неполным(monkeypatch: pytest.MonkeyPatch) -> None:
    """Нет строки подключения — это неполнота, а не «нечего проверять»."""
    monkeypatch.setattr(conftest, "NO_DATA", False)
    monkeypatch.setattr(conftest, "NO_EXAMPLES", False)
    monkeypatch.setattr(conftest, "NO_DB", True)
    monkeypatch.delenv(conftest.REQUIRE_DATA_VAR, raising=False)
    репортёр = _Репортёр(пропущено=339)

    conftest.pytest_terminal_summary(репортёр)  # type: ignore[arg-type]

    assert "ПРОГОН НЕПОЛНЫЙ" in репортёр.всё
    assert "базы" in репортёр.всё.lower()
    assert "339" in репортёр.всё


def test_объявленный_полным_прогон_без_базы_краснеет(monkeypatch: pytest.MonkeyPatch) -> None:
    """Объявлен полным, а база не поднята — прогон обязан упасть.

    Это та половина, которой не хватало: без неё «N passed» на машине без базы
    выглядит ровно так же, как полный прогон.
    """
    monkeypatch.setattr(conftest, "NO_DATA", False)
    monkeypatch.setattr(conftest, "NO_EXAMPLES", False)
    monkeypatch.setattr(conftest, "NO_DB", True)
    monkeypatch.setenv(conftest.REQUIRE_DATA_VAR, "1")

    with pytest.raises(Exception) as отказ:
        conftest.pytest_terminal_summary(_Репортёр(пропущено=339))  # type: ignore[arg-type]

    assert "полным" in str(отказ.value)


def test_полный_прогон_молчит(monkeypatch: pytest.MonkeyPatch) -> None:
    """Всё на месте — сводка не говорит ничего и ничего не роняет.

    Проверка обязана падать на испорченном входе И молчать на исправном: без
    второй половины сторож, который кричит всегда, ничем не лучше молчащего.
    """
    monkeypatch.setattr(conftest, "NO_DATA", False)
    monkeypatch.setattr(conftest, "NO_EXAMPLES", False)
    monkeypatch.setattr(conftest, "NO_DB", False)
    monkeypatch.setenv(conftest.REQUIRE_DATA_VAR, "1")
    репортёр = _Репортёр()

    conftest.pytest_terminal_summary(репортёр)  # type: ignore[arg-type]

    assert репортёр.всё == ""
