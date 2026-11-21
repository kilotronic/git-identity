# Copyright (c) 2026 Kilotronic LLC.
# SPDX-License-Identifier: MIT
"""commit_msg.py: the commit-subject and session-trailer checks, as commit-msg hooks and over a range."""

from __future__ import annotations

# The trailer is built from two halves so this public repository never holds it whole (its own
# data-leak check refuses the literal).
T = "Claude" + chr(45) + "Session:"
T_LOWER = T.lower()

import os
import subprocess
from pathlib import Path

import pytest

from git_identity import commit_msg
from git_identity.commit_msg import subject_problem, trailer_lines

TYPES = commit_msg.DEFAULT_TYPES


@pytest.mark.parametrize(
    "message",
    [
        "feat: add the session trailer check",
        "fix(hook): refuse an empty subject",
        "refactor!: drop the v1 inputs",
        "docs: Address the review",
        "chore: focus the tests",
        "build(deps): bump actions/checkout from 4 to 5",
        "fix: embed the default config",
        "feat: bring back the CLI",
        "Merge branch 'main' into feature",
        "Merge pull request #12 from x/y",
        'Revert "feat: add x"',
        "fixup! feat: add x",
        "squash! feat: add x",
    ],
)
def test_subject_allows(message):
    assert subject_problem(message, TYPES) is None


@pytest.mark.parametrize(
    ("message", "why"),
    [
        ("", "empty"),
        ("add the check", "<type>: <imperative"),
        ("Feat: add the check", "<type>: <imperative"),
        ("feat:add the check", "<type>: <imperative"),
        ("feat:  add the check", "<type>: <imperative"),
        ("wip: add the check", "<type>: <imperative"),
        ("feat: added the check", "imperative"),
        ("feat: adding the check", "imperative"),
        ("fix: adds the check", "imperative"),
        ("fix: Removes the check", "imperative"),
        ("feat:", "<type>: <imperative"),
    ],
)
def test_subject_refuses(message, why):
    problem = subject_problem(message, TYPES)
    assert problem is not None and why in problem


def test_subject_types_are_configurable():
    assert subject_problem("wip: add x", ("wip",)) is None
    assert subject_problem("feat: add x", ("wip",)) is not None


def test_body_only_when_asked():
    assert subject_problem("feat: add x", TYPES, require_body=True) is not None
    assert (
        subject_problem(
            "feat: add x\n\nCo-Authored-By: A <a@b.c>\n", TYPES, require_body=True
        )
        is not None
    )
    assert (
        subject_problem("feat: add x\n\nBecause y.\n", TYPES, require_body=True) is None
    )


@pytest.mark.parametrize(
    ("message", "found"),
    [
        (f"feat: add x\n\n{T} https://example.test/s1\n", 1),
        (f"feat: add x\n\n{T_LOWER} https://example.test/s1\n", 1),
        (f"feat: add x\n\nCo-Authored-By: A <a@b.c>\n  {T} x\n", 1),
        ("feat: add x\n\nCo-Authored-By: A <a@b.c>\n", 0),
        (f"feat: add x\n\nThe {T} trailer is now refused.\n", 0),
    ],
)
def test_trailer_lines(message, found):
    assert len(trailer_lines(message)) == found


# --- the hooks, as git hands them the message file, in a real repository


