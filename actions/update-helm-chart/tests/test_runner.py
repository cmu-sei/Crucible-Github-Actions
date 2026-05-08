import json
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
