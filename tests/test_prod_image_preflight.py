"""A failed image import check stops deployment before any service is replaced."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def deployment(tmp_path: Path, *, fail_service: str = ""):
    repo = tmp_path / "repo"
    scripts = repo / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy(ROOT / "scripts/prod-update.sh", scripts / "prod-update.sh")
    verify = scripts / "verify-source.sh"
    verify.write_text("#!/bin/sh\nexit 0\n")
    verify.chmod(0o755)
    binary = tmp_path / "bin"
    binary.mkdir()
    events = tmp_path / "events.jsonl"
    docker = binary / "docker"
    docker.write_text(
        f"#!{sys.executable}\n"
        "import json,os,sys\n"
        "args=sys.argv[1:]\n"
        "with open(os.environ['PREFLIGHT_EVENTS'],'a') as out: out.write(json.dumps(args)+'\\n')\n"
        "if 'tools/image_preflight.py' in args and args[-1]==os.environ['FAIL_PREFLIGHT']:\n"
        " sys.exit(17)\n"
        "if 'port' in args: print('127.0.0.1:'+('8267' if 'web' in args else '8265'))\n"
        "probe=args[-1].startswith('touch /app/state/.walk-probe')\n"
        "if 'exec' in args and 'web' in args and probe:\n"
        " sys.exit(1)\n"
    )
    git = binary / "git"
    git.write_text("#!/bin/sh\necho synthetic-sha\n")
    curl = binary / "curl"
    curl.write_text(
        f"#!{sys.executable}\nimport sys\nprint('401' if 'POST' in sys.argv else '200')\n"
    )
    for command in (docker, git, curl):
        command.chmod(0o755)
    env = dict(
        os.environ,
        PATH=str(binary) + os.pathsep + os.environ["PATH"],
        PULL="0",
        LEAK_CHECK="0",
        DECIMUS_DEPLOY_LOCKED="1",
        DECIMUS_OVERLAYS="fixture-overlay.yml",
        PREFLIGHT_EVENTS=str(events),
        FAIL_PREFLIGHT=fail_service,
    )
    result = subprocess.run(  # noqa: S603 — production script with isolated command adapters
        ["/bin/bash", str(scripts / "prod-update.sh")],
        capture_output=True,
        text=True,
        env=env,
        timeout=20,
        check=False,
    )
    assert events.exists(), result.stderr
    calls = [json.loads(row) for row in events.read_text().splitlines()]
    return result, calls


@pytest.mark.parametrize("service", ["bot", "web", "walk", "mcp"])
def test_failed_import_stops_before_switching_the_running_services(tmp_path: Path, service):
    result, calls = deployment(tmp_path, fail_service=service)
    assert result.returncode != 0, "an image rejected by preflight still reached deployment"
    assert any("tools/image_preflight.py" in call and call[-1] == service for call in calls)
    assert not any("up" in call for call in calls), (
        "running services changed before image acceptance"
    )


def test_every_application_image_is_checked_before_the_first_service_change(tmp_path: Path):
    result, calls = deployment(tmp_path)
    assert result.returncode == 0, result.stderr
    checks = [call for call in calls if "tools/image_preflight.py" in call]
    assert {call[-1] for call in checks} == {"bot", "web", "walk", "mcp"}
    assert all("--no-deps" in call and "--entrypoint" in call for call in checks)
    first_up = next(index for index, call in enumerate(calls) if "up" in call)
    assert all(calls.index(call) < first_up for call in checks)


def test_preflight_rejects_root_before_importing_any_application(monkeypatch):
    from tools import image_preflight

    monkeypatch.setattr(image_preflight.os, "getuid", lambda: 0)
    monkeypatch.setattr(
        image_preflight,
        "read_copied_sources",
        lambda root: pytest.fail("source scan ran before rejecting a wrong UID"),
    )
    with pytest.raises(RuntimeError, match="expected uid/gid 10001"):
        image_preflight.preflight(["bot"])


def test_preflight_imports_each_entry_without_starting_application_main(monkeypatch):
    from types import SimpleNamespace

    from tools import image_preflight

    for name in ("getuid", "geteuid", "getgid", "getegid"):
        monkeypatch.setattr(image_preflight.os, name, lambda: 10001)
    monkeypatch.setattr(image_preflight, "read_copied_sources", lambda root: None)
    imported = []

    def entry(name):
        imported.append(name)
        return SimpleNamespace(main=lambda: pytest.fail("an application was started by preflight"))

    monkeypatch.setattr(image_preflight.importlib, "import_module", entry)
    image_preflight.preflight(["bot", "web", "walk", "mcp"])
    assert imported == list(image_preflight.ENTRY_MODULES.values())


def test_checker_file_resolves_its_sources_from_an_unrelated_working_directory(tmp_path: Path):
    image = tmp_path / "image"
    for name in ("src/bot", "src/web", "src/mcp", "engine", "tools", "checklist-blank"):
        (image / name).mkdir(parents=True, exist_ok=True)
    checker = image / "tools/image_preflight.py"
    shutil.copy(ROOT / "tools/image_preflight.py", checker)
    (image / "pyproject.toml").write_text("")
    for name in ("src", "src/bot", "src/web", "src/mcp"):
        (image / name / "__init__.py").write_text("")
    entries = (
        "src/bot/app.py",
        "src/web/__main__.py",
        "src/web/walk_main.py",
        "src/mcp/__main__.py",
    )
    for name in entries:
        (image / name).write_text(
            "def main():\n raise AssertionError('application must not start')\n"
        )
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    # Identity is shimmed solely to reach imports; actual UID proof is a Docker check.
    code = """
import os,runpy,sys
from pathlib import Path
for name in ('getuid','geteuid','getgid','getegid'):
    setattr(os,name,lambda:10001)
sys.argv=[sys.argv[1],'bot','web','walk','mcp']
root=Path(sys.argv[0]).resolve().parents[1]
try:
    runpy.run_path(sys.argv[0],run_name='__main__')
except SystemExit as stopped:
    if stopped.code:
        raise
for name in ('src.bot.app','src.web.__main__','src.web.walk_main','src.mcp.__main__'):
    assert Path(sys.modules[name].__file__).is_relative_to(root), 'wrong source root'
"""
    result = subprocess.run(  # noqa: S603 — copied checker and synthetic packages, no app entry calls
        [sys.executable, "-c", code, str(checker)],
        cwd=elsewhere,
        env={"PATH": os.environ["PATH"], "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.count("import OK") == 4
