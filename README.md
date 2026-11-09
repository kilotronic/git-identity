# git-identity

A tiny, stdlib-only gate for git author identities. It does two things:

1. **Always refuses default identities.** These are placeholders like `Test <test@example.com>` or
   `ci <ci@example.com>` that agent sessions stamp when git was never configured, and the
   `<login>@<hostname>` emails git invents when no email is set, such as `jay@Jays-MacBook-Pro.local`,
   `azureuser@vm.….internal.cloudapp.net`, `…@host.tailnet.ts.net` and `ec2-user@….compute.internal`.
2. **Optionally requires a domain from a list.** With `--domain` (or the Action's `domains`), every email
   must be `…@<one of them>` exactly. The match is case-insensitive, and subdomains do not match.

Default identities break attribution: decisions recorded as "owner said" can't be cross-checked against
commit authorship. The tool uses a denylist, not an allowlist, so without a domain list any real identity
passes.

It ships as a **GitHub Action**, which checks the commits in a pull request or push, a **pre-commit hook**,
which checks this machine before you commit, and a **CLI**.

## Use as a GitHub Action (checks the commits)

```yaml
on: [pull_request]
jobs:
  git-identity:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: kilotronic/git-identity@v2   # pin a commit SHA in production
        with:
          domains: ixid.net, kilotronic.com  # optional
```

By default, the Action checks the **authors of the commits the event brings in**:

- On a pull request, every commit in the PR.
- On a push, the newly pushed commits, or only the tip of a newly created branch.

It fetches the commit history it needs itself, as a cheap fetch of commits only, so the default shallow
checkout is fine.

It skips two things on purpose:

- **Merge commits.**
- **Committers.** GitHub stamps its own committer (`noreply@github.com`) on web-UI, merge and rebase
  commits.

To make it a required check, add the job's name (`git-identity` above) to the branch's ruleset.

Inputs:

| Input | Default | Meaning |
| --- | --- | --- |
| `domains` | empty (any) | Allowed email domains, separated by commas, spaces or newlines |
| `commits` | empty (this event's commits) | A git range such as `main..HEAD`, or `identity` to check the identity git would stamp on the runner (the v1 behavior) |
| `domain` | empty | Deprecated v1 alias; it is combined with `domains` |

**v1 → v2:** v1 checked the runner's identity, not the commits. To keep that behavior, add
`commits: identity`.

## Use as a pre-commit hook (checks this machine)

```yaml
repos:
  - repo: https://github.com/kilotronic/git-identity
    # Pin a dotted release tag (v2.0.0), not the floating Action major tag (v2).
    rev: v2.0.0
    hooks:
      - id: git-identity
        args: [--domain=ixid.net,kilotronic.com]  # optional
        fail_fast: true
```

The hook checks the identity git will actually stamp: `GIT_AUTHOR_*` / `GIT_COMMITTER_*` first, then
`git var`. That means `git commit --author` overrides are validated too.

It is `always_run` and doesn't use the changed-file list. Rebase and amend skip pre-commit, so this gates
new commits. Use the Action to catch anything that slips past.

## Use as a CLI

```bash
pip install git+https://github.com/kilotronic/git-identity.git@v2.0.0
check-git-identity                                  # this machine; default identities only
check-git-identity --domain ixid.net,kilotronic.com # also require one of these domains
check-git-identity --commits origin/main..HEAD --domain ixid.net  # judge existing commits' authors
```

`--domain` can be repeated or comma-separated.

Exit codes:

- `0`: pass.
- `1`: a default identity, an email outside the domains, or a range git can't read.
- `2`: an empty `--domain` value.

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
