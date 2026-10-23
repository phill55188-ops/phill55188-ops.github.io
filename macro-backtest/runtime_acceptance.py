"""Synthetic runtime acceptance for Macro result-writer infrastructure.

This module never reads portfolio configuration or market data.  It validates
workflow provenance, structured synthetic artifacts, and result persistence
against an isolated temporary Git remote.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path


SCHEMA_VERSION = "1.0"
TEST_TYPE = "SYNTHETIC_WORKFLOW_ACCEPTANCE"
REPAIR_BRANCH = "macro-backtest-v08-repair"
BASE_BRANCH = "macro-backtest-v08"
CHECK_NAMES = {
    "selected_head_provenance",
    "structured_artifact_validation",
    "same_branch_persistence",
}


def _run(command, cwd=None, env=None, capture_output=True):
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=False,
        text=True,
        capture_output=capture_output,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip() if completed.stderr else ""
        stdout = completed.stdout.strip() if completed.stdout else ""
        raise RuntimeError(
            f"Command failed ({completed.returncode}): {command!r}\n"
            f"stdout: {stdout}\nstderr: {stderr}"
        )
    return completed


def _git(*args, cwd=None):
    return _run(["git", *args], cwd=cwd).stdout.strip()


def _utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_time(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def validate_record(record, expected_head=None, expected_branch=None):
    required = {
        "schema_version",
        "test_type",
        "synthetic",
        "contains_financial_results",
        "source_head",
        "source_tree",
        "branch",
        "run_id",
        "run_attempt",
        "slot",
        "queue_mode",
        "started_at",
        "finished_at",
        "checks",
        "persistence",
    }
    missing = sorted(required - set(record))
    if missing:
        raise RuntimeError(f"Synthetic artifact missing fields: {missing}")
    if record["schema_version"] != SCHEMA_VERSION:
        raise RuntimeError("Synthetic artifact schema version mismatch")
    if record["test_type"] != TEST_TYPE or record["synthetic"] is not True:
        raise RuntimeError("Artifact is not explicitly synthetic")
    if record["contains_financial_results"] is not False:
        raise RuntimeError("Synthetic artifact must not contain financial results")
    if record["queue_mode"] != "max":
        raise RuntimeError("Synthetic artifact queue mode mismatch")
    if record["branch"] != REPAIR_BRANCH:
        raise RuntimeError(
            f"Synthetic acceptance must run on {REPAIR_BRANCH}, got {record['branch']}"
        )
    if set(record["checks"]) != CHECK_NAMES or set(record["checks"].values()) != {"PASS"}:
        raise RuntimeError("Synthetic acceptance checks are incomplete")
    if expected_head and record["source_head"] != expected_head:
        raise RuntimeError(
            f"Selected-head mismatch: expected {expected_head}, got {record['source_head']}"
        )
    if expected_branch and record["branch"] != expected_branch:
        raise RuntimeError(
            f"Branch mismatch: expected {expected_branch}, got {record['branch']}"
        )
    if _parse_time(record["finished_at"]) < _parse_time(record["started_at"]):
        raise RuntimeError("Synthetic artifact has a negative runtime interval")

    persistence = record["persistence"]
    expected_path = f"macro-backtest/results-runtime-acceptance/slot-{record['slot']}.json"
    if persistence.get("target_branch") != REPAIR_BRANCH:
        raise RuntimeError("Persistence target branch mismatch")
    if persistence.get("base_branch") != BASE_BRANCH:
        raise RuntimeError("Persistence base branch mismatch")
    if persistence.get("base_unchanged") is not True:
        raise RuntimeError("Synthetic persistence modified the base branch")
    if persistence.get("changed_paths") != [expected_path]:
        raise RuntimeError("Synthetic persistence changed an unexpected path")


def run_persistence_acceptance(source_root, slot):
    source_root = Path(source_root).resolve()
    helper_source = source_root / "macro-backtest" / "persist_results.py"
    result_relative = f"macro-backtest/results-runtime-acceptance/slot-{slot}.json"
    configured_temp = os.environ.get("RUNNER_TEMP") or os.environ.get("MACRO_ACCEPTANCE_TEMP")
    temp_parent = Path(configured_temp) if configured_temp else source_root / ".runtime-acceptance-tmp"
    temp_parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(
        prefix="macro-writer-acceptance-", dir=temp_parent, ignore_cleanup_errors=True
    ) as temp:
        temp_path = Path(temp)
        remote = temp_path / "remote.git"
        work = temp_path / "work"
        _run(["git", "init", "--bare", str(remote)])
        _run(["git", "init", "-b", REPAIR_BRANCH, str(work)])
        _git("config", "user.name", "Synthetic Acceptance", cwd=work)
        _git("config", "user.email", "synthetic-acceptance@example.invalid", cwd=work)

        helper_target = work / "macro-backtest" / "persist_results.py"
        helper_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(helper_source, helper_target)
        (work / "README.synthetic.md").write_text(
            "Synthetic writer acceptance fixture. No portfolio or market data.\n",
            encoding="utf-8",
        )
        _git("add", "--", ".", cwd=work)
        _git("commit", "-m", "Initialize synthetic persistence fixture", cwd=work)
        initial = _git("rev-parse", "HEAD", cwd=work)
        _git("remote", "add", "origin", remote.resolve().as_uri(), cwd=work)
        _git("push", "-u", "origin", REPAIR_BRANCH, cwd=work)
        _git("push", "origin", f"{initial}:refs/heads/{BASE_BRANCH}", cwd=work)

        result_file = work / result_relative
        result_file.parent.mkdir(parents=True, exist_ok=True)
        result_file.write_text(
            json.dumps({"synthetic": True, "slot": slot}, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        env = os.environ.copy()
        env["GITHUB_REF_NAME"] = REPAIR_BRANCH
        _run(
            [
                sys.executable,
                str(helper_target),
                result_file.parent.relative_to(work).as_posix(),
                f"Synthetic writer acceptance slot {slot}",
            ],
            cwd=work,
            env=env,
        )

        repair_head = _git(
            "--git-dir", str(remote), "rev-parse", f"refs/heads/{REPAIR_BRANCH}"
        )
        base_head = _git("--git-dir", str(remote), "rev-parse", f"refs/heads/{BASE_BRANCH}")
        changed_paths = _git(
            "--git-dir", str(remote), "diff", "--name-only", f"{initial}..{repair_head}"
        ).splitlines()
        if repair_head == initial:
            raise RuntimeError("Synthetic persistence did not advance the repair branch")
        if base_head != initial:
            raise RuntimeError("Synthetic persistence modified the base branch")
        if changed_paths != [result_relative]:
            raise RuntimeError(f"Synthetic persistence changed unexpected paths: {changed_paths}")

        result = {
            "target_branch": REPAIR_BRANCH,
            "base_branch": BASE_BRANCH,
            "base_unchanged": True,
            "changed_paths": changed_paths,
        }
    if not configured_temp:
        temp_parent.rmdir()
    return result


def run_acceptance(slot, output, expected_head, expected_branch, hold_seconds=0.0):
    source_root = Path(__file__).resolve().parents[1]
    actual_head = _git("rev-parse", "HEAD", cwd=source_root)
    actual_tree = _git("rev-parse", "HEAD^{tree}", cwd=source_root)
    if actual_head != expected_head:
        raise RuntimeError(f"Selected-head mismatch: expected {expected_head}, got {actual_head}")

    started_at = _utc_now()
    if hold_seconds:
        time.sleep(hold_seconds)
    persistence = run_persistence_acceptance(source_root, slot)
    finished_at = _utc_now()
    record = {
        "schema_version": SCHEMA_VERSION,
        "test_type": TEST_TYPE,
        "synthetic": True,
        "contains_financial_results": False,
        "source_head": actual_head,
        "source_tree": actual_tree,
        "branch": expected_branch,
        "run_id": os.environ.get("GITHUB_RUN_ID", "local"),
        "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", "local"),
        "slot": slot,
        "queue_mode": "max",
        "started_at": started_at,
        "finished_at": finished_at,
        "checks": {
            "selected_head_provenance": "PASS",
            "structured_artifact_validation": "PASS",
            "same_branch_persistence": "PASS",
        },
        "persistence": persistence,
    }
    validate_record(record, expected_head, expected_branch)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    validate_record(json.loads(output.read_text(encoding="utf-8")), expected_head, expected_branch)
    return record


def validate_batch(directory, expected_head, expected_branch, expected_slots=(1, 2, 3)):
    records = []
    for path in sorted(Path(directory).glob("slot-*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        validate_record(record, expected_head, expected_branch)
        records.append(record)
    slots = sorted(record["slot"] for record in records)
    if slots != list(expected_slots):
        raise RuntimeError(f"Expected synthetic slots {list(expected_slots)}, got {slots}")

    ordered = sorted(records, key=lambda record: _parse_time(record["started_at"]))
    for previous, current in zip(ordered, ordered[1:]):
        if _parse_time(current["started_at"]) < _parse_time(previous["finished_at"]):
            raise RuntimeError(
                f"Concurrency intervals overlap for slots {previous['slot']} and {current['slot']}"
            )
    return {
        "synthetic": True,
        "contains_financial_results": False,
        "source_head": expected_head,
        "branch": expected_branch,
        "slots": slots,
        "queue_retained_all_jobs": True,
        "execution_intervals_non_overlapping": True,
        "structured_artifacts_valid": True,
        "same_branch_persistence_valid": True,
    }


def main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--slot", type=int, required=True)
    run_parser.add_argument("--output", required=True)
    run_parser.add_argument("--expected-head", required=True)
    run_parser.add_argument("--expected-branch", required=True)
    run_parser.add_argument("--hold-seconds", type=float, default=0.0)

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--input", required=True)
    validate_parser.add_argument("--expected-head", required=True)
    validate_parser.add_argument("--expected-branch", required=True)

    batch_parser = subparsers.add_parser("validate-batch")
    batch_parser.add_argument("--directory", required=True)
    batch_parser.add_argument("--expected-head", required=True)
    batch_parser.add_argument("--expected-branch", required=True)

    args = parser.parse_args()
    if args.command == "run":
        result = run_acceptance(
            args.slot,
            args.output,
            args.expected_head,
            args.expected_branch,
            args.hold_seconds,
        )
    elif args.command == "validate":
        result = json.loads(Path(args.input).read_text(encoding="utf-8"))
        validate_record(result, args.expected_head, args.expected_branch)
    else:
        result = validate_batch(args.directory, args.expected_head, args.expected_branch)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
