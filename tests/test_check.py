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
    "email",
    ["ada@ixid.net", "Ada@IXID.NET", "ada.lovelace+git@ixid.net"],
)
def test_email_in_required_domain_is_clean(email: str) -> None:
    assert problems("Ada Lovelace", email, "author", domain="ixid.net") == []


@pytest.mark.parametrize(
    "email",
    [
        "ada@kilotronic.com",
        "ada@mail.ixid.net",
        "ada@ixid.net.evil.com",
        "ada@notixid.net",
        "ixid.net@gmail.com",
    ],
)
def test_email_outside_required_domain_is_reported(email: str) -> None:
    found = problems("Ada Lovelace", email, "author", domain="ixid.net")
    assert any("not in domain 'ixid.net'" in p for p in found), found


def test_domain_check_does_not_mask_placeholders() -> None:
    found = problems("Ada", "test@ixid.net", "author", domain="ixid.net")
    assert any("placeholder" in p for p in found)


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


_ADA_ENV = {
    "GIT_AUTHOR_NAME": "Ada Lovelace",
    "GIT_AUTHOR_EMAIL": "ada@ixid.net",
    "GIT_COMMITTER_NAME": "Ada Lovelace",
    "GIT_COMMITTER_EMAIL": "ada@ixid.net",
}


def test_main_without_a_domain_accepts_any_real_domain() -> None:
    assert main([], environ=_ADA_ENV) == 0


def test_main_without_a_domain_still_refuses_placeholders(
    capsys: pytest.CaptureFixture[str],
) -> None:
    env = {**_ADA_ENV, "GIT_AUTHOR_EMAIL": "test@example.com"}
    assert main([], environ=env) == 1
    assert "you@your-domain" in capsys.readouterr().err


@pytest.mark.parametrize("arg", ["--domain=", "--domain=  ", "--domain=@"])
def test_main_refuses_an_empty_domain(arg: str) -> None:
    with pytest.raises(SystemExit) as exc:
        main([arg], environ=_ADA_ENV)
    assert exc.value.code == 2


def test_main_normalizes_the_domain() -> None:
    assert main(["--domain", "@IXID.net"], environ=_ADA_ENV) == 0


def test_main_refuses_an_email_outside_the_domain(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["--domain", "kilotronic.com"], environ=_ADA_ENV) == 1
    err = capsys.readouterr().err
    assert "not in domain 'kilotronic.com'" in err
    assert "you@kilotronic.com" in err


def test_main_accepts_the_equals_form() -> None:
    assert main(["--domain=ixid.net"], environ=_ADA_ENV) == 0


def test_main_passes_a_real_identity() -> None:
    env = {
        "GIT_AUTHOR_NAME": "Ada Lovelace",
        "GIT_AUTHOR_EMAIL": "ada@ixid.net",
        "GIT_COMMITTER_NAME": "Ada Lovelace",
        "GIT_COMMITTER_EMAIL": "ada@ixid.net",
    }
    assert main(["--domain", "ixid.net"], environ=env) == 0


def test_main_refuses_placeholders(capsys: pytest.CaptureFixture[str]) -> None:
    env = {
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    assert main(["--domain", "example.com"], environ=env) == 1
    err = capsys.readouterr().err
    assert "commit blocked: git identity refused" in err
    assert "git config --global user.name" in err
