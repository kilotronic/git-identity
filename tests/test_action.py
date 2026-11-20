# Copyright (c) 2026 Kilotronic LLC.
# SPDX-License-Identifier: MIT
"""action.sh end to end: which commits each event checks, in a real clone with an origin."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ZERO = "0" * 40
GOOD = "ada@ixid.net"
BAD = "jay@Jays-MacBook-Pro.local"


def _git(cwd: Path, *args: str, author: str = GOOD) -> str:
    env = {
        "GIT_AUTHOR_NAME": "Ada",
        "GIT_AUTHOR_EMAIL": author,
        "GIT_COMMITTER_NAME": "GitHub",
        "GIT_COMMITTER_EMAIL": "noreply@github.com",
        "HOME": str(cwd),
        "PATH": os.environ["PATH"],
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    return subprocess.run(
        ["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path):
    """A clone whose origin has base <- bad <- good; returns (clone, base, bad, good)."""
    origin = tmp_path / "origin"
    origin.mkdir()
    _git(origin, "init", "-q", "-b", "main")
    _git(origin, "commit", "-q", "--allow-empty", "-m", "base")
    clone = tmp_path / "clone"
    _git(tmp_path, "clone", "-q", str(origin), str(clone))
    base = _git(clone, "rev-parse", "HEAD")
    _git(clone, "commit", "-q", "--allow-empty", "-m", "bad", author=BAD)
    bad = _git(clone, "rev-parse", "HEAD")
    _git(clone, "commit", "-q", "--allow-empty", "-m", "good")
    good = _git(clone, "rev-parse", "HEAD")
    _git(clone, "push", "-q", "origin", "HEAD:refs/heads/feature")
    return clone, base, bad, good


def _action(clone: Path, **env: str) -> subprocess.CompletedProcess:
    full = {
        "PATH": os.environ["PATH"],
        "HOME": str(clone),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GITHUB_ACTION_PATH": str(ROOT),
        # The runner's own identity is real: only the commits can fail.
        "GIT_AUTHOR_NAME": "Ada",
        "GIT_AUTHOR_EMAIL": GOOD,
        "GIT_COMMITTER_NAME": "Ada",
        "GIT_COMMITTER_EMAIL": GOOD,
        "DOMAINS": "",
        "COMMITS": "",
        "EVENT": "pull_request",
        "PR_BASE": "",
        "PR_HEAD": "",
        "PUSH_BEFORE": "",
        "PUSH_AFTER": "",
        "PUSH_REF": "",
        "DEFAULT_BRANCH": "",
        "ALLOW_BOTS": "",
        "PR_USER": "",
        "HEAD_REF": "",
        "ACTOR": "",
    }
    full.update(env)
    return subprocess.run(
        ["bash", str(ROOT / "src/git_identity/action.sh")],
        check=False,
        cwd=clone,
        env=full,
        capture_output=True,
        text=True,
    )


def test_a_pull_request_checks_every_commit_not_only_its_tip(repo) -> None:
    clone, base, bad, good = repo
    run = _action(clone, EVENT="pull_request", PR_BASE=base, PR_HEAD=good)
    assert run.returncode == 1
    assert f"commit {bad[:7]} author email" in run.stderr


def test_a_pull_request_of_good_commits_passes(repo) -> None:
    clone, _base, bad, good = repo
    run = _action(clone, EVENT="pull_request", PR_BASE=bad, PR_HEAD=good)
    assert run.returncode == 0, run.stderr
    assert "1 commit(s)" in run.stdout


def test_a_push_checks_every_new_commit(repo) -> None:
    clone, base, bad, good = repo
    run = _action(clone, EVENT="push", PUSH_BEFORE=base, PUSH_AFTER=good)
    assert run.returncode == 1
    assert f"commit {bad[:7]} author email" in run.stderr


def test_a_push_does_not_judge_commits_before_it(repo) -> None:
    clone, _base, bad, good = repo
    assert (
        _action(clone, EVENT="push", PUSH_BEFORE=bad, PUSH_AFTER=good).returncode == 0
    )


def test_a_new_branch_checks_its_tip(repo) -> None:
    clone, _base, bad, _good = repo
    run = _action(
        clone,
        EVENT="push",
        PUSH_BEFORE=ZERO,
        PUSH_AFTER=bad,
        PUSH_REF="refs/heads/feature",
        DEFAULT_BRANCH="main",
    )
    assert run.returncode == 1
    assert f"commit {bad[:7]} author email" in run.stderr


@pytest.fixture
def branches(tmp_path: Path):
    """An origin whose main is m0 <- m1, where m1 has a bad author main already has, and branches:
    feature (m0 <- bad <- good), fresh (m1 <- c1), merged (feature plus a merge of main),
    nothing-new (at m1). Returns (origin, commits by name)."""
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "-q", "-b", "main")
    c = {}

    def commit(name: str, author: str = GOOD) -> None:
        _git(work, "commit", "-q", "--allow-empty", "-m", name, author=author)
        c[name] = _git(work, "rev-parse", "HEAD")

    commit("m0")
    _git(work, "checkout", "-q", "-b", "feature")
    commit("bad", BAD)
    commit("good")
    _git(work, "checkout", "-q", "main")
    commit("m1", BAD)
    _git(work, "checkout", "-q", "-b", "fresh")
    commit("c1")
    _git(work, "checkout", "-q", "-b", "merged", "feature")
    _git(work, "merge", "-q", "--no-ff", "-m", "merge", "main")
    c["merge"] = _git(work, "rev-parse", "HEAD")
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", str(origin))
    _git(work, "remote", "add", "origin", str(origin))
    _git(
        work,
        "push",
        "-q",
        "origin",
        "main",
        "feature",
        "fresh",
        "merged",
        f"{c['m1']}:refs/heads/nothing-new",
        f"{c['m1']}:refs/tags/v9",
    )
    return origin, c


def _new(
    origin: Path, branch: str, ref: str, **env: str
) -> subprocess.CompletedProcess:
    """The push that created ``ref`` at ``branch``'s tip, run in a shallow checkout of it (the
    actions/checkout default)."""
    clone = origin.parent / f"checkout-{branch}-{len(env)}"
    _git(
        origin.parent,
        "clone",
        "-q",
        "--depth",
        "1",
        "--branch",
        branch,
        f"file://{origin}",
        str(clone),
    )
    tip = _git(clone, "rev-parse", "HEAD")
    full = {
        "EVENT": "push",
        "PUSH_BEFORE": ZERO,
        "PUSH_AFTER": tip,
        "PUSH_REF": ref,
        "DEFAULT_BRANCH": "main",
    }
    full.update(env)
    return _action(clone, **full)


def test_a_new_branch_checks_every_commit_main_does_not_have(branches) -> None:
    """Like the pre-push rule: a bad commit below a good tip is caught, from a shallow checkout."""
    origin, c = branches
    run = _new(origin, "feature", "refs/heads/feature")
    assert run.returncode == 1
    assert f"commit {c['bad'][:7]} author email" in run.stderr
    assert c["m1"][:7] not in run.stderr


def test_a_new_branch_does_not_judge_commits_main_has(branches) -> None:
    origin, c = branches
    run = _new(origin, "fresh", "refs/heads/fresh")
    assert run.returncode == 0, run.stderr
    assert f"1 commit(s) in {c['m1']}..{c['c1']} OK" in run.stdout


def test_a_new_branch_that_merged_main_checks_its_own_commits(branches) -> None:
    origin, c = branches
    run = _new(origin, "merged", "refs/heads/merged")
    assert run.returncode == 1
    assert f"commit {c['bad'][:7]} author email" in run.stderr
    assert c["m1"][:7] not in run.stderr


def test_a_new_branch_with_no_new_commits_checks_nothing(branches) -> None:
    origin, _c = branches
    run = _new(origin, "nothing-new", "refs/heads/nothing-new")
    assert run.returncode == 0, run.stderr
    assert "nothing to check" in run.stdout


def test_a_new_tag_on_a_commit_main_has_checks_nothing(branches) -> None:
    origin, _c = branches
    run = _new(origin, "main", "refs/tags/v9")
    assert run.returncode == 0, run.stderr
    assert "nothing to check" in run.stdout


def test_a_new_default_branch_checks_its_whole_history(branches) -> None:
    """The first push of the default branch: nothing has been checked yet."""
    origin, c = branches
    run = _new(origin, "main", "refs/heads/main")
    assert run.returncode == 1
    assert f"commit {c['m1'][:7]} author email" in run.stderr


@pytest.mark.parametrize("default", ["gone", ""])
def test_a_new_branch_with_no_default_to_compare_checks_its_whole_history(
    branches, default: str
) -> None:
    origin, c = branches
    run = _new(origin, "fresh", "refs/heads/fresh", DEFAULT_BRANCH=default)
    assert run.returncode == 1
    assert f"commit {c['m1'][:7]} author email" in run.stderr


def test_a_deleted_branch_checks_the_runner_identity(repo) -> None:
    clone, _base, bad, _good = repo
    assert (
        _action(clone, EVENT="push", PUSH_BEFORE=bad, PUSH_AFTER=ZERO).returncode == 0
    )
    run = _action(
        clone,
        EVENT="push",
        PUSH_BEFORE=bad,
        PUSH_AFTER=ZERO,
        GIT_AUTHOR_EMAIL="test@example.com",
    )
    assert run.returncode == 1


def test_other_events_check_the_runner_identity_not_head(repo) -> None:
    clone, *_ = repo
    _git(clone, "commit", "-q", "--allow-empty", "-m", "bad tip", author=BAD)
    assert _action(clone, EVENT="schedule").returncode == 0
    assert (
        _action(
            clone, EVENT="schedule", GIT_COMMITTER_EMAIL="ci@example.com"
        ).returncode
        == 1
    )


def test_an_explicit_range_wins_over_the_event(repo) -> None:
    clone, base, bad, good = repo
    assert (
        _action(clone, COMMITS=f"{bad}..{good}", PR_BASE=base, PR_HEAD=good).returncode
        == 0
    )
    assert (
        _action(clone, COMMITS=f"{base}..{bad}", PR_BASE=bad, PR_HEAD=good).returncode
        == 1
    )


def test_the_action_applies_the_domains(repo) -> None:
    clone, _base, bad, good = repo
    run = _action(
        clone, PR_BASE=bad, PR_HEAD=good, DOMAINS="kilotronic.com, example.org"
    )
    assert run.returncode == 1
    assert "not in domain 'example.org' or 'kilotronic.com'" in run.stderr


def test_allow_bots_does_not_apply_to_an_explicit_range(repo) -> None:
    """A bot's own commits in an explicit range are judged like anyone's."""
    clone, _base, _bad, good = repo
    dependabot = "49699333+dependabot[bot]@users.noreply.github.com"
    _git(clone, "commit", "-q", "--allow-empty", "-m", "bump", author=dependabot)
    bump = _git(clone, "rev-parse", "HEAD")
    run = _action(
        clone,
        COMMITS=f"{good}..{bump}",
        DOMAINS="ixid.net",
        ALLOW_BOTS="dependabot",
        PR_USER="dependabot[bot]",
        ACTOR="dependabot[bot]",
        HEAD_REF="dependabot/npm/x",
    )
    assert run.returncode == 1
    assert "not in domain 'ixid.net'" in run.stderr
