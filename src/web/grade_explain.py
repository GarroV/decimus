"""«Почему такая буква» и «расшифровка» для карточки проверки (D490).

Здесь только раскладка: правило буквы и строки расшифровки приходят от движка
(`src/report/explain.py`), стоимость записанных находок и потери зон — из базы.
Ни ставок, ни порогов, ни сложения: число попадает на экран тем, каким оно
пришло, и только форматируется под язык (запятая в русском).

Строки по классам показываются, только если движок сказал `exact` — то есть
они сходятся с итогом. Иначе (старые данные, потолок зоны, другой режим D3)
остаются записанные вычеты по зонам: цифры, которые не складываются, не
показываются никогда.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from typing import Any

from src.db.models import InspectionDetail
from src.report import explain as explain_engine
from src.report.letters import LetterError
from src.report.letters import sources as letter_sources

from . import view
from .texts import t

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Explanation:
    """Что карточка показывает под оценкой. Пустые поля не рисуются."""

    #: «B — есть нарушение D2»; пусто, если правило неизвестно (нет методики и т. п.).
    reason: str
    #: Строки расшифровки по порядку, от «Старт» до «Итог».
    lines: tuple[str, ...]
    #: Строка-пояснение перед вычетами по зонам, когда строк по классам нет.
    note: str = ""


def number(value: Any, lang: str) -> str:
    """Число для экрана: без хвостовых нулей, в русском — с запятой."""
    text = format(round(float(value), 2), "g")
    return text.replace(".", ",") if lang == "ru" else text


def reason_text(rule: dict[str, Any], grade: str, detail: InspectionDetail, lang: str) -> str:
    """Фраза «буква — почему» по условию сработавшего правила.

    Ключ текста выбирается по ТОМУ, какие условия стоят в правиле (`if`), а
    пороги берутся из него же. Правила незнакомой формы получают общую фразу,
    а не выдуманную причину.
    """
    cond: dict[str, Any] = rule.get("if") or {}
    if rule.get("index", 0) < 0:
        return t("grade.why.fallback", lang, grade=grade)
    keys = set(cond)
    if keys == {"min_d3"}:
        return t("grade.why.d3", lang, grade=grade)
    if keys == {"min_d2"}:
        return t("grade.why.d2_many", lang, grade=grade, n=number(cond["min_d2"], lang))
    if keys == {"pct_below"}:
        return t("grade.why.pct_below", lang, grade=grade, pct=number(cond["pct_below"], lang))
    if keys == {"pct_at_least", "max_d2"}:
        better = rule.get("better_if")
        if better is None and cond["max_d2"] == 0:
            return t("grade.why.top", lang, grade=grade, pct=number(cond["pct_at_least"], lang))
        if better is not None and set(better) == {"pct_at_least", "max_d2"}:
            has_d2 = int(detail.counts.get("D2", 0)) > better["max_d2"]
            low = float(detail.inspection.pct) < better["pct_at_least"]
            pct = number(better["pct_at_least"], lang)
            if has_d2 and low:
                return t("grade.why.mid_both", lang, grade=grade, pct=pct)
            if has_d2:
                return t("grade.why.mid_d2", lang, grade=grade)
            if low:
                return t("grade.why.mid_pct", lang, grade=grade, pct=pct)
    return t("grade.why.other", lang, grade=grade)


def _zone_names(detail: InspectionDetail, lang: str) -> dict[str, str]:
    return {z.code: z.name for z in view.zone_lines(detail.by_zone, lang)}


def _breakdown_lines(raw: dict[str, Any], names: dict[str, str], lang: str) -> tuple[str, ...]:
    out = [t("explain.start", lang, pct=number(raw["start"], lang))]
    for row in raw["lines"]:
        loss = number(row["loss"], lang)
        if row["kind"] == "level":
            key = "explain.level_repeat" if row["repeat"] else "explain.level"
            out.append(t(key, lang, level=row["level"], n=row["count"], loss=loss))
        else:
            zone = names.get(row["zone"]) or view.pick(row["name_ru"], row["name_en"], lang)
            key = "explain.d3_zone_many" if row["count"] > 1 else "explain.d3_zone"
            out.append(t(key, lang, zone=zone, n=row["count"], loss=loss))
    if raw["skipped"]:
        what = ", ".join(f"{lvl} × {n}" for lvl, n in raw["skipped"].items())
        out.append(t("explain.skipped", lang, what=what))
    out.append(t("explain.total", lang, pct=number(raw["total"], lang)))
    return tuple(out)


def _zone_lines(detail: InspectionDetail, lang: str) -> tuple[str, ...]:
    """Записанные вычеты по зонам — запасной вид, когда строк по классам нет."""
    zones = view.loss_zones(view.zone_lines(detail.by_zone, lang))
    out = [t("explain.zone_loss", lang, zone=z.name, loss=number(z.loss, lang)) for z in zones]
    out.append(t("explain.total", lang, pct=number(detail.inspection.pct, lang)))
    return tuple(out)


def build(detail: InspectionDetail, lang: str) -> Explanation | None:
    """Объяснение оценки; `None` — у исторической проверки его нет (D332).

    Движок недоступен или не сошёлся с записанным — причина буквы не
    показывается, расшифровка сводится к записанным вычетам по зонам, и это
    пишется в лог, а не прячется.
    """
    if detail.inspection.is_legacy:
        return None
    try:
        got = explain_engine.explain(detail, papers=letter_sources())
    except (LetterError, subprocess.SubprocessError, OSError) as exc:
        _log.warning("объяснение оценки %s недоступно: %s", detail.inspection.id, exc)
        return Explanation(
            reason="",
            lines=_zone_lines(detail, lang),
            note=t("explain.zones_only", lang),
        )
    reason = reason_text(got.grade_rule, detail.inspection.grade, detail, lang)
    if got.breakdown.get("exact"):
        lines = _breakdown_lines(got.breakdown, _zone_names(detail, lang), lang)
        return Explanation(reason=reason, lines=lines)
    return Explanation(
        reason=reason, lines=_zone_lines(detail, lang), note=t("explain.zones_only", lang)
    )
