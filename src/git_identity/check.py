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

Optional ``--domain``: each email's domain must also equal it exactly
(case-insensitive; subdomains do not match).
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
    r"@localhost$",
    r"@\(none\)$",
    r"^root@",
    r"^(test|ci|user|admin|nobody|placeholder|changeme)@",
    r"^$",
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
    name: str, email: str, role: str, *, domain: str | None = None
) -> list[str]:
    found: list[str] = []
    if name.lower() in _BAD_NAMES:
        found.append(f"{role} name {name!r} is a placeholder")
    for pat in _BAD_EMAIL_PATTERNS:
        if re.search(pat, email, re.IGNORECASE):
            found.append(f"{role} email {email!r} is a placeholder")
            break
    if domain is not None and email.rpartition("@")[2].lower() != domain:
        found.append(f"{role} email {email!r} is not in domain {domain!r}")
    return found


def _domain(value: str) -> str:
    domain = value.strip().lstrip("@").lower()
    if not domain:
        raise argparse.ArgumentTypeError("must not be empty")
    return domain


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="check-git-identity",
        description="Refuse placeholder git identities and emails outside a domain.",
    )
    parser.add_argument(
        "--domain",
        type=_domain,
        help="also require this email domain, e.g. ixid.net (default: any)",
    )
    return parser.parse_args(argv)


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> int:
    domain = _parse_args(argv).domain
    env = os.environ if environ is None else environ
    found: list[str] = []
    for kind, role in (("AUTHOR", "author"), ("COMMITTER", "committer")):
        name, email = identity(kind, environ=env)
        found.extend(problems(name, email, role, domain=domain))

    if not found:
        return 0

    print("commit blocked: git identity refused", file=sys.stderr)
    for item in found:
        print(f"  - {item}", file=sys.stderr)
    print(
        "\nConfigure a real identity on this machine, then retry:\n"
        '  git config --global user.name  "Your Name"\n'
        f'  git config --global user.email "you@{domain or "your-domain"}"\n'
        "Agent sessions inherit the machine config — set it once per host.\n"
        "(Why: placeholder authors make owner-attribution uncheckable.)",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
