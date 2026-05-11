"""Integration test for the update_helm_chart.py CLI wiring.

We can't mock git_io across a subprocess boundary, so this test initializes a
real git repo with the settings file tagged at two versions and invokes the
script end-to-end.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _run(cmd: list[str], cwd: Path) -> None:
    subprocess.run(cmd, cwd=cwd, check=True, capture_output=True)


def _init_git_repo_with_two_tags(
    repo: Path, settings_file: str, prev_content: str, new_content: str
) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _run(["git", "init", "-q", "-b", "main"], cwd=repo)
    _run(["git", "config", "user.email", "t@t"], cwd=repo)
    _run(["git", "config", "user.name", "t"], cwd=repo)
    target = repo / settings_file
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(prev_content)
    _run(["git", "add", "."], cwd=repo)
    _run(["git", "commit", "-q", "-m", "prev"], cwd=repo)
    _run(["git", "tag", "v2.5.0"], cwd=repo)
    target.write_text(new_content)
    _run(["git", "add", "."], cwd=repo)
    _run(["git", "commit", "-q", "-m", "new"], cwd=repo)
    _run(["git", "tag", "v2.6.0"], cwd=repo)


def test_cli_end_to_end_emits_settings_outputs(tmp_path: Path) -> None:
    app_repo = tmp_path / "app"
    settings_path = "appsettings.json"
    _init_git_repo_with_two_tags(
        app_repo,
        settings_path,
        prev_content=json.dumps({"A": ""}),
        new_content=json.dumps({"A": "", "B": True}),
    )

    helm_repo = tmp_path / "helm"
    chart_dir = helm_repo / "charts" / "player" / "charts" / "player-api"
    chart_dir.mkdir(parents=True)
    (chart_dir / "Chart.yaml").write_text(
        'apiVersion: v2\nname: player-api\nversion: 1.0.0\nappVersion: "2.5.0"\n'
    )
    (chart_dir / "values.yaml").write_text('env:\n  Existing: ""\n')

    gh_out = tmp_path / "gh_output"
    gh_out.write_text("")

    script = Path(__file__).resolve().parents[1] / "update_helm_chart.py"
    proc = subprocess.run(
        [
            sys.executable,
            str(script),
            "--helm-repo-dir", str(helm_repo),
            "--chart-file", "charts/player/charts/player-api/Chart.yaml",
            "--release-tag", "v2.6.0",
            "--app-name", "Player API",
            "--github-output", str(gh_out),
            "--settings-file", settings_path,
            "--settings-file-kind", "dotnet-appsettings",
            "--source-repo", "cmu-sei/Player.Api",
            "--app-repo-dir", str(app_repo),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr

    output = gh_out.read_text()
    assert "settings_changed=true" in output
    assert "settings_added=" in output
    assert "previous_release_tag=v2.5.0" in output

    values_text = (chart_dir / "values.yaml").read_text()
    assert "Existing" in values_text  # preserved
    assert "B" in values_text  # newly added
