"""CI deduplicates only acknowledged Telegram delivery, using actual YAML shell."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = [("pr-checks.yml", "main-gate"), ("mcp-outside.yml", "notify")]


@pytest.fixture(params=WORKFLOWS)
def delivery(request, tmp_path: Path):
    workflow, job = request.param
    definition = yaml.safe_load((ROOT / ".github/workflows" / workflow).read_text())
    steps = definition["jobs"][job]["steps"]
    script = steps[0]["run"]
    bindir = tmp_path / "bin"
    bindir.mkdir()
    jq = shutil.which("jq")
    assert jq, "JSON selection in gh must run through real jq"
    for name, path in {
        "python3": shutil.which("python3"),
        "mktemp": "/usr/bin/mktemp",
        "rm": "/bin/rm",
        "jq": jq,
    }.items():
        assert path
        (bindir / name).symlink_to(path)
    gh = bindir / "gh"
    gh.write_text("""#!/usr/bin/env python3
import json, os, re, subprocess, sys
args = sys.argv[1:]
if "--slurp" in args and ("--jq" in args or "--template" in args):
    sys.stderr.write("the --slurp option is not supported with --jq or --template")
    sys.exit(1)
with open(os.environ["GH_CALLS"], "a") as f: f.write(json.dumps(args)+"\\n")
if os.environ.get("GH_FAIL") in ("1", args[0]): sys.exit(1)
if args[0] == "run":
    if "conclusion" in args:
        print("failure"); sys.exit(0)
    data = [{"databaseId": n} for n in json.loads(os.environ["RUN_IDS"])]
else:
    match = re.search(r"/runs/(\\d+)/jobs", args[1])
    assert match, args
    marker = json.loads(os.environ["HISTORY"])[match[1]]
    steps = [] if marker == "legacy" else [{
        "name": ("Telegram acknowledged " + marker[4:] if marker.startswith("ack-") else
                 "Telegram state " + ("unknown" if marker == "pending" else marker)),
        "conclusion": "skipped" if marker == "pending" else "success",
        "completed_at": "2026-11-17T00:00:00Z"
    }]
    data = [{"jobs": [{"steps": steps}]}]
if "--jq" in args or "-q" in args:
    flag = "--jq" if "--jq" in args else "-q"
    result = subprocess.run([os.environ["REAL_JQ"], "-r", args[args.index(flag)+1]],
                            input=json.dumps(data), text=True)
    sys.exit(result.returncode)
print(json.dumps(data))
""")
    curl = bindir / "curl"
    curl.write_text("""#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ["CURL_CALLS"], "a") as f: f.write(json.dumps(args)+"\\n")
if "-o" in args and args[args.index("-o")+1] != "/dev/null":
    with open(args[args.index("-o")+1], "w") as f:
        json.dump({"ok": os.environ.get("TG_OK", "true") == "true"}, f)
