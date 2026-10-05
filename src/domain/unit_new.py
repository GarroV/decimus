"""Новая пиццерия справочника из веб-админки: что заводится и почему нет (#437).

Правила те же, что у бота на «Новая пиццерия?» (D233, D240), и стоят они
здесь, а не в обработчике экрана: поверхностей две, правило одно.

- Имя — «Город-N» по-английски (D232, D233): написанное как угодно сводится
  `canonical_unit`, без номера имени нет.
- Пиццерия заводится в стране экрана. Город, который словарь знает в ДРУГОЙ
  стране, — отказ: «Yerevan-4» в Сербии — это опечатка в выборе страны, а не
  новая точка.
- Незнакомый город не отказ (D240), но требует подтверждения: словарь его не
  знает, и «Zemun-2» из района вместо города иначе заводился бы молча (#440).

Дубль справочника здесь не проверяется: это знание базы, его держит
`src/db/directory.create_unit` в той же транзакции, что и запись.
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import ValidationError
from .geo import COUNTRIES
from .unit_name import UNIT_NAME_BYTE_LIMIT, UNIT_NAME_LIMIT, canonical_unit

#: Коды отказов. Это коды, а не тексты: экран переводит их своим словарём.
EMPTY = "empty"
TOO_LONG = "too_long"
NEED_NUMBER = "need_number"
OTHER_COUNTRY = "other_country"
UNKNOWN_COUNTRY = "unknown_country"


class NewUnitRefused(ValidationError):
    """Пиццерию с таким вводом завести нельзя. `code` — код отказа, `params` — подстановки."""

    def __init__(self, code: str, **params: str | int) -> None:
        super().__init__(code)
        self.code = code
        self.params = params


@dataclass(frozen=True)
class NewUnit:
    """Что ляжет в справочник."""

    name: str
    country: str
    #: Код города словаря; `None` — город словарю незнаком.
    city: str | None
    #: Как написал человек — станет синонимом, если отличается от имени.
    typed: str

    @property
    def known_city(self) -> bool:
        return self.city is not None

    @property
    def aliases(self) -> tuple[str, ...]:
        return (self.typed,) if self.typed and self.typed != self.name else ()


def plan_new_unit(typed: str, *, country: str) -> NewUnit:
    """Каноническая новая пиццерия страны `country` из написанного — или `NewUnitRefused`."""
    код_страны = (country or "").strip().upper()
    if код_страны not in COUNTRIES:
        raise NewUnitRefused(UNKNOWN_COUNTRY, country=код_страны)
    написано = " ".join((typed or "").split())
    if not написано:
        raise NewUnitRefused(EMPTY)
    if len(написано) > UNIT_NAME_LIMIT or len(написано.encode("utf-8")) > UNIT_NAME_BYTE_LIMIT:
        raise NewUnitRefused(TOO_LONG, limit=UNIT_NAME_LIMIT)
    имя = canonical_unit(написано)
    if имя is None:
        raise NewUnitRefused(NEED_NUMBER, typed=написано)
    if len(имя.name) > UNIT_NAME_LIMIT:
        # Латиница бывает длиннее написанного («Щ» → «shch»): предел имени
        # файла отчёта сверяется с тем, что ляжет в шапку (как в боте).
        raise NewUnitRefused(TOO_LONG, limit=UNIT_NAME_LIMIT)
    if имя.country is not None and имя.country != код_страны:
        raise NewUnitRefused(OTHER_COUNTRY, name=имя.name, country=имя.country)
    return NewUnit(name=имя.name, country=код_страны, city=имя.city, typed=написано)
