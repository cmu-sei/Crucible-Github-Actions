#!/usr/bin/env bash
# Tests the input validation of .github/workflows/npm-release.yaml by
# extracting the `run:` body of the `validate` step and running it locally
# against a temporary GITHUB_OUTPUT file.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKFLOW="$ROOT/.github/workflows/npm-release.yaml"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# Print the de-indented `run: |` body of the step whose `id:` is $1 (same
# extraction rules as tests/codeql-plan.test.sh).
extract_step() {
  awk -v want="$1" '
    /^      - / { in_step = 0 }
    $0 ~ "^        id: " want "$" { in_step = 1; next }
    in_step && /^        run: \|$/ { in_run = 1; next }
    in_run {
      if ($0 ~ /^      - / || ($0 !~ /^[[:space:]]*$/ && $0 !~ /^          /)) { exit }
      print
    }
  ' "$WORKFLOW" | sed -e 's/^          //'
}

extract_step validate > "$TMP/validate.sh"
if ! grep -q 'GITHUB_OUTPUT' "$TMP/validate.sh" || grep -q '^ *# ' "$TMP/validate.sh"; then
  echo "FAIL extract validate step (empty or polluted extraction)"; exit 1
fi

pass=0; fail=0
OUT="$TMP/out"; ERR="$TMP/err"
# run_step VAR=value ...  -> sets $rc; output in $OUT, stderr+stdout in $ERR
run_step() {
  : > "$OUT"
  env -i PATH="$PATH" GITHUB_OUTPUT="$OUT" VERSION=1.2.3 DIST_TAG= AUTH_MODE=api-key \
    PUBLISH_PATH='dist/pkg-{version}.tgz' COMMIT_VERSION=false DRY_RUN=false REF_TYPE=branch REF=refs/heads/main "$@" \
    bash "$TMP/validate.sh" > "$ERR" 2>&1
  rc=$?
}
out_val() { sed -n "s/^$1=//p" "$OUT"; }
check() { # check <name> <condition-command...>
  local name="$1"; shift
  if "$@"; then echo "PASS $name"; pass=$((pass + 1)); else echo "FAIL $name"; sed 's/^/    | /' "$ERR"; fail=$((fail + 1)); fi
}

t() { run_step VERSION=1.2.3; [ "$rc" = 0 ] && [ "$(out_val version)" = 1.2.3 ]; }
check "version: 1.2.3 accepted" t

t() { run_step VERSION=v2.0.0-rc.1 DIST_TAG=next; [ "$rc" = 0 ] && [ "$(out_val version)" = 2.0.0-rc.1 ]; }
check "version: leading v stripped (v2.0.0-rc.1 -> 2.0.0-rc.1)" t

t() { run_step 'VERSION=1.2.3;id'; [ "$rc" = 1 ] && grep -q "is not a SemVer version" "$ERR" && [ ! -s "$OUT" ]; }
check "version: shell metacharacters rejected" t

t() { run_step 'VERSION= 1.2.3'; [ "$rc" = 1 ] && grep -q "is not a SemVer version" "$ERR" && [ ! -s "$OUT" ]; }
check "version: leading space rejected" t

t() { run_step DIST_TAG=next; [ "$rc" = 0 ] && [ "$(out_val version)" = 1.2.3 ]; }
check "dist-tag: next accepted" t

t() { run_step VERSION=2.0.0-rc.1; [ "$rc" = 1 ] && grep -q "needs a dist-tag" "$ERR" && [ ! -s "$OUT" ]; }
check "dist-tag: prerelease without dist-tag rejected" t

t() { run_step VERSION=1.2.3+build.5; [ "$rc" = 1 ] && grep -q "has SemVer build metadata" "$ERR" && [ ! -s "$OUT" ]; }
check "version: build metadata rejected" t

t() { run_step VERSION=1.2.3-rc.1 DIST_TAG=next; [ "$rc" = 0 ] && [ "$(out_val version)" = 1.2.3-rc.1 ]; }
check "version: prerelease 1.2.3-rc.1 accepted" t

t() { run_step VERSION=1.2.3-0 DIST_TAG=next; [ "$rc" = 0 ] && [ "$(out_val version)" = 1.2.3-0 ]; }
check "version: numeric prerelease 1.2.3-0 accepted" t

t() { run_step VERSION=1.2.3-rc..1 DIST_TAG=next; [ "$rc" = 1 ] && grep -q "is not a SemVer version" "$ERR" && [ ! -s "$OUT" ]; }
check "version: empty prerelease identifier (1.2.3-rc..1) rejected" t

t() { run_step VERSION=1.2.3-01 DIST_TAG=next; [ "$rc" = 1 ] && grep -q "is not a SemVer version" "$ERR" && [ ! -s "$OUT" ]; }
check "version: leading-zero numeric prerelease (1.2.3-01) rejected" t

t() { run_step 'DIST_TAG=Bad Tag'; [ "$rc" = 1 ] && grep -q "invalid dist-tag" "$ERR" && [ ! -s "$OUT" ]; }
check "dist-tag: 'Bad Tag' rejected" t

t() { run_step AUTH_MODE=bogus; [ "$rc" = 1 ] && grep -q "auth-mode must be api-key or trusted" "$ERR" && [ ! -s "$OUT" ]; }
check "auth-mode: bogus rejected" t

# ---- commit-version ref guard ----
t() { run_step COMMIT_VERSION=true; [ "$rc" = 0 ]; }
check "commit-version: branch ref accepted" t

t() { run_step COMMIT_VERSION=true REF_TYPE=tag REF=refs/tags/v1.2.3
  [ "$rc" = 1 ] && grep -q "::error::commit-version requires a branch-triggered run (workflow_dispatch or push); got ref_type=tag" "$ERR" && [ ! -s "$OUT" ]; }
check "commit-version: tag ref rejected" t

t() { run_step COMMIT_VERSION=true REF_TYPE=branch REF=refs/pull/7/merge; [ "$rc" = 1 ] && grep -q "commit-version requires a branch-triggered run" "$ERR"; }
check "commit-version: pull request merge ref rejected" t

t() { run_step COMMIT_VERSION=true DRY_RUN=true REF_TYPE=tag REF=refs/tags/v1.2.3; [ "$rc" = 0 ]; }
check "commit-version: tag ref allowed in dry-run" t

# ---- publish-path ----
t() { run_step VERSION=v1.2.3; [ "$rc" = 0 ] && [ "$(out_val publish_path)" = ./dist/pkg-1.2.3.tgz ]; }
check "publish-path: {version} substituted, ./ prefixed" t

t() { run_step PUBLISH_PATH=dist/console-forge; [ "$rc" = 0 ] && [ "$(out_val publish_path)" = ./dist/console-forge ]; }
check "publish-path: bare relative dir gets ./ (not a GitHub shorthand)" t

t() { run_step PUBLISH_PATH=./dist/x; [ "$rc" = 0 ] && [ "$(out_val publish_path)" = ./dist/x ]; }
check "publish-path: ./ path unchanged" t

t() { run_step PUBLISH_PATH=/abs/x; [ "$rc" = 0 ] && [ "$(out_val publish_path)" = /abs/x ]; }
check "publish-path: absolute path unchanged" t

t() { run_step PUBLISH_PATH=$'dist/x\nversion=9.9.9'; [ "$rc" = 1 ] && grep -q "publish-path must be non-empty" "$ERR" && [ ! -s "$OUT" ]; }
check "publish-path: newline (output injection) rejected" t

echo "----"
echo "$pass passed, $fail failed"
[ "$fail" = 0 ]
