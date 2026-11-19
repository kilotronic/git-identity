#!/usr/bin/env python3
# Copyright (c) 2026 Kilotronic LLC.
# SPDX-License-Identifier: MIT
"""Opt-in exemption for dependency bots' own updates (the Action's ``allow-bots``).

Dependabot and Renovate author their commits as their GitHub noreply address,
which no domain list contains, so their pull requests fail the author check.
With ``allow-bots``, a bot's update skips the check, but only when all of
these hold, so a commit that merely claims a bot's email is still judged:

- on a pull request: the pull request was opened by the bot from a branch
  with the bot's prefix, this run was started by the bot, and every new
  non-merge commit is authored by the bot's address and committed by GitHub;
- on a push (the merge on the default branch): every new non-merge commit is
  authored by the bot's address and committed by GitHub, and GitHub says it
  is the merge commit of a merged pull request the bot opened from its branch
  (needs a token with ``pull-requests: read``).

Anything else, or any error on the way (git, GitHub's API), means the normal
author check runs. Exit status: 0 = a listed bot's own update, 1 = not.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

GITHUB_COMMITTER = "noreply@github.com"


@dataclass(frozen=True)
class Bot:
    login: str  # the GitHub App's bot user
    email: str  # its commits' author email
    branch: str  # the prefix of the branches it opens pull requests from
    committer: str = GITHUB_COMMITTER  # both commit through GitHub's API


BOTS = {
    "dependabot": Bot(
        "dependabot[bot]",
        "49699333+dependabot[bot]@users.noreply.github.com",
        "dependabot/",
    ),
    "renovate": Bot(
        "renovate[bot]",
        "29139614+renovate[bot]@users.noreply.github.com",
        "renovate/",
    ),
}

GitLog = Callable[[str], tuple[int, str, str]]
PullsOf = Callable[[str], list[dict]]


def _git_log(rev_range: str) -> tuple[int, str, str]:
    result = subprocess.run(
        ["git", "log", "--no-merges", "--format=%H%x00%ae%x00%ce", rev_range, "--"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode, result.stdout, result.stderr.strip()


def own_update(
    bot: Bot,
    *,
    event: str,
    rev_range: str,
    pr_user: str,
    head_ref: str,
    actor: str,
    git_log: GitLog,
    pulls_of: PullsOf,
) -> bool:
    """Is every commit in ``rev_range`` ``bot``'s own update (see the module notes)?"""
    if event == "pull_request":
        if not (
            pr_user == bot.login
            and actor == bot.login
            and head_ref.startswith(bot.branch)
        ):
            return False
    elif event != "push":
        return False
    code, out, _err = git_log(rev_range)
    if code != 0:
        return False
    commits = [line.split("\0") for line in out.splitlines() if line]
    if not commits or any(
        len(c) != 3
        or c[1].lower() != bot.email.lower()
        or c[2].lower() != bot.committer
        for c in commits
    ):
        return False
    if event == "push":
        try:
            return all(_merged_by(bot, sha, pulls_of(sha)) for sha, *_ in commits)
        except Exception:  # noqa: BLE001 - any failure to ask GitHub means the check runs
            return False
    return True


def _merged_by(bot: Bot, sha: str, pulls: list[dict]) -> bool:
    return any(
        p.get("merged_at")
        and p.get("merge_commit_sha") == sha
        and (p.get("user") or {}).get("login") == bot.login
        and (p.get("head") or {}).get("ref", "").startswith(bot.branch)
        for p in pulls
    )


def which_bot(names: Sequence[str], **context) -> str | None:
    """The first of ``names`` whose own update this is, or None."""
    for name in names:
        bot = BOTS.get(name)
        if bot is None:
            known = ", ".join(BOTS)
            print(
                f"::warning::git-identity: unknown bot {name!r} in allow-bots (known: {known})"
            )
            continue
        if own_update(bot, **context):
            return name
    return None


def github_pulls_of(environ: Mapping[str, str]) -> PullsOf:
    """The pull requests GitHub links to a commit (needs ``pull-requests: read``)."""

    def pulls_of(sha: str) -> list[dict]:
        api = environ.get("GITHUB_API_URL", "https://api.github.com")
        url = f"{api}/repos/{environ['GITHUB_REPOSITORY']}/commits/{sha}/pulls"
        request = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {environ['GITHUB_TOKEN']}",
                "Accept": "application/vnd.github+json",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)

    return pulls_of


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    git_log: GitLog | None = None,
    pulls_of: PullsOf | None = None,
) -> int:
    parser = argparse.ArgumentParser(prog="git-identity-bots")
    parser.add_argument(
        "--bots", default="", help="bot names, e.g. 'dependabot, renovate'"
    )
    parser.add_argument("--range", required=True, help="the event's commits")
    args = parser.parse_args(argv)
    env = os.environ if environ is None else environ
    names = [n.lower() for n in re.split(r"[,\s]+", args.bots) if n]
    bot = which_bot(
        names,
        event=env.get("EVENT", ""),
        rev_range=args.range,
        pr_user=env.get("PR_USER", ""),
        head_ref=env.get("HEAD_REF", ""),
        actor=env.get("ACTOR", ""),
        git_log=git_log or _git_log,
        pulls_of=pulls_of or github_pulls_of(env),
    )
    if bot is None:
        if names:
            print("git identity: not an allowed bot's own update; checking the authors")
        return 1
    print(f"git identity: {bot}'s own update; the author check is skipped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
