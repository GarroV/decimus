"""Названия стран и городов для людей — по коду из справочника точек.

Справочник сети хранит город кодом источника (`tbilisi`, `novisad`,
`starazagora`), а страну — кодом ISO 3166-1 (`GE`). Код остаётся ключом везде —
в адресе, в отборе, в базе; здесь только то, как его показать (конституция,
принцип 5: связь кодом, перевод — словом).

Незнакомый код не ломает экран: город показывается кодом с заглавной буквы,
страна — кодом. Появится новая страна сети — дописать строку сюда.
"""

from __future__ import annotations

COUNTRIES: dict[str, dict[str, str]] = {
    "AE": {"ru": "ОАЭ", "en": "UAE"},
    "AM": {"ru": "Армения", "en": "Armenia"},
    "AZ": {"ru": "Азербайджан", "en": "Azerbaijan"},
    "BG": {"ru": "Болгария", "en": "Bulgaria"},
    "CY": {"ru": "Кипр", "en": "Cyprus"},
    "EE": {"ru": "Эстония", "en": "Estonia"},
    "ES": {"ru": "Испания", "en": "Spain"},
    "GE": {"ru": "Грузия", "en": "Georgia"},
    "HR": {"ru": "Хорватия", "en": "Croatia"},
    "ID": {"ru": "Индонезия", "en": "Indonesia"},
    "KG": {"ru": "Киргизия", "en": "Kyrgyzstan"},
    "LT": {"ru": "Литва", "en": "Lithuania"},
    "ME": {"ru": "Черногория", "en": "Montenegro"},
    "MN": {"ru": "Монголия", "en": "Mongolia"},
    "NG": {"ru": "Нигерия", "en": "Nigeria"},
    "PL": {"ru": "Польша", "en": "Poland"},
    "QA": {"ru": "Катар", "en": "Qatar"},
    "RO": {"ru": "Румыния", "en": "Romania"},
    "RS": {"ru": "Сербия", "en": "Serbia"},
    "SI": {"ru": "Словения", "en": "Slovenia"},
    "TJ": {"ru": "Таджикистан", "en": "Tajikistan"},
    "TR": {"ru": "Турция", "en": "Türkiye"},
}

CITIES: dict[str, dict[str, str]] = {
    "abuja": {"ru": "Абуджа", "en": "Abuja"},
    "adana": {"ru": "Адана", "en": "Adana"},
    "antalya": {"ru": "Анталья", "en": "Antalya"},
    "baku": {"ru": "Баку", "en": "Baku"},
    "bali": {"ru": "Бали", "en": "Bali"},
    "bar": {"ru": "Бар", "en": "Bar"},
    "batumi": {"ru": "Батуми", "en": "Batumi"},
    "beograd": {"ru": "Белград", "en": "Belgrade"},
    "bishkek": {"ru": "Бишкек", "en": "Bishkek"},
    "brasov": {"ru": "Брашов", "en": "Brașov"},
    "bucuresti": {"ru": "Бухарест", "en": "Bucharest"},
    "budva": {"ru": "Будва", "en": "Budva"},
    "burgas": {"ru": "Бургас", "en": "Burgas"},
    "doha": {"ru": "Доха", "en": "Doha"},
    "dubai": {"ru": "Дубай", "en": "Dubai"},
    "dushanbe": {"ru": "Душанбе", "en": "Dushanbe"},
    "gyumri": {"ru": "Гюмри", "en": "Gyumri"},
    "iasi": {"ru": "Яссы", "en": "Iași"},
    "izmir": {"ru": "Измир", "en": "İzmir"},
    "kaunas": {"ru": "Каунас", "en": "Kaunas"},
    "klaipeda": {"ru": "Клайпеда", "en": "Klaipėda"},
    "koper": {"ru": "Копер", "en": "Koper"},
    "lagos": {"ru": "Лагос", "en": "Lagos"},
    "limassol": {"ru": "Лимасол", "en": "Limassol"},
    "ljubljana": {"ru": "Любляна", "en": "Ljubljana"},
    "manisa": {"ru": "Маниса", "en": "Manisa"},
    "menemen": {"ru": "Менемен", "en": "Menemen"},
    "mersin": {"ru": "Мерсин", "en": "Mersin"},
    "nicosia": {"ru": "Никосия", "en": "Nicosia"},
    "novisad": {"ru": "Нови-Сад", "en": "Novi Sad"},
    "parnu": {"ru": "Пярну", "en": "Pärnu"},
    "pleven": {"ru": "Плевен", "en": "Pleven"},
    "plovdiv": {"ru": "Пловдив", "en": "Plovdiv"},
    "podgorica": {"ru": "Подгорица", "en": "Podgorica"},
    "popeshtileordeni": {"ru": "Попешти-Леордени", "en": "Popești-Leordeni"},
    "sabadell": {"ru": "Сабадель", "en": "Sabadell"},
    "starazagora": {"ru": "Стара-Загора", "en": "Stara Zagora"},
    "tallinn": {"ru": "Таллин", "en": "Tallinn"},
    "tartu": {"ru": "Тарту", "en": "Tartu"},
    "tbilisi": {"ru": "Тбилиси", "en": "Tbilisi"},
    "ulaanbaatar": {"ru": "Улан-Батор", "en": "Ulaanbaatar"},
    "vilnius": {"ru": "Вильнюс", "en": "Vilnius"},
    "warszawa": {"ru": "Варшава", "en": "Warsaw"},
    "yerevan": {"ru": "Ереван", "en": "Yerevan"},
    "zagreb": {"ru": "Загреб", "en": "Zagreb"},
}


def _title(table: dict[str, dict[str, str]], code: str, lang: str) -> str | None:
    names = table.get(code)
    if names is None:
        return None
    return names.get(lang) or names.get("en")


def country_title(code: str | None, lang: str) -> str:
    """Страна словом; незнакомый код — кодом, пустой — пустой строкой."""
    if not code:
        return ""
    return _title(COUNTRIES, code.upper(), lang) or code.upper()


def city_title(code: str | None, lang: str) -> str:
    """Город словом; незнакомый код — кодом с заглавной, пустой — пустой строкой."""
    if not code:
        return ""
    return _title(CITIES, code.casefold(), lang) or code[:1].upper() + code[1:]
