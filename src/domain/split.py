"""Human-confirmed split, staged through the existing engine and committed once."""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from .engine import DOMAIN_KEY, option, run_audit, state_file
from .errors import ValidationError
from .findings import _number, check_reading
from .handover import while_open
from .models import ADVICE_LEVEL, SOURCE_COMMENT, Finding
from .state import (
    READINGS_KEY,
    SOURCES_KEY,
    SUGGESTIONS_KEY,
    WORDS_KEY,
    _inspection,
    _read_raw,
    _write_atomic,
    settings_for,
    state_lock,
)
from .timing import utc_now

FINDING_HISTORY_KEY = "finding_history"


class SplitConflict(ValidationError):
    """The source changed, or an idempotency key was reused for another request."""


@dataclass(frozen=True)
class SplitPart:
    code: str
    level: str
    zone: str
    text: str
    comment: str = ""
    repeat: bool = False
    reading_c: float | None = None
    photos: tuple[str, ...] = ()


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def finding_revision(finding: Finding) -> str:
    return _digest(asdict(finding))


def _validate_parts(
    source: Finding, parts: Sequence[SplitPart], shared_photos: Sequence[str]
) -> None:
    if not 2 <= len(parts) <= 5:
        raise ValidationError("Разделение требует от двух до пяти частей")
    allocated: Counter[str] = Counter()
    for part in parts:
        for value in (part.code, part.level, part.zone, part.text):
            if not isinstance(value, str) or not value.strip() or len(value) > 4000:
                raise ValidationError("У каждой части нужны явные пункт, класс, зона и текст")
        if not isinstance(part.comment, str) or len(part.comment) > 4000:
            raise ValidationError("Некорректная рекомендация части")
        if not isinstance(part.repeat, bool):
            raise ValidationError("Повтор части должен быть явным выбором")
        check_reading(part.reading_c)
        if len(set(part.photos)) != len(part.photos):
            raise ValidationError("Кадр повторён внутри одной части")
        if any(ref not in source.photos for ref in part.photos):
            raise ValidationError("Разделять можно только существующие кадры исходной записи")
        if source.photos and part.level != ADVICE_LEVEL and not part.photos:
            raise ValidationError("К каждой части нарушения нужно явно назначить кадр")
        allocated.update(part.photos)
    if set(allocated) != set(source.photos):
        raise ValidationError("Нужно явно распределить все исходные кадры")
    shared = {ref for ref, count in allocated.items() if count > 1}
    if shared != set(shared_photos):
        raise ValidationError("Общий кадр требует отдельного явного подтверждения")


def split_finding(
    chat_id: int,
    n: int,
    parts: Sequence[SplitPart],
    *,
    expected_run_id: str,
    source_revision: str,
    request_id: str,
    shared_photos: Sequence[str] = (),
    confirmed: bool,
) -> dict[str, Any]:
    """Replace one source with reviewed parts, recording the original and every result.

    Replays return the recorded event before looking for the now-deleted source.
    No source words, suggestions or photos are inherited by a new part.
    """
    if confirmed is not True:
        raise ValidationError("Разделение должен подтвердить человек")
    if not re.fullmatch(r"[a-f0-9]{32}", request_id):
        raise ValidationError("Нужен идентификатор операции разделения")
    signature = _digest(
        {
            "n": n,
            "parts": [asdict(part) for part in parts],
            "run_id": expected_run_id,
            "source_revision": source_revision,
            "shared_photos": sorted(shared_photos),
        }
    )
    with while_open(chat_id):
        settings = settings_for(chat_id)
        path = state_file(chat_id, settings)
        with state_lock(path):
            raw = _read_raw(path)
            inspection = _inspection(chat_id, raw, path)
            if inspection.run_id != expected_run_id:
                raise SplitConflict("Сменился запуск проверки")
            for event in inspection.finding_history:
                if event.get("request_id") == request_id:
                    if event.get("signature") != signature:
                        raise SplitConflict("Идентификатор разделения уже использован иначе")
                    return event
            source = inspection.finding(n)
            if source is None or finding_revision(source) != source_revision:
                raise SplitConflict("Исходная запись изменилась; перечитайте её")
            _validate_parts(source, parts, shared_photos)
            with tempfile.TemporaryDirectory(prefix=".split-", dir=path.parent) as temp:
                staged = replace(settings, state_dir=Path(temp))
                staged_path = state_file(chat_id, staged)
                staged_path.parent.mkdir(parents=True)
                _write_atomic(staged_path, raw)
                run_audit(["drop", str(n)], chat_id=chat_id, settings=staged)
                numbers = []
                for part in parts:
                    output = run_audit(
                        [
                            "add",
                            option("qid", part.code),
                            option("level", part.level),
                            option("zone", part.zone),
                            option("evidence", part.text),
                            option("comment", part.comment),
                            "--zone-by-person",
                            *(["--repeat"] if part.repeat else []),
                            *([option("photo", ",".join(part.photos))] if part.photos else []),
                        ],
                        chat_id=chat_id,
                        settings=staged,
                    )
                    numbers.append(_number(output, "add"))
                result = _read_raw(staged_path)
                block = dict(result.get(DOMAIN_KEY) or {})
                for key in (SOURCES_KEY, WORDS_KEY, READINGS_KEY, SUGGESTIONS_KEY):
                    values = dict(block.get(key) or {})
                    values.pop(str(n), None)
                    block[key] = values
                for number, part in zip(numbers, parts, strict=True):
                    block[SOURCES_KEY][str(number)] = SOURCE_COMMENT
                    if part.reading_c is not None:
                        block[READINGS_KEY][str(number)] = part.reading_c
                result[DOMAIN_KEY] = block
                after = _inspection(chat_id, result, staged_path)
                children: list[Finding] = []
                for number, part in zip(numbers, parts, strict=True):
                    child = after.finding(number)
                    if child is None or tuple(child.photos) != part.photos:
                        raise ValidationError("Движок не подтвердил кадры каждой части")
                    children.append(child)
                if after.finding(n) is not None:
                    raise ValidationError("Движок не подтвердил все части разделения")
                event = {
                    "kind": "split",
                    "request_id": request_id,
                    "signature": signature,
                    "run_id": inspection.run_id,
                    "at": utc_now().isoformat(),
                    "before": asdict(source),
                    "after": [asdict(child) for child in children],
                    "shared_photos": sorted(shared_photos),
                }
                block[FINDING_HISTORY_KEY] = [*inspection.finding_history, event]
                _write_atomic(path, result)
                return event