print(os.environ.get("HTTP_CODE", "200"), end="")
sys.exit(int(os.environ.get("CURL_EXIT", "0")))
""")
    gh.chmod(0o700)
    curl.chmod(0o700)
    output = tmp_path / "outputs"
    calls = tmp_path / "curl-calls"
    gh_calls = tmp_path / "gh-calls"
    env = {
        "PATH": str(bindir),
        "FAILED": "true",
        "TG_TOKEN": "synthetic-only",
        "TG_CHAT": "synthetic-only",
        "GH_REPO": "synthetic/repo",
        "GITHUB_REF_NAME": "main",
        "GITHUB_EVENT_NAME": "push",
        "GITHUB_RUN_ID": "99",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_OUTPUT": str(output),
        "RUNNER_TEMP": str(tmp_path),
        "RUN_URL": "https://example.invalid/run",
        "ALERT_FAIL": definition["env"]["ALERT_FAIL"],
        "ALERT_OK": definition["env"]["ALERT_OK"],
        "RUN_IDS": "[]",
        "HISTORY": "{}",
        "REAL_JQ": jq,
        "GH_CALLS": str(gh_calls),
        "CURL_CALLS": str(calls),
    }

    class Runner:
        def run(self, *, history=None, failed=True, **changes):
            output.unlink(missing_ok=True)
            calls.unlink(missing_ok=True)
            gh_calls.unlink(missing_ok=True)
            h = history or {}
            current = {
                **env,
                "FAILED": str(failed).lower(),
                "RUN_IDS": json.dumps(list(h)),
                "HISTORY": json.dumps(h),
                **changes,
            }
            result = subprocess.run(  # noqa: S603 -- actual YAML, only mocked GH/Telegram reachable
                ["/bin/bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", script],
                cwd=tmp_path,
                env=current,
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            self.outputs = (
                dict(line.split("=", 1) for line in output.read_text().splitlines())
                if output.exists()
                else {}
            )
            self.calls = (
                [json.loads(line) for line in calls.read_text().splitlines()]
                if calls.exists()
                else []
            )
            self.gh_calls = (
                [json.loads(line) for line in gh_calls.read_text().splitlines()]
                if gh_calls.exists()
                else []
            )
            return result

    return Runner()


@pytest.mark.parametrize("failure", ["http", "timeout", "missing_config", "api_not_ok"])
def test_delivery_failure_is_retried_during_same_red_episode(delivery, failure) -> None:
    changes = {
        "http": {"HTTP_CODE": "500"},
        "timeout": {"HTTP_CODE": "000", "CURL_EXIT": "28"},
        "missing_config": {"TG_TOKEN": ""},
        "api_not_ok": {"TG_OK": "false"},
    }[failure]
    first = delivery.run(**changes)
    assert first.returncode != 0
    assert "state" not in delivery.outputs
    retry = delivery.run(history={"42": "pending"})
    assert retry.returncode == 0, retry.stderr
    assert len(delivery.calls) == 1
    assert delivery.outputs == {"state": "fail", "source": "acknowledged", "delivered": "true"}


def test_silent_red_runs_carry_forward_last_ack_in_one_lookup(delivery) -> None:
    result = delivery.run(
        history={str(i): "fail" for i in range(2000, 1000, -1)}, GITHUB_RUN_ID="2001"
    )
    assert result.returncode == 0, result.stderr
    assert delivery.calls == []
    assert delivery.outputs == {"state": "fail", "source": "carried", "delivered": "false"}
    assert len([call for call in delivery.gh_calls if call[0] == "api"]) == 1


def test_recovery_requires_prior_fail_ack_and_is_deduplicated(delivery) -> None:
    result = delivery.run(history={"43": "pending", "42": "fail"}, failed=False)
    assert result.returncode == 0, result.stderr
    assert len(delivery.calls) == 1
    assert delivery.outputs["state"] == "ok"
    repeated = delivery.run(history={"44": "ok"}, failed=False)
    assert repeated.returncode == 0
    assert delivery.calls == []
    assert delivery.outputs["source"] == "carried"


def test_empty_history_starts_healthy_without_sending(delivery) -> None:
    result = delivery.run(failed=False)
    assert result.returncode == 0
    assert delivery.calls == []
    assert delivery.outputs == {"state": "ok", "source": "migration-baseline", "delivered": "false"}


def test_legacy_history_does_not_suppress_first_red_alert(delivery) -> None:
    result = delivery.run(history={"42": "legacy"})
    assert result.returncode == 0
    assert len(delivery.calls) == 1
    assert delivery.outputs["delivered"] == "true"


@pytest.mark.parametrize("operation", ["run", "api"])
def test_github_api_error_never_sends_or_advances_state(delivery, operation) -> None:
    result = delivery.run(history={"42": "fail"}, GH_FAIL=operation)
    assert result.returncode != 0
    assert delivery.calls == []
    assert "state" not in delivery.outputs


@pytest.mark.parametrize("failed", [True, False])
def test_history_queries_are_bounded_without_losing_red_retry(delivery, failed) -> None:
    result = delivery.run(
        history={str(i): "pending" for i in range(100, 60, -1)}, failed=failed, GITHUB_RUN_ID="101"
    )
    assert len([call for call in delivery.gh_calls if call[0] == "api"]) == 20
    if failed:
        assert result.returncode == 0
        assert len(delivery.calls) == 1
        assert delivery.outputs["source"] == "acknowledged"
    else:
        assert result.returncode != 0
        assert delivery.calls == []
        assert "state" not in delivery.outputs


def test_rerun_carries_receipt_even_if_checkpoint_was_interrupted(delivery) -> None:
    result = delivery.run(history={"99": "ack-fail"}, RUN_IDS="[]", GITHUB_RUN_ATTEMPT="2")
    assert result.returncode == 0, result.stderr
    assert delivery.calls == []
    assert delivery.outputs == {"state": "fail", "source": "carried", "delivered": "false"}


def test_delivery_text_and_recipient_are_unchanged(delivery) -> None:
    result = delivery.run()
    assert result.returncode == 0
    args = delivery.calls[0]
    payload = [args[i + 1] for i, value in enumerate(args) if value == "--data-urlencode"]
    assert "chat_id=synthetic-only" in payload
    assert len(payload) == 2
    assert any(
        value.startswith("text=DECIMUS:") and value.endswith(" https://example.invalid/run")
        for value in payload
    )


@pytest.mark.parametrize(("workflow", "job"), WORKFLOWS)
def test_receipt_and_checkpoint_require_successful_delivery_step(workflow, job) -> None:
    definition = yaml.safe_load((ROOT / ".github/workflows" / workflow).read_text())
    steps = definition["jobs"][job]["steps"]
    assert steps[0]["id"] == "delivery"
    assert steps[1]["name"].startswith("Telegram acknowledged ")
    assert steps[1]["if"] == "steps.delivery.outputs.delivered == 'true'"
    assert steps[2]["name"].startswith("Telegram state ")
    assert steps[2]["if"] == "success() && steps.delivery.outputs.state != ''"
    assert definition["jobs"][job]["permissions"] == {"actions": "read"}
    assert all("uses" not in step for step in steps), "notification job must not checkout code"


def test_delayed_older_red_run_cannot_override_newer_delivered_recovery(delivery) -> None:
    # B completes first and delivers recovery from an acknowledged red episode.
    newer = delivery.run(history={"100": "fail"}, failed=False, GITHUB_RUN_ID="102")
    assert newer.returncode == 0, newer.stderr
    assert len(delivery.calls) == 1
    assert delivery.outputs["state"] == "ok" and delivery.outputs["delivered"] == "true"
    # Delayed pending A starts only after B has completed. Its old result must
    # neither send a new red message nor overwrite B's state checkpoint.
    older = delivery.run(history={"102": "ok", "100": "fail"}, GITHUB_RUN_ID="101")
    assert older.returncode == 0, older.stderr
    assert delivery.calls == []
    assert delivery.outputs == {}
    assert not any(call[0] == "api" for call in delivery.gh_calls)


def test_rerunning_an_old_run_is_stale_even_with_its_own_previous_receipt(delivery) -> None:
    result = delivery.run(
        history={"102": "ok", "101": "ack-fail"}, GITHUB_RUN_ID="101", GITHUB_RUN_ATTEMPT="2"
    )
    assert result.returncode == 0, result.stderr
    assert delivery.calls == []
    assert delivery.outputs == {}


def test_new_run_reads_newest_chronological_checkpoint_from_unordered_history(delivery) -> None:
    # Delivery completion order or an old rerun must not select an older state.
    result = delivery.run(
        history={"100": "fail", "102": "ok", "101": "pending"},
        failed=False,
        GITHUB_RUN_ID="103",
    )
    assert result.returncode == 0, result.stderr
    assert delivery.calls == []
    assert delivery.outputs == {"state": "ok", "source": "carried", "delivered": "false"}
    api_calls = [call for call in delivery.gh_calls if call[0] == "api"]
    assert len(api_calls) == 1 and "/runs/102/jobs" in api_calls[0][1]


def test_healthy_legacy_checkpoint_uses_supported_cli_flags(delivery) -> None:
    result = delivery.run(history={"42": "legacy"}, failed=False)
    assert result.returncode == 0, result.stderr
    assert delivery.calls == []
    assert delivery.outputs["state"] == "ok"
