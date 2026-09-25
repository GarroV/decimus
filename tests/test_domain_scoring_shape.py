"""T349: отпечаток того, что влияет на ОЦЕНКУ издания (#337).

Ряд оценок по сети смешивает проверки, посчитанные по разным ценам, и делает
это молча: средняя по такому ряду выглядит совершенно правдоподобно. Это худший
вид ошибки — не падение, а цифра, которой верят.

Чтобы разрыв ряда стал видимым, нужен способ ответить на вопрос «эти два
издания считали одинаково?». Отвечать им обязана не разница файлов целиком:
правка формулировки пункта или перевода названия зоны цену не двигает, и ряд от
неё рваться не должен — иначе признак сработает на каждом издании и его
перестанут читать.

Здесь проверяется ровно эта граница: что в отпечаток входит и что в него не
входит. Оценка при этом не пересчитывается нигде — отпечаток считается по
файлам методики, а проценты и буквы по-прежнему приходят только из `audit.py`.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from src.domain.shape import scoring_shape


def _правка_json(каталог: Path, меняем) -> None:  # type: ignore[no-untyped-def]
    файл = каталог / "scoring.json"
    тело = json.loads(файл.read_text(encoding="utf-8"))
    меняем(тело)
    файл.write_text(json.dumps(тело, ensure_ascii=False), encoding="utf-8")


def _строки(путь: Path) -> tuple[list[dict[str, str]], list[str]]:
    with путь.open(encoding="utf-8-sig", newline="") as f:
        читатель = csv.DictReader(f)
        строки = list(читатель)
    return строки, list(строки[0].keys())


def _записать(путь: Path, строки: list[dict[str, str]], колонки: list[str]) -> None:
    with путь.open("w", encoding="utf-8", newline="") as f:
        писарь = csv.DictWriter(f, fieldnames=колонки)
        писарь.writeheader()
        писарь.writerows(строки)


# --- что цену НЕ двигает ------------------------------------------------------


def test_правка_формулировки_ряд_не_рвёт(data_copy: Path) -> None:
    """Иначе признак срабатывает на каждом издании и его перестают читать.

    Правка текста пункта — самое частое переиздание методики: опечатка,
    уточнение, перевод. Считать проверки до и после неё несравнимыми значило бы
    объявить несравнимым вообще всё.
    """
    было = scoring_shape(data_copy)

    строки, колонки = _строки(data_copy / "checklist.csv")
    строки[0]["question_ru"] = "совершенно другая формулировка"
    строки[0]["process_ru"] = "и процесс другой"
    _записать(data_copy / "checklist.csv", строки, колонки)

    assert scoring_shape(data_copy) == было


def test_правка_названия_зоны_ряд_не_рвёт(data_copy: Path) -> None:
    """Название зоны — подпись в отчёте, а не вес в оценке."""
    было = scoring_shape(data_copy)

    строки, колонки = _строки(data_copy / "zones.csv")
    строки[0]["name_ru"] = "Переименованная зона"
    строки[0]["name_en"] = "Renamed zone"
    _записать(data_copy / "zones.csv", строки, колонки)

    assert scoring_shape(data_copy) == было


def test_правка_срока_устранения_ряд_не_рвёт(data_copy: Path) -> None:
    """Срок уезжает в предписание партнёру и в план, но не в процент и не в букву."""
    было = scoring_shape(data_copy)

    строки, колонки = _строки(data_copy / "checklist.csv")
    строки[0]["days"] = str(int(float(строки[0]["days"] or 0)) + 7)
    _записать(data_copy / "checklist.csv", строки, колонки)

    assert scoring_shape(data_copy) == было


def test_порядок_строк_в_файлах_ряд_не_рвёт(data_copy: Path) -> None:
    """Иначе перестановка пунктов в редакторе управляющей компании рвала бы ряд.

    Порядок обхода — дело маршрута (`route.csv`), а не цены: те же пункты с
    теми же классами считаются одинаково, в каком бы порядке они ни лежали.
    """
    было = scoring_shape(data_copy)

    строки, колонки = _строки(data_copy / "checklist.csv")
    _записать(data_copy / "checklist.csv", list(reversed(строки)), колонки)

    assert scoring_shape(data_copy) == было


def test_подсказки_и_критерии_ряд_не_рвут(data_copy: Path) -> None:
    """Критерии и карта кадров помогают аудитору, а считает движок не по ним."""
    было = scoring_shape(data_copy)

    критерии = data_copy / "criteria.md"
    критерии.write_text(критерии.read_text(encoding="utf-8") + "\nдописано\n", encoding="utf-8")

    assert scoring_shape(data_copy) == было


def test_сроки_из_настроек_ряд_не_рвут(data_copy: Path) -> None:
    """`deadlines` и `plan_due_days` лежат в том же файле, что и ставки, — и ценой не являются.

    Предел срока устранения и срок плана действий уезжают в предписание
    партнёру. Ни процента, ни буквы они не двигают, поэтому их правка ряд
    оценок не рвёт — иначе признак сработал бы на переиздании, где цена не
    менялась вовсе.
    """
    было = scoring_shape(data_copy)

    def правка(тело: dict[str, object]) -> None:
        тело["plan_due_days"] = int(тело.get("plan_due_days") or 0) + 5  # type: ignore[arg-type]
        сроки = тело["deadlines"]["max_days"]  # type: ignore[index]
        for класс in сроки:  # type: ignore[union-attr]
            сроки[класс] = int(сроки[класс]) + 3  # type: ignore[index]

    _правка_json(data_copy, правка)

    assert scoring_shape(data_copy) == было


def test_подпись_буквы_ряд_не_рвёт(data_copy: Path) -> None:
    """Ярлык буквы — текст в отчёте; сама буква и её порог остаются ценой."""
    было = scoring_shape(data_copy)

    def правка(тело: dict[str, object]) -> None:
        тело["grades"]["rules"][0]["label_ru"] = "Совсем другая подпись"  # type: ignore[index]
        тело["grades"]["fallback"]["label_en"] = "Another label"  # type: ignore[index]

    _правка_json(data_copy, правка)

    assert scoring_shape(data_copy) == было


# --- что цену двигает ---------------------------------------------------------


def test_ставка_вычета_рвёт_ряд(data_copy: Path) -> None:
    """Главная цена: изменившийся вычет делает проценты до и после несравнимыми."""
    было = scoring_shape(data_copy)

    _правка_json(data_copy, lambda тело: тело["penalty"].update({"D1": 9.0}))

    assert scoring_shape(data_copy) != было


def test_порог_буквы_рвёт_ряд(data_copy: Path) -> None:
    """Процент остался прежним, а буква у той же проверки стала другой.

    Буква — то, чем сводку и читают: распределение букв по сети собирается
    именно из неё.
    """
    было = scoring_shape(data_copy)

    def правка(тело: dict[str, object]) -> None:
        правила = тело["grades"]["rules"]  # type: ignore[index]
        for правило in правила:  # type: ignore[union-attr]
            if "pct_at_least" in правило["if"]:
                правило["if"]["pct_at_least"] = 99.0
                return
        raise AssertionError("в методике нет правила с порогом процента — тест ничего не стережёт")

    _правка_json(data_copy, правка)

    assert scoring_shape(data_copy) != было


def test_начальный_процент_рвёт_ряд(data_copy: Path) -> None:
    было = scoring_shape(data_copy)

    _правка_json(data_copy, lambda тело: тело.update({"start_pct": 90.0}))

    assert scoring_shape(data_copy) != было


def test_доля_зоны_рвёт_ряд(data_copy: Path) -> None:
    """Доля зоны — вес: та же находка стоит разного в зонах разного размера."""
    было = scoring_shape(data_copy)

    строки, колонки = _строки(data_copy / "zones.csv")
    строки[0]["share_pct"] = str(float(строки[0]["share_pct"]) + 5)
    строки[-1]["share_pct"] = str(float(строки[-1]["share_pct"]) - 5)
    _записать(data_copy / "zones.csv", строки, колонки)

    assert scoring_shape(data_copy) != было


def test_снятый_пункт_рвёт_ряд(data_copy: Path) -> None:
    """Состав влияющих на оценку пунктов — вторая половина цены."""
    было = scoring_shape(data_copy)

    строки, колонки = _строки(data_copy / "checklist.csv")
    _записать(data_copy / "checklist.csv", строки[1:], колонки)

    assert scoring_shape(data_copy) != было


def test_новый_класс_у_пункта_рвёт_ряд(data_copy: Path) -> None:
    """Классы пункта решают, каким вычетом он может обернуться."""
    было = scoring_shape(data_copy)

    строки, колонки = _строки(data_copy / "checklist.csv")
    строки[0]["levels"] = "D1;D2;D3"
    _записать(data_copy / "checklist.csv", строки, колонки)

    assert scoring_shape(data_copy) != было


def test_смена_зоны_у_пункта_рвёт_ряд(data_copy: Path) -> None:
    """Зона пункта решает, в чей вес ляжет находка."""
    было = scoring_shape(data_copy)

    строки, колонки = _строки(data_copy / "checklist.csv")
    зоны = [z["code"] for z in _строки(data_copy / "zones.csv")[0]]
    свои = [z.strip() for z in строки[0]["zones"].split(",") if z.strip()]
    чужая = next(z for z in зоны if z not in свои)
    строки[0]["zones"] = ",".join([*свои, чужая])
    _записать(data_copy / "checklist.csv", строки, колонки)

    assert scoring_shape(data_copy) != было


# --- когда ответа нет ---------------------------------------------------------


def test_каталога_нет_отпечатка_нет(tmp_path: Path) -> None:
    """Пусто — не отказ и не «сравнимо».

    Издания, методики которого на машине нет, сравнить не с чем. Выдать за
    сравнимое значило бы соврать ровно в ту сторону, ради которой задача и
    заведена; отказать — остановить сводку из-за отсутствующего архива.
    """
    assert scoring_shape(tmp_path / "нет-такого") is None


def test_испорченные_ставки_отпечатка_не_дают(data_copy: Path) -> None:
    """Нечитаемый `scoring.json` — то же самое: ответа нет, а не «как было»."""
    (data_copy / "scoring.json").write_text("{не json", encoding="utf-8")

    assert scoring_shape(data_copy) is None


def test_отпечаток_одинаков_у_двух_копий_одной_методики(data_copy: Path, tmp_path: Path) -> None:
    """Иначе признак зависел бы от пути, и каждая копия рвала бы ряд."""
    import shutil

    вторая = tmp_path / "вторая"
    shutil.copytree(data_copy, вторая)

    assert scoring_shape(вторая) == scoring_shape(data_copy)
