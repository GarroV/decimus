"""Stage technical checkpoints over the published edition, then publish explicitly."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.domain.checklist_store import Store, published_dir, published_edition
from src.domain.config import DATA_FILES
from src.domain.technical import FILE_NAME, TechnicalRefused, manifest
from src.domain.version import edition_of
from src.mcp.checklist import apply_edit, publish
from src.mcp.errors import ChecklistError


def stage(store: Store, source: Path, *, expected: str, write: bool = False) -> dict[str, object]:
    """Dry-run by default; preserve every existing methodology byte outside the manifest."""
    if published_edition(store) != expected:
        raise ChecklistError("Published edition changed", refusal="edit_stale")
    base = published_dir(store, expected)
    if edition_of(base, DATA_FILES) != expected:
        raise ChecklistError("Published edition fingerprint differs", refusal="bad_version")
    payload = source.read_bytes()
    with tempfile.TemporaryDirectory(prefix="technical-activate-") as temporary:
        candidate = Path(temporary) / "data"
        shutil.copytree(base, candidate)
        (candidate / FILE_NAME).write_bytes(payload)
        checks = manifest(candidate, include_disabled=True)
    result: dict[str, object] = {
        "previous": expected,
        "manifest_sha256": hashlib.sha256(payload).hexdigest(),
        "checkpoints": len(checks),
        "active_checkpoints": sum(c.get("enabled", True) for c in checks),
        "physical_checks": sum(len(c["zones"]) for c in checks if c.get("enabled", True)),
    }
    existing = base / FILE_NAME
    if existing.is_file():
        if existing.read_bytes() == payload:
            return {**result, "status": "unchanged", "version": expected}
        raise ChecklistError(
            "Technical checkpoints already exist; use the methodology editor",
            refusal="technical_already_present",
        )
    if not write:
        return {**result, "status": "validated"}

    def mutate(candidate: Path, holder: Path) -> tuple[None, str]:
        # apply_edit holds the common edit/publication lock here.
        if published_edition(store) != expected:
            raise ChecklistError("Published edition changed", refusal="edit_stale")
        (candidate / FILE_NAME).write_bytes(payload)
        return None, "Technical checkpoint manifest added"

    outcome = apply_edit(
        store,
        tenant="HQ",
        tool="activate_technical_checkpoints",
        mutate=mutate,
        base=expected,
        expected_version=expected,
        note="Add technical checkpoints without changing scoring or checklist entries",
    )
    return {**result, **asdict(outcome)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, default=os.environ.get("MCP_CHECKLIST_STORE"))
    parser.add_argument("--live", type=Path, default=os.environ.get("AUDIT_DATA_DIR"))
    parser.add_argument("--space", default="hq")
    parser.add_argument("--code", default="bizdev")
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("stage")
    prepare.add_argument("manifest", type=Path)
    prepare.add_argument("--expected", required=True)
    prepare.add_argument("--write", action="store_true")
    activate = commands.add_parser("publish")
    activate.add_argument("version")
    activate.add_argument("--expected", required=True)
    args = parser.parse_args()
    if args.store is None or args.live is None:
        parser.error("MCP_CHECKLIST_STORE and AUDIT_DATA_DIR or explicit paths are required")
    store = Store(args.store, args.live, space=args.space, code=args.code)
    try:
        if args.command == "stage":
            result = stage(store, args.manifest, expected=args.expected, write=args.write)
        else:
            result = publish(
                store, tenant="HQ", version=args.version, expected_current=args.expected
            )
    except (ChecklistError, TechnicalRefused) as exc:
        print(json.dumps({"refusal": getattr(exc, "refusal", None) or "technical_invalid"}))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("accepted", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
