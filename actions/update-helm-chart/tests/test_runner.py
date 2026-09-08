import json
import textwrap
from pathlib import Path

import pytest

from settings_sync import runner
from settings_sync.flatten import LeafType


class _FakeGit:
    def __init__(self, tags, files):
        self._tags = tags
        self._files = files  # {(ref, path): content or None}

    def list_tags(self, _):
        return list(self._tags)

    def previous_tag(self, _, target):
        try:
            idx = self._tags.index(target)
        except ValueError:
            return None
        if idx + 1 >= len(self._tags):
            return None
        return self._tags[idx + 1]

    def show_file_at_ref(self, _, ref, path):
        return self._files.get((ref, path))


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_dotnet_end_to_end_updates_child_and_parent_and_returns_diff(
    tmp_path: Path, monkeypatch
):
    app_repo = tmp_path / "app"
    app_repo.mkdir()

    helm_repo = tmp_path / "helm"
    child_values = helm_repo / "charts" / "player" / "charts" / "player-api" / "values.yaml"
    parent_values = helm_repo / "charts" / "player" / "values.yaml"
    _write(child_values, "env:\n  Existing__Key: \"\"\n")
    _write(
        parent_values,
        "player-api:\n  env:\n    Existing__Key: \"\"\n",
    )

    prev_appsettings = json.dumps({"Existing": {"Key": ""}})
    new_appsettings = json.dumps(
        {"Existing": {"Key": ""}, "New": {"Key": "x", "Flag": True}}
    )

    fake = _FakeGit(
        tags=["v2.6.0", "v2.5.0"],
        files={
            ("v2.5.0", "Player.Api/appsettings.json"): prev_appsettings,
            ("v2.6.0", "Player.Api/appsettings.json"): new_appsettings,
        },
    )
    monkeypatch.setattr(runner, "git_io", fake)

    result = runner.run(
        app_repo_dir=app_repo,
        helm_repo_dir=helm_repo,
        settings_file="Player.Api/appsettings.json",
        settings_file_kind="dotnet-appsettings",
        chart_file="charts/player/charts/player-api/Chart.yaml",
        parent_chart_file="charts/player/Chart.yaml",
        release_tag="v2.6.0",
    )

    assert result.previous_tag == "v2.5.0"
    assert result.added == {
        "New__Key": LeafType.STRING,
        "New__Flag": LeafType.BOOL,
    }
    assert result.removed == []
    child_text = child_values.read_text()
    parent_text = parent_values.read_text()
    assert "New__Key" in child_text and "New__Flag" in child_text
    assert "New__Key" in parent_text and "New__Flag" in parent_text


def test_missing_new_file_raises(tmp_path: Path, monkeypatch):
    app_repo = tmp_path / "app"
    app_repo.mkdir()
    helm_repo = tmp_path / "helm"
    _write(
        helm_repo / "charts" / "player" / "charts" / "player-api" / "values.yaml",
        "env: {}\n",
    )

    fake = _FakeGit(
        tags=["v1.0.0"],
        files={("v1.0.0", "settings.json"): None},
    )
    monkeypatch.setattr(runner, "git_io", fake)

    with pytest.raises(runner.SettingsSyncError):
        runner.run(
            app_repo_dir=app_repo,
            helm_repo_dir=helm_repo,
            settings_file="settings.json",
            settings_file_kind="dotnet-appsettings",
            chart_file="charts/player/charts/player-api/Chart.yaml",
            parent_chart_file=None,
            release_tag="v1.0.0",
        )


