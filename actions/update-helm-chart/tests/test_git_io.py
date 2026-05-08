import subprocess

import pytest

from settings_sync import git_io


def test_list_tags_returns_tags_in_version_order(tmp_path, monkeypatch):
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(
            cmd, 0, stdout="v2.6.0\nv2.5.2\nv2.5.1\n", stderr=""
        )

    monkeypatch.setattr(git_io.subprocess, "run", fake_run)
    tags = git_io.list_tags(tmp_path)
    assert tags == ["v2.6.0", "v2.5.2", "v2.5.1"]
    assert calls == [["git", "-C", str(tmp_path), "tag", "--list", "--sort=-v:refname"]]


def test_previous_tag_returns_tag_before_target(tmp_path, monkeypatch):
    monkeypatch.setattr(
        git_io, "list_tags", lambda _: ["v2.6.0", "v2.5.2", "v2.5.1"]
    )
    assert git_io.previous_tag(tmp_path, "v2.6.0") == "v2.5.2"
    assert git_io.previous_tag(tmp_path, "v2.5.1") is None


def test_previous_tag_returns_none_when_target_not_found(tmp_path, monkeypatch):
    monkeypatch.setattr(git_io, "list_tags", lambda _: ["v2.5.2", "v2.5.1"])
    assert git_io.previous_tag(tmp_path, "v2.6.0") is None


def test_show_file_at_ref_returns_content(tmp_path, monkeypatch):
    def fake_run(cmd, **kwargs):
        assert cmd == ["git", "-C", str(tmp_path), "show", "v1.0.0:x.json"]
        return subprocess.CompletedProcess(cmd, 0, stdout='{"a": 1}', stderr="")

    monkeypatch.setattr(git_io.subprocess, "run", fake_run)
    assert git_io.show_file_at_ref(tmp_path, "v1.0.0", "x.json") == '{"a": 1}'


def test_show_file_at_ref_returns_none_when_file_missing(tmp_path, monkeypatch):
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd, 128, stdout="", stderr="fatal: path 'x.json' does not exist"
        )

    monkeypatch.setattr(git_io.subprocess, "run", fake_run)
    assert git_io.show_file_at_ref(tmp_path, "v1.0.0", "x.json") is None
