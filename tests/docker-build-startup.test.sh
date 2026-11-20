#!/usr/bin/env bash
# Tests the startup_test step of .github/workflows/docker-build.yaml, which
# starts a Postgres container and the built image, then polls the health
# endpoints. Extracts the step's `run:` body and runs it locally against
# stubbed docker and curl commands, checking all validation, port detection,
# env handling, polling logic, and cleanup cases.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKFLOW="$ROOT/.github/workflows/docker-build.yaml"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# Print the de-indented `run: |` body of the workflow step whose `id:` is $2
# in workflow file $1 (steps at 6 spaces, keys at 8, run body at 10).
extract_step() {
  awk -v want="$2" '
    /^      - / { in_step = 0 }
    $0 == "        id: " want { in_step = 1; next }
    in_step && /^        run: \|$/ { in_run = 1; next }
    in_run {
      if ($0 ~ /^      - / || ($0 !~ /^[[:space:]]*$/ && $0 !~ /^          /)) { exit }
      print
    }
  ' "$1" | sed -e 's/^          //'
}

extract_step "$WORKFLOW" startup_test > "$TMP/startup.sh"
if ! grep -q 'IMAGE' "$TMP/startup.sh"; then
  echo "FAIL extract startup_test step (empty or polluted extraction)"; exit 1
fi

pass=0; fail=0
ERR="$TMP/err"

# Create stub directory
mkdir -p "$TMP/bin"

# Stub: docker logs all invocations; image inspect returns $FAKE_EXPOSED (or
# prints $FAKE_INSPECT_ERR to stderr and exits $FAKE_INSPECT_RC when non-zero);
# pull exits $FAKE_PULL_RC (prints $FAKE_PULL_ERR); exec ... pg_isready exits
# $FAKE_PG_RC; run ... startup-test-app exits $FAKE_RUN_RC (prints $FAKE_RUN_ERR to
# stderr when non-zero); the Postgres run exits $FAKE_PG_RUN_RC (prints
# $FAKE_PG_RUN_ERR); inspect -f on startup-test-app pops a line from $TMP/states
# (repeats last); logs prints marker; rm succeeds.
cat > "$TMP/bin/docker" << 'EOSTUB'
#!/usr/bin/env bash
echo "$*" >> "$TMP/docker.log"
if [[ "$1" == "image" && "$2" == "inspect" ]]; then
  rc="${FAKE_INSPECT_RC:-0}"
  if [[ "$rc" != 0 ]]; then
    echo "${FAKE_INSPECT_ERR:-}" >&2
    exit "$rc"
  fi
  echo "${FAKE_EXPOSED:-null}"
elif [[ "$1" == "pull" ]]; then
  rc="${FAKE_PULL_RC:-0}"
  if [[ "$rc" != 0 ]]; then
    echo "${FAKE_PULL_ERR:-}" >&2
  fi
  exit "$rc"
elif [[ "$1" == "exec" && "$2" == "startup-test-postgres" && "$3" == "pg_isready" ]]; then
  exit "${FAKE_PG_RC:-0}"
elif [[ "$1" == "run" && "$*" == *"startup-test-app"* ]]; then
  rc="${FAKE_RUN_RC:-0}"
  if [[ "$rc" != 0 ]]; then
    echo "${FAKE_RUN_ERR:-}" >&2
  fi
  exit "$rc"
elif [[ "$1" == "run" ]]; then
  # Postgres container
  rc="${FAKE_PG_RUN_RC:-0}"
  if [[ "$rc" != 0 ]]; then
    echo "${FAKE_PG_RUN_ERR:-}" >&2
  fi
  exit "$rc"
elif [[ "$1" == "inspect" && "$*" == *"startup-test-app"* ]]; then
  if [[ -f "$TMP/states" && -s "$TMP/states" ]]; then
    state="$(head -n1 "$TMP/states")"
    tail -n +2 "$TMP/states" > "$TMP/states.tmp" || true
    if [[ -s "$TMP/states.tmp" ]]; then
      mv "$TMP/states.tmp" "$TMP/states"
    else
      # Last state repeats
      echo "$state" > "$TMP/states"
    fi
    echo "$state"
  else
    echo "running 0"
  fi
elif [[ "$1" == "logs" ]]; then
  echo "APP-LOG-MARKER"
elif [[ "$1" == "rm" ]]; then
  # cleanup succeeds
  exit 0
fi
EOSTUB
chmod +x "$TMP/bin/docker"

