"""Журнал обхода на карточке проверки (D710): шаги человеческими словами.

В базе лежат коды (пункт, зона, класс, вердикт, путь); здесь они превращаются в
слова: пункт — его меткой с формулировкой (`item_label.full` методики той версии, по
которой шла проверка), зона — названием, класс — «отклонение / значительное /
критическое», вердикт и причина отказа — теми же текстами, что видел аудитор. Код
пункта наружу не выходит, пока методика его знает; не знает — остаётся кодом, чтобы
сбой был виден (правило метки, `docs/02-domain.md`).

Модуль только готовит строки к показу: решает, кому они видны, база (`0119`).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC

from src.db import walk_log
from src.db.errors import DbError
from src.db.walk_log import StepRow

from . import auth, usage_screen
from .texts import TEXTS, t

logger = logging.getLogger(__name__)

_TONES = {"ok": "tag--ok", "refused": "tag--warn", "error": "tag--err"}
#: Сколько предложенных пунктов называется в строке подбора.
_OFFERED_SHOWN = 3


@dataclass(frozen=True)
class Step:
    """Один шаг для показа."""

    at: str
    title: str
    outcome: str
    tone: str
    lines: tuple[str, ...]
    duration: str


@dataclass(frozen=True)
class Run:
    """Шаги одного обхода: подпись и учётка аудитора, затем хронология."""

    heading: str
    who: str
    steps: tuple[Step, ...]


def _has(key: str) -> bool:
    return key in TEXTS


def _level(code: str | None, lang: str) -> str:
    if not code:
        return ""
    key = f"walklog.class.{code}"
    return t(key, lang) if _has(key) else code


def _zone(code: str | None, names: dict[str, str]) -> str:
    return names.get(code or "", code or "")


def _offered(row: StepRow, lang: str, full: Callable[[str], str], names: dict[str, str]) -> str:
    cards = row.detail.get("candidates")
    shown = []
    for card in (cards if isinstance(cards, list) else [])[:_OFFERED_SHOWN]:
        if not isinstance(card, dict) or not card.get("code"):
            continue
        parts = [full(str(card["code"]))]
        extra = [_level(card.get("level"), lang), _zone(card.get("zone"), names)]
        if any(extra):
            parts.append(f"({', '.join(x for x in extra if x)})")
        shown.append(" ".join(parts))
    if not shown:
        return t("walklog.offered_none", lang)
    return t("walklog.offered", lang, offer="; ".join(shown))


def _via(row: StepRow, lang: str) -> str:
    if not row.via:
        return ""
    key = f"walklog.via.{row.via}"
    return t(key, lang) if _has(key) else t("walklog.via.other", lang, via=row.via)


def _verdict(row: StepRow, lang: str) -> str:
    if not row.verdict:
        return ""
    key = f"walklog.verdict.{row.verdict}"
    return t(key, lang) if _has(key) else t("walklog.verdict.other", lang, verdict=row.verdict)


def _refusal(row: StepRow, lang: str) -> str:
    code = row.detail.get("reason_code")
    if isinstance(code, str) and _has(code):
        return t("walklog.refusal", lang, message=t(code, lang))
    return ""


def _lines(
    row: StepRow, lang: str, full: Callable[[str], str], names: dict[str, str]
) -> tuple[str, ...]:
    out: list[str] = []
    if row.words:
        out.append(t("walklog.said", lang, words=row.words))
    if row.photos:
        out.append(t("walklog.photos", lang, n=row.photos))
    if row.step == "suggest":
        if row.outcome == "ok":
            out.append(_offered(row, lang, full, names))
        out.append(_via(row, lang))
        out.append(
            t("walklog.question", lang, question=str(row.detail["question"]))
            if row.detail.get("question")
            else ""
        )
    else:
        if row.item_code:
            out.append(t("walklog.item", lang, item=full(row.item_code)))
        if row.zone:
            out.append(t("walklog.zone", lang, zone=_zone(row.zone, names)))
        if row.level:
            out.append(t("walklog.level", lang, level=_level(row.level, lang)))
        out.append(_verdict(row, lang))
        provisional = row.detail.get("provisional")
        if provisional and not row.level:
            out.append(t("walklog.provisional", lang, level=_level(str(provisional), lang)))
        if row.reason:
            out.append(t("walklog.reason", lang, reason=row.reason))
        if row.detail.get("question"):
            out.append(t("walklog.question", lang, question=str(row.detail["question"])))
        if row.detail.get("clarifications"):
            out.append(t("walklog.facts", lang, n=row.detail["clarifications"]))
        if row.detail.get("text"):
            out.append(t("walklog.text", lang, text=str(row.detail["text"])))
    out.append(_refusal(row, lang))
    if row.error:
        out.append(t("walklog.error", lang, error=row.error))
    return tuple(line for line in out if line)


def _step(row: StepRow, lang: str, full: Callable[[str], str], names: dict[str, str]) -> Step:
    key = f"walklog.step.{row.step}"
    return Step(
        at=row.at.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S"),
        title=t(key, lang) if _has(key) else row.step,
        outcome=t(f"walklog.outcome.{row.outcome}", lang),
        tone=_TONES.get(row.outcome, "tag--neutral"),
        lines=_lines(row, lang, full, names),
        duration=t("walklog.duration", lang, ms=row.duration_ms)
        if row.duration_ms is not None
        else "",
    )


def build(
    rows: tuple[StepRow, ...],
    *,
    lang: str,
    full: Callable[[str], str],
    zone_names: dict[str, str],
) -> tuple[Run, ...]:
    """Шаги по обходам (`run_id`), каждый обход — хронологией; порядок обходов — по первому шагу."""
    groups: dict[str, list[StepRow]] = {}
    for row in rows:
        groups.setdefault(row.run_id or f"unit:{row.unit}", []).append(row)
    runs = []
    for group in groups.values():
        unit = next((r.unit for r in group if r.unit), "")
        login = next((r.login for r in group if r.login), "")
        runs.append(
            Run(
                heading=t("walklog.run", lang, unit=unit),
                who=t("walklog.who", lang, login=login) if login else "",
                steps=tuple(_step(r, lang, full, zone_names) for r in group),
            )
        )
    return tuple(runs)


def load(
    session_token: str,
    inspection_id: str,
    *,
    lang: str,
    full: Callable[[str], str],
    zone_names: dict[str, str],
) -> tuple[tuple[Run, ...], bool]:
    """Журнал обхода проверки и «известен ли он»: отказ базы карточку не роняет."""
    try:
        rows = walk_log.read(session_token, inspection_id)
    except DbError as exc:
        logger.warning("журнал обхода проверки %s не прочитался: %s", inspection_id, exc)
        return (), False
    return build(rows, lang=lang, full=full, zone_names=zone_names), True


def card_block(
    inspection_id: str,
    *,
    lang: str,
    full: Callable[[str], str],
    zone_names: dict[str, str],
) -> dict[str, object]:
    """Что карточка проверки получает из журнала обхода.

    Видят главный админ и админ УК (как расход модели): прочим журнал не читается совсем,
    блока на карточке нет. Решающий заслон — в базе (`walk_log_read`), здесь только чтобы не
    ходить за пустым ответом.
    """
    account = auth.current_account()
    if account is None or not usage_screen.may_see(account.role, account.tenant):
        return {"walk_log_visible": False, "walk_log": (), "walk_log_known": True}
    runs, known = load(
        auth.current_session_token(),
        inspection_id,
        lang=lang,
        full=full,
        zone_names=zone_names,
    )
    return {"walk_log_visible": True, "walk_log": runs, "walk_log_known": known}
