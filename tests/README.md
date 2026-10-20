# Tests

Shell tests for the `run:` logic of the reusable workflows. Each script extracts step bodies from a workflow file and runs them locally against a temporary `GITHUB_OUTPUT`:

- `codeql-plan.test.sh` extracts the `run:` scripts of the `plan` job's `matrix` and `config` steps from `.github/workflows/codeql.yaml`, asserting on the language matrix, query-suite validation, and the merged CodeQL config JSON (central plus caller exclusions, input validation).
- `nuget-release.test.sh` extracts the `validate` step of `.github/workflows/nuget-release.yaml` and `.github/workflows/nuget-relist.yaml`, asserting on version normalization (leading `v` stripped), SemVer and package-id rejection (shell metacharacters, whitespace, leading zeros), and the `auth-mode` / `github-release` enums.

Run from the repository root, e.g. `bash tests/nuget-release.test.sh`, or all of them with `for t in tests/*.test.sh; do echo "== $t"; bash "$t"; done` (needs `bash`, `awk`, `jq`). Each prints one PASS/FAIL line per case and exits non-zero on any failure.

They run in CI as the `codeql-plan-tests` job (`.github/workflows/ci.yaml`), which runs every `tests/*.test.sh`; see "Continuous integration" in the top-level README.