# Stub: curl finds the URL argument, looks up its path in $TMP/codes (lines
# "PATH CODE"), prints the code (default 000); appends URL to $TMP/curl.log.
# Exits 7 when printing 000 (to test curl failure handling).
# Records all args to $TMP/curl.args for --globoff and --max-time detection.
# When $FAKE_CURL_SLEEP is set, each request really takes that many seconds;
# like real curl, a request longer than --max-time is cut off at --max-time
# and prints 000 (exit 28), unless $FAKE_CURL_IGNORE_MAX_TIME is set.
cat > "$TMP/bin/curl" << 'EOSTUB'
#!/usr/bin/env bash
echo "$*" >> "$TMP/curl.args"
url=""
max_time=""
prev=""
for arg in "$@"; do
  if [[ "$prev" == "--max-time" ]]; then
    max_time="$arg"
  fi
  prev="$arg"
  if [[ "$arg" =~ ^http ]]; then
    url="$arg"
    break
  fi
done
if [[ -n "${FAKE_CURL_SLEEP:-}" ]]; then
  if [[ -z "${FAKE_CURL_IGNORE_MAX_TIME:-}" && -n "$max_time" ]] &&
     awk -v s="$FAKE_CURL_SLEEP" -v m="$max_time" 'BEGIN { exit !(s > m) }'; then
    /bin/sleep "$max_time"
    echo "000"
    exit 28
  fi
  /bin/sleep "$FAKE_CURL_SLEEP"
fi
if [[ -n "$url" ]]; then
  echo "$url" >> "$TMP/curl.log"
  path="${url#http://*/}"
  path="/${path}"
  code="000"
  if [[ -f "$TMP/codes" ]]; then
    found="$(awk -v p="$path" '$1 == p {print $2}' "$TMP/codes")"
    if [[ -n "$found" ]]; then
      code="$found"
    fi
  fi
  echo "$code"
  if [[ "$code" == "000" ]]; then
    exit 7
  fi
fi
EOSTUB
chmod +x "$TMP/bin/curl"

# Stub: sleep is a no-op by default (so polling rounds are bounded by count, not time),
# but can burn time if $FAKE_SLEEP_SECONDS is set
cat > "$TMP/bin/sleep" << 'EOSTUB'
#!/usr/bin/env bash
if [[ -n "${FAKE_SLEEP_SECONDS:-}" ]]; then
  /bin/sleep "$FAKE_SLEEP_SECONDS"
fi
EOSTUB
chmod +x "$TMP/bin/sleep"

# run_startup VAR=value ... -> runs the startup script with defaults
run_startup() {
  : > "$TMP/docker.log"
  : > "$TMP/curl.log"
  : > "$TMP/curl.args"
  mkdir -p "$TMP/rt"
  (cd "$TMP" && env -i PATH="$TMP/bin:$PATH" RUNNER_TEMP="$TMP/rt" IMAGE=img STARTUP_TEST_TIMEOUT_SECONDS="${STARTUP_TEST_TIMEOUT_SECONDS:-6}" STARTUP_TEST_POLL_SECONDS="${STARTUP_TEST_POLL_SECONDS:-2}" PG_IMAGE=postgres:17.6 STARTUP_TEST_PATH="${STARTUP_TEST_PATH:-}" STARTUP_TEST_ENV="${STARTUP_TEST_ENV:-}" TMP="$TMP" FAKE_EXPOSED="${FAKE_EXPOSED:-}" FAKE_PG_RC="${FAKE_PG_RC:-}" FAKE_RUN_RC="${FAKE_RUN_RC:-}" FAKE_RUN_ERR="${FAKE_RUN_ERR:-}" FAKE_SLEEP_SECONDS="${FAKE_SLEEP_SECONDS:-}" FAKE_INSPECT_RC="${FAKE_INSPECT_RC:-}" FAKE_INSPECT_ERR="${FAKE_INSPECT_ERR:-}" FAKE_PULL_RC="${FAKE_PULL_RC:-}" FAKE_PULL_ERR="${FAKE_PULL_ERR:-}" FAKE_PG_RUN_RC="${FAKE_PG_RUN_RC:-}" FAKE_PG_RUN_ERR="${FAKE_PG_RUN_ERR:-}" FAKE_CURL_SLEEP="${FAKE_CURL_SLEEP:-}" FAKE_CURL_IGNORE_MAX_TIME="${FAKE_CURL_IGNORE_MAX_TIME:-}" "$@" bash --noprofile --norc -e -o pipefail "$TMP/startup.sh") > "$ERR" 2>&1
  rc=$?
}

check() {
  local name="$1"; shift
  if "$@"; then
    echo "PASS $name"
    pass=$((pass + 1))
  else
    echo "FAIL $name"
    sed 's/^/    | /' "$ERR"
    fail=$((fail + 1))
  fi
}

docker_log_has() { grep -qF -- "$1" "$TMP/docker.log"; }
curl_log_has() { grep -qF -- "$1" "$TMP/curl.log"; }
output_has() { grep -qF -- "$1" "$ERR"; }
output_lacks() { ! grep -qF -- "$1" "$ERR"; }

# port from ExposedPorts
t() {
  FAKE_EXPOSED='{"80/tcp":{}}' run_startup
  [[ "$rc" = 0 ]] && docker_log_has "-p 127.0.0.1:80:80" && curl_log_has "http://127.0.0.1:80/api/health/ready" && output_has "port 80"
}
setup_codes() {
  cat > "$TMP/codes" << EOF
/api/health/ready 200
EOF
}
setup_states() { echo "running 0" > "$TMP/states"; }
setup_codes; setup_states
check "port from ExposedPorts" t

