# Copyright (c) 2026 Kilotronic LLC.
# SPDX-License-Identifier: MIT
"""Denylist identity checks, driven through injected environ — never the host git."""

from __future__ import annotations

import pytest

from git_identity.check import identity, main, problems


@pytest.mark.parametrize(
    ("name", "email"),
    [
        ("Ada Lovelace", "ada@ixid.net"),
        ("jasonluther", "jason@kilotronic.com"),
        (
            "github-actions[bot]",
            "41898282+github-actions[bot]@users.noreply.github.com",
        ),
    ],
)
def test_real_identities_are_clean(name: str, email: str) -> None:
    assert problems(name, email, "author") == []


@pytest.mark.parametrize(
    ("name", "email", "needle"),
    [
        ("test", "ada@ixid.net", "name"),
        ("Test", "ada@ixid.net", "name"),
        ("Your Name", "ada@ixid.net", "name"),
        ("Ada", "test@example.com", "email"),
        ("Ada", "ci@example.org", "email"),
        ("Ada", "nobody@example.net", "email"),
        ("Ada", "root@localhost", "email"),
        ("Ada", "user@(none)", "email"),
        ("Ada", "test@ixid.net", "email"),
        ("Ada", "ci@ixid.net", "email"),
        ("Ada", "", "email"),
        ("", "ada@ixid.net", "name"),
    ],
)
def test_placeholders_are_reported(name: str, email: str, needle: str) -> None:
    found = problems(name, email, "author")
    assert found, (name, email)
    assert any(needle in p for p in found)


def test_env_identity_skips_git_var() -> None:
    name, email = identity(
        "AUTHOR",
        environ={
            "GIT_AUTHOR_NAME": "Ada Lovelace",
            "GIT_AUTHOR_EMAIL": "ada@ixid.net",
        },
        git_var=lambda _kind: (_ for _ in ()).throw(AssertionError("git var")),
    )
    assert (name, email) == ("Ada Lovelace", "ada@ixid.net")


def test_git_var_fills_when_env_is_absent() -> None:
    name, email = identity(
        "AUTHOR",
        environ={},
        git_var=lambda _kind: (0, "Ada Lovelace <ada@ixid.net>"),
    )
    assert (name, email) == ("Ada Lovelace", "ada@ixid.net")


def test_git_var_failure_is_an_empty_identity() -> None:
    assert identity("AUTHOR", environ={}, git_var=lambda _kind: (1, "")) == ("", "")


def test_unparseable_ident_exits() -> None:
    with pytest.raises(SystemExit) as exc:
        identity("AUTHOR", environ={}, git_var=lambda _kind: (0, "not-an-ident"))
    assert exc.value.code == 1


def test_main_passes_a_real_identity() -> None:
    env = {
        "GIT_AUTHOR_NAME": "Ada Lovelace",
        "GIT_AUTHOR_EMAIL": "ada@ixid.net",
        "GIT_COMMITTER_NAME": "Ada Lovelace",
        "GIT_COMMITTER_EMAIL": "ada@ixid.net",
    }
    assert main(environ=env) == 0


def test_main_refuses_placeholders(capsys: pytest.CaptureFixture[str]) -> None:
    env = {
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    assert main(environ=env) == 1
    err = capsys.readouterr().err
    assert "commit blocked: placeholder git identity" in err
    assert "git config --global user.name" in err
