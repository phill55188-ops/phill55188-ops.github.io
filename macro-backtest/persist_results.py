"""Persist workflow results without crossing branches or rebasing stale outputs."""

import os
import re
import subprocess
import sys
from pathlib import PurePosixPath


AUTHORIZED_BRANCHES = {"macro-backtest-v08", "macro-backtest-v08-repair"}
RESULT_ARTIFACT_RE = re.compile(r"^macro-backtest/results(?:/|-[^/]+/)")


def _git(*args, check=True, capture_output=False):
    return subprocess.run(
        ["git", *args],
        check=check,
        text=True,
        capture_output=capture_output,
    )


def validate_result_path(value):
    path = PurePosixPath(value.replace("\\", "/"))
    normalized = path.as_posix()
    if path.is_absolute() or ".." in path.parts:
        raise RuntimeError(f"Refusing unsafe result path: {value}")
    if not (
        normalized == "macro-backtest/results"
        or re.fullmatch(r"macro-backtest/results-[^/]+", normalized)
    ):
        raise RuntimeError(f"Refusing non-result path: {value}")
    return normalized


def is_result_artifact_path(path):
    return bool(RESULT_ARTIFACT_RE.match(path.replace("\\", "/")))


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 2:
        raise RuntimeError("usage: persist_results.py RESULT_PATH COMMIT_MESSAGE")

    result_path = validate_result_path(argv[0])
    commit_message = argv[1]
    result_branch = os.environ.get("GITHUB_REF_NAME", "")
    if result_branch not in AUTHORIZED_BRANCHES:
        raise RuntimeError(
            f"Refusing to persist results from unauthorized branch: {result_branch or '<unset>'}"
        )

    source_sha = _git("rev-parse", "HEAD", capture_output=True).stdout.strip()
    _git("config", "user.name", "github-actions[bot]")
    _git("config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
    _git("add", "--", result_path)

    diff = _git("diff", "--cached", "--quiet", check=False)
    if diff.returncode == 0:
        print("No result changes")
        return 0
    if diff.returncode != 1:
        raise RuntimeError("Unable to inspect staged result changes")

    _git("commit", "-m", commit_message)
    _git("fetch", "origin", result_branch)
    remote_ref = f"origin/{result_branch}"
    remote_sha = _git("rev-parse", remote_ref, capture_output=True).stdout.strip()

    ancestor = _git("merge-base", "--is-ancestor", source_sha, remote_sha, check=False)
    if ancestor.returncode != 0:
        raise RuntimeError(
            f"Refusing to persist results because {remote_ref} no longer descends from {source_sha}"
        )

    changed = _git(
        "diff", "--name-only", f"{source_sha}..{remote_sha}", capture_output=True
    ).stdout.splitlines()
    unexpected = [path for path in changed if not is_result_artifact_path(path)]
    if unexpected:
        details = "\n".join(unexpected)
        raise RuntimeError(
            "Refusing to persist stale results because source files changed after checkout:\n"
            f"{details}"
        )

    _git("rebase", remote_ref)
    _git("push", "origin", f"HEAD:{result_branch}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1)
