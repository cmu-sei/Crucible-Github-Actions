# Crucible GitHub Actions

Reusable GitHub Actions owned by the Crucible team. Consumers can depend on the actions
in this repository to keep shared automation consistent across applications.

## Available Actions

### Update Helm Chart

`actions/update-helm-chart` synchronizes a Helm chart with a newly published application
release and raises a pull request against `cmu-sei/helm-charts`.

The action:

- extracts a semantic version from the release tag
- infers the release type (`major`/`minor`/`patch`) from the existing `appVersion`
- updates the target chart's `appVersion`
- bumps the chart `version` based on the release type
- optionally bumps parent charts
- pushes a feature branch to the Helm charts repository and opens a PR

#### Inputs

| Name | Required | Description |
| --- | --- | --- |
| `app_name` | ✅ | Friendly application name used for commit and PR title, e.g. `TopoMojo API`. |
| `github_app_client_id` |  | GitHub App client ID that should mint a token for pushing to the Helm repo. Provide via a secret. |
| `github_app_private_key` |  | Private key for the GitHub App. Provide via a secret. Required when `github_app_client_id` is set. |
| `chart_file` | ✅ | Path to the application's `Chart.yaml` within the Helm repo, e.g. `charts/topomojo/charts/topomojo-api/Chart.yaml`. |
| `release_tag` |  | Tag from the calling workflow (defaults to `${{ github.event.release.tag_name }}`). |
| `parent_chart_file` |  | Optional path to a parent `Chart.yaml` that should be bumped. |
| `helm_chart_repo` |  | Helm charts repo (`cmu-sei/helm-charts` by default). |
| `helm_repo_token` |  | Optional repository token override. |
| `git_user_name` |  | Commit author name (`github-actions[bot]`). |
| `git_user_email` |  | Commit author email (`41898282+github-actions[bot]@users.noreply.github.com`). |
| `settings_file` |  | Path in the calling repo to the app settings file (e.g. `Player.Api/appsettings.json`). When set, enables the settings-sync phase. Omit to disable. |
| `settings_file_kind` |  | One of `dotnet-appsettings`, `dotnet-conf`, or `angular-settings`. Required when `settings_file` is set. |

#### Outputs

- `new_app_version` – parsed version string, e.g. `2.5.2`
- `release_type` – computed release type (`major`/`minor`/`patch`)
- `new_chart_version` – bumped chart version
- `parent_chart_update` – JSON object describing the parent chart bump
- `chart_modified` – `true` when an update was required
- `branch_name` – suggested feature branch for the PR
- `has_changes` – `true` when any files were modified
- `settings_changed` – `true` when settings were added or removed between the previous and new release tags
- `settings_added` – JSON object mapping added flattened setting keys to their leaf type
- `settings_removed` – JSON array of removed flattened setting keys
- `previous_release_tag` – resolved previous release tag (empty when no prior tag exists)

#### Settings sync (optional)

When `settings_file` and `settings_file_kind` are set, the action additionally diffs the settings file between the previous and new release tags and propagates added/removed leaf keys:

- Updates the `env:` block (for `dotnet-appsettings` and `dotnet-conf`) or `settings:` / `settingsYaml:` blocks (for `angular-settings`) in the child chart's `values.yaml`.
- Mirrors the same changes under the parent chart's subkey in the parent `values.yaml` when `parent_chart_file` is set and the subkey's block already exists. The subkey is derived from the chart folder name.
- Appends a "Settings changes to review" section to the helm-charts PR body listing added/removed keys so a human can update the hand-curated chart README.

New keys are inserted with blank placeholders by JSON type (`""`, `false`, `0`). No README edits are made automatically. Re-running the action for the same release is a no-op.

