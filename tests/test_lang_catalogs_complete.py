"""Полнота словарей по языкам отчёта (#541, #1619): каждый язык `REPORT_LANGS` — в каждом каталоге.

Третий язык отчёта — строка в `src/domain/models.py: REPORT_LANGS` плюс переводы в
каталогах ниже. Пропущенный перевод не должен всплыть в готовом письме партнёру
английским словом вместо турецкого: он обязан покраснеть здесь, с названием
каталога, ключа и языка.

Движок (`engine/`) не импортирует `src` по контракту слоёв и держит свою копию списка
языков — тест сверяет её с `REPORT_LANGS` и заодно читает каталоги движка.
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Mapping
from types import ModuleType
from typing import Any

import pytest
from conftest import ROOT

from src.domain import geo, item_label, kinds, mailing_content
from src.domain.models import BASE_LANG, REPORT_LANGS
from src.report import batch_letter_texts
from src.web import google_mail


def _load_engine() -> tuple[ModuleType, ModuleType]:
    """`engine/audit.py` и `engine/report.py` по пути: как подпроцесс, но в памяти.

    Тот же приём, что у `test_engine_manage_columns.py`: движку нужен соседний `audit`,
    поэтому путь на время загрузки дополняется и после возвращается как был.
    """
    было_путь, было_модули = list(sys.path), set(sys.modules)
    try:
        spec = importlib.util.spec_from_file_location(
            "report_под_тестом", ROOT / "engine/report.py"
        )
        assert spec and spec.loader
        report = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = report
        spec.loader.exec_module(report)
        return sys.modules["audit"], report
    finally:
        sys.path[:] = было_путь
        for имя in set(sys.modules) - было_модули:
            sys.modules.pop(имя, None)


AUDIT, REPORT = _load_engine()


def _empty(value: Any) -> bool:
    """Пустой перевод: пустая строка, пустой набор или пустая строка внутри набора."""
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, Mapping):
        return not value or any(_empty(v) for v in value.values())
    if isinstance(value, (tuple, list)):
        return not value or any(_empty(v) for v in value)
    return value is None


def holes_lang_first(name: str, catalog: Mapping[str, Any]) -> list[str]:
    """Каталог «язык → (ключ → текст) или текст»: язык есть, ключи те же, что у базового."""
    out: list[str] = []
    base_keys = set(catalog[BASE_LANG]) if isinstance(catalog.get(BASE_LANG), Mapping) else None
    for lang in REPORT_LANGS:
        if lang not in catalog:
            out.append(f"{name}: нет языка «{lang}»")
            continue
        value = catalog[lang]
        if _empty(value):
            out.append(f"{name}[{lang}]: пусто")
        if base_keys is not None and isinstance(value, Mapping) and set(value) != base_keys:
            razn = sorted(set(value) ^ base_keys)
            out.append(f"{name}[{lang}]: набор ключей расходится с «{BASE_LANG}»: {razn}")
    return out


def holes_key_first(name: str, catalog: Mapping[str, Any]) -> list[str]:
    """Каталог «ключ → язык → текст»: у каждого ключа есть каждый язык и он не пуст."""
    out: list[str] = []
    for key, by_lang in catalog.items():
        for lang in REPORT_LANGS:
            if lang not in by_lang:
                out.append(f"{name}[{key}]: нет языка «{lang}»")
            elif _empty(by_lang[lang]):
                out.append(f"{name}[{key}][{lang}]: пусто")
    return out


#: Каталоги «язык → …»: постоянные тексты отчёта и письма в движке, тема письма.
LANG_FIRST: dict[str, Mapping[str, Any]] = {
    "engine/report.py T": REPORT.T,
    "engine/report.py GRADE_NOTE": REPORT.GRADE_NOTE,
    "engine/report.py ITEM_REF": REPORT.ITEM_REF,
    "engine/report.py LETTER_PLAN": REPORT.LETTER_PLAN,
    "engine/report.py LETTER_CLEAN": REPORT.LETTER_CLEAN,
    "engine/report.py LETTER_EMPTY": REPORT.LETTER_EMPTY,
    "engine/report.py LETTER_FEEDBACK": REPORT.LETTER_FEEDBACK,
    "engine/report.py LETTER_COUNTS": REPORT.LETTER_COUNTS,
    "engine/report.py LETTER_CRITICAL": REPORT.LETTER_CRITICAL,
    "engine/report.py TIME_UNITS": REPORT.TIME_UNITS,
    "engine/report.py FILE_WORDS": REPORT.FILE_WORDS,
    "web/google_mail.py SUBJECT_TITLES": google_mail.SUBJECT_TITLES,
}

#: Каталоги «ключ → язык → …»: виды проверки (две копии), общее письмо, метки, города,
#: встроенные шаблоны писем.
KEY_FIRST: dict[str, Mapping[str, Any]] = {
    "engine/audit.py INSPECTION_KINDS": AUDIT.INSPECTION_KINDS,
    "domain/kinds.py INSPECTION_KINDS": kinds.INSPECTION_KINDS,
    "report/batch_letter_texts.py TEXTS": batch_letter_texts.TEXTS,
    "domain/item_label.py SPECIAL_TITLES": item_label.SPECIAL_TITLES,
    "domain/geo.py CITIES": geo.CITIES,
    "domain/mailing_content.py DEFAULTS": mailing_content.DEFAULTS,
}


def test_список_языков_движка_равен_списку_продукта() -> None:
    assert tuple(AUDIT.LANGS) == REPORT_LANGS
    assert AUDIT.BASE_LANG == BASE_LANG


@pytest.mark.parametrize("name", LANG_FIRST)
def test_каталог_язык_первым_полон(name: str) -> None:
    assert holes_lang_first(name, LANG_FIRST[name]) == []


@pytest.mark.parametrize("name", KEY_FIRST)
def test_каталог_ключ_первым_полон(name: str) -> None:
    assert holes_key_first(name, KEY_FIRST[name]) == []


def test_проверка_ловит_дыру_в_каталоге() -> None:
    """Сама проверка обязана краснеть на пропуске: без этого зелёное ничего не значит."""
    other = REPORT_LANGS[-1]
    assert other != BASE_LANG
    полный = {lang: {"a": "x", "b": "y"} for lang in REPORT_LANGS}
    assert holes_lang_first("t", полный) == []
    assert holes_lang_first("t", {k: v for k, v in полный.items() if k != other})
    assert holes_lang_first("t", {**полный, other: {"a": " ", "b": "y"}})
    assert holes_lang_first("t", {**полный, other: {"a": "x"}})
    по_ключам = {"k": {lang: "x" for lang in REPORT_LANGS}}
    assert holes_key_first("t", по_ключам) == []
    assert holes_key_first("t", {"k": {BASE_LANG: "x"}})
    assert holes_key_first("t", {"k": {**по_ключам["k"], other: ""}})
