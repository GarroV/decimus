"""Валюта выручки Dodo IS по стране (D723): справочник, а не догадка по сумме.

Dodo IS отдаёт выручку «пиццерия × месяц» в местной валюте страны, а поле `currency` в
`dodois.unit_sales_month` у загруженных строк пусто (разбор ответа его не нашёл). Валюту
поэтому даёт страна пиццерии — закрытый перечень стран сети. Страны вне перечня — `None`:
вызывающий не показывает сумму без валюты, а не гадает.

Перечень — валюты на 2026 год: Болгария перешла на евро с 01.01.2026, а сбор продаж
начинается с июля 2026, так что болгарских строк в левах в базе нет. Сверено по Сербии:
ноябрь ≈ 2,93 млн RSD, как в `FinancialMetrics` публичного API Dodo.
"""

from __future__ import annotations

COUNTRY_CURRENCY: dict[str, str] = {
    "AM": "AMD",
    "AZ": "AZN",
    "BG": "EUR",
    "BY": "BYN",
    "CY": "EUR",
    "EE": "EUR",
    "ES": "EUR",
    "GE": "GEL",
    "HR": "EUR",
    "ID": "IDR",
    "KG": "KGS",
    "LT": "EUR",
    "ME": "EUR",
    "MN": "MNT",
    "MX": "MXN",
    "NG": "NGN",
    "PL": "PLN",
    "RO": "RON",
    "RS": "RSD",
    "SI": "EUR",
    "TJ": "TJS",
    "TR": "TRY",
}


def currency_of(country_code: str) -> str | None:
    """Трёхбуквенный код валюты страны или `None`, если страны нет в перечне."""
    return COUNTRY_CURRENCY.get(country_code.upper())
