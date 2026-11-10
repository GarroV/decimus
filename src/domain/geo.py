"""Страны и города сети: названия для людей, страна города, местные написания.

Справочник точек хранит город кодом источника (`tbilisi`, `novisad`,
`starazagora`), а страну — кодом ISO 3166-1 (`GE`). Код остаётся ключом везде;
здесь — как его показать (`COUNTRIES`, `CITIES`), в какой стране город
(`CITY_COUNTRY`) и как ещё его пишут люди (`CITY_SPELLINGS`, сверх русского и
английского названий), чтобы написанное на любом языке сводилось к английскому
имени точки (D233, `unit_name.py`).

Общее для бота и админки, поэтому живёт в `domain`. Новая страна или город
сети — строка сюда.
"""

from __future__ import annotations

COUNTRIES: dict[str, dict[str, str]] = {
    "AE": {"ru": "ОАЭ", "en": "UAE"},
    "AM": {"ru": "Армения", "en": "Armenia"},
    "AZ": {"ru": "Азербайджан", "en": "Azerbaijan"},
    "BG": {"ru": "Болгария", "en": "Bulgaria"},
    "BY": {"ru": "Беларусь", "en": "Belarus"},
    "CY": {"ru": "Кипр", "en": "Cyprus"},
    "EE": {"ru": "Эстония", "en": "Estonia"},
    "ES": {"ru": "Испания", "en": "Spain"},
    "GE": {"ru": "Грузия", "en": "Georgia"},
    "HR": {"ru": "Хорватия", "en": "Croatia"},
    "ID": {"ru": "Индонезия", "en": "Indonesia"},
    "KG": {"ru": "Кыргызстан", "en": "Kyrgyzstan"},
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
    "UZ": {"ru": "Узбекистан", "en": "Uzbekistan"},
}

#: Страны, которых нет в сети Decimus, но которые встречаются в данных рейтингов: названия
#: нужны, чтобы показать их словом, а не кодом. Заводить пиццерии в них нельзя — `COUNTRIES`
#: этих стран не содержит.
EXTRA_COUNTRIES: dict[str, dict[str, str]] = {
    "CN": {"ru": "Китай", "en": "China"},
    "DE": {"ru": "Германия", "en": "Germany"},
    "GB": {"ru": "Великобритания", "en": "United Kingdom"},
    "IQ": {"ru": "Ирак", "en": "Iraq"},
    "MD": {"ru": "Молдова", "en": "Moldova"},
    "US": {"ru": "США", "en": "United States"},
    "VN": {"ru": "Вьетнам", "en": "Vietnam"},
    "KZ": {"ru": "Казахстан", "en": "Kazakhstan"},
    "MX": {"ru": "Мексика", "en": "Mexico"},
    "RU": {"ru": "Россия", "en": "Russia"},
}

#: Единый справочник названий стран для показа: сеть и страны из данных рейтингов. Новая
#: страна заводится здесь (в `COUNTRIES`, если в ней можно вести пиццерии, иначе в
#: `EXTRA_COUNTRIES`); `src/web/geo_names.py` и `src/ratings/countries.py` берут названия отсюда.
COUNTRY_NAMES: dict[str, dict[str, str]] = {**COUNTRIES, **EXTRA_COUNTRIES}

