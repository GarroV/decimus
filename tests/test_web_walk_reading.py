"""Мини-апп: показание термометра в форме записи — поле, правка, пересчёт (#836).

Модель читает цифры с термометра неверно (6 °C как 26 °C). Карточка предложения
несёт показание, форма показывает его числовым полем «Температура, °C»;
исправленное число пересчитывает предложение тем же поиском, а в запись ложится
то, что подтвердил аудитор.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from test_web_walk import АУДИТОР
from test_web_walk_suggest import МОДЕЛЬ, Модель, _поиск, модель  # noqa: F401 -- фикстура
from test_web_walk_write import Клиент, _нарушение, клиент  # noqa: F401 -- фикстура

from src.bot import propose as ядро
from src.domain import get_state
from src.recognize.models import Suggestion


class Термометр(Модель):
    """Модель, которая читает с кадра 26 и сохраняет то, что ей сказали про исправление."""

    def __call__(self, note: str, photo: bytes | None, zone: str | None, **kw: Any) -> Suggestion:
        self.звали.append({"note": note, "photos": kw["photos"], "reading_c": kw.get("reading_c")})
        показание = kw.get("reading_c")
        кандидат = replace(МОДЕЛЬ, reading_c=26.0 if показание is None else показание)
        return Suggestion(candidates=(кандидат,), needs_human=False)


@pytest.fixture
def термометр(модель: Модель, monkeypatch: pytest.MonkeyPatch) -> Термометр:  # noqa: F811
    m = Термометр()
    monkeypatch.setattr(ядро, "classify", m)
    return m


def _запись(клиент: Клиент) -> Any:  # noqa: F811
    return get_state(АУДИТОР).findings[0]  # type: ignore[union-attr]


def test_карточка_несёт_показание_модели(клиент: Клиент, термометр: Термометр) -> None:  # noqa: F811
    ответ = _поиск(клиент, zone_hint="hot_kitchen", words="замер", photos=[клиент.ссылка()])

    assert ответ.get_json()["candidates"][0]["reading_c"] == 26.0


def test_исправленное_число_пересчитывает_предложение(
    клиент: Клиент,  # noqa: F811
    термометр: Термометр,
) -> None:
    ответ = _поиск(
        клиент, zone_hint="hot_kitchen", words="замер", photos=[клиент.ссылка()], reading_c=6
    )

    assert термометр.звали[0]["reading_c"] == 6.0, "исправление не дошло до модели"
    assert ответ.get_json()["candidates"][0]["reading_c"] == 6.0
    assert get_state(АУДИТОР).findings == [], "пересчёт записал без подтверждения"  # type: ignore[union-attr]


def test_исправление_обходит_быстрый_путь(клиент: Клиент, модель: Модель) -> None:  # noqa: F811
    """Быстрый путь по словам температуры не знает и ответил бы прежним."""
    ответ = _поиск(
        клиент, zone_hint="hot_kitchen", words="нагар", photos=[клиент.ссылка()], reading_c=6
    )

    assert ответ.get_json()["via"] == "model"


@pytest.mark.parametrize("мусор", ["шесть", True, 1000, -100])
def test_мусорное_число_в_поиске_отказ(клиент: Клиент, термометр: Термометр, мусор: Any) -> None:  # noqa: F811
    ответ = _поиск(
        клиент, zone_hint="hot_kitchen", words="замер", photos=[клиент.ссылка()], reading_c=мусор
    )

    assert ответ.status_code == 422 and термометр.звали == []


def test_показание_ложится_в_запись_и_видно_на_экране(клиент: Клиент) -> None:  # noqa: F811
    ref = клиент.ссылка()

    ответ = клиент.запись(**_нарушение(ref, reading_c=6.5))

    assert ответ.status_code == 200, ответ.get_json()
    assert _запись(клиент).reading_c == 6.5
    горячий = next(z for z in ответ.get_json()["zones"] if z["code"] == "hot_kitchen")
    assert горячий["recorded"][0]["reading_c"] == 6.5


def test_правка_меняет_одно_показание_без_других_полей(клиент: Клиент) -> None:  # noqa: F811
    клиент.запись(**_нарушение(клиент.ссылка(), reading_c=26, text="Температура выше нормы"))

    ответ = клиент.запись(op="edit", n=1, reading_c=6)

    assert ответ.status_code == 200, ответ.get_json()
    assert _запись(клиент).reading_c == 6.0
    assert _запись(клиент).text == "Температура выше нормы", "правка числа тронула формулировку"


def test_явный_null_снимает_показание(клиент: Клиент) -> None:  # noqa: F811
    клиент.запись(**_нарушение(клиент.ссылка(), reading_c=26))

    клиент.запись(op="edit", n=1, reading_c=None)

    assert _запись(клиент).reading_c is None


def test_правка_без_ключа_показание_не_трогает(клиент: Клиент) -> None:  # noqa: F811
    клиент.запись(**_нарушение(клиент.ссылка(), reading_c=6))

    клиент.запись(op="edit", n=1, comment="замечание")

    assert _запись(клиент).reading_c == 6.0


@pytest.mark.parametrize("мусор", ["шесть", True, 1000, -100])
def test_мусорное_число_в_записи_отказ(клиент: Клиент, мусор: Any) -> None:  # noqa: F811
    ответ = клиент.запись(**_нарушение(клиент.ссылка(), reading_c=мусор))

    assert ответ.status_code == 422
    assert get_state(АУДИТОР).findings == []  # type: ignore[union-attr]
