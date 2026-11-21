# Copyright (c) 2026 Kilotronic LLC.
# SPDX-License-Identifier: MIT
"""action.sh end to end: which commits each event checks, in a real clone with an origin."""

from __future__ import annotations

# The trailer is built from two halves so this public repository never holds it whole (its own
# data-leak check refuses the literal).
T = "Claude" + chr(45) + "Session:"
T_LOWER = T.lower()

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


def test_a_new_default_branch_with_no_ref_named_checks_its_whole_history(
    branches,
) -> None:
    """Without PUSH_REF the action can't tell the default branch's own push apart, so it checks all."""
    origin, c = branches
    run = _new(origin, "main", "")
    assert run.returncode == 1
    assert f"commit {c['m1'][:7]} author email" in run.stderr


def test_a_new_annotated_tag_off_main_checks_its_commits(branches) -> None:
    origin, c = branches
    work = origin.parent / "work"
    _git(work, "tag", "-a", "-m", "v8", "v8", c["good"])
    _git(work, "push", "-q", "origin", "v8")
    tag = _git(work, "rev-parse", "v8")
    run = _new(origin, "v8", "refs/tags/v8", PUSH_AFTER=tag)
    assert run.returncode == 1
    assert f"commit {c['bad'][:7]} author email" in run.stderr


def test_a_new_branch_whose_commit_cannot_be_found_is_refused(branches) -> None:
    origin, _c = branches
    run = _action(
        origin.parent / "work",
        EVENT="push",
        PUSH_BEFORE=ZERO,
        PUSH_AFTER="1234567890" * 4,
        PUSH_REF="refs/heads/gone",
        DEFAULT_BRANCH="main",
    )
    assert run.returncode != 0
    assert "nothing to check" not in run.stdout


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


# --- the commit-message checks the Action also runs over the same commits


def _commit(clone: Path, message: str) -> str:
    _git(clone, "commit", "-q", "--allow-empty", "-m", message)
    return _git(clone, "rev-parse", "HEAD")


def test_commit_subject_is_off_unless_asked(repo) -> None:
    clone, _base, bad, good = repo
    assert _action(clone, PR_BASE=bad, PR_HEAD=good).returncode == 0


def test_commit_subject_refuses_a_bad_subject(repo) -> None:
    clone, _base, bad, good = repo
    run = _action(clone, PR_BASE=bad, PR_HEAD=good, COMMIT_SUBJECT="true")
    assert run.returncode == 1
    assert f"commit {good[:7]}: subject is not" in run.stdout


def test_commit_subject_passes_good_subjects_and_reads_types(repo) -> None:
    clone, _base, _bad, good = repo
    tip = _commit(clone, "feat: add x")
    assert (
        _action(clone, PR_BASE=good, PR_HEAD=tip, COMMIT_SUBJECT="true").returncode == 0
    )
    wip = _commit(clone, "wip: add y")
    assert (
        _action(clone, PR_BASE=tip, PR_HEAD=wip, COMMIT_SUBJECT="true").returncode == 1
    )
    assert (
        _action(
            clone,
            PR_BASE=tip,
            PR_HEAD=wip,
            COMMIT_SUBJECT="true",
            COMMIT_TYPES="wip, feat",
        ).returncode
        == 0
    )


SESSION = (
    f"feat: add x\n\nCo-Authored-By: A <ada@ixid.net>\n{T} https://example.test/s1"
)


def test_session_trailer_refused_on_a_public_repository(repo) -> None:
    clone, _base, _bad, good = repo
    tip = _commit(clone, SESSION)
    run = _action(clone, PR_BASE=good, PR_HEAD=tip, VISIBILITY="public")
    assert run.returncode == 1
    assert f"commit {tip[:7]}: line 4: a Claude-Session trailer" in run.stdout


@pytest.mark.parametrize("vis", ["private", "internal"])
def test_session_trailer_allowed_on_a_private_repository(repo, vis) -> None:
    clone, _base, _bad, good = repo
    tip = _commit(clone, SESSION)
    assert _action(clone, PR_BASE=good, PR_HEAD=tip, VISIBILITY=vis).returncode == 0


def test_session_trailer_cannot_be_skipped(repo) -> None:
    clone, _base, _bad, good = repo
    tip = _commit(clone, SESSION)
    for skip in ("session-trailer", "public-no-leak"):
        run = _action(
            clone, PR_BASE=good, PR_HEAD=tip, VISIBILITY="public", SKIP_CHECKS=skip
        )
        assert run.returncode == 1
        assert "floor check" in run.stdout


