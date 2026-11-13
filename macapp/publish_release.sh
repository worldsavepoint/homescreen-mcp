#!/usr/bin/env bash
# Publish the verified assets for the exact commit built by CI.
set -euo pipefail

: "${GH_REPO:?Set GH_REPO}" "${RELEASE_TAG:?Set RELEASE_TAG}" "${RELEASE_TARGET:?Set RELEASE_TARGET}"
assets_dir=${1:?Supply the release assets directory}
notes_file=$(cd "$(dirname "${2:?Supply the release notes file}")" && pwd)/$(basename "$2")
cd "$assets_dir"
assets=("./ios-homescreen-organizer-${RELEASE_TAG#v}-macos-arm64.dmg"
        "./ios-homescreen-organizer-${RELEASE_TAG#v}-macos-arm64.zip"
        "./ios-homescreen-organizer-${RELEASE_TAG#v}-macos-x86_64.dmg"
        "./ios-homescreen-organizer-${RELEASE_TAG#v}-macos-x86_64.zip" "SHA256SUMS.txt")
for asset in "${assets[@]}"; do test -f "$asset"; done
shasum -a 256 --check SHA256SUMS.txt

releases=$(gh api --paginate "repos/$GH_REPO/releases?per_page=100" \
  --jq '.[] | [.tag_name, .draft] | @tsv')
draft=
while IFS=$'\t' read -r tag is_draft; do
  if [[ "$tag" == "$RELEASE_TAG" ]]; then draft=$is_draft; fi
done <<< "$releases"
if [[ "$draft" == false ]]; then
  echo "$RELEASE_TAG is published. Increment project.version for the next release."
  exit 0
fi

refs=$(gh api "repos/$GH_REPO/git/matching-refs/tags/$RELEASE_TAG" --jq '.[].ref')
while IFS= read -r ref; do
  if [[ "$ref" == "refs/tags/$RELEASE_TAG" ]]; then
    target=$(gh api "repos/$GH_REPO/commits/$RELEASE_TAG" --jq .sha)
    if [[ "$target" != "$RELEASE_TARGET" ]]; then
      echo "Set a new project version: $RELEASE_TAG points to another commit." >&2
      exit 1
    fi
  fi
done <<< "$refs"

prerelease=false
if [[ "$RELEASE_TAG" == *-* ]]; then prerelease=true; fi
if [[ "$draft" == true ]]; then
  gh release upload "$RELEASE_TAG" --clobber "${assets[@]}"
  gh release edit "$RELEASE_TAG" --draft=false --target "$RELEASE_TARGET" \
    --title "iOS Home Screen Organizer $RELEASE_TAG" --notes-file "$notes_file" \
    --prerelease="$prerelease"
else
  gh release create "$RELEASE_TAG" --target "$RELEASE_TARGET" \
    --title "iOS Home Screen Organizer $RELEASE_TAG" --notes-file "$notes_file" \
    --prerelease="$prerelease" "${assets[@]}"
fi
