"""Лимиты пространства партнёра (D755, D759 п.5, #1670): правило и потолок расхода модели.

Ядро — деньги и права: какой лимит действует (настройка, умолчание, «без лимита»,
УК), когда потолок расхода закрывает вызов модели и что до платного вызова дело не
доходит. База и сеть подменены; настоящие запросы — `tests/test_db_space_limits.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from src.db import space_limits as db_limits
from src.domain.model_usage import usage_scope
from src.domain.space_limits import (
    DEFAULT_INSPECTIONS_PER_UNIT,
    DEFAULT_MONTHLY_SPEND_USD,
    DEFAULTS,
    UNLIMITED,
    Limits,
    check_inspections,
    check_spend,
    effective,
    month_start,
    spend_level,
)
from src.recognize import spend_cap
from src.recognize.client import ask_model
from src.recognize.config import RecognizeSettings
from src.recognize.errors import MODEL_LIMIT_MESSAGE, ModelLimitReached, ModelUnavailable
from src.recognize.pricing import Price
from src.recognize.spend_cap import Spend, cost_of, ensure_within_cap
from src.recognize.transcribe import transcribe

# --- какой лимит действует -----------------------------------------------------


def test_партнёр_без_строки_получает_умолчания_пять_проверок_и_пятьдесят_долларов() -> None:
    assert effective("GE", None) == DEFAULTS
    assert DEFAULTS.inspections_per_unit == DEFAULT_INSPECTIONS_PER_UNIT == 5
    assert DEFAULTS.monthly_spend_usd == DEFAULT_MONTHLY_SPEND_USD == Decimal("50")


def test_строка_настроек_перекрывает_умолчание_а_пустое_значение_снимает_лимит() -> None:
    свои = Limits(inspections_per_unit=3, monthly_spend_usd=Decimal("12.50"))
    assert effective("GE", свои) == свои
    без_потолка = Limits(inspections_per_unit=3, monthly_spend_usd=None)
    assert effective("GE", без_потолка).monthly_spend_usd is None


@pytest.mark.parametrize("stored", [None, DEFAULTS, Limits(1, Decimal("0"))])
def test_ук_без_лимитов_что_бы_ни_лежало_в_настройках(stored: Limits | None) -> None:
    assert effective("HQ", stored) == UNLIMITED


def test_потолок_месяца_календарный_utc() -> None:
    момент = datetime(2026, 11, 30, 23, 59, tzinfo=UTC)
    assert month_start(момент) == datetime(2026, 11, 1, tzinfo=UTC)
    assert month_start(datetime(2026, 12, 1, 0, 0, tzinfo=UTC)) == datetime(2026, 12, 1, tzinfo=UTC)


@pytest.mark.parametrize(
    ("spent", "cap", "level"),
    [
        ("0", "50", "ok"),
        ("39.99", "50", "ok"),
        ("40", "50", "warn"),
        ("49.99", "50", "warn"),
        ("50", "50", "over"),
        ("73", "50", "over"),
        ("1000", None, "ok"),
        ("0", "0", "over"),
    ],
)
def test_уровень_расхода_предупреждение_с_восьмидесяти_процентов(
    spent: str, cap: str | None, level: str
) -> None:
    assert spend_level(Decimal(spent), None if cap is None else Decimal(cap)) == level


def test_негодные_значения_лимитов_отвергаются() -> None:
    for плохо in (0, -1, True, 2.5):
        with pytest.raises(ValueError):
            check_inspections(плохо)  # type: ignore[arg-type]
    for плохо_д in (Decimal("-0.01"), Decimal("1.005"), Decimal("1000000.01")):
        with pytest.raises(ValueError):
            check_spend(плохо_д)
    assert check_inspections(None) is None and check_spend(None) is None
    assert check_spend(Decimal("0")) == Decimal("0")


# --- расход в долларах ----------------------------------------------------------


def test_расход_считается_по_ценам_а_модель_без_цены_помечает_неполный_итог() -> None:
    rows = (
        db_limits.SpendRow("m", 500_000, 100_000, 0.0),
        db_limits.SpendRow("без-цены", 10, 10, 0.0),
    )
    prices = {"m": Price(input_per_1m=2.0, output_per_1m=10.0)}

    total, partial = cost_of(rows, prices)

    assert total == Decimal("2.00") and partial is True


# --- потолок закрывает вызов -----------------------------------------------------


@pytest.fixture(autouse=True)
def _чистый_кэш() -> None:
    spend_cap.forget()


def _read(spent: str, cap: str | None, seen: list[str] | None = None) -> Any:
    def read(tenant: str) -> Spend:
        if seen is not None:
            seen.append(tenant)
        return Spend(Decimal(spent), False, None if cap is None else Decimal(cap))

    return read


def test_расход_на_потолке_закрывает_вызов_ниже_потолка_открывает() -> None:
    with pytest.raises(ModelLimitReached):
        ensure_within_cap("GE", read=_read("50", "50"))
    spend_cap.forget()
    ensure_within_cap("GE", read=_read("49.99", "50"))


def test_без_потолка_и_у_ук_расход_не_проверяется() -> None:
    seen: list[str] = []
    ensure_within_cap("GE", read=_read("100000", None, seen))
    ensure_within_cap("HQ", read=_read("100000", "1", seen))
    ensure_within_cap(None, read=_read("100000", "1", seen))  # дверь не назвала пространство
    assert seen == ["GE"]


def test_пространство_берётся_из_контекста_двери() -> None:
    with usage_scope(tenant="GE"), pytest.raises(ModelLimitReached):
        ensure_within_cap(read=_read("60", "50"))
    spend_cap.forget()
    with usage_scope(tenant="HQ"):
        ensure_within_cap(read=_read("60", "50"))


def test_сумма_и_лимиты_кэшируются_на_секунды_потом_читаются_заново() -> None:
    now = [100.0]
    seen: list[str] = []
    read = _read("1", "50", seen)

    for _ in range(3):
        ensure_within_cap("GE", clock=lambda: now[0], read=read)
    assert seen == ["GE"]
    now[0] += spend_cap.CACHE_SECONDS + 1
    ensure_within_cap("GE", clock=lambda: now[0], read=read)
    assert seen == ["GE", "GE"]


def test_сбой_базы_вызов_не_останавливает_и_уходит_в_журнал(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from src.db.errors import DbError

    def broken(_tenant: str) -> Spend:
        raise DbError("нет базы")

    with caplog.at_level("WARNING"):
        ensure_within_cap("GE", read=broken)
    assert "потолок расхода модели не сверен" in caplog.text


def test_отказ_говорит_по_русски_и_по_английски_и_подходит_двери_голоса_и_текста() -> None:
    assert "Месячный лимит расхода пространства исчерпан" in MODEL_LIMIT_MESSAGE
    assert "monthly spending limit has been reached" in MODEL_LIMIT_MESSAGE
    from src.recognize.errors import TranscriptionFailed

    assert issubclass(ModelLimitReached, ModelUnavailable)
    assert issubclass(ModelLimitReached, TranscriptionFailed)


# --- до платного вызова дело не доходит -------------------------------------------


def _settings() -> RecognizeSettings:
    return RecognizeSettings(
        model="gpt-5.6-sol",
        transcribe_model="gpt-4o-mini-transcribe",
        api_key="sk-test",
        timeout=90.0,
        min_confidence=0.6,
        max_candidates=5,
        ffmpeg="ffmpeg",
    )


def test_достигнутый_потолок_не_пускает_запрос_к_провайдеру(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ушло: list[str] = []
    monkeypatch.setattr(
        spend_cap, "month_spend", lambda t: Spend(Decimal("50"), False, Decimal("50"))
    )
    monkeypatch.setattr(
        "src.recognize.client._new_client", lambda _s: ушло.append("клиент") or object()
    )

    with usage_scope(tenant="GE"), pytest.raises(ModelLimitReached):
        ask_model(
            kind="recognize",
            instructions="i",
            question="q",
            schema={"type": "object", "properties": {}, "required": []},
            photo=None,
            settings=_settings(),
        )

    assert ушло == []


def test_достигнутый_потолок_не_пускает_голос_ни_к_перекодировке_ни_к_провайдеру(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ушло: list[str] = []
    monkeypatch.setattr(
        spend_cap, "month_spend", lambda t: Spend(Decimal("50"), False, Decimal("50"))
    )
    monkeypatch.setattr(
        "src.recognize.transcribe._reencode", lambda a, f: ушло.append("ffmpeg") or b"wav"
    )
    monkeypatch.setattr(
        "src.recognize.transcribe.OpenAI", lambda **_k: ушло.append("клиент") or object()
    )

    with usage_scope(tenant="GE"), pytest.raises(ModelLimitReached):
        transcribe(b"voice", settings=_settings())

    assert ушло == []