Only the added and removed key lines change. The `values.yaml` files are edited as a YAML round-trip, so comments, quoting, block-sequence indentation (the `helm create` style, with list items indented under their key), and long unindented scalars are all preserved. Additions are appended inside the patched block: a blank line separating it from the next key stays after the new keys, and so do any comments dedented out of the block to introduce that next key. This matters because helm-charts compares a parent chart's subkey block against the child `values.yaml` as raw text in CI — any incidental reformatting desyncs the pair and fails the check.

##### Choosing between `dotnet-appsettings` and `dotnet-conf`

Both kinds target ASP.NET Core configuration files and emit the same `Section__Key` flat-key shape into the chart's `env:` block. Pick the one that matches the file your app ships:

| | `dotnet-appsettings` | `dotnet-conf` |
| --- | --- | --- |
| **File format** | JSON (with optional JSONC `//` and `/* */` comments) | INI-style: `Section__Key = value`, optionally prefixed with `#` to comment out a default |
| **Typical filename** | `appsettings.json` | `appsettings.conf` |
| **Type inference** | Yes — strings, bools, and numbers are detected from the JSON literal, so placeholders are typed (`""`, `false`, `0`) | No — the format is untyped, so every new key is added as `""` |
| **Nested objects** | Walks the JSON tree to build `Section__Key` keys | Authors already write `Section__Key` directly; the parser just collects them line-by-line |
| **Scalar arrays** | First element emitted as `Key__0` | Authors typically write `Key__0 = ...` directly; collected as-is |
| **Comments** | JSONC line/block comments stripped before parsing | Lines starting with `#` (including dividers like `####`) are tolerated; entries are recognized whether commented out or active |
| **Duplicate keys** | Last value wins (standard JSON semantics) | First occurrence wins; later duplicates (e.g., the example/dev sections at the bottom of `appsettings.conf`) are ignored |

If the source file is a hybrid you control, prefer `dotnet-appsettings` so placeholders pick up the right type. Use `dotnet-conf` when the upstream project distributes a `.conf` file — feeding that text to the JSON parser would fail.

When `settings_file` is set the action checks out the calling repository at `release_tag` with full tag history into a `source/` sub-path. Consumers do not need to add their own `actions/checkout` step.

#### Example Usage

```yaml
name: Update Helm Chart

on:
  release:
    types: [published]

jobs:
  update:
    runs-on: ubuntu-latest
    steps:
      - name: Update Helm chart
        uses: cmu-sei/Crucible-Github-Actions/actions/update-helm-chart@update-helm-chart-v3
        with:
          app_name: TopoMojo API
          github_app_client_id: ${{ secrets.CRUCIBLE_HELM_UPDATE_CLIENT_ID }}
          github_app_private_key: ${{ secrets.CRUCIBLE_HELM_UPDATE_PRIVATE_KEY }}
          chart_file: charts/topomojo/charts/topomojo-api/Chart.yaml
          parent_chart_file: charts/topomojo/Chart.yaml
```

### Repository Configuration Checklist

1. **Create credentials** for pushing to `cmu-sei/helm-charts`.
   - Preferred: register a GitHub App with `contents:write` and `pull_request:write`, install it on `cmu-sei/helm-charts`, and store the app client ID and private key as repository secrets (e.g., `CRUCIBLE_HELM_UPDATE_CLIENT_ID`/`CRUCIBLE_HELM_UPDATE_PRIVATE_KEY`).
   - Alternative: use a fine-grained PAT limited to the Helm charts repo and store as `HELM_CHARTS_TOKEN`; pass it via the optional `helm_repo_token` input.
2. **Add the workflow** (example above) to the application repository.
   - Trigger on `release` with `types: [published]`.
3. **Reference the action** by pinning the floating major tag (e.g. `update-helm-chart-v3`).
4. **Provide chart paths** that match the structure in `cmu-sei/helm-charts`.
   - `chart_file` must point at the child chart’s `Chart.yaml`.
   - `parent_chart_file` should list any umbrella chart `Chart.yaml` files that need a version bump.

When the workflow runs on a release event it will push a feature branch directly to
`cmu-sei/helm-charts` (or your configured `helm_chart_repo`) named `update-<slug>-<version>` and open a PR titled
`<App name> to <version>`.

