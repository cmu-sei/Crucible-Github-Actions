# Tests

Shell tests for the `run:` logic of the reusable workflows. Each script extracts step bodies from a workflow file and runs them locally against a temporary `GITHUB_OUTPUT`:

- `codeql-plan.test.sh` extracts the `run:` scripts of the `plan` job's `matrix` and `config` steps from `.github/workflows/codeql.yaml`, asserting on the language matrix, query-suite validation, and the merged CodeQL config JSON (central plus caller exclusions, input validation).
- `nuget-release.test.sh` extracts the `validate` step of `.github/workflows/nuget-release.yaml` and `.github/workflows/nuget-relist.yaml`, asserting on version normalization (leading `v` stripped), SemVer and package-id rejection (shell metacharacters, whitespace, leading zeros, build metadata), error messages that never echo the raw input, and the `auth-mode` / `github-release` enums; it also extracts the Pack step's `description` escaping line and checks the MSBuild escapes (`%3B`, `%2C`, `%25`).
- `npm-release.test.sh` extracts the `run:` script of the `validate` step from `.github/workflows/npm-release.yaml`, asserting that SemVer versions (with an optional leading `v`) are accepted and normalized; that malformed versions (including empty or leading-zero prerelease identifiers), build metadata (`+…`), a prerelease without a dist-tag, invalid dist-tags and unknown `auth-mode` values fail; that `commit-version` is rejected on non-branch refs (tags, pull request merge refs) except in dry-run; and that `publish-path` gets `{version}` substituted and a `./` prefix for bare relative paths, with control characters rejected.

Run from the repository root, e.g. `bash tests/nuget-release.test.sh`, or all of them with `for t in tests/*.test.sh; do echo "== $t"; bash "$t"; done` (needs `bash`, `awk`, `jq`). Each prints one PASS/FAIL line per case and exits non-zero on any failure.

They run in CI as the `codeql-plan-tests` job (`.github/workflows/ci.yaml`), which runs every `tests/*.test.sh`; see "Continuous integration" in the top-level README.
