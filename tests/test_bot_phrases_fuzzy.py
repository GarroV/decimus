"""#1267, D646 п. 4: выученная фраза находится и тогда, когда её сказали иначе.

Правило выучивания не менялось: фраза ложится в карту после первого же
подтверждения аудитором (D119). Не работало узнавание: ключ — строка байт в
байт, поэтому «пол грязный в зале» не узнавалась, хотя «грязный пол в зале»
уже выучена, и аудитор снова ждал модель 8 секунд.

Узнавание по набору основ слов — это решение за человека без модели, поэтому
защита строгая и каждая её ветка здесь проверяется отдельно: два слова минимум,
набор целиком (а не часть), отрицание и противоречие в слова не прощаются,
спор двух пунктов и снятая строка — отказ, а не выбор.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest
from bot_harness import CHAT_ID

from src.bot.phrases import recall
from src.db import synonyms
from src.db.errors import ConfigError
from src.db.synonyms import LEARNED, PhraseAlias
from src.domain import start_inspection

ПУНКТ = "CLN05"
ДРУГОЙ = "TEH05"
ЯЗЫК = "ru"
ВЫУЧЕНО = "духовка вся закоптилась"


def начата() -> None:
    start_inspection(CHAT_ID, "Белград 2", "planned", ЯЗЫК, date="2026-08-21", auditor="Гарро")


def строка(phrase: str, code: str = ПУНКТ, *, снята: bool = False) -> PhraseAlias:
    return PhraseAlias(
        item_code=code,
        lang=ЯЗЫК,
        phrase=phrase,
        key=synonyms.normalize_phrase(phrase),
        origin=LEARNED,
        created_at=None,  # type: ignore[arg-type]
        retracted_at=object() if снята else None,  # type: ignore[arg-type]
    )


def карта(monkeypatch: pytest.MonkeyPatch, *строки: PhraseAlias) -> list[dict[str, Any]]:
    """Карта без точного совпадения: `lookup_phrase` молчит, `list_phrases` отдаёт строки."""
    спрошено: list[dict[str, Any]] = []
    monkeypatch.setattr(synonyms, "lookup_phrase", lambda *a, **k: None)

    def _list(**kw: Any) -> list[PhraseAlias]:
        спрошено.append(kw)
        return list(строки)

    monkeypatch.setattr(synonyms, "list_phrases", _list)
    return спрошено


def test_слова_в_другом_порядке_узнаются(domain_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    начата()
    спрошено = карта(monkeypatch, строка(ВЫУЧЕНО))

    найдено = recall("закоптилась вся духовка", lang=ЯЗЫК, chat_id=CHAT_ID)

    assert найдено is not None and найдено.code == ПУНКТ
    assert найдено.phrase == ВЫУЧЕНО, "аудитору показываем, ЧТО выучено, а не что он сказал"
    assert спрошено[0]["lang"] == ЯЗЫК, "карта читается на языке речи, чужие языки не мешаются"
    assert спрошено[0]["include_retracted"] is True, "снятые строки нужны для запрета"


def test_точное_совпадение_карту_целиком_не_читает(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Быстрый путь остаётся быстрым: сначала ключ, а полная карта — только при промахе."""
    начата()
    спрошено = карта(monkeypatch, строка(ВЫУЧЕНО))
    monkeypatch.setattr(synonyms, "lookup_phrase", lambda *a, **k: строка(ВЫУЧЕНО))

    assert recall(ВЫУЧЕНО, lang=ЯЗЫК, chat_id=CHAT_ID) is not None
    assert спрошено == []


def test_лишнее_значимое_слово_не_узнаётся(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Набор целиком, а не пересечение: «духовка закоптилась в зале» — уже другая мысль."""
    начата()
    карта(monkeypatch, строка(ВЫУЧЕНО))

    assert recall("духовка вся закоптилась и поломалась", lang=ЯЗЫК, chat_id=CHAT_ID) is None
    assert recall("духовка закоптилась", lang=ЯЗЫК, chat_id=CHAT_ID) is None


def test_отрицание_не_узнаётся(domain_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """«Духовка не закоптилась» — обратное выученному, пункт ставить нельзя."""
    начата()
    карта(monkeypatch, строка("духовка закоптилась"))

    assert recall("духовка не закоптилась", lang=ЯЗЫК, chat_id=CHAT_ID) is None
    assert recall("закоптилась духовка", lang=ЯЗЫК, chat_id=CHAT_ID) is not None


def test_противоречие_внутри_фразы_не_узнаётся(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Основа сказана и отрицается разом (T197): разбирать, какая половина про что, не берёмся."""
    начата()
    карта(monkeypatch, строка("духовка закоптилась"))

    assert (
        recall("духовка закоптилась, нагара нет, нагар есть", lang=ЯЗЫК, chat_id=CHAT_ID) is None
    ), "остаток фразы совпал бы с выученной, но это не то, что сказал человек"


def test_отрицаемое_слово_входит_в_набор(domain_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """«Духовка вся, нагара нет» и «духовка вся» — разные фразы, хотя утверждаемое то же."""
    начата()
    карта(monkeypatch, строка("духовка вся, нагара нет"))

    assert recall("духовка вся", lang=ЯЗЫК, chat_id=CHAT_ID) is None
    assert recall("вся духовка, нагара нет", lang=ЯЗЫК, chat_id=CHAT_ID) is not None


def test_одно_слово_по_основам_не_узнаётся(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Одна основа — слишком мало: «нагара» не должно утягивать «нагар» без второго слова."""
    начата()
    карта(monkeypatch, строка("нагар"))

    assert recall("нагара", lang=ЯЗЫК, chat_id=CHAT_ID) is None


def test_два_пункта_с_одним_набором_слов_спор_а_не_выбор(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    начата()
    карта(monkeypatch, строка(ВЫУЧЕНО, ПУНКТ), строка("закоптилась вся духовка", ДРУГОЙ))

    assert recall("вся духовка закоптилась", lang=ЯЗЫК, chat_id=CHAT_ID) is None


def test_два_синонима_одного_пункта_не_спор(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    начата()
    карта(monkeypatch, строка(ВЫУЧЕНО, ПУНКТ), строка("закоптилась вся духовка", ПУНКТ))

    найдено = recall("вся духовка закоптилась", lang=ЯЗЫК, chat_id=CHAT_ID)

    assert найдено is not None and найдено.code == ПУНКТ


def test_снятая_строка_запрещает_узнавание_соседей(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Управляющая компания сняла эту формулировку (T292): перестановка слов её не воскрешает."""
    начата()
    карта(monkeypatch, строка(ВЫУЧЕНО, ДРУГОЙ, снята=True), строка("закоптилась вся духовка"))

    assert recall("вся духовка закоптилась", lang=ЯЗЫК, chat_id=CHAT_ID) is None


def test_пункт_вне_издания_не_применяется(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    начата()
    карта(monkeypatch, строка(ВЫУЧЕНО, "XXX99"))

    assert recall("закоптилась вся духовка", lang=ЯЗЫК, chat_id=CHAT_ID) is None


def test_отказ_карты_не_роняет_разбор(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    начата()
    монитор = карта(monkeypatch)
    monkeypatch.setattr(
        synonyms, "list_phrases", lambda **kw: (_ for _ in ()).throw(ConfigError("нет базы"))
    )

    with caplog.at_level(logging.WARNING):
        assert recall("закоптилась вся духовка", lang=ЯЗЫК, chat_id=CHAT_ID) is None

    assert монитор == [] and "нет базы" in caplog.text, "отказ должен остаться в журнале"
