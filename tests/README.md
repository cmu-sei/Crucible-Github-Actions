# Tests

`codeql-plan.test.sh` extracts the `run:` scripts of the `plan` job's `matrix` and `config` steps from `.github/workflows/codeql.yaml` and runs them locally against a temporary `GITHUB_OUTPUT`, asserting on the language matrix, query-suite validation, and the merged CodeQL config JSON (central plus caller exclusions, input validation).

Run from the repository root with `bash tests/codeql-plan.test.sh` (needs `bash`, `awk`, `jq`). It prints one PASS/FAIL line per case and exits non-zero on any failure.

Not wired into CI yet.
