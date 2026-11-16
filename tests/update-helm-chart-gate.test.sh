#!/usr/bin/env bash
# Tests the gate step of actions/update-helm-chart/action.yaml, which skips
# the helm-charts PR when the `enabled` input is false or the release notes
# contain `<!-- helm-chart-pr: false -->`. Extracts the step's `run:` body and
# runs it locally against a temporary GITHUB_OUTPUT file, then checks that
# every later step is gated on its output.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ACTION="$ROOT/actions/update-helm-chart/action.yaml"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# Print the de-indented `run: |` body of the composite step whose `id:` is $2
# in action file $1 (steps at 4 spaces, keys at 6, run body at 8).
extract_step() {
  awk -v want="$2" '
    /^    - / { in_step = 0 }
    $0 ~ "^      id: " want "$" { in_step = 1; next }
    in_step && /^      run: \|$/ { in_run = 1; next }
    in_run {
      if ($0 ~ /^    - / || ($0 !~ /^[[:space:]]*$/ && $0 !~ /^        /)) { exit }
      print
    }
  ' "$1" | sed -e 's/^        //'
}

extract_step "$ACTION" gate > "$TMP/gate.sh"
if ! grep -q 'GITHUB_OUTPUT' "$TMP/gate.sh" || grep -q '^ *# ' "$TMP/gate.sh"; then
  echo "FAIL extract gate step (empty or polluted extraction)"; exit 1
fi

pass=0; fail=0
OUT="$TMP/out"; ERR="$TMP/err"
# run_gate VAR=value ...  -> runs the gate step the way a composite `shell:
# bash` step runs (bash -e -o pipefail); sets $rc; output in $OUT, stdout and
# stderr in $ERR. ENABLED defaults to the input's default, "true".
run_gate() {
  : > "$OUT"
  (cd "$TMP" && env -i PATH="$PATH" GITHUB_OUTPUT="$OUT" ENABLED=true "$@" bash --noprofile --norc -e -o pipefail "$TMP/gate.sh") > "$ERR" 2>&1
  rc=$?
}
out_val() { sed -n "s/^$1=//p" "$OUT"; }
check() { # check <name> <condition-command...>
  local name="$1"; shift
  if "$@"; then echo "PASS $name"; pass=$((pass + 1)); else echo "FAIL $name"; sed 's/^/    | /' "$ERR"; fail=$((fail + 1)); fi
}
runs()    { [ "$rc" = 0 ] && [ "$(out_val skipped)" = false ] && ! grep -q '::notice' "$ERR"; }
skipped() { [ "$rc" = 0 ] && [ "$(out_val skipped)" = true ] && grep -q "::notice title=Helm chart PR skipped::.*$1" "$ERR"; }

NOTES=$'## What\'s Changed\n\n- Fix the thing (#12)\n\n**Full Changelog**: https://github.com/cmu-sei/Example/compare/1.0.0...1.1.0'

# ---- default: PR is opened ----
t() { run_gate RELEASE_BODY="$NOTES"; runs; }
check "notes without the marker: PR opened" t
t() { run_gate RELEASE_BODY=""; runs; }
check "empty notes: PR opened" t
t() { run_gate RELEASE_BODY="$NOTES"$'\n<!-- helm-chart-pr: true -->'; runs; }
check "marker set to true: PR opened" t
t() { run_gate RELEASE_BODY="helm-chart-pr: false"; runs; }
check "marker text outside an HTML comment: PR opened" t
t() { run_gate RELEASE_BODY='<!-- helm-chart-pr: falsey -->'; runs; }
check "marker with a value other than false: PR opened" t

# ---- release-notes marker: PR skipped ----
for m in '<!-- helm-chart-pr: false -->' '<!--helm-chart-pr:false-->' '<!--   helm-chart-pr:   false   -->' '<!-- HELM-CHART-PR: FALSE -->'; do
  t() { run_gate RELEASE_BODY="$NOTES"$'\n\n'"$m"; skipped 'release notes contain'; }
  check "marker '$m' at the end: PR skipped" t
done
t() { run_gate RELEASE_BODY='<!-- helm-chart-pr: false -->'$'\r\n'"$NOTES"; skipped 'release notes contain'; }
check "marker on the first line with CRLF endings: PR skipped" t

# ---- enabled input ----
for v in false FALSE False; do
  t() { run_gate ENABLED="$v" RELEASE_BODY="$NOTES"; skipped 'enabled input is false'; }
  check "enabled=$v: PR skipped" t
done
for v in true TRUE True ''; do
  t() { run_gate ENABLED="$v" RELEASE_BODY="$NOTES"; runs; }
  check "enabled=$v: PR opened" t
done
t() { run_gate ENABLED=false RELEASE_BODY='<!-- helm-chart-pr: false -->'; skipped 'enabled input is false'; }
check "enabled=false and the marker: skipped once, reason is the input" t
for v in yes 0 ' false' 'true; touch pwned' '$(touch pwned)'; do
  t() { run_gate ENABLED="$v" RELEASE_BODY="$NOTES"; [ "$rc" = 1 ] && grep -q "::error::enabled must be 'true' or 'false'" "$ERR" && [ ! -s "$OUT" ] && ! grep -qF -- "$v" "$ERR" && [ ! -e "$TMP/pwned" ]; }
  check "enabled='$v' rejected without echoing it" t
done

# ---- release notes are data, never code ----
t() { run_gate RELEASE_BODY='$(touch pwned) `touch pwned` <!-- helm-chart-pr: false -->'; skipped 'release notes contain' && [ ! -e "$TMP/pwned" ]; }
check "shell syntax in the notes is not run" t

# ---- every later step is gated ----
# Each step after the gate must check the gate's output itself, or depend on
# steps.update.outputs.has_changes (empty when the update step was skipped).
ungated="$(awk '
  /^    - name: / { if (name != "" && name != "gate" && !gated) print name; name = substr($0, 13); gated = 0; next }
  /^      id: gate$/ { name = "gate" }
  /steps\.gate\.outputs\.skipped == .false./ || /steps\.update\.outputs\.has_changes == .true./ { gated = 1 }
  END { if (name != "" && name != "gate" && !gated) print name }
' "$ACTION")"
first="$(grep -m1 '^    - name: ' "$ACTION")"
t() { [ -z "$ungated" ] || { printf 'ungated steps:\n%s\n' "$ungated" > "$ERR"; false; }; }
check "every step after the gate is gated on it" t
t() { [ "$first" = "    - name: Check whether to open a helm-charts PR" ] || { echo "first step: $first" > "$ERR"; false; }; }
check "the gate is the first step" t
t() { grep -q 'RELEASE_BODY: \${{ github.event.release.body }}' "$ACTION" && ! grep -q 'run:.*github\.event\.release\.body' "$ACTION"; }
check "release notes reach the gate through env only" t

echo "update-helm-chart-gate: $pass passed, $fail failed"
[ "$fail" = 0 ]