# lowest of several ports
t() {
  FAKE_EXPOSED='{"443/tcp":{},"80/tcp":{}}' run_startup
  [[ "$rc" = 0 ]] && docker_log_has "-p 127.0.0.1:80:80"
}
setup_codes; setup_states
check "lowest of several ports" t

# udp-only falls back to 8080
t() {
  FAKE_EXPOSED='{"53/udp":{}}' run_startup
  [[ "$rc" = 0 ]] && docker_log_has "-p 127.0.0.1:8080:8080"
}
setup_codes; setup_states
check "udp-only falls back to 8080" t

# no ExposedPorts falls back to 8080
t() {
  FAKE_EXPOSED='null' run_startup
  [[ "$rc" = 0 ]] && docker_log_has "-p 127.0.0.1:8080:8080"
}
setup_codes; setup_states
check "no ExposedPorts falls back to 8080" t

# network namespace
t() {
  run_startup
  docker_log_has "--network container:startup-test-postgres" && ! docker_log_has "--network host"
}
setup_codes; setup_states
check "network namespace" t

# default env then caller env
t() {
  STARTUP_TEST_ENV=$'Database__Provider=Sqlite\nFoo__Bar=1' run_startup
  [[ "$rc" = 0 ]] &&
  env_file="$(cat "$TMP/rt/startup-test.env")" &&
  [[ "$(echo "$env_file" | head -n1)" == "Database__Provider=PostgreSQL" ]] &&
  [[ "$(echo "$env_file" | sed -n '2p')" =~ ^ConnectionStrings__PostgreSQL= ]] &&
  [[ "$(echo "$env_file" | sed -n '3p')" =~ ^Database__ConnectionString= ]] &&
  [[ "$(echo "$env_file" | sed -n '4p')" == "Oidc__RequireHttpsMetadata=false" ]] &&
  [[ "$(echo "$env_file" | sed -n '5p')" == "GameEngine__ClientId=startuptest" ]] &&
  [[ "$(echo "$env_file" | sed -n '6p')" == "GameEngine__ClientSecret=startuptest" ]] &&
  [[ "$(echo "$env_file" | sed -n '7p')" == "Database__Provider=Sqlite" ]] &&
  [[ "$(echo "$env_file" | sed -n '8p')" == "Foo__Bar=1" ]]
}
setup_codes; setup_states
check "default env then caller env" t

# CRLF and blank lines in env
t() {
  STARTUP_TEST_ENV=$'A=1\r\n\r\nB=2\r\n' run_startup
  [[ "$rc" = 0 ]] &&
  env_file="$(cat "$TMP/rt/startup-test.env")" &&
  echo "$env_file" | grep -qF "A=1" &&
  echo "$env_file" | grep -qF "B=2" &&
  ! echo "$env_file" | grep -q $'\r'
}
setup_codes; setup_states
check "CRLF and blank lines in env" t

# invalid env line not echoed
t() {
  STARTUP_TEST_ENV=$'A=1\nexport SECRETVALUE=x' run_startup
  [[ "$rc" != 0 ]] && output_has "line 2" && output_lacks "SECRETVALUE" && ! docker_log_has "run "
}
check "invalid env line not echoed" t

# comment lines in env are skipped like blank lines
t() {
  STARTUP_TEST_ENV=$'# leading comment\nA=1\n   # indented comment\r\n\t#tab comment\n#B=commented\nC=2 # kept in value\n' run_startup
  [[ "$rc" = 0 ]] &&
  caller_env="$(sed -n '7,$p' "$TMP/rt/startup-test.env")" &&
  [[ "$caller_env" == $'A=1\nC=2 # kept in value' ]]
}
setup_codes; setup_states
check "comment lines in env are skipped" t

# like docker --env-file: whitespace-only lines are skipped and leading
# whitespace is trimmed from KEY=VALUE lines
t() {
  STARTUP_TEST_ENV=$'  A=1\n \t \n\tB=2\r\n' run_startup
  [[ "$rc" = 0 ]] &&
  caller_env="$(sed -n '7,$p' "$TMP/rt/startup-test.env")" &&
  [[ "$caller_env" == $'A=1\nB=2' ]]
}
setup_codes; setup_states
check "indented and whitespace-only env lines handled like docker" t

# line numbers in env errors still count comment and blank lines
t() {
  STARTUP_TEST_ENV=$'# comment\n\nA=1\n  # comment\nexport SECRETVALUE=x' run_startup
  [[ "$rc" != 0 ]] && output_has "::error title=Startup test failed::Invalid env line 5" &&
  output_lacks "SECRETVALUE" && ! docker_log_has "run "
}
check "env error line numbers count comment lines" t

