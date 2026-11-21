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

It also checks **commit messages**, over the same commits in CI and as `commit-msg` hooks:

- **commit-subject** (opt-in): the subject reads `<type>: <imperative summary>`, with `type(scope):` and
  `type!:` allowed, and a type from a list you can set (default `feat`, `fix`, `refactor`, `perf`, `test`,
  `docs`, `build`, `ci`, `chore`, `style`, `revert`). "added" or "adds" is refused; say "add". git's own
  `Merge …`, `Revert "…"` and `fixup!`/`squash!`/`amend!` subjects pass. `--require-body` also wants a paragraph
  saying why.
- **session-trailer** (always on): in a **public** repository, no `Claude-Session` trailer line in any commit,
  merge commits included, which links a private agent session. A private repository passes.

The message checks run on pull request and push events, over the commits the author check reads. A dependency
bot's own update that `allow-bots` lets through skips them too; other events (and `commits: identity`) check
only the runner's identity.

It ships as a **GitHub Action**, which checks the commits in a pull request or push, **prek / pre-commit
hooks**, which check this machine and each message before you commit, and a **CLI**.

## Use as a GitHub Action (checks the commits)

```yaml
on: [pull_request]
jobs:
  git-identity:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: kilotronic/git-identity@v2 # pin a commit SHA in production
        with:
          domains: ixid.net, kilotronic.com # optional
```

By default, the Action checks the **authors of the commits the event brings in**:

- On a pull request, every commit in the PR.
- On a push, the newly pushed commits.
- On a push that creates a branch (or tag), its commits that the repository's default branch doesn't have
  yet (as the default branch stands when the job runs). Commits the branch merged in from the default
  branch are not checked again. A new branch with no such commits checks nothing. The default branch's
  own first push (or a repository with no default branch to compare with) checks the whole history,
  since nothing has been checked yet.
- On other events (a deleted branch, schedule, manual runs), the identity git would stamp on the runner.

It fetches the commit history it needs itself, as a cheap fetch of commits only, so the default shallow
checkout is fine.

It skips two things on purpose:

- **Merge commits.**
- **Committers.** GitHub stamps its own committer (`noreply@github.com`) on web-UI, merge and rebase
  commits.

To make it a required check, add the job's name (`git-identity` above) to the branch's ruleset.

Inputs:

| Input            | Default                      | Meaning                                                                                                                                                       |
| ---------------- | ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `domains`        | empty (any)                  | Allowed email domains, separated by commas, spaces or newlines                                                                                                |
| `commits`        | empty (this event's commits) | A git range such as `main..HEAD`, or `identity` to check the identity git would stamp on the runner (the v1 behavior)                                         |
| `allow-bots`     | empty (nobody)               | Dependency bots whose own updates skip the check: `dependabot`, `renovate` (see below)                                                                        |
| `commit-subject` | `false`                      | `true` also checks each commit's subject (see above)                                                                                                          |
| `commit-types`   | empty (the default list)     | The types `commit-subject` allows, separated by commas or spaces                                                                                              |
| `skip`           | empty                        | Checks to skip, by id: only `commit-subject`. The author check and the session trailer check are the floor: naming one warns and it runs; an unknown id fails |
| `token`          | `github.token`               | Used only with `allow-bots`, to ask GitHub which pull request a pushed commit merged                                                                          |
| `domain`         | empty                        | Deprecated v1 alias; it is combined with `domains`                                                                                                            |

### Dependency bots (opt-in)

Dependabot and Renovate author their commits as their GitHub noreply address, which no domain list
contains, so with `domains` set their pull requests fail. `allow-bots` lets a bot's own update through:

```yaml
permissions:
  contents: read
  pull-requests: read # allow-bots: which pull request a pushed commit merged
steps:
  - uses: actions/checkout@v4
  - uses: kilotronic/git-identity@v2
    with:
      domains: ixid.net
      allow-bots: dependabot, renovate
```

The check is skipped only when everything below holds; otherwise, or on any error (git, GitHub's API),
the normal author check runs. A commit that only uses a bot's email is still refused.

- **Pull request:** opened by the bot from its branch (`dependabot/…` or `renovate/…`), this run started
  by the bot, and every new non-merge commit authored by the bot's address and committed by GitHub
  (`noreply@github.com`).
- **Push** (the merge on the default branch): every new non-merge commit authored by the bot's address and
  committed by GitHub, and GitHub links it as the merge commit of a merged pull request the bot opened
  from its branch. This is a squash merge; a merge commit or rebase merge of a bot's pull request is
  checked as usual.

| Bot          | Login                            | Author email                                        | Branch prefix |
| ------------ | -------------------------------- | --------------------------------------------------- | ------------- |
| `dependabot` | `dependabot[bot]`                | `49699333+dependabot[bot]@users.noreply.github.com` | `dependabot/` |
| `renovate`   | `renovate[bot]` (the GitHub App) | `29139614+renovate[bot]@users.noreply.github.com`   | `renovate/`   |

Renovate must use its default `branchPrefix` and commit through the GitHub App (its default), so GitHub
is the committer. `allow-bots` applies only to the event's own commits, not to an explicit `commits`
range. The pre-commit hook and CLI are unaffected.

**v1 → v2:** v1 checked the runner's identity, not the commits. To keep that behavior, add
`commits: identity`.

## Use as a prek or pre-commit hook (checks this machine)

Works with [prek](https://github.com/j178/prek) and with [pre-commit](https://pre-commit.com). In your
`.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/kilotronic/git-identity
    rev: b0d54e809d81cabf61d357cbe519a9b9263b17cb # frozen: v2.4.0
    hooks:
      - id: git-identity
        args: ["--domain=ixid.net,kilotronic.com"] # optional; quoted, or YAML splits the list at the comma
        fail_fast: true
```

The commit-message hooks run at the `commit-msg` stage:

```yaml
default_install_hook_types: [pre-commit, commit-msg]
repos:
  - repo: https://github.com/kilotronic/git-identity
    rev: <commit of the release> # frozen: v2.4.0
    hooks:
      - id: git-identity
      - id: commit-subject
        # args: [--types=feat,fix,docs, --require-body]
      - id: session-trailer
```

`session-trailer` needs the repository's visibility: `$KILOTRONIC_VISIBILITY` when set (the Action passes
the event's), else `gh repo view` once a day, kept in the clone's git directory (`kilotronic-visibility`, the
same file kilotronic/lint's hooks use). Offline or without `gh` the visibility is unknown, and the hook passes
with a note: it refuses only when it knows the repository is public.

Two gaps the hooks can't close, because a hook can't tell `git commit -m` from the editor: with `-m`, git keeps
`#` lines, so a subject typed as `# ...` or a trailer hidden after a fake `commit -v` diff passes the hook. The
Action reads the stored commits and refuses both.

`commit-subject` is opt-in: list the hook, or set the Action's `commit-subject: true`. `skip: commit-subject`
exists for a workflow shared by several repositories that sets `commit-subject: true`: one repository can
leave it out. The session trailer check is a floor check (`public-no-leak`): it can't be skipped.

Then `prek install` (or `pre-commit install`). The `git-identity` hook runs at the `pre-commit` stage, and also at
`pre-merge-commit` and `manual` (`prek run git-identity --hook-stage manual`).

The hook checks the identity git will actually stamp: `GIT_AUTHOR_*` / `GIT_COMMITTER_*` first, then
`git var`. That means `git commit --author` overrides are validated too.

It is `always_run` and doesn't use the changed-file list. Rebase and amend skip pre-commit, so this gates
new commits. Use the Action to catch anything that slips past.

## Use as a CLI

```bash
pip install git+https://github.com/kilotronic/git-identity.git@v2.3.1
check-git-identity                                  # this machine; default identities only
check-git-identity --domain ixid.net,kilotronic.com # also require one of these domains
check-git-identity --commits origin/main..HEAD --domain ixid.net  # judge existing commits' authors
check-commit-subject --commits origin/main..HEAD --types feat,fix  # judge existing commits' subjects
check-session-trailer --commits origin/main..HEAD                  # no Claude-Session line if public
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
