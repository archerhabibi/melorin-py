#!/usr/bin/env bash
# S104 - safety tag on main + working branch for the cleanup. Idempotent; never moves an existing tag.
# Usage: scripts/s104_safety_tag.sh [tag] [branch]      (push needs credentials in the environment/git config)
#        scripts/s104_safety_tag.sh --rollback [tag]    (deletes the tag from origin; branch kept)
set -Eeuo pipefail
if [[ "${1:-}" == "--rollback" ]]; then
  TAG="${2:-pre-cleanup-2026-10-22}"
  git push --delete origin "$TAG"; git tag -d "$TAG" 2>/dev/null || true; exit 0
fi
TAG="${1:-pre-cleanup-2026-10-22}"; BRANCH="${2:-chore/execution}"
git fetch -q origin --tags
MAIN="$(git rev-parse origin/main)"
if git ls-remote --exit-code --tags origin "refs/tags/$TAG" >/dev/null 2>&1; then
  echo "tag $TAG already on origin (not moved)"
else
  git tag -a "$TAG" "$MAIN" -m "Safety snapshot of main before cleanup (S104)"
  git push origin "refs/tags/$TAG"
fi
if git ls-remote --exit-code --heads origin "$BRANCH" >/dev/null 2>&1; then
  echo "branch $BRANCH already on origin"
else
  git push origin "$MAIN:refs/heads/$BRANCH"
fi
echo "tag $TAG -> $(git rev-parse "$TAG^{commit}" 2>/dev/null || git ls-remote origin "refs/tags/$TAG^{}" | cut -f1)"
echo "origin/main = $MAIN"
