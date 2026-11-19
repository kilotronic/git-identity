# Copyright (c) 2026 Kilotronic LLC.
# SPDX-License-Identifier: MIT
"""The opt-in bot exemption: a bot's own update skips the author check, nothing else does."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from git_identity.bots import BOTS, main, own_update, which_bot

DEPENDABOT = BOTS["dependabot"]
RENOVATE = BOTS["renovate"]
GITHUB = "noreply@github.com"
SHA_A = "a" * 40
SHA_B = "b" * 40


def _log(*commits: tuple[str, str, str]):
    out = "".join(
        f"{sha}\0{author}\0{committer}\n" for sha, author, committer in commits
    )
    return lambda _range: (0, out, "")


def _pr(sha: str, bot=DEPENDABOT, **over):
    pr = {
        "merged_at": "2026-01-01T00:00:00Z",
        "merge_commit_sha": sha,
        "user": {"login": bot.login},
        "head": {"ref": bot.branch + "npm/left-pad-1.3.0"},
    }
    pr.update(over)
    return pr


def _pull_request(bot=DEPENDABOT, **over):
    ctx = {
        "event": "pull_request",
        "rev_range": f"{'0' * 39}1..{SHA_A}",
        "pr_user": bot.login,
        "head_ref": bot.branch + "npm/left-pad-1.3.0",
        "actor": bot.login,
        "git_log": _log((SHA_A, bot.email, GITHUB)),
        "pulls_of": lambda _sha: pytest.fail("a pull request does not ask GitHub"),
    }
    ctx.update(over)
    return ctx


def _push(bot=DEPENDABOT, **over):
    ctx = {
        "event": "push",
        "rev_range": f"{SHA_B}..{SHA_A}",
        "pr_user": "",
        "head_ref": "",
        "actor": "someone",  # whoever pressed merge
        "git_log": _log((SHA_A, bot.email, GITHUB)),
        "pulls_of": lambda sha: [_pr(sha, bot)],
    }
    ctx.update(over)
    return ctx


# --- the bots' identities --------------------------------------------------


def test_known_bots() -> None:
    assert DEPENDABOT.login == "dependabot[bot]"
    assert DEPENDABOT.email == "49699333+dependabot[bot]@users.noreply.github.com"
    assert DEPENDABOT.branch == "dependabot/"
    assert RENOVATE.login == "renovate[bot]"
    assert RENOVATE.email == "29139614+renovate[bot]@users.noreply.github.com"
    assert RENOVATE.branch == "renovate/"
    assert DEPENDABOT.committer == RENOVATE.committer == GITHUB


# --- pull requests ---------------------------------------------------------


@pytest.mark.parametrize("bot", [DEPENDABOT, RENOVATE])
def test_a_bots_own_pull_request_is_exempt(bot) -> None:
    assert own_update(bot, **_pull_request(bot))


@pytest.mark.parametrize(
    "over",
    [
        {"pr_user": "mallory"},  # opened by someone else
        {"actor": "mallory"},  # this run started by someone else
        {"head_ref": "feature/bump"},  # not the bot's branch
        {"head_ref": "x-dependabot/npm"},
        {"event": "pull_request_target"},
        {"event": "workflow_dispatch"},
    ],
)
def test_a_pull_request_that_is_not_the_bots_is_not_exempt(over) -> None:
    assert not own_update(DEPENDABOT, **_pull_request(**over))


@pytest.mark.parametrize(
    "commits",
    [
        # a changed email alone never passes: wrong committer
        [(SHA_A, DEPENDABOT.email, DEPENDABOT.email)],
        [(SHA_A, DEPENDABOT.email, "mallory@example.org")],
        # someone else's commit pushed onto the bot's branch
        [(SHA_A, DEPENDABOT.email, GITHUB), (SHA_B, "mallory@example.org", GITHUB)],
        # the other bot's address
        [(SHA_A, RENOVATE.email, GITHUB)],
        # nothing to judge
        [],
    ],
)
def test_a_pull_request_with_other_commits_is_not_exempt(commits) -> None:
    assert not own_update(DEPENDABOT, **_pull_request(git_log=_log(*commits)))


def test_a_git_failure_is_not_exempt() -> None:
    assert not own_update(
        DEPENDABOT, **_pull_request(git_log=lambda _r: (128, "", "bad revision"))
    )


def test_the_email_case_does_not_matter() -> None:
    commits = _log((SHA_A, DEPENDABOT.email.upper(), "NoReply@GitHub.com"))
    assert own_update(DEPENDABOT, **_pull_request(git_log=commits))


# --- pushes (the merge on the default branch) ------------------------------


@pytest.mark.parametrize("bot", [DEPENDABOT, RENOVATE])
def test_the_merge_of_a_bots_pull_request_is_exempt(bot) -> None:
    assert own_update(bot, **_push(bot))


@pytest.mark.parametrize(
    "pulls",
    [
        [],  # GitHub links no pull request
        [_pr(SHA_A, merged_at=None)],  # not merged
        [_pr(SHA_B)],  # merged some other commit
        [_pr(SHA_A, user={"login": "mallory"})],  # opened by someone else
        [_pr(SHA_A, head={"ref": "feature/bump"})],  # not from the bot's branch
        [_pr(SHA_A, user=None, head=None)],
        [_pr(SHA_A, RENOVATE)],  # the other bot's pull request
    ],
)
def test_a_push_not_linked_to_the_bots_merged_pull_request_is_not_exempt(pulls) -> None:
    assert not own_update(DEPENDABOT, **_push(pulls_of=lambda _sha: pulls))


def test_a_push_with_any_other_commit_is_not_exempt() -> None:
    commits = _log(
        (SHA_A, DEPENDABOT.email, GITHUB), (SHA_B, "mallory@example.org", GITHUB)
    )
    assert not own_update(DEPENDABOT, **_push(git_log=commits))


def test_every_pushed_commit_must_be_a_merged_bot_pull_request() -> None:
    commits = _log((SHA_A, DEPENDABOT.email, GITHUB), (SHA_B, DEPENDABOT.email, GITHUB))
    assert not own_update(
        DEPENDABOT, **_push(git_log=commits, pulls_of=lambda _s: [_pr(SHA_A)])
    )
    assert own_update(DEPENDABOT, **_push(git_log=commits, pulls_of=lambda s: [_pr(s)]))


def test_a_github_failure_is_not_exempt() -> None:
    def broken(_sha):
        raise OSError("HTTP Error 403: Resource not accessible by integration")

    assert not own_update(DEPENDABOT, **_push(pulls_of=broken))


# --- which bot, and the command line ---------------------------------------


def test_which_bot_names_the_bot_whose_update_it_is() -> None:
    ctx = _pull_request(RENOVATE)
    assert which_bot(["dependabot", "renovate"], **ctx) == "renovate"
    assert which_bot(["dependabot"], **ctx) is None
    assert which_bot([], **ctx) is None


def test_which_bot_ignores_an_unknown_name(capsys: pytest.CaptureFixture[str]) -> None:
    assert which_bot(["dependabott"], **_pull_request()) is None
    assert "unknown bot 'dependabott'" in capsys.readouterr().out


_ENV = {
    "EVENT": "pull_request",
    "PR_USER": DEPENDABOT.login,
    "HEAD_REF": "dependabot/pip/requests-2.32.0",
    "ACTOR": DEPENDABOT.login,
}


@pytest.mark.parametrize(
    "bots", ["dependabot", "renovate, dependabot", "Dependabot\nrenovate"]
)
def test_main_exits_0_for_an_allowed_bots_update(bots, capsys) -> None:
    rc = main(
        ["--bots", bots, "--range", "x..y"],
        environ=_ENV,
        git_log=_log((SHA_A, DEPENDABOT.email, GITHUB)),
    )
    assert rc == 0
    assert "dependabot's own update" in capsys.readouterr().out


@pytest.mark.parametrize("bots", ["", "renovate"])
def test_main_exits_1_otherwise(bots) -> None:
    rc = main(
        ["--bots", bots, "--range", "x..y"],
        environ=_ENV,
        git_log=_log((SHA_A, DEPENDABOT.email, GITHUB)),
    )
    assert rc == 1


# --- end to end: action.sh with a real repository --------------------------

ROOT = Path(__file__).resolve().parent.parent


def _git(
    cwd: Path, *args: str, author: str = "ada@ixid.net", committer: str = GITHUB
) -> str:
    env = {
        "GIT_AUTHOR_NAME": author.split("@")[0],
        "GIT_AUTHOR_EMAIL": author,
        "GIT_COMMITTER_NAME": "GitHub",
        "GIT_COMMITTER_EMAIL": committer,
        "HOME": str(cwd),
        "PATH": os.environ["PATH"],
    }
    return subprocess.run(
        ["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path):
    """A clone whose origin has a base commit; returns (clone, base sha, commit helper)."""
    origin = tmp_path / "origin"
    origin.mkdir()
    _git(origin, "init", "-q", "-b", "main")
    _git(origin, "commit", "-q", "--allow-empty", "-m", "base")
    clone = tmp_path / "clone"
    _git(tmp_path, "clone", "-q", str(origin), str(clone))
    base = _git(clone, "rev-parse", "HEAD")

    def commit(author: str, committer: str = GITHUB) -> str:
        _git(
            clone,
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "bump",
            author=author,
            committer=committer,
        )
        head = _git(clone, "rev-parse", "HEAD")
        _git(clone, "push", "-q", "origin", f"HEAD:refs/heads/b-{head[:7]}")
        return head

    return clone, base, commit


def _action(
    clone: Path, base: str, head: str, **env: str
) -> subprocess.CompletedProcess:
    full = {
        "PATH": os.environ["PATH"],
        "HOME": str(clone),
        "GITHUB_ACTION_PATH": str(ROOT),
        "DOMAINS": "ixid.net",
        "COMMITS": "",
        "EVENT": "pull_request",
        "PR_BASE": base,
        "PR_HEAD": head,
        "PUSH_BEFORE": "",
        "PUSH_AFTER": "",
        "ALLOW_BOTS": "dependabot",
        "PR_USER": DEPENDABOT.login,
        "HEAD_REF": "dependabot/npm/left-pad-1.3.0",
        "ACTOR": DEPENDABOT.login,
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


def test_action_skips_the_author_check_for_the_bots_pull_request(repo) -> None:
    clone, base, commit = repo
    head = commit(DEPENDABOT.email)
    run = _action(clone, base, head)
    assert run.returncode == 0, run.stderr
    assert "dependabot's own update" in run.stdout


def test_action_without_allow_bots_refuses_the_bot(repo) -> None:
    clone, base, commit = repo
    head = commit(DEPENDABOT.email)
    run = _action(clone, base, head, ALLOW_BOTS="")
    assert run.returncode == 1
    assert "not in domain 'ixid.net'" in run.stderr


def test_action_refuses_a_commit_that_only_claims_the_bots_email(repo) -> None:
    clone, base, commit = repo
    head = commit(DEPENDABOT.email, committer=DEPENDABOT.email)
    run = _action(clone, base, head)
    assert run.returncode == 1
    assert "not in domain 'ixid.net'" in run.stderr


def test_action_refuses_a_bad_email_from_a_person(repo) -> None:
    clone, base, commit = repo
    head = commit("ada@gmail.com")
    run = _action(clone, base, head, PR_USER="ada", ACTOR="ada", HEAD_REF="feature")
    assert run.returncode == 1
    assert "author email 'ada@gmail.com' is not in domain 'ixid.net'" in run.stderr


def test_action_still_passes_a_good_email_with_allow_bots(repo) -> None:
    clone, base, commit = repo
    head = commit("ada@ixid.net")
    run = _action(clone, base, head, PR_USER="ada", ACTOR="ada", HEAD_REF="feature")
    assert run.returncode == 0, run.stderr
    assert "1 commit(s)" in run.stdout
