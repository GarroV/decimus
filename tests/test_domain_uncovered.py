"""Накопитель непокрытых формулировок (T268).

Накопитель существует ровно затем, чтобы случай «записи не появилось» не
исчезал бесследно — поэтому здесь проверяется не только счастливый путь
(записалось — прочиталось), но и то, что накопитель ведёт себя честно на
границах: испорченный файл не превращается в тихую пустоту, а её отсутствие —
не путается с отказом. Тон и форма — как в `test_domain_finding_invariants.py`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.domain import (
    OUTCOME_ABANDONED,
    OUTCOME_RECORDED,
    ZONE_SOURCE_DICTIONARY,
    UncoveredEntry,
    archive_uncovered,
    read_uncovered,
    record_uncovered,
)
from src.domain.config import check_environment
from src.domain.engine import chat_dir
from src.domain.errors import ValidationError


def сделать(
    note: str = "стеллаж в углу грязный",
    *,
    outcome: str = OUTCOME_RECORDED,
    suggested_code: str = "",
    suggested_level: str = "",
    suggested_zone: str = "",
    confidence: float = 0.0,
    chosen_code: str = "",
    chosen_level: str = "",
    zone: str = "",
    zone_source: str = "",
    checklist_version: str = "",
    at: str = "",
) -> UncoveredEntry:
    """Готовая запись накопителя. `outcome` явный: у него нет легального умолчания."""
    return UncoveredEntry(
        note=note,
        outcome=outcome,
        suggested_code=suggested_code,
        suggested_level=suggested_level,
        suggested_zone=suggested_zone,
        confidence=confidence,
        chosen_code=chosen_code,
        chosen_level=chosen_level,
        zone=zone,
        zone_source=zone_source,
        checklist_version=checklist_version,
        at=at,
    )


# --- Запись и чтение ---------------------------------------------------------


def test_запись_читается_обратно_поля_и_типы_совпадают(domain_env: Path) -> None:
    """Разбор карты слов доверяет каждому полю записи — расхождение хотя бы в одном
    (например, уверенность, прочитанная строкой вместо числа) незаметно испортит выборку."""
    исходная = сделать(
        note="стеллаж в углу грязный",
        outcome=OUTCOME_ABANDONED,
        suggested_code="CLN07",
        suggested_level="D1",
        suggested_zone="dry_storage",
        confidence=0.42,
        chosen_code="",
        chosen_level="",
        zone="dry_storage",
        zone_source=ZONE_SOURCE_DICTIONARY,
        checklist_version="imf-2026-01-01-aaaaaaaaaaaa",
        at="2026-09-16T10:00:00+00:00",
    )
    record_uncovered(42, исходная)
    (прочитанная,) = read_uncovered(chat_id=42)
    assert прочитанная == исходная, f"запись вернулась другой: {прочитанная} != {исходная}"
    assert isinstance(прочитанная.confidence, float), (
        "уверенность обязана остаться числом с плавающей точкой, а не строкой из JSON"
    )


def test_порядок_прихода_сохраняется(domain_env: Path) -> None:
    record_uncovered(42, сделать("первая"))
    record_uncovered(42, сделать("вторая"))
    record_uncovered(42, сделать("третья"))
    формулировки = [e.note for e in read_uncovered(chat_id=42)]
    assert формулировки == ["первая", "вторая", "третья"], (
        f"порядок прихода нарушен: {формулировки}"
    )


def test_две_одинаковые_формулировки_дают_две_записи(domain_env: Path) -> None:
    """Идемпотентности здесь нет намеренно: повтор формулировки — это дело,
    встретившееся дважды, и счёт повторов нужен для разбора не меньше самой формулировки."""
    record_uncovered(42, сделать("грязная печь"))
    record_uncovered(42, сделать("грязная печь"))
    записи = read_uncovered(chat_id=42)
    assert len(записи) == 2, "повтор формулировки схлопнулся в одну запись — счёт повторов потерян"


# --- Архивация ----------------------------------------------------------------


def test_archive_переносит_open_в_history_и_второй_раз_ничего_не_переносит(
    domain_env: Path,
) -> None:
    record_uncovered(42, сделать("а"))
    record_uncovered(42, сделать("б"))
    перенесено = archive_uncovered(42)
    assert перенесено == 2, "обе записи открытой проверки должны перенестись в историю"
    assert [e.note for e in read_uncovered(chat_id=42)] == ["а", "б"], (
        "после архивации записи обязаны читаться как прежде"
    )
    второй_перенос = archive_uncovered(42)
    assert второй_перенос == 0, "повторная архивация обязана быть идемпотентной"
    assert [e.note for e in read_uncovered(chat_id=42)] == ["а", "б"], (
        "второй вызов не должен портить уже перенесённые записи"
    )


# --- Чтение нескольких чатов --------------------------------------------------


def test_read_uncovered_без_чата_собирает_все_чаты(domain_env: Path) -> None:
    record_uncovered(1, сделать("чат один"))
    record_uncovered(2, сделать("чат два"))
    формулировки = {e.note for e in read_uncovered()}
    assert формулировки == {"чат один", "чат два"}, (
        "чтение без chat_id обязано собрать записи со всех папок проверок"
    )


def test_read_uncovered_без_чата_упорядочен_по_имени_папки_не_по_числу(
    domain_env: Path,
) -> None:
    """Имя папки «chat_10» лексикографически меньше «chat_2» — так и обязан идти
    порядок, иначе он тайно зависел бы от того, в каком порядке ОС отдаёт список папок."""
    record_uncovered(2, сделать("у второго чата"))
    record_uncovered(10, сделать("у десятого чата"))
    формулировки = [e.note for e in read_uncovered()]
    assert формулировки == ["у десятого чата", "у второго чата"], (
        f"порядок разошёлся с сортировкой имён папок chat_10 < chat_2: {формулировки}"
    )


# --- Отказы --------------------------------------------------------------------


def test_неизвестный_исход_отклонён(domain_env: Path) -> None:
    with pytest.raises(ValidationError):
        record_uncovered(42, сделать(outcome="какой-то-неизвестный"))
    assert read_uncovered(chat_id=42) == (), (
        "отказ по исходу случился ДО записи — файл не должен получить частичную запись"
    )


def test_неизвестный_источник_зоны_отклонён(domain_env: Path) -> None:
    with pytest.raises(ValidationError):
        record_uncovered(42, сделать(zone_source="гадание"))


def test_пустая_формулировка_отклонена(domain_env: Path) -> None:
    with pytest.raises(ValidationError):
        record_uncovered(42, сделать(note=""))


def test_испорченный_json_накопителя_отказ_на_чтении(domain_env: Path) -> None:
    """Испорченный файл — не то же самое, что его отсутствие: одно отказ, другое — пустой ответ."""
    путь = chat_dir(42, check_environment()) / "uncovered.json"
    путь.parent.mkdir(parents=True, exist_ok=True)
    путь.write_text("это не json{{{", encoding="utf-8")
    with pytest.raises(ValidationError):
        read_uncovered(chat_id=42)


def test_накопитель_не_объектом_отказ_на_записи(domain_env: Path) -> None:
    """Валидный JSON, но не объект («[]») — тоже испорченный накопитель, а не пустой."""
    путь = chat_dir(42, check_environment()) / "uncovered.json"
    путь.parent.mkdir(parents=True, exist_ok=True)
    путь.write_text("[]", encoding="utf-8")
    with pytest.raises(ValidationError):
        record_uncovered(42, сделать("что угодно"))


def test_накопителя_нет_вовсе_пустой_ответ_не_отказ(domain_env: Path) -> None:
    assert read_uncovered(chat_id=999) == (), "нет файла — законное «ещё ничего не копилось»"
    assert read_uncovered() == (), "нет ни одной папки проверки — тоже пустой ответ"
    assert archive_uncovered(999) == 0, "нечего архивировать — ноль, а не отказ"


# --- Соседние файлы -------------------------------------------------------------


def test_запись_не_трогает_bot_json_и_inspection_json_рядом(domain_env: Path) -> None:
    """Три файла делят одну папку проверки — запись в один не должна касаться других."""
    папка = chat_dir(42, check_environment())
    папка.mkdir(parents=True, exist_ok=True)
    bot_json = папка / "bot.json"
    inspection_json = папка / "inspection.json"
    bot_текст = '{"schema": 4, "zone": "hot_kitchen", "frames": []}'
    inspection_текст = '{"meta": {"unit": "Белград-1"}}'
    bot_json.write_text(bot_текст, encoding="utf-8")
    inspection_json.write_text(inspection_текст, encoding="utf-8")

    record_uncovered(42, сделать("что угодно"))

    assert bot_json.read_text(encoding="utf-8") == bot_текст, (
        "заметки бота не должны измениться от записи в накопитель"
    )
    assert inspection_json.read_text(encoding="utf-8") == inspection_текст, (
        "состояние проверки не должно измениться от записи в накопитель"
    )
