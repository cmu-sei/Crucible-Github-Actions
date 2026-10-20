# Tests

`codeql-plan.test.sh` extracts the `run:` scripts of the `plan` job's `matrix` and `config` steps from `.github/workflows/codeql.yaml` and runs them locally against a temporary `GITHUB_OUTPUT`, asserting on the language matrix, query-suite validation, and the merged CodeQL config JSON (central plus caller exclusions, input validation).

Run from the repository root with `bash tests/codeql-plan.test.sh` (needs `bash`, `awk`, `jq`). It prints one PASS/FAIL line per case and exits non-zero on any failure.

`npm-release.test.sh` extracts the `run:` script of the `validate` step from `.github/workflows/npm-release.yaml` and runs it against a temporary `GITHUB_OUTPUT`, asserting that SemVer versions (with an optional leading `v`) are accepted and normalized, and that malformed versions, invalid dist-tags and unknown `auth-mode` values fail. Run it with `bash tests/npm-release.test.sh` (needs `bash`, `awk`).

Every `tests/*.test.sh` script runs in CI as the `codeql-plan-tests` job (`.github/workflows/ci.yaml`); see "Continuous integration" in the top-level README.