### Header Check

`actions/header` enforces that every tracked file carries the standard Crucible license header. It can optionally use block comments when a language does not support line comments.

#### Inputs

| Name | Required | Description |
| --- | --- | --- |
| `github_token` | ✅ | Token with push rights to the calling repository (usually `${{ secrets.GITHUB_TOKEN }}`). |
| `use_block_comments` |  | Set to `true` to wrap the header in `/* */` style comments. Defaults to `false` so the script prefers single-line prefixes. |

#### Example Usage

```yaml
jobs:
  headers:
    runs-on: ubuntu-latest
    steps:
      - uses: cmu-sei/Crucible-Github-Actions/actions/header@header-v1
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          use_block_comments: false
```

Call this action from `pull_request` (or `push`) workflows only; it refuses to run on `pull_request_target`, `issue_comment` and `workflow_run`, because it checks out and pushes to the PR head.

The action checks out the current branch, runs `header.py` to add missing headers, and automatically commits/pushes fixes when changes are detected.

#### Exempting files with `.headerignore`

Some files should never receive the Crucible header — for example, vendored sources or files managed by external tooling that carry their own upstream license. To exempt them, add a `.headerignore` file at the root of the calling repository. It uses gitignore-style syntax:

- One pattern per line; blank lines and lines starting with `#` are ignored.
- Glob patterns are matched against each file's repo-relative, forward-slash path (e.g. `*.md`, `vendor/**`).
- A directory pattern (a bare directory name or one with a trailing slash, e.g. `.agents/`) exempts everything beneath it.

```gitignore
# .headerignore — files managed by external tooling; do not add SEI headers.
.agents/
.claude/
```

Matched files are logged as `skipping (ignored): <path>` and left untouched. When no `.headerignore` file is present, every supported file is checked as before.

## Reusable Workflows

### Build & Publish Image

`.github/workflows/docker-build.yaml` is a `workflow_call` reusable workflow that builds Docker images with Buildx, applies standard semver/ref tagging via `docker/metadata-action`, and optionally pushes to Docker Hub. It can also build a secondary target stage (e.g., a worker image) using the same tag set.

#### Inputs

| Name | Required | Description |
| --- | --- | --- |
| `imageName` | ✅ | Base image name such as `cmusei/myapp`. |
| `tagName` |  | Explicit tag override. When omitted, tags are inferred from semver, branches, or tags. |
| `dockerfilePath` |  | Path to the Dockerfile (`./Dockerfile` by default). |
| `additionalTarget` |  | Optional extra build stage to publish (tags will be suffixed with `-<target>`). |
| `push` |  | Set to `false` to force a build-only run even outside PRs. Defaults to `true` on non-PR events. |
| `versionMode` |  | How to inject version at build time: `none` (default), `npm`, or `csproj`. |
| `versionFiles` |  | Newline-separated file paths to update (used by `npm` mode to set version in `package.json` files before build). |
| `buildArgs` |  | Optional Docker build args (newline-separated `key=value`). |
| `platforms` |  | Comma-separated target platforms; default `linux/amd64,linux/arm64`. |
| `preBuildCommands` |  | Optional shell commands to run before the Docker build (e.g., fetch artifacts). |

#### Required Secrets

- `DOCKERHUB_USERNAME`
- `DOCKERHUB_PASSWORD`

#### Example Usage

```yaml
jobs:
  docker:
    uses: cmu-sei/Crucible-Github-Actions/.github/workflows/docker-build.yaml@docker-v1
    with:
      imageName: cmusei/topomojo-api
      additionalTarget: worker
    secrets:
      DOCKERHUB_USERNAME: ${{ secrets.DOCKERHUB_USERNAME }}
      DOCKERHUB_PASSWORD: ${{ secrets.DOCKERHUB_PASSWORD }}
```

Callers inherit the workflow’s caching, tagging, and push logic without duplicating build boilerplate across repositories.

