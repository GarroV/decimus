"""Синтетические выгрузки рейтингов для тестов: заголовки живые, данные выдуманы.

Живые файлы в репозиторий не кладутся (конституция: названия точек партнёров и
их оценки чувствительны). Здесь — те же колонки, BOM и CRLF, что у Dodo IS, и
вымышленные пиццерии `Testville-N` с id `aa…01`.
"""

from __future__ import annotations

import csv
import io
import json

U1 = "aa000000000000000000000000000001"
U2 = "aa000000000000000000000000000002"
U_RU = "aa0000000000000000000000000000ff"
C1 = "cc000000000000000000000000000001"
C2 = "cc000000000000000000000000000002"
C3 = "cc000000000000000000000000000003"
C_RU = "cc0000000000000000000000000000ff"
P_RKO = "dd000000000000000000000000000001"
P_RS = "dd000000000000000000000000000002"
P_RS_PREV = "dd000000000000000000000000000003"


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


#: Заголовок в первой строке, без служебных строк — допустимый простой вид листа.
SHEET_RS_HEADER = [
    "Бизнес-девелопер",
    "Страна",
    "Пиццерия",
    "Ссылка",
    "Август 2",
    "Сентябрь 1",
    "Сентябрь 2",
]


def sheet_csv(rows: list[list[str]]) -> bytes:
    """Как «Файл → Скачать → CSV» из Google-таблицы: строки как есть, без заголовка."""
    return to_csv(rows[0], rows[1:])


def sheet_rs() -> bytes:
    """Устройство настоящего листа РС: служебные строки над подписями периодов,
    строка «Девелопер, Страна, Пиццерия» под ними, дубль «Пиццерия» в колонке E,
    девелопер и страна только в первой строке объединённого блока, флаг у страны,
    прочерк вместо оценки."""
    return sheet_csv(
        [
            ["Кол-во пиццерий", "", "", "", "", "", "", ""],
            ["Рейтинг/Показатель", "", "", "", "", "Август 2", "Сентябрь 1 ", "Сентябрь 2"],
            ["Девелопер", "Страна", "Пиццерия", "", "Пиццерия", "", "", ""],
            [
                "Dev One",
                "🇷🇸 Serbia",
                "Testville-1",
                f"https://dodopizza.info/rating#/{U1}/2",
                "Testville-1",
                "90",
                "88,5",
                "97.5%",
            ],
            ["", "Slovenia", "Testville 2", "#N/A", "Testville 2", "-", "71", ""],
            [
                "",
                "\n\nРоссия\n",
                "Testgrad-1",
                f"https://dodopizza.info/rating#/{U_RU}/2",
                "Testgrad-1",
                "80",
                "80",
                "80",
            ],
        ]
    )


def sheet_rko() -> bytes:
    """Устройство настоящего листа РКО: строки «Месяц» и «Неделя рейтинга», без
    строки «Девелопер, Страна…», флаг у страны, «—» вместо оценки."""
    return sheet_csv(
        [
            ["Месяц", "", "", "", "", "Декабрь 2025", "", "Январь"],
            ["Неделя рейтинга", "", "", "", "", "22.12 — 28.12", "29.12 — 04.01", "05.01 — 11.01"],
            [
                "Dev One",
                "🇷🇸 Serbia",
                "Testville-1",
                f"https://dodopizza.info/rating#/{U1}/1",
                "Testville-1",
                "91",
                "92",
                "93",
            ],
            ["", "", "Testville-3", "", "Testville-3", "—", "94", ""],
        ]
    )


def snapshot_doc(**unit_override: object) -> dict[str, object]:
    unit: dict[str, object] = {
        "dodo_id": U1.upper(),
        "name": "Testville-1",
        "country_id": 12,
        "history": [
            {
                "score": 97.5,
                "status": "1",
                "period": {
                    "id": P_RS,
                    "rating_type": 2,
                    "begin": "2026-09-16T00:00:00",
                    "end": "2026-09-30",
                    "alias": "Сентябрь 2 часть 2026",
                    "alias_en": "September part 2 2026",
                },
            },
            {
                "score": 91,
                "status": "1",
                "period": {
                    "id": P_RKO,
                    "rating_type": 1,
                    "begin": "2026-09-29",
                    "end": "2026-10-05",
                    "alias": "29.09–05.10",
                },
            },
            {
                "score": None,
                "status": "0",
                "period": {
                    "id": P_RS_PREV,
                    "rating_type": 2,
                    "begin": "2026-09-01",
                    "end": "2026-09-15",
                    "alias": "Сентябрь 1 часть 2026",
                },
            },
        ],
        "remarks": [
            {
                "period_id": P_RS,
                "checkups": 4,
                "items": [
                    {
                        "criterion_id": "17",
                        "name": "Грязный пол",
                        "parent": "D1",
                        "deduction": -0.5,
                        "auto": False,
                        "amount": 2,
                        "wow": False,
                    },
                    {
                        "criterion_id": "99",
                        "name": "Улыбка",
                        "parent": "WOW",
                        "deduction": 0,
                        "auto": False,
                        "amount": 1,
                        "wow": True,
                    },
                ],
            },
            {
                "period_id": P_RKO,
                "checkups": 3,
                "items": [{"criterion_id": "5", "name": "Белый борт", "amount": 1}],
            },
        ],
    }
    unit.update(unit_override)
    return {
        "version": 1,
        "taken_at": "2026-10-08T10:00:00Z",
        "chunk": {"index": 2, "of": 3},
        "countries": [
            {"id": 12, "name": "Serbia", "region": 2},
            {"id": 1, "name": "Russia", "region": 1},
        ],
        "units": [
            unit,
            {"dodo_id": U_RU, "name": "Testgrad-1", "country_id": 1, "history": [], "remarks": []},
        ],
    }


def snapshot(**unit_override: object) -> bytes:
    return json.dumps(snapshot_doc(**unit_override), ensure_ascii=False).encode("utf-8")