def test_dotnet_conf_end_to_end_diffs_added_and_removed_keys(
    tmp_path: Path, monkeypatch
):
    app_repo = tmp_path / "app"
    app_repo.mkdir()

    helm_repo = tmp_path / "helm"
    child_values = (
        helm_repo / "charts" / "topomojo" / "charts" / "topomojo-api" / "values.yaml"
    )
    parent_values = helm_repo / "charts" / "topomojo" / "values.yaml"
    _write(child_values, "env:\n  Existing__Key: \"\"\n  Removed__Key: \"\"\n")
    _write(
        parent_values,
        "topomojo-api:\n  env:\n    Existing__Key: \"\"\n    Removed__Key: \"\"\n",
    )

    prev_conf = (
        "# Existing__Key =\n"
        "# Removed__Key =\n"
    )
    new_conf = (
        "####################\n"
        "## AppSettings\n"
        "####################\n"
        "# Existing__Key =\n"
        "# New__Key = topomojo-api\n"
        "# New__Flag = true\n"
    )

    fake = _FakeGit(
        tags=["v3.6.0", "v3.5.0"],
        files={
            ("v3.5.0", "src/TopoMojo.Api/appsettings.conf"): prev_conf,
            ("v3.6.0", "src/TopoMojo.Api/appsettings.conf"): new_conf,
        },
    )
    monkeypatch.setattr(runner, "git_io", fake)

    result = runner.run(
        app_repo_dir=app_repo,
        helm_repo_dir=helm_repo,
        settings_file="src/TopoMojo.Api/appsettings.conf",
        settings_file_kind="dotnet-conf",
        chart_file="charts/topomojo/charts/topomojo-api/Chart.yaml",
        parent_chart_file="charts/topomojo/Chart.yaml",
        release_tag="v3.6.0",
    )

    assert result.previous_tag == "v3.5.0"
    assert result.added == {
        "New__Key": LeafType.STRING,
        "New__Flag": LeafType.STRING,
    }
    assert result.removed == ["Removed__Key"]
    child_text = child_values.read_text()
    parent_text = parent_values.read_text()
    assert "New__Key" in child_text and "New__Flag" in child_text
    assert "Removed__Key" not in child_text
    assert "New__Key" in parent_text and "New__Flag" in parent_text
    assert "Removed__Key" not in parent_text


def test_dotnet_patch_leaves_untouched_formatting_byte_identical(
    tmp_path: Path, monkeypatch
):
    """Only the patched keys may change; everything else round-trips as-is.

    Guards two ruamel dump defaults that used to rewrite unrelated lines:
    block sequences dedenting flush with their parent key, and scalars past
    80 columns folding onto a continuation line. Either one desyncs the
    parent block from the child file and fails helm-charts' parent/child
    values-sync CI check.
    """
    app_repo = tmp_path / "app"
    app_repo.mkdir()

    helm_repo = tmp_path / "helm"
    child_values = (
        helm_repo / "charts" / "alloy" / "charts" / "alloy-api" / "values.yaml"
    )
    parent_values = helm_repo / "charts" / "alloy" / "values.yaml"

    child_src = textwrap.dedent(
        """\
        ingress:
          enabled: false
          hosts:
            - host: chart-example.local
              paths:
                - path: /(api|swagger|hubs)
                  pathType: ImplementationSpecific
          tls: []

        env:
          Authorization__AuthorizationScope: "alloy-api player-api caster-api steamfitter-api vm-api"
        """
    )
    parent_src = textwrap.dedent(
        """\
        alloy-api:
          ingress:
            enabled: false
            hosts:
              - host: chart-example.local
                paths:
                  - path: /(api|swagger|hubs)
                    pathType: ImplementationSpecific
            tls: []

          env:
            Authorization__AuthorizationScope: "alloy-api player-api caster-api steamfitter-api vm-api"
        """
    )
    _write(child_values, child_src)
    _write(parent_values, parent_src)

    prev_appsettings = json.dumps(
        {"Authorization": {"AuthorizationScope": "alloy-api"}}
    )
    new_appsettings = json.dumps(
        {
            "Authorization": {"AuthorizationScope": "alloy-api"},
            "Email": {"SmtpHost": ""},
        }
    )

    fake = _FakeGit(
        tags=["v3.7.0", "v3.6.0"],
        files={
            ("v3.6.0", "Alloy.Api/appsettings.json"): prev_appsettings,
            ("v3.7.0", "Alloy.Api/appsettings.json"): new_appsettings,
        },
    )
    monkeypatch.setattr(runner, "git_io", fake)

    runner.run(
        app_repo_dir=app_repo,
        helm_repo_dir=helm_repo,
        settings_file="Alloy.Api/appsettings.json",
        settings_file_kind="dotnet-appsettings",
        chart_file="charts/alloy/charts/alloy-api/Chart.yaml",
        parent_chart_file="charts/alloy/Chart.yaml",
        release_tag="v3.7.0",
    )

    assert child_values.read_text() == child_src + '  Email__SmtpHost: ""\n'
    assert parent_values.read_text() == parent_src + '    Email__SmtpHost: ""\n'


