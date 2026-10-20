"""`import_match_findings`: пункт, класс и зона по замечаниям конвейером бота (#1033).

До этого MCP подбирал пункт одной картой слов (`import_suggest_items`), а она на
проде промахивается: «три мясных продукта на линии 14 градусов» уходило в PRD06
вместо FSB03. Бот же идёт тремя ступенями: слова места → быстрый путь для
однозначных (`recognize.fastpath`) → модель по ПОЛНОМУ перечню пунктов
(`recognize.classify`). Здесь та же лестница, а своей логики подбора нет: каталог
методики назначается на время сборки (`domain.config.pinned_data_dir`), и бот-овские
`fast_path`, `prepare_request`, `finish` читают издание черновика из хранилища.

Четвёртая ступень — только здесь: когда пункт выбран и у него больше одного класса,
второй узкий вопрос (`recognize.level`) определяет класс по ПОЛНЫМ критериям пункта и
фактам из слов. Одного выполненного условия класса достаточно; не хватает факта —
`need_fact` одной фразой.

Обращения к модели идут пакетом: сначала все запросы собираются по очереди (чтение
файлов методики), потом уходят параллельно потоками, и десять замечаний не стоят
десяти последовательных раундов. Расход пишется как у бота (`recognize.client`,
`model_usage`), контекст — пространство и проверка.

Модель недоступна — откат на карту слов с явным полем `fallback: "word_map"` у
замечания и у ответа: молча подменить подбор нельзя. Только чтение; оценку никто не
считает.
"""

from __future__ import annotations

import contextvars
import logging
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, TypeVar

from ..domain import item_label
from ..domain.config import pinned_data_dir
from ..domain.errors import DomainError
from ..domain.model_usage import usage_scope
from ..recognize.classify import PreparedRequest, finish, prepare_request
from ..recognize.config import RecognizeSettings, load_recognize_settings
from ..recognize.errors import RecognizeError
from ..recognize.fastpath import fast_path
from ..recognize.level import LevelAnswer, level_from, level_request
from ..recognize.models import UNKNOWN_ZONE, Suggestion
from ..recognize.zone_words import zone_from_words
from . import checklist as store_api
from .checklist_layout import Store
from .errors import ToolError
from .import_draft import (
    Draft,
    check_zone,
    levels_of,
    load_draft,
    word_map_suggest,
)
from .imports import MAX_TEXT, _required

logger = logging.getLogger(__name__)

#: Замечаний за вызов — как у `import_add_findings`.
MAX_FINDINGS = 50
#: Параллельных обращений к модели. Больше — упрёмся в лимиты провайдера, а не в
#: время: пятьдесят замечаний идут шестью волнами по восемь.
WORKERS = 8
FALLBACK_WORD_MAP = "word_map"

T = TypeVar("T")


@dataclass
class _Job:
    """Одно замечание на пути по конвейеру."""

    n: int
    text: str
    zone: str | None  # названная вызывающим
    hint: str | None  # зона по словам места
    fast: Any = None  # recognize.fastpath.FastItem
    request: PreparedRequest | None = None
    suggestion: Suggestion | None = None
    failure: str = ""  # почему этого замечания нет в конвейере (→ откат)


def _levels(draft: Draft, code: str) -> list[str]:
    return levels_of(draft.offered[code])


def _in_parallel(calls: Sequence[Callable[[], T]]) -> list[T | Exception]:
    """Выполнить вызовы пакетом. Контекст (учёт расхода) уходит в каждый поток."""
    if not calls:
        return []
    contexts = [contextvars.copy_context() for _ in calls]
    with ThreadPoolExecutor(max_workers=min(WORKERS, len(calls))) as pool:
        futures = [pool.submit(ctx.run, call) for ctx, call in zip(contexts, calls, strict=True)]
    return [f.exception() or f.result() for f in futures]  # type: ignore[misc]