CITIES: dict[str, dict[str, str]] = {
    "abuja": {"ru": "Абуджа", "en": "Abuja", "tr": "Abuja"},
    "adana": {"ru": "Адана", "en": "Adana", "tr": "Adana"},
    "antalya": {"ru": "Анталья", "en": "Antalya", "tr": "Antalya"},
    "baku": {"ru": "Баку", "en": "Baku", "tr": "Bakü"},
    "bali": {"ru": "Бали", "en": "Bali", "tr": "Bali"},
    "bar": {"ru": "Бар", "en": "Bar", "tr": "Bar"},
    "batumi": {"ru": "Батуми", "en": "Batumi", "tr": "Batum"},
    "beograd": {"ru": "Белград", "en": "Belgrade", "tr": "Belgrad"},
    "bishkek": {"ru": "Бишкек", "en": "Bishkek", "tr": "Bişkek"},
    "brasov": {"ru": "Брашов", "en": "Brașov", "tr": "Braşov"},
    "bucuresti": {"ru": "Бухарест", "en": "Bucharest", "tr": "Bükreş"},
    "budva": {"ru": "Будва", "en": "Budva", "tr": "Budva"},
    "burgas": {"ru": "Бургас", "en": "Burgas", "tr": "Burgaz"},
    "doha": {"ru": "Доха", "en": "Doha", "tr": "Doha"},
    "dubai": {"ru": "Дубай", "en": "Dubai", "tr": "Dubai"},
    "dushanbe": {"ru": "Душанбе", "en": "Dushanbe", "tr": "Duşanbe"},
    "gyumri": {"ru": "Гюмри", "en": "Gyumri", "tr": "Gümrü"},
    "iasi": {"ru": "Яссы", "en": "Iași", "tr": "Yaş"},
    "izmir": {"ru": "Измир", "en": "İzmir", "tr": "İzmir"},
    "kaunas": {"ru": "Каунас", "en": "Kaunas", "tr": "Kaunas"},
    "klaipeda": {"ru": "Клайпеда", "en": "Klaipėda", "tr": "Klaipeda"},
    "koper": {"ru": "Копер", "en": "Koper", "tr": "Koper"},
    "lagos": {"ru": "Лагос", "en": "Lagos", "tr": "Lagos"},
    "limassol": {"ru": "Лимасол", "en": "Limassol", "tr": "Limasol"},
    "ljubljana": {"ru": "Любляна", "en": "Ljubljana", "tr": "Ljubljana"},
    "manisa": {"ru": "Маниса", "en": "Manisa", "tr": "Manisa"},
    "menemen": {"ru": "Менемен", "en": "Menemen", "tr": "Menemen"},
    "mersin": {"ru": "Мерсин", "en": "Mersin", "tr": "Mersin"},
    "nicosia": {"ru": "Никосия", "en": "Nicosia", "tr": "Lefkoşa"},
    "novisad": {"ru": "Нови-Сад", "en": "Novi Sad", "tr": "Novi Sad"},
    "parnu": {"ru": "Пярну", "en": "Pärnu", "tr": "Pärnu"},
    "pleven": {"ru": "Плевен", "en": "Pleven", "tr": "Plevne"},
    "plovdiv": {"ru": "Пловдив", "en": "Plovdiv", "tr": "Filibe"},
    "podgorica": {"ru": "Подгорица", "en": "Podgorica", "tr": "Podgorica"},
    "popeshtileordeni": {
        "ru": "Попешти-Леордени",
        "en": "Popești-Leordeni",
        "tr": "Popeşti-Leordeni",
    },
    "sabadell": {"ru": "Сабадель", "en": "Sabadell", "tr": "Sabadell"},
    "starazagora": {"ru": "Стара-Загора", "en": "Stara Zagora", "tr": "Eski Zağra"},
    "tallinn": {"ru": "Таллин", "en": "Tallinn", "tr": "Tallinn"},
    "tartu": {"ru": "Тарту", "en": "Tartu", "tr": "Tartu"},
    "tbilisi": {"ru": "Тбилиси", "en": "Tbilisi", "tr": "Tiflis"},
    "ulaanbaatar": {"ru": "Улан-Батор", "en": "Ulaanbaatar", "tr": "Ulan Batur"},
    "vilnius": {"ru": "Вильнюс", "en": "Vilnius", "tr": "Vilnius"},
    "warszawa": {"ru": "Варшава", "en": "Warsaw", "tr": "Varşova"},
    "yerevan": {"ru": "Ереван", "en": "Yerevan", "tr": "Erivan"},
    "zagreb": {"ru": "Загреб", "en": "Zagreb", "tr": "Zagreb"},
}

#: Страна города — код ISO 3166-1 alpha-2.
CITY_COUNTRY: dict[str, str] = {
    "abuja": "NG",
    "adana": "TR",
    "antalya": "TR",
    "baku": "AZ",
    "bali": "ID",
    "bar": "ME",
    "batumi": "GE",
    "beograd": "RS",
    "bishkek": "KG",
    "brasov": "RO",
    "bucuresti": "RO",
    "budva": "ME",
    "burgas": "BG",
    "doha": "QA",
    "dubai": "AE",
    "dushanbe": "TJ",
    "gyumri": "AM",
    "iasi": "RO",
    "izmir": "TR",
    "kaunas": "LT",
    "klaipeda": "LT",
    "koper": "SI",
    "lagos": "NG",
    "limassol": "CY",
    "ljubljana": "SI",
    "manisa": "TR",
    "menemen": "TR",
    "mersin": "TR",
    "nicosia": "CY",
    "novisad": "RS",
    "parnu": "EE",
    "pleven": "BG",
    "plovdiv": "BG",
    "podgorica": "ME",
    "popeshtileordeni": "RO",
    "sabadell": "ES",
    "starazagora": "BG",
    "tallinn": "EE",
    "tartu": "EE",
    "tbilisi": "GE",
    "ulaanbaatar": "MN",
    "vilnius": "LT",
    "warszawa": "PL",
    "yerevan": "AM",
    "zagreb": "HR",
}

#: Как ещё пишут город: местным алфавитом, с диакритикой, по-старому.
CITY_SPELLINGS: dict[str, tuple[str, ...]] = {
    "antalya": ("Анталия",),
    "baku": ("Bakı",),
    "batumi": ("ბათუმი",),
    "beograd": ("Beograd", "Београд"),
    "bishkek": ("Бишкек",),
    "brasov": ("Brașov", "Брашов"),
    "bucuresti": ("București", "Bucuresti"),
    "budva": ("Будва",),
    "burgas": ("Бургас",),
    "doha": ("الدوحة",),
    "dubai": ("دبي",),
    "dushanbe": ("Душанбе",),
    "gyumri": ("Գյումրի", "Gumri"),
    "iasi": ("Iași",),
    "izmir": ("İzmir",),
    "klaipeda": ("Klaipėda",),
    "koper": ("Capodistria",),
    "limassol": ("Лимассол", "Lemesos", "Λεμεσός"),
    "nicosia": ("Lefkosia", "Λευκωσία"),
    "novisad": ("Novi Sad", "Нови Сад", "Новый Сад"),
    "parnu": ("Pärnu", "Пярну"),
    "pleven": ("Плевен",),
    "plovdiv": ("Пловдив",),
    "podgorica": ("Подгорица",),
    "popeshtileordeni": ("Popești-Leordeni", "Popesti-Leordeni"),
    "starazagora": ("Стара Загора",),
    "tallinn": ("Таллинн",),
    "tbilisi": ("თბილისი", "Tiflis"),
    "ulaanbaatar": ("Улаанбаатар", "Ulan Bator", "Улан Батор"),
    "warszawa": ("Warszawa", "Warsaw"),
    "yerevan": ("Երևան", "Erevan", "Yerevan"),
}