def test_dotnet_append_keeps_blank_line_after_parent_subchart_block(
    tmp_path: Path, monkeypatch
):
    """A blank line separating subchart blocks stays at the end of the block.

    ruamel hangs that blank line off the block's last key, so appending keys
    used to push it between the old and new keys and drop the separator before
    the next subchart — leaving the parent block one blank line off from the
    child file it must mirror.
    """
    app_repo = tmp_path / "app"
    app_repo.mkdir()

    helm_repo = tmp_path / "helm"
    child_values = (
        helm_repo
        / "charts"
        / "steamfitter"
        / "charts"
        / "steamfitter-api"
        / "values.yaml"
    )
    parent_values = helm_repo / "charts" / "steamfitter" / "values.yaml"

    child_src = textwrap.dedent(
        """\
        env:
          Existing__Key: ""

          # Optional: override the service name reported to collectors
          # OTEL_SERVICE_NAME: steamfitter-api
        """
    )
    parent_src = textwrap.dedent(
        """\
        steamfitter-api:
          env:
            Existing__Key: ""

            # Optional: override the service name reported to collectors
            # OTEL_SERVICE_NAME: steamfitter-api

        steamfitter-ui:
          env:
            APP_BASEHREF: /steamfitter
        """
    )
    _write(child_values, child_src)
    _write(parent_values, parent_src)

    fake = _FakeGit(
        tags=["3.10.0", "3.9.13"],
        files={
            ("3.9.13", "Steamfitter.Api/appsettings.json"): json.dumps(
                {"Existing": {"Key": ""}}
            ),
            ("3.10.0", "Steamfitter.Api/appsettings.json"): json.dumps(
                {"Existing": {"Key": ""}, "Email": {"SmtpHost": ""}}
            ),
        },
    )
    monkeypatch.setattr(runner, "git_io", fake)

    runner.run(
        app_repo_dir=app_repo,
        helm_repo_dir=helm_repo,
        settings_file="Steamfitter.Api/appsettings.json",
        settings_file_kind="dotnet-appsettings",
        chart_file="charts/steamfitter/charts/steamfitter-api/Chart.yaml",
        parent_chart_file="charts/steamfitter/Chart.yaml",
        release_tag="3.10.0",
    )

    assert child_values.read_text() == child_src + '  Email__SmtpHost: ""\n'
    assert parent_values.read_text() == textwrap.dedent(
        """\
        steamfitter-api:
          env:
            Existing__Key: ""

            # Optional: override the service name reported to collectors
            # OTEL_SERVICE_NAME: steamfitter-api
            Email__SmtpHost: ""

        steamfitter-ui:
          env:
            APP_BASEHREF: /steamfitter
        """
    )


