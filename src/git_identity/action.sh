#!/usr/bin/env bash
# GitHub Action entry point: work out which commits this event brings in, make sure their history is present
# (actions/checkout is shallow by default), then run check.py on their authors and commit_msg.py on their
# messages (the subject when asked; no Claude-Session trailer in a public repository). Inputs arrive as env vars (action.yml).
set -euo pipefail

# skip: only commit-subject can be skipped. The author check and session-trailer (public-no-leak) are floor
# checks: naming one warns and it runs. An unknown id fails, so a typo can't look like a skip.
subject="${COMMIT_SUBJECT:-false}"
set -f # the ids are words, never file patterns
skips="${SKIP_CHECKS:-}"
for id in ${skips//,/ }; do
  case "$id" in
    commit-subject)
      [ "$subject" = true ] && echo "commit-subject: skipped (skip: $id)"
      subject=false
      ;;
    session-trailer | public-no-leak | git-identity | real-author)
      echo "::warning::git-identity: $id is a floor check; it can't be skipped, so it runs"
      ;;
    *)
      echo "::error::git-identity: unknown check id in skip: $id (only commit-subject can be skipped)"
      exit 1
      ;;
  esac
done
set +f

zero=0000000000000000000000000000000000000000
range="$COMMITS"
new=""
if [ -z "$range" ]; then
  case "$EVENT" in
    pull_request | pull_request_target) range="$PR_BASE..$PR_HEAD" ;;
    push)
      if [ -z "$PUSH_AFTER" ] || [ "$PUSH_AFTER" = "$zero" ]; then
        range=identity # branch deletion: nothing to check
      elif [ -z "$PUSH_BEFORE" ] || [ "$PUSH_BEFORE" = "$zero" ]; then
        new=true range="$PUSH_AFTER" # new branch: worked out below, once fetched
      else
        range="$PUSH_BEFORE..$PUSH_AFTER"
      fi
      ;;
    *) range=identity ;;
  esac
fi

args=()
for d in $DOMAINS; do args+=(--domain "$d"); done
check=("python3" "$GITHUB_ACTION_PATH/src/git_identity/check.py")

if [ "$range" = identity ]; then
  exec "${check[@]}" ${args[@]+"${args[@]}"}
fi

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  echo "::error::git-identity needs a checkout (run actions/checkout first) to check commits $range"
  exit 1
fi
# Fetch the full commit graph (no trees or blobs, so it's cheap) plus any SHAs the range names.
shas=() # (no mapfile: macOS runners ship bash 3.2)
while read -r sha; do shas+=("$sha"); done < <(grep -oE '[0-9a-f]{40}' <<<"$range" || true)
fetch=(git fetch -q --no-tags --filter=tree:0 origin ${shas[@]+"${shas[@]}"})
if [ "$(git rev-parse --is-shallow-repository)" = true ]; then
  fetch+=(--unshallow)
fi
if [ "${#shas[@]}" -gt 0 ] || [ "$(git rev-parse --is-shallow-repository)" = true ]; then
  "${fetch[@]}"
fi

# A push that created a branch (or tag): check its commits that the default branch doesn't have yet, the rule
# secret-scan's pre-push hook uses. The default branch itself (a first push), or no default branch to compare
# with, checks the whole history: nothing has been checked yet.
if [ -n "$new" ]; then
  # A tag push reports the annotated tag's own id; a commit that can't be found fails here, not as "nothing new".
  if ! after=$(git rev-parse -q --verify "$PUSH_AFTER^{commit}"); then
    echo "::error::git-identity: the pushed commit $PUSH_AFTER is not in this checkout"
    exit 1
  fi
  default="${DEFAULT_BRANCH:-}" tip=""
  # Without PUSH_REF the default branch's own push can't be told apart, so it falls to the whole history.
  if [ -n "$default" ] && [ -n "${PUSH_REF:-}" ] && [ "$PUSH_REF" != "refs/heads/$default" ] \
    && git fetch -q --no-tags --filter=tree:0 origin "+refs/heads/$default:refs/remotes/origin/$default"; then
    tip=$(git rev-parse -q --verify "refs/remotes/origin/$default^{commit}" || true)
  fi
  range="$after"
  if [ -z "$tip" ]; then
    echo "git identity: a new branch with no default branch to compare with; checking its whole history"
  else
    first=$(git rev-list -1 "$tip..$after") # on its own line, so a git error stops the check
    if [ -z "$first" ]; then
      echo "git identity: a new branch with no commits that $default doesn't have (at $tip); nothing to check"
      exit 0
    fi
    range="$tip..$after"
  fi
fi

# allow-bots: a listed bot's own update (its pull request, or the merge of one) skips the author check.
# Only for the event's own commits; bots.py exits non-zero for anything else, and on any error.
if [ -n "${ALLOW_BOTS//[[:space:],]/}" ] && [ -z "$COMMITS" ] \
  && python3 "$GITHUB_ACTION_PATH/src/git_identity/bots.py" --bots "$ALLOW_BOTS" --range "$range"; then
  exit 0
fi

# The authors, then the same commits' messages: every check runs, so one run shows every finding.
bad=0
"${check[@]}" --commits "$range" ${args[@]+"${args[@]}"} || bad=1
msg=("python3" "$GITHUB_ACTION_PATH/src/git_identity/commit_msg.py")
if [ "$subject" = true ]; then
  "${msg[@]}" subject --commits "$range" ${COMMIT_TYPES:+--types "$COMMIT_TYPES"} || bad=1
fi
KILOTRONIC_VISIBILITY="${VISIBILITY:-}" "${msg[@]}" trailer --commits "$range" || bad=1
exit "$bad"
