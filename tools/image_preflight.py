"""Check copied source readability and application imports under the runtime UID.

No application main function is called: this check starts no servers or jobs.
"""

from __future__ import annotations

import argparse
import importlib
import os
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# File execution starts with /app/tools on sys.path, unlike the application's
# python -m entrypoints. Resolve imports from this image, independent of cwd or
# editable-install finder behavior.
sys.path.insert(0, str(ROOT))
RUNTIME_ID = 10001
ENTRY_MODULES = {
    "bot": "src.bot.app",
    "web": "src.web.__main__",
    "walk": "src.web.walk_main",
    "mcp": "src.mcp.__main__",
}
COPIED_TREES = ("src", "engine", "tools", "checklist-blank")


def _unreadable_directory(error: OSError) -> None:
    raise error


def read_copied_sources(root: Path) -> None:
    """Actually open all copied files; inaccessible directories must also fail."""
    for name in COPIED_TREES:
        base = root / name
        if not base.is_dir():
            raise FileNotFoundError(name)
        for directory, _, files in os.walk(base, onerror=_unreadable_directory):
            for filename in files:
                with (Path(directory) / filename).open("rb") as source:
                    source.read(1)
    with (root / "pyproject.toml").open("rb") as metadata:
        metadata.read(1)


def preflight(services: Sequence[str], *, root: Path = ROOT) -> None:
    """Require the real application identity before reading or importing code."""
    identity = (os.getuid(), os.geteuid(), os.getgid(), os.getegid())
    if identity != (RUNTIME_ID,) * 4:
        raise RuntimeError(f"expected uid/gid {RUNTIME_ID}; got {identity}")
    read_copied_sources(root)
    for service in services:
        module = importlib.import_module(ENTRY_MODULES[service])
        if not callable(getattr(module, "main", None)):
            raise ImportError(f"missing entry function for {service}")
        print(f"image preflight: {service} import OK", flush=True)
    print(f"image preflight: uid/gid {RUNTIME_ID} OK", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("services", nargs="+", choices=tuple(ENTRY_MODULES))
    args = parser.parse_args()
    try:
        preflight(args.services)
    except (OSError, ImportError, RuntimeError) as error:
        print(f"image preflight failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