def test_dotnet_append_keeps_dedented_trailing_comments_with_next_key(
    tmp_path: Path, monkeypatch
):
    """Comments introducing the next sibling key stay above that key.

    topomojo's env: block is followed by "## Create a seed data file ..."
    documenting `seedData:`. ruamel hangs those lines off the last env: key, so
    appending used to emit the new setting below them — reading as if it
    belonged to seedData. Comments indented with the env: keys keep their place.
    """
    app_repo = tmp_path / "app"
    app_repo.mkdir()

    helm_repo = tmp_path / "helm"
    child_values = (
        helm_repo / "charts" / "topomojo" / "charts" / "topomojo-api" / "values.yaml"
    )
    parent_values = helm_repo / "charts" / "topomojo" / "values.yaml"

    child_src = textwrap.dedent(
        """\
        env:
          Existing__Key: ""

          # Optional: override the service name reported to collectors
          # OTEL_SERVICE_NAME: topomojo-api

        ## Create a seed data file based on the contents of an existing secret
        ## or by values that support templating via the tpl function.
        seedData:
          existingSeedDataSecretKey: "seedData"
        """
    )
    parent_src = textwrap.dedent(
        """\
        topomojo-api:
          env:
            Existing__Key: ""

            # Optional: override the service name reported to collectors
            # OTEL_SERVICE_NAME: topomojo-api

          ## Create a seed data file based on the contents of an existing secret
          ## or by values that support templating via the tpl function.
          seedData:
            existingSeedDataSecretKey: "seedData"
        """
    )
    _write(child_values, child_src)
    _write(parent_values, parent_src)

    fake = _FakeGit(
        tags=["v3.6.0", "v3.5.0"],
        files={
            ("v3.5.0", "src/TopoMojo.Api/appsettings.conf"): "# Existing__Key =\n",
            ("v3.6.0", "src/TopoMojo.Api/appsettings.conf"): (
                "# Existing__Key =\n# New__Key =\n"
            ),
        },
    )
    monkeypatch.setattr(runner, "git_io", fake)

    runner.run(
        app_repo_dir=app_repo,
        helm_repo_dir=helm_repo,
        settings_file="src/TopoMojo.Api/appsettings.conf",
        settings_file_kind="dotnet-conf",
        chart_file="charts/topomojo/charts/topomojo-api/Chart.yaml",
        parent_chart_file="charts/topomojo/Chart.yaml",
        release_tag="v3.6.0",
    )

    assert child_values.read_text() == textwrap.dedent(
        """\
        env:
          Existing__Key: ""

          # Optional: override the service name reported to collectors
          # OTEL_SERVICE_NAME: topomojo-api
          New__Key: ""

        ## Create a seed data file based on the contents of an existing secret
        ## or by values that support templating via the tpl function.
        seedData:
          existingSeedDataSecretKey: "seedData"
        """
    )
    assert parent_values.read_text() == textwrap.dedent(
        """\
        topomojo-api:
          env:
            Existing__Key: ""

            # Optional: override the service name reported to collectors
            # OTEL_SERVICE_NAME: topomojo-api
            New__Key: ""

          ## Create a seed data file based on the contents of an existing secret
          ## or by values that support templating via the tpl function.
          seedData:
            existingSeedDataSecretKey: "seedData"
        """
    )


def test_no_previous_tag_treats_prev_as_empty(tmp_path: Path, monkeypatch):
    app_repo = tmp_path / "app"
    app_repo.mkdir()
    helm_repo = tmp_path / "helm"
    _write(
        helm_repo / "charts" / "player" / "charts" / "player-api" / "values.yaml",
        "env: {}\n",
    )

    fake = _FakeGit(
        tags=["v1.0.0"],
        files={("v1.0.0", "s.json"): json.dumps({"A": "", "B": False})},
    )
    monkeypatch.setattr(runner, "git_io", fake)

    result = runner.run(
        app_repo_dir=app_repo,
        helm_repo_dir=helm_repo,
        settings_file="s.json",
        settings_file_kind="dotnet-appsettings",
        chart_file="charts/player/charts/player-api/Chart.yaml",
        parent_chart_file=None,
        release_tag="v1.0.0",
    )
    assert result.previous_tag is None
    assert set(result.added.keys()) == {"A", "B"}
