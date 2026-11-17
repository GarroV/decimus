"""Фронт запускает только локальный закреплённый Wrangler до чтения секретов."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _front(tmp_path: Path) -> Path:
    front = tmp_path / "front"
    shutil.copytree(ROOT / "front", front, ignore=shutil.ignore_patterns("node_modules"))
    (front / ".deploy.env").write_text(
        'printf loaded > "$LOADED"\nVPC_SERVICE_ID=synthetic-vpc\n'
        "ORIGIN_HOST=example.invalid\nSYNTHETIC_DEPLOY_SECRET=synthetic-only\n"
    )
    return front


def _run(front: Path, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    mock = tmp_path / "mock"
    mock.mkdir()
    npx = mock / "npx"
    npx.write_text('#!/bin/bash\nprintf fallback > "$FALLBACK"\n')
    npx.chmod(0o700)
    return subprocess.run(  # noqa: S603 -- own script, synthetic config; no real Wrangler reachable
        ["/bin/bash", str(front / "deploy.sh"), "admin", "--dry-run"],
        env={
            **os.environ,
            "PATH": f"{mock}:/usr/bin:/bin",
            "LOADED": str(tmp_path / "loaded"),
            "FALLBACK": str(tmp_path / "fallback"),
            "CAPTURE": str(tmp_path / "capture"),
        },
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )


def test_missing_local_tool_fails_before_loading_deploy_secrets(tmp_path: Path) -> None:
    front = _front(tmp_path)
    done = _run(front, tmp_path)
    assert done.returncode != 0
    assert not (tmp_path / "loaded").exists()
    assert not (tmp_path / "fallback").exists()


def test_installed_local_tool_receives_config_and_arguments_without_npx(tmp_path: Path) -> None:
    front = _front(tmp_path)
    tool = front / "node_modules/.bin/wrangler"
    tool.parent.mkdir(parents=True)
    tool.write_text(
        '#!/bin/bash\nprintf "%s\\n" "$@" > "$CAPTURE"\n'
        '[ "$SYNTHETIC_DEPLOY_SECRET" = synthetic-only ]\n'
    )
    tool.chmod(0o700)
    done = _run(front, tmp_path)
    assert done.returncode == 0, done.stderr
    assert (tmp_path / "capture").read_text().splitlines() == [
        "deploy",
        "-c",
        "wrangler.admin.jsonc",
        "--dry-run",
    ]
    assert not (tmp_path / "fallback").exists()


def test_wrangler_tree_is_exact_and_integrity_locked() -> None:
    manifest = json.loads((ROOT / "front/package.json").read_text())
    lock = json.loads((ROOT / "front/package-lock.json").read_text())
    version = manifest["devDependencies"]["wrangler"]
    assert version == lock["packages"][""]["devDependencies"]["wrangler"]
    assert version == lock["packages"]["node_modules/wrangler"]["version"]
    assert version[0].isdigit() and all(part.isdigit() for part in version.split("."))
    for name, package in lock["packages"].items():
        if name:
            assert package["resolved"].startswith("https://registry.npmjs.org/")
            assert package["integrity"].startswith("sha512-")