# explicit path
t() {
  STARTUP_TEST_PATH=/api/x run_startup
  [[ "$rc" = 0 ]] && curl_log_has "http://127.0.0.1:8080/api/x" &&
  ! curl_log_has "/api/health/ready"
}
cat > "$TMP/codes" << EOF
/api/x 200
EOF
setup_states
check "explicit path" t

# path without leading slash rejected
t() {
  STARTUP_TEST_PATH=api/x run_startup
  [[ "$rc" != 0 ]] && ! docker_log_has "run "
}
check "path without leading slash rejected" t

# path with space rejected before docker run
t() {
  STARTUP_TEST_PATH='/api/x y' run_startup
  [[ "$rc" != 0 ]] && output_has "invalid characters" && ! docker_log_has "run "
}
check "path with space rejected before docker run" t

# path with bracket accepted and curl called with --globoff
t() {
  STARTUP_TEST_PATH='/api/x[0]' run_startup
  [[ "$rc" = 0 ]] && curl_log_has "http://127.0.0.1:8080/api/x[0]" &&
  grep -qF -- '--globoff' "$TMP/curl.args"
}
cat > "$TMP/codes" << EOF
/api/x[0] 200
EOF
setup_states
check "path with bracket accepted and curl called with --globoff" t

# default list fallback
t() {
  run_startup
  [[ "$rc" = 0 ]] &&
  curl_log_has "/api/health/ready" &&
  curl_log_has "/api/health/version" &&
  curl_log_has "/api/status" &&
  # Check order: ready and version before status
  ready_line="$(grep -n "/api/health/ready" "$TMP/curl.log" | head -1 | cut -d: -f1)" &&
  version_line="$(grep -n "/api/health/version" "$TMP/curl.log" | head -1 | cut -d: -f1)" &&
  status_line="$(grep -n "/api/status" "$TMP/curl.log" | head -1 | cut -d: -f1)" &&
  [[ "$ready_line" -lt "$status_line" ]] && [[ "$version_line" -lt "$status_line" ]] &&
  output_has "Startup test passed: /api/status returned 200 on port"
}
cat > "$TMP/codes" << EOF
/api/health/ready 000
/api/health/version 000
/api/status 200
EOF
setup_states
check "default list fallback" t

# 503 locks the path and keeps polling only it: at 6s timeout and 2s poll,
# 3 rounds of one request each, logged once
t() {
  run_startup
  [[ "$rc" != 0 ]] && output_has "last status: /api/health/ready=503)" &&
  [[ "$(wc -l < "$TMP/curl.log")" -eq 3 ]] &&
  [[ "$(grep -c '/api/health/ready$' "$TMP/curl.log")" -eq 3 ]] &&
  [[ "$(grep -cF 'Startup test: using /api/health/ready (answered 503)' "$ERR")" -eq 1 ]]
}
cat > "$TMP/codes" << EOF
/api/health/ready 503
/api/health/version 404
/api/status 404
/ 404
EOF
setup_states
check "503 locks the path and keeps polling it" t

# a locked 503 is not masked by a later path's 200
t() {
  run_startup
  [[ "$rc" != 0 ]] &&
  output_has "::error title=Startup test failed::Timeout waiting for healthy response (last status: /api/health/ready=503)" &&
  output_lacks "Startup test passed" && ! curl_log_has "/api/health/version"
}
cat > "$TMP/codes" << EOF
/api/health/ready 503
/api/health/version 200
EOF
setup_states
check "ready 503 is not masked by version 200" t

# 404 moves on; the first 5xx answer (500) locks, so a later 200 does not count
t() {
  run_startup
  [[ "$rc" != 0 ]] && output_has "Startup test: using /api/health/version (answered 500)" &&
  output_has "(last status: /api/health/version=500)" && ! curl_log_has "/api/status"
}
cat > "$TMP/codes" << EOF
/api/health/ready 404
/api/health/version 500
/api/status 200
EOF
setup_states
check "first 5xx answer locks the path" t

# only 5xx locks: 401 and 3xx (route protected or redirected) move on to a later 200
t() {
  run_startup
  [[ "$rc" = 0 ]] && output_lacks "Startup test: using" &&
  output_has "Startup test passed: /api/status returned 200 on port"
}
cat > "$TMP/codes" << EOF
/api/health/ready 401
/api/health/version 302
/api/status 200
EOF
setup_states
check "401 and 3xx do not lock the path" t

# 404 on ready and version falls through to /api/status (Gameboard)
t() {
  run_startup
  [[ "$rc" = 0 ]] && output_has "Startup test passed: /api/status returned 200 on port 8080" &&
  output_lacks "Startup test: using"
}
cat > "$TMP/codes" << EOF
/api/health/ready 404
/api/health/version 404
/api/status 200
EOF
setup_states
check "ready and version 404 pass via /api/status" t

