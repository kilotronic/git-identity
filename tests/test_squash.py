# Copyright (c) 2026 Kilotronic LLC.
# SPDX-License-Identifier: MIT
"""squash-bots: a listed bot's squash merge on a push is judged by its pull request's own commits."""

from __future__ import annotations

import pytest

from git_identity.bots import squash_authors

AGENT = "12345+acme-agents[bot]@users.noreply.github.com"
GITHUB = "noreply@github.com"
SHA_A = "a" * 40
SHA_B = "b" * 40
ADA = ("c" * 40, "Ada", "ada@ixid.net")
BOB = ("d" * 40, "Bob", "bob@ixid.net")


def _log(*commits: tuple[str, str, str, str]):
    out = "".join(
        f"{sha}\0{name}\0{author}\0{committer}\n"
        for sha, name, author, committer in commits
    )
    return lambda _range: (0, out, "")


def _pr(sha: str, number: int = 7, **over):
    pr = {
        "number": number,
        "merged_at": "2026-01-01T00:00:00Z",
        "merge_commit_sha": sha,
    }
    pr.update(over)
    return pr


def _authors(*, logins=("acme-agents",), git_log=None, pulls_of=None, pr_commits=None):
    return squash_authors(
        logins,
        f"{SHA_B}..{SHA_A}",
        git_log=git_log or _log((SHA_A, "acme-agents[bot]", AGENT, GITHUB)),
        pulls_of=pulls_of or (lambda sha: [_pr(sha)]),
        pr_commits=pr_commits or (lambda _n: [ADA, BOB]),
    )


def test_a_bots_squash_merge_is_judged_by_its_pull_requests_commits() -> None:
    assert _authors() == [ADA, BOB]


def test_the_login_may_be_given_with_its_bot_suffix() -> None:
    assert _authors(logins=("acme-agents[bot]",)) == [ADA, BOB]


def test_a_persons_commit_is_judged_as_itself() -> None:
    log = _log((SHA_A, "Mallory", "mallory@example.org", GITHUB))
    assert _authors(git_log=log) == [(SHA_A, "Mallory", "mallory@example.org")]


@pytest.mark.parametrize(
    "author, committer",
    [
        (
            AGENT,
            AGENT,
        ),  # not committed by GitHub: a commit that only claims the address
        (AGENT, "mallory@example.org"),
        ("12345+other-bot[bot]@users.noreply.github.com", GITHUB),  # a bot not listed
        (
            "acme-agents[bot]@users.noreply.github.com",
            GITHUB,
        ),  # not GitHub's noreply form
        ("12345+acme-agents[bot]@users.noreply.github.com.evil", GITHUB),
    ],
)
def test_anything_but_the_listed_bots_github_commit_is_judged_as_itself(
    author, committer
) -> None:
    log = _log((SHA_A, "x", author, committer))
    assert _authors(git_log=log) == [(SHA_A, "x", author)]


@pytest.mark.parametrize(
    "pulls",
    [
        [],  # GitHub links no pull request
        [_pr(SHA_A, merged_at=None)],  # not merged
        [_pr(SHA_B)],  # merged some other commit
    ],
)
def test_a_commit_that_is_not_a_pull_requests_merge_is_judged_as_itself(pulls) -> None:
    assert _authors(pulls_of=lambda _sha: pulls) == [(SHA_A, "acme-agents[bot]", AGENT)]


def test_a_pull_request_with_no_commits_judges_the_squash_itself() -> None:
    assert _authors(pr_commits=lambda _n: []) == [(SHA_A, "acme-agents[bot]", AGENT)]


def test_a_github_failure_judges_the_squash_itself() -> None:
    def broken(_x):
        raise OSError("HTTP Error 403: Resource not accessible by integration")

    expected = [(SHA_A, "acme-agents[bot]", AGENT)]
    assert _authors(pulls_of=broken) == expected
    assert _authors(pr_commits=broken) == expected


def test_a_bad_commit_in_the_pull_request_is_judged() -> None:
    bad = ("e" * 40, "test", "test@example.com")
    assert _authors(pr_commits=lambda _n: [ADA, bad]) == [ADA, bad]


def test_each_pushed_commit_is_judged_on_its_own() -> None:
    log = _log(
        (SHA_A, "acme-agents[bot]", AGENT, GITHUB),
        (SHA_B, "Mallory", "mallory@example.org", GITHUB),
    )
    assert _authors(git_log=log) == [
        ADA,
        BOB,
        (SHA_B, "Mallory", "mallory@example.org"),
    ]


def test_the_merged_pull_request_is_the_one_asked_for() -> None:
    asked = []
    _authors(
        pulls_of=lambda sha: [_pr(SHA_B, 3), _pr(sha, 9)],
        pr_commits=lambda n: asked.append(n) or [ADA],
    )
    assert asked == [9]


def test_a_git_failure_stops() -> None:
    with pytest.raises(SystemExit):
        _authors(git_log=lambda _r: (128, "", "bad revision"))
