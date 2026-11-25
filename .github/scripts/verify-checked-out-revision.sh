#!/usr/bin/env bash
set -eu

actual_sha=$(git rev-parse --verify HEAD)
test "$actual_sha" = "$GITHUB_SHA"
test "$GITHUB_SHA" = "${EXPECTED_SHA:-$GITHUB_SHA}"