# ready 200 passes on the first request
t() {
  run_startup
  [[ "$rc" = 0 ]] && output_has "Startup test passed: /api/health/ready returned 200 on port 8080" &&
  [[ "$(wc -l < "$TMP/curl.log")" -eq 1 ]]
}
cat > "$TMP/codes" << EOF
/api/health/ready 200
EOF
setup_states
check "ready 200 passes" t

# a UI that answers 200 on every path passes via /api/health/ready
t() {
  run_startup
  [[ "$rc" = 0 ]] && output_has "Startup test passed: /api/health/ready returned 200 on port 8080" &&
  ! curl_log_has "/api/health/version"
}
cat > "$TMP/codes" << EOF
/api/health/ready 200
/api/health/version 200
/api/status 200
/ 200
EOF
setup_states
check "all-200 UI passes via /api/health/ready" t

# explicit path: no lock message, timeout names only that path
t() {
  STARTUP_TEST_PATH=/api/x run_startup
  [[ "$rc" != 0 ]] && output_lacks "Startup test: using" && output_has "(last status: /api/x=503)" &&
  [[ "$(wc -l < "$TMP/curl.log")" -eq 3 ]]
}
cat > "$TMP/codes" << EOF
/api/x 503
EOF
setup_states
check "explicit path with 503 times out without a lock message" t

# timeout message with last code per path (no path locked)
t() {
  run_startup
  [[ "$rc" != 0 ]] && output_has "last status: /api/health/ready=404 /api/health/version=000 /api/status=404 /=404"
}
cat > "$TMP/codes" << EOF
/api/health/ready 404
/api/status 404
/ 404
EOF
setup_states
check "timeout message with last code per path" t

# timeout with 000 codes included
t() {
  run_startup
  [[ "$rc" != 0 ]] && output_has "last status:" && output_has "/api/health/ready=000" && output_has "/api/health/version=000"
}
: > "$TMP/codes"
setup_states
check "timeout with 000 codes included" t

# deadline stops loop before max rounds: a 4s timeout with a 1s poll allows
# max_rounds=4, but each sleep really takes 2.5s, so the wall-clock deadline
# is reached after about 3 rounds (12 curls), short of the 4 rounds (16 curls)
# the round count alone would allow.
t() {
  STARTUP_TEST_TIMEOUT_SECONDS=4 STARTUP_TEST_POLL_SECONDS=1 FAKE_SLEEP_SECONDS=2.5 run_startup
  curl_count="$(wc -l < "$TMP/curl.log")"
  [[ "$rc" != 0 ]] && output_has "::error title=Startup test failed::Timeout waiting for healthy response" &&
  [[ "$curl_count" -ge 4 ]] && [[ "$curl_count" -lt 16 ]]
}
: > "$TMP/codes"
setup_states
check "deadline stops loop before max rounds" t

# --max-time is 5 while more than 5 seconds remain
t() {
  run_startup
  [[ "$rc" = 0 ]] && head -n1 "$TMP/curl.args" | grep -qF -- '--max-time 5 '
}
setup_codes; setup_states
check "curl --max-time is 5 with time to spare" t

# deadline hit mid-round: with a 3s timeout and 1s requests, the deadline
# passes before the round reaches the fourth path, and the first request's
# --max-time is clamped to the 3 seconds remaining
t() {
  STARTUP_TEST_TIMEOUT_SECONDS=3 STARTUP_TEST_POLL_SECONDS=1 FAKE_CURL_SLEEP=1 run_startup
  curl_count="$(wc -l < "$TMP/curl.log")"
  [[ "$rc" != 0 ]] && output_has "::error title=Startup test failed::Timeout waiting for healthy response" &&
  [[ "$curl_count" -ge 1 ]] && [[ "$curl_count" -le 3 ]] &&
  head -n1 "$TMP/curl.args" | grep -qF -- '--max-time 3 '
}
: > "$TMP/codes"
setup_states
check "deadline hit mid-round stops polling" t

# a 200 that would only arrive after the deadline: --max-time is clamped to
# the 2 seconds remaining, so the 3-second request is cut off and fails
t() {
  STARTUP_TEST_TIMEOUT_SECONDS=2 STARTUP_TEST_POLL_SECONDS=1 FAKE_CURL_SLEEP=3 run_startup
  [[ "$rc" != 0 ]] && output_has "::error title=Startup test failed::Timeout waiting for healthy response" &&
  output_lacks "Startup test passed" && head -n1 "$TMP/curl.args" | grep -qF -- '--max-time 2 '
}
setup_codes; setup_states
check "200 after the deadline is cut off by --max-time" t

# a 200 received after the deadline is not accepted even if curl overruns
t() {
  STARTUP_TEST_TIMEOUT_SECONDS=2 STARTUP_TEST_POLL_SECONDS=1 FAKE_CURL_SLEEP=3 FAKE_CURL_IGNORE_MAX_TIME=1 run_startup
  [[ "$rc" != 0 ]] && output_has "::error title=Startup test failed::Timeout waiting for healthy response" &&
  output_lacks "Startup test passed" && [[ "$(wc -l < "$TMP/curl.log")" -eq 1 ]]
}
setup_codes; setup_states
check "200 received after the deadline is rejected" t

