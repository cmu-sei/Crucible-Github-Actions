# Crucible GitHub Actions

Reusable GitHub Actions owned by the Crucible team. Consumers can depend on the actions
in this repository to keep shared automation consistent across applications.

## Table of contents

- [Available Actions](#available-actions)
  - [Update Helm Chart](#update-helm-chart)
  - [Repository Configuration Checklist](#repository-configuration-checklist)
  - [Header Check](#header-check)
- [Reusable Workflows](#reusable-workflows)
  - [Build & Publish Image](#build--publish-image)
  - [CodeQL](#codeql)
  - [NuGet Release](#nuget-release)
  - [NuGet Relist](#nuget-relist)
  - [npm Release](#npm-release)
  - [.NET Build and Test](#net-build-and-test)
  - [npm Build and Test](#npm-build-and-test)
- [Continuous integration](#continuous-integration)
- [Dependabot](#dependabot)
- [Releasing](#releasing)
  - [Choosing the version bump](#choosing-the-version-bump)

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

### NuGet Release

`.github/workflows/nuget-release.yaml` is a `workflow_call` reusable workflow that builds, packs and publishes a NuGet package to nuget.org, then tags the commit and (by default) creates a GitHub release with the `.nupkg` attached. It replaces the per-repository client-package workflows in the API repositories and crucible-common-dotnet's release + apply-tag pair.

It covers both package shapes in use:

- **API client packages** (set `openapi-project`): build the API, export its OpenAPI document with `dotnet swagger tofile`, run NSwag in the client project's directory to generate the client, then pack the client project.
- **Plain libraries** (crucible-common-dotnet): pack the project directly.

The job runs validate → setup .NET → resolve metadata → (generate OpenAPI client) → pack → upload artifact → push → (unlist) → GitHub release/tag. Push comes before the tag/release, so a failed push never leaves an orphaned tag. `dry-run: true` stops after the artifact upload (`nupkg-<PackageId>-<version>`), which is how a new caller is validated without credentials.

Package metadata is set at pack time, so nothing is patched into the `.nuspec` afterwards: authors and company `Carnegie Mellon University/Software Engineering Institute`, `PackageLicenseExpression` `MIT`, project URL `https://github.com/cmu-sei/crucible`, and the repository URL/commit of the caller. The package id comes from the project's `PackageId` (the project name unless overridden).

Behaviour the callers rely on:

- The .NET SDK comes from the repository's `global.json`; set `dotnet-version` only for repositories without one.
- `dotnet tool restore` runs **inside** `openapi-project`, so a `.config/dotnet-tools.json` either there or at the repository root works. The Swashbuckle CLI version in that manifest (`swashbuckle.aspnetcore.cli`) must match the API's `Swashbuckle.AspNetCore` package version.
- NSwag runs **inside** the client project's directory via `npx --no-install nswag run`, so that directory needs a `package.json` declaring `nswag` (`npm ci` is used when a `package-lock.json` is present, `npm install` otherwise), and `nswag.json` must set `"runtime": "Net100"` (NSwag 14.x).
- The release tag defaults to `<PackageId>.<version>` (for example `Alloy.Api.Client.1.2.3`), the format the API repositories already use.
- Versions with SemVer build metadata (`1.2.3+abc`) are rejected: NuGet drops the metadata from the package file name.
- Runs are serialized per caller repository and `project` (concurrency group, `cancel-in-progress: false`). GitHub still cancels an older *pending* run in the same group when a newer one queues, so dispatch releases of the same project one at a time.
- `description` may contain `,` and `;` (escaped for MSBuild before `dotnet pack`).

#### Inputs

| Name | Required | Description | Default |
| --- | --- | --- | --- |
| `version` | ✅ | Package version (SemVer, e.g. `1.2.3` or `1.2.3-rc.1`). A leading `v` is stripped; anything else that is not SemVer fails the run before checkout. | |
| `project` | ✅ | Path to the `.csproj` to pack, e.g. `Alloy.Api.Client/Alloy.Api.Client.csproj`. | |
| `openapi-project` |  | API project directory. When set, the OpenAPI document is exported from it and NSwag is run in the client project's directory. | `""` |
| `openapi-assembly` |  | API assembly name. | `openapi-project` directory name |
| `openapi-document` |  | Swagger document name passed to `dotnet swagger tofile`. | `v1` |
| `openapi-output` |  | File name NSwag reads, written next to the client project (`openapi.json` for TopoMojo). | `swagger.json` |
| `dotnet-version` |  | SDK to install when the repository has no `global.json` (e.g. `10.0.x`). Leave empty to use `global.json`. | `""` |
| `description` |  | Package description. | the project's own `<Description>` |
| `include-symbols` |  | Also produce and push a `.snupkg` symbols package. | `false` |
| `unlist` |  | Unlist the version on nuget.org right after pushing (API client convention; re-list with [NuGet Relist](#nuget-relist)). | `false` |
| `github-release` |  | `release` = tag + GitHub release with the `.nupkg` attached; `tag` = tag only; `none` = skip. | `release` |
| `release-tag` |  | Tag name. | `<PackageId>.<version>` |
| `auth-mode` |  | `api-key` (`NUGET_APIKEY` secret) or `trusted` (NuGet trusted publishing; see [below](#trusted-publishing-later)). | `api-key` |
| `nuget-user` |  | nuget.org account that owns the trusted-publishing policy (`auth-mode: trusted` only). | `""` |
| `dry-run` |  | Build and pack only; skip push, unlist and GitHub release. | `false` |

#### Secrets

Both are optional at the workflow level; which ones a caller needs depends on its mode.

| Name | Needed when | Description |
| --- | --- | --- |
| `NUGET_APIKEY` | `auth-mode: api-key` and not `dry-run` | nuget.org push key. |
| `NUGET_APIKEY_UNLIST` | `unlist: true` and not `dry-run` | nuget.org key with unlist scope. |

#### Outputs

| Name | Description |
| --- | --- |
| `package-id` | Resolved `PackageId`. |
| `version` | Normalized version (leading `v` stripped). |

#### Required Permissions

The workflow declares no top-level `permissions:` block on purpose: a called workflow that requests more than its caller grants fails at startup, so the job inherits the calling job's grant. The calling job grants:

```yaml
permissions:
  contents: write      # tag + GitHub release
  # id-token: write    # only for auth-mode: trusted
```

A `dry-run: true` caller needs nothing beyond `contents: read` (checkout).

#### Example Usage

API repository (`.github/workflows/build-client.yml`), shown for alloy.api:

```yaml
name: Build Client Package

on:
  workflow_dispatch:
    inputs:
      clientVersion:
        description: "Version of the Client package"
        required: true

permissions: {}

jobs:
  release:
    uses: cmu-sei/Crucible-Github-Actions/.github/workflows/nuget-release.yaml@nuget-v1
    permissions:
      contents: write          # tag + GitHub release with the .nupkg
    with:
      version: ${{ inputs.clientVersion }}
      project: Alloy.Api.Client/Alloy.Api.Client.csproj
      openapi-project: Alloy.Api
      description: NSwag generated client for Crucible's Alloy.Api
      unlist: true
    secrets:
      NUGET_APIKEY: ${{ secrets.NUGET_APIKEY }}
      NUGET_APIKEY_UNLIST: ${{ secrets.NUGET_APIKEY_UNLIST }}
```

Library repository (crucible-common-dotnet `.github/workflows/release-package.yml`, replacing its push-to-nuget job and `apply-tag.yml`):

```yaml
name: Release package to NuGet

on:
  workflow_dispatch:
    inputs:
      packageName:
        description: "The NuGet package (which corresponds to a Crucible.Common project) you want to release"
        required: true
        type: choice
        options:
          - Crucible.Common.Authentication
          - Crucible.Common.EntityEvents
          - Crucible.Common.ServiceDefaults
          - Crucible.Common.Utilities
      versionNumber:
        description: "A semver version string (e.g. 1.0.0)"
        required: true
        type: string

permissions: {}

jobs:
  build-and-test:
    uses: ./.github/workflows/build-and-test.yml
    permissions:
      contents: read

  release:
    needs: build-and-test
    uses: cmu-sei/Crucible-Github-Actions/.github/workflows/nuget-release.yaml@nuget-v1
    permissions:
      contents: write          # tag (created only after a successful push)
    with:
      version: ${{ inputs.versionNumber }}
      project: src/${{ inputs.packageName }}/${{ inputs.packageName }}.csproj
      include-symbols: true
      dotnet-version: "10.0.x"     # repo has no global.json
      github-release: tag
      release-tag: ${{ inputs.packageName }}-${{ inputs.versionNumber }}
    secrets:
      NUGET_APIKEY: ${{ secrets.NUGET_APIKEY }}
```

In the library example, `release-tag` is built from the raw `versionNumber` input, so give `versionNumber` without a leading `v` (otherwise the tag carries it); the shared workflow normalizes `version` itself (strips a leading `v`), but not a caller-built `release-tag`.

To validate a new caller without credentials, add `dry-run: true` under `with:` and dispatch it once; the packed `.nupkg` is uploaded as a run artifact.

#### Per-repository values

| Repository | `project` | `openapi-project` | Notes |
| --- | --- | --- | --- |
| alloy.api | `Alloy.Api.Client/Alloy.Api.Client.csproj` | `Alloy.Api` | Set `nswag.json` `runtime` to `Net100`, bump `nswag` to 14.x in the client `package.json` (commit a `package-lock.json`), bump the client's `System.Text.Json` to 10.0.0 (NSwag 14 emits `JsonStringEnumConverter<T>`), and bump `swashbuckle.aspnetcore.cli` in `Alloy.Api/.config/dotnet-tools.json` from 6.8.1 to the API's Swashbuckle version (10.1.0). |
| blueprint.api | `Blueprint.Api.Client/Blueprint.Api.Client.csproj` | `Blueprint.Api` | Same `nswag.json` runtime / `nswag` 14.x changes as alloy.api (`System.Text.Json` is already 10.0.0 via `Directory.Packages.props`). The repository has no `dotnet-tools.json`: add one (root or `Blueprint.Api/.config/`) with `swashbuckle.aspnetcore.cli` at the API's Swashbuckle version (10.0.1). |
| cite.api | `Cite.Api.Client/Cite.Api.Client.csproj` | `Cite.Api` | |
| gallery.api | `Gallery.Api.Client/Gallery.Api.Client.csproj` | `Gallery.Api` | |
| steamfitter.api | `Steamfitter.Api.Client/Steamfitter.Api.Client.csproj` | `Steamfitter.Api` | |
| player.api | `Player.Api.Client/Player.Api.Client.csproj` | `Player.Api` | |
| caster.api | `src/Caster.Api.Client/Caster.Api.Client.csproj` | `src/Caster.Api` | |
| vm.api | `src/Player.Vm.Api.Client/Player.Vm.Api.Client.csproj` | `src/Player.Vm.Api` | |
| topomojo | `src/TopoMojo.Api.Client/TopoMojo.Api.Client.csproj` | `src/TopoMojo.Api` | Also `openapi-output: openapi.json` and `dotnet-version: "10.0.x"`; add a client `package.json` declaring `nswag`. |

#### Trusted publishing (later)

Today every caller uses `auth-mode: api-key`. NuGet trusted publishing (OIDC via `NuGet/login`, exchanging the job's GitHub token for a short-lived push key) is already wired into the workflow so switching is mostly a caller change:

```yaml
# Phase 2 (trusted publishing): the only change in each caller
jobs:
  release:
    uses: cmu-sei/Crucible-Github-Actions/.github/workflows/nuget-release.yaml@nuget-v1
    permissions:
      contents: write
      id-token: write          # NEW: lets NuGet/login exchange the OIDC token
    with:
      # ...unchanged inputs...
      auth-mode: trusted       # NEW
      nuget-user: <nuget.org account that owns the trusted-publishing policy>
    # secrets: NUGET_APIKEY no longer passed (NUGET_APIKEY_UNLIST still needed for unlist)
```

The shared workflow inherits the caller's grant, so nothing changes in it; api-key callers do not grant `id-token: write`. Open questions before switching:

- How nuget.org trusted-publishing policies identify a reusable workflow: whether the policy names the caller's workflow file or this repository's `nuget-release.yaml`.
- Whether the short-lived key issued by `NuGet/login` has unlist scope; until confirmed, `unlist: true` callers keep passing `NUGET_APIKEY_UNLIST`.

### NuGet Relist

`.github/workflows/nuget-relist.yaml` is a `workflow_call` reusable workflow that re-lists a previously unlisted package version on nuget.org. It pairs with `nuget-release.yaml` `unlist: true`: API client packages are pushed unlisted, then listed once the matching API release ships. It validates `package-id` and `version` (same SemVer rule as NuGet Release) before calling nuget.org. There is no dry-run: the call needs the unlist-scoped key.

#### Inputs

| Name | Required | Description |
| --- | --- | --- |
| `package-id` | ✅ | NuGet package id, e.g. `Alloy.Api.Client`. |
| `version` | ✅ | Version to re-list (SemVer; a leading `v` is stripped). |

#### Secrets

| Name | Required | Description |
| --- | --- | --- |
| `NUGET_APIKEY_UNLIST` | ✅ | nuget.org key with unlist scope. |

#### Required Permissions

None: the workflow declares `permissions: {}` and talks only to nuget.org.

#### Example Usage

API repository (`.github/workflows/list-package.yml`):

```yaml
name: List Client Package

on:
  workflow_dispatch:
    inputs:
      clientVersion:
        description: "Version of the Client package"
        required: true

permissions: {}

jobs:
  relist:
    uses: cmu-sei/Crucible-Github-Actions/.github/workflows/nuget-relist.yaml@nuget-v1
    with:
      package-id: Alloy.Api.Client
      version: ${{ inputs.clientVersion }}
    secrets:
      NUGET_APIKEY_UNLIST: ${{ secrets.NUGET_APIKEY_UNLIST }}
```

### npm Release

`.github/workflows/npm-release.yaml` is a `workflow_call` reusable workflow that publishes an npm package for Crucible libraries (Crucible.Common.Ui, console-forge). One job validates the inputs, sets the version in each listed `package.json` (`npm version --no-git-tag-version`), runs the caller's build command, optionally commits the version bump back to the triggering branch, and runs `npm publish` (with `--access public`, the dist-tag if given, and `--provenance` by default).

Inputs are passed to scripts through environment variables only, and the version is validated as SemVer before anything else runs (a leading `v` is stripped, so release tag names can be passed directly; build metadata such as `+build.5` is rejected because `npm version` strips it, so the `{version}` path and commit message would not match). `dry-run: true` validates a caller end to end without publishing: the version commit is skipped, `npm publish --dry-run` prints the tarball contents, and no `NPM_TOKEN` is needed.

Runs share the concurrency group `npm-release-<repository>` with `cancel-in-progress: false`, but GitHub still cancels an older *pending* run when a newer one queues in the same group, so queue releases one at a time.

#### Inputs

| Name | Required | Description | Default |
| --- | --- | --- | --- |
| `version` | ✅ | Package version (SemVer). A leading `v` is stripped. | |
| `dist-tag` |  | npm dist-tag, e.g. `next` or `rc`. Required for prerelease versions (`X.Y.Z-…`): npm refuses to publish them without `--tag`, so the workflow fails at validation instead. Must match `^[a-z][a-z0-9._-]*$`. | `""` |
| `version-dirs` |  | Newline-separated directories whose `package.json` gets the version (root first). | `.` |
| `build-command` |  | Shell command that installs dependencies and builds the package. | `npm ci && npm run build` |
| `publish-path` | ✅ | Directory or `.tgz` to publish. `{version}` is replaced with the version. A relative path is given a `./` prefix (npm would otherwise read a bare `dist/pkg` as a GitHub `owner/repo` shorthand). | |
| `commit-version` |  | Commit the `package.json`/`package-lock.json` bump back to the triggering branch (needs `contents: write`). Requires a branch ref (`workflow_dispatch` or `push` on a branch); on a tag, release or pull request run the workflow fails at validation (unless `dry-run`). | `false` |
| `provenance` |  | Publish with npm provenance (needs `id-token: write`). | `true` |
| `node-version` |  | Node.js version for `actions/setup-node`. | `24` |
| `auth-mode` |  | `api-key` (publish with the `NPM_TOKEN` secret) or `trusted` (npm trusted publishing). | `api-key` |
| `dry-run` |  | Run `npm publish --dry-run` and skip the version commit. | `false` |

#### Secrets

| Name | Required | Description |
| --- | --- | --- |
| `NPM_TOKEN` | With `auth-mode: api-key` (except in `dry-run`) | npm automation/granular token. Crucible repositories pass their existing `NPM_APIKEY` secret. |

#### Required Permissions

The shared workflow declares no permissions block, so its job inherits the calling job's grant (a called workflow that declares more than its caller grants fails to start, which would break read-only callers). The calling job grants only what it uses: `contents: read` (or `contents: write` with `commit-version: true`) plus `id-token: write` when `provenance` is `true` or `auth-mode` is `trusted`.

#### Example Usage

Crucible.Common.Ui (manual dispatch, version bump committed back to the branch):

```yaml
on:
  workflow_dispatch:
    inputs:
      version:
        description: "Version of the Client package"
        required: true
      tag:
        description: "npm dist-tag (required for prerelease versions, e.g. next, rc)"
        required: false

permissions: {}

jobs:
  release:
    uses: cmu-sei/Crucible-Github-Actions/.github/workflows/npm-release.yaml@npm-v1
    permissions:
      contents: write          # commit-version pushes the bump to the branch
      id-token: write          # npm provenance
    with:
      version: ${{ inputs.version }}
      dist-tag: ${{ inputs.tag }}
      version-dirs: |
        .
        projects/@crucible-common
      build-command: npm install && npm run pack
      publish-path: dist/@crucible-common/cmusei-crucible-common-{version}.tgz
      commit-version: true
    secrets:
      NPM_TOKEN: ${{ secrets.NPM_APIKEY }}
```

console-forge (publish on a GitHub Release, no commit back):

```yaml
on:
  release:
    types: [published]

permissions: {}

jobs:
  publish:
    uses: cmu-sei/Crucible-Github-Actions/.github/workflows/npm-release.yaml@npm-v1
    permissions:
      contents: read           # no version commit back to main
      id-token: write          # npm provenance
    with:
      version: ${{ github.event.release.tag_name }}
      dist-tag: ${{ github.event.release.prerelease && 'next' || '' }}
      version-dirs: projects/console-forge   # the library's package.json; the root one is a 0.0.0 shell
      build-command: npm ci && (cd projects/console-forge && npm ci) && npm run build
      publish-path: ./dist/console-forge     # adjust to the package's build output (ng-package.json `dest`)
    secrets:
      NPM_TOKEN: ${{ secrets.NPM_APIKEY }}
```

#### Provenance vs. trusted publishing

Provenance and trusted publishing are different things. **Provenance** (`--provenance`) attaches a signed attestation linking the published package to the workflow run that built it; it uses the job's OIDC token (`id-token: write`) but the publish itself is still authenticated with `NPM_TOKEN`. **Trusted publishing** replaces `NPM_TOKEN` with OIDC authentication against a trusted-publisher configuration on npmjs.com. Callers use `auth-mode: api-key` today; switching to `auth-mode: trusted` (and dropping the `NPM_TOKEN` secret) is a later phase, once each package has a trusted publisher configured.

### .NET Build and Test

`.github/workflows/dotnet-test.yaml` is a `workflow_call` reusable workflow that builds an API repository and runs its xUnit v3 test project against PostgreSQL (the shared Crucible API test harness, which starts PostgreSQL itself through Testcontainers).

One job restores, builds and tests, then checks the log for the harness's `[<assembly>] database provider: PostgreSQL` banner (so a harness change cannot silently stop exercising PostgreSQL) and uploads the TRX results as the `test-results` artifact, also when tests fail.

**Test runner.** The workflow reads `test.runner` from the repository's `global.json`, the same setting `dotnet test` reads on the .NET 10 SDK, so CI and local runs always agree:

| `global.json` | How the tests run |
| --- | --- |
| no `test` section (the default), or `"runner": "VSTest"` | `dotnet test` through the VSTest bridge. |
| `"test": { "runner": "Microsoft.Testing.Platform" }` | The test project runs as a Microsoft.Testing.Platform app (`dotnet run`), built with `UseMicrosoftTestingPlatformRunner=true`. Required by xunit.v3 4 and later on the .NET 10 SDK. |

`dotnet run` is used rather than `dotnet test` for Microsoft.Testing.Platform because `dotnet test` does not forward the test app's console or xUnit diagnostic messages, so the banner would never reach the log. Either way the results land in `<test-project>/TestResults/test-results.trx`.

Runs share the concurrency group `dotnet-test-<repository>-<workflow>-<ref>` with `cancel-in-progress: true`, so a newer push supersedes a run still in flight.

#### Inputs

| Name | Required | Description | Default |
| --- | --- | --- | --- |
| `test-project` | ✅ | Test project directory, relative to the repository root (e.g. `Example.Api.Tests`, `src/Example.Api.Tests`). | |
| `test-assembly` |  | Assembly name the PostgreSQL banner names. | `test-project` directory name |
| `expect-postgres` |  | Fail unless the log shows the PostgreSQL banner. | `true` |
| `dotnet-version` |  | SDK to install when the repository has no `global.json` (e.g. `10.0.x`). Leave empty to use `global.json`. | `""` |
| `timeout-minutes` |  | Job timeout. | `30` |

#### Required Permissions

The shared workflow declares no permissions block, so its job inherits the calling job's grant. The calling job grants `contents: read`.

#### Example Usage

```yaml
name: Build and Test

on:
  pull_request:
  push:
    branches: [main]

permissions: {}

jobs:
  build-and-test:
    uses: cmu-sei/Crucible-Github-Actions/.github/workflows/dotnet-test.yaml@dotnet-test-v1
    permissions:
      contents: read
    with:
      test-project: Example.Api.Tests
```

The status-check context is `<caller job id> / Build and Test`, here `build-and-test / Build and Test`.

### npm Build and Test

`.github/workflows/npm-test.yaml` is a `workflow_call` reusable workflow that installs, tests and optionally lints and builds a UI repository (Angular apps built with npm). One job sets up Node with the npm cache, runs the install command, the lint command (if set), the test command, and the build command (if set), then uploads the coverage report as the `coverage` artifact, also when tests fail.

Commands are run with `bash -euo pipefail -c`, so a failing command fails the job. Coverage thresholds belong to the test runner (for example `coverageThresholds` in `angular.json`); the workflow only uploads the report.

Runs share the concurrency group `npm-test-<repository>-<workflow>-<ref>` with `cancel-in-progress: true`, so a newer push supersedes a run still in flight.

#### Inputs

| Name | Required | Description | Default |
| --- | --- | --- | --- |
| `node-version` |  | Node.js version for `actions/setup-node` (`24`, `24.11`, `24.11.1`). Match the node image in the repository's Dockerfile. | `24` |
| `install-command` |  | Installs dependencies. | `npm ci` |
| `test-command` |  | Runs the tests once (no watch mode). | `npm run test:coverage` |
| `lint-command` |  | Lints before the tests, e.g. `npm run lint`. Empty skips the step. | `""` |
| `build-command` |  | Builds after the tests, e.g. `npx ng build --configuration production`. Empty skips the step. | `""` |
| `coverage-path` |  | Coverage directory uploaded as the `coverage` artifact. Empty skips the upload. | `coverage` |
| `timeout-minutes` |  | Job timeout. | `20` |

#### Required Permissions

The shared workflow declares no permissions block, so its job inherits the calling job's grant. The calling job grants `contents: read`.

#### Example Usage

```yaml
name: Build Test

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

permissions: {}

jobs:
  build-test:
    uses: cmu-sei/Crucible-Github-Actions/.github/workflows/npm-test.yaml@npm-test-v1
    permissions:
      contents: read
    with:
      node-version: "24"
      build-command: npx ng build --configuration production
```

The status-check context is `<caller job id> / Build and Test`, here `build-test / Build and Test`.

## Continuous integration

`.github/workflows/ci.yaml` runs on every pull request and on pushes to `main`: `actionlint` (pinned, checksum-verified, with shellcheck) over all workflows (composite `action.yaml` files are not linted by actionlint), every `tests/*.test.sh` (the shell logic of the shared CodeQL plan job, the NuGet and npm workflows' input validation, the .NET build-and-test workflow's input validation and test-runner detection, and the npm build-and-test workflow's input validation), and the `actions/update-helm-chart` pytest suite. The `CodeQL` workflow (`.github/workflows/codeql-analysis.yml`) additionally scans this repository's Python and Actions code.

The `main` ruleset should list these required status-check contexts, exactly as written: `actionlint`, `codeql-plan-tests`, `update-helm-chart-tests`, `codeql / Plan languages`, `codeql / Analyze (python)`, `codeql / Analyze (actions)`. A status-check context is the job name, not `<workflow> / <job>` (the UI prefixes the workflow name only for grouping); for the CodeQL self-scan, which calls a reusable workflow, the context is `<caller job id> / <called job name>`.

## Dependabot

`.github/dependabot.yml` checks the GitHub Actions used by the workflows and composite actions weekly and groups all updates into one pull request.

`.github/workflows/dependabot-auto-merge.yaml` approves and queues auto-merge (squash) for Dependabot patch updates; minor and major updates are left for manual review. It never checks out code. It depends on these repository settings, configured in this order:

1. Required status checks on `main` (the contexts listed in [Continuous integration](#continuous-integration)), so auto-merge waits for CI.
2. "Allow auto-merge" enabled.

Configure the required status checks **before** enabling auto-merge: otherwise the App's approval satisfies the one-review rule and an auto-merge PR can merge before CI finishes.

The approval and merge are performed with a token minted from the org's `crucible-ci` GitHub App, not `GITHUB_TOKEN`. Merges made with `GITHUB_TOKEN` do not trigger `push` workflows; merges made under the App do, so the resulting push to `main` triggers workflows such as Auto release. This requires:

- The `crucible-ci` App installed on this repository (Contents and Pull requests read/write); the minted token is narrowed to only those two permissions.
- `CRUCIBLE_HELM_UPDATE_CLIENT_ID` and `CRUCIBLE_HELM_UPDATE_PRIVATE_KEY` available as **Dependabot** secrets for this repository (Settings → Secrets and variables → Dependabot, or org-level Dependabot secrets scoped to this repository). `pull_request` runs for PRs authored by `dependabot[bot]` receive Dependabot secrets, not Actions secrets. If they are missing, the workflow fails with an explicit error before minting a token.

Auto-merged bumps are released by **Auto release** on the resulting push to `main`, which cuts a patch release for each affected family (see [Releasing](#releasing)).

## Releasing

Each action family in this repository is versioned independently. Releases are tagged per family:

| Family | Contents | Tag example |
| --- | --- | --- |
| `docker` | `.github/workflows/docker-build.yaml` | `docker-v1.1.7` |
| `header` | Header Check composite action | `header-v1.0.1` |
| `update-helm-chart` | Update Helm Chart composite action | `update-helm-chart-v3.2.0` |
| `codeql` | `.github/workflows/codeql.yaml` | `codeql-v1.0.0` |
| `nuget` | `.github/workflows/nuget-release.yaml`, `nuget-relist.yaml` | `nuget-v1.0.0` |
| `npm` | `.github/workflows/npm-release.yaml` | `npm-v1.0.0` |
| `dotnet-test` | `.github/workflows/dotnet-test.yaml` | `dotnet-test-v1.0.0` |
| `npm-test` | `.github/workflows/npm-test.yaml` | `npm-test-v1.0.0` |

Pre-existing `update-helm-chart` release tags used two segments (for example `update-helm-chart-v3.1`); new releases use three (`X.Y.Z`).

Every release produces three tags, all pointing at the same commit:

- `<family>-vX.Y.Z` — annotated release tag, never moved by this workflow (a GitHub Release is published for it).
- `<family>-vX.Y` — floating minor tag, force-moved to the latest patch.
- `<family>-vX` — floating major tag, force-moved to the latest minor/patch.

Consumers should pin the floating major tag (for example `@docker-v1`) so they pick up fixes automatically, and only change their reference for a new major version.

Merging to `main` automatically cuts the next release for every family whose files changed since its latest `<family>-vX.Y.Z` tag (the **Auto release** workflow, `.github/workflows/auto-release.yaml`); families without a release tag yet are skipped. A manual **Auto release** dispatch with `dry-run` reports what would be released without cutting anything.

### Choosing the version bump

By default a merge to `main` cuts a PATCH release for each changed family. To cut a minor or major release instead, include `[release:minor]` or `[release:major]` in the PR title (or in any commit message in the PR); squash merges carry the PR title into the merge commit. `[release:skip]` holds the release for a manual `Cut release` dispatch, for example to coordinate several PRs into one release.

| Marker | Release from `1.4.2` |
| --- | --- |
| `[release:minor]` | `1.5.0` |
| `[release:major]` | `2.0.0` |
| `[release:skip]` | none |

Markers are case-insensitive and only count on commits that touch the family's files. When several PRs are merged before the workflow runs (for example while a previous run is still in progress), the highest bump wins, and `[release:skip]` wins over all.

To release a specific version by hand (for example after a `[release:skip]`), dispatch the **Cut release** workflow (`.github/workflows/cut-release.yaml`):

```bash
gh workflow run cut-release.yaml -R cmu-sei/Crucible-Github-Actions -f family=<family> -f version=X.Y.Z
```

Releases are cut from `main` only: the workflow tags the current head of `main` and fails if dispatched from any other ref. It also refuses to run if `<family>-vX.Y.Z` already exists or if the version is not `X.Y.Z`. The Release notes are generated from the previous `<family>-vX.Y.Z` tag of the same family, so other families' changes are not listed.
