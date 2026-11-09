#!/usr/bin/env bash
# GitHub Action entry point: work out which commits this event brings in, make sure their history is present
# (actions/checkout is shallow by default), then run check.py on them. Inputs arrive as env vars (action.yml).
set -euo pipefail

zero=0000000000000000000000000000000000000000
range="$COMMITS"
if [ -z "$range" ]; then
  case "$EVENT" in
    pull_request | pull_request_target) range="$PR_BASE..$PR_HEAD" ;;
    push)
      if [ -z "$PUSH_AFTER" ] || [ "$PUSH_AFTER" = "$zero" ]; then
        range=identity # branch deletion: nothing to check
      elif [ -z "$PUSH_BEFORE" ] || [ "$PUSH_BEFORE" = "$zero" ]; then
        range="$PUSH_AFTER^!" # new branch: just its tip
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

exec "${check[@]}" --commits "$range" ${args[@]+"${args[@]}"}
