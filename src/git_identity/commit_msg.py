#!/usr/bin/env python3
# Copyright (c) 2026 Kilotronic LLC.
# SPDX-License-Identifier: MIT
"""Commit-message checks, as commit-msg hooks and over a range of commits (what the Action runs).

``check-commit-subject``: the subject reads ``<type>: <imperative summary>`` (``type(scope):`` and ``type!:``
too), with the type from a list (``--types``). ``--require-body`` also wants a paragraph saying why, other than
a closing block of trailers. git's own shapes (``Merge ...``, ``Revert "..."``, ``fixup!``/``squash!``/
``amend!``) pass. Opt-in: list the hook, or set the Action's ``commit-subject: true``; the Action's ``skip: commit-subject``
skips it.

``check-session-trailer``: in a public repository, no ``Claude-Session`` trailer line: it links a private agent
session. Merge commits too. The visibility comes from ``$KILOTRONIC_VISIBILITY`` (the Action passes the
event's), else from ``gh repo view`` once a day, kept in the clone's git directory (``kilotronic-visibility``,
shared with kilotronic/lint). Refused only when the repository is known to be public: offline or without
``gh`` it passes with a note. It is a floor check (``public-no-leak``): the Action's ``skip`` can't skip it.

As a hook each reads the message file git hands it; ``--commits A..B`` checks the commits there.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path

DEFAULT_TYPES = (
    "feat",
    "fix",
    "refactor",
    "perf",
    "test",
    "docs",
    "build",
    "ci",
    "chore",
    "style",
    "revert",
)
_GIT_OWN = re.compile(
    r"^(?:fixup! |squash! |amend! |Merge (?:branch|pull request|remote-tracking branch|tag|commit) |Revert \")"
)
# A trailer: a hyphenated key (Co-Authored-By:) or one of the usual one-word ones. A one-line reason such as
# `Why: the cache leaked.` stays prose.
_TRAILER = re.compile(
    r"^(?:\w+(?:-\w+)+|Fixes|Closes|Resolves|Refs|Ref|See|Bug|Issue): ", re.IGNORECASE
)
_SESSION = re.compile(r"^\s*claude-session\s*:", re.IGNORECASE)
# Common commit verbs: the subject's first word may not be one of these conjugated (added, adds, adding). A
# list rather than a suffix rule, so words that only look conjugated (alias, caching, macOS, windows) pass;
# verbs that are also common nouns (log, test, check, build, change, release, fix) are left out, so
# `fix: tests for x` and `ci: builds on arm` pass.
_VERB_WORDS = (
    "add allow avoid bump clean clarify configure convert correct create define delete deprecate describe "
    "disable document enable ensure expose extend extract generate handle hide ignore implement improve "
    "include increase introduce make migrate move optimise optimize prefer prepare prevent protect rebuild "
    "reduce refactor refuse reject remove rename reorder replace require reset restore restrict retry revert "
    "rework rewrite send simplify skip tidy trim tweak unify update upgrade use validate verify wrap write"
)
_VERBS = set(_VERB_WORDS.split())
_IRREGULAR = {"made", "wrote", "sent"}
CACHE = "kilotronic-visibility"
CACHE_SECONDS = 24 * 3600
VISIBILITIES = ("PUBLIC", "PRIVATE", "INTERNAL")


def comment_char() -> str:
    """git's core.commentChar: `#` by default, and for `auto` (which picks one per message)."""
    out = subprocess.run(
        ["git", "config", "core.commentChar"],
        capture_output=True,
        text=True,
        check=False,
    )
    char = out.stdout.strip()
    return char if char and char != "auto" else "#"


def _lines(text: str) -> list[str]:
    """Lines as git splits them: on newlines only, with a CR before one dropped."""
    lines = [ln.removesuffix("\r") for ln in text.split("\n")]
    return lines[:-1] if lines and lines[-1] == "" else lines


def _cut_diff(lines: list[str], char: str) -> list[str]:
    """Drop git's `commit -v` diff: its scissors line with the diff after it. A typed scissors line stays."""
    scissors = f"{char} ------------------------ >8 ------------------------"
    for i, line in enumerate(lines):
        if line == scissors and any(
            ln.startswith("diff --git ") for ln in lines[i + 1 :]
        ):
            return lines[:i]
    return lines


def cleaned(raw: str) -> str:
    """The message git stores from the hook's file in its default cleanup: comment lines and the diff dropped."""
    char = comment_char()
    return "\n".join(
        ln for ln in _cut_diff(_lines(raw), char) if not ln.startswith(char)
    )


def raw_message(raw: str) -> str:
    """The hook's file with only the diff cut. With `-m`, git keeps comment lines, so a trailer check reads them."""
    return "\n".join(_cut_diff(_lines(raw), comment_char()))


def _paragraphs(message: str) -> list[list[str]]:
    paragraphs: list[list[str]] = [[]]
    for line in _lines(message):
        if line.strip():
            paragraphs[-1].append(line.strip())
        elif paragraphs[-1]:
            paragraphs.append([])
    return [p for p in paragraphs if p]


def _stems(word: str):
    for suffix in ("ing", "ed", "es", "s", "d"):
        if word.endswith(suffix):
            stem = word[: -len(suffix)]
            yield stem
            yield stem + "e"
            if len(stem) > 2 and stem[-1] == stem[-2]:
                yield stem[:-1]  # pinned, mapped
            if stem.endswith("i"):
                yield stem[:-1] + "y"  # simplified, applies


def _not_imperative(word: str) -> bool:
    w = word.lower().strip(",.:;")
    if w in _VERBS:
        return False
    return w in _IRREGULAR or any(stem in _VERBS for stem in _stems(w))


