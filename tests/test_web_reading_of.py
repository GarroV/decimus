"""#855: поле температуры на вычитке — число, запятая, пусто; мусор — отказ."""

from __future__ import annotations

import pytest

from src.db.errors import ReviseError
from src.web.revision import reading_of


@pytest.mark.parametrize(
    ("raw", "ждём"),
    [("", None), ("  ", None), ("26", 26.0), ("4,5", 4.5), ("-18", -18.0), (" 7.0 ", 7.0)],
)
def test_разбор_показания(raw: str, ждём: float | None) -> None:
    assert reading_of(raw) == ждём


@pytest.mark.parametrize("raw", ["тепло", "26°", "nan", "inf", "-61", "501", "1e9"])
def test_мусор_отклоняется(raw: str) -> None:
    with pytest.raises(ReviseError) as отказ:
        reading_of(raw)
    assert отказ.value.code == "revise_reading"
