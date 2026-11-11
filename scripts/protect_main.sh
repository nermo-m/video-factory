#!/usr/bin/env bash
# Switch on the repository settings from design doc sections 13 and 14.3:
#
#   - main is protected: pull requests only, all ten CI jobs green, linear history,
#     no force pushes, no deletion
#   - squash merges only, auto-merge allowed, merged branches deleted
#   - secret scanning and push protection on
#
# Run it once, after the repository exists on GitHub and CI has run at least once:
#
#   scripts/protect_main.sh nermo-m/video-factory
#
# It needs the GitHub CLI signed in as an owner of the repository. It is safe to run again.
set -euo pipefail

repo="${1:?Usage: scripts/protect_main.sh <owner>/<repository>}"

echo "Merge settings for ${repo}"
gh repo edit "${repo}" \
  --enable-auto-merge \
  --enable-squash-merge \
  --enable-merge-commit=false \
  --enable-rebase-merge=false \
  --delete-branch-on-merge

echo "Secret scanning and push protection"
gh api --method PATCH "repos/${repo}" --silent --input - <<'JSON'
{
  "security_and_analysis": {
    "secret_scanning": { "status": "enabled" },
    "secret_scanning_push_protection": { "status": "enabled" }
  }
}
JSON

echo "Branch protection for main"
# The contexts are the job names in .github/workflows/ci.yml. build-images is a matrix,
# so it reports one check per image.
gh api --method PUT "repos/${repo}/branches/main/protection" --silent --input - <<'JSON'
{
  "required_status_checks": {
    "strict": true,
    "contexts": [
      "lint-types",
      "unit",
      "integration",
      "render",
      "e2e-demo",
      "secret-scan",
      "asset-licence",
      "deps-audit",
      "build-images (web)",
      "build-images (api)",
      "build-images (worker)",
      "commit-lint"
    ]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": null,
  "restrictions": null,
  "required_linear_history": true,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "required_conversation_resolution": true
}
JSON

echo "Done. Check: gh api repos/${repo}/branches/main/protection --jq '.required_status_checks.contexts'"