# exited container fails fast
t() {
  run_startup
  [[ "$rc" != 0 ]] && output_has "135" && output_has "APP-LOG-MARKER" &&
  curl_count="$(wc -l < "$TMP/curl.log" || echo 0)" &&
  [[ "$curl_count" -le 4 ]]
}
echo "exited 135" > "$TMP/states"
: > "$TMP/codes"
check "exited container fails fast" t

# docker run fails
t() {
  FAKE_RUN_RC=125 FAKE_RUN_ERR='exec format error' run_startup
  [[ "$rc" != 0 ]] && output_has "exec format error" &&
  tail -1 "$TMP/docker.log" | grep -qF "rm -f" &&
  tail -1 "$TMP/docker.log" | grep -qF "startup-test-app" &&
  tail -1 "$TMP/docker.log" | grep -qF "startup-test-postgres"
}
check "docker run fails" t

# image inspect fails: annotation plus docker's error text, not swallowed into the JSON value
t() {
  FAKE_INSPECT_RC=1 FAKE_INSPECT_ERR='Error: No such image: startup-test:local' run_startup
  [[ "$rc" != 0 ]] && output_has "::error title=Startup test failed::Failed to inspect image" &&
  output_has "Error: No such image: startup-test:local" &&
  ! docker_log_has "pull " && ! docker_log_has "run " && docker_log_has "rm -f"
}
check "image inspect fails with annotation and docker error" t

# Postgres pull fails
t() {
  FAKE_PULL_RC=1 FAKE_PULL_ERR='toomanyrequests: rate limit' run_startup
  [[ "$rc" != 0 ]] && output_has "::error title=Startup test failed::Failed to pull Postgres image" &&
  output_has "toomanyrequests: rate limit" &&
  ! docker_log_has "run " && tail -1 "$TMP/docker.log" | grep -qF "rm -f"
}
check "postgres pull fails with annotation" t

# Postgres run fails
t() {
  FAKE_PG_RUN_RC=125 FAKE_PG_RUN_ERR='port is already allocated' run_startup
  [[ "$rc" != 0 ]] && output_has "::error title=Startup test failed::Failed to start Postgres container" &&
  output_has "port is already allocated" &&
  ! docker_log_has "--name startup-test-app" && tail -1 "$TMP/docker.log" | grep -qF "rm -f"
}
check "postgres run fails with annotation" t

# postgres never ready
t() {
  FAKE_PG_RC=1 run_startup
  [[ "$rc" != 0 ]] && output_has "Postgres" && ! docker_log_has "--name startup-test-app" && docker_log_has "rm -f"
}
check "postgres never ready" t

# cleanup on success
t() {
  run_startup
  [[ "$rc" = 0 ]] && docker_log_has "rm -f" && docker_log_has "startup-test-app" && docker_log_has "startup-test-postgres"
}
setup_codes; setup_states
check "cleanup on success" t

# logs on timeout
t() {
  run_startup
  [[ "$rc" != 0 ]] && output_has "APP-LOG-MARKER" && output_has "::group::"
}
cat > "$TMP/codes" << EOF
/api/health/ready 503
EOF
setup_states
check "logs on timeout" t

# GitHub annotation
t() {
  run_startup
  [[ "$rc" != 0 ]] && output_has "::error title=Startup test failed::"
}
echo "exited 135" > "$TMP/states"
: > "$TMP/codes"
check "GitHub annotation" t


# ============ Structural checks: wiring into the build flow ============
#
# Step names are matched literally (never as regexes), so names with
# parentheses behave the same under mawk and gawk.

