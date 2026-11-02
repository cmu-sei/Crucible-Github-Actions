#!/usr/bin/env bash
# Tests actions/header/header.py by running it in a temporary directory of
# sample files and checking which files it marks.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
ERR="$TMP/err"
pass=0; fail=0

check() { # check <name> <condition-command...>
  local name="$1"; shift
  if "$@"; then echo "PASS $name"; pass=$((pass + 1)); else echo "FAIL $name"; sed 's/^/    | /' "$ERR"; fail=$((fail + 1)); fi
}

REPO="$TMP/repo"
mkdir -p "$REPO/src" "$REPO/vendor/lib"
printf '// Copyright 2025 Carnegie Mellon University. All Rights Reserved.\n// Released under a MIT (SEI)-style license. See LICENSE.md in the project root for license information.\n\nexport const a = 1;\n' > "$REPO/src/a.ts"
printf '//  ===BEGIN LICENSE===\n//  Copyright 2025 Carnegie Mellon University. All rights reserved.\n//  Released under an MIT (SEI)-style license. See the LICENSE.md file for license information.\n//  ===END LICENSE===\n\nexport const an = 1;\n' > "$REPO/src/an.ts"
printf 'export const none = 1;\n' > "$REPO/src/none.ts"
printf '<p>none</p>\n' > "$REPO/src/none.html"
printf 'export const vendored = 1;\n' > "$REPO/vendor/lib/vendored.js"
printf 'vendor/\n' > "$REPO/.headerignore"
cp "$REPO/src/a.ts" "$TMP/a.before"; cp "$REPO/src/an.ts" "$TMP/an.before"; cp "$REPO/vendor/lib/vendored.js" "$TMP/vendored.before"

(cd "$REPO" && python3 "$ROOT/actions/header/header.py" false) > "$ERR" 2>&1
rc=$?

marks() { grep -c 'Released under a[n]\? MIT (SEI)-style license' "$1"; }

check "header.py exits 0" test "$rc" = 0
check "'a MIT' header left alone" cmp -s "$TMP/a.before" "$REPO/src/a.ts"
check "'an MIT' header left alone (no second header)" cmp -s "$TMP/an.before" "$REPO/src/an.ts"
check "unmarked .ts gets one header" test "$(marks "$REPO/src/none.ts")" = 1
check "unmarked .ts header uses // comments" grep -q '^// Copyright [0-9]\{4\} Carnegie Mellon University. All Rights Reserved.$' "$REPO/src/none.ts"
check "unmarked .html gets one <!-- --> header" grep -q '^<!-- Released under a MIT (SEI)-style license. See LICENSE.md in the project root for license information. -->$' "$REPO/src/none.html"
check ".headerignore'd file left alone" cmp -s "$TMP/vendored.before" "$REPO/vendor/lib/vendored.js"

# ---- license: bsd-3-clause (TopoMojo) ----
BSD="$TMP/bsd"
mkdir -p "$BSD/src"
printf '// Copyright 2025 Carnegie Mellon University. All Rights Reserved.\n// Released under a 3 Clause BSD-style license. See LICENSE.md in the project root for license information.\n\nexport const b = 1;\n' > "$BSD/src/bsd.ts"
printf 'export const none = 1;\n' > "$BSD/src/none.ts"
cp "$BSD/src/bsd.ts" "$TMP/bsd.before"
(cd "$BSD" && python3 "$ROOT/actions/header/header.py" false bsd-3-clause) > "$ERR" 2>&1
rc=$?
check "bsd-3-clause: header.py exits 0" test "$rc" = 0
check "bsd-3-clause: existing BSD header left alone" cmp -s "$TMP/bsd.before" "$BSD/src/bsd.ts"
check "bsd-3-clause: unmarked file gets the BSD line" grep -q '^// Released under a 3 Clause BSD-style license. See LICENSE.md in the project root for license information.$' "$BSD/src/none.ts"
check "bsd-3-clause: unmarked file gets no MIT line" bash -c "! grep -q 'MIT (SEI)' '$BSD/src/none.ts'"

# ---- license: default and unknown ----
DEF="$TMP/default"
mkdir -p "$DEF"
printf 'export const none = 1;\n' > "$DEF/none.ts"
(cd "$DEF" && python3 "$ROOT/actions/header/header.py" false '') > "$ERR" 2>&1
check "empty license defaults to mit-sei" grep -q '^// Released under a MIT (SEI)-style license' "$DEF/none.ts"

UNK="$TMP/unknown"
mkdir -p "$UNK"
printf 'export const none = 1;\n' > "$UNK/none.ts"
cp "$UNK/none.ts" "$TMP/unknown.before"
(cd "$UNK" && python3 "$ROOT/actions/header/header.py" false gpl) > "$ERR" 2>&1
rc=$?
check "unknown license fails without touching files" bash -c "[ $rc = 1 ] && grep -q 'license must be one of' '$ERR' && cmp -s '$TMP/unknown.before' '$UNK/none.ts'"

echo "header: $pass passed, $fail failed"
[ "$fail" = 0 ]
