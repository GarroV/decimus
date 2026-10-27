"""Прожектор на недоверенный текст в ответах MCP (#1338; образец — Swarm `untrusted.ts`).

Текст людей — в замечаниях, названиях, письмах, именах — доходит до модели
через ответ ЛЮБОГО инструмента. Поэтому каждый текст результата `tools/call`
оборачивается в блок `<untrusted_data id="…" source="…">…</untrusted_data id="…">`.
Граница блока — случайный одноразовый id, который рождается ПОСЛЕ того, как
данные прочитаны: содержимое не может его знать и закрыть блок изнутри не
может, как бы ни был записан подделанный тег. Обезвреживание подделок — второй
слой, не граница. Правило для модели лежит в `instructions` сервера
(`instructions.GENERAL_INSTRUCTIONS`).

Оборачивает транспорт (`server._post`), а не `rpc.handle`: обработчики и их
тесты видят голый результат, а клиент — всегда обёрнутый. Отказ протокола
(`error`) обёртки не получает: в нём только имена аргументов, а не данные.
"""

from __future__ import annotations

import re
import secrets
from typing import Any

#: Невидимые символы внутри подделанного тега: пробельные, нулевой ширины, BOM.
_INVISIBLE = "\\s\\u200b-\\u200d\\u2060\\ufeff"
#: Тег в любом регистре, с пробелами и невидимыми символами внутри:
#: `< / UNTRUSTED_DATA`, `<​ untrusted_data`.
_FORGED_TAG = re.compile(
    rf"<([{_INVISIBLE}]*/?[{_INVISIBLE}]*untrusted[{_INVISIBLE}_-]*data)", re.IGNORECASE
)
_SOURCE_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")


def neutralise_untrusted(text: str) -> str:
    """Меняет «<» подделанных тегов `untrusted_data` на «‹»: блок изнутри не закрыть."""
    return _FORGED_TAG.sub(r"‹\1", text)


def block_nonce() -> str:
    """Случайный id блока: 16 байт, hex."""
    return secrets.token_hex(16)


def wrap_untrusted(source: str, text: str) -> str:
    """Текст результата инструмента `source` в блоке недоверенных данных с новым id."""
    safe_source = _SOURCE_UNSAFE.sub("", source)
    nonce = block_nonce()
    # Совпадение id с текстом невероятно, но тогда граница не была бы уникальной.
    while nonce in text:
        nonce = block_nonce()
    return (
        f'<untrusted_data id="{nonce}" source="{safe_source}">\n'
        f"{neutralise_untrusted(text)}\n"
        f'</untrusted_data id="{nonce}">'
    )


def wrap_call_result(message: object, answer: dict[str, Any] | None) -> dict[str, Any] | None:
    """Ответ на `tools/call`: каждый текстовый блок результата — в `wrap_untrusted`.

    Другие методы и отказы протокола возвращаются как есть. Исходный ответ не
    меняется: возвращается копия.
    """
    if answer is None or not isinstance(message, dict) or message.get("method") != "tools/call":
        return answer
    result = answer.get("result")
    if not isinstance(result, dict) or not isinstance(result.get("content"), list):
        return answer
    params = message.get("params")
    name = params.get("name") if isinstance(params, dict) else None
    source = name if isinstance(name, str) else ""
    content = [
        {**block, "text": wrap_untrusted(source, block["text"])}
        if isinstance(block, dict) and isinstance(block.get("text"), str)
        else block
        for block in result["content"]
    ]
    return {**answer, "result": {**result, "content": content}}