def subject_problem(
    message: str, types: Sequence[str], *, require_body: bool = False
) -> str | None:
    """Why this commit message's subject (or missing body) fails, or None."""
    paragraphs = _paragraphs(message) or [[]]
    subject = " ".join(paragraphs[0])  # git's %s
    if _GIT_OWN.match(subject):
        return None
    if not subject:
        return "empty subject"
    m = re.match(
        r"^(?:" + "|".join(map(re.escape, types)) + r")(?:\([\w./, -]+\))?!?: (\S+)",
        subject,
    )
    if not m:
        return f"subject is not `<type>: <imperative summary>` with a type in {'/'.join(types)}: {subject!r}"
    if _not_imperative(m.group(1)):
        return (
            f"subject is not imperative ({m.group(1)!r}: say what the commit does, e.g. 'add', not 'added'): "
            f"{subject!r}"
        )
    if require_body:
        body = paragraphs[1:]
        if body and all(_TRAILER.match(ln) for ln in body[-1]):
            body.pop()
        if not body:
            return "no body saying why (only a subject and trailers)"
    return None


def trailer_lines(message: str) -> list[int]:
    """1-based numbers of the message's lines that are a Claude-Session trailer."""
    return [i for i, line in enumerate(_lines(message), 1) if _SESSION.match(line)]


def visibility() -> str:
    """PUBLIC, PRIVATE, INTERNAL or UNKNOWN for the repository in the current directory."""
    given = os.environ.get("KILOTRONIC_VISIBILITY", "").strip().upper()
    if given:
        return given
    try:
        git_dir = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "UNKNOWN"
    cache = Path(git_dir) / CACHE
    try:
        if 0 <= time.time() - cache.stat().st_mtime < CACHE_SECONDS:
            cached = cache.read_text().strip()
            if cached in VISIBILITIES:
                return cached
    except OSError:
        pass
    try:
        out = subprocess.run(
            ["gh", "repo", "view", "--json", "visibility", "-q", ".visibility"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "UNKNOWN"
    if out not in VISIBILITIES:
        return "UNKNOWN"
    try:
        cache.write_text(out + "\n")
    except OSError:
        pass
    return out


def _messages(
    args: argparse.Namespace, *, merges: bool = False, raw: bool = False
) -> list[tuple[str, str]]:
    """(short sha, message) for each commit in --commits (merges only when asked), or ("", the hook's message):
    as git stores it by default, or with `raw` only the `commit -v` diff cut."""
    if args.commits:
        out = subprocess.run(
            [
                "git",
                "log",
                "-z",
                *([] if merges else ["--no-merges"]),
                "--format=%h%n%B",
                args.commits,
                "--",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if out.returncode != 0:
            print(f"could not list commits in {args.commits!r}: {out.stderr.strip()}")
            sys.exit(1)
        records = [
            r.strip("\n").partition("\n") for r in out.stdout.split("\0") if r.strip()
        ]
        return [(sha, message) for sha, _, message in records]
    if not args.message_file:
        print("a commit message file or --commits <range> is required")
        sys.exit(2)
    text = Path(args.message_file).read_text(encoding="utf-8", errors="replace")
    return [("", raw_message(text) if raw else cleaned(text))]


def _parser(prog: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=prog)
    parser.add_argument(
        "message_file", nargs="?", help="git's COMMIT_EDITMSG (commit-msg hook)"
    )
    parser.add_argument(
        "--commits", metavar="RANGE", help="check the commits in this range"
    )
    return parser


def subject_main(argv: Sequence[str] | None = None) -> int:
    parser = _parser("check-commit-subject")
    parser.add_argument(
        "--types",
        default=",".join(DEFAULT_TYPES),
        help=f"allowed types, comma-separated (default: {','.join(DEFAULT_TYPES)})",
    )
    parser.add_argument(
        "--require-body", action="store_true", help="also require a body saying why"
    )
    args = parser.parse_args(argv)
    types = tuple(t for t in re.split(r"[,\s]+", args.types) if t)
    bad = [
        (sha, p)
        for sha, message in _messages(args)
        if (p := subject_problem(message, types, require_body=args.require_body))
    ]
    for sha, p in bad:
        print(f"commit {sha}: {p}" if sha else p)
    if bad:
        print(
            "\nWrite the subject as `<type>: <imperative summary>`, e.g. `fix: refuse an empty subject`. "
            f"Types: {', '.join(types)}."
        )
        return 1
    return 0


def trailer_main(
    argv: Sequence[str] | None = None, *, visibility: Callable[[], str] = visibility
) -> int:
    args = _parser("check-session-trailer").parse_args(argv)
    found = [
        (sha, n)
        for sha, message in _messages(args, merges=True, raw=True)
        for n in trailer_lines(message)
    ]
    if not found:
        return 0
    vis = visibility()
    if vis != "PUBLIC":
        if vis == "UNKNOWN":
            print(
                "session trailer: the repository's visibility is unknown (offline, or no gh); not checked"
            )
        return 0
    for sha, n in found:
        print(
            f"commit {sha}: line {n}: a Claude-Session trailer"
            if sha
            else f"line {n}: a Claude-Session trailer"
        )
    print(
        "\nThis repository is public: a Claude-Session line links a private agent session. Remove it\n"
        "(git commit --amend, or git rebase -i for earlier commits) and keep only Co-Authored-By."
    )
    return 1


if __name__ == "__main__":
    # The Action runs this file directly: commit_msg.py subject|trailer [args].
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command not in ("subject", "trailer"):
        print(
            "usage: commit_msg.py subject|trailer [--commits RANGE | MESSAGE_FILE] ...",
            file=sys.stderr,
        )
        sys.exit(2)
    sys.exit(
        subject_main(sys.argv[2:])
        if command == "subject"
        else trailer_main(sys.argv[2:])
    )
