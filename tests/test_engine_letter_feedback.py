"""D663, D664: сильные стороны и зоны роста пиццерии — в письме и на первой странице отчёта.

Связь с информационным полем идёт КОДОМ пункта, а не текстом вопроса: у пункта
методики колонка `letter_role` (`strengths` / `growth`). Чек-листы по странам
разные, формулировки правятся и переводятся — код остаётся. Текст аудитора
уходит как есть (без правки моделью): срезаются пробелы и ведущая нумерация.

Проверяется поведение движка на всех трёх видах письма (план, чистая, пустая) и
на обоих шаблонах, плюс граница языка: обратная связь на языке, отличном от
языка документа, не подставляется молча и не переводится.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import AUDIT, REPORT, Run, run_engine

СИЛЬНЫЕ = "INF01"
РОСТ = "INF06"
ТЕКСТ_СИЛЬНЫЕ = "Чистая кухня, вежливая смена"
ТЕКСТ_РОСТ = "Сроки годности на заготовках"

ГОЛОВА = {
    "ru": ("Что получается хорошо:", "Над чем стоит поработать:"),
    "en": ("What is going well:", "What to work on:"),
}
СПАСИБО = {"ru": "Спасибо за работу", "en": "Thank you for your work"}
ЗАФИКСИРОВАЛИ = {"plan": "Что зафиксировали:", "clean": "Что отметили:"}


def _роли(каталог: Path, роли: dict[str, str]) -> None:
    """Дописать колонку `letter_role` в копию методики."""
    путь = каталог / "checklist.csv"
    with путь.open(encoding="utf-8-sig", newline="") as f:
        строки = list(csv.DictReader(f))
        поля = list(строки[0].keys())
    if "letter_role" not in поля:
        поля.append("letter_role")
    for строка in строки:
        строка["letter_role"] = роли.get(строка["id"], "")
    with путь.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=поля)
        w.writeheader()
        w.writerows(строки)


@pytest.fixture
def с_ролями(data_copy: Path) -> Path:
    _роли(data_copy, {СИЛЬНЫЕ: "strengths", РОСТ: "growth"})
    return data_copy


@pytest.fixture
def прогон(workdir: Path, с_ролями: Path) -> Callable[..., Run]:
    """`audit.py` и `report.py` над методикой с ролями; первый аргумент — скрипт."""

    def call(script: Path, *args: str) -> Run:
        return run_engine(
            script, *args, cwd=workdir, state=workdir / "inspection.json", data_dir=с_ролями
        )

    return call


def _начать(
    прогон: Callable[..., Run],
    *,
    вид: str,
    сильные: str | None = ТЕКСТ_СИЛЬНЫЕ,
    рост: str | None = ТЕКСТ_РОСТ,
) -> None:
    """Проверка нужного вида: `plan` (D2), `clean` (одно D1), `empty` (без записей)."""
    assert (
        прогон(
            AUDIT, "init", "--unit", "Тестовая", "--auditor", "Тест", "--date", "2026-08-21"
        ).code
        == 0
    )
    if вид == "plan":
        r = прогон(
            AUDIT,
            "add",
            "--qid",
            "PRD01",
            "--level",
            "D2",
            "--zone",
            "fridge",
            "--evidence",
            "Нет ярлыка",
        )
        assert r.code == 0, r.text
    elif вид == "clean":
        r = прогон(
            AUDIT,
            "add",
            "--qid",
            "PRD01",
            "--level",
            "D1",
            "--zone",
            "fridge",
            "--evidence",
            "Нет ярлыка",
        )
        assert r.code == 0, r.text
    for код, текст in ((СИЛЬНЫЕ, сильные), (РОСТ, рост)):
        if текст is not None:
            r = прогон(AUDIT, "info", "--qid", код, "--text", текст)
            assert r.code == 0, r.text


def _письмо(прогон: Callable[..., Run], *args: str) -> str:
    r = прогон(REPORT, "letter", *args)
    assert r.code == 0, r.text
    return r.out


@pytest.mark.parametrize("язык", ["ru", "en"])
@pytest.mark.parametrize("вид", ["plan", "clean", "empty"])
def test_шаблон_1_сильные_до_нарушений_зоны_роста_после(
    прогон: Callable[..., Run], вид: str, язык: str
) -> None:
    _начать(прогон, вид=вид)
    # Информационные поля записаны по-русски; письмо на английском их не получит
    # (граница языка, ниже), поэтому для английского называем язык записи.
    текст = _письмо(прогон, "--lang", язык, "--template", "1", "--speech-lang", язык)
    хорошо, работа = ГОЛОВА[язык]
    assert хорошо in текст and работа in текст, текст
    assert ТЕКСТ_СИЛЬНЫЕ in текст and ТЕКСТ_РОСТ in текст
    оценка = текст.index("%).")
    assert оценка < текст.index(хорошо) < текст.index(работа), "порядок блоков шаблона 1"
    if вид != "empty":
        ключ = ЗАФИКСИРОВАЛИ["plan" if вид == "plan" else "clean"] if язык == "ru" else None
        if ключ:
            assert текст.index(хорошо) < текст.index(ключ) < текст.index(работа), (
                "нарушения должны стоять между сильными сторонами и зонами роста"
            )
    assert текст.index(работа) < текст.index(СПАСИБО[язык])


@pytest.mark.parametrize("язык", ["ru", "en"])
@pytest.mark.parametrize("вид", ["plan", "clean", "empty"])
def test_шаблон_2_обе_части_в_конце_перед_благодарностью(
    прогон: Callable[..., Run], вид: str, язык: str
) -> None:
    _начать(прогон, вид=вид)
    текст = _письмо(прогон, "--lang", язык, "--template", "2", "--speech-lang", язык)
    хорошо, работа = ГОЛОВА[язык]
    спасибо = текст.index(СПАСИБО[язык])
    assert текст.index("%).") < текст.index(хорошо) < текст.index(работа) < спасибо
    # Нарушения идут как прежде — до обратной связи.
    if вид == "plan":
        assert текст.index("Нет ярлыка") < текст.index(хорошо)
    # Тексты стоят сразу под своими заголовками.
    assert текст.index(хорошо) < текст.index(ТЕКСТ_СИЛЬНЫЕ) < текст.index(работа)
    assert текст.index(работа) < текст.index(ТЕКСТ_РОСТ) < спасибо


def test_шаблон_по_умолчанию_первый(прогон: Callable[..., Run]) -> None:
    _начать(прогон, вид="plan")
    assert _письмо(прогон, "--lang", "ru") == _письмо(прогон, "--lang", "ru", "--template", "1")


def test_пустое_поле_блока_нет(прогон: Callable[..., Run]) -> None:
    _начать(прогон, вид="plan", сильные="   ", рост=None)
    for шаблон in ("1", "2"):
        текст = _письмо(прогон, "--lang", "ru", "--template", шаблон)
        assert "Что получается хорошо:" not in текст, "заголовок печатается над пустым полем"
        assert "Над чем стоит поработать:" not in текст


def test_одна_часть_без_другой(прогон: Callable[..., Run]) -> None:
    _начать(прогон, вид="plan", сильные=None)
    текст = _письмо(прогон, "--lang", "ru", "--template", "2")
    assert "Над чем стоит поработать:" in текст and "Что получается хорошо:" not in текст


def test_нумерация_срезается_и_текст_как_есть(прогон: Callable[..., Run]) -> None:
    _начать(
        прогон,
        вид="plan",
        сильные="  1. Чистая кухня\n2. Вежливая смена  ",
        рост="2.5 кг муки не взвешено",
    )
    текст = _письмо(прогон, "--lang", "ru")
    assert "Что получается хорошо:\nЧистая кухня\n2. Вежливая смена\n" in текст, (
        "ведущая нумерация не срезана либо нумерация внутри текста тронута"
    )
    assert "Над чем стоит поработать:\n2.5 кг муки не взвешено\n" in текст, (
        "«2.5 кг» принято за нумерацию"
    )


def test_язык_не_совпал_блока_нет_и_есть_предупреждение(прогон: Callable[..., Run]) -> None:
    _начать(прогон, вид="plan")  # проверка заведена по-русски, поля записаны по-русски
    r = прогон(REPORT, "letter", "--lang", "en")
    assert r.code == 0, r.text
    assert ТЕКСТ_СИЛЬНЫЕ not in r.out and ТЕКСТ_РОСТ not in r.out, "чужой язык подставлен молча"
    assert ГОЛОВА["en"][0] not in r.out and ГОЛОВА["en"][1] not in r.out
    assert "не вставлена" in r.err and "«ru»" in r.err and "«en»" in r.err, r.err
    # Для программ — то же в структуре: список ролей и язык записи.
    данные = json.loads(прогон(REPORT, "letter", "--lang", "en", "--json").out)
    assert данные["feedback_skipped"] == ["strengths", "growth"]
    assert данные["feedback_lang"] == "ru"
    assert ТЕКСТ_СИЛЬНЫЕ not in данные["text"]


def test_язык_совпал_предупреждения_нет(прогон: Callable[..., Run]) -> None:
    _начать(прогон, вид="plan")
    r = прогон(REPORT, "letter", "--lang", "ru")
    assert r.err == "" and ТЕКСТ_СИЛЬНЫЕ in r.out
    данные = json.loads(прогон(REPORT, "letter", "--lang", "ru", "--json").out)
    assert данные["feedback_skipped"] == []


def test_нет_пометки_письмо_как_раньше(workdir: Path) -> None:
    """Синтетическая методика без `letter_role`: поля заполнены, блоков нет, письмо прежнее."""

    def run(script: Path, *args: str) -> Run:
        return run_engine(script, *args, cwd=workdir, state=workdir / "inspection.json")

    assert (
        run(AUDIT, "init", "--unit", "Тестовая", "--auditor", "Тест", "--date", "2026-08-21").code
        == 0
    )
    assert (
        run(
            AUDIT,
            "add",
            "--qid",
            "PRD01",
            "--level",
            "D2",
            "--zone",
            "fridge",
            "--evidence",
            "Нет ярлыка",
        ).code
        == 0
    )
    до = run(REPORT, "letter", "--lang", "ru").out
    assert run(AUDIT, "info", "--qid", СИЛЬНЫЕ, "--text", ТЕКСТ_СИЛЬНЫЕ).code == 0
    после = run(REPORT, "letter", "--lang", "ru", "--template", "2")
    assert после.code == 0 and после.err == ""
    assert после.out == до, "информационное поле без пометки изменило письмо"


def test_отчёт_блок_на_первой_странице_и_не_дублируется_в_приложении(
    прогон: Callable[..., Run],
) -> None:
    _начать(прогон, вид="plan")
    assert прогон(AUDIT, "info", "--qid", "INF03", "--text", "да").code == 0  # служебное поле
    r = прогон(REPORT, "html", "--lang", "ru")
    assert r.code == 0, r.text
    html = r.out
    assert "Обратная связь" in html
    assert html.index("Обратная связь") < html.index("Сводка"), (
        "блок не на первой странице под оценкой"
    )
    assert html.index("%</div>") < html.index("Обратная связь")
    assert html.count(ТЕКСТ_СИЛЬНЫЕ) == 1 and html.count(ТЕКСТ_РОСТ) == 1, (
        "обратная связь напечатана дважды — в приложении тоже"
    )
    assert "Приложение" in html and "да" in html.split("Приложение", 1)[1], (
        "прочие информационные поля из приложения пропали"
    )


def test_отчёт_язык_не_совпал_блока_нет_и_в_приложении_тоже(
    прогон: Callable[..., Run],
) -> None:
    _начать(прогон, вид="plan")
    r = прогон(REPORT, "html", "--lang", "en")
    assert r.code == 0, r.text
    assert "Feedback" not in r.out and ТЕКСТ_СИЛЬНЫЕ not in r.out and ТЕКСТ_РОСТ not in r.out
    assert "не вставлена" in r.err, r.err


def test_неизвестная_роль_отказ(data_copy: Path, workdir: Path) -> None:
    _роли(data_copy, {СИЛЬНЫЕ: "strenghts"})  # опечатка
    r = run_engine(
        AUDIT,
        "init",
        "--unit",
        "Т",
        "--date",
        "2026-08-21",
        cwd=workdir,
        state=workdir / "inspection.json",
        data_dir=data_copy,
    )
    assert r.code == 0, r.text
    r = run_engine(
        AUDIT, "score", cwd=workdir, state=workdir / "inspection.json", data_dir=data_copy
    )
    assert r.code != 0 and "letter_role" in r.text and "strenghts" in r.text, r.text


def test_неизвестный_шаблон_отказ(прогон: Callable[..., Run]) -> None:
    _начать(прогон, вид="plan")
    r = прогон(REPORT, "letter", "--lang", "ru", "--template", "3")
    assert r.code != 0 and "Шаблон письма" in r.text
