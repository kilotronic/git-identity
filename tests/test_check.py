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
    assert problems("Ada Lovelace", email, "author", domains=["ixid.net"]) == []


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
    found = problems("Ada Lovelace", email, "author", domains=["ixid.net"])
    assert any("not in domain 'ixid.net'" in p for p in found), found


def test_domain_check_does_not_mask_placeholders() -> None:
    found = problems("Ada", "test@ixid.net", "author", domains=["ixid.net"])
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
        # Git's <login>@<hostname> fallback when no email is configured.
        ("Jay", "jay@Jays-MacBook-Pro.local", "email"),
        ("Jay", "jay@jays-mbp", "email"),
        ("Jay", "jay@box.localdomain", "email"),
        ("Jay", "jay@box.lan", "email"),
        (
            "Yao",
            "azureuser@oa-shell.he2uy4z0vbxubjlxbr405flr3d.bx.internal.cloudapp.net",
            "email",
        ),
        ("Yao", "azureuser@oa-shell.tail3d71ab.ts.net", "email"),
        ("Ec2", "ec2-user@ip-10-0-0-1.ec2.internal", "email"),
        ("Ec2", "ec2-user@ip-10-0-0-1.us-west-2.compute.internal", "email"),
        ("Gcp", "me@vm-1.c.my-project.internal", "email"),
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


def _log(*commits: tuple[str, str, str]):
    out = "".join(f"{sha}\0{name}\0{email}\n" for sha, name, email in commits)
    return lambda _range: (0, out, "")


_GOOD = ("a" * 40, "Ada Lovelace", "ada@ixid.net")
_BAD = ("b" * 40, "test", "test@example.com")
_OUTSIDE = ("c" * 40, "Ada Lovelace", "ada@gmail.com")


def test_commits_mode_passes_real_authors(capsys: pytest.CaptureFixture[str]) -> None:
    assert (
        main(["--commits", "main..HEAD", "--domain", "ixid.net"], git_log=_log(_GOOD))
        == 0
    )
    assert "1 commit(s) in main..HEAD OK" in capsys.readouterr().out


def test_commits_mode_ignores_the_machine_identity() -> None:
    env = {k: "test@example.com" if k.endswith("EMAIL") else "test" for k in _ADA_ENV}
    assert main(["--commits", "x..y"], environ=env, git_log=_log(_GOOD)) == 0


def test_commits_mode_names_each_bad_commit(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(
        ["--commits", "x..y", "--domain", "ixid.net"],
        git_log=_log(_GOOD, _BAD, _OUTSIDE),
    )
    err = capsys.readouterr().err
    assert rc == 1
    assert "commit bbbbbbb author email 'test@example.com' is a placeholder" in err
    assert (
        "commit ccccccc author email 'ada@gmail.com' is not in domain 'ixid.net'" in err
    )
    assert "aaaaaaa" not in err
    assert "--reset-author" in err


def test_commits_mode_with_an_empty_range_passes() -> None:
    assert main(["--commits", "x..x"], git_log=_log()) == 0


def test_commits_mode_exits_when_git_log_fails(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--commits", "nope"], git_log=lambda _r: (128, "", "bad revision 'nope'"))
    assert exc.value.code == 1
    assert "bad revision" in capsys.readouterr().err


def test_commits_mode_against_a_real_repository(tmp_path, monkeypatch) -> None:
    import subprocess

    def git(
        *args: str, email: str = "ada@ixid.net", name: str = "Ada Lovelace"
    ) -> None:
        env = {
            "GIT_AUTHOR_NAME": name,
            "GIT_AUTHOR_EMAIL": email,
            "GIT_COMMITTER_NAME": "GitHub",
            "GIT_COMMITTER_EMAIL": "noreply@github.com",
            "HOME": str(tmp_path),
            "PATH": os.environ["PATH"],
        }
        subprocess.run(
            ["git", *args], cwd=tmp_path, env=env, check=True, capture_output=True
        )

    import os

    git("init", "-q", "-b", "main")
    git(
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "base",
        email="test@example.com",
        name="test",
    )
    git("tag", "base")
    git("commit", "-q", "--allow-empty", "-m", "good")
    monkeypatch.chdir(tmp_path)
    # The committer (noreply@github.com) and the commit before the range are not judged.
    assert main(["--commits", "base..HEAD", "--domain", "ixid.net"]) == 0
    git("commit", "-q", "--allow-empty", "-m", "bad", email="ada@gmail.com")
    assert main(["--commits", "base..HEAD", "--domain", "ixid.net"]) == 1


@pytest.mark.parametrize("email", ["ada@ixid.net", "ada@KILOTRONIC.com"])
def test_any_domain_in_the_list_is_clean(email: str) -> None:
    assert (
        problems("Ada", email, "author", domains=["ixid.net", "kilotronic.com"]) == []
    )


def test_email_outside_every_listed_domain_names_them_all() -> None:
    found = problems(
        "Ada", "ada@gmail.com", "author", domains=["ixid.net", "kilotronic.com"]
    )
    assert found == [
        "author email 'ada@gmail.com' is not in domain 'ixid.net' or 'kilotronic.com'"
    ]


@pytest.mark.parametrize(
    "args",
    [
        ["--domain", "kilotronic.com,ixid.net"],
        ["--domain", "kilotronic.com", "--domain", "ixid.net"],
        ["--domain", " kilotronic.com  ixid.net "],
        ["--domain=@KILOTRONIC.com,", "--domain=ixid.net"],
    ],
)
def test_main_accepts_a_domain_list(args: list[str]) -> None:
    assert main(args, environ=_ADA_ENV) == 0


def test_main_refuses_an_email_outside_the_domain_list(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert (
        main(["--domain", "kilotronic.com,patentoaresponse.com"], environ=_ADA_ENV) == 1
    )
    assert (
        "not in domain 'kilotronic.com' or 'patentoaresponse.com'"
        in capsys.readouterr().err
    )