### CodeQL

`.github/workflows/codeql.yaml` is a `workflow_call` reusable workflow that runs CodeQL code scanning (`github/codeql-action` v4) so each repository's CodeQL file can be a short caller instead of its own copy of the analysis steps.

- **`plan`** validates `languages` and `build-mode` against an allowlist and builds a matrix of `{language, build-mode}` entries. The `actions` language (the caller's own GitHub Actions workflows) is always added unless `include-actions` is `false`.
- **`analyze`** runs one job per language: checkout, CodeQL init, an optional manual build, and analysis, uploading results to the repository's **Security → Code scanning** tab under the category `/language:<language>`.

Build modes: interpreted languages (`javascript-typescript`, `python`, `ruby`, `rust`) and `actions` always use `none`. C# defaults to `none` (no build needed); set `build-mode` to `autobuild` or `manual` to analyze a real build instead (the .NET SDK is then installed from the repository's `global.json`). Other compiled languages (`go`, `java-kotlin`, `c-cpp`, `swift`) use `autobuild`, or `manual` when requested; Go also installs the toolchain from `go.mod`, which must be at the repository root. `build-mode` applies to every compiled language in a single call, so pass one compiled language per caller (the expected use).

The query suite (default `security-extended`), the central `paths-ignore` list (`**/node_modules/**`, `**/dist/**`, `**/bin/**`, `**/obj/**`) and the central query exclusions (`actions/unpinned-tag`) are defined in this workflow, so changing them here and cutting a `codeql` release updates every caller. The `plan` job merges them with any caller exclusions into a single CodeQL config (logged as `Config: {...}`).

This repository scans itself with the same workflow — see `.github/workflows/codeql-analysis.yml` — and is a working caller example.

#### Inputs

| Name | Required | Description | Default |
| --- | --- | --- | --- |
| `languages` | ✅ | Comma-separated CodeQL languages, e.g. `csharp` or `javascript-typescript`. | |
| `include-actions` |  | Also scan the caller's GitHub Actions workflows (`actions` language). | `true` |
| `build-mode` |  | C# build mode: `none`, `autobuild`, or `manual`. Other compiled languages use `autobuild` unless this is `manual`. | `none` |
| `build-command` |  | Shell command run between init and analyze when `build-mode` is `manual` (e.g. `dotnet build Alloy.Api -c Release`). Required for `manual`. | `""` |
| `query-suite` |  | CodeQL query suite: `default` (CodeQL's default suite; no `queries` is passed), or one of the named suites `security-extended`, `security-and-quality`, `security-experimental`. Any other value fails the `plan` job. | `security-extended` |
| `runs-on` |  | Runner label for the analyze jobs. | `ubuntu-24.04` |
| `timeout-minutes` |  | Timeout for each analyze job. | `30` |
| `paths-ignore` |  | Newline-separated glob patterns to exclude, appended to the central list (`node_modules`, `dist`, `bin`, `obj`). Entries are trimmed, blank lines dropped; tabs or control characters fail the `plan` job. | `""` |
| `exclude-queries` |  | Comma-separated CodeQL query IDs to exclude (e.g. `cs/log-forging,js/xss`), appended to the central exclusions (`actions/unpinned-tag`). An ID not shaped like `<lang>/<query>` fails the `plan` job. | `""` |

#### Required Permissions

The shared workflow declares no permissions of its own (`permissions: {}` at the top level); the calling job must grant:

```yaml
permissions:
  actions: read
  contents: read
  security-events: write
```

#### Example Usage

API repository (`.github/workflows/codeql-analysis.yml`):

```yaml
name: CodeQL

# Keep the repo's existing `on:` block as-is when migrating (trigger clean-up is deferred).
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  schedule:
    - cron: "0 5 * * 5"

permissions: {}

jobs:
  codeql:
    uses: cmu-sei/Crucible-Github-Actions/.github/workflows/codeql.yaml@codeql-v1
    permissions:
      actions: read
      contents: read
      security-events: write
    with:
      languages: csharp
```

UI repository (`.github/workflows/codeql-analysis.yml`):

```yaml
name: CodeQL

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  schedule:
    - cron: "0 13 * * 6"

permissions: {}

jobs:
  codeql:
    uses: cmu-sei/Crucible-Github-Actions/.github/workflows/codeql.yaml@codeql-v1
    permissions:
      actions: read
      contents: read
      security-events: write
    with:
      languages: javascript-typescript
```

When migrating an existing CodeQL workflow, keep the repo's existing `on:` block; trigger clean-up is a separate effort.

#### Excluding paths and queries

Callers can add repository-specific exclusions; they are appended to (never replace) the central ones, and duplicates are dropped:

```yaml
    with:
      languages: csharp
      paths-ignore: |
        **/Migrations/**
        **/*.Tests/**
      exclude-queries: cs/log-forging
```

For interpreted languages and `build-mode: none`, `paths-ignore` removes the matching files from analysis entirely. For traced builds (`autobuild` / `manual`) CodeQL still extracts every compiled file, so `paths-ignore` only filters alerts in those paths out of the results. Paths that only exist after a build (for example NSwag-generated client code) are therefore only worth excluding under `build-mode: autobuild` or `manual`; with the default `none` they are never scanned in the first place. `exclude-queries` drops the listed queries' results for every language in the call. Central exclusions cannot be removed by callers.

Migration notes:

- CodeQL v4 rejects the old language aliases: callers migrating from `javascript` must use `javascript-typescript`.
- `swift` analysis needs a macOS runner, so set `runs-on` (for example `macos-15`) for it.
- The `actions/unpinned-tag` query is in the central exclusion list (merged into `query-filters` by the `plan` job, and not removable by callers) by org decision: consumers reference Crucible-Github-Actions by floating per-family tags (e.g. `@codeql-v1`) so that fixes propagate without a PR in every repository, and the rule would otherwise fire permanently on every caller. Pin third-party actions by commit SHA where you want that guarantee.

## Releasing

Each action family in this repository is versioned independently. Releases are tagged per family:

| Family | Contents | Tag example |
| --- | --- | --- |
| `docker` | `.github/workflows/docker-build.yaml` | `docker-v1.1.7` |
| `header` | Header Check composite action | `header-v1.0.1` |
| `update-helm-chart` | Update Helm Chart composite action | `update-helm-chart-v3.2.0` |
| `codeql` | `.github/workflows/codeql.yaml` | `codeql-v1.0.0` |
| `nuget`, `npm` | Reserved for upcoming families | `nuget-v1.0.0` |

Pre-existing `update-helm-chart` release tags used two segments (for example `update-helm-chart-v3.1`); new releases use three (`X.Y.Z`).

Every release produces three tags, all pointing at the same commit:

- `<family>-vX.Y.Z` — annotated release tag, never moved by this workflow (a GitHub Release is published for it).
- `<family>-vX.Y` — floating minor tag, force-moved to the latest patch.
- `<family>-vX` — floating major tag, force-moved to the latest minor/patch.

Consumers should pin the floating major tag (for example `@docker-v1`) so they pick up fixes automatically, and only change their reference for a new major version.

Merging to `main` does **not** release anything. Every merge that touches a family must be followed by a dispatch of the **Cut release** workflow (`.github/workflows/cut-release.yaml`) for that family, otherwise consumers on the floating tag never see the change:

```bash
gh workflow run cut-release.yaml -R cmu-sei/Crucible-Github-Actions -f family=<family> -f version=X.Y.Z
```

Releases are cut from `main` only: the workflow tags the current head of `main` and fails if dispatched from any other ref. It also refuses to run if `<family>-vX.Y.Z` already exists or if the version is not `X.Y.Z`. The Release notes are generated from the previous `<family>-vX.Y.Z` tag of the same family, so other families' changes are not listed.
