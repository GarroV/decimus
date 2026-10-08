"""Синтетические выгрузки рейтингов для тестов: заголовки живые, данные выдуманы.

Живые файлы в репозиторий не кладутся (конституция: названия точек партнёров и
их оценки чувствительны). Здесь — те же колонки, BOM и CRLF, что у Dodo IS, и
вымышленные пиццерии `Testville-N` с id `aa…01`.
"""

from __future__ import annotations

import csv
import io

U1 = "aa000000000000000000000000000001"
U2 = "aa000000000000000000000000000002"
U_RU = "aa0000000000000000000000000000ff"
C1 = "cc000000000000000000000000000001"
C2 = "cc000000000000000000000000000002"
C3 = "cc000000000000000000000000000003"
C_RU = "cc0000000000000000000000000000ff"
P_RKO = "dd000000000000000000000000000001"
P_RS = "dd000000000000000000000000000002"


def kb(unit: str, kind: int, checkup: str, period: str) -> str:
    return (
        f"https://dodopizza.info/rating#/{unit}/{kind}?selectedRemarkType=0"
        f"&openRemarkDetails=1&checkupId={checkup}&ratingPeriodId={period}"
    )


def back(checkup: str) -> str:
    return f"https://control.dodois.io/backoffice/checkups/{checkup}"


def to_csv(header: list[str], rows: list[list[str]], *, delimiter: str = ",") -> bytes:
    out = io.StringIO(newline="")
    writer = csv.writer(out, delimiter=delimiter, lineterminator="\r\n")
    writer.writerow(header)
    writer.writerows(rows)
    return b"\xef\xbb\xbf" + out.getvalue().encode("utf-8")


RKO_VIOLATIONS_HEADER = [
    "Страна",
    "Пиццерия",
    "Пользователь",
    "Выявленные нарушения",
    "Ответы клиента",
    "Другие проблемы",
    "Номер заказа",
    "Дата заказа",
    "Название пиццы",
    "Размер и тип теста",
    "Link",
    "KnowledgeBaseLink",
    "CreatedAtUtc",
    "CheckupType",
]


def rko_violations(**override: str) -> bytes:
    rows = [
        [
            "Serbia",
            "Testville-1",
            "Тест Тестов",
            "Ингредиенты на бортах; Пицца деформирована (ML); Ингредиенты на бортах",
            "Да; ok",
            "",
            "3",
            "2026-10-06 10:14:19",
            "Pepperoni",
            "25 см, традиционное",
            back(C1),
            kb(U1, 1, C1, P_RKO),
            "2026-10-06 10:24:19",
            "Доставка",
        ],
        [
            "Беларусь",
            "Testville-2",
            "Тест Тестов",
            "",
            "Нет",
            "Пиццу привезли холодной",
            "7",
            "2026-10-07 12:00:00",
            "Margherita",
            "30 см, тонкое",
            back(C2),
            kb(U2, 1, C2, P_RKO),
            "2026-10-07 12:10:00",
            "Ресторан",
        ],
        [
            "Россия",
            "Testgrad-1",
            "Тест Тестов",
            "Белый борт",
            "",
            "",
            "1",
            "2026-10-07 13:00:00",
            "Pepperoni",
            "25 см, традиционное",
            back(C_RU),
            kb(U_RU, 1, C_RU, P_RKO),
            "2026-10-07 13:10:00",
            "Доставка",
        ],
    ]
    if override:
        rows[0] = [override.get(h, v) for h, v in zip(RKO_VIOLATIONS_HEADER, rows[0], strict=True)]
    return to_csv(RKO_VIOLATIONS_HEADER, rows)


RKO_EVALUATIONS_HEADER = [
    "CheckupId",
    "Ссылка на проверку",
    "Manager",
    "Дата и время начала оценки (UTC)",
    "Дата и время оценки (UTC)",
    "Результат оценки",
    "Конвеер",
    "Страна",
    "Дата",
]


def rko_evaluations() -> bytes:
    return to_csv(
        RKO_EVALUATIONS_HEADER,
        [
            [
                C1,
                back(C1),
                "Тест Тестов",
                "2026-10-06 15:50:44",
                "2026-10-06 15:51:51",
                "Принято",
                "Клиенты - Доставка - IMF",
                "Serbia",
                "2026-10-06 02:09:48",
            ],
            [
                C3,
                back(C3),
                "",
                "",
                "2026-10-06 16:00:00",
                "Отклонено",
                "Клиенты - Ресторан - IMF",
                "Кыргызстан",
                "2026-10-06 03:00:00",
            ],
            [
                C_RU,
                back(C_RU),
                "",
                "",
                "2026-10-06 16:00:00",
                "Принято",
                "Клиенты - Доставка - РФ",
                "Россия",
                "2026-10-06 03:00:00",
            ],
        ],
    )


RS_CHECKUPS_HEADER = [
    "Пиццерия",
    "Ссылка на отчет в беке",
    "Ссылка на отчет в БЗ",
    "Фактическая дата + время",
    "Менеджер",
    "Дата и время принятия отчёта (UTC)",
    "Конвейер",
    "Страна",
    "Баллы",
    "Формат проверки",
    "Продолжительность проверки, мин",
]


def rs_checkups() -> bytes:
    return to_csv(
        RS_CHECKUPS_HEADER,
        [
            [
                "Testville-1",
                back(C1),
                kb(U1, 2, C1, P_RS),
                "2026-10-06 15:15:00",
                "Тест Тестов",
                "2026-10-07 08:20:04",
                "IMF",
                "Serbia",
                "",
                "Инспекция",
                "42",
            ],
            [
                "Testville-2",
                back(C2),
                kb(U2, 2, C2, P_RS),
                "2026-10-07 11:00:00",
                "Тест Тестов",
                "2026-10-07 18:00:00",
                "",
                "Slovenia",
                "",
                "Онлайн",
                "",
            ],
            [
                "Testgrad-1",
                back(C_RU),
                kb(U_RU, 2, C_RU, P_RS),
                "2026-10-07 11:00:00",
                "Тест Тестов",
                "2026-10-07 18:00:00",
                "РФ",
                "Россия",
                "",
                "Инспекция",
                "30",
            ],
        ],
    )


SHEET_RS_HEADER = [
    "Бизнес-девелопер",
    "Страна",
    "Пиццерия",
    "Ссылка",
    "Август 2",
    "Сентябрь 1",
    "Сентябрь 2",
]


def sheet_rs() -> bytes:
    return to_csv(
        SHEET_RS_HEADER,
        [
            [
                "Dev One",
                "Serbia",
                "Testville-1",
                f"https://dodopizza.info/rating#/{U1}/2",
                "90",
                "88,5",
                "97.5%",
            ],
            ["Dev One", "Slovenia", "Testville 2", "", "", "71", ""],
            [
                "",
                "Россия",
                "Testgrad-1",
                f"https://dodopizza.info/rating#/{U_RU}/2",
                "80",
                "80",
                "80",
            ],
        ],
    )


SHEET_RKO_HEADER = [
    "Девелопер",
    "Страна",
    "Пиццерия",
    "Ссылка",
    "22.12 — 28.12",
    "29.12 — 04.01",
    "05.01 — 11.01",
]


def sheet_rko() -> bytes:
    return to_csv(
        SHEET_RKO_HEADER,
        [
            [
                "Dev One",
                "Serbia",
                "Testville-1",
                f"https://dodopizza.info/rating#/{U1}/1",
                "91",
                "92",
                "93",
            ]
        ],
    )