def _prepare(draft: Draft, job: _Job, settings: RecognizeSettings) -> None:
    """Слова места → быстрый путь → запрос к модели. Сбой — в `job.failure`, а не отказ вызова."""
    try:
        with pinned_data_dir(draft.data_dir):
            job.hint = job.zone or zone_from_words(job.text, chat_id=None, zones=draft.zones)
            if job.hint is not None:
                job.fast = fast_path(job.text, job.hint, lang=draft.lang, chat_id=None).item
            if job.fast is None:
                job.request = prepare_request(
                    job.text,
                    None,
                    job.hint,
                    lang=draft.lang,
                    settings=settings,
                    chat_id=None,
                )
    except (RecognizeError, DomainError) as exc:
        logger.warning("подбор замечания %s: запрос не собран: %s", job.n, exc)
        job.failure = f"the request to the model could not be built ({type(exc).__name__})"


def _zone_of(draft: Draft, job: _Job, code: str, model_zone: str | None) -> str | None:
    """Зона: названная вызывающим > ответ модели > слова места > единственная зона пункта."""
    codes = draft.zone_codes
    if job.zone:
        return job.zone
    if model_zone and model_zone != UNKNOWN_ZONE and model_zone in codes:
        return model_zone
    if job.hint:
        return job.hint
    own = [z.strip() for z in (draft.offered[code].get("zones") or "").split(",") if z.strip()]
    return own[0] if len(own) == 1 and own[0] != "*" and own[0] in codes else None


def _described(
    draft: Draft, texts: dict[str, item_label.ItemTexts], code: str
) -> dict[str, object]:
    return {
        "code": code,
        "item_label": item_label.label(code, texts, draft.lang),
        "item_title": item_label.wording(code, texts, draft.lang),
    }


def _fallback(
    draft: Draft, texts: dict[str, item_label.ItemTexts], job: _Job, why: str
) -> dict[str, object]:
    """Откат на карту слов: кандидаты без класса — решает человек, молча подмены нет."""
    кандидаты, угадана, _ = word_map_suggest(draft, job.text, job.zone)
    return {
        "n": job.n,
        "text": job.text,
        "fallback": FALLBACK_WORD_MAP,
        "fallback_reason": why,
        "candidates": [
            {
                **_described(draft, texts, str(c["code"])),
                "levels": c["levels"],
                "criteria": c["criteria"],
            }
            for c in кандидаты
        ],
        **{k: v for k, v in угадана.items() if k in ("zone_guess", "zone_options")},
        "note": "word map only (the model was not used): show the options or ask the person; "
        "the class is not decided",
    }


def _result(
    draft: Draft,
    texts: dict[str, item_label.ItemTexts],
    job: _Job,
    settings: RecognizeSettings,
    level: LevelAnswer | None,
) -> dict[str, object]:
    """Готовая к записи строка: пункт, класс, зона — или `no_item` с причиной."""
    if job.fast is not None:
        fast = job.fast
        return {
            "n": job.n,
            "text": job.text,
            "via": "fast_path",
            **_described(draft, texts, fast.code),
            "level": fast.level,
            "zone": fast.zone,
        }
    suggestion = job.suggestion
    top = suggestion.top() if suggestion is not None else None
    if top is None or top.code not in draft.offered:
        return {
            "n": job.n,
            "text": job.text,
            "via": "model",
            "no_item": True,
            "reason": (suggestion.question if suggestion is not None else "")
            or "no checklist item of this edition matches this wording",
        }
    zone = _zone_of(draft, job, top.code, top.zone)
    answer: dict[str, object] = {
        "n": job.n,
        "text": job.text,
        "via": "model" if level is None else "model+criteria",
        **_described(draft, texts, top.code),
        "level": level.level if level is not None else top.level,
        "zone": zone,
    }
    need = (level.need_fact if level is not None else "") or (
        suggestion.question if suggestion is not None else ""
    )
    if zone is None and not need:
        need = "In which area (place) was this seen?"
    if need:
        answer["need_fact"] = need
    if top.confidence < settings.min_confidence:
        answer["doubt"] = f"the model is not sure (confidence {top.confidence:.2f}): check the item"
    return answer


