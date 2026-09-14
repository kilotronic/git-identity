# git-identity

A tiny, stdlib-only gate that **refuses placeholder git author identities**.

Agent sessions that never configured git stamp commits as `Test <test@example.com>`
or `ci <ci@example.com>`. That breaks attribution: decisions recorded as "owner
said" cannot be cross-checked against commit authorship.

Denylist, not allowlist: any real human identity passes. Only obvious placeholders
fail. Checks the identity git will actually stamp (`GIT_AUTHOR_*` /
`GIT_COMMITTER_*` first, then `git var`), so `git commit --author` overrides are
validated too.

Ships as a **pre-commit hook**, a **GitHub Action**, and a **CLI**.

## Use as a pre-commit hook

```yaml
repos:
  - repo: https://github.com/kilotronic/git-identity
    # Pin a dotted release tag (v1.0.0), not the floating Action major tag (v1).
    rev: v1.0.0
    hooks:
      - id: git-identity
        fail_fast: true
```

The hook is `always_run` and does not consume the changed-file list. Rebase and
amend skip pre-commit, so this gates new commits — history is not retroactively
judged.

## Use as a GitHub Action

Useful to prove a runner's identity is configured. Skip it in CI that only
_replays_ already-authored commits (the hook inspects the machine, not the
commit object).

```yaml
- uses: actions/checkout@v4
- uses: kilotronic/git-identity@v1
```

Pin a commit SHA in production (Renovate's `pinGitHubActionDigests` does this).

## Use as a CLI

```bash
pip install git+https://github.com/kilotronic/git-identity.git@v1.0.0
check-git-identity
```

Exit codes: `0` pass, `1` placeholder identity.

Configure a real identity, then retry:

```bash
git config --global user.name  "Your Name"
git config --global user.email "you@your-domain"
```

## Development

```bash
pip install -e ".[dev]"
pytest -q
ruff check .
```

## License

MIT — see [LICENSE](LICENSE).
