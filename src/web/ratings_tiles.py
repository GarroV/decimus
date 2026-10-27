"""Плитки раздела «Рейтинги» (D585): лицо плитки — заголовок, одна-две цифры и
короткая строка. Ничего не считается заново: берём готовое из сводки
(`src.ratings.report`), здесь только выбор того, что вынести на лицо.

Развёрнутый блок — прежний кусок страницы, его рисует шаблон.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass

from src.ratings import compare as rcompare
from src.ratings import maps as rmaps
from src.ratings import report
from src.ratings.aggregators import summary as ragg
from src.ratings.summary import ViolationBlock

from . import ratings_risk
from .texts import t

#: Плитка, раскрытая без `?open=`: экран не должен открываться пустым.
DEFAULT_OPEN = "hard"
#: `?open=none` — всё свёрнуто (иначе свёрнутое по умолчанию открытое вернулось бы).
NONE_OPEN = "none"
_DASH = "—"


@dataclass(frozen=True)
class Face:
    figures: tuple[tuple[str, str], ...]  # (подпись, значение)
    note: str


def open_key(arg: str | None, tiles: Collection[str]) -> str | None:
    """Какая плитка раскрыта: названная в адресе; `none` — никакая; нет или
    незнакомая — плитка по умолчанию, если она на экране."""
    if arg == NONE_OPEN:
        return None
    if arg in tiles:
        return arg
    return DEFAULT_OPEN if DEFAULT_OPEN in tiles else None


def _score(x: float | None) -> str:
    return _DASH if x is None else f"{x:.1f}"


def _total(block: ViolationBlock) -> str:
    return str(block.total) if block.has_data else _DASH


def _agg_value(avg: float, scale: int) -> str:
    if scale == 100:
        return f"{avg:.1f}%"
    return f"{avg:.1f}/10" if scale == 10 else f"{avg:.2f}"


def _scores(s: report.Summary, lang: str) -> Face:
    return Face(
        (
            (t("ratings.rs", lang), _score(s.total.rs)),
            (t("ratings.rko", lang), _score(s.total.rko)),
        ),
        t("ratings.tile.scores", lang, n=len(s.groups)),
    )


def _compare(c: rcompare.Comparison, lang: str) -> Face:
    best = c.developers[0] if c.developers else None
    note = (
        t("ratings.tile.compare", lang, name=best.key, x=_score(best.rs))
        if best and best.rs is not None
        else t("ratings.tile.none", lang)
    )
    return Face(
        (
            (t("ratings.tile.developers", lang), str(len(c.developers))),
            (t("ratings.tile.countries", lang), str(len(c.countries))),
        ),
        note,
    )


def _violations(s: report.Summary, lang: str) -> Face:
    rko, rs = s.rko_cluster, s.rs_cluster
    note = (
        t("ratings.tile.violations", lang, rko=_per(rko), rs=_per(rs))
        if rko.has_data or rs.has_data
        else t("ratings.tile.none", lang)
    )
    return Face(((t("ratings.rko", lang), _total(rko)), (t("ratings.rs", lang), _total(rs))), note)


def _per(block: ViolationBlock) -> str:
    return f"{block.per_checkup:.2f}" if block.per_checkup is not None else _DASH


def _top(s: report.Summary, lang: str) -> Face:
    tops, bottoms = s.rs_top, s.rs_bottom
    best = max(tops, key=lambda u: u.score) if tops else None
    worst = min(bottoms, key=lambda u: u.score) if bottoms else None
    kind = t("ratings.rs", lang)
    return Face(
        (
            (t("ratings.tile.best", lang, kind=kind), _score(best.score if best else None)),
            (t("ratings.tile.worst", lang, kind=kind), _score(worst.score if worst else None)),
        ),
        t("ratings.tile.top", lang, name=best.unit_name) if best else t("ratings.tile.none", lang),
    )


def _hard(s: report.Summary, lang: str) -> Face:
    units = {v.unit for v in (*s.rs_hard, *s.rko_hard)}
    return Face(
        (
            (t("ratings.rs", lang), str(len(s.rs_hard))),
            (t("ratings.rko", lang), str(len(s.rko_hard))),
        ),
        t("ratings.tile.hard", lang, n=len(units)),
    )


def _risk(combined: ratings_risk.CombinedRisk, lang: str) -> Face:
    return Face(
        ((t("ratings.col.unit", lang), str(len(combined.rows))),),
        t("ratings.risk.tile", lang),
    )


def _clients(lang: str) -> Face:
    """Оценки клиентов — из Dodo IS (#1303); пока данных нет, лицо честно пустое."""
    return Face(((t("ratings.clients.fig", lang), _DASH),), t("ratings.clients.soon", lang))


def _maps(rows: Sequence[rmaps.CountryMaps] | None, providers: Sequence[int], lang: str) -> Face:
    head = rows[0] if rows and any(r.as_of for r in rows) else None
    figures = []
    for p in providers:
        score = head.scores.get(p) if head else None
        value = f"{score.avg:.2f}" if score and score.avg is not None else _DASH
        figures.append((t(f"ratings.maps.provider.{p}", lang), value))
    note = t("ratings.tile.maps", lang) if head else t("ratings.tile.none", lang)
    return Face(tuple(figures), note)


def _aggs(
    aggs: tuple[tuple[str, ...], Sequence[ragg.GroupAggs], bool] | None,
    names: dict[str, str],
    lang: str,
) -> Face:
    cols, rows, _later = aggs if aggs else ((), (), False)
    if not cols:
        return Face((), t("ratings.tile.none", lang))
    head = rows[0] if rows else None
    figures = []
    for code in cols[:2]:
        score = head.scores.get(code) if head else None
        value = _agg_value(score.avg, score.scale) if score else _DASH
        figures.append((names.get(code, code), value))
    return Face(tuple(figures), t("ratings.tile.aggregators", lang, n=len(cols)))


def faces(
    summary: report.Summary,
    comparison: rcompare.Comparison | None,
    *,
    maps: Sequence[rmaps.CountryMaps] | None,
    map_providers: Sequence[int],
    aggs: tuple[tuple[str, ...], Sequence[ragg.GroupAggs], bool] | None,
    agg_names: dict[str, str],
    risk: ratings_risk.CombinedRisk,
    lang: str,
) -> dict[str, Face]:
    """Лицо каждой плитки по коду блока; `compare` — только когда он есть у зрителя."""
    out = {
        "scores": _scores(summary, lang),
        "violations": _violations(summary, lang),
        "top": _top(summary, lang),
        "hard": _hard(summary, lang),
        "risk": _risk(risk, lang),
        "clients": _clients(lang),
        "maps": _maps(maps, map_providers, lang),
        "aggregators": _aggs(aggs, agg_names, lang),
    }
    if comparison is not None:
        out["compare"] = _compare(comparison, lang)
    return out
