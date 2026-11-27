"""Explicit technical checkpoints over the same findings as the ordinary walk."""

from __future__ import annotations

import copy
import csv
import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .config import Settings, check_environment
from .engine import DOMAIN_KEY, state_file
from .errors import ValidationError
from .models import Inspection, fallback_chain
from .revisions import finding_revision

FILE_NAME = "technical_checks.json"
KEY = "technical_checks"
TERMINAL = frozenset({"ok", "issue", "recorded", "na"})


class TechnicalRefused(ValidationError):
    """A checkpoint cannot accept the proposed human confirmation."""

    def __init__(self, reason: str = "invalid") -> None:
        self.reason = reason
        super().__init__(f"walk.technical.err.{reason}")


class TechnicalConflict(TechnicalRefused):
    """The run or reviewed content changed before confirmation."""

    def __init__(self) -> None:
        super().__init__("stale")


def read_answers(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict) or len(value) > 5000:
        raise TechnicalRefused()
    return copy.deepcopy(value)


def manifest(data_dir: Path, *, include_disabled: bool = False) -> list[dict[str, Any]]:
    """Read a versioned optional manifest; malformed content fails closed."""
    path = data_dir / FILE_NAME
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != 1:
            raise TechnicalRefused()
        checks = data.get("checks")
        if not isinstance(checks, list) or not 1 <= len(checks) <= 1000:
            raise TechnicalRefused()
        with (data_dir / "checklist.csv").open(encoding="utf-8-sig", newline="") as file:
            codes = {row["id"] for row in csv.DictReader(file)}
        with (data_dir / "zones.csv").open(encoding="utf-8-sig", newline="") as file:
            zones = {row["code"] for row in csv.DictReader(file)}
        seen: set[str] = set()
        for check in checks:
            if not isinstance(check, dict):
                raise TechnicalRefused()
            ident = check.get("id")
            if not isinstance(ident, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", ident):
                raise TechnicalRefused()
            if ident in seen:
                raise TechnicalRefused()
            seen.add(ident)
            for field, allowed in (("item_codes", codes), ("zones", zones)):
                values = check.get(field)
                if (
                    not isinstance(values, list)
                    or not values
                    or any(not isinstance(value, str) or value not in allowed for value in values)
                    or len(set(values)) != len(values)
                ):
                    raise TechnicalRefused()
            if not isinstance(check.get("required"), bool):
                raise TechnicalRefused()
            for field in ("title_ru", "title_en"):
                if not isinstance(check.get(field), str) or not check[field].strip():
                    raise TechnicalRefused()
            if check.get("kind", "violation") not in {"violation", "info"}:
                raise TechnicalRefused()
            if not isinstance(check.get("requires_photo", False), bool):
                raise TechnicalRefused()
            if not isinstance(check.get("enabled", True), bool):
                raise TechnicalRefused()
            for field in ("guidance_ru", "guidance_en", "applicability_ru", "applicability_en"):
                if not isinstance(check.get(field, ""), str):
                    raise TechnicalRefused()
            countries = check.get("countries", [])
            if not isinstance(countries, list) or any(
                not isinstance(code, str) or not re.fullmatch(r"[A-Z]{2}", code)
                for code in countries
            ):
                raise TechnicalRefused()
        return checks if include_disabled else [c for c in checks if c.get("enabled", True)]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise TechnicalRefused() from exc


def _text(check: dict[str, Any], field: str, lang: str) -> str:
    return next(
        (
            str(check[f"{field}_{code}"])
            for code in fallback_chain(lang)
            if check.get(f"{field}_{code}")
        ),
        "",
    )


def _country(inspection: Inspection) -> str | None:
    from .report_langs import country_of_city
    from .unit_name import canonical_unit

    unit = canonical_unit(inspection.unit)
    return country_of_city(inspection.city) or (unit.country if unit else None)


def _rows(
    inspection: Inspection, checks: list[dict[str, Any]], *, country: str | None
) -> list[dict[str, Any]]:
    country = country or _country(inspection)
    result = []
    for check in checks:
        countries = check.get("countries") or []
        if country and countries and country.upper() not in countries:
            continue
        for zone in check["zones"]:
            key = f"{check['id']}:{zone}"
            answer = inspection.technical_checks.get(key, {})
            if not isinstance(answer, dict):
                raise TechnicalRefused()
            related = [
                finding
                for finding in inspection.findings
                if finding.code in check["item_codes"]
                and finding.zone == zone
                and finding.text.strip()
                and finding.photos
                and finding.level in {"D0", "D1", "D2", "D3"}
            ]
            candidates = {finding.n: finding for finding in related}
            status = answer.get("status", "pending")
            selected = answer.get("findings") or {}
            valid_sources = (
                bool(selected)
                and isinstance(selected, dict)
                and all(
                    str(n).isdigit()
                    and int(n) in candidates
                    and finding_revision(candidates[int(n)]) == signature
                    for n, signature in selected.items()
                )
            )
            if status in {"issue", "recorded"} and not valid_sources:
                status = "pending"
            if status == "ok" and check.get("requires_photo"):
                status = "pending"
            if status not in TERMINAL:
                status = "pending"
            row = copy.deepcopy(check)
            row.update(
                zone=zone,
                key=key,
                status=status,
                terminal=status in TERMINAL,
                reason=str(answer.get("reason") or ""),
                confirmed_at=answer.get("confirmed_at"),
                confirmed_by=answer.get("confirmed_by"),
                finding_numbers=[int(n) for n in selected] if valid_sources else [],
                finding_evidence=[asdict(candidates[int(n)]) for n in selected]
                if valid_sources
                else [],
                candidate_finding_numbers=list(candidates),
            )
            result.append(row)
    return result


def snapshot_from(
    inspection: Inspection, checks: list[dict[str, Any]], *, country: str | None = None
) -> dict[str, Any]:
    from .revision import revision

    checks = [c for c in checks if c.get("enabled", True)]
    rows = _rows(inspection, checks, country=country)
    checked = sum(row["terminal"] for row in rows)
    return {
        "enabled": bool(checks),
        "version": 1,
        "revision": revision(inspection),
        "checklist_version": inspection.checklist_version,
        "checks": rows,
        "total": len(rows),
        "checked": checked,
        "pending": len(rows) - checked,
        "required_pending": sum(row["required"] and not row["terminal"] for row in rows),
    }


def snapshot(
    chat_id: int, settings: Settings | None = None, *, country: str | None = None
) -> dict[str, Any]:
    """Freeze source text and acknowledgements from this visit's pinned edition."""
    from .edition import pin
    from .state import read_state

    env = settings or check_environment()
    inspection = read_state(chat_id, env)
    if inspection is None:
        return {
            "enabled": False,
            "checks": [],
            "total": 0,
            "checked": 0,
            "pending": 0,
            "required_pending": 0,
        }
    if inspection.technical_snapshot is not None:
        # Report translation works on a durable copy after the auditor sealed it.
        # The audit's confirmations describe that seal, before presentation changes.
        return copy.deepcopy(inspection.technical_snapshot)
    # The start marker prevents silently activating checks on pre-existing visits.
    if not inspection.technical_enabled:
        return snapshot_from(inspection, [])
    pinned = pin(chat_id, env)
    checks = manifest(pinned.data_dir)
    if not checks:
        raise TechnicalRefused()
    return snapshot_from(inspection, checks, country=country)


def public_payload(chat_id: int, lang: str, *, country: str | None = None) -> dict[str, Any]:
    data = snapshot(chat_id, country=country)
    for row in data["checks"]:
        row["title"] = _text(row, "title", lang)
        row["guidance"] = _text(row, "guidance", lang)
        row["applicability"] = _text(row, "applicability", lang)
    return data


def assert_complete(chat_id: int, settings: Settings | None = None) -> None:
    if snapshot(chat_id, settings)["required_pending"]:
        raise TechnicalRefused("pending")


def invalidate_raw(raw: dict[str, Any], code: str, zone: str) -> None:
    """A new observation must never resurrect an older positive confirmation."""
    block = raw.get(DOMAIN_KEY) or {}
    answers = block.get(KEY) or {}
    for key, answer in list(answers.items()):
        if answer.get("zone") == zone and code in answer.get("item_codes", []):
            answers.pop(key)


def invalidate_new(path: Path, code: str, zone: str) -> None:
    from .state import _read_raw, _write_atomic, state_lock

    with state_lock(path):
        raw = _read_raw(path)
        if (raw.get(DOMAIN_KEY) or {}).get(KEY):
            invalidate_raw(raw, code, zone)
            _write_atomic(path, raw)


def confirm(
    chat_id: int,
    *,
    run_id: str,
    check_id: str,
    zone: str,
    status: str,
    reason: str = "",
    finding_numbers: list[int] | None = None,
    expected_revision: str | None = None,
) -> None:
    """Confirm one checkpoint under the same notes/state locks as ordinary writes."""
    from .handover import while_open
    from .revision import revision
    from .state import _inspection, _read_raw, _write_atomic, settings_for, state_lock
    from .timing import utc_now

    if status not in TERMINAL | {"pending"} or not isinstance(reason, str) or len(reason) > 1000:
        raise TechnicalRefused()
    if status == "na" and not reason.strip():
        raise TechnicalRefused("reason")
    env = settings_for(chat_id)
    path = state_file(chat_id, env)
    with while_open(chat_id), state_lock(path):
        raw = _read_raw(path)
        inspection = _inspection(chat_id, raw, path)
        if (
            not run_id
            or inspection.run_id != run_id
            or inspection.finished_at is not None
            or (expected_revision is not None and revision(inspection) != expected_revision)
        ):
            raise TechnicalConflict()
        if not inspection.technical_enabled:
            raise TechnicalRefused()
        checks = manifest(env.data_dir)
        check = next(
            (row for row in checks if row["id"] == check_id and zone in row["zones"]), None
        )
        if check is None:
            raise TechnicalRefused()
        country = _country(inspection)
        if country and check.get("countries") and country not in check["countries"]:
            raise TechnicalRefused()
        key = f"{check_id}:{zone}"
        block = dict(raw.get(DOMAIN_KEY) or {})
        answers = dict(block.get(KEY) or {})
        if status == "pending":
            answers.pop(key, None)
        else:
            selected = {}
            numbers = finding_numbers or []
            if status in {"issue", "recorded"}:
                if not isinstance(numbers, list) or not numbers or len(numbers) > 100:
                    raise TechnicalRefused("issue")
                for n in numbers:
                    if not isinstance(n, int) or isinstance(n, bool):
                        raise TechnicalRefused("issue")
                    finding = inspection.finding(n)
                    if (
                        finding is None
                        or finding.code not in check["item_codes"]
                        or finding.zone != zone
                        or not finding.photos
                        or not finding.text.strip()
                        or (status == "issue" and finding.level not in {"D1", "D2", "D3"})
                        or (
                            status == "recorded"
                            and (finding.level != "D0" or check.get("kind") != "info")
                        )
                    ):
                        raise TechnicalRefused("issue")
                    selected[str(n)] = finding_revision(finding)
            elif status == "ok":
                if check.get("requires_photo"):
                    raise TechnicalRefused("photo")
                current = next(
                    row for row in _rows(inspection, [check], country=None) if row["zone"] == zone
                )
                if current["status"] == "issue":
                    raise TechnicalRefused("issue")
            answers[key] = {
                "status": status,
                "reason": reason.strip(),
                "findings": selected,
                "confirmed_at": utc_now().isoformat(),
                "confirmed_by": inspection.auditor or str(chat_id),
                "item_codes": check["item_codes"],
                "zone": zone,
            }
        block[KEY] = answers
        block.pop("technical_snapshot", None)
        raw[DOMAIN_KEY] = block
        _write_atomic(path, raw)
