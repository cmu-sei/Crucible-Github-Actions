#!/usr/bin/env bash
# Tests the input validation of the shared npm build-and-test workflow by
# extracting the `run:` body of the `validate` step from
# .github/workflows/npm-test.yaml and running it locally against a temporary
# GITHUB_OUTPUT file.
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

extract_step "$ROOT/.github/workflows/npm-test.yaml" validate > "$TMP/validate.sh"
if ! grep -q 'GITHUB_OUTPUT' "$TMP/validate.sh" || grep -q '^ *# ' "$TMP/validate.sh"; then
  echo "FAIL extract validate step (empty or polluted extraction)"; exit 1
fi

pass=0; fail=0
OUT="$TMP/out"; ERR="$TMP/err"
# run_step VAR=value ...  -> sets $rc; output in $OUT, stderr+stdout in $ERR
run_step() {
  : > "$OUT"
  env -i PATH="$PATH" GITHUB_OUTPUT="$OUT" "$@" bash "$TMP/validate.sh" > "$ERR" 2>&1
  rc=$?
}
out_val() { sed -n "s/^$1=//p" "$OUT"; }
check() { # check <name> <condition-command...>
  local name="$1"; shift
  if "$@"; then echo "PASS $name"; pass=$((pass + 1)); else echo "FAIL $name"; sed 's/^/    | /' "$ERR"; fail=$((fail + 1)); fi
}

ok_env=(NODE_VERSION=24 INSTALL_COMMAND='npm ci' TEST_COMMAND='npm run test:coverage')

t() { run_step "${ok_env[@]}" COVERAGE_PATH=coverage; [ "$rc" = 0 ] && [ "$(out_val coverage)" = coverage ]; }
check "defaults accepted; coverage=coverage" t

t() { run_step "${ok_env[@]}" COVERAGE_PATH=coverage/alloy/; [ "$rc" = 0 ] && [ "$(out_val coverage)" = coverage/alloy ]; }
check "nested coverage-path, trailing slash stripped" t

t() { run_step "${ok_env[@]}" COVERAGE_PATH=; [ "$rc" = 0 ] && grep -qx 'coverage=' "$OUT"; }
check "empty coverage-path -> upload skipped (coverage= empty)" t

for v in 24 24.11 24.11.1; do
  t() { run_step NODE_VERSION="$v" INSTALL_COMMAND='npm ci' TEST_COMMAND='npm test' COVERAGE_PATH=coverage; [ "$rc" = 0 ]; }
  check "node-version $v accepted" t
done

for v in '' 'lts/*' 'v24' '24.x' '24;id' $'24\n::warning::x'; do
  t() { run_step NODE_VERSION="$v" INSTALL_COMMAND='npm ci' TEST_COMMAND='npm test' COVERAGE_PATH=coverage; [ "$rc" = 1 ] && [ ! -s "$OUT" ] && [ "$(wc -l < "$ERR")" = 1 ] && grep -qx "::error::node-version must be [^:]*" "$ERR"; }
  check "node-version $(printf %q "$v") rejected without echoing it" t
done

t() { run_step NODE_VERSION=24 INSTALL_COMMAND= TEST_COMMAND='npm test' COVERAGE_PATH=coverage; [ "$rc" = 1 ] && grep -q "::error::install-command must not be empty" "$ERR" && [ ! -s "$OUT" ]; }
check "empty install-command rejected" t

t() { run_step NODE_VERSION=24 INSTALL_COMMAND='npm ci' TEST_COMMAND= COVERAGE_PATH=coverage; [ "$rc" = 1 ] && grep -q "::error::test-command must not be empty" "$ERR" && [ ! -s "$OUT" ]; }
check "empty test-command rejected" t

for bad in '/abs' '../coverage' 'a/../b' 'a/./b' './coverage' 'a//b' 'cov erage' 'cov;id' $'cov\n::warning::x'; do
  t() { run_step "${ok_env[@]}" COVERAGE_PATH="$bad"; [ "$rc" = 1 ] && [ ! -s "$OUT" ] && [ "$(wc -l < "$ERR")" = 1 ] && grep -qx "::error::coverage-path must [^:]*" "$ERR"; }
  check "coverage-path $(printf %q "$bad") rejected without echoing it" t
done

echo "npm-test: $pass passed, $fail failed"
[ "$fail" = 0 ]
