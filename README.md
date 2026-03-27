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

#### Outputs

- `new_app_version` – parsed version string, e.g. `2.5.2`
- `release_type` – computed release type (`major`/`minor`/`patch`)
- `new_chart_version` – bumped chart version
- `parent_chart_update` – JSON object describing the parent chart bump
- `chart_modified` – `true` when an update was required
- `branch_name` – suggested feature branch for the PR
- `has_changes` – `true` when any files were modified

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
