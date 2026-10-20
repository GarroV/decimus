"""F-127: CSV сверх потолка строк — отказ с причиной; ровно потолок читается."""

from __future__ import annotations

import pytest

from src.ratings import csvio
from src.ratings.csvio import read_table
from src.ratings.model import ERR_TOO_MANY_ROWS, RatingsFormatError


def _csv(rows: int) -> bytes:
    return ("a,b\n" + "".join(f"{i},x\n" for i in range(rows))).encode()


def test_rows_at_cap_are_read(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(csvio, "MAX_ROWS", 100)
    header, rows = read_table(_csv(100))
    assert header == ("a", "b")
    assert len(rows) == 100


def test_one_row_over_cap_is_refused_with_code_and_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(csvio, "MAX_ROWS", 100)
    with pytest.raises(RatingsFormatError, match="больше 100 строк") as exc:
        read_table(_csv(101))
    assert exc.value.code == ERR_TOO_MANY_ROWS
    assert exc.value.params == {"limit": "100"}


def test_blank_rows_do_not_count_toward_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(csvio, "MAX_ROWS", 3)
    data = b"a,b\n1,x\n,\n2,x\n,\n3,x\n"
    assert len(read_table(data)[1]) == 3
