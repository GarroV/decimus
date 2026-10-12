"""Копии дизайн-системы `GarroV/forma` не правят на месте (#273, D136).

Первая строка копии — штамп forma с sha256 содержимого ниже неё. Правка здесь
не достанется двум другим продуктам линейки, поэтому прогон краснеет. Код —
из `dodo/docs/consumers.md` forma; сети и клона forma не нужно.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "src" / "web" / "static"
КОПИИ = ("dodo-ds.css", "decimus-domain.css")


def штамп_сходится(text: str) -> bool:
    head, _, body = text.partition("\n")
    stamp = re.search(r"sha256:([0-9a-f]{64})", head)
    return stamp is not None and hashlib.sha256(body.encode()).hexdigest() == stamp.group(1)


@pytest.mark.parametrize("имя", КОПИИ)
def test_копия_forma_не_правлена_на_месте(имя: str) -> None:
    text = (STATIC / имя).read_text(encoding="utf-8")
    assert штамп_сходится(text), (
        f"{имя}: файл правили на месте или нет штампа forma. Правка идёт в GarroV/forma "
        "и приезжает сюда раскаткой (`tools/spread.py`), см. src/web/static/SOURCE.md"
    )


def test_правка_копии_ловится() -> None:
    text = (STATIC / КОПИИ[0]).read_text(encoding="utf-8")
    испорчено = text + "\n.x { color: red; }\n"
    assert испорчено != text
    assert not штамп_сходится(испорчено)
