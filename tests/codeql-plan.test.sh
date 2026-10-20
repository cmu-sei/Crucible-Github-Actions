#!/usr/bin/env bash
# Tests the shell logic of the `plan` job in .github/workflows/codeql.yaml by
# extracting the `run:` bodies of the `matrix` and `config` steps and running
# them locally against a temporary GITHUB_OUTPUT file.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKFLOW="$ROOT/.github/workflows/codeql.yaml"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# Print the de-indented `run: |` body of the step whose `id:` is $1.
# The step is found by its `id:` line; the body runs from the following
# `run: |` line until the next step item (`      - `) or a less-indented
# non-blank line (next job / top-level key). `#` comment lines above the next
# step are dropped by the de-indent filter since they sit at step-list depth.
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

extract_step matrix > "$TMP/matrix.sh"
extract_step config > "$TMP/config.sh"
for f in matrix config; do
  if ! grep -q 'GITHUB_OUTPUT' "$TMP/$f.sh" || grep -q '^ *# ' "$TMP/$f.sh"; then
    echo "FAIL extract $f step (empty or polluted extraction)"; exit 1
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

matrix_env=(INCLUDE_ACTIONS=true BUILD_MODE=none QUERY_SUITE=security-extended)
config_json() { out_val config; }

# ---- matrix step ----
t() { run_step matrix "${matrix_env[@]}" LANGUAGES=csharp
  [ "$rc" = 0 ] && [ "$(out_val include | jq -c 'sort_by(.language)')" = '[{"language":"actions","build-mode":"none"},{"language":"csharp","build-mode":"none"}]' ]; }
check "matrix: csharp + actions -> both none" t

t() { run_step matrix "${matrix_env[@]}" LANGUAGES=go INCLUDE_ACTIONS=false
  [ "$rc" = 0 ] && [ "$(out_val include)" = '[{"language":"go","build-mode":"autobuild"}]' ]; }
check "matrix: go without actions -> autobuild" t

t() { run_step matrix "${matrix_env[@]}" LANGUAGES=cobol; [ "$rc" = 1 ] && grep -q "Unsupported CodeQL language 'cobol'" "$ERR"; }
check "matrix: unsupported language fails" t

t() { run_step matrix "${matrix_env[@]}" LANGUAGES=csharp BUILD_MODE=bogus; [ "$rc" = 1 ] && grep -q "build-mode must be" "$ERR"; }
check "matrix: invalid build-mode fails" t

t() { run_step matrix "${matrix_env[@]}" LANGUAGES=csharp QUERY_SUITE=default
  [ "$rc" = 0 ] && grep -qx 'queries=' "$OUT"; }
check "matrix: default suite -> empty queries" t

t() { run_step matrix "${matrix_env[@]}" LANGUAGES=csharp QUERY_SUITE=security-and-quality
  [ "$rc" = 0 ] && [ "$(out_val queries)" = security-and-quality ]; }
check "matrix: named suite passes through" t

t() { run_step matrix "${matrix_env[@]}" LANGUAGES=csharp QUERY_SUITE=bogus; [ "$rc" = 1 ] && grep -q "query-suite must be" "$ERR"; }
check "matrix: invalid query-suite fails" t

t() { run_step matrix "${matrix_env[@]}" LANGUAGES= INCLUDE_ACTIONS=false; [ "$rc" = 1 ] && grep -q "No languages to analyze" "$ERR"; }
check "matrix: no languages fails" t

# ---- config step ----
CENTRAL_PATHS='["**/node_modules/**","**/dist/**","**/bin/**","**/obj/**"]'
CENTRAL_FILTERS='[{"exclude":{"id":"actions/unpinned-tag"}}]'

t() { run_step config PATHS_IGNORE= EXCLUDE_QUERIES=
  [ "$rc" = 0 ] && config_json | jq -e --argjson p "$CENTRAL_PATHS" --argjson f "$CENTRAL_FILTERS" \
    '.["paths-ignore"] == $p and .["query-filters"] == $f and (keys == ["paths-ignore","query-filters"])' >/dev/null; }
check "config: empty inputs -> central defaults only" t

t() { run_step config PATHS_IGNORE=$'Alloy.Api.Client/**\n\n  **/Migrations/**  ' EXCLUDE_QUERIES=
  [ "$rc" = 0 ] && config_json | jq -e --argjson p "$CENTRAL_PATHS" \
    '.["paths-ignore"] == ($p + ["Alloy.Api.Client/**","**/Migrations/**"])' >/dev/null; }
check "config: paths-ignore trimmed, blanks dropped, central first (6 paths)" t

t() { run_step config PATHS_IGNORE= EXCLUDE_QUERIES='cs/log-forging, js/xss'
  [ "$rc" = 0 ] && config_json | jq -e --argjson f "$CENTRAL_FILTERS" \
    '.["query-filters"] == ($f + [{"exclude":{"id":"cs/log-forging"}},{"exclude":{"id":"js/xss"}}])' >/dev/null; }
check "config: exclude-queries appended to central (3 filters)" t

t() { run_step config PATHS_IGNORE=$'**/dist/**\nfoo/**\nfoo/**' EXCLUDE_QUERIES='actions/unpinned-tag,cs/log-forging,cs/log-forging'
  [ "$rc" = 0 ] && config_json | jq -e '(.["paths-ignore"] | length == 5) and (.["query-filters"] | length == 2)' >/dev/null; }
check "config: duplicates of central and repeated entries removed" t

t() { run_step config PATHS_IGNORE= EXCLUDE_QUERIES='cs/log-forging; rm -rf /'
  [ "$rc" = 1 ] && grep -q "::error::Invalid CodeQL query id 'cs/log-forging; rm -rf /' (expected like cs/log-forging)" "$ERR" && [ ! -s "$OUT" ]; }
check "config: invalid query id fails" t

t() { run_step config PATHS_IGNORE=$'ok/**\n\tbad' EXCLUDE_QUERIES=
  [ "$rc" = 1 ] && grep -q "::error::paths-ignore entries must not contain tabs or control characters" "$ERR" && [ ! -s "$OUT" ]; }
check "config: tab/control char in paths-ignore fails" t

t() { run_step config PATHS_IGNORE=$'a/**\nb/**' EXCLUDE_QUERIES='cs/log-forging'
  [ "$rc" = 0 ] && [ "$(wc -l < "$OUT")" = 1 ] && config_json | jq -e . >/dev/null; }
check "config: output is single-line valid JSON" t

echo "----"
echo "$pass passed, $fail failed"
[ "$fail" = 0 ]