# step_block NAME [FILE]: print the lines of the step whose `- name:` line is
# exactly "      - name: NAME", from that line up to (not including) the next
# step at 6-space indent or any other non-comment line indented 6 or less.
# Exits 2 when no such step exists.
step_block() {
  awk -v want="      - name: $1" '
    started {
      if ($0 ~ /^[[:space:]]*$/ || $0 ~ /^[[:space:]]*#/) { print; next }
      match($0, /^ */)
      if (RLENGTH <= 6) { exit }
      print
      next
    }
    $0 == want { started = 1; found = 1; print }
    END { if (!found) exit 2 }
  ' "${2:-$WORKFLOW}"
}

# step_has_line NAME PREFIX [FILE]: 0 when a line of the step starts with the
# literal PREFIX, 1 when the step exists without one, 2 when the step is missing.
step_has_line() {
  local block
  block="$(step_block "$1" "${3:-$WORKFLOW}")" || return 2
  printf '%s\n' "$block" | awk -v p="$2" 'index($0, p) == 1 { f = 1 } END { exit f ? 0 : 1 }'
}

# step_lacks_line NAME PREFIX [FILE]: true only when the step exists and has no
# line starting with PREFIX.
step_lacks_line() {
  local st
  step_has_line "$@"; st=$?
  [[ "$st" == 1 ]]
}

# step_field NAME KEY [FILE]: value of the step's 8-space `KEY ` line (KEY
# includes the colon, e.g. 'if:').
step_field() {
  step_block "$1" "${3:-$WORKFLOW}" | awk -v p="        $2 " '
    index($0, p) == 1 { print substr($0, length(p) + 1); exit }
  '
}

# step_with_value NAME ATTR [FILE]: value of `ATTR:` under the step's `with:`,
# including continuation lines of a block scalar.
step_with_value() {
  step_block "$1" "${3:-$WORKFLOW}" | awk -v p="          $2:" '
    $0 == "        with:" { in_with = 1; next }
    in_with && /^        [^ ]/ { exit }
    in_val {
      if ($0 ~ /^[[:space:]]*$/ || index($0, "           ") == 1) { print; next }
      exit
    }
    in_with && (index($0, p " ") == 1 || $0 == p) {
      v = substr($0, length(p) + 1); sub(/^ /, "", v); print v; in_val = 1
    }
  '
}

# step_with_has NAME ATTR EXPECTED [FILE]
step_with_has() {
  [[ "$(step_with_value "$1" "$2" "${4:-$WORKFLOW}")" == "$3" ]]
}

STARTUP_TEST_BUILD='Build default stage for startup test'
STARTUP_TEST_STEP='Startup test default stage'
PUSH_BUILD='Build (push by digest) default stage'
NOPUSH_BUILD='Build (no push) default stage'

# inject_in_step NAME AFTER NEWLINE SRC: copy SRC, adding NEWLINE after the
# first line equal to AFTER inside step NAME (AFTER empty: after the name line).
inject_in_step() {
  awk -v want="      - name: $1" -v after="$2" -v add="$3" '
    { print }
    done { next }
    $0 == want { in_step = 1; if (after == "") { print add; done = 1 }; next }
    in_step && /^      - / { in_step = 0 }
    in_step && $0 == after { print add; done = 1 }
    END { if (!done) exit 3 }
  ' "$4"
}

# mutant NAME AFTER NEWLINE OUT: write a mutated copy of the workflow to OUT,
# failing if the injection did not happen.
mutant() {
  inject_in_step "$1" "$2" "$3" "$WORKFLOW" > "$4" && ! cmp -s "$WORKFLOW" "$4"
}

# build_startup_test exists with correct attributes
build_startup_test_attrs() {
  local f="$1"
  step_block "$STARTUP_TEST_BUILD" "$f" > /dev/null &&
  [[ "$(step_field "$STARTUP_TEST_BUILD" 'id:' "$f")" == "build_startup_test" ]] &&
  [[ "$(step_field "$STARTUP_TEST_BUILD" 'if:' "$f")" == "inputs.startupTest" ]] &&
  step_with_has "$STARTUP_TEST_BUILD" 'load' 'true' "$f" &&
  step_with_has "$STARTUP_TEST_BUILD" 'push' 'false' "$f" &&
  step_with_has "$STARTUP_TEST_BUILD" 'tags' 'startup-test:local' "$f" &&
  # No target: means additionalTarget is not used for startup test
  step_lacks_line "$STARTUP_TEST_BUILD" '          target:' "$f" &&
  # cache-from scope matches default stage pattern
  step_with_has "$STARTUP_TEST_BUILD" 'cache-from' "type=gha,scope=\${{ needs.prepare.outputs.image_slug }}-\${{ matrix.safe }}-default" "$f"
}
t() { build_startup_test_attrs "$WORKFLOW"; }
check "build_startup_test exists with correct attributes" t

# mutant: target: under build_startup_test's with: must fail the check
t() {
  mutant "$STARTUP_TEST_BUILD" '        with:' '          target: x' "$TMP/mut-target.yaml" &&
  ! step_lacks_line "$STARTUP_TEST_BUILD" '          target:' "$TMP/mut-target.yaml" &&
  ! build_startup_test_attrs "$TMP/mut-target.yaml"
}
check "mutant: build_startup_test with target: fails the attributes check" t

# startup_test has if: inputs.startupTest
t() {
  [[ "$(step_field "$STARTUP_TEST_STEP" 'id:')" == "startup_test" ]] &&
  [[ "$(step_field "$STARTUP_TEST_STEP" 'if:')" == "inputs.startupTest" ]]
}
check "startup_test has if: inputs.startupTest" t

# Step order: build_startup_test < startup_test < build_default_push
t() {
  build_startup_test_line="$(grep -nxF -- "      - name: $STARTUP_TEST_BUILD" "$WORKFLOW" | cut -d: -f1)"
  startup_test_line="$(grep -nxF -- "      - name: $STARTUP_TEST_STEP" "$WORKFLOW" | cut -d: -f1)"
  build_push_line="$(grep -nxF -- "      - name: $PUSH_BUILD" "$WORKFLOW" | cut -d: -f1)"
  [[ -n "$build_startup_test_line" ]] && [[ -n "$startup_test_line" ]] && [[ -n "$build_push_line" ]] &&
  [[ "$build_startup_test_line" -lt "$startup_test_line" ]] &&
  [[ "$startup_test_line" -lt "$build_push_line" ]]
}
check "step order: build_startup_test < startup_test < build_default_push" t

# Build (no push) default stage has updated if:
t() {
  if_cond="$(step_field "$NOPUSH_BUILD" 'if:')"
  [[ "$if_cond" == "needs.prepare.outputs.push != 'true' && !inputs.startupTest" ]]
}
check "Build (no push) default stage has updated if condition" t

# No other step if: changed (baseline from origin/main)
# Expected if: lines (step name | if: condition) from origin/main, excluding the ones we change
expected_ifs=(
  "Pre-build commands|inputs.preBuildCommands != ''"
  "Inject version into package.json files (npm)|inputs.versionMode == 'npm' && steps.version.outputs.version != '' && inputs.versionFiles != ''"
  "Prepare build args for .NET version (csproj)|inputs.versionMode == 'csproj' && steps.version.outputs.version != ''"
  "Login to Docker Hub|needs.prepare.outputs.push == 'true'"
  "Build (push by digest) default stage|needs.prepare.outputs.push == 'true'"
  "Export default digest|needs.prepare.outputs.push == 'true'"
  "Upload default digest|needs.prepare.outputs.push == 'true'"
  "Build (push by digest) additional target|needs.prepare.outputs.push == 'true' && needs.prepare.outputs.has_additional_target == 'true'"
  "Build (no push) additional target|needs.prepare.outputs.push != 'true' && needs.prepare.outputs.has_additional_target == 'true'"
  "Export additional digest|needs.prepare.outputs.push == 'true' && needs.prepare.outputs.has_additional_target == 'true'"
  "Upload additional digest|needs.prepare.outputs.push == 'true' && needs.prepare.outputs.has_additional_target == 'true'"
)
t() {
  for entry in "${expected_ifs[@]}"; do
    step_name="${entry%%|*}"
    expected_if="${entry#*|}"
    actual_if="$(step_field "$step_name" 'if:')"
    if [[ "$actual_if" != "$expected_if" ]]; then
      echo "Step '$step_name' if: changed: expected '$expected_if', got '$actual_if'" >&2
      return 1
    fi
  done
  return 0
}
check "no other step if: changed from origin/main" t

# build_startup_test and startup_test have no continue-on-error
t() { step_lacks_line "$STARTUP_TEST_BUILD" '        continue-on-error:'; }
check "build_startup_test has no continue-on-error" t

t() { step_lacks_line "$STARTUP_TEST_STEP" '        continue-on-error:'; }
check "startup_test has no continue-on-error" t

# mutants: continue-on-error under each step must fail its check
t() {
  mutant "$STARTUP_TEST_BUILD" '' '        continue-on-error: true' "$TMP/mut-coe-build.yaml" &&
  ! step_lacks_line "$STARTUP_TEST_BUILD" '        continue-on-error:' "$TMP/mut-coe-build.yaml"
}
check "mutant: build_startup_test continue-on-error fails the check" t

t() {
  mutant "$STARTUP_TEST_STEP" '' '        continue-on-error: true' "$TMP/mut-coe-startup.yaml" &&
  ! step_lacks_line "$STARTUP_TEST_STEP" '        continue-on-error:' "$TMP/mut-coe-startup.yaml"
}
check "mutant: startup_test continue-on-error fails the check" t

# continue-on-error on the step after startup_test belongs to that step, not startup_test
t() {
  mutant "$PUSH_BUILD" '' '        continue-on-error: true' "$TMP/mut-coe-next.yaml" &&
  step_lacks_line "$STARTUP_TEST_STEP" '        continue-on-error:' "$TMP/mut-coe-next.yaml"
}
check "step block ends at the next step" t

# a missing step is not reported as lacking the key
t() {
  step_has_line 'No such step' '        continue-on-error:'
  [[ "$?" == 2 ]] && ! step_lacks_line 'No such step' '        continue-on-error:'
}
check "missing step is distinct from missing key" t

# build_startup_test and build_default_push have identical build attributes
t() {
  local attr startup_test push
  for attr in context file platforms pull build-args labels cache-from cache-to; do
    startup_test="$(step_with_value "$STARTUP_TEST_BUILD" "$attr")"
    push="$(step_with_value "$PUSH_BUILD" "$attr")"
    if [[ -z "$startup_test" || "$startup_test" != "$push" ]]; then
      echo "with.$attr differs or is missing" >&2
      return 1
    fi
  done
  return 0
}
check "build_startup_test and build_default_push have identical build attributes" t

echo "docker-build-startup: $pass passed, $fail failed"
[ "$fail" = 0 ]
