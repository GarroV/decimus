"""Расход модели (D537): учёт вызова, контекст двери, цена, запись без права ронять.

Ядро — то, что даёт цифры для денег: оценка стоимости и то, что каждый вызов
провайдера попадает в учёт с верным видом, моделью и токенами. Сеть и база не
участвуют: провайдер и соединение подменены; настоящая запись в базу и функция
чтения — в `tests/test_db_model_usage.py` (нужна живая база).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import pytest
from openai import OpenAIError
from openai.types.audio import Transcription

from src.db import model_usage
from src.db.errors import DbError
from src.domain.model_usage import (
    KIND_MERGE,
    KIND_OTHER,
    KIND_RECOGNIZE,
    KIND_SUGGEST,
    KIND_TRANSCRIBE,
    KIND_TRANSLATE,
    ModelCall,
    UsageScope,
    build_call,
    current_scope,
    resolve_kind,
    usage_scope,
)
from src.recognize.client import ask_model
from src.recognize.config import RecognizeSettings
from src.recognize.errors import ModelUnavailable
from src.recognize.pricing import Price, estimate_cost, load_prices
from src.recognize.transcribe import transcribe

#: Настоящая запись: автоподмена в conftest снимается уже после импорта этого модуля.
_REAL_RECORD = model_usage.record

_SCHEMA = {"type": "object", "properties": {}, "required": []}
_PRICES = {
    "m": Price(input_per_1m=2.0, output_per_1m=10.0),
    "audio": Price(audio_per_minute=0.006),
    "no-out": Price(input_per_1m=1.0),
}


# --- виды вызова и контекст двери ---------------------------------------------


@pytest.mark.parametrize(
    ("call_kind", "scope_kind", "want"),
    [
        (KIND_RECOGNIZE, None, KIND_RECOGNIZE),
        (KIND_RECOGNIZE, KIND_SUGGEST, KIND_SUGGEST),
        # Дверь уточняет только распознавание: перевод остаётся переводом.
        (KIND_TRANSLATE, KIND_SUGGEST, KIND_TRANSLATE),
        (KIND_MERGE, KIND_SUGGEST, KIND_MERGE),
        # Незнакомый код не роняет учёт.
        ("новый-вид", None, KIND_OTHER),
    ],
)
def test_вид_вызова_уточняется_только_для_распознавания(
    call_kind: str, scope_kind: str | None, want: str
) -> None:
    assert resolve_kind(call_kind, UsageScope(kind=scope_kind)) == want


def test_контекст_вложенный_дополняет_внешний_и_снимается() -> None:
    assert current_scope() == UsageScope()
    with usage_scope(user_id="u1", tenant="HQ"):
        with usage_scope(inspection_ref="run-1", telegram_id=7):
            inner = current_scope()
        outer = current_scope()
    assert inner == UsageScope(user_id="u1", telegram_id=7, tenant="HQ", inspection_ref="run-1")
    assert outer == UsageScope(user_id="u1", tenant="HQ")
    assert current_scope() == UsageScope()


def test_запись_учёта_берёт_кто_и_где_из_контекста() -> None:
    with usage_scope(user_id="u1", telegram_id=5, tenant="HQ", inspection_ref="r"):
        call = build_call(KIND_TRANSLATE, "m", ok=True, input_tokens=3, output_tokens=4)
    assert call == ModelCall(
        kind=KIND_TRANSLATE,
        model="m",
        ok=True,
        input_tokens=3,
        output_tokens=4,
        user_id="u1",
        telegram_id=5,
        tenant="HQ",
        inspection_ref="r",
    )


# --- цена ---------------------------------------------------------------------


def test_стоимость_токенов_по_цене_за_миллион() -> None:
    cost = estimate_cost("m", input_tokens=500_000, output_tokens=100_000, prices=_PRICES)
    assert cost == pytest.approx(0.5 * 2.0 + 0.1 * 10.0)


def test_стоимость_звука_по_минутам() -> None:
    cost = estimate_cost("audio", input_tokens=0, output_tokens=0, audio_seconds=90, prices=_PRICES)
    assert cost == pytest.approx(1.5 * 0.006)


def test_неизвестная_модель_или_нехватка_цены_это_none_а_не_ноль() -> None:
    assert estimate_cost("нет-такой", input_tokens=1, output_tokens=1, prices=_PRICES) is None
    # Расход на выходе есть, цены выхода нет — частичная сумма выдала бы себя за полную.
    assert estimate_cost("no-out", input_tokens=10, output_tokens=10, prices=_PRICES) is None
    assert (
        estimate_cost("m", input_tokens=0, output_tokens=0, audio_seconds=5, prices=_PRICES) is None
    )


def test_без_расхода_стоимость_ноль_даже_без_цены_выхода() -> None:
    assert estimate_cost("no-out", input_tokens=0, output_tokens=0, prices=_PRICES) == 0.0


def test_файл_цен_читается_и_держит_настроенные_модели() -> None:
    from src.recognize.config import DEFAULT_MERGE_MODEL, DEFAULT_MODEL, DEFAULT_TRANSCRIBE_MODEL

    prices = load_prices()
    for name in (DEFAULT_MODEL, DEFAULT_MERGE_MODEL, DEFAULT_TRANSCRIBE_MODEL):
        assert name in prices, f"у настроенной модели {name} нет цены в model_prices.json"


# --- запись не вправе ронять вызов ---------------------------------------------


@dataclass
class _Cursor:
    executed: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def execute(self, sql: str, params: dict[str, Any]) -> None:
        self.executed.append((sql, params))

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *_: object) -> None:
        return None


@dataclass
class _Conn:
    cur: _Cursor

    def cursor(self) -> _Cursor:
        return self.cur

    def __enter__(self) -> _Conn:
        return self

    def __exit__(self, *_: object) -> None:
        return None


def test_запись_кладёт_строку_с_полями_вызова(monkeypatch: pytest.MonkeyPatch) -> None:
    cur = _Cursor()
    monkeypatch.setattr(model_usage, "_connected", lambda _why: _Conn(cur))
    _REAL_RECORD(
        ModelCall(
            kind=KIND_RECOGNIZE,
            model="gpt-x",
            ok=False,
            input_tokens=11,
            output_tokens=2,
            telegram_id=9,
            tenant="HQ",
            inspection_ref="r",
        )
    )
    ((sql, params),) = cur.executed
    assert "insert into model_usage" in sql
    assert params["kind"] == "recognize"
    assert (params["input"], params["output"], params["ok"]) == (11, 2, False)
    assert (params["telegram"], params["tenant"], params["inspection"]) == (9, "HQ", "r")


@pytest.mark.parametrize("error", [DbError("база лежит"), RuntimeError("что угодно")])
def test_сбой_записи_уходит_в_журнал_и_не_поднимается(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, error: Exception
) -> None:
    def broken(_why: str) -> Any:
        raise error

    monkeypatch.setattr(model_usage, "_connected", broken)
    with caplog.at_level(logging.ERROR):
        _REAL_RECORD(ModelCall(kind=KIND_RECOGNIZE, model="m", ok=True))
    assert "запись не прошла" in caplog.text


# --- единственная точка вызова провайдера учитывает каждый вызов ----------------


@dataclass
class _Usage:
    input_tokens: int
    output_tokens: int


@dataclass
class _Response:
    output_text: str
    usage: _Usage | None = None
    status: str = "completed"


@dataclass
class _Responses:
    answer: _Response | None = None
    error: Exception | None = None

    def create(self, **_: Any) -> _Response:
        if self.error is not None:
            raise self.error
        assert self.answer is not None
        return self.answer


@dataclass
class _Client:
    responses: _Responses


def _settings(**over: Any) -> RecognizeSettings:
    base: dict[str, Any] = dict(
        model="gpt-5.6-sol",
        transcribe_model="gpt-4o-mini-transcribe",
        api_key="sk-test",
        timeout=90.0,
        min_confidence=0.6,
        max_candidates=5,
        ffmpeg="ffmpeg",
    )
    base.update(over)
    return RecognizeSettings(**base)


def _ask(monkeypatch: pytest.MonkeyPatch, responses: _Responses, **kw: Any) -> Any:
    monkeypatch.setattr("src.recognize.client._new_client", lambda _s: _Client(responses))
    return ask_model(
        instructions="i", question="q", schema=_SCHEMA, photo=None, settings=_settings(), **kw
    )


def test_удавшийся_вызов_учтён_с_токенами_видом_и_моделью(
    monkeypatch: pytest.MonkeyPatch, model_usage_calls: list[ModelCall]
) -> None:
    ok = _Responses(answer=_Response("{}", _Usage(100, 20)))
    with usage_scope(user_id="u1", tenant="HQ"):
        _ask(monkeypatch, ok, kind=KIND_TRANSLATE, model="gpt-6-luna")
    (call,) = model_usage_calls
    assert (call.kind, call.model, call.ok) == (KIND_TRANSLATE, "gpt-6-luna", True)
    assert (call.input_tokens, call.output_tokens) == (100, 20)
    assert (call.user_id, call.tenant) == ("u1", "HQ")


def test_подбор_на_экране_учитывается_как_suggest(
    monkeypatch: pytest.MonkeyPatch, model_usage_calls: list[ModelCall]
) -> None:
    ok = _Responses(answer=_Response("{}", _Usage(1, 1)))
    with usage_scope(kind=KIND_SUGGEST):
        _ask(monkeypatch, ok, kind=KIND_RECOGNIZE)
    assert model_usage_calls[0].kind == KIND_SUGGEST


@pytest.mark.parametrize(
    "responses",
    [
        _Responses(error=OpenAIError("лимит")),
        _Responses(answer=_Response("не json", _Usage(5, 6))),
        _Responses(answer=_Response("[]", _Usage(5, 6))),
        _Responses(answer=_Response("{}", _Usage(5, 6), status="incomplete")),
    ],
)
def test_неудавшийся_вызов_тоже_учтён_как_неуспешный(
    monkeypatch: pytest.MonkeyPatch, model_usage_calls: list[ModelCall], responses: _Responses
) -> None:
    with pytest.raises(ModelUnavailable):
        _ask(monkeypatch, responses, kind=KIND_RECOGNIZE)
    (call,) = model_usage_calls
    assert call.ok is False


def test_отказ_до_обращения_к_провайдеру_не_учитывается(
    model_usage_calls: list[ModelCall],
) -> None:
    with pytest.raises(ModelUnavailable):
        ask_model(
            kind=KIND_RECOGNIZE,
            instructions="i",
            question="q",
            schema=_SCHEMA,
            photo=None,
            settings=_settings(api_key=""),
        )
    assert model_usage_calls == []


def test_вид_вызова_обязателен() -> None:
    with pytest.raises(TypeError):
        ask_model(  # type: ignore[call-arg]
            instructions="i", question="q", schema=_SCHEMA, photo=None, settings=_settings()
        )


def test_расшифровка_учитывается_с_токенами_или_секундами(
    monkeypatch: pytest.MonkeyPatch, model_usage_calls: list[ModelCall]
) -> None:
    class _Transcriptions:
        def __init__(self, result: Any) -> None:
            self.result = result

        def create(self, **_: Any) -> Any:
            return self.result

    def patch(result: Any) -> None:
        client = type(
            "C", (), {"audio": type("A", (), {"transcriptions": _Transcriptions(result)})}
        )
        monkeypatch.setattr("src.recognize.transcribe.OpenAI", lambda **_kw: client)

    monkeypatch.setattr("src.recognize.transcribe._reencode", lambda audio, ffmpeg: b"wav")
    with_tokens = Transcription.model_validate(
        {
            "text": "привет",
            "usage": {"type": "tokens", "input_tokens": 40, "output_tokens": 6, "total_tokens": 46},
        }
    )
    with_seconds = Transcription.model_validate(
        {"text": "привет", "usage": {"type": "duration", "seconds": 12}}
    )
    patch(with_tokens)
    transcribe(b"a", settings=_settings())
    patch(with_seconds)
    transcribe(b"a", settings=_settings())
    first, second = model_usage_calls
    assert (first.kind, first.input_tokens, first.output_tokens) == (KIND_TRANSCRIBE, 40, 6)
    assert (second.input_tokens, second.audio_seconds) == (None, 12.0)
    assert first.model == "gpt-4o-mini-transcribe"


def test_проверка_чата_бота_называется_пиццерией_и_датой(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from src.bot import usage as bot_usage

    state = SimpleNamespace(run_id="run-9", unit="Тбилиси-1", date="2026-10-02")
    monkeypatch.setattr(bot_usage, "get_state", lambda _chat: state)

    with bot_usage.chat_usage(5):
        scope = current_scope()

    assert (scope.inspection_ref, scope.inspection_label) == ("run-9", "Тбилиси-1 · 2026-10-02")
    # Проверка, названная выше (веб знает номер в базе), не перетирается.
    with usage_scope(inspection_ref="uuid-1"), bot_usage.chat_usage(5):
        assert current_scope().inspection_ref == "uuid-1"


def test_состояние_чата_не_читается_вызов_идёт_без_проверки(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.bot import usage as bot_usage

    def broken(_chat: int) -> None:
        raise OSError("диск")

    monkeypatch.setattr(bot_usage, "get_state", broken)
    with bot_usage.chat_usage(5):
        assert current_scope().inspection_ref is None
