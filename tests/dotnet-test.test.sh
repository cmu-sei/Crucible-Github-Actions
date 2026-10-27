#!/usr/bin/env bash
# Tests the input validation and test-runner detection of the shared .NET
# build-and-test workflow by extracting the `run:` bodies of the `validate`
# and `runner` steps from .github/workflows/dotnet-test.yaml and running them
# locally against a temporary GITHUB_OUTPUT file.
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

WF="$ROOT/.github/workflows/dotnet-test.yaml"
extract_step "$WF" validate > "$TMP/validate.sh"
extract_step "$WF" runner > "$TMP/runner.sh"
for f in validate runner; do
  if ! grep -q 'GITHUB_OUTPUT' "$TMP/$f.sh" || grep -q '^ *# ' "$TMP/$f.sh"; then
    echo "FAIL extract $f step (empty or polluted extraction)"; exit 1
  fi
done

pass=0; fail=0
OUT="$TMP/out"; ERR="$TMP/err"; WORK="$TMP/work"
# run_step <script> VAR=value ...  -> sets $rc; output in $OUT, stderr+stdout in $ERR.
# Runs in $WORK, where the runner tests put their global.json.
run_step() {
  local script="$1"; shift
  : > "$OUT"
  (cd "$WORK" && env -i PATH="$PATH" GITHUB_OUTPUT="$OUT" "$@" bash "$TMP/$script.sh") > "$ERR" 2>&1
  rc=$?
}
out_val() { sed -n "s/^$1=//p" "$OUT"; }
check() { # check <name> <condition-command...>
  local name="$1"; shift
  if "$@"; then echo "PASS $name"; pass=$((pass + 1)); else echo "FAIL $name"; sed 's/^/    | /' "$ERR"; fail=$((fail + 1)); fi
}
mkdir -p "$WORK"

# ---- Validate inputs ----
t() { run_step validate TEST_PROJECT=Example.Api.Tests; [ "$rc" = 0 ] && [ "$(out_val project)" = Example.Api.Tests ] && [ "$(out_val assembly)" = Example.Api.Tests ]; }
check "validate: Example.Api.Tests -> assembly defaults to the directory name" t

t() { run_step validate TEST_PROJECT=src/Example.Api.Tests/; [ "$rc" = 0 ] && [ "$(out_val project)" = src/Example.Api.Tests ] && [ "$(out_val assembly)" = Example.Api.Tests ]; }
check "validate: nested path, trailing slash stripped, assembly is the last segment" t

t() { run_step validate TEST_PROJECT=test/Example.Api.Tests TEST_ASSEMBLY=Example.Tests; [ "$rc" = 0 ] && [ "$(out_val assembly)" = Example.Tests ]; }
check "validate: explicit test-assembly wins" t

for bad in '' '/abs/Tests' '../Tests' 'a/../b' 'a/./b' './Tests' 'a//b' 'A Tests' 'Tests;id' 'Tests$(id)' $'Tests\n::warning::x'; do
  t() { run_step validate TEST_PROJECT="$bad"; [ "$rc" = 1 ] && [ ! -s "$OUT" ] && [ "$(wc -l < "$ERR")" = 1 ] && grep -qx "::error::test-project must [^:]*" "$ERR"; }
  check "validate: test-project $(printf %q "$bad") rejected without echoing it" t
done

for bad in 'a b' 'x;y' '../x' 'x/y'; do
  t() { run_step validate TEST_PROJECT=Ok.Tests TEST_ASSEMBLY="$bad"; [ "$rc" = 1 ] && grep -q "::error::test-assembly" "$ERR" && [ ! -s "$OUT" ]; }
  check "validate: test-assembly $(printf %q "$bad") rejected" t
done

# ---- Detect test runner ----
t() { rm -f "$WORK/global.json"; run_step runner; [ "$rc" = 0 ] && [ "$(out_val mode)" = vstest ]; }
check "runner: no global.json -> vstest" t

t() { echo '{"sdk":{"version":"10.0.100","rollForward":"latestMinor"}}' > "$WORK/global.json"; run_step runner; [ "$rc" = 0 ] && [ "$(out_val mode)" = vstest ]; }
check "runner: global.json without test section -> vstest" t

t() { echo '{"sdk":{"version":"10.0.100"},"test":{"runner":"VSTest"}}' > "$WORK/global.json"; run_step runner; [ "$rc" = 0 ] && [ "$(out_val mode)" = vstest ]; }
check "runner: test.runner VSTest -> vstest" t

t() { echo '{"sdk":{"version":"10.0.100"},"test":{"runner":"Microsoft.Testing.Platform"}}' > "$WORK/global.json"; run_step runner; [ "$rc" = 0 ] && [ "$(out_val mode)" = mtp ]; }
check "runner: test.runner Microsoft.Testing.Platform -> mtp" t

t() { echo '{"test":{"runner":"NUnit"}}' > "$WORK/global.json"; run_step runner; [ "$rc" = 1 ] && grep -q "::error::global.json test.runner must be" "$ERR" && [ ! -s "$OUT" ]; }
check "runner: unknown test.runner rejected" t

t() { echo '{"sdk": ' > "$WORK/global.json"; run_step runner; [ "$rc" = 1 ] && grep -q "::error::global.json is not valid JSON" "$ERR" && [ ! -s "$OUT" ]; }
check "runner: malformed global.json rejected" t

echo "dotnet-test: $pass passed, $fail failed"
[ "$fail" = 0 ]
