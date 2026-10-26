"""T031: единственная точка вызова провайдера — `client.ask_model`.

`_new_client` — «шов, которым тесты подменяют вызов» (см. докстринг модуля):
здесь он подменяется на фальшивый клиент, у которого `.responses.create`
возвращает заранее заданный ответ или бросает ошибку. Сеть в тестах не
участвует ни разу — это отдельная (дорогая, оплачиваемая) проверка вручную.

Любой отказ провайдера — сеть, испорченный JSON, ответ не-объектом — обязан
превращаться в `ModelUnavailable`: контракт блока требует, чтобы недоступная
модель не роняла проверку, а уводила бота на ручной выбор кнопками.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from openai import OpenAIError

from src.recognize.client import MAX_OUTPUT_TOKENS, ask_model
from src.recognize.config import RecognizeSettings
from src.recognize.errors import ModelUnavailable

_SCHEMA = {"type": "object", "properties": {}, "required": []}


def _settings(**overrides: Any) -> RecognizeSettings:
    base = dict(
        model="gpt-5.6-sol",
        transcribe_model="gpt-4o-mini-transcribe",
        api_key="sk-test",
        timeout=90.0,
        min_confidence=0.6,
        max_candidates=5,
        ffmpeg="ffmpeg",
    )
    base.update(overrides)
    return RecognizeSettings(**base)


@dataclass
class _FakeUsage:
    input_tokens: int
    output_tokens: int


@dataclass
class _FakeResponse:
    output_text: str
    usage: _FakeUsage | None = None
    status: str = "completed"


@dataclass
class _FakeResponses:
    """Подменяет `client.responses`. `calls` копит переданные аргументы для проверки."""

    answer: _FakeResponse | None = None
    error: Exception | None = None
    calls: list[dict[str, Any]] = field(default_factory=list)

    def create(self, **kwargs: Any) -> _FakeResponse:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        assert self.answer is not None
        return self.answer


@dataclass
class _FakeClient:
    responses: _FakeResponses


class _FakeProviderError(OpenAIError):
    """Любой отказ провайдера — сеть, ключ, лимит — это подкласс `OpenAIError`."""


def _patch_client(monkeypatch: pytest.MonkeyPatch, fake: _FakeClient) -> None:
    monkeypatch.setattr("src.recognize.client._new_client", lambda settings: fake)


def test_ключ_не_задан_даёт_отказ_без_обращения_к_сети() -> None:
    # Act / Assert: `_new_client` не подменён — значит дошли бы до настоящего
    # OpenAI-клиента, если бы отказ не случился раньше.
    with pytest.raises(ModelUnavailable, match="OPENAI_API_KEY"):
        ask_model(
            kind="recognize",
            instructions="сис",
            question="вопрос",
            schema=_SCHEMA,
            photo=None,
            settings=_settings(api_key=""),
        )


def test_успешный_ответ_разбирается_и_расход_возвращается(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    fake_responses = _FakeResponses(
        answer=_FakeResponse(
            output_text='{"records": [], "question": ""}',
            usage=_FakeUsage(input_tokens=100, output_tokens=20),
        )
    )
    _patch_client(monkeypatch, _FakeClient(responses=fake_responses))

    # Act
    answer = ask_model(
        kind="recognize",
        instructions="сис",
        question="вопрос",
        schema=_SCHEMA,
        photo=None,
        settings=_settings(),
    )

    # Assert
    assert answer.payload == {"records": [], "question": ""}
    assert answer.usage == {"input": 100, "output": 20}


def test_usage_отсутствует_даёт_пустой_словарь(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    fake_responses = _FakeResponses(
        answer=_FakeResponse(output_text='{"records": [], "question": ""}', usage=None)
    )
    _patch_client(monkeypatch, _FakeClient(responses=fake_responses))

    # Act
    answer = ask_model(
        kind="recognize",
        instructions="сис",
        question="вопрос",
        schema=_SCHEMA,
        photo=None,
        settings=_settings(),
    )

    # Assert
    assert answer.usage == {}


def test_кадр_передан_только_когда_есть_photo(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    fake_responses = _FakeResponses(
        answer=_FakeResponse(output_text='{"records": [], "question": ""}')
    )
    _patch_client(monkeypatch, _FakeClient(responses=fake_responses))

    # Act: без фото
    ask_model(
        kind="recognize",
        instructions="сис",
        question="вопрос",
        schema=_SCHEMA,
        photo=None,
        settings=_settings(),
    )
    # Act: с фото
    ask_model(
        kind="recognize",
        instructions="сис",
        question="вопрос",
        schema=_SCHEMA,
        photo=b"jpeg",
        settings=_settings(),
    )

    # Assert
    без_фото, с_фото = fake_responses.calls
    assert len(без_фото["input"][0]["content"]) == 1, "без фото — только текст"
    assert len(с_фото["input"][0]["content"]) == 2, "с фото — текст и кадр"
    assert с_фото["input"][0]["content"][1]["type"] == "input_image"


def test_model_из_аргумента_перекрывает_настройки(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange: T035 гоняет один и тот же запрос по нескольким моделям
    fake_responses = _FakeResponses(
        answer=_FakeResponse(output_text='{"records": [], "question": ""}')
    )
    _patch_client(monkeypatch, _FakeClient(responses=fake_responses))

    # Act
    ask_model(
        kind="recognize",
        instructions="сис",
        question="вопрос",
        schema=_SCHEMA,
        photo=None,
        settings=_settings(model="gpt-5.6-sol"),
        model="gpt-4o-mini",
    )

    # Assert
    assert fake_responses.calls[0]["model"] == "gpt-4o-mini"
    # Кадры и записи у OpenAI не хранятся: без этого Responses держит их у себя.
    assert fake_responses.calls[0]["store"] is False
    # Потолок выхода стоит на каждом разборе (#784).
    assert fake_responses.calls[0]["max_output_tokens"] == MAX_OUTPUT_TOKENS


def test_отказ_провайдера_это_ModelUnavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    fake_responses = _FakeResponses(error=_FakeProviderError("лимит запросов"))
    _patch_client(monkeypatch, _FakeClient(responses=fake_responses))

    # Act / Assert
    with pytest.raises(ModelUnavailable, match="лимит запросов"):
        ask_model(
            kind="recognize",
            instructions="сис",
            question="вопрос",
            schema=_SCHEMA,
            photo=None,
            settings=_settings(),
        )


def test_испорченный_json_это_ModelUnavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    fake_responses = _FakeResponses(answer=_FakeResponse(output_text="не json{"))
    _patch_client(monkeypatch, _FakeClient(responses=fake_responses))

    # Act / Assert
    with pytest.raises(ModelUnavailable, match="строгая схема"):
        ask_model(
            kind="recognize",
            instructions="сис",
            question="вопрос",
            schema=_SCHEMA,
            photo=None,
            settings=_settings(),
        )


def test_ответ_не_объект_это_ModelUnavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange: строгая схема просила объект, а не список
    fake_responses = _FakeResponses(answer=_FakeResponse(output_text="[]"))
    _patch_client(monkeypatch, _FakeClient(responses=fake_responses))

    # Act / Assert
    with pytest.raises(ModelUnavailable, match="не объект"):
        ask_model(
            kind="recognize",
            instructions="сис",
            question="вопрос",
            schema=_SCHEMA,
            photo=None,
            settings=_settings(),
        )


def test_обрезанный_потолком_ответ_это_ModelUnavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange: модель упёрлась в потолок выхода (#784) — ответ неполный
    fake_responses = _FakeResponses(
        answer=_FakeResponse(output_text='{"records": [', status="incomplete")
    )
    _patch_client(monkeypatch, _FakeClient(responses=fake_responses))

    # Act / Assert
    with pytest.raises(ModelUnavailable, match="обрезан"):
        ask_model(
            kind="recognize",
            instructions="сис",
            question="вопрос",
            schema=_SCHEMA,
            photo=None,
            settings=_settings(),
        )


# --- #1267 (D646): глубина рассуждения и точка кэша -------------------------------


def _ask(
    monkeypatch: pytest.MonkeyPatch,
    *,
    settings: RecognizeSettings,
    kind: str = "recognize",
    model: str | None = None,
    cached_prefix: str = "",
    question: str = "ПОСТОЯННОЕ\n\nМЕНЯЮЩЕЕСЯ",
) -> dict[str, Any]:
    fake = _FakeResponses(answer=_FakeResponse(output_text="{}", usage=_FakeUsage(10, 2)))
    _patch_client(monkeypatch, _FakeClient(responses=fake))
    ask_model(
        kind=kind,
        instructions="сис",
        question=question,
        schema=_SCHEMA,
        photo=None,
        settings=settings,
        model=model,
        cached_prefix=cached_prefix,
    )
    return fake.calls[0]


def test_глубина_рассуждения_уходит_только_у_разбора_на_модели_из_настроек(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    настройки = _settings(reasoning_effort="low")

    разбор = _ask(monkeypatch, settings=настройки)
    сведение = _ask(monkeypatch, settings=настройки, kind="merge")
    чужая_модель = _ask(monkeypatch, settings=настройки, model="gpt-4o-mini")

    assert разбор["reasoning"] == {"effort": "low"}
    assert "reasoning" not in сведение, "глубина разбора ушла в сведение комментария"
    assert "reasoning" not in чужая_модель, "глубина разбора ушла на другую модель"


def test_пустая_глубина_параметр_не_передаёт(monkeypatch: pytest.MonkeyPatch) -> None:
    вызов = _ask(monkeypatch, settings=_settings(reasoning_effort=""))

    assert "reasoning" not in вызов


def test_за_постоянной_частью_вопроса_стоит_явная_точка_кэша(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    вызов = _ask(monkeypatch, settings=_settings(), cached_prefix="ПОСТОЯННОЕ")

    части = вызов["input"][0]["content"]
    assert части[0]["text"] == "ПОСТОЯННОЕ"
    assert части[0]["prompt_cache_breakpoint"] == {"mode": "explicit"}
    assert части[1]["text"] == "\n\nМЕНЯЮЩЕЕСЯ"
    assert "prompt_cache_breakpoint" not in части[1]
    assert вызов["extra_body"] == {"prompt_cache_options": {"mode": "explicit"}}


def test_без_постоянной_части_и_на_чужой_модели_точки_кэша_нет(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    без_части = _ask(monkeypatch, settings=_settings())
    чужая = _ask(monkeypatch, settings=_settings(), model="gpt-4o-mini", cached_prefix="ПОСТОЯННОЕ")

    for вызов in (без_части, чужая):
        assert "extra_body" not in вызов
        assert len(вызов["input"][0]["content"]) == 1
        assert "prompt_cache_breakpoint" not in вызов["input"][0]["content"][0]


def test_кэш_и_рассуждение_попадают_в_расход_ответа(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    usage = SimpleNamespace(
        input_tokens=100,
        output_tokens=20,
        input_tokens_details=SimpleNamespace(cached_tokens=64, cache_write_tokens=0),
        output_tokens_details=SimpleNamespace(reasoning_tokens=7),
    )
    fake = _FakeResponses(answer=_FakeResponse(output_text="{}", usage=usage))  # type: ignore[arg-type]
    _patch_client(monkeypatch, _FakeClient(responses=fake))

    answer = ask_model(
        kind="recognize",
        instructions="с",
        question="в",
        schema=_SCHEMA,
        photo=None,
        settings=_settings(),
    )

    assert answer.usage == {
        "input": 100,
        "output": 20,
        "cached": 64,
        "reasoning": 7,
        "cache_write": 0,
    }


def test_глубина_рассуждения_из_окружения() -> None:
    from src.recognize.config import RecognizeConfigError, load_recognize_settings

    def глубина(значение: str | None) -> str:
        env = {} if значение is None else {"RECOGNIZE_REASONING_EFFORT": значение}
        return load_recognize_settings(env).reasoning_effort

    assert глубина(None) == "low", "умолчание — то, что выиграл замер"
    assert глубина("medium") == "medium"
    assert глубина("default") == "", "default — не передавать параметр вовсе"
    with pytest.raises(RecognizeConfigError, match="RECOGNIZE_REASONING_EFFORT"):
        глубина("быстро")
