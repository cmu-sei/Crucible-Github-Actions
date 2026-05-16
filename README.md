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
| `github_app_id` | ✅ | Optional GitHub App ID that should mint a token for pushing to the Helm repo. Provide via a secret. |
| `github_app_private_key` | ✅ | Private key for the GitHub App. Provide via a secret. |
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
        uses: cmu-sei/Crucible-Github-Actions/actions/update-helm-chart@main
        with:
          app_name: TopoMojo API
          github_app_id: ${{ secrets.CRUCIBLE_HELM_UPDATE_APP_ID }}
          github_app_private_key: ${{ secrets.CRUCIBLE_HELM_UPDATE_PRIVATE_KEY }}
          chart_file: charts/topomojo/charts/topomojo-api/Chart.yaml
          parent_chart_file: charts/topomojo/Chart.yaml
```

### Repository Configuration Checklist

1. **Create credentials** for pushing to `cmu-sei/helm-charts`.
   - Preferred: register a GitHub App with `contents:write` and `pull_request:write`, install it on `cmu-sei/helm-charts`, and store the app ID and private key as repository secrets (e.g., `CRUCIBLE_HELM_UPDATE_APP_ID`/`CRUCIBLE_HELM_UPDATE_PRIVATE_KEY`).
   - Alternative: use a fine-grained PAT limited to the Helm charts repo and store as `HELM_CHARTS_TOKEN`; pass it via the optional `helm_repo_token` input.
2. **Add the workflow** (example above) to the application repository.
   - Trigger on `release` with `types: [published]`.
3. **Reference the action** with a tagged version or commit SHA.
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
      - uses: cmu-sei/crucible-github-actions/actions/header@v1
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          use_block_comments: false
```

The action checks out the current branch, runs `header.py` to add missing headers, and automatically commits/pushes fixes when changes are detected.

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
| `enableQemu` |  | Set to `true` to enable QEMU for multi-arch builds. Defaults to `false`. |
| `preBuildCommands` |  | Optional shell commands to run before the Docker build (e.g., fetch artifacts). |

#### Required Secrets

- `DOCKERHUB_USERNAME`
- `DOCKERHUB_PASSWORD`

#### Example Usage

```yaml
jobs:
  docker:
    uses: cmu-sei/crucible-github-actions/.github/workflows/docker-build.yaml@v1
    with:
      imageName: cmusei/topomojo-api
      additionalTarget: worker
    secrets:
      DOCKERHUB_USERNAME: ${{ secrets.DOCKERHUB_USERNAME }}
      DOCKERHUB_PASSWORD: ${{ secrets.DOCKERHUB_PASSWORD }}
```

Callers inherit the workflow’s caching, tagging, and push logic without duplicating build boilerplate across repositories.
