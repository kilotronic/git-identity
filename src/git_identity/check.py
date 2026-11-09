#!/usr/bin/env python3
# Copyright (c) 2026 Kilotronic LLC.
# SPDX-License-Identifier: MIT
"""Refuse placeholder git identities and emails outside a required domain.

Machine defaults from agent sessions (``Test <test@example.com>``,
``ci <ci@example.com>``) break attribution: decisions recorded as "owner said"
cannot be cross-checked against commit authorship.

Checks the identity git will actually stamp (``GIT_AUTHOR_*`` /
``GIT_COMMITTER_*`` env overrides first, then ``git var``), so
``git commit --author`` overrides are validated too. Denylist, not allowlist:
any real human identity passes; only obvious placeholders fail. Rebase/amend
rewrites skip pre-commit, so this gates new commits — history is not
retroactively judged.

Optional ``--domain`` (repeatable, or comma-separated): each email's domain
must also equal one of them exactly (case-insensitive; subdomains do not
match).

Optional ``--commits <range>`` (what the GitHub Action passes by default):
judge the *authors* of existing commits in a git revision range instead of
the machine's identity. Merge commits are skipped, and committers are not
judged: GitHub stamps its own committer on web-UI, merge and rebase commits.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence

# Emails that are machine defaults or documentation placeholders, never a
# person. Substring/regex matches on the full address, case-insensitive.
_BAD_EMAIL_PATTERNS = [
    r"@example\.(com|org|net)$",
    r"@localhost(\.localdomain)?$",
    r"@\(none\)$",
    r"^root@",
    r"^(test|ci|user|admin|nobody|placeholder|changeme)@",
    r"^$",
    # Git's fallback when no email is configured: <login>@<hostname>.
    r"@[^@.]+$",  # bare hostname, no dot
    r"\.(local|localdomain|lan|home|internal|localhost)$",  # LAN / mDNS hostnames
    r"\.internal\.cloudapp\.net$",  # Azure VM hostnames
    r"\.compute(-1)?\.internal$",  # AWS EC2 hostnames
    r"\.c\.[a-z0-9-]+\.internal$",  # GCP VM hostnames
    r"\.ts\.net$",  # Tailscale MagicDNS hostnames
]

# Names that are defaults, not people. Full-string matches, case-insensitive.
_BAD_NAMES = {
    "",
    "test",
    "ci",
    "user",
    "root",
    "admin",
    "your name",
    "unknown",
    "nobody",
    "placeholder",
}


def _git_var(kind: str) -> tuple[int, str]:
    result = subprocess.run(
        ["git", "var", f"GIT_{kind}_IDENT"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode, result.stdout.strip()


def identity(
    kind: str,
    *,
    environ: Mapping[str, str] | None = None,
    git_var: Callable[[str], tuple[int, str]] | None = None,
) -> tuple[str, str]:
    """Return (name, email) for ``kind`` (``AUTHOR`` or ``COMMITTER``)."""
    env = os.environ if environ is None else environ
    name = env.get(f"GIT_{kind}_NAME")
    email = env.get(f"GIT_{kind}_EMAIL")
    if name is None or email is None:
        lookup = git_var or _git_var
        code, ident = lookup(kind)
        if code != 0:
            return "", ""
        m = re.match(r"^(.*?) <([^>]*)>", ident)
        if not m:
            print(f"could not parse GIT_{kind}_IDENT: {ident!r}", file=sys.stderr)
            sys.exit(1)
        name = name if name is not None else m.group(1)
        email = email if email is not None else m.group(2)
    return name.strip(), email.strip()


def problems(
    name: str, email: str, role: str, *, domains: Sequence[str] = ()
) -> list[str]:
    found: list[str] = []
    if name.lower() in _BAD_NAMES:
        found.append(f"{role} name {name!r} is a placeholder")
    for pat in _BAD_EMAIL_PATTERNS:
        if re.search(pat, email, re.IGNORECASE):
            found.append(f"{role} email {email!r} is a placeholder")
            break
    if domains and email.rpartition("@")[2].lower() not in domains:
        allowed = " or ".join(repr(d) for d in domains)
        found.append(f"{role} email {email!r} is not in domain {allowed}")
    return found


def _git_log(rev_range: str) -> tuple[int, str, str]:
    result = subprocess.run(
        ["git", "log", "--no-merges", "--format=%H%x00%an%x00%ae", rev_range, "--"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode, result.stdout, result.stderr.strip()


def commit_authors(
    rev_range: str,
    *,
    git_log: Callable[[str], tuple[int, str, str]] | None = None,
) -> list[tuple[str, str, str]]:
    """Return (sha, author name, author email) for each non-merge commit in ``rev_range``."""
    code, out, err = (git_log or _git_log)(rev_range)
    if code != 0:
        print(f"could not list commits in {rev_range!r}: {err}", file=sys.stderr)
        sys.exit(1)
    authors = []
    for line in out.splitlines():
        if line:
            sha, name, email = line.split("\0")
            authors.append((sha, name.strip(), email.strip()))
    return authors


def _domains(value: str) -> list[str]:
    """Parse one --domain value: a domain, or several separated by commas or whitespace."""
    domains = [d.strip().lstrip("@").lower() for d in re.split(r"[,\s]+", value)]
    domains = [d for d in domains if d]
    if not domains:
        raise argparse.ArgumentTypeError("must not be empty")
    return domains


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="check-git-identity",
        description="Refuse placeholder git identities and emails outside a domain.",
    )
    parser.add_argument(
        "--domain",
        type=_domains,
        action="extend",
        default=[],
        help="also require one of these email domains; repeat the flag or separate "
        "with commas, e.g. --domain ixid.net,kilotronic.com (default: any)",
    )
    parser.add_argument(
        "--commits",
        metavar="RANGE",
        help="judge the authors of the commits in this git range (e.g. main..HEAD) "
        "instead of the identity this machine would stamp",
    )
    return parser.parse_args(argv)


def _check_commits(
    rev_range: str,
    domains: Sequence[str],
    *,
    git_log: Callable[[str], tuple[int, str, str]] | None = None,
) -> int:
    authors = commit_authors(rev_range, git_log=git_log)
    found: list[str] = []
    for sha, name, email in authors:
        found.extend(problems(name, email, f"commit {sha[:7]} author", domains=domains))
    if not found:
        print(f"git identity: {len(authors)} commit(s) in {rev_range} OK")
        return 0

    print("git identity refused", file=sys.stderr)
    for item in found:
        print(f"  - {item}", file=sys.stderr)
    print(
        "\nSet a real identity, then rewrite the listed commits and push again:\n"
        f'  git config user.email "you@{domains[0] if domains else "your-domain"}"\n'
        "  git commit --amend --reset-author --no-edit   # last commit only\n"
        "  git rebase -r <base> --exec 'git commit --amend --reset-author --no-edit'\n"
        "(Why: placeholder authors make owner-attribution uncheckable.)",
        file=sys.stderr,
    )
    return 1


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    git_log: Callable[[str], tuple[int, str, str]] | None = None,
) -> int:
    args = _parse_args(argv)
    domains = sorted(set(args.domain))
    if args.commits is not None:
        return _check_commits(args.commits, domains, git_log=git_log)

    env = os.environ if environ is None else environ
    found: list[str] = []
    for kind, role in (("AUTHOR", "author"), ("COMMITTER", "committer")):
        name, email = identity(kind, environ=env)
        found.extend(problems(name, email, role, domains=domains))

    if not found:
        return 0

    print("commit blocked: git identity refused", file=sys.stderr)
    for item in found:
        print(f"  - {item}", file=sys.stderr)
    print(
        "\nConfigure a real identity on this machine, then retry:\n"
        '  git config --global user.name  "Your Name"\n'
        f'  git config --global user.email "you@{domains[0] if domains else "your-domain"}"\n'
        "Agent sessions inherit the machine config — set it once per host.\n"
        "(Why: placeholder authors make owner-attribution uncheckable.)",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
