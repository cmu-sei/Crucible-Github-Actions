#!/usr/bin/env bash
# Tests the input validation of the shared NuGet workflows by extracting the
# `run:` body of the `validate` step from .github/workflows/nuget-release.yaml
# and .github/workflows/nuget-relist.yaml and running it locally against a
# temporary GITHUB_OUTPUT file.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# Print the de-indented `run: |` body of the step whose `id:` is $2 in
# workflow file $1 (same extraction rules as tests/codeql-plan.test.sh).
extract_step() {
  awk -v want="$2" '
    /^      - / { in_step = 0 }
    $0 ~ "^        id: " want "$" { in_step = 1; next }
    in_step && /^        run: \|$/ { in_run = 1; next }
    in_run {
      if ($0 ~ /^      - / || ($0 !~ /^[[:space:]]*$/ && $0 !~ /^          /)) { exit }
      print
    }
  ' "$1" | sed -e 's/^          //'
}

extract_step "$ROOT/.github/workflows/nuget-release.yaml" validate > "$TMP/release.sh"
extract_step "$ROOT/.github/workflows/nuget-relist.yaml" validate > "$TMP/relist.sh"
for f in release relist; do
  if ! grep -q 'GITHUB_OUTPUT' "$TMP/$f.sh" || grep -q '^ *# ' "$TMP/$f.sh"; then
    echo "FAIL extract $f validate step (empty or polluted extraction)"; exit 1
  fi
done

pass=0; fail=0
OUT="$TMP/out"; ERR="$TMP/err"
# run_step <script> VAR=value ...  -> sets $rc; output in $OUT, stderr+stdout in $ERR
run_step() {
  local script="$1"; shift
  : > "$OUT"
  env -i PATH="$PATH" GITHUB_OUTPUT="$OUT" "$@" bash "$TMP/$script.sh" > "$ERR" 2>&1
  rc=$?
}
out_val() { sed -n "s/^$1=//p" "$OUT"; }
check() { # check <name> <condition-command...>
  local name="$1"; shift
  if "$@"; then echo "PASS $name"; pass=$((pass + 1)); else echo "FAIL $name"; sed 's/^/    | /' "$ERR"; fail=$((fail + 1)); fi
}

ok_env=(AUTH_MODE=api-key GITHUB_RELEASE=release)

# ---- nuget-release.yaml: Validate inputs ----
t() { run_step release "${ok_env[@]}" VERSION=1.2.3; [ "$rc" = 0 ] && [ "$(out_val version)" = 1.2.3 ]; }
check "release: 1.2.3 -> version=1.2.3" t

t() { run_step release "${ok_env[@]}" VERSION=v2.0.0-rc.1; [ "$rc" = 0 ] && [ "$(out_val version)" = 2.0.0-rc.1 ]; }
check "release: v2.0.0-rc.1 -> leading v stripped" t

t() { run_step release "${ok_env[@]}" VERSION='1.2.3;id'; [ "$rc" = 1 ] && grep -q "is not a SemVer version" "$ERR" && [ ! -s "$OUT" ]; }
check "release: '1.2.3;id' rejected" t

t() { run_step release "${ok_env[@]}" VERSION='$(id)'; [ "$rc" = 1 ] && ! grep -q 'uid=' "$ERR" && [ ! -s "$OUT" ]; }
check "release: '\$(id)' rejected, not executed" t

t() { run_step release "${ok_env[@]}" VERSION=' 1.2.3'; [ "$rc" = 1 ] && [ ! -s "$OUT" ]; }
check "release: leading space rejected" t

t() { run_step release "${ok_env[@]}" VERSION=01.2.3; [ "$rc" = 1 ] && [ ! -s "$OUT" ]; }
check "release: leading zero (01.2.3) rejected" t

t() { run_step release VERSION=1.2.3 AUTH_MODE=bogus GITHUB_RELEASE=release; [ "$rc" = 1 ] && grep -q "auth-mode must be" "$ERR"; }
check "release: invalid auth-mode rejected" t

t() { run_step release VERSION=1.2.3 AUTH_MODE=api-key GITHUB_RELEASE=maybe; [ "$rc" = 1 ] && grep -q "github-release must be" "$ERR"; }
check "release: invalid github-release rejected" t

t() { run_step release VERSION=1.2.3 AUTH_MODE=trusted GITHUB_RELEASE=tag; [ "$rc" = 0 ] && [ "$(out_val version)" = 1.2.3 ]; }
check "release: trusted + tag accepted" t

# ---- nuget-relist.yaml: Validate inputs ----
t() { run_step relist PACKAGE_ID=Alloy.Api.Client VERSION=v1.2.3
  [ "$rc" = 0 ] && [ "$(out_val package_id)" = Alloy.Api.Client ] && [ "$(out_val version)" = 1.2.3 ]; }
check "relist: Alloy.Api.Client v1.2.3 -> 1.2.3" t

t() { run_step relist PACKAGE_ID='x;y' VERSION=1.2.3; [ "$rc" = 1 ] && grep -q "not a valid NuGet package id" "$ERR" && [ ! -s "$OUT" ]; }
check "relist: package id 'x;y' rejected" t

t() { run_step relist PACKAGE_ID=Alloy.Api.Client VERSION='1.2.3;id'; [ "$rc" = 1 ] && [ ! -s "$OUT" ]; }
check "relist: version '1.2.3;id' rejected" t

echo "----"
echo "$pass passed, $fail failed"
[ "$fail" = 0 ]