def _git(cwd: Path, *args: str) -> str:
    env = {
        "GIT_AUTHOR_NAME": "Ada",
        "GIT_AUTHOR_EMAIL": "ada@ixid.net",
        "GIT_COMMITTER_NAME": "Ada",
        "GIT_COMMITTER_EMAIL": "ada@ixid.net",
        "HOME": str(cwd),
        "PATH": os.environ["PATH"],
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    return subprocess.run(
        ["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path, monkeypatch):
    _git(tmp_path, "init", "-q", "-b", "main")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("KILOTRONIC_VISIBILITY", raising=False)
    return tmp_path


def _msg(repo: Path, text: str) -> str:
    path = repo / ".git" / "COMMIT_EDITMSG"
    path.write_text(text)
    return str(path)


def test_subject_hook(repo, capsys):
    assert commit_msg.subject_main([_msg(repo, "feat: add x\n")]) == 0
    assert commit_msg.subject_main([_msg(repo, "added x\n")]) == 1
    assert commit_msg.subject_main(["--types=wip", _msg(repo, "wip: add x\n")]) == 0
    # git's comment lines and the `commit -v` diff are not part of the message
    text = "# Please enter the commit message\nfeat: add x\n# ------------------------ >8 ------------------------\nadded\n"
    assert commit_msg.subject_main([_msg(repo, text)]) == 0


def test_subject_over_a_range(repo):
    _git(repo, "commit", "-q", "--allow-empty", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "feat: add x")
    assert commit_msg.subject_main(["--commits", f"{base}..HEAD"]) == 0
    _git(repo, "commit", "-q", "--allow-empty", "-m", "added y")
    assert commit_msg.subject_main(["--commits", f"{base}..HEAD"]) == 1
    _git(
        repo, "merge", "-q", "--no-ff", "-m", "Merge branch 'x'", "HEAD~1"
    )  # a merge: skipped


SESSION = f"feat: add x\n\n{T} https://example.test/s1\n"


def test_trailer_refused_when_public(repo):
    assert (
        commit_msg.trailer_main([_msg(repo, SESSION)], visibility=lambda: "PUBLIC") == 1
    )
    assert (
        commit_msg.trailer_main(
            [_msg(repo, "feat: add x\n")], visibility=lambda: "PUBLIC"
        )
        == 0
    )


@pytest.mark.parametrize("vis", ["PRIVATE", "INTERNAL", "UNKNOWN"])
def test_trailer_allowed_unless_known_public(repo, vis):
    assert commit_msg.trailer_main([_msg(repo, SESSION)], visibility=lambda: vis) == 0


def test_trailer_over_a_range(repo):
    _git(repo, "commit", "-q", "--allow-empty", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD")
    _git(repo, "commit", "-q", "--allow-empty", "-m", SESSION)
    assert (
        commit_msg.trailer_main(
            ["--commits", f"{base}..HEAD"], visibility=lambda: "PUBLIC"
        )
        == 1
    )
    assert (
        commit_msg.trailer_main(
            ["--commits", f"{base}..HEAD"], visibility=lambda: "PRIVATE"
        )
        == 0
    )


def _fake_gh(tmp_path: Path, answer: str, code: int = 0) -> Path:
    bindir = tmp_path / f"bin-{answer}-{code}"
    bindir.mkdir()
    gh = bindir / "gh"
    gh.write_text(
        f'#!/bin/sh\necho "$*" >> "{tmp_path}/gh-calls"\necho {answer}\nexit {code}\n'
    )
    gh.chmod(0o755)
    return bindir


def test_visibility_asks_gh_once_and_caches(repo, tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", f"{_fake_gh(tmp_path, 'PUBLIC')}:{os.environ['PATH']}")
    assert commit_msg.visibility() == "PUBLIC"
    assert commit_msg.visibility() == "PUBLIC"
    assert (tmp_path / "gh-calls").read_text().count("\n") == 1
    assert (repo / ".git" / "kilotronic-visibility").read_text().strip() == "PUBLIC"


def test_visibility_unknown_offline(repo, tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", f"{_fake_gh(tmp_path, 'nope', 1)}:{os.environ['PATH']}")
    assert commit_msg.visibility() == "UNKNOWN"
    assert not (repo / ".git" / "kilotronic-visibility").exists()


def test_visibility_from_the_environment(repo, monkeypatch):
    monkeypatch.setenv("KILOTRONIC_VISIBILITY", "public")
    assert commit_msg.visibility() == "PUBLIC"


# --- review findings


def test_trailer_in_a_merge_commit_is_refused(repo):
    _git(repo, "commit", "-q", "--allow-empty", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "-b", "side")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "feat: add x")
    _git(repo, "checkout", "-q", "main")
    _git(
        repo,
        "merge",
        "-q",
        "--no-ff",
        "side",
        "-m",
        "Merge branch 'side'",
        "-m",
        f"{T} https://x",
    )
    assert (
        commit_msg.trailer_main(
            ["--commits", f"{base}..HEAD"], visibility=lambda: "PUBLIC"
        )
        == 1
    )


def test_a_typed_scissors_line_does_not_hide_a_trailer(repo):
    text = f"feat: add y\n\n# ------------------------ >8 ------------------------\n\n{T} https://x\n"
    assert commit_msg.trailer_main([_msg(repo, text)], visibility=lambda: "PUBLIC") == 1
    # git's own scissors, with the diff below it, is cut as git cuts it
    diff = f"feat: add y\n# ------------------------ >8 ------------------------\ndiff --git a/x b/x\n+{T} x\n"
    assert commit_msg.trailer_main([_msg(repo, diff)], visibility=lambda: "PUBLIC") == 0


def test_comment_char_is_honoured(repo):
    _git(repo, "config", "core.commentChar", ";")
    assert (
        commit_msg.subject_main(
            [_msg(repo, "; Please enter the message\nfeat: add x\n")]
        )
        == 0
    )
    assert (
        commit_msg.subject_main([_msg(repo, "# not a comment now\nfeat: add x\n")]) == 1
    )


@pytest.mark.parametrize(
    "message",
    [
        "feat: alias ls to eza",
        "fix: bias the sampler",
        "fix: macOS runner path",
        "ci: caching for uv",
        "fix: bleed the old cache",
        "docs: windows install notes",
        "fix: https redirect",
        "feat: kubernetes manifests",
        "fix: unembed the font",
        "chore: logging tweaks",
        "ci: builds on arm",
        "docs: releases page",
        "fix: checks fail on macOS",
        "fix: changes to x",
    ],
)
def test_subject_allows_words_that_only_look_conjugated(message):
    assert subject_problem(message, TYPES) is None


@pytest.mark.parametrize(
    "message",
    [
        "fix: updated the docs",
        "feat: creates the hook",
        "refactor: moving the checks",
        "fix: removes x",
        "fix: Added y",
    ],
)
def test_subject_refuses_conjugated_commit_verbs(message):
    problem = subject_problem(message, TYPES)
    assert problem is not None and "imperative" in problem


def test_body_with_single_word_trailers(repo):
    assert (
        subject_problem("feat: add x\n\nFixes: #12\n", TYPES, require_body=True)
        is not None
    )


def test_trailer_lines_split_like_git():
    assert trailer_lines(f"feat: a\x0c{T} x\n") == []
    assert trailer_lines(f"feat: a\r\n\r\n{T} x\r\n") == [3]


def test_a_cache_from_the_future_is_not_trusted(repo, tmp_path, monkeypatch):
    cache = repo / ".git" / "kilotronic-visibility"
    cache.write_text("PRIVATE\n")
    future = 4_000_000_000
    os.utime(cache, (future, future))
    monkeypatch.setenv("PATH", f"{_fake_gh(tmp_path, 'PUBLIC')}:{os.environ['PATH']}")
    assert commit_msg.visibility() == "PUBLIC"
