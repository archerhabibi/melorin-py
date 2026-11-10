#!/usr/bin/env bash
# T19: read-only report of remote branches that are already merged into main (safe to delete) and of
# unmerged ones with how far ahead they are. It NEVER deletes anything: it prints the commands for you to review.
# Usage: scripts/branch_hygiene.sh [remote=origin] [base=main]
set -euo pipefail
remote="${1:-origin}"; base="${2:-main}"
git fetch --prune --quiet "$remote"
echo "== merged into $remote/$base (candidates for deletion; keep long-lived release branches) =="
git branch -r --merged "$remote/$base" | grep -vE "HEAD|/$base$" | sed 's/^ *//' | while read -r b; do
  echo "git push $remote --delete ${b#"$remote"/}   # last commit: $(git log -1 --format=%cs "$b")"
done
echo
echo "== NOT merged (review before touching) =="
git branch -r --no-merged "$remote/$base" | grep -v HEAD | sed 's/^ *//' | while read -r b; do
  echo "$b  ahead=$(git rev-list --count "$remote/$base..$b")  last=$(git log -1 --format=%cs "$b")"
done
