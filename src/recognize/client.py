"""T031: единственное место, где блок разговаривает с провайдером модели.

Решение D010: «вызов изолируется за одной функцией, чтобы смена провайдера была
правкой конфига». Поэтому `openai` импортируется только здесь; всё остальное в
блоке работает со словарями и знать про провайдера не обязано.

Любой отказ — сеть, ключ, лимит, таймаут, испорченный JSON — превращается в
`ModelUnavailable`. Проверку это не роняет: бот уходит на ручной выбор пункта
кнопками (задача T034).
"""

from __future__ import annotations

import base64
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from openai import AuthenticationError, OpenAI, OpenAIError, PermissionDeniedError
from openai.types.responses import (
    EasyInputMessageParam,
    ResponseInputImageParam,
    ResponseInputMessageContentListParam,
    ResponseInputTextParam,
    ResponseTextConfigParam,
)
from openai.types.responses.response_format_text_json_schema_config_param import (
    ResponseFormatTextJSONSchemaConfigParam,
)

from src.db import model_usage
from src.domain.model_usage import build_call

from .config import RecognizeSettings
from .errors import ModelKeyRejected, ModelUnavailable

#: Имя схемы в запросе. Провайдеру оно нужно, на содержание не влияет.
SCHEMA_NAME = "audit_suggestions"

#: Кадр отдаётся провайдеру как есть, разрешение выбирает он сам. Замер на
#: боевом кадре: `detail=low` на флагмане стоит 315 токенов входа против 1463 у
#: `auto`, но срезает ровно ту мелочь, ради которой кадр и смотрят, — нагар под
#: лентой печи от целого металла отличается на увеличении.
IMAGE_DETAIL: Literal["auto"] = "auto"


@dataclass(frozen=True)
class ModelAnswer:
    """Разобранный ответ модели и расход на запрос."""

    payload: dict[str, Any]
    usage: dict[str, int] = field(default_factory=dict)


def _new_client(settings: RecognizeSettings) -> OpenAI:
    """Клиент провайдера. Отдельная функция — шов, которым тесты подменяют вызов."""
    if not settings.api_key:
        raise ModelUnavailable(
            "Не задан ключ модели (экран «Подключения» или OPENAI_API_KEY). "
            "Разбор комментариев не работает, "
            "проверка продолжается ручным выбором пункта"
        )
    return OpenAI(api_key=settings.api_key, timeout=settings.timeout)


#: Проверка ключа — один дешёвый вызов (перечень моделей), без повторов.
VERIFY_TIMEOUT = 15.0

#: Потолок выхода одного разбора, токенов, вместе с рассуждением модели (#784).
#: Ответ по схеме — десятки токенов (замер #221: 64), рассуждение — сотни;
#: потолок с запасом на порядок и только против разгона стоимости. Упёрся —
#: ответ обрезан и отказ, а не полуразобранный JSON.
MAX_OUTPUT_TOKENS = 8000


def verify_key(api_key: str) -> None:
    """Один вызов провайдера с этим ключом: принят — тихо, иначе отказ.

    `ModelKeyRejected` — провайдер ключ не принял; `ModelUnavailable` — проверить не удалось
    (сеть, лимит, сбой провайдера). Ни ключа, ни текста ответа провайдера в отказе нет.
    """
    client = OpenAI(api_key=api_key, timeout=VERIFY_TIMEOUT, max_retries=0)
    try:
        client.models.list()
    except (AuthenticationError, PermissionDeniedError) as exc:
        raise ModelKeyRejected("Провайдер не принял ключ модели") from exc
    except OpenAIError as exc:
        raise ModelUnavailable(f"Не удалось проверить ключ модели ({type(exc).__name__})") from exc


def _content(question: str, photos: Sequence[bytes]) -> ResponseInputMessageContentListParam:
    content: ResponseInputMessageContentListParam = [
        ResponseInputTextParam(type="input_text", text=question)
    ]
    for photo in photos:
        encoded = base64.b64encode(photo).decode("ascii")
        content.append(
            ResponseInputImageParam(
                type="input_image",
                image_url=f"data:image/jpeg;base64,{encoded}",
                detail=IMAGE_DETAIL,
            )
        )
    return content


def _note(kind: str, model: str, usage: dict[str, int], *, ok: bool) -> None:
    """Учесть вызов (D537). Сбой учёта в журнал процесса, ответ человеку он не меняет."""
    model_usage.record(
        build_call(
            kind,
            model,
            ok=ok,
            input_tokens=usage.get("input"),
            output_tokens=usage.get("output"),
        )
    )


def ask_model(
    *,
    kind: str,
    instructions: str,
    question: str,
    schema: dict[str, Any],
    photo: bytes | None,
    settings: RecognizeSettings,
    model: str | None = None,
    photos: Sequence[bytes] = (),
) -> ModelAnswer:
    """Спросить модель со строгой схемой ответа. Кадр уходит тем же запросом.

    `photos` — кадры пачки с комментарием (D208): уходят все, тем же запросом и
    в порядке съёмки. `photo` — одиночный кадр, как было; вместе их не передают.

    `model` перекрывает имя из настроек — это нужно замеру точности (T035),
    который гоняет один и тот же запрос по нескольким моделям. В работе бота
    имя берётся из конфига и никогда из кода.

    `kind` — вид вызова для учёта расхода (D537, коды — `domain.model_usage`): обязателен,
    чтобы новое место вызова не могло про учёт забыть. Каждый ушедший к провайдеру запрос
    пишется строкой в `model_usage` — и удавшийся, и отказанный.
    """
    client = _new_client(settings)
    text_format = ResponseFormatTextJSONSchemaConfigParam(
        type="json_schema",
        name=SCHEMA_NAME,
        schema=schema,
        strict=True,
    )
    text_config: ResponseTextConfigParam = {"format": text_format}
    message: EasyInputMessageParam = {
        "role": "user",
        "content": _content(question, (photo,) if photo is not None else tuple(photos)),
    }
    used_model = model or settings.model
    try:
        response = client.responses.create(
            model=used_model,
            instructions=instructions,
            input=[message],
            text=text_config,
            # Кадры кухни (на них бывают лица) и записи не оставляем у OpenAI:
            # без `store=False` Responses хранит запрос и ответ у себя. Цепочек
            # ответов (`previous_response_id`) у нас нет, хранить незачем.
            store=False,
            max_output_tokens=MAX_OUTPUT_TOKENS,
        )
    except OpenAIError as exc:
        _note(kind, used_model, {}, ok=False)
        raise ModelUnavailable(f"Модель не ответила: {exc}") from exc
    raw_usage = response.usage
    usage = (
        {}
        if raw_usage is None
        else {"input": raw_usage.input_tokens, "output": raw_usage.output_tokens}
    )
    if getattr(response, "status", None) == "incomplete":
        _note(kind, used_model, usage, ok=False)
        raise ModelUnavailable(
            f"Ответ модели обрезан потолком в {MAX_OUTPUT_TOKENS} токенов — разбор не принят"
        )

    raw = response.output_text
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        _note(kind, used_model, usage, ok=False)
        raise ModelUnavailable(
            f"Ответ модели не разобран как JSON, хотя запрошена строгая схема: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        _note(kind, used_model, usage, ok=False)
        raise ModelUnavailable("Ответ модели — не объект, хотя запрошена строгая схема")

    _note(kind, used_model, usage, ok=True)
    return ModelAnswer(payload=payload, usage=usage)
