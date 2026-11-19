"""Publish generated result directories onto the latest compatible branch head."""

import os
import re
import subprocess
import sys

BRANCHES = {"macro-backtest-v08", "macro-backtest-v08-repair"}
RESULT = re.compile(r'macro-backtest/results(?:-[A-Za-z0-9_-]+)?')
BUNDLE = re.compile(r'macro-backtest/results-provenance/[0-9]+-[0-9]+/(?:defense|historical)')


def git(*args):
    return subprocess.check_output(["git", *args], text=True).strip()


def publish(paths, message):
    branch = os.environ.get("GITHUB_REF_NAME")
    if branch not in BRANCHES:
        raise ValueError("Unsupported result branch")
    if not paths or not all((RESULT.fullmatch(p) and p != 'macro-backtest/results-provenance')
                            or BUNDLE.fullmatch(p) for p in paths):
        raise ValueError("Expected result directories or run-specific capture bundles")

    source = git("rev-parse", "HEAD")
    git("config", "user.name", "github-actions[bot]")
    git("config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
    git("add", "--", *paths)
    snapshot = git("write-tree")
    # The shared Actions queue serializes writers. Recheck source freshness in
    # case a code push arrived while this run waited or computed its results.
    git("fetch", "origin", "refs/heads/" + branch)
    latest = git("rev-parse", "FETCH_HEAD")
    git("merge-base", "--is-ancestor", source, latest)
    changed = git("diff", "--name-only", "-z", source, latest).split("\0")
    for name in filter(None, changed):
        if not RESULT.fullmatch("/".join(name.split("/")[:2])):
            raise ValueError("Source changed after checkout: " + name)

    # Build on the previous writer's exact tree, replacing only this job's
    # owned outputs. Older sibling outputs remain reachable in commit history.
    git("reset", "--mixed", latest)
    git("restore", "--staged", "--source=" + snapshot, "--", *paths)
    if not git("diff", "--cached", "--name-only"):
        return
    git("commit", "-m", message)
    git("push", "origin", "HEAD:refs/heads/" + branch)


if __name__ == "__main__":
    publish(sys.argv[1:-1], sys.argv[-1])