def match_texts(
    draft: Draft,
    items: Sequence[tuple[str, str | None]],
    *,
    settings: RecognizeSettings | None = None,
) -> list[dict[str, object]]:
    """Прогнать замечания `(текст, зона?)` по конвейеру бота в издании черновика."""
    texts = item_label.from_csv(draft.rows)
    jobs = [_Job(n=i, text=t, zone=z, hint=None) for i, (t, z) in enumerate(items, start=1)]
    try:
        cfg = settings or load_recognize_settings()
    except RecognizeError as exc:
        logger.warning("подбор замечаний: настройки модели не прочитались: %s", exc)
        return [_fallback(draft, texts, j, "the model settings are not usable") for j in jobs]
    for job in jobs:
        _prepare(draft, job, cfg)

    asking = [j for j in jobs if j.request is not None]
    answers = _in_parallel([j.request.ask.call for j in asking if j.request is not None])
    for job, answer in zip(asking, answers, strict=True):
        if isinstance(answer, Exception):
            logger.warning("подбор замечания %s: модель не ответила: %s", job.n, answer)
            job.failure = "the model did not answer"
        elif job.request is not None:
            job.suggestion = finish(job.request, answer)

    # Второй вопрос — класс по полным критериям — только там, где у пункта есть выбор.
    refining: list[tuple[_Job, list[str]]] = []
    calls: list[Callable[..., Any]] = []
    for job in jobs:
        top = job.suggestion.top() if job.suggestion is not None else None
        if top is None or top.code not in draft.offered:
            continue
        levels = _levels(draft, top.code)
        if len(levels) < 2:
            continue
        criteria = store_api.read_item(draft.store, code=top.code, version=draft.version)
        ask = level_request(
            job.text,
            code=top.code,
            levels=levels,
            criteria=criteria["criteria"],
            lang=draft.lang,
            settings=cfg,
        )
        refining.append((job, levels))
        calls.append(ask.call)
    refined: dict[int, LevelAnswer | None] = {}
    for (job, levels), answer in zip(refining, _in_parallel(calls), strict=True):
        if isinstance(answer, Exception):
            # Класс первого ответа остаётся, но молча — нет: строка пойдёт с пометкой.
            logger.warning(
                "подбор замечания %s: класс по критериям не определён: %s", job.n, answer
            )
            refined[job.n] = None
        else:
            refined[job.n] = level_from(answer, levels)

    out: list[dict[str, object]] = []
    for job in jobs:
        if job.failure:
            out.append(_fallback(draft, texts, job, job.failure))
            continue
        row = _result(draft, texts, job, cfg, refined.get(job.n))
        if job.n in refined and refined[job.n] is None and "level" in row:
            row["doubt"] = "the class was not checked against the criteria: confirm it"
        out.append(row)
    return out


def _findings(raw: object) -> list[tuple[str, str | None]]:
    if not isinstance(raw, list) or not raw:
        raise ToolError("findings — непустой список замечаний [{text, zone?}]")
    if len(raw) > MAX_FINDINGS:
        raise ToolError(f"За один вызов — не больше {MAX_FINDINGS} замечаний")
    out: list[tuple[str, str | None]] = []
    for i, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ToolError(f"Замечание {i}: ожидается объект {{text, zone?}}")
        unknown = set(item) - {"text", "zone"}
        if unknown:
            raise ToolError(f"Замечание {i}: лишние поля {', '.join(sorted(unknown))}")
        text = _required(str(item.get("text") or ""), field=f"findings[{i}].text", limit=MAX_TEXT)
        out.append((text, str(item["zone"]) if item.get("zone") else None))
    return out


def import_match_findings(
    *,
    tenant: str,
    store: Store,
    actor: str,
    inspection_id: str,
    findings: list[dict[str, str]],
) -> dict[str, object]:
    """Подобрать пункт, класс и зону по каждому замечанию — тем же конвейером, что у бота."""
    del actor
    разобранные = _findings(findings)
    draft = load_draft(tenant=tenant, store=store, inspection_id=inspection_id)
    пары = [(text, check_zone(draft, zone)) for text, zone in разобранные]
    started = time.monotonic()
    # Расход модели (D537): за пространством и проверкой, как у бота за её чатом.
    with usage_scope(tenant=tenant, inspection_ref=draft.ident):
        results = match_texts(draft, пары)
    answer: dict[str, object] = {
        "inspection_id": draft.ident,
        "mode": "history" if draft.history else "current",
        "checklist_version": draft.version,
        "elapsed_s": round(time.monotonic() - started, 1),
        "results": results,
    }
    if any(r.get("fallback") for r in results):
        answer["fallback"] = FALLBACK_WORD_MAP
    if draft.history:
        answer["history_note"] = (
            "history mode: item codes are optional, give one only if the old report names it"
        )
    return answer
