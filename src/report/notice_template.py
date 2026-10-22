"""Шаблон предписания: текст с подстановками и его разметка в HTML (D601, шаг 3 спеки 2026-10-21).

Документ — английский всегда (D601). Шаблон — обычный текст: абзацы через пустую
строку, `# ` в начале абзаца — заголовок, строка `---` — новая страница. Подстановки
`{{имя}}`. Три из них — блоки (`{{visits_table}}`, `{{findings_table}}`, `{{appendix}}`):
стоят в абзаце одни и разворачиваются таблицей или приложением. Остальные
подставляются в текст.

**Встроенный шаблон обезличен.** Реальные юрлицо, адрес, регистрационный номер и
номера пунктов договора в репозитории не лежат (он публичный): вместо них явные
заглушки в квадратных скобках. Настоящий текст загружается в базу инструментом
`tools/prescription_template.py` и становится новой версией (`mail_templates`).

Подстановка идёт одним проходом по тексту шаблона: значение, в котором случайно
стоит `{{...}}`, повторно не разбирается. Неизвестная подстановка в шаблоне — отказ
сразу (`NoticeTemplateError`), а не пустое место в документе партнёра.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from html import escape

from .errors import ReportError

#: Подстановки, которые подставляются в текст.
INLINE_TOKENS = (
    "date",
    "country",
    "franchisee_name",
    "franchisee_block",
    "agreement",
    "due_on",
)
#: Подстановки-блоки: стоят в абзаце одни.
BLOCK_TOKENS = ("visits_table", "findings_table", "appendix")
KNOWN_TOKENS = frozenset(INLINE_TOKENS + BLOCK_TOKENS)

TOKEN = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
PAGE_BREAK = "---"
MAX_TEMPLATE = 100_000

#: Заглушка на месте сведений, которых нет в карточке страны: видна в превью ОСБ.
MISSING_AGREEMENT = "[Franchise Agreement: name and date]"
MISSING_FRANCHISEE = "[Franchisee legal name]"

#: Вид шаблона в `mail_templates` по виду предписания.
TEMPLATE_KIND = "prescription_inspection"
TEMPLATE_LANG = "en"

#: Сопроводительное письмо по умолчанию — тело письма с PDF во вложении.
DEFAULT_COVER = (
    "Dear colleagues,\n\n"
    "Please find attached the Notice of the Franchisor regarding the failures identified "
    "during the quality assurance audit of your restaurants/premises. The remedy terms "
    "are stated in the Notice."
)

BUILTIN_PRESCRIPTION_INSPECTION = """\
# [Franchisor legal name]

[Franchisor address]
Registration number: [Franchisor registration number]

# NOTICE

{{date}}

Franchisor: [Franchisor legal name], [Franchisor address], registration number [Franchisor registration number].

Franchisee:
{{franchisee_block}}

We entered into the {{agreement}} (the "Franchise Agreement").

In accordance with clause [clause] of the Franchise Agreement, the Franchisor is entitled to carry out quality assurance audits of the restaurants/premises operated by the Franchisee.

In accordance with clause [clause] of the Franchise Agreement, the Franchisee is obliged to remedy the failures identified during the audit within the term set by the Franchisor.

The Franchisor visited the following restaurants/premises:

{{visits_table}}

The following failures were identified:

{{findings_table}}

By this notice, the Franchisor requests that the Franchisee remedy the failure identified above by {{due_on}}, unless another term is stated in the table. The photographs are attached in Appendix 1.

[Signatory name and title]

Signature: ____________________

---

# Appendix 1

{{appendix}}
"""  # noqa: E501 — абзацы шаблона длинные, переносы строк в них стали бы переносами в документе


class NoticeTemplateError(ReportError):
    """Шаблон не годится: неизвестная подстановка, пустой или слишком длинный текст."""


def tokens_of(text: str) -> tuple[str, ...]:
    """Подстановки текста по порядку появления, без повторов."""
    return tuple(dict.fromkeys(m.group(1) for m in TOKEN.finditer(text)))


def check_template(text: str) -> str:
    """Текст шаблона, если он годится; иначе `NoticeTemplateError` с названием причины."""
    if not (text or "").strip():
        raise NoticeTemplateError("Текст шаблона пуст")
    if len(text) > MAX_TEMPLATE:
        raise NoticeTemplateError(f"Шаблон длиннее {MAX_TEMPLATE} знаков")
    unknown = [name for name in tokens_of(text) if name not in KNOWN_TOKENS]
    if unknown:
        raise NoticeTemplateError(
            f"В шаблоне неизвестные подстановки: {', '.join('{{' + n + '}}' for n in unknown)}. "
            f"Известные: {', '.join(sorted(KNOWN_TOKENS))}"
        )
    for name in BLOCK_TOKENS:
        for block in re.split(r"\n\s*\n", text):
            if name in tokens_of(block) and block.strip() != "{{" + name + "}}":
                raise NoticeTemplateError(
                    f"Подстановка {{{{{name}}}}} стоит в абзаце одна, без другого текста"
                )
    return text


def _inline(text: str, values: Mapping[str, str]) -> str:
    """Одним проходом: значения экранируются, переводы строк в них — `<br>`."""
    out: list[str] = []
    last = 0
    for found in TOKEN.finditer(text):
        out.append(escape(text[last : found.start()]))
        out.append(escape(values.get(found.group(1), "")).replace("\n", "<br>"))
        last = found.end()
    out.append(escape(text[last:]))
    return "".join(out).replace("\n", "<br>")


def render_body(text: str, *, values: Mapping[str, str], blocks: Mapping[str, str]) -> str:
    """HTML тела документа: абзацы шаблона с подставленными значениями и блоками."""
    check_template(text)
    parts: list[str] = []
    for raw in re.split(r"\n\s*\n", text.strip()):
        block = raw.strip()
        if not block:
            continue
        if block == PAGE_BREAK:
            parts.append('<div class="pagebreak"></div>')
            continue
        only = TOKEN.fullmatch(block)
        if only and only.group(1) in BLOCK_TOKENS:
            parts.append(blocks.get(only.group(1), ""))
        elif block.startswith("# "):
            parts.append(f"<h1>{_inline(block[2:], values)}</h1>")
        else:
            parts.append(f"<p>{_inline(block, values)}</p>")
    return "\n".join(parts)
