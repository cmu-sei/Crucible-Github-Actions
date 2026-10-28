#!/usr/bin/env bash
# Tests the input validation of the shared Dependabot auto-merge workflow by
# extracting the `run:` body of the `validate` step from
# .github/workflows/dependabot-auto-merge.yaml and running it locally against a
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

extract_step "$ROOT/.github/workflows/dependabot-auto-merge.yaml" validate > "$TMP/validate.sh"
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

for tok in github-token app; do
  for m in squash merge rebase; do
    t() { run_step TOKEN="$tok" MERGE_METHOD="$m"; [ "$rc" = 0 ] && [ "$(out_val token)" = "$tok" ] && [ "$(out_val merge_method)" = "$m" ]; }
    check "token=$tok merge-method=$m accepted" t
  done
done

for bad in '' 'GITHUB_TOKEN' 'pat' 'app;id' 'github-token ' $'app\n::warning::x'; do
  t() { run_step TOKEN="$bad" MERGE_METHOD=squash; [ "$rc" = 1 ] && [ ! -s "$OUT" ] && [ "$(wc -l < "$ERR")" = 1 ] && grep -qx "::error::token must be github-token or app" "$ERR"; }
  check "token $(printf %q "$bad") rejected without echoing it" t
done

for bad in '' 'squash-merge' 'fast-forward' 'squash;id' $'squash\n::warning::x'; do
  t() { run_step TOKEN=github-token MERGE_METHOD="$bad"; [ "$rc" = 1 ] && [ ! -s "$OUT" ] && [ "$(wc -l < "$ERR")" = 1 ] && grep -qx "::error::merge-method must be squash, merge or rebase" "$ERR"; }
  check "merge-method $(printf %q "$bad") rejected without echoing it" t
done

# The approve/merge step must only run for semver-patch updates, and the App
# steps only in app mode; guard against an edit that widens either condition.
WF="$ROOT/.github/workflows/dependabot-auto-merge.yaml"
t() { [ "$(grep -c "if: steps.meta.outputs.update-type == 'version-update:semver-patch'$" "$WF")" = 1 ] && [ "$(grep -c "if: steps.meta.outputs.update-type == 'version-update:semver-patch' && steps.validate.outputs.token == 'app'$" "$WF")" = 2 ]; }
check "approve/merge gated on semver-patch; App steps gated on token app" t
t() { grep -q "if: github.event.pull_request.user.login == 'dependabot\[bot\]' && github.repository_owner == 'cmu-sei'$" "$WF" && ! grep -q 'actions/checkout' "$WF"; }
check "job gated on dependabot[bot] in cmu-sei; never checks out code" t

echo "dependabot-auto-merge: $pass passed, $fail failed"
[ "$fail" = 0 ]
