"""Human-confirmed product measurements grouped by explicit line and physical zone."""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .engine import state_file
from .errors import ValidationError
from .models import Inspection
from .revisions import digest, finding_revision

if TYPE_CHECKING:
    from .criteria import ItemCriteria

KEY = "measurement_sets"
MAX_SETS = 20
MAX_PRODUCTS = 30
MAX_SOURCES = 60
MAX_SCOPE_CHARS = 24_000
_IDENT = re.compile(r"[a-f0-9]{32}")
_REVISION = re.compile(r"[a-f0-9]{64}")


class MeasurementSetConflict(ValidationError):
    """The saved set, run, or one of its measurement sources changed."""


@dataclass(frozen=True)
class MeasurementScope:
    set_id: str
    set_revision: str
    data: dict[str, Any]

    @property
    def context(self) -> dict[str, str]:
        return {
            "set_id": self.set_id,
            "set_revision": self.set_revision,
            "scope_hash": digest(self.data),
        }


def read_sets(value: Any) -> dict[str, Any]:
    """Preserve optional metadata; missing legacy metadata is an empty collection."""
    if value is None:
        return {}
    if not isinstance(value, dict) or len(value) > MAX_SETS:
        raise ValidationError("Некорректное хранилище наборов замеров")
    return copy.deepcopy(value)


def _text(value: Any, limit: int, *, required: bool = True) -> str:
    if not isinstance(value, str) or len(value) > limit:
        raise ValidationError("Текст набора замеров отсутствует или слишком длинный")
    result = value.strip()
    if required and not result:
        raise ValidationError("Нужно явно назвать линию и продукты")
    if any(ord(char) < 32 and char not in "\n\t" for char in result):
        raise ValidationError("Текст набора содержит недопустимые символы")
    return result


def _ident(value: Any) -> str:
    if not isinstance(value, str) or not _IDENT.fullmatch(value):
        raise ValidationError("Некорректный идентификатор набора или продукта")
    return value


def _revision(value: Any) -> str:
    if not isinstance(value, str) or not _REVISION.fullmatch(value):
        raise ValidationError("Нужна ревизия источника замера")
    return value


def revision_of(group: dict[str, Any]) -> str:
    return digest(group)


def _sources(inspection: Inspection, group: dict[str, Any]) -> list[dict[str, Any]]:
    """Resolve server measurements; client numbers and frame counts are never facts."""
    products = []
    seen: set[int] = set()
    for product in group["products"]:
        resolved = []
        for ref in product["sources"]:
            n = ref["n"]
            if n in seen:
                raise ValidationError("Один источник нельзя считать двумя продуктами")
            seen.add(n)
            finding = inspection.finding(n)
            if finding is None or finding_revision(finding) != ref["revision"]:
                raise MeasurementSetConflict("Исходный замер изменён или удалён")
            if finding.zone != group["zone"]:
                raise ValidationError("Замер относится к другой физической зоне")
            if finding.level != "D0" or finding.reading_c is None:
                raise ValidationError("Для набора нужен отдельный подтверждённый замер D0")
            resolved.append(
                {
                    "n": finding.n,
                    "revision": ref["revision"],
                    "reading_c": finding.reading_c,
                    "text": finding.text,
                    "words": finding.words,
                    "photo_refs": list(finding.photos),
                }
            )
        products.append({**product, "sources": resolved})
    return products


