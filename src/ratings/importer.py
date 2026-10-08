"""Дверь загрузки рейтингов: байты → разбор → одна транзакция → отчёт.

Один модуль на два входа (D320): веб (`POST /ratings/import`) и MCP
(`import_ratings`). Файл ложится целиком или не ложится вовсе. Тот же sha256 —
строка журнала `duplicate` со ссылкой на первую загрузку; неразобранный файл или
отказ базы — `failed` с причиной, отдельной транзакцией после отката. Исход
пишется при вставке строки журнала и больше не меняется: роль приложения правит
в журнале только счётчики (грант 0038). Пиццерия без id сопоставляется по имени
(`matching`), несопоставленное уходит в журнал, а не теряется (D323).
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime

import psycopg

from src.db import ratings as store
from src.db.config import check_environment
from src.db.errors import RatingsError
from src.db.units import normalize_unit_name

from .countries import country_names, is_excluded
from .formats import detect_format, parse_rko_evaluations, parse_rko_violations, parse_rs_checkups
from .matching import KnownUnit, match_unit
from .model import (
    ERR_UNKNOWN_FORMAT,
    FORMAT_RKO_EVALUATIONS,
    FORMAT_RKO_VIOLATIONS,
    FORMAT_RS_CHECKUPS,
    FORMAT_SHEET_SCORES,
    FORMAT_SNAPSHOT,
    FORMATS,
    ISSUE_BAD_ROW,
    ISSUE_UNIT_UNMATCHED,
    Issue,
    Parsed,
    PeriodRef,
    RatingsFormatError,
    UnitRef,
    Violation,
)
from .sheet import parse_sheet_scores
from .snapshot import parse_snapshot

logger = logging.getLogger(__name__)

CHANNEL_WEB = "web"
CHANNEL_MCP = "mcp"
CHANNEL_SEED = "seed"
OUTCOME_LOADED = "loaded"
OUTCOME_DUPLICATE = "duplicate"

SOURCE_SNAPSHOT = "snapshot"
SOURCE_SHEET = "sheet"

_CSV_PARSERS = {
    FORMAT_RKO_VIOLATIONS: parse_rko_violations,
    FORMAT_RKO_EVALUATIONS: parse_rko_evaluations,
    FORMAT_RS_CHECKUPS: parse_rs_checkups,
}


@dataclass(frozen=True)
class ImportReport:
    import_id: int
    format: str
    outcome: str
    accepted: int = 0
    updated: int = 0
    skipped: int = 0
    unmatched: int = 0
    issues: int = 0
    #: «часть 2 из 3» у снимка — и у загрузки, и у её дубля.
    label: str | None = None
    #: У дубля — когда файл лёг впервые.
    loaded_at: datetime | None = None
    #: Номер части снимка и их число (P26): подпись на языке интерфейса строит
    #: веб, `label` — русская строка для журнала и MCP.
    chunk_index: int | None = None
    chunk_of: int | None = None


def parse_file(data: bytes, *, kind: str | None, today: date) -> Parsed:
    fmt = kind or detect_format(data)
    if fmt not in FORMATS:
        raise RatingsFormatError(
            f"Формат «{fmt[:40]}» не знаком. Есть: {', '.join(FORMATS)}",
            ERR_UNKNOWN_FORMAT,
        )
    if fmt == FORMAT_SNAPSHOT:
        return parse_snapshot(data)
    if fmt == FORMAT_SHEET_SCORES:
        return parse_sheet_scores(data, today=today)
    return _CSV_PARSERS[fmt](data)


def _journal_issues(issues: list[Issue]) -> list[tuple[int, str, Mapping[str, str]]]:
    """Замечания журнала по строке файла: одна строка — одна причина (P10).

    Номер 0 (замечание к документу целиком, например `chunk`) ложится первой
    строкой: в журнале `row_no > 0`.
    """
    seen: dict[tuple[int, str], Mapping[str, str]] = {}
    for issue in issues:
        seen.setdefault((max(issue.row_no, 1), issue.reason), issue.detail)
    return [(row_no, reason, detail) for (row_no, reason), detail in seen.items()]


class _Writer:
    """Пишет разобранный файл в открытую транзакцию и считает строки."""

    def __init__(
        self, conn: psycopg.Connection, parsed: Parsed, import_id: int, source: str
    ) -> None:
        self.conn, self.parsed, self.import_id, self.source = conn, parsed, import_id, source
        self.known = [KnownUnit(*row) for row in store.known_units(conn)]
        self.countries: set[str] = set()
        self.issues: list[Issue] = list(parsed.issues)
        self.accepted = self.updated = 0
        self.skipped = parsed.skipped

    def count(self, outcome: str) -> None:
        if outcome == store.INSERTED:
            self.accepted += 1
        elif outcome == store.UPDATED:
            self.updated += 1
        else:
            self.skipped += 1

    def country(self, code: str | None, dodo_id: int | None = None) -> None:
        if code is None or (code in self.countries and dodo_id is None):
            return
        name_ru, name_en = country_names(code)
        store.ensure_country(
            self.conn,
            code,
            name_ru=name_ru,
            name_en=name_en,
            is_imf=not is_excluded(code),
            dodo_id=dodo_id,
        )
        self.countries.add(code)

    def unit(self, ref: UnitRef, row_no: int) -> str | None:
        self.country(ref.country)
        if ref.dodo_id is not None:
            store.upsert_unit(
                self.conn,
                ref.dodo_id,
                name=ref.name,
                name_normalized=normalize_unit_name(ref.name),
                country=ref.country,
            )
            if all(known.dodo_id != ref.dodo_id for known in self.known):
                self.known.append(KnownUnit(ref.dodo_id, ref.name, ref.country))
            return ref.dodo_id
        found = self.match(ref)
        if found is None:
            detail = {"unit": ref.name, "country": ref.country or ""}
            self.issues.append(Issue(row_no, ISSUE_UNIT_UNMATCHED, detail))
        return found

    def match(self, ref: UnitRef) -> str | None:
        """Только пиццерии с известной страной: запись справочника без страны
        `match_unit` пустил бы в любую страну."""
        if ref.country is None:
            return None
        pool = [known for known in self.known if known.country is not None]
        return match_unit(ref.name, ref.country, pool)

    def run(self) -> None:
        for ref in self.parsed.countries:
            self.country(ref.code, ref.dodo_id)
        for code, developer in self.parsed.developers.items():
            self.country(code)
            store.set_developer_if_empty(self.conn, code, developer)
        self.checkups()
        self.evaluations()
        self.scores()
        self.remarks()

    def checkups(self) -> None:
        for c in self.parsed.checkups:
            unit = self.unit(c.unit, c.row_no)
            if unit is None:
                continue
            self.count(
                store.upsert_checkup(
                    self.conn,
                    rating_type=c.rating_type,
                    dodo_id=c.dodo_id,
                    unit=unit,
                    country=c.unit.country,
                    occurred_at=c.occurred_at,
                    channel=c.channel,
                    period_dodo_id=c.period_dodo_id,
                    backoffice_url=c.backoffice_url,
                    rating_url=c.rating_url,
                    duration_min=c.duration_min,
                    import_id=self.import_id,
                )
            )
            rows: dict[str, store.ViolationRow] = {}
            for v in c.violations:
                _merge(rows, _row_key(f"{c.rating_type}:chk:{c.dodo_id}:{v.category}", v.text), v)
            store.replace_checkup_violations(
                self.conn,
                rating_type=c.rating_type,
                checkup=c.dodo_id,
                unit=unit,
                rows=list(rows.values()),
                import_id=self.import_id,
            )

    def evaluations(self) -> None:
        for e in self.parsed.evaluations:
            self.country(e.country)
            self.count(
                store.set_acceptance(
                    self.conn,
                    dodo_id=e.dodo_id,
                    country=e.country,
                    acceptance=e.acceptance,
                    evaluated_at=e.evaluated_at,
                    import_id=self.import_id,
                )
            )

    def period(self, p: PeriodRef) -> int:
        return store.upsert_period(
            self.conn,
            rating_type=p.rating_type,
            begin_on=p.begin_on,
            end_on=p.end_on,
            title_ru=p.title_ru,
            title_en=p.title_en,
            dodo_id=p.dodo_id,
        )

    def scores(self) -> None:
        for s in self.parsed.scores:
            unit = self.unit(s.unit, s.row_no)
            if unit is None:
                continue
            self.count(
                store.upsert_score(
                    self.conn,
                    unit=unit,
                    period_id=self.period(s.period),
                    score=s.score,
                    status=s.status,
                    checkups_count=s.checkups_count,
                    source=self.source,
                    import_id=self.import_id,
                )
            )

    def remarks(self) -> None:
        groups: dict[tuple[str, int], dict[str, store.ViolationRow]] = {}
        for r in self.parsed.remarks:
            if r.unit.dodo_id is None:
                # Замечание периода без пиццерии некуда положить — но и терять молча нельзя (D323).
                detail = {"reason": "замечание без id пиццерии", "unit": r.unit.name}
                self.issues.append(Issue(0, ISSUE_BAD_ROW, detail))
                continue
            unit = self.unit(r.unit, 0)
            if unit is None:
                continue
            period_id = self.period(r.period)
            tail = r.violation.criterion_id or r.violation.text
            key = _row_key(f"rs:rem:{unit}:{period_id}", tail)
            _merge(groups.setdefault((unit, period_id), {}), key, r.violation)
        for (unit, period_id), rows in groups.items():
            store.replace_remarks(
                self.conn,
                unit=unit,
                period_id=period_id,
                rows=list(rows.values()),
                import_id=self.import_id,
            )


def _row_key(prefix: str, text: str) -> str:
    """Ключ нарушения: хеш полного текста, а не сам текст — длинный текст не упрётся
    в предел строки btree уникального индекса `row_key`."""
    normalized = " ".join(text.split())
    return f"{prefix}:{hashlib.sha256(normalized.encode('utf-8')).hexdigest()}"


def _merge(rows: dict[str, store.ViolationRow], key: str, v: Violation) -> None:
    """Совпавшие по ключу нарушения — одна строка с суммой повторов, а не отказ индекса."""
    prior = rows.get(key)
    rows[key] = _row(key, v, amount=v.amount + (prior.amount if prior else 0))


def _row(key: str, v: Violation, *, amount: int | None = None) -> store.ViolationRow:
    return store.ViolationRow(
        row_key=key,
        text=v.text,
        category=v.category,
        auto_detected=v.auto_detected,
        criterion_id=v.criterion_id,
        parent_name=v.parent_name,
        deduction=v.deduction,
        amount=v.amount if amount is None else amount,
    )


def _trace_failure(
    *, channel: str, actor: str, file_name: str | None, sha: str, note: str, fmt: str | None
) -> None:
    """След `failed`. Сама база недоступна — след не ляжет; это в лог, а наружу
    уходит исходная причина отказа, а не ошибка записи следа."""
    try:
        store.record_failure(
            channel=channel, actor=actor, file_name=file_name, sha=sha, note=note, fmt=fmt
        )
    # Любой сбой следа — в лог: подменить им исходную причину отказа файла нельзя.
    except Exception as exc:
        logger.warning("ratings: след failed не записан (%s): %s", type(exc).__name__, note)


def _db_reason(exc: psycopg.Error) -> str:
    """Причина отказа базы для журнала и человека: класс и имя ограничения, без текста драйвера."""
    constraint = exc.diag.constraint_name
    name = type(exc).__name__
    return f"{name}, ограничение {constraint}" if constraint else name


def _write(
    parsed: Parsed,
    *,
    sha: str,
    channel: str,
    actor: str,
    file_name: str | None,
    source: str | None,
) -> ImportReport:
    with psycopg.connect(check_environment().dsn) as conn, conn.transaction():
        store.lock_imports(conn)
        prior = store.loaded_with(conn, sha)
        if prior is not None:
            dup = store.open_import(
                conn,
                channel=channel,
                actor=actor,
                fmt=parsed.format,
                file_name=file_name,
                sha=sha,
                outcome=OUTCOME_DUPLICATE,
                duplicate_of=prior[0],
                note=parsed.label,
            )
            return ImportReport(
                dup,
                parsed.format,
                OUTCOME_DUPLICATE,
                label=parsed.label,
                loaded_at=prior[1],
                chunk_index=parsed.chunk_index,
                chunk_of=parsed.chunk_of,
            )
        import_id = store.open_import(
            conn,
            channel=channel,
            actor=actor,
            fmt=parsed.format,
            file_name=file_name,
            sha=sha,
            outcome=OUTCOME_LOADED,
            note=parsed.label,
        )
        default = SOURCE_SNAPSHOT if parsed.format == FORMAT_SNAPSHOT else SOURCE_SHEET
        writer = _Writer(conn, parsed, import_id, source or default)
        writer.run()
        issues = _journal_issues(writer.issues)
        unmatched = sum(1 for _, reason, _ in issues if reason == ISSUE_UNIT_UNMATCHED)
        store.add_issues(conn, import_id, issues)
        store.close_import(
            conn,
            import_id,
            accepted=writer.accepted,
            updated=writer.updated,
            skipped=writer.skipped,
            unmatched=unmatched,
        )
    return ImportReport(
        import_id,
        parsed.format,
        OUTCOME_LOADED,
        accepted=writer.accepted,
        updated=writer.updated,
        skipped=writer.skipped,
        unmatched=unmatched,
        issues=len(issues),
        label=parsed.label,
        chunk_index=parsed.chunk_index,
        chunk_of=parsed.chunk_of,
    )


def import_file(
    data: bytes,
    *,
    kind: str | None,
    channel: str,
    actor: str,
    file_name: str | None,
    today: date | None = None,
    source: str | None = None,
) -> ImportReport:
    """Загрузить файл. `RatingsFormatError` — не разобран, `RatingsError` — база отказала
    или файл противоречит базе; любой другой сбой уходит наружу как есть. Во всех
    случаях строка `failed` в журнале уже есть, данных из файла — нет."""
    sha = hashlib.sha256(data).hexdigest()

    def failed(note: str, fmt: str | None) -> None:
        _trace_failure(
            channel=channel, actor=actor, file_name=file_name, sha=sha, note=note, fmt=fmt
        )

    try:
        parsed = parse_file(data, kind=kind, today=today or date.today())
    except RatingsFormatError as exc:
        failed(str(exc), None)
        raise
    except Exception as exc:
        failed(f"сбой разбора: {type(exc).__name__}", None)
        raise
    try:
        return _write(
            parsed, sha=sha, channel=channel, actor=actor, file_name=file_name, source=source
        )
    except psycopg.Error as exc:
        reason = _db_reason(exc)
        failed(f"база отказала: {reason}", parsed.format)
        raise RatingsError(
            f"Загрузка не легла, база отказала ({reason}). Ничего не записано"
        ) from exc
    except RatingsError as exc:
        failed(str(exc), parsed.format)
        raise
    except Exception as exc:
        failed(f"сбой загрузки: {type(exc).__name__}", parsed.format)
        raise