def test_commit_subject_can_be_skipped(repo) -> None:
    clone, _base, bad, good = repo
    run = _action(
        clone,
        PR_BASE=bad,
        PR_HEAD=good,
        COMMIT_SUBJECT="true",
        SKIP_CHECKS="commit-subject",
    )
    assert run.returncode == 0, run.stdout
    assert "commit-subject: skipped" in run.stdout


def test_an_unknown_skip_id_fails(repo) -> None:
    clone, _base, bad, good = repo
    run = _action(clone, PR_BASE=bad, PR_HEAD=good, SKIP_CHECKS="commit-subjet")
    assert run.returncode == 1
    assert "unknown check id" in run.stdout


def _action_home(tmp: Path, skippable: str | None) -> Path:
    """An action directory sharing this repo's src/, with its own skippable.txt (or none)."""
    home = tmp / "action"
    home.mkdir()
    (home / "src").symlink_to(ROOT / "src")
    if skippable is not None:
        (home / "skippable.txt").write_text(skippable)
    return home


def test_skippable_txt_lists_commit_subject_as_opt_in() -> None:
    lines = [
        ln.split()
        for ln in (ROOT / "skippable.txt").read_text().splitlines()
        if ln.strip() and not ln.lstrip().startswith("#")
    ]
    assert lines == [["commit-subject", "opt-in"]]


def test_the_skippable_ids_come_from_skippable_txt(repo, tmp_path) -> None:
    clone, _base, bad, good = repo
    home = _action_home(tmp_path, "# nothing can be skipped\n")
    run = _action(
        clone,
        PR_BASE=bad,
        PR_HEAD=good,
        SKIP_CHECKS="commit-subject",
        GITHUB_ACTION_PATH=str(home),
    )
    assert run.returncode == 1
    assert "unknown check id in skip: commit-subject" in run.stdout


def test_a_missing_skippable_txt_is_named(repo, tmp_path) -> None:
    clone, _base, bad, good = repo
    home = _action_home(tmp_path, None)
    run = _action(
        clone,
        PR_BASE=bad,
        PR_HEAD=good,
        SKIP_CHECKS="commit-subject",
        GITHUB_ACTION_PATH=str(home),
    )
    assert run.returncode == 1
    assert "skippable.txt" in run.stdout


def test_a_floor_id_in_skippable_txt_still_runs(repo, tmp_path) -> None:
    clone, _base, _bad, good = repo
    tip = _commit(clone, SESSION)
    home = _action_home(tmp_path, "commit-subject opt-in\nsession-trailer\n")
    run = _action(
        clone,
        PR_BASE=good,
        PR_HEAD=tip,
        VISIBILITY="public",
        SKIP_CHECKS="session-trailer",
        GITHUB_ACTION_PATH=str(home),
    )
    assert run.returncode == 1
    assert "floor check" in run.stdout


def test_an_id_skippable_txt_lists_but_nothing_skips_fails(repo, tmp_path) -> None:
    clone, _base, bad, good = repo
    home = _action_home(tmp_path, "commit-subject opt-in\nnew-check\n")
    run = _action(
        clone,
        PR_BASE=bad,
        PR_HEAD=good,
        SKIP_CHECKS="new-check",
        GITHUB_ACTION_PATH=str(home),
    )
    assert run.returncode == 1
    assert "new-check" in run.stdout and "can't skip" in run.stdout


def test_every_check_reports_in_one_run(repo) -> None:
    clone, base, bad, _good = repo
    tip = _commit(clone, SESSION.replace("feat: add x", "added x"))
    run = _action(
        clone, PR_BASE=base, PR_HEAD=tip, VISIBILITY="public", COMMIT_SUBJECT="true"
    )
    assert run.returncode == 1
    assert f"commit {bad[:7]} author email" in run.stderr
    assert f"commit {tip[:7]}: subject is not" in run.stdout
    assert f"commit {tip[:7]}: line 4: a Claude-Session trailer" in run.stdout


def test_message_checks_skip_the_runner_identity_events(repo) -> None:
    clone, _base, _bad, _good = repo
    run = _action(clone, EVENT="schedule", VISIBILITY="public", COMMIT_SUBJECT="true")
    assert run.returncode == 0, run.stdout + run.stderr