def _normalize(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "schema",
        "id",
        "code",
        "zone",
        "line_label",
        "confirmed",
        "products",
    }:
        raise ValidationError("Некорректная структура набора замеров")
    if value["schema"] != 1 or type(value["schema"]) is not int or value["confirmed"] is not True:
        raise ValidationError("Человек должен подтвердить состав набора")
    raw = value["products"]
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_PRODUCTS:
        raise ValidationError("Набор пуст или превышает предел продуктов")
    products = []
    ids: set[str] = set()
    total = 0
    for product in raw:
        if not isinstance(product, dict) or set(product) != {
            "id",
            "label",
            "facts",
            "confirmed_product",
            "sources",
        }:
            raise ValidationError("Некорректная структура продукта")
        ident = _ident(product["id"])
        if ident in ids or product["confirmed_product"] is not True:
            raise ValidationError(
                "Нужно подтвердить отдельный продукт, а не воздух или оборудование"
            )
        ids.add(ident)
        sources = product["sources"]
        if not isinstance(sources, list) or not 1 <= len(sources) <= MAX_SOURCES:
            raise ValidationError("У продукта нет источников или превышен предел замеров")
        refs: list[dict[str, Any]] = []
        for ref in sources:
            if not isinstance(ref, dict) or set(ref) != {"n", "revision"}:
                raise ValidationError("Источник задаётся номером и ревизией сохранённой записи")
            if type(ref["n"]) is not int or ref["n"] < 1:
                raise ValidationError("Некорректный номер источника")
            refs.append({"n": ref["n"], "revision": _revision(ref["revision"])})
        total += len(refs)
        if total > MAX_SOURCES:
            raise ValidationError("Слишком много источников набора")
        products.append(
            {
                "id": ident,
                "label": _text(product["label"], 120),
                "facts": _text(product["facts"], 500, required=False),
                "confirmed_product": True,
                "sources": sorted(refs, key=lambda ref: ref["n"]),
            }
        )
    return {
        "schema": 1,
        "id": _ident(value["id"]),
        "code": _text(value["code"], 32),
        "zone": _text(value["zone"], 64),
        "line_label": _text(value["line_label"], 120),
        "confirmed": True,
        "products": sorted(products, key=lambda product: product["id"]),
    }


def _distinct_lines(sets: dict[str, Any], group: dict[str, Any]) -> None:
    own = {ref["n"] for p in group["products"] for ref in p["sources"]}
    products = {p["id"] for p in group["products"]}
    for other in sets.values():
        if other["id"] == group["id"] or (other["code"], other["zone"]) != (
            group["code"],
            group["zone"],
        ):
            continue
        refs = {ref["n"] for p in other["products"] for ref in p["sources"]}
        if own & refs or products & {p["id"] for p in other["products"]}:
            raise ValidationError("Один продукт или замер нельзя включать в разные линии")


def save_set(chat_id: int, value: Any, *, run_id: str) -> dict[str, Any]:
    """Save an explicitly confirmed composition atomically, before any class exists."""
    from .criteria import item_criteria
    from .handover import guard_writable, while_open

    guard_writable(chat_id)
    if not isinstance(value, dict) or "revision" not in value:
        raise ValidationError("Нужна ревизия набора или null для нового")
    expected = value["revision"]
    group = _normalize({k: v for k, v in value.items() if k != "revision"})
    criterion = item_criteria(chat_id, group["code"])
    if not set(criterion.levels) & {"D1", "D2", "D3"}:
        raise ValidationError("Совокупность оценивается по пункту нарушения, а не по D0")
    if criterion.run_id != run_id:
        raise MeasurementSetConflict("Проверка изменилась")
    with while_open(chat_id):
        return _save_checked(chat_id, group, expected, criterion, run_id)


def _save_checked(
    chat_id: int, group: dict[str, Any], expected: Any, criterion: ItemCriteria, run_id: str
) -> dict[str, Any]:
    from .state import _inspection, _read_raw, _write_atomic, settings_for, state_lock

    path = state_file(chat_id, settings_for(chat_id))
    with state_lock(path):
        raw = _read_raw(path)
        inspection = _inspection(chat_id, raw, path)
        if (
            inspection.run_id != run_id
            or inspection.checklist_version != criterion.checklist_version
        ):
            raise MeasurementSetConflict("Проверка или издание изменились")
        groups = read_sets(inspection.measurement_sets)
        existing = groups.get(group["id"])
        _sources(inspection, group)
        if existing == group:
            return {**group, "revision": revision_of(group), "stale": False}
        if (existing is None and expected is not None) or (
            existing is not None and expected != revision_of(existing)
        ):
            raise MeasurementSetConflict("Набор уже изменился")
        if existing is None and len(groups) >= MAX_SETS:
            raise ValidationError("Превышен предел наборов проверки")
        _distinct_lines(groups, group)
        groups[group["id"]] = group
        block = dict(raw.get("domain") or {})
        block[KEY] = groups
        raw["domain"] = block
        _write_atomic(path, raw)
    return {**group, "revision": revision_of(group), "stale": False}


