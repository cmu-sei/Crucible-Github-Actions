#!/usr/bin/env bash
# Tests the input validation and the merge decision of the shared Dependabot
# auto-merge workflow by extracting the `run:` bodies of the `validate` and
# `decide` steps from .github/workflows/dependabot-auto-merge.yaml and running
# them locally against a temporary GITHUB_OUTPUT file.
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

for step in validate decide; do
  extract_step "$ROOT/.github/workflows/dependabot-auto-merge.yaml" "$step" > "$TMP/$step.sh"
  if ! grep -q 'GITHUB_OUTPUT' "$TMP/$step.sh" || grep -q '^ *# ' "$TMP/$step.sh"; then
    echo "FAIL extract $step step (empty or polluted extraction)"; exit 1
  fi
done

pass=0; fail=0
OUT="$TMP/out"; ERR="$TMP/err"
# run_step VAR=value ...  -> runs the validate step; sets $rc; output in $OUT,
# stderr+stdout in $ERR. run_decide does the same for the decide step.
run_script() {
  local script="$1"; shift
  : > "$OUT"
  env -i PATH="$PATH" GITHUB_OUTPUT="$OUT" "$@" bash "$TMP/$script.sh" > "$ERR" 2>&1
  rc=$?
}
run_step() { run_script validate UPDATE_TYPES=patch "$@"; }
run_decide() { run_script decide "$@"; }
out_val() { sed -n "s/^$1=//p" "$OUT"; }
check() { # check <name> <condition-command...>
  local name="$1"; shift
  if "$@"; then echo "PASS $name"; pass=$((pass + 1)); else echo "FAIL $name"; sed 's/^/    | /' "$ERR"; fail=$((fail + 1)); fi
}

for tok in github-token app; do
  for m in squash merge rebase; do
    t() { run_step TOKEN="$tok" MERGE_METHOD="$m"; [ "$rc" = 0 ] && [ "$(out_val token)" = "$tok" ] && [ "$(out_val merge_method)" = "$m" ] && [ "$(out_val update_types)" = patch ]; }
    check "token=$tok merge-method=$m accepted" t
  done
done

for u in patch minor all; do
  t() { run_step TOKEN=github-token MERGE_METHOD=squash UPDATE_TYPES="$u"; [ "$rc" = 0 ] && [ "$(out_val update_types)" = "$u" ]; }
  check "update-types=$u accepted" t
done

for bad in '' 'major' 'Patch' 'semver-patch' 'all;id' 'patch ' $'all\n::warning::x'; do
  t() { run_step TOKEN=github-token MERGE_METHOD=squash UPDATE_TYPES="$bad"; [ "$rc" = 1 ] && [ ! -s "$OUT" ] && [ "$(wc -l < "$ERR")" = 1 ] && grep -qx "::error::update-types must be patch, minor or all" "$ERR"; }
  check "update-types $(printf %q "$bad") rejected without echoing it" t
done

# Merge decision: update-types x Dependabot update-type. An empty or unknown
# update type (no semver bump) is never merged.
expect() { # expect <update-types> <update-type> <true|false>
  t() { run_decide UPDATE_TYPES="$1" UPDATE_TYPE="$2"; [ "$rc" = 0 ] && [ "$(out_val merge)" = "$3" ]; }
  check "update-types=$1 update-type=${2:-<empty>} -> merge=$3" t "$@"
}
for u in patch minor all; do
  expect "$u" version-update:semver-patch true
  expect "$u" '' false
  expect "$u" version-update:semver-prerelease false
  expect "$u" semver-patch false
done
expect patch version-update:semver-minor false
expect patch version-update:semver-major false
expect minor version-update:semver-minor true
expect minor version-update:semver-major false
expect all version-update:semver-minor true
expect all version-update:semver-major true

for bad in '' 'GITHUB_TOKEN' 'pat' 'app;id' 'github-token ' $'app\n::warning::x'; do
  t() { run_step TOKEN="$bad" MERGE_METHOD=squash; [ "$rc" = 1 ] && [ ! -s "$OUT" ] && [ "$(wc -l < "$ERR")" = 1 ] && grep -qx "::error::token must be github-token or app" "$ERR"; }
  check "token $(printf %q "$bad") rejected without echoing it" t
done

for bad in '' 'squash-merge' 'fast-forward' 'squash;id' $'squash\n::warning::x'; do
  t() { run_step TOKEN=github-token MERGE_METHOD="$bad"; [ "$rc" = 1 ] && [ ! -s "$OUT" ] && [ "$(wc -l < "$ERR")" = 1 ] && grep -qx "::error::merge-method must be squash, merge or rebase" "$ERR"; }
  check "merge-method $(printf %q "$bad") rejected without echoing it" t
done

# The approve/merge step must only run when the decide step says so, and the
# App steps only in app mode; guard against an edit that widens either
# condition. update-types must default to patch.
WF="$ROOT/.github/workflows/dependabot-auto-merge.yaml"
t() { [ "$(grep -c "if: steps.decide.outputs.merge == 'true'$" "$WF")" = 1 ] && [ "$(grep -c "if: steps.decide.outputs.merge == 'true' && steps.validate.outputs.token == 'app'$" "$WF")" = 2 ] && [ "$(grep -c '^        if:' "$WF")" = 3 ]; }
check "approve/merge gated on decide; App steps gated on token app" t
t() { awk '/^      update-types:$/ { f = 1 } f && /^        default: / { print $2; exit }' "$WF" | grep -qx patch; }
check "update-types defaults to patch" t
t() { grep -q "if: github.event.pull_request.user.login == 'dependabot\[bot\]' && github.repository_owner == 'cmu-sei'$" "$WF" && ! grep -q 'actions/checkout' "$WF"; }
check "job gated on dependabot[bot] in cmu-sei; never checks out code" t

echo "dependabot-auto-merge: $pass passed, $fail failed"
[ "$fail" = 0 ]
