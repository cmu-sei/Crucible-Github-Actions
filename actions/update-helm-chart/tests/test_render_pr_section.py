import json
import subprocess
import sys
from pathlib import Path


def test_render_pr_section_cli_emits_section():
    script = Path(__file__).resolve().parents[1] / "render_pr_section.py"
    proc = subprocess.run(
        [
            sys.executable,
            str(script),
            "--source-repo", "cmu-sei/Player.Api",
            "--release-tag", "v2.6.0",
            "--readme-path", "charts/player/README.md",
            "--added", json.dumps({"A__Key": "string"}),
            "--removed", json.dumps(["Old__Key"]),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    out = proc.stdout
    assert "## Settings changes to review" in out
    assert "`A__Key`" in out
    assert "`Old__Key`" in out


def test_render_pr_section_cli_empty_input_prints_nothing():
    script = Path(__file__).resolve().parents[1] / "render_pr_section.py"
    proc = subprocess.run(
        [
            sys.executable,
            str(script),
            "--source-repo", "cmu-sei/Player.Api",
            "--release-tag", "v2.6.0",
            "--readme-path", "",
            "--added", "{}",
            "--removed", "[]",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert proc.stdout.strip() == ""