def delete_set(chat_id: int, ident: Any, *, revision: Any, run_id: str) -> None:
    from .handover import guard_writable, while_open

    guard_writable(chat_id)
    ident = _ident(ident)
    _revision(revision)
    with while_open(chat_id):
        _delete_checked(chat_id, ident, revision=revision, run_id=run_id)


def _delete_checked(chat_id: int, ident: str, *, revision: str, run_id: str) -> None:
    from .state import _inspection, _read_raw, _write_atomic, settings_for, state_lock

    path = state_file(chat_id, settings_for(chat_id))
    with state_lock(path):
        raw = _read_raw(path)
        inspection = _inspection(chat_id, raw, path)
        group = inspection.measurement_sets.get(ident)
        if inspection.run_id != run_id:
            raise MeasurementSetConflict("Набор или проверка изменились")
        if group is None:
            return
        if revision_of(group) != revision:
            raise MeasurementSetConflict("Набор или проверка изменились")
        block = dict(raw.get("domain") or {})
        groups = read_sets(inspection.measurement_sets)
        del groups[ident]
        block[KEY] = groups
        raw["domain"] = block
        _write_atomic(path, raw)


def scope_for(
    inspection: Inspection, *, code: str, zone: str | None, set_id: str, set_revision: str
) -> MeasurementScope:
    selected = inspection.measurement_sets.get(_ident(set_id))
    _revision(set_revision)
    if selected is None or revision_of(selected) != set_revision:
        raise MeasurementSetConflict("Выбранный набор изменился")
    if (selected["code"], selected["zone"]) != (code, zone):
        raise ValidationError("Набор относится к другому пункту или зоне")
    lines = []
    for group in sorted(inspection.measurement_sets.values(), key=lambda group: group["id"]):
        if (group["code"], group["zone"]) == (code, zone):
            lines.append(
                {**group, "revision": revision_of(group), "products": _sources(inspection, group)}
            )
    inventory = [
        {"n": f.n, "revision": finding_revision(f)}
        for f in sorted(inspection.findings, key=lambda finding: finding.n)
        if f.zone == zone and f.level == "D0" and f.reading_c is not None
    ]
    data = {"schema": 1, "code": code, "zone": zone, "lines": lines, "inventory": inventory}
    if len(json.dumps(data, ensure_ascii=False)) > MAX_SCOPE_CHARS:
        raise ValidationError("Совокупность превышает предел; молчаливое усечение запрещено")
    return MeasurementScope(set_id, set_revision, data)


def bound_scope(inspection: Inspection, value: Any, *, code: str, zone: str) -> MeasurementScope:
    if not isinstance(value, dict) or set(value) != {"set_id", "set_revision", "scope_hash"}:
        raise ValidationError("Некорректный контекст совокупности")
    scope = scope_for(
        inspection, code=code, zone=zone, set_id=value["set_id"], set_revision=value["set_revision"]
    )
    if scope.context != value:
        raise MeasurementSetConflict("Совокупность замеров изменилась")
    return scope


def public_sets(inspection: Inspection) -> list[dict[str, Any]]:
    result = []
    for group in inspection.measurement_sets.values():
        stale = False
        try:
            _sources(inspection, group)
        except (ValidationError, KeyError, TypeError):
            stale = True
        result.append({**copy.deepcopy(group), "revision": revision_of(group), "stale": stale})
    return result
